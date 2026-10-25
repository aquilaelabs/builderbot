"""The session half (roadmap #24): Claude's sessions on this node, their terminals, tokens, firewall and upkeep."""
import contextlib
import glob
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import threading
import time
from .jobs import pump
from .base import (
    AGENT_INSTALLS,
    AGENT_PREFIXES,
    AGENTS_DIR,
    CLAUDE_INSTALL,
    CLAUDE_DIR,
    DOCKER_BIN,
    FIREWALL_CMD,
    FIREWALL_EVERY_S,
    IDLE_UNIT,
    NFT_BIN,
    RESPAWNABLE,
    SESSION,
    ROOT_BUNDLE_DIR,
    SESSION_BIN,
    SESSION_BIND,
    SESSION_NFT,
    SCREEN_PORT,
    SHARE,
    _probe,
    _run,
    log,
    log_once,
)
from .stores import noexec, tc_root
from .backends import _have
from .toolchains import sdk_env
from .census import controller_ip, network_now



def _pin_release(pin_dir, cmd, root):
    """Pin an agent the vendor installs as a release folder (Codex CLI's:
    bin/codex, bin/codex-code-mode-host and codex-resources beside them): the
    whole folder copied root-owned to <pin_dir>/release, swapped in whole,
    and the command and each helper beside it a link into it, so the agent
    finds its helpers where it looks, beside its own executable. Copying the
    one binary left Codex 0.163 without codex-code-mode-host, and every
    command a session ran failed (B247)."""
    new, rel, old = (os.path.join(pin_dir, n) for n in (".release.new", "release", ".release.old"))
    shutil.rmtree(new, ignore_errors=True)
    shutil.copytree(root, new, symlinks=True)
    for d, dirs, files in os.walk(new):
        for n in dirs + files:
            with contextlib.suppress(OSError):
                os.lchown(os.path.join(d, n), 0, 0)
    os.lchown(new, 0, 0)
    os.chmod(new, 0o755)
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(rel) and not os.path.islink(rel):
        os.replace(rel, old)
    os.replace(new, rel)
    shutil.rmtree(old, ignore_errors=True)
    for exe in sorted(os.listdir(os.path.join(rel, "bin"))):
        if not (exe == cmd or exe.startswith(cmd + "-")):
            continue
        link, tmp = os.path.join(pin_dir, exe), os.path.join(pin_dir, exe + ".new")
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        os.symlink(os.path.join("release", "bin", exe), tmp)
        os.replace(tmp, link)

def _release_root(exe, src, home):
    """The vendor's release folder to pin whole, or "" for one binary: only
    where the command is a link into a folder of the vendor's own (Codex's
    ~/.local/bin/codex into ~/.codex/packages/.../bin). A binary that IS the
    file in ~/.local/bin is one binary, and its "release folder" was the
    account's whole ~/.local: Copilot's pin copied a gigabyte of it, its
    share/ and state/ among it, root-owned and readable by every account
    (B262)."""
    if os.path.basename(os.path.dirname(src)) != "bin" or os.path.realpath(exe) != src \
            or os.path.abspath(exe) == src:
        return ""
    root = os.path.dirname(os.path.dirname(src))
    homes = {os.path.realpath(home), os.path.realpath(os.path.join(home, ".local"))}
    return "" if os.path.realpath(root) in homes or root in ("/", "/usr", "/usr/local") else root


class SessionWatch:
    """The node's sessions reported the moment one changes (a session
    starting, ending, a Claude pane turning from waiting to working), so
    the dot beside a name on a project's row follows within seconds (the
    operator, 25 Sep). The heartbeat carries the same rows on its own turn,
    every poll; this is the edge in between."""

    def __init__(self, agent):
        self.agent = agent
        self.last = None

    def start(self):
        threading.Thread(target=self.run, name="sessions", daemon=True).start()

    def run(self):
        while True:
            try:
                self.step()
            except Exception as e:                                # noqa: BLE001 (the loop must outlive one bad step; the journal has it)
                log_once("sessions-step", f"sessions: {type(e).__name__}: {e}")
            time.sleep(2)

    def step(self):
        if not self.agent.session_up:
            return
        rows = self.agent.sessions_now() or []
        key = sorted((r.get("name", ""), r.get("title", "")) for r in rows)
        if key == self.last:
            return
        if self.last is not None:
            st, r = self.agent.ctl.call("sessions", {"sessions": rows}, timeout=15)
            if st != 200:
                return                      # said again on the next change
        self.last = key


class SessionsMixin:
    """Agent's session methods: one of the parts class Agent (agent.py) is made of."""

    def keep_session_tokens(self, rows):
        """Store each live session's fresh token where that session reads it.

        Handed to the BUNDLE's own `bb token keep` rather than written here,
        and as the session account rather than the job one. Both halves of
        "where does this token go" already live in bb: which home this
        BuilderBot account has on this machine (user_home) and what the cache
        file is called (bbapi.keep_token). A copy of either here would be a
        second thing to keep in step with the controller, which is the fault
        claudegrant.py was written to stop repeating.

        Best effort and quiet: a token that could not be kept is a token that
        expires on schedule, which is what happened before this existed.
        """
        if not isinstance(rows, list) or not rows:
            return
        who_name = self.session_account()
        if not who_name:
            return
        # The copy already unpacked for this node's sessions, never a fetch:
        # this runs on the heartbeat, and `bundle()` pulls from the controller
        # every time it is called. `.bb/current/scripts` is what a shell here
        # puts on its PATH, so it is the same bb the session itself runs. It
        # looked for `.bb/current/bb`, which no bundle has, found nothing and
        # returned, so no idle session's token was ever refreshed and each
        # ran out twelve hours after its last call (B335).
        store = tc_root(self.state)
        bb = os.path.join(store, ".bb", "current", "scripts", "bb") if store else ""
        if not bb or not os.access(bb, os.X_OK):
            self.keep_said("bundle", f"no bundle bb at {bb or '(no toolchain store)'}, so no idle "
                                     "session's token is refreshed")
            return
        env0 = dict(os.environ)
        try:
            who = self.as_user(env0, who_name)
        except RuntimeError as e:
            self.keep_said("account", str(e))
            return
        for row in rows[:64]:
            project = str((row or {}).get("project") or "")
            uid = str((row or {}).get("uid") or "")
            token = str((row or {}).get("token") or "")
            if not project or not token or "/" in project:
                continue
            env = dict(env0)
            env.update({"BUILDER_HOME": env.get("HOME", ""), "BB_ACCOUNT_UID": uid,
                        "BB_PROJECT": project, "BB_TOKEN": token,
                        "BUILDERBOT_ROLE": "node"})
            # Kept by the account's own user where its home is that user's
            # (R125): the session account cannot write there any more.
            run_bb, run_who = bb, who
            dropper = getattr(self, "drop_for", None)
            if dropper:
                with contextlib.suppress(RuntimeError):
                    w, base, root_bb = dropper(env, uid)
                    if root_bb:
                        run_bb, run_who = os.path.join(root_bb, "scripts", "bb"), w
                        env["BUILDER_HOME"] = base
            try:
                p = subprocess.run([run_bb, "token", "keep"],
                                   env=env, capture_output=True, text=True, timeout=20, check=False,
                                   **({"user": run_who["user"], "group": run_who["group"],
                                       "extra_groups": run_who["extra_groups"]} if run_who else {}))
            except (OSError, subprocess.SubprocessError) as e:
                self.keep_said(f"{uid}/{project}", f"bb token keep did not run: {e}")
                return
            if p.returncode:
                said = ((p.stderr or "") + (p.stdout or "")).strip().splitlines()
                self.keep_said(f"{uid}/{project}", f"bb token keep failed (exit {p.returncode}): "
                                                    + (said[-1][-300:] if said else "it said nothing"))
            else:
                self.__dict__["_keep_ok"] = int(time.time())

    def keep_said(self, key, msg):
        """Log why an idle session's token was not refreshed, once an hour per
        session: this was silent, and a session's token then ran out twelve
        hours after its last call with nothing on the node saying why (B419)."""
        now = time.monotonic()
        seen = self.__dict__.setdefault("_keep_said", {})
        if now - seen.get(key, -1e9) < 3600:
            return
        seen[key] = now
        log(f"session tokens: {msg}")
        # ...and kept for the controller, which the hello carries: the log
        # above is the node's own journal, which nothing on the dashboard or
        # in a session reads, so in practice it was still silent (B419).
        recent = self.__dict__.setdefault("_keep_recent", [])
        recent.append({"at": int(time.time()), "key": str(key)[:80], "msg": str(msg)[:300]})
        del recent[:-8]

    def keep_report(self):
        """What the hello tells the controller about the session tokens kept
        here: the last few complaints of two days, and when one was last kept."""
        now = int(time.time())
        said = [x for x in self.__dict__.get("_keep_recent", []) if now - x["at"] < 48 * 3600]
        tw = self.__dict__.get("_tokenwatch")
        return {"said": said, "ok": int(self.__dict__.get("_keep_ok") or 0),
                # Who opened an account's token here that was neither it nor
                # the agent (R125 step 6), for the controller's audit.
                "reads": tw.report() if tw else []}

    # -- the session half (roadmap #24) ---------------------------------------
    def session_account(self):
        """The account sessions run as, or "" when this node runs none: the
        one the provisioner made when this process is root, and this
        process's own when it is not (a container node runs the agent as
        the image's builder and sessions as the same)."""
        if os.geteuid() == 0:
            return self.state.get("session_user") or ""
        import pwd
        # A uid with no passwd entry (a container started as a bare number,
        # OpenShift's random uids) has no name to look up: the agent died on
        # the KeyError after its first hello and never dialed in again (diag
        # report #119). Its own name from the environment, then the number.
        try:
            return pwd.getpwuid(os.geteuid()).pw_name
        except KeyError:
            return os.environ.get("USER") or str(os.geteuid())

    def session_env(self, into):
        """What every terminal on this node inherits: this
        node's toolchains (sdk_env), the bundle's scripts and the account's
        own bin directories on PATH, the role, and how to reach the
        controller: the URL and the certificate pin the agent enrolled
        with, never its token. bb's relayed verbs carry the session's own
        token, which rides in on the terminal's URL."""
        env = dict(sdk_env(self.state))
        who = self.as_user(env, self.session_account())
        if not who:
            env.update({"HOME": os.path.expanduser("~"), "USER": self.session_account(),
                        "LOGNAME": self.session_account()})
        home = env["HOME"]
        # The SYMLINK on PATH, not the digest it points at (bug #66). A new
        # bundle only reaches terminals opened after it: a tmux
        # session's shell was started whenever it was started and keeps the
        # PATH it was given, so a session that has been open since before an
        # update went on running the bundle it began with. What that looks
        # like is a typo (`bb tests` printing bb's usage on a node whose
        # controller has the verb) rather than a machine that is behind.
        #
        # Through `current`, every bb invocation in every shell, however old,
        # runs whatever was delivered last. The name is resolved at exec, so
        # there is nothing to restart and nothing to keep in step; `into` is
        # still the resolved path everywhere else, because the census has to
        # report the digest actually running rather than a symlink.
        store = tc_root(self.state)
        link = os.path.join(store, ".bb", "current") if store else ""
        bbdir = link if link and os.path.isdir(link) else into
        # The pinned Claude Code ahead of the account's own bin (claude_update):
        # root-owned, so `claude update` typed in a session changes nothing
        # that runs here, and the auto-updater is off (bb-tty).
        pinned = [CLAUDE_DIR] if os.access(os.path.join(CLAUDE_DIR, "claude"), os.X_OK) else []
        # ...and each other coding agent's pinned copy the same way (R95).
        pinned += [os.path.join(AGENTS_DIR, s["id"]) for s in AGENT_INSTALLS.values()
                   if os.access(os.path.join(AGENTS_DIR, s["id"], s["command"]), os.X_OK)]
        env["PATH"] = ":".join([os.path.join(bbdir, "scripts")] + pinned
                               + [os.path.join(home, ".local", "bin"),
                                  os.path.join(home, ".npm-global", "bin"), env["PATH"]])
        # AVDs under the account's own ~/.android rather than the data store,
        # which the job account owns: a session's `bb emu create` has to be
        # able to write where its emulator keeps state.
        env.pop("ANDROID_AVD_HOME", None)
        env.update({"BUILDER_HOME": home, "BUILDERBOT_ROLE": "node",
                    "BB_CONTROLLER": self.ctl.url, "BB_CONTROLLER_PIN": self.state.get("pin", ""),
                    "BB_NODE": self.state.get("name") or "", "BUILDERBOT_NODE": self.state.get("node_id", ""),
                    "WORKSPACE": SHARE, "LANG": "C.UTF-8"})
        return env, who

    def session_bind(self):
        if SESSION_BIND:
            return SESSION_BIND
        # A node behind a tunnel (R161) is reached at its address there,
        # and only there: the session ports listen on nothing else.
        t = self.state.get("tunnel") if isinstance(self.state.get("tunnel"), dict) else {}
        if t.get("addr"):
            return str(t["addr"])
        for a in (network_now().get("addresses") or []):
            if ":" not in a:
                return a.split("/")[0]
        return "0.0.0.0"

    def session_start(self, into):
        """The session half (roadmap #24): what a terminal here runs, bb-tty
        from the bundle as the session account (or through bb-session tty as
        the account's own user, R125), recorded for the screen relay's
        terminal server (term.py), which opens one for each signed /term the
        controller sends. Nothing is started: there is no process to keep up
        and no port of its own, only the relay's."""
        self.session_stop()
        bbtty = os.path.join(into, "scripts", "dashboard", "bb-tty")
        user = self.session_account()
        if not user or not os.path.isfile(bbtty):
            SESSION.update(up=False, user=user, bundle=self.session_bundle,
                           why="no session account" if not user else "the bundle carries no bb-tty")
            return
        env, who = self.session_env(into)
        bind = self.session_bind()
        self.session_bound = bind
        self.session_stale = ""
        # Where accounts are their own users (R125) a terminal starts
        # through bb-session tty, which asks the controller whose it is and
        # runs as that account from the root-owned bundle.
        mine = getattr(self, "account_users_ready", None)
        if mine and mine():
            self.tty_env_write()
            rw, ro = ["sudo", "-n", SESSION_BIN, "tty"], ["sudo", "-n", SESSION_BIN, "tty-ro"]
        else:
            rw, ro = [bbtty], [bbtty]
        cwd = env["HOME"] if os.path.isdir(env["HOME"]) else "/"
        # The read-only kind is told so: bb-tty then says where the sign-in
        # happens instead of prompting for a code nobody can type into it
        # (B137).
        self.term_kinds = {"rw": {"argv": rw, "env": dict(env), "who": who, "cwd": cwd},
                           "ro": {"argv": ro, "env": dict(env, BB_TTY_RO="1"), "who": who, "cwd": cwd}}
        self.session_up = True
        SESSION.update(up=True, user=user, home=env["HOME"], bind=bind, bundle=self.session_bundle, why="",
                       term=True, screen=SCREEN_PORT)
        log(f"sessions: terminals open as {user}, bb {self.session_bundle[7:19]}")
        self.ctr_start(bbtty)

    def ctr_start(self, bbtty):
        """The container terminal (R218 step 4): a shell inside a container
        and nothing else, as the docker account, which jobs already run as
        and the session account is kept apart from (that one is in no docker
        group: docker is root on the machine). bb-tty under BB_TTY_CTR opens
        only a ctr: terminal the controller's grant names, and only docker
        exec into that one running container. One that cannot be set up
        leaves ctr false with why, and the sessions as they are."""
        user = self.state.get("user") or ""
        env = dict(sdk_env(self.state))
        try:
            who = self.as_user(env, user)
        except RuntimeError as e:
            SESSION.update(ctr=False, ctr_why=str(e)[:120])
            return
        if not who:
            env["HOME"] = os.path.expanduser("~")
        store = tc_root(self.state)
        link = os.path.join(store, ".bb", "current") if store else ""
        bbdir = link if link and os.path.isdir(link) else os.path.dirname(os.path.dirname(os.path.dirname(bbtty)))
        env["PATH"] = os.path.join(bbdir, "scripts") + ":" + env["PATH"]
        env.update({"BUILDERBOT_ROLE": "node", "BB_CONTROLLER": self.ctl.url,
                    "BB_CONTROLLER_PIN": self.state.get("pin", ""), "BB_NODE": self.state.get("name") or "",
                    "BUILDERBOT_NODE": self.state.get("node_id", ""), "LANG": "C.UTF-8", "BB_TTY_CTR": "1"})
        self.term_kinds = dict(getattr(self, "term_kinds", None) or {},
                               ctr={"argv": [bbtty], "env": dict(env), "who": who,
                                    "cwd": env["HOME"] if os.path.isdir(env["HOME"]) else "/"})
        SESSION.update(ctr=True, ctr_why="")

    def session_stop(self):
        self.session_up = False
        self.term_kinds = {}

    def session_try(self, digest=None):
        """session_refresh, never fatal: the session half must not take the
        job half down with it: a toolchain store this process cannot write
        is a node with no sessions, not a node with no agent."""
        # A hosting-only node runs no sessions and keeps no bb (the
        # controller's flag, said in every hello).
        if self.state.get("host_only"):
            SESSION.update(up=False, bundle="",
                           why="this node hosts containers only, so it runs no sessions")
            return
        try:
            self.session_refresh(digest)
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            SESSION.update(up=False, user=self.session_account(),
                           bundle="", why=f"{e}"[:120])
            log(f"sessions: not started: {e}")

    def session_refresh(self, digest=None):
        """The bundle the controller ships against the one the terminals run
        from: fetched and swapped in when they differ, and at the start of
        this process (no digest to compare, since the fetch answers with one),
        which is when sessions start."""
        if self.session_up and (digest is None or digest == self.session_bundle):
            self.bundle_back()
            return
        if not self.session_account():
            SESSION.update(up=False, user="", bundle="",
                           why="no session account; provision with --session-user")
            return
        env = {}
        who = self.as_user(env, self.session_account())
        into = self.bundle(None, who)
        if not into:
            return
        self.session_bundle = self.session_digest or digest
        self.session_tried = time.time()
        self.session_start(into)

    BUNDLE_BACK_EVERY = 60

    def bundle_back(self):
        """Fetch the bundle again when `.bb/current` is gone from the store
        while sessions run: the same digest, so nothing restarts, but every
        heartbeat task that runs bb (an idle session's token, the logins
        list, the census's versions) and every shell's PATH need it there.
        A store emptied by hand took it (the operator, 12 Oct: "no bundle bb
        at .../.bb/current/scripts/bb, so no idle session's token is
        refreshed"), and only the next job or session start fetched it.
        Once a minute at most while it is missing."""
        store = tc_root(self.state)
        bb = os.path.join(store, ".bb", "current", "scripts", "bb") if store else ""
        if not store or os.access(bb, os.X_OK):
            return
        # There and unable to run: a store mounted noexec. Fetching again
        # changes nothing, and saying it was gone was wrong (every terminal
        # closed at once, with the log blaming a missing bundle). Said once;
        # the census carries it to the node's page.
        if os.path.exists(bb) and noexec(store):
            if not getattr(self, "_noexec_said", False):
                log(f"sessions: the toolchain store {store} is mounted noexec, so bb and every terminal "
                    "cannot run from it; remount it with exec")
                self._noexec_said = True
            return
        now = time.time()
        if now - getattr(self, "_bundle_back_at", 0) < self.BUNDLE_BACK_EVERY:
            return
        self._bundle_back_at = now
        who = self.as_user({}, self.session_account()) if self.session_account() else None
        if self.bundle(None, who):
            log("sessions: the bundle was gone from the toolchain store; fetched it again")

    def _tmux(self, argv, timeout=10):
        """tmux on the server a session is on. Where accounts are their own
        users (R125) each runs its own: a command aimed at an account's
        session (its u_X~ name) goes to that account's server, and to the
        session account's for one started before the switch; a listing is
        every server's, joined. Otherwise the session account's alone."""
        users = self._tmux_users()
        if len(users) > 1:
            t = argv[argv.index("-t") + 1] if "-t" in argv and argv.index("-t") + 1 < len(argv) else ""
            m = re.match(r"=?(u_[0-9a-f]{8})~", t)
            if m:
                own = "bbu-" + m.group(1)[2:]
                if own in users:
                    got = self._tmux_as(own, argv, timeout, quiet=True)
                    if got is not None:
                        return got
                return self._tmux_as(users[0], argv, timeout)
            if not t:
                outs = [self._tmux_as(u, argv, timeout, quiet=i > 0) for i, u in enumerate(users)]
                got = [o for o in outs if o is not None]
                return "".join(got) if got else None
        return self._tmux_as(users[0], argv, timeout)

    def _tmux_users(self):
        """Whose tmux servers there are: the session account's, and each
        account's own user where accounts are (R125)."""
        users = [self.session_account()]
        # Every account user there is, the setting on or not: one turned off
        # still has its sessions running until they end (R125).
        if os.geteuid() == 0:
            users += sorted(p.pw_name for p in pwd.getpwall() if p.pw_name.startswith("bbu-"))
        return users

    def _tmux_as(self, user, argv, timeout=10, quiet=False):
        """tmux as one account: its server, its sessions. The environment
        is that account's own (HOME and the default socket path follow the
        uid), not this process's: the agent under systemd has no TMUX_TMPDIR
        and must not inherit one from a test."""
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
               "LANG": "C.UTF-8"}
        for k in ("TMUX_TMPDIR",):
            if k in os.environ:
                env[k] = os.environ[k]
        who = self.as_user(env, user)
        if not who:
            env["HOME"] = os.path.expanduser("~")
        try:
            p = subprocess.run(["tmux", *argv], env=env, capture_output=True, text=True,
                               timeout=timeout, check=False, **who)
        except (OSError, subprocess.SubprocessError, RuntimeError) as e:
            log(f"sessions: tmux {argv[0]}: {e}")
            return None
        if p.returncode != 0 and not quiet and argv[0] != "list-panes" and "no server running" not in (p.stderr or ""):
            # No server up is the normal state of a node nobody has opened a
            # terminal on, whichever verb met it: list-sessions from the idle
            # reaper said so once a minute, all day. Anything else failing is
            # worth a line, once an hour while it keeps failing the same way.
            log_once(f"tmux {argv[0]}", f"sessions: tmux {' '.join(argv)}: {(p.stderr or '').strip()[:120]}")
        return p.stdout if p.returncode == 0 else None

    def sessions_now(self):
        """The session account's tmux sessions, for the heartbeat: name,
        attached, the active pane's directory and title. Empty when the
        server is not up, which is the normal state of a node nobody has
        opened a terminal on yet."""
        # When each session started, too: a toolchain installed after that
        # is not on its PATH until it is reopened, and the Tools tab says so
        # on the row. Before the title, which is free text and goes last.
        out = self._tmux(["list-panes", "-a", "-F",
                          "#{session_name}\t#{pane_active}\t#{session_attached}\t"
                          "#{pane_current_path}\t#{session_created}\t#{pane_title}"])
        rows = []
        for line in (out or "").splitlines():
            parts = line.split("\t", 5)
            if len(parts) == 6 and parts[1] == "1":
                rows.append({"name": parts[0], "attached": parts[2].strip() not in ("", "0"),
                             "cwd": parts[3], "created": int(parts[4]) if parts[4].isdigit() else 0,
                             "title": parts[5]})
        return rows[:64]

    # What each account on this machine is signed in to Claude as, refreshed
    # at most this often. It is two file reads per account and no subprocess
    # per account, but it is also news that changes about once a week, and
    # the heartbeat runs every poll.
    LOGINS_EVERY = 300

    def logins_now(self):
        """Which Anthropic account each BuilderBot account here is signed in
        as, or None when there is nothing new to say (B104).

        The controller holds no credential and learns of a login only when
        something on the machine tells it. That used to be a session's hook
        and nothing else, so a node signed in with no session running stayed
        "not signed in" on the card until somebody opened one, and after a
        sign-out the way back needed the very thing the card was refusing.
        The agent is already here and already tends these homes, so it says
        so on the heartbeat.

        Asked of the BUNDLE rather than read here: where an account lives on
        this machine is bb's answer, and a second copy of that rule in this
        file is how the two would drift. `.bb/current` is the copy a shell on
        this node already runs, so this costs no fetch.
        """
        now = time.time()
        if now - getattr(self, "_logins_at", 0) < self.LOGINS_EVERY:
            return None
        self._logins_at = now
        store = tc_root(self.state)
        bb = os.path.join(store, ".bb", "current", "scripts", "bb") if store else ""
        if not (bb and os.path.isfile(bb)):
            return None
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
               "LANG": "C.UTF-8"}
        try:
            who = self.as_user(env, self.session_account())
        except RuntimeError:
            return None
        if not who:
            return None
        # Where accounts own their homes (R125) the session account can read
        # none of them: read as root, and only from the root-owned bundle,
        # which nothing outside a view can change.
        lister = os.path.join(ROOT_BUNDLE_DIR, "current", "scripts", "lib", "login-list.py")
        if any(u.startswith("bbu-") for u in self._tmux_users()) and os.path.isfile(lister):
            try:
                p = subprocess.run([sys.executable, "-I", lister], env={
                    "PATH": env["PATH"], "LANG": "C.UTF-8",
                    "BB_USERS_DIR": os.path.join(env.get("HOME", ""), "users")},
                    capture_output=True, text=True, timeout=20, check=False)
                rows = json.loads(p.stdout) if p.returncode == 0 else None
            except (OSError, subprocess.SubprocessError, ValueError):
                return None
            return rows[:64] if isinstance(rows, list) else None
        try:
            p = subprocess.run(["bash", bb, "login", "--list"], env=env,
                               capture_output=True, text=True, timeout=20,
                               check=False, **who)
            rows = json.loads(p.stdout) if p.returncode == 0 else None
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        return rows[:64] if isinstance(rows, list) else None

    def kill_sessions(self, names):
        for name in names:
            log(f"sessions: ending {name} (asked from the dashboard)")
            self._tmux(["kill-session", "-t", "=" + name])

    def tell(self, job, spec):
        """One line into a Claude session here, and Enter only if it
        visibly arrived: the notebook's Send to Claude, run where the pane
        is. The controller's notify.tell does exactly this in its own tmux
        and cannot in this one, so the rule is repeated rather than
        approximated: a session waiting at its prompt echoes what is typed
        and a permission dialog swallows it, and pressing Enter into a
        dialog blind is the one thing this must never do. Exit 0 sent, 3
        typed but left unsent for a person to look at, 2 no such session."""
        sess = str(spec.get("session") or "")
        text = " ".join(str(spec.get("text") or "").split())
        if not sess or not text:
            job.say("nothing to say, or nobody to say it to\n")
            return "failed", 2
        names = {str((r or {}).get("name") or "") for r in (self.sessions_now() or [])}
        if sess not in names:
            job.say(f"no session called {sess} is running here\n")
            return "failed", 2
        # A long line lands in claude's box folded into "[Pasted text #1]"
        # (the TUI reads a burst of typed characters as a paste), so the
        # placeholder counts as the echo; whitespace is collapsed because
        # the box wraps a long line at word boundaries with an indent.
        mark = " ".join(text[:40].split())
        def screen():
            return " ".join((self._tmux(["capture-pane", "-p", "-J", "-t", sess]) or "").split())

        def seen(flat=None):
            flat = screen() if flat is None else flat
            return flat.count(mark) + flat.count("[Pasted text")
        # Counted once the pane is still, as notify.tell does: a pane still
        # drawing the last send's output (a shell's "command not found"
        # repeats the line) put a copy on screen after the count, which read
        # as this line's echo, and Enter went to a box that never took it
        # (B389). At most a second.
        flat = screen()
        for _ in range(4):
            time.sleep(0.25)
            again = screen()
            if again == flat:
                break
            flat = again
        was = seen(flat)
        if self._tmux(["send-keys", "-t", sess, "-l", "--", text]) is None:
            job.say("tmux would not take the line\n")
            return "failed", 1
        # The same look-window as the controller's (notify.LOOKS): eight
        # quarter-second looks, one more per 120 characters, since a TUI
        # re-renders as it takes input and a long line is not on screen
        # inside a short one. Two looks left the bell's Resume unsent in an
        # idle session that took a second to draw it (B774); the first look
        # that sees it sends, so a quick one waits no longer.
        for _ in range(8 + len(text) // 120):
            time.sleep(0.25)
            if seen() > was:
                if self._tmux(["send-keys", "-t", sess, "Enter"]) is None:
                    job.say("the line is in the box but Enter did not go\n")
                    return "failed", 1
                job.say(f"sent to {sess}\n")
                return "succeeded", 0
        job.say(f"typed into {sess} but not sent: the pane did not echo it, so something "
                "other than the prompt has the keyboard\n")
        return "failed", 3

    def tmux_ops(self, ops):
        """Keys into a session here, as the dashboard sends them into its
        own tmux (server._say, _send). Only send-keys and copy-mode, only at
        a session by exact name: the controller composed the argv, and this
        node still decides what it will run. `respawn` is the one decision
        made here, because only this side can find the launcher."""
        for op in ops[:16]:
            if not isinstance(op, dict):
                continue
            sess = str(op.get("session") or "")
            if not sess:
                continue
            # A bare name, not `=name`: these take a target-PANE, and the
            # exact-match prefix is target-session syntax, measured as
            # "can't find pane: =…". tmux tries the exact name first anyway.
            # Restart this session's own process onto its launcher, which is
            # what the dashboard asks for when a project's model, effort or
            # permission rung changes. `-k` replaces the pane's process and
            # keeps the tmux session, so every browser attached to it stays
            # where it is; `--respawn` tells the launcher to resume the newest
            # transcript, so the conversation continues rather than restarting.
            #
            # The launcher's PATH is read off the pane rather than composed
            # here. On a node the session belongs to one of several accounts
            # and the file is in that account's home, which this side would
            # have to reconstruct, while tmux already knows, because bb-tty
            # starts the pane on that script and nothing else. Hence the
            # claude-run- name, and hence checking it before running it: the
            # controller asked for a respawn, it did not say what to execute.
            if op.get("respawn"):
                cmd = (self._tmux(["display-message", "-p", "-t", sess,
                                   "#{pane_start_command}"]) or "").strip()
                if re.fullmatch(RESPAWNABLE, cmd):
                    # Word by word. tmux runs more than one argument as the
                    # program and its arguments, so the view's launcher line
                    # handed over whole names a program nobody has, and the
                    # pane dies with its session. The pattern admits no
                    # quoting, so a space is exactly a word boundary.
                    self._tmux(["respawn-pane", "-k", "-t", sess, *cmd.split(" "), "--respawn"])
                continue
            argv = [str(a) for a in (op.get("argv") or [])][:12]
            if argv[:1] not in (["send-keys"], ["copy-mode"]) or "-t" not in argv:
                continue
            # The target is this op's session, whatever the argv says.
            argv[argv.index("-t") + 1] = sess
            # A key for the program leaves copy mode first, as the
            # dashboard's own tmux does (macros.py): scrolled back, an arrow
            # moved tmux's cursor and the program heard nothing.
            if argv[0] == "send-keys" and "-X" not in argv \
                    and (self._tmux(["display-message", "-p", "-t", sess, "#{pane_in_mode}"]) or "").strip() == "1":
                self._tmux(["send-keys", "-t", sess, "-X", "cancel"])
            self._tmux(argv)

    def agent_update(self, job, spec):
        """Install, update or remove one of the other coding agents for the
        SESSION account (R95 step 2). Which agent and how is AGENT_INSTALLS's
        row for this job's type, never anything the controller sent."""
        how = AGENT_INSTALLS.get(job.job.get("type") or "")
        if not how:
            job.say("refused: no coding agent is installed by this job\n")
            return "failed", 78
        return self.agent_install(job, spec, how)

    def claude_update(self, job, spec):
        """Install the current Claude Code for the SESSION account, and pin it
        (claudecode.py on the controller). Queued by an administrator's press
        and by nothing else; the controller ended the Claude sessions here
        before queueing it, since the binary is swapped under nothing."""
        return self.agent_install(job, spec, CLAUDE_INSTALL)

    def agent_install(self, job, spec, how):
        """One coding agent installed, updated or removed for the SESSION
        account, from its row (AGENT_INSTALLS, CLAUDE_INSTALL): one path for
        every agent (R95 step 18).

        The vendor's installer runs as the session account, into its home,
        the way the provisioner first installed it. Then, where this agent
        is root, the binary is copied into the row's pin folder, root-owned,
        which the session's PATH reads first: that copy is what a session
        runs and what the account cannot write, so an update typed in a
        session changes nothing that runs. A guest node, where the agent is
        not root, keeps the account's own copy and says so."""
        product, cmd = how["product"], how["command"]
        who_name = self.session_account()
        env = dict(sdk_env(self.state))
        try:
            who = self.as_user(env, who_name)
        except RuntimeError as e:
            job.say(f"refused: {e}\n")
            return "failed", 78
        if not who_name:
            job.say(f"refused: this node reports no session account, so there is nowhere for {product} to go\n")
            return "failed", 78
        if not who:
            env.update({"HOME": os.path.expanduser("~"), "USER": who_name, "LOGNAME": who_name})
        home = env.get("HOME") or os.path.expanduser("~")
        pin_dir = how.get("pin_dir") or os.path.join(AGENTS_DIR, how["id"])
        # Taken off, from the node's Agents page (R145): the pinned copy a
        # session runs and the account's own install under its home.
        if spec.get("action") == "remove":
            gone = []
            for path in (os.path.join(pin_dir, cmd), os.path.join(home, how["bin"]),
                         *(os.path.join(home, a) for a in how.get("also", ()))):
                if os.path.lexists(path):
                    with contextlib.suppress(OSError):
                        shutil.rmtree(path) if os.path.isdir(path) and not os.path.islink(path) else os.unlink(path)
                        gone.append(path)
            # ...and a pinned release folder, with the links into it.
            rel = os.path.join(pin_dir, "release")
            if os.path.isdir(rel) and not os.path.islink(rel):
                for f in os.listdir(pin_dir):
                    p = os.path.join(pin_dir, f)
                    if os.path.islink(p) and os.path.realpath(p).startswith(os.path.realpath(rel) + os.sep):
                        with contextlib.suppress(OSError):
                            os.unlink(p)
                shutil.rmtree(rel, ignore_errors=True)
                gone.append(rel)
            job.say(("removed " + ", ".join(gone)) if gone else f"{product} was not installed here")
            job.say("\n")
            self.hello_again(f"{product} was removed")
            return "succeeded", 0
        env["PATH"] = ":".join([os.path.join(home, ".local", "bin"), env.get("PATH") or "/usr/local/bin:/usr/bin:/bin"])
        env.setdefault("LANG", "C.UTF-8")
        for k, v in how["env"].items():
            env[k] = v.format(home=home)
        want = str(spec.get("to") or "")
        if want and how["pin"] and re.fullmatch(r"\d+\.\d+\.\d+", want):
            env[how["pin"][0]] = how["pin"][1].format(v=want)
        stub = os.environ.get(f"BUILDERBOT_{how['id'].upper()}_INSTALLER")
        argv = ["bash", stub] if stub else ["bash", "-c", how["script"]]
        job.say(f"installing {product} for {who_name}" + (f" ({want} is out)" if want else "") + "\n")
        try:
            job.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        cwd=home if os.path.isdir(home) else "/tmp", env=env,
                                        start_new_session=True, close_fds=True, **who)
        except (OSError, ValueError) as e:
            job.say(f"could not start the installer: {e}\n")
            return "failed", 70
        deadline = time.monotonic() + int(spec.get("timeout") or 900)
        # Posted as it goes and timed by the clock, not by the next line: it
        # read on this thread, so nothing was posted until the end and a
        # silent hang never reached its deadline.
        reader = pump(job, job.proc.stdout)
        while reader.is_alive():
            reader.join(0.5)
            if job.pending:
                job.flush()
            if time.monotonic() > deadline:
                job.say("the installer did not finish in time\n")
                job.cancel()
                return "failed", 75
        code = job.proc.wait()
        job.proc = None
        if code != 0:
            job.say(f"the installer exited {code}\n")
            return "failed", code
        # The binary the installer just put down: the version asked for in
        # the folder it leaves, where the row names one (Claude Code's
        # ~/.local/share/claude/versions), else whatever its launcher resolves
        # to. Claude's launcher is not trusted alone: on a lab node it is a
        # stand-in the installer leaves in place, and pinning that pinned the
        # old version (23 Sep).
        exe = os.path.join(home, how["bin"])
        fresh = os.path.join(home, how["fresh"].format(v=want)) if want and how.get("fresh") else ""
        src = fresh if fresh and os.access(fresh, os.X_OK) else (os.path.realpath(exe) if os.access(exe, os.X_OK) else "")
        if not src:
            job.say(f"installed, but no {cmd} to run at ~/{how['bin']}\n")
            return "failed", 70
        out, dead = _probe([src, "--version"], timeout=20)
        if dead:
            job.say(f"installed, but it does not run: {dead}\n")
            return "failed", 70
        m = re.search(r"(\d+\.\d+\.\d+)", out)
        ver = m.group(1) if m else out.split("\n")[0].strip()[:40]
        if os.geteuid() == 0:
            try:
                os.makedirs(pin_dir, mode=0o755, exist_ok=True)
                root = _release_root(exe, src, home)
                if root:
                    _pin_release(pin_dir, cmd, root)
                else:
                    # One binary, and any release folder an earlier pin made
                    # (B262) goes with what it held.
                    shutil.rmtree(os.path.join(pin_dir, "release"), ignore_errors=True)
                    tmp = os.path.join(pin_dir, cmd + ".new")
                    shutil.copy2(src, tmp)
                    os.chown(tmp, 0, 0)
                    os.chmod(tmp, 0o755)
                    os.replace(tmp, os.path.join(pin_dir, cmd))
                job.say(f"pinned {ver} at {pin_dir}/{cmd}, root-owned: a session runs this copy and cannot change it\n")
            except OSError as e:
                job.say(f"installed {ver} for {who_name}, but could not pin it: {e}\n")
        else:
            job.say(f"installed {ver} for {who_name} (the agent is not root here, so the account's own copy is what runs)\n")
        # New terminals get the PATH with the pinned copy on it, tmux
        # sessions untouched (there are none).
        self.session_renew()
        job.say(f"{product} {ver} is what a session here runs now\n")
        # ...and the controller hears it now: the version it compares rides
        # the census, which rides hello, so without this the bell kept saying
        # an update was out for up to ten minutes after it landed (B249).
        self.hello_again(f"{product} was updated")
        return "succeeded", 0


    def published_now(self):
        """The published host ports of every container here, by compose
        project, for the controller to hand other nodes' sessions of the
        same project (R82). One docker ps a minute, cached between; None
        where there is no docker, so the heartbeat says nothing about it."""
        now = time.time()
        if now - getattr(self, "published_at", 0) < 60:
            return getattr(self, "published", None)
        self.published_at = now
        # On the PATH, as sessnet looks: DOCKER_BIN is the bare name unless
        # the environment names a path, and os.access on a bare name looks
        # in the working directory, so this said None on every node (B764).
        docker = shutil.which(DOCKER_BIN)
        if not docker:
            self.published = None
            return None
        out = _run([docker, "ps", "--format", '{{.Label "com.docker.compose.project"}}\t{{.Names}}\t{{.Ports}}'],
                   timeout=15)
        pub = {}
        for line in out.splitlines():
            bits = line.split("\t")
            if len(bits) < 3:
                continue
            key = (bits[0] or bits[1]).strip()[:100]
            ports = {int(p) for p in re.findall(r"(?:\d+\.){3}\d+:(\d+)->", bits[2])}
            if key and ports:
                pub.setdefault(key, set()).update(ports)
        self.published = {k: sorted(v) for k, v in pub.items()}
        return self.published

    def containers_now(self):
        """A fingerprint of every container here, running or not: its name,
        its state and its health, hashed. The controller moves the Containers
        page's token when it changes, so a container that crashed, or that a
        shell or a session started or removed, is on the page within a
        heartbeat, with no Refresh to press (the operator, 17 Oct). Read at
        most every ten seconds; None where there is no docker."""
        now = time.time()
        if now - getattr(self, "ctr_digest_at", 0) < 10:
            return getattr(self, "ctr_digest", None)
        self.ctr_digest_at = now
        docker = shutil.which(DOCKER_BIN)
        if not docker:
            self.ctr_digest = None
            return None
        out = _run([docker, "ps", "-a", "--format", "{{.Names}}\t{{.State}}\t{{.Status}}"], timeout=15)
        # The health, not the uptime: "Up 5 minutes (healthy)" moves every
        # minute, and only its parenthesis is news.
        rows = []
        for line in out.splitlines():
            bits = line.split("\t")
            if len(bits) >= 3:
                health = re.search(r"\((\w+)\)", bits[2])
                rows.append("\t".join([bits[0], bits[1], health.group(1) if health else ""]))
        rows.sort()
        self.ctr_digest = hashlib.blake2b("\n".join(rows).encode(), digest_size=8).hexdigest()
        return self.ctr_digest

    def held_now(self):
        """The sessions here a controller outage held (R251): each account's
        gate (bb-gate) leaves a mark beside its stamp while it refuses for an
        outage and takes it off with the first call it lets through. Read
        from the session account's home, where every account's cache lives on
        a node: [{project, uid, session, since}]."""
        home = SESSION.get("home") or ""
        if not home:
            return []
        out = []
        for pat in (os.path.join(home, ".cache", "builderbot", "u", "*", "project", "*", "held"),
                    os.path.join(home, "users", "*", ".cache", "builderbot", "u", "*", "project", "*", "held")):
            for f in glob.glob(pat)[:32]:
                parts = f.split(os.sep)
                try:
                    with open(f) as fh:
                        mark = json.load(fh)
                    out.append({"project": parts[-2], "uid": parts[-4],
                                "session": str(mark.get("session") or "")[:120],
                                "since": int(mark.get("since") or 0)})
                except (OSError, ValueError, TypeError, AttributeError):
                    continue
        return out[:32]

    def stats_now(self):
        """What each running container here uses, by name: [cpu %, memory %],
        for the hour's ring the controller keeps (R218 step 9). One docker
        stats a minute, cached between like published_now; None where there
        is no docker or it did not answer, and absent from the heartbeats
        between, which the controller reads as no news."""
        now = time.time()
        if now - getattr(self, "stats_at", 0) < 60:
            return None
        self.stats_at = now
        docker = shutil.which(DOCKER_BIN)       # on the PATH (B764)
        if not docker:
            return None
        out = _run([docker, "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}"],
                   timeout=20)
        got = {}
        for line in out.splitlines():
            bits = line.split("\t")
            if len(bits) < 3:
                continue
            try:
                got[bits[0].strip()[:120]] = [float(bits[1].strip().rstrip("%") or 0),
                                              float(bits[2].strip().rstrip("%") or 0)]
            except ValueError:
                continue
        return got or None

    def session_renew(self):
        """Ask the loop to make the terminals' environment again from the
        current bundle. From a job's thread, so only the flag
        is set here."""
        store = tc_root(self.state)
        into = os.path.realpath(os.path.join(store, ".bb", "current")) if store else ""
        if into and os.path.isdir(into) and self.session_up:
            self.session_stale = into

    def session_firewall_check(self):
        """Once a minute: the session ports' rule names the controller's
        address as it resolved when the node was provisioned, and a
        controller that moved (a new lease, a new host behind the same
        name) would find the ports dropped for it from then on. So the name
        is resolved again here and the rule rewritten when the answer
        changed: the nftables file the Debian path wrote and re-applied, or
        firewalld's rich rules replaced. The same rewrite keeps the rule to
        the screen relay's port alone, the one port a terminal or a VM's
        screen comes in on, on a node provisioned while ttyd's three were
        open too. Root only, which is a managed node; a guest has no such
        rule and skips."""
        if time.time() - self.fw_checked < FIREWALL_EVERY_S or os.geteuid() != 0:
            return
        self.fw_checked = time.time()
        ip = controller_ip(self.state.get("controller") or "")
        if not ip:
            return
        want = [SCREEN_PORT]
        ports = ", ".join(str(p) for p in want)
        fam = "ip6" if ":" in ip else "ip"
        if os.path.isfile(SESSION_NFT):
            try:
                with open(SESSION_NFT) as f:
                    text = f.read()
            except OSError:
                return
            m = re.search(r"tcp dport \{ ([0-9, ]+) \} (ip6?) saddr (\S+) accept", text)
            if not m:
                return
            if m.group(3) == ip and m.group(1) == ports:
                return
            new = re.sub(r"tcp dport \{ [0-9, ]+ \}", f"tcp dport {{ {ports} }}", text)
            new = new.replace(f"{m.group(2)} saddr {m.group(3)} accept", f"{fam} saddr {ip} accept")
            try:
                with open(SESSION_NFT, "w") as f:
                    f.write(new)
            except OSError as e:
                log(f"session ports: could not rewrite {SESSION_NFT}: {e}")
                return
            rc = subprocess.run([NFT_BIN, "-f", SESSION_NFT], capture_output=True, check=False).returncode
            log(f"session ports: {ports} from {ip} (was {m.group(1)} from {m.group(3)}); "
                f"rule rewritten{'' if rc == 0 else ' but nft refused it (' + str(rc) + ')'}")
            return
        if _have(FIREWALL_CMD) and _run([FIREWALL_CMD, "--state"]) == "running":
            rules = _run([FIREWALL_CMD, "--permanent", "--list-rich-rules"], timeout=20).splitlines()
            ours = [r for r in rules if any(f'port="{p}"' in r for p in (7681, 7682, 7683, *want))]
            have = {re.search(r'source address="([^"]+)"', r).group(1)
                    for r in ours if re.search(r'source address="([^"]+)"', r)}
            found = [re.search(r'port port="(\d+)"', r) for r in ours]
            have_ports = {int(m.group(1)) for m in found if m}
            if not ours or (have == {ip} and have_ports == set(want)):
                return
            for r in ours:
                subprocess.run([FIREWALL_CMD, "--permanent", f"--remove-rich-rule={r}"], capture_output=True, check=False)
            ffam = "ipv6" if ":" in ip else "ipv4"
            for port in want:
                subprocess.run([FIREWALL_CMD, "--permanent", f'--add-rich-rule=rule family="{ffam}" source '
                                f'address="{ip}" port port="{port}" protocol="tcp" accept'],
                               capture_output=True, check=False)
            subprocess.run([FIREWALL_CMD, "--reload"], capture_output=True, check=False)
            log(f"session ports: {ports} from {ip} (was {', '.join(str(p) for p in sorted(have_ports))} from "
                f"{', '.join(sorted(have)) or '?'}); firewalld rules replaced")

    def session_idle_reap(self):
        """End this node's agent sessions past the idle rule: the
        controller's idle.py, enforced here from node.json. An agent's
        sessions by name (claude-<project>, u_xxxx~claude-<project>, the
        prefixes in AGENT_PREFIXES), by tmux's own session_activity, once
        per minute."""
        limit = self.state.get("session_idle_minutes") or 0
        if limit <= 0 or time.time() - getattr(self, "_idle_at", 0) < IDLE_UNIT:
            return
        self._idle_at = time.time()
        out = self._tmux(["list-sessions", "-F", "#{session_name}\t#{session_activity}"])
        for line in (out or "").splitlines():
            if "\t" not in line:
                continue
            name, act = line.split("\t", 1)
            try:
                last = float(act.strip())
            except ValueError:
                continue
            base = name.split("~", 1)[1] if "~" in name else name
            if base.startswith(AGENT_PREFIXES) and time.time() - last > limit * IDLE_UNIT:
                log(f"sessions: ending {name} (idle {limit} minute(s), the controller's rule)")
                self._tmux(["kill-session", "-t", "=" + name])

    def session_check(self):
        """Once a loop: the terminals' environment made again onto a newer
        bundle a job just fetched, or onto the node's own address where it
        moved (DHCP handed it another, the interface came back on a new
        one), which the screen relay listens on. Sessions are tmux's and
        are untouched; only the next terminal opened sees the change."""
        if self.session_up and self.session_bound and not SESSION_BIND and not self.session_stale:
            now = self.session_bind()
            if now != self.session_bound:
                store = tc_root(self.state)
                into = os.path.realpath(os.path.join(store, ".bb", "current")) if store else ""
                if into and os.path.isdir(into):
                    log(f"sessions: this node's address moved ({self.session_bound} -> {now})")
                    self.session_stale = into
                    self.screen.rebind()
        if self.session_stale and self.session_up and os.path.isdir(self.session_stale):
            log("sessions: the bundle or the store changed; new terminals see it")
            self.session_bundle = self.session_digest
            self.session_tried = time.time()
            self.session_start(self.session_stale)
