"""The coding agents' sign-ins sealed on a node (R126).

With the node's switch on (token_seal, after R125's accounts as their own
users), an account's Claude Code, Codex CLI and Grok Build sign-ins are kept here
sealed, never in the clear on a disk: a copied disk, a backup, the share or
a snapshot carries nothing usable, and a root who arrives while the account
has no session running gets nothing for it. tokenseal.py says how.

  SEAL_DIR/u_X/AGENT.seal   the sealed sign-in, root's alone, outside every
                            home and every session's view
  OPEN_DIR/u_X/AGENT.json   the opened copy while the account works here: a
                            tmpfs, the account's user's alone; the home's
                            own file is a link to it, so the agent reads and
                            refreshes it where it always did

A seal is opened only when a person opens a terminal for their own account
(the key rides in the controller's signed /term open, token_open), and the
opened copy is wiped GRACE_S after the account's last session ends. A
refresh written into it is sealed again within a pass. A login writes into
the home as ever; the pass finds the plain file, seals it, and puts the
link in its place. Copilot CLI keeps its token in a file of its settings and
is not sealed yet.
"""
import base64
import contextlib
import json
import os
import pwd
import subprocess
import time

from . import tokenseal
from .accounts import UID_RE, user_of
from .base import log

SEAL_DIR = "/var/lib/builderbot/tokens"
OPEN_DIR = "/run/bb-tokens"
GRACE_S = 300
EVERY_S = 10
# ...and Grok Build's session (R95 step 21), a file of its own as Codex's is.
FILES = (("claude", os.path.join(".claude", ".credentials.json")), ("codex", os.path.join(".codex", "auth.json")),
         ("grok", os.path.join(".grok", "auth.json")))


def _claims(jwt):
    try:
        part = str(jwt).split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))) or {}
    except (IndexError, ValueError, TypeError):
        return {}


def _jwt_email(d, depth=0):
    """The email a JSON Web Token anywhere in a record names, from its
    claims, unverified (a name to show, never a credential), or ""."""
    if depth > 4:
        return ""
    for v in (d.values() if isinstance(d, dict) else d if isinstance(d, list) else []):
        if isinstance(v, (dict, list)):
            got = _jwt_email(v, depth + 1)
            if got:
                return got
        elif isinstance(v, str) and v.count(".") == 2 and len(v) < 8192:
            got = str(_claims(v).get("email") or "")
            if got:
                return got
    return ""


def about(agent, data, home):
    """What a sign-in says of itself, kept readable in its seal's header so
    the Agents page can name who is signed in without opening it."""
    out = {"agent": agent}
    with contextlib.suppress(ValueError, TypeError, AttributeError):
        if agent == "codex":
            toks = (json.loads(data) or {}).get("tokens") or {}
            c = _claims(toks.get("id_token"))
            out["email"] = str(c.get("email") or "")[:120]
            out["plan"] = str(((c.get("https://api.openai.com/auth") or {}).get("chatgpt_plan_type")) or "")[:40]
        elif agent == "claude":
            with open(os.path.join(home, ".claude.json"), encoding="utf-8") as f:
                out["email"] = str(((json.load(f).get("oauthAccount") or {}).get("emailAddress")) or "")[:120]
        elif agent == "grok":
            # The email its token's claims name, else that it is an xAI
            # account (login-list.py grok_of says it the same way).
            out["email"] = (_jwt_email(json.loads(data)) or "an xAI account")[:120]
    return out


def _shred(path):
    """A plain sign-in file overwritten and removed: what overwriting can do
    on the disk it is on (nothing on a copy-on-write one, or a snapshot)."""
    with contextlib.suppress(OSError):
        n = os.path.getsize(path)
        with open(path, "r+b") as f:
            f.write(b"\0" * n)
            f.flush()
            os.fsync(f.fileno())
    with contextlib.suppress(OSError):
        os.unlink(path)


def link_left(home_file, opened, seal):
    """Whether the home's file is a link to an opened copy that is not there
    with no seal left to open it from: a sign-out, or a seal wiped, after
    the link was made."""
    return os.path.islink(home_file) and os.readlink(home_file) == opened \
        and not os.path.lexists(opened) and not os.path.exists(seal)


def _write(path, data, mode, uid=0, gid=0):
    tmp = path + ".new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chown(tmp, uid, gid)
    os.replace(tmp, path)


class TokensMixin:
    tokens_at = 0.0
    _tok_e = None

    def token_seal_on(self):
        return bool(self.state.get("token_seal")) and self.account_users_ready()

    def token_boot_public(self):
        """This run's public half, which the controller wraps a seal's key to."""
        if self._tok_e is None:
            self._tok_e = tokenseal.boot_secret()
        return tokenseal.public(self._tok_e)

    def _tok_state(self):
        if not hasattr(self, "_tok_seen"):
            self._tok_seen, self._tok_live = {}, {}
        return self._tok_seen, self._tok_live

    def token_census(self):
        """For the hello: this boot's public half and the R of every seal
        here, by account and agent (public, both), or None while off."""
        if not self.token_seal_on() and not os.path.isdir(SEAL_DIR):
            return None
        sealed = {}
        with contextlib.suppress(OSError):
            for acct in sorted(os.listdir(SEAL_DIR))[:500]:
                if not UID_RE.match(acct):
                    continue
                for agent, _ in FILES:
                    with contextlib.suppress(OSError, tokenseal.Refused):
                        with open(os.path.join(SEAL_DIR, acct, agent + ".seal"), "rb") as f:
                            h = tokenseal.header(f.read(8192))
                        sealed.setdefault(acct, {})[agent] = {"R": h.get("R", ""), "K": h.get("K", ""),
                                                             "email": h.get("email", ""), "plan": h.get("plan", "")}
        return {"E": self.token_boot_public(), "sealed": sealed}

    def _open_mounted(self):
        """OPEN_DIR a tmpfs of its own, mounted once: noswap where the kernel
        has it, so an opened sign-in is not written to swap either."""
        os.makedirs(OPEN_DIR, mode=0o711, exist_ok=True)
        with open("/proc/mounts", encoding="utf-8") as f:
            if any(ln.split()[1] == OPEN_DIR and ln.split()[2] == "tmpfs" for ln in f if len(ln.split()) > 2):
                return True
        for opts in ("mode=0711,size=4m,noswap", "mode=0711,size=4m"):
            if subprocess.run(["mount", "-t", "tmpfs", "-o", opts, "bb-tokens", OPEN_DIR],
                              capture_output=True, timeout=30, check=False).returncode == 0:
                return True
        log(f"tokens: could not mount a tmpfs at {OPEN_DIR}, so no sign-in is opened here")
        return False

    def _acct_open_dir(self, acct, pw):
        d = os.path.join(OPEN_DIR, acct)
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chown(d, pw.pw_uid, pw.pw_gid)
        os.chmod(d, 0o700)
        return d

    def _seal(self, acct, agent, data, home):
        # The X25519 public where this node has the library (R158 step 3),
        # else the public before, which seals the old way.
        pub = ((self.state.get("token_pubs2") or {}).get(acct) if tokenseal.HAVE else None) \
            or (self.state.get("token_pubs") or {}).get(acct)
        if not pub:
            return False
        d = os.path.join(SEAL_DIR, acct)
        os.makedirs(SEAL_DIR, mode=0o700, exist_ok=True)
        os.makedirs(d, mode=0o700, exist_ok=True)
        # K names the public key it was sealed under, so the controller can
        # tell a seal still under the install key before a rotation.
        _write(os.path.join(d, agent + ".seal"), tokenseal.seal(pub, data, dict(about(agent, data, home), K=tokenseal.rid(pub))), 0o600)
        # The controller hears the new seal's R at once: the next terminal
        # opened for this account must bring the key that opens this one.
        again = getattr(self, "hello_again", None)
        if again:
            again(f"{acct}'s {agent} sign-in was sealed")
        return True

    def _link(self, home_file, target, pw):
        """The home's file a link to the opened copy, the account's user's."""
        with contextlib.suppress(FileNotFoundError):
            if os.path.islink(home_file) and os.readlink(home_file) == target:
                return
            os.unlink(home_file)
        os.makedirs(os.path.dirname(home_file), exist_ok=True)
        os.symlink(target, home_file)
        os.lchown(home_file, pw.pw_uid, pw.pw_gid)

    def _live(self, acct):
        user = user_of(acct)
        return bool((self._tmux_as(user, ["list-sessions", "-F", "#{session_name}"], quiet=True) or "").strip())

    def token_pass(self):
        """Every few seconds, with the switch on: a plain sign-in sealed and
        made a link, a refreshed one sealed again, and an account's opened
        copies wiped GRACE_S after its last session."""
        if os.geteuid() != 0 or time.time() - self.tokens_at < EVERY_S:
            return
        if not self.token_seal_on():
            self.tokens_at = time.time()
            self._tokens_back()
            return
        self.tokens_at = time.time()
        if not self._open_mounted():
            return
        seen, live = self._tok_state()
        try:
            users_dir = os.path.join(pwd.getpwnam(self.session_account()).pw_dir, "users")
            accts = [a for a in sorted(os.listdir(users_dir))[:500] if UID_RE.match(a)]
        except (KeyError, OSError):
            return
        now = time.time()
        for acct in accts:
            home = os.path.join(users_dir, acct)
            try:
                pw = pwd.getpwnam(user_of(acct))
                if os.lstat(home).st_uid != pw.pw_uid:
                    continue                    # not moved to its user yet (R125)
            except (KeyError, OSError):
                continue
            odir = os.path.join(OPEN_DIR, acct)
            for agent, rel in FILES:
                hf, of = os.path.join(home, rel), os.path.join(odir, agent + ".json")
                with contextlib.suppress(OSError):
                    if os.path.isfile(hf) and not os.path.islink(hf) and os.path.getsize(hf) > 0:
                        # A login, or a sign-in from before the switch:
                        # sealed, kept open while the account works here,
                        # and the plain file gone.
                        with open(hf, "rb") as f:
                            data = f.read()
                        if self._seal(acct, agent, data, home):
                            if os.path.isdir(odir) or self._live(acct):
                                self._acct_open_dir(acct, pw)
                                _write(of, data, 0o600, pw.pw_uid, pw.pw_gid)
                                st = os.stat(of)
                                seen[(acct, agent)] = (st.st_ino, st.st_size, st.st_mtime_ns)
                            _shred(hf)
                            self._link(hf, of, pw)
                            log(f"tokens: {acct}'s {agent} sign-in sealed")
                    elif os.path.isfile(of):
                        st = os.stat(of)
                        key = (st.st_ino, st.st_size, st.st_mtime_ns)
                        if seen.get((acct, agent)) != key:
                            with open(of, "rb") as f:
                                self._seal(acct, agent, f.read(), home)
                            seen[(acct, agent)] = key
                    elif acct not in live and link_left(hf, of, os.path.join(SEAL_DIR, acct, agent + ".seal")):
                        # No seal behind the home's link and nothing open: the
                        # link goes, so a terminal here says to sign in rather
                        # than that a sign-in is waiting to be opened (B386).
                        os.unlink(hf)
            if not os.path.isdir(odir):
                continue
            if self._live(acct):
                live[acct] = now
            elif now - live.setdefault(acct, now) > GRACE_S:
                for agent, _ in FILES:
                    of = os.path.join(odir, agent + ".json")
                    with contextlib.suppress(OSError):
                        os.unlink(of)
                    seen.pop((acct, agent), None)
                with contextlib.suppress(OSError):
                    os.rmdir(odir)
                live.pop(acct, None)

    def _tokens_back(self):
        """The switch off: each account's opened sign-ins put back as the
        plain files they were, and their seals gone. One with no copy open
        stays sealed until its next terminal opens it (the controller keeps
        sending its key while this node reports a seal), and then comes back."""
        if not os.path.isdir(SEAL_DIR) or not os.path.isdir(OPEN_DIR):
            return
        try:
            users_dir = os.path.join(pwd.getpwnam(self.session_account()).pw_dir, "users")
        except KeyError:
            return
        for acct in sorted(os.listdir(OPEN_DIR))[:500]:
            if not UID_RE.match(acct):
                continue
            with contextlib.suppress(KeyError, OSError):
                pw = pwd.getpwnam(user_of(acct))
                home = os.path.join(users_dir, acct)
                for agent, rel in FILES:
                    of = os.path.join(OPEN_DIR, acct, agent + ".json")
                    if not os.path.isfile(of):
                        continue
                    with open(of, "rb") as f:
                        data = f.read()
                    hf = os.path.join(home, rel)
                    with contextlib.suppress(FileNotFoundError):
                        os.unlink(hf)
                    _write(hf, data, 0o600, pw.pw_uid, pw.pw_gid)
                    self.token_forget(acct, agent)
                    log(f"tokens: {acct}'s {agent} sign-in is a plain file again")
                with contextlib.suppress(OSError):
                    os.rmdir(os.path.join(OPEN_DIR, acct))

    def token_open(self, tk):
        """An account's seals opened for the terminal a person just opened
        for it (the controller's signed /term, R133): the keys unwrapped with
        this boot's secret, each seal opened into the tmpfs, and the home's
        file a link to it. Called by the terminal server before the program
        starts; the keys are forgotten when it returns."""
        acct = str(tk.get("acct") or "")
        # Opened with the switch off too: that is how a seal left from while
        # it was on comes back (_tokens_back).
        if not UID_RE.match(acct) or self._tok_e is None or not self.account_users_ready() \
                or not os.path.isdir(os.path.join(SEAL_DIR, acct)) or not self._open_mounted():
            return
        keys = tokenseal.unwrap(self._tok_e, tk["C"], base64.urlsafe_b64decode(tk["w"] + "=" * (-len(tk["w"]) % 4)))
        pw = pwd.getpwnam(user_of(acct))
        home = os.path.join(pwd.getpwnam(self.session_account()).pw_dir, "users", acct)
        seen, live = self._tok_state()
        odir = None
        for agent, rel in FILES:
            with contextlib.suppress(OSError, tokenseal.Refused):
                with open(os.path.join(SEAL_DIR, acct, agent + ".seal"), "rb") as f:
                    blob = f.read()
                r = tokenseal.rid(tokenseal.header(blob).get("R", ""))
                data = None
                # The install key's, or the one before it while a rotation
                # keeps it (|prev); opened with the old, it is sealed again
                # under the account's public key now.
                for k, old in ((keys.get(r), False), (keys.get(r + "|prev"), True)):
                    if not k:
                        continue
                    with contextlib.suppress(tokenseal.Refused):
                        data = tokenseal.open_with(k, blob)
                        if old:
                            self._seal(acct, agent, data, home)
                        break
                if data is None:
                    continue
                odir = odir or self._acct_open_dir(acct, pw)
                of = os.path.join(odir, agent + ".json")
                _write(of, data, 0o600, pw.pw_uid, pw.pw_gid)
                st = os.stat(of)
                seen[(acct, agent)] = (st.st_ino, st.st_size, st.st_mtime_ns)
                self._link(os.path.join(home, rel), of, pw)
        if odir:
            live[acct] = time.time()

    def token_login_ready(self, acct):
        """Before a sign-in: the account's opened folder made, so a login
        writing through the home's link lands in the tmpfs, never on a disk."""
        if not UID_RE.match(acct or "") or not self.token_seal_on() or not self._open_mounted():
            return
        self._acct_open_dir(acct, pwd.getpwnam(user_of(acct)))
        self._tok_state()[1][acct] = time.time()

    def token_forget(self, acct, agent):
        """A sign-out: the seal and the opened copy gone."""
        for p in (os.path.join(SEAL_DIR, acct, agent + ".seal"), os.path.join(OPEN_DIR, acct, agent + ".json")):
            with contextlib.suppress(OSError):
                os.unlink(p)
