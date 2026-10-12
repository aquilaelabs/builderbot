#!/usr/bin/env python3
"""BuilderBot dashboard: status, project list and bb macros over HTTP.

Deliberately stdlib-only. This runs inside a container whose whole premise is
that it gets rebuilt often; a dashboard that drags in a web framework would be
one more thing to keep current, and http.server is more than adequate for one
operator on a LAN.

The terminal is not served from here. ttyd owns that on its own port, because
proxying a PTY websocket through a hand-written server is exactly the kind of
code that looks fine until it deadlocks.
"""
import base64
import contextlib
from html import escape as html_escape
import glob
import gzip
import hashlib
import hmac
import atexit
import collections
import json
import os
import sys
import re
import selectors
import shlex
import socket
import sqlite3
import subprocess
import threading
import traceback
import time

# Beside this file. Imported up here rather than with the modules below,
# because write_json is defined from it before any of those load.
import statefile
from names import PROJECT_NAME, claude_session, tmux_name   # noqa: F401 - re-exported to the modules
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
PORT = int(os.environ.get("DASHBOARD_PORT", "7680"))
# Loopback only: the browser reaches terminals through this server's own
# /term proxy, so there is no second port for the page to be told about.
TTYD_PORT = int(os.environ.get("DASHBOARD_TTYD_PORT", "7681"))
# The read-only twin (roadmap #27). ttyd is read-only unless started with
# --writable, so an account that may not have a shell reaches this one and
# cannot type into the socket at all. Its Claude input goes through the send
# path, which is a table lookup and literal text like every other thing this
# page can make happen.
TTYD_RO_PORT = int(os.environ.get("DASHBOARD_TTYD_RO_PORT", str(TTYD_PORT + 1)))

# ---- one login for everything ---------------------------------------------
# The browser used to be asked twice: once by this server, once by ttyd on
# its own port, each with the built-in credentials dialog. The terminals are
# proxied under /term on this origin now, so a single sign-in on a real login
# page covers both, and ttyd's port no longer needs to be published at all.
#
# The cookie is a signed expiry, not a server-side session: the secret lives
# on the /config volume, so a container update does not log every phone out,
# and there is no session table to grow, lock, or clean. Basic auth still
# works on every request (curl, bb capture shot and the tests send it preemptively),
# but no response carries a WWW-Authenticate challenge any more, because the
# challenge is precisely what made browsers pop their own dialog.
SESSION_DAYS = 30
STATE = Path(os.environ.get("DASHBOARD_STATE", "/config"))


def _session_secret():
    """The key the session cookie is signed with, kept on the state volume.

    Every other read of that volume degrades rather than raises, and this one
    has to as well: it runs at import, so a /config that is missing or
    read-only took the whole dashboard down at startup, where the honest
    outcome is a dashboard that runs and forgets its sessions on restart.
    Basic auth is unaffected either way.
    """
    p = STATE / "dashboard-secret"
    try:
        s = p.read_bytes()
        if len(s) >= 32:
            return s
    except OSError:
        pass
    s = os.urandom(32)
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(s)
    except OSError as e:
        print(f"dashboard: cannot keep the session secret in {STATE} ({e}); "
              "sign-ins will not survive a restart", flush=True)
    return s


SECRET = _session_secret()


def make_token(u):
    """A cookie for this account: name, expiry, and a signature over both plus
    the account's password stamp.

    Stateless: there is no token table to keep. What
    the stamp buys is the revocation such a table would have given: changing a
    password or deleting an account moves it, and every cookie signed against
    the old one stops verifying on the next request.
    """
    exp = str(int(time.time()) + SESSION_DAYS * 86400)
    nm = base64.urlsafe_b64encode(u["name"].encode()).decode().rstrip("=")
    sig = hmac.new(SECRET, f"{u['name']}|{exp}|{users.stamp(u)}".encode(),
                   hashlib.sha256).hexdigest()
    return f"{nm}.{exp}.{sig}"


def token_user(tok):
    """The account a cookie is for, or None. Fails closed on everything.

    A cookie from before accounts existed has two parts rather than three and
    simply does not verify, which signs those sessions out once. That is the
    honest outcome: there is no way to know who they were.
    """
    nm, _, rest = str(tok or "").partition(".")
    exp, _, sig = rest.partition(".")
    if not exp.isdigit() or int(exp) < time.time():
        return None
    try:
        name = base64.urlsafe_b64decode(nm + "=" * (-len(nm) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None
    u = users.get(name)
    if not u:
        return None
    want = hmac.new(SECRET, f"{name}|{exp}|{users.stamp(u)}".encode(),
                    hashlib.sha256).hexdigest()
    return u if hmac.compare_digest(sig, want) else None


# The landing page. Same palette as the dashboard, one job: turn a credential
# into the cookie. autocomplete names are the standard ones so password
# managers offer to fill and to save, which the browser dialog never did
# well on a phone.
# The first-run screen. Same card as the sign-in, so there is one look and one
# place to change it, with the copy and the fields the first account needs.
#
# It is served ONLY while the store holds no accounts, and creating one closes
# it for good. That window is the honest cost of not putting a password in the
# container's environment: until somebody claims the box, whoever reaches the
# port can. Which is why the page says to do it now rather than leaving it to
# be inferred, and why the dashboard refuses everything else until it is done.
SETUP_FIELDS = """  <p class="note">Nobody owns this container yet. The first account you make
    here is the <b>owner</b>: it cannot be deleted, and it is how you add
    everyone else. Do it now: until you do, anyone who can reach this page
    can claim it.</p>
  <!--ERR-->
  <label for="u">Username</label>
  <input id="u" name="username" autocomplete="username" autocapitalize="none"
    required autofocus>
  <label for="p">Password</label>
  <input id="p" name="password" type="password" autocomplete="new-password"
    minlength="8" required>
  <label for="p2">Password again</label>
  <input id="p2" name="password2" type="password" autocomplete="new-password"
    minlength="8" required>
  <button type="submit">Create the owner</button>"""

LOGIN_FIELDS = """  <!--ERR-->
  <input type="hidden" name="next" value="/">
  <label for="u">Username</label>
  <input id="u" name="username" autocomplete="username" autocapitalize="none" required>
  <label for="p">Password</label>
  <input id="p" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Sign in</button>"""

LOGIN_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>BuilderBot: <!--TITLE--></title>
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<style>
  /* dvh, not vh: on a phone `vh` resolves against the LARGE viewport (the
     page as it would be with the URL bar retracted), so min-height:100vh
     made the body taller than the visible area and the page scrolled to
     reach nothing. dvh tracks the bar as it comes and goes; vh stays first
     as the fallback for browsers that do not know dvh.
     `safe center` keeps the top of the card reachable if a soft keyboard
     ever leaves less room than the card needs, the same rule the
     dashboard's own dialogs use. */
  body{margin:0;min-height:100vh;min-height:100dvh;padding:16px;
    box-sizing:border-box;
    display:flex;align-items:safe center;justify-content:center;
    background:#0d1117;color:#e6edf3;
    font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  /* border-box, or the padding and border are added to the width: the card
     wanted 398px on a 390px phone, flex shrank it to exactly the viewport,
     and it sat edge to edge looking far bigger than it is. */
  form{box-sizing:border-box;background:#161b22;border:1px solid #30363d;
    border-radius:10px;padding:28px;width:min(340px,100%);
    display:flex;flex-direction:column;gap:12px}
  h1{margin:0 0 6px;font-size:18px;display:flex;align-items:center;gap:10px}
  h1 svg{width:28px;height:28px;color:#3fb950}
  label{font-size:12px;color:#8b98a5}
  input{background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:6px;
    padding:10px;font-size:16px}
  input:focus{outline:2px solid #2f4d6d;outline-offset:-1px}
  button{margin-top:6px;background:#1f6f36;border:1px solid #2ea043;color:#e6edf3;
    border-radius:6px;padding:10px;font-size:15px;cursor:pointer}
  .err{color:#f85149;font-size:13px;margin:0}
  .note{color:#8b98a5;font-size:13px;margin:0 0 4px}
</style></head><body>
<form method="post" action="<!--ACTION-->">
  <h1><svg viewBox="0 0 32 32" aria-hidden="true"><mask id="m">
    <rect width="32" height="32" fill="#000"/>
    <rect x="4" y="8.5" width="24" height="17" rx="5.5" fill="#fff"/>
    <rect x="15" y="3.5" width="2" height="6" rx="1" fill="#fff"/>
    <circle cx="16" cy="3" r="2.3" fill="#fff"/>
    <circle cx="11.4" cy="15.4" r="2.1" fill="#000"/>
    <circle cx="20.6" cy="15.4" r="2.1" fill="#000"/>
    <rect x="10.6" y="19.6" width="10.8" height="2.6" rx="1.3" fill="#000"/>
  </mask><rect width="32" height="32" fill="currentColor" mask="url(#m)"/></svg>
  BuilderBot</h1>
  <!--FIELDS-->
</form>
<script>
  const n = new URLSearchParams(location.search).get("next");
  if (n && n.startsWith("/") && !n.startsWith("//"))
    document.querySelector('[name=next]').value = n;
</script>
</body></html>
"""

# Every command the UI can run and every key it can press, by name, and the
# operator's own command lists: macros.py (R77).



# Where Claude Code keeps transcripts: one directory per working directory,
# with the path's slashes turned into dashes, holding one .jsonl per session.
CLAUDE_PROJECTS = Path(
    os.environ.get("BUILDER_HOME", str(Path.home()))) / ".claude" / "projects"


# Every request body here is a handful of short JSON fields. Anything larger is
# a mistake or a probe, and reading it into memory unbounded helps neither.
MAX_BODY = 64 * 1024
# The one body that is a document: a project's whole design, which its own
# limits let run to megabytes (forty pages, sixty rules of twenty thousand
# characters). At 64 kB a design of forty pages and thirteen themes was
# refused as "body too large" with every part of it inside its limit.
# ...and an agent's log post: it batches chunks up to 40 kB and then adds a
# whole chunk of up to 32 kB, characters json.dumps may spell six bytes each,
# so a post could pass 64 kB, and one refused as too large was retried for
# good, holding its job in the agent's count and refusing every update as
# busy (B520: j_cdcb12b7, a phone screenshot, held from 4 to 6 Oct).
# ...and a file saved from a person's editor (R159): files.MAX_READ as base64.
MAX_BODY_FOR = {"/api/design": 4 * 1024 * 1024, "/api/wiki": 1024 * 1024,
                "/api/v1/files": 28 * 1024 * 1024,
                "/api/v1/agent/log": 512 * 1024}

# One field out of a request body, read the one way here and in every
# module a handler calls into (fields.py).
from fields import field                                         # noqa: E402







# The one implementation, in statefile.py, along with the file lock that makes
# a read-modify-write safe against the OTHER writer, a `bb` invocation, which
# is a different process. Kept as a name here because thirty-odd call sites and
# every configure() injection already say write_json.
write_json = statefile.write_json


# One lock for every read-modify-write of a state file. The revision the
# layout carries is what lets two browsers share a strip without fighting;
# two saves reading the same file and both stamping rev+1 handed both pages
# the same number, and each then took the other's writes for its own and
# skipped them. Coarse on purpose: these are tiny files and rare writes.
_state_lock = threading.Lock()

# ---- what the page keeps here ---------------------------------------------------
# Each account's tab strip and panes, and the sidebar's cards: layout.py.
import layout                                                    # noqa: E402

layout.configure(state=STATE, write_json=write_json, lock=_state_lock)
# ...and what each account has put away from its bell: bellseen.py.
import bellseen                                                  # noqa: E402

bellseen.configure(state=STATE, write_json=write_json)








# `bb toolchains install|update|remove` refuses when CLAUDECODE is set, and the
# message it prints tells the session to ask the operator to use this page.
# So this page must never carry that variable, and it can: `bb dashboard dev`
# is normally run *by* a session, and the server it starts inherits whatever
# that session had. One line here, rather than trusting every launcher to
# remember, because the failure looks like the dashboard refusing to obey the
# operator and quoting its own name as the workaround.
os.environ.pop("CLAUDECODE", None)


def run(cmd, cwd=None, timeout=120, env=None, split_err=False, register=None):
    # split_err=True keeps stdout in `out` and stderr in `err`, for the one
    # caller class that must not mistake a warning for real output (the
    # ls-remote emptiness check: ssh's first-contact "Permanently added ..."
    # note lands on stderr and made an empty repo look non-empty). The
    # default stays combined, which is what every log-oriented caller wants.
    # register: hand the caller the process, so a long job can be interrupted.
    # It gets its own process group with it, because stopping an install means
    # stopping the curl or the tar it is waiting on, not only the shell.
    try:
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=env,
                             start_new_session=register is not None)
    except FileNotFoundError as e:
        return {"cmd": shlex.join(cmd), "code": 127, "out": str(e), "err": ""}
    if register:
        register(p)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        return {"cmd": shlex.join(cmd), "code": 124,
                "out": f"timed out after {timeout}s", "err": ""}
    finally:
        if register:
            register(None)
    out, err = out or "", err or ""
    if not split_err:
        out, err = out + err, ""
    return {"cmd": shlex.join(cmd), "code": p.returncode, "out": out, "err": err}


def version_payload(name):
    """The Artifacts tab's version block, plus what a window move would cost
    here. One function so every answer the tab gets carries the same warning:
    the staged line is drawn from whichever of them came back last."""
    cost = window_cost(name)
    # {tag: {url, error, forge}} of the forge releases Release made, for the row's link (R123, R124).
    rel = forgerelease.kept(name)
    return (version.payload(name) | ({"window_cost": cost} if cost else {})
            | ({"forge_releases": rel} if rel else {}))


def window_cost(name):
    """What a MINOR bump of this project would cost the others, or {}.

    Only one project can answer yes: the one whose checkout IS BuilderBot,
    because its minor is the compatibility window. What that window still
    holds, now the environment block is assembled per session and cannot be
    from another one (R63 step 3), is a node's AGENT: bump the minor and every
    node running an agent from the old window holds its projects until that
    agent is updated. Sessions on them end. Said before the button is pressed
    rather than after (B92); the test is the two files that move the window,
    not a project's name.
    """
    try:
        here = WORKSPACE / name
        if not ((here / "tools" / "version-stamp").is_file()
                and (here / "scripts" / "agent" / "builderbot-agent.py").is_file()):
            return {}
    except OSError:
        return {}
    # Every project bound to a node that runs an agent: after the bump that
    # agent is from the previous window until it is updated.
    live = {n["id"] for n in nodes.node_list(all=True) if n.get("kind") == "agent"}
    held = []
    try:
        for d in sorted(WORKSPACE.iterdir()):
            if not d.is_dir() or (d / IGNORE_MARKER).exists():
                continue
            if ((prefs.get(d.name) or {}).get("node") or "") in live:
                held.append(d.name)
    except OSError:
        return {}
    if not held:
        return {}
    return {"window": nodes.agent_window(nodes.agent_file()["version"]), "projects": held}


def node_holds(reap=False):
    """{node id: why} for every agent node no Claude session may start on
    right now: its agent is from another compatibility window than this
    controller ships, or its Claude Code is being updated (claudecode.py),
    which ends the sessions there first. The half of a project's hold that
    is its node's. Being merely behind is not here: inside a window an
    older agent takes a job and a session, and the Nodes tab's Update is a
    courtesy rather than a gate. reap: only what ends a running session
    (claudecode.holds)."""
    out = {}
    if NODES_OK:
        return out
    for n in nodes.node_list():
        if n["kind"] == "agent" and nodes.agent_gap(n):
            out[n["id"]] = nodes.agent_stale(n)
    out.update(claudecode.holds(reap))
    return out


def compat_holds(reap=False):
    """{project: why} for every project no Claude session may run on right
    now, which since R63 step 3 means one thing: its node's agent is from
    another compatibility window. Per project on purpose, because another
    project's node being out of window is that project's problem and this
    one's button stays live."""
    out = {}
    holds = node_holds(reap)
    pp = prefs.all_projects()
    try:
        dirs = [d for d in WORKSPACE.iterdir() if d.is_dir()]
    except OSError:
        return out
    for d in dirs:
        # The block's window went with the block (R63 step 3): what a session
        # is told is assembled per session now, so there is no copy to be from
        # another window. A node's agent still can be, and that is this.
        why = holds.get((pp.get(d.name) or {}).get("node") or "", "")
        if why:
            out[d.name] = why
    return out


# When a hosting-only node's refused verb was last audited (Handler._agent).
_host_refused_at = {}


# How often the sweep below runs. Settable only so the suite need not wait
# half a minute to see a session end.
COMPAT_SWEEP_S = float(os.environ.get("BB_COMPAT_SWEEP") or 30)


def compat_reap_once():
    """End the Claude sessions running on a held project (compat_holds), here
    and on the nodes. Returns the names ended.

    This is the other half of the window's promise: a controller that moved
    its minor may have changed what the block says and what the agent
    understands, so a conversation started under the old window is running
    on a map that is now wrong, and it is ended rather than left to act on
    it. Inside a window nothing here fires: an update to the block or the
    agent that keeps the window leaves every session running. Run once at
    start, which is the moment after a controller update, and on a timer
    after that for a window that moves under a running server (a bump
    landing on a `bb dashboard dev` restart, a node enrolled behind)."""
    holds = compat_holds(reap=True)
    if not holds:
        return []
    wanted = {claude_session(p): why for p, why in holds.items()}
    ended = []
    for s in tmux_sessions():
        why = wanted.get(tmux_base(s["name"]))
        if not why:
            continue
        r = run(["tmux", "kill-session", "-t", "=" + s["name"]], timeout=10)
        if r["code"] == 0:
            ended.append(s["name"])
            print(f"dashboard: compat: ended {s['name']} ({why})", flush=True)
    if not NODES_OK:
        for nid, (nname, sess) in nodes.node_sessions().items():
            for s in sess:
                real = str(s.get("name") or "")
                why = wanted.get(tmux_base(real))
                if not why:
                    continue
                nodes.session_kill(nid, real)
                ended.append(real)
                print(f"dashboard: compat: ending {real} on {nname} ({why})", flush=True)
    return ended


def _compat_loop():
    while True:
        try:
            compat_reap_once()
        except Exception as e:        # noqa: BLE001 (a sweeper must not die)
            print(f"dashboard: compat: {e}", flush=True)
        time.sleep(max(1.0, COMPAT_SWEEP_S))


# What a new project may be called. It becomes a directory under /workspace and
# part of a tmux session name, so it gets the strictest charset here: one path
# segment, starting with a letter or digit, which also rules out dotfiles
# and `..`. Where a clone may come from is forges.URL, next door: the
# same allowlist reasoning (`git clone` accepts transports a browser form must
# never reach, like `ext::`, which runs commands) applied to more than one host.

# The builder user's ssh directory. Overridable through BUILDER_HOME for the
# same reason CLAUDE_PROJECTS is: the tests point it at a scratch home, and
# nothing they write may land in the real one.
SSH_DIR = Path(os.environ.get("BUILDER_HOME", str(Path.home()))) / ".ssh"


def agent_keys():
    """[{name, pub}] for every key the shielded agent holds.

    ssh-add -L prints the *public* halves, the one part of a shielded key
    that is meant to be shown around. The name is the key's comment (the
    filename it was loaded from), sanitized to the same charset as a project
    name because it becomes a filename and a host alias here. A key whose
    comment does not survive that is skipped, not mangled: it cannot be
    addressed unambiguously, and these names face the operator.
    """
    r = run(["ssh-add", "-L"], timeout=10)
    if r["code"] != 0:
        return []                         # no agent, or an empty one
    keys = []
    for line in r["out"].splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2 or not parts[0].startswith(("ssh-", "ecdsa-", "sk-")):
            continue
        name = os.path.basename(parts[2].strip()) if len(parts) > 2 else ""
        if PROJECT_NAME.fullmatch(name) and name not in {k["name"] for k in keys}:
            keys.append({"name": name, "pub": line.strip()})
    return keys


def gh_authed():
    """Whether git-over-https can authenticate, i.e. whether a PAT is wired up.

    Asked of gh rather than the environment, because gh is what actually
    answers the credential prompt (`gh auth setup-git` at startup): this is
    true exactly when an https remote will work, which only a `gh auth login`
    typed in a shell makes so. `gh auth token` is offline and instant;
    `gh auth status` phones home.
    """
    return run(["gh", "auth", "token"], timeout=10)["code"] == 0


def ensure_deploy_alias(name, pub, host):
    """A per-repo ssh alias for one agent key on one host, created
    idempotently; returns the alias.

    Why an alias at all: deploy keys are scoped to a single repository, and
    ssh offers every agent key in order: the host authenticates the first
    valid one and then refuses the repo it does not belong to. The fix is
    IdentitiesOnly plus an IdentityFile naming the *public* half, which acts
    purely as a selector for the agent key (the private half stays shielded).

    The host is in the alias because one key can serve two of them: the same
    ed25519 on GitHub and on the Gitea in the cupboard is two different
    HostName lines, and an alias named after the key alone could only ever
    carry one of them.

    Everything written lives in a namespace of our own (bb_<name>.pub and
    Host bb-<name>-<host>), so a .pub or an alias the operator maintains by
    hand is never touched, and rewriting ours is always safe.

    The lock makes the check-then-append on ~/.ssh/config actually atomic:
    two concurrent requests using the same key would otherwise both miss the
    marker and both append the block. ssh would still behave (first match
    wins), but "idempotent" should not mean "single-threaded".
    """
    alias = f"bb-{name}-{forges.slug(host)}"
    with _ssh_lock:
        return _ensure_deploy_alias(alias, name, pub, host)


_ssh_lock = threading.Lock()


def _ensure_deploy_alias(alias, name, pub, host):
    SSH_DIR.mkdir(mode=0o700, exist_ok=True)
    pub_path = SSH_DIR / f"bb_{name}.pub"
    try:
        current = pub_path.read_text()
    except OSError:
        current = None
    if current != pub + "\n":
        pub_path.write_text(pub + "\n")
    cfg = SSH_DIR / "config"
    # The marker carries the alias, not the key: one key on two hosts is two
    # blocks, and a marker naming only the key would write the first and call
    # the second already done.
    marker = f"# builderbot:deploy-key:{alias}"
    try:
        have = cfg.read_text()
    except OSError:
        have = ""
    if marker not in have:
        hostname, _, port = host.partition(":")
        block = (f"\n{marker}\nHost {alias}\n"
                 f"    HostName {hostname}\n"
                 + (f"    Port {port}\n" if port.isdigit() else "")
                 + f"    IdentityFile {pub_path}\n"
                 f"    IdentitiesOnly yes\n")
        with open(cfg, "a") as f:
            f.write(block)
        os.chmod(cfg, 0o600)
    return alias


def _remote_host(remotes):
    """The real host behind the first remote in `git remote -v` output.

    Not the host as written: the standard multi-deploy-key setup (including
    the bb- aliases this dashboard's own clone and link flows write) hides
    the server behind a ~/.ssh/config Host alias, so the URL says `bb-key-x`
    and only that file knows what it stands for. forges.host_of resolves it
    with `ssh -G`, which reads the config and touches no network.
    """
    for line in remotes.splitlines():
        parts = line.split()
        if len(parts) >= 2 and forges.parse(parts[1]):
            return forges.host_of(parts[1])
    return ""


# A directory holding this file is not a project: not listed, not offered a
# Claude session, not counted. Written by the container into its own paths
# under the projects share, and by hand for anything else.
IGNORE_MARKER = ".bbignore"


def _session_nodes(name):
    """One row per node the project works on, for the chooser a Claude press
    opens when there is more than one (R82): where a session there would
    stand (node or refused, with the why), the node's boot for the tab, and
    what the machine has and how busy it is, so the pick is a read. A
    project on one node gets its one row too, so its chooser says what that
    machine has as well (the operator, 30 Sep); [] for a project on none."""
    p = prefs.get(name) or {}
    set_ = p.get("nodes") or ([p["node"]] if p.get("node") else [])
    if not set_:
        return []
    out = []
    for nid in set_:
        t = session_target(name, claude=True, node=nid)
        n = nodes.node(nid) or {}
        rep = n.get("reported") or {}
        out.append({"id": nid, "name": n.get("name") or t.get("name") or nid,
                    "where": t["where"], "why": t.get("why") or "", "boot": t.get("boot") or "",
                    "sample": rep.get("sample") or {}, "gpu": rep.get("gpu") or "",
                    "tools": sorted((rep.get("toolchains") or {}).keys())[:6]})
    return out


def _session_at(name):
    t = session_target(name, claude=True)
    if t["where"] == "node":
        # The node's boot, for the page to stamp into a terminal's URL in
        # place of this container's: bb-tty on the node compares against the
        # node's own run, and a tab carrying the controller's boot was
        # refused there as "from before the container restarted" on every
        # connection, a loop nobody could end from the Sessions card,
        # because the session never started.
        return {"session_at": t["name"], "session_why": "",
                # ...and its id, which is what the page asks its own Claude
                # sign-ins about: a login is one account's on one node.
                "session_node": t["id"],
                "session_boot": t.get("boot") or ""}
    if t["where"] == "refused":
        return {"session_at": t["name"], "session_why": t["why"], "session_node": "", "session_boot": "",
                # A wait that passes on its own (a node reconnecting after a
                # restart, a mount landing after boot): drawn quietly.
                "session_waiting": bool(t.get("waiting"))}
    return {"session_at": "", "session_why": "", "session_node": "", "session_boot": ""}


def _row_git_ready(base, over):
    """Whether a commit on this project would carry an author, for one row."""
    g = users.identity_over(base, over)
    return bool(g["name"] and g["email"])


# What git says of each project, kept until what it depends on moves (R94):
# three git forks per project on every /api/status, about sixty a poll on a
# controller with twenty projects, and the status poll at 1.3s on average
# (12 Oct). Keyed on what .git/HEAD says, .git/config's size and time and
# .git's time: a branch switch rewrites HEAD and a remote change config, so
# either asks git again; a .git that is a file (a worktree) is asked every
# time, and nothing is kept longer than GIT_FACTS_S.
GIT_FACTS_S = 60.0
_git_facts_kept = {}


def _git_stamp(d):
    # HEAD by its contents, a few bytes that are the branch itself, since a
    # share that keeps times to the second would not tell two switches in
    # one second apart; config by its size and time, and .git's time.
    g = d / ".git"
    try:
        if not g.is_dir():
            return None
        c = (g / "config").stat()
        return ((g / "HEAD").read_bytes()[:512], c.st_size, c.st_mtime_ns, g.stat().st_mtime_ns)
    except OSError:
        return None


def _git_facts(d):
    """(git_ok, linked, fhost, forge, github, branch) for one project."""
    stamp = _git_stamp(d)
    hit = _git_facts_kept.get(str(d))
    if stamp is not None and hit and hit[0] == stamp and time.time() - hit[1] < GIT_FACTS_S:
        return hit[2]
    branch, git_ok, linked, github, fhost, forge = None, False, True, False, "", forges.OTHER
    if (d / ".git").exists():
        # Asking git rather than trusting the directory's existence: a
        # half-copied or corrupt .git looks identical from out here, and a
        # repo git cannot read is not one anything can act on.
        git_ok = run(["git", "-C", str(d), "rev-parse", "--is-inside-work-tree"],
                     timeout=10)["out"].strip() == "true"
    if git_ok:
        # Asked of git, not read out of .git/config: a worktree or a
        # submodule keeps its config elsewhere, and these drive visible
        # controls (the chain on the row; the GitHub command card's
        # ghosting), so a wrong guess here offers an action that cannot
        # work. -v for the URLs, which is what says which host it is on.
        remotes = run(["git", "-C", str(d), "remote", "-v"], timeout=10)["out"]
        linked = bool(remotes.strip())
        # Which forge, for the chain's own words, and `github` still on its
        # own, because the command card runs `gh` and that is GitHub's and
        # nobody else's.
        fhost = _remote_host(remotes) if linked else ""
        forge = forges.forge_of(fhost)
        github = fhost.lower().split(":")[0] == "github.com"
        r = run(["git", "-C", str(d), "symbolic-ref", "--short", "-q", "HEAD"], timeout=10)
        # `out` carries stderr too, so a detached HEAD would otherwise put a
        # `fatal:` line where the branch name goes.
        branch = (r["out"].strip() or "(detached)") if r["code"] == 0 else "(detached)"
    facts = (git_ok, linked, fhost, forge, github, branch)
    if stamp is not None:
        _git_facts_kept[str(d)] = (stamp, time.time(), facts)
    return facts


def _projects_on_disk():
    """The directories under /workspace that are projects, each with what is
    wrong with it: the walk, the permissions, and what git says of the
    repository. One dict of facts per project (`dir`, `name`, `issues`,
    `git`, `git_ok`, `linked`, `github`, `fhost`, `forge`), for
    _project_columns to dress into the row the page reads, plus the list
    to hand back as it stands when there is nothing to walk: no workspace,
    or one this user cannot list. Nothing here asks who is looking; that is
    _projects_seen_by, and the split is the point: this stays one
    description of the share.
    """
    out = []
    uid, gid = os.getuid(), os.getgid()
    try:
        if not WORKSPACE.is_dir():
            return out, out
    except OSError:
        pass                    # unreadable: reported by the listing below
    try:
        here = sorted(WORKSPACE.iterdir())
    except OSError:
        # A workspace this user cannot list is a mount to fix, not a reason for
        # the runner card and the terminal to stop working too.
        return out, [{"name": str(WORKSPACE), "git": None,
                      "last_claude": None,
                      "issues": [{"level": "error",
                                  "text": f"cannot list this directory as uid {uid}:{gid}"
                                          "; chown it to PUID:PGID on the host"}]}]
    cloning = projects.busy_name()
    # Only what BuilderBot made (R154, the operator 8 Oct): a folder made by
    # hand on the share is not a project, and Import is the way one comes in.
    registry.sync()
    for d in here:
        if not registry.is_project(d.name):
            continue
        # Mid-clone: a directory with a .git and not much else, which every
        # check below reads as a repository in a strange state. The job row is
        # already saying what it really is.
        if d.name == cloning:
            continue
        # Hidden directories are not projects: the whole projects folder is
        # mounted now, so this list would otherwise open with the share's own
        # furniture (.Recycle.Bin and friends) presented as things to fix.
        #
        # .bbignore is the general form of the same idea, and the one thing
        # here an operator can drive: a directory holding that file is not a
        # project and is not listed. The container drops it into any path of
        # its own that lands inside the projects share (the toolchain store, when
        # someone maps it inside the projects folder rather than beside it),
        # and anyone can create one by hand for a directory they would rather
        # not see. It hides; locking a project is the thing that *blocks*, and
        # that is a different control with a different guarantee.
        if (not d.is_dir() or d.name.startswith(".")
                or (d / IGNORE_MARKER).exists()):
            continue
        issues = []

        # Permissions first, and reported even when everything after fails.
        # A directory this user cannot read also fails the git check below, so
        # checking git first would file a permissions problem as "not a repo"
        # and hide it under the rule that never shows those.
        missing = [n for n, m in (("read", os.R_OK), ("write", os.W_OK), ("enter", os.X_OK))
                   if not os.access(d, m)]
        if missing:
            issues.append({"level": "error",
                           "text": f"cannot {', '.join(missing)} this directory as "
                                   f"uid {uid}:{gid}; chown it to PUID:PGID on the host"})

        # Path.is_file() only swallows ENOENT/ENOTDIR/EBADF/ELOOP; EACCES is
        # re-raised, so an unreadable project directory took out the whole
        # status endpoint rather than being reported as the one thing wrong.

        # linked defaults to True and github to False: each gates an offered
        # action (the chain on the row; the GitHub command buttons), and a
        # project this loop could not examine must get no offer rather than a
        # broken one, which is the opposite default for the two. The forge
        # defaults with them, and to the entry that promises nothing.
        branch, git_ok, linked, github = None, False, True, False
        fhost, forge = "", forges.OTHER
        if not missing:
            # An empty directory is the one thing never reported. It is not a
            # problem to fix but a mount point waiting for content, or a
            # leftover, and flagging it would be noise on every boot.
            try:
                if not any(d.iterdir()):
                    continue
            except OSError:
                pass                    # unreadable: covered by `missing` above

            git_ok, linked, fhost, forge, github, branch = _git_facts(d)
            if not git_ok:
                issues.append({"level": "error", "text": "no valid git repository"})

        out.append({"dir": d, "name": d.name, "issues": issues, "git": branch,
                    "git_ok": git_ok, "linked": linked, "github": github,
                    "fhost": fhost, "forge": forge})
    # Two projects whose names slug alike are one dev instance: `My.App` and
    # `my-app` both slug to my-app, which is one compose project name, one env
    # file and one data directory driven by two rows that know nothing about
    # each other. Nothing owns the moment a directory appears under /workspace,
    # so it cannot be refused the way a container's name is, but this is the
    # only place that sees every name at once, which makes it the only place
    # that can say so at all.
    #
    # A warning, not an error: both projects are real and everything except the
    # dev instance works. An error would take them out of findings attribution
    # and off the Claude button, which would be a bigger fault than the one
    # being reported.
    by_slug = {}
    for row in out:
        by_slug.setdefault(devapp._slug(row["name"]), []).append(row)
    for slug, rows in by_slug.items():
        if len(rows) < 2:
            continue
        for row in rows:
            others = ", ".join(r["name"] for r in rows if r is not row)
            row["issues"].append({
                "level": "warning",
                "text": f"this name and {others} both shorten to “{slug}”: a "
                        f"dev instance of either is the same containers, env "
                        f"file and data directory. Rename one before using it"})
    return out, None


def _project_columns(who, facts):
    """The row the page reads for each project _projects_on_disk found: its
    facts, and everything else a row carries. The project's own settings
    and this account's own on it, where its sessions run and why nothing
    runs there right now, the notebook's counts, the newest transcript.
    Every file that serves the whole list is read once here rather than per
    row: this runs on the fifteen-second poll.
    """
    locked = set(projects.load_locks())
    # Each directory's id and the name it is shown under (R154): synced with
    # the disk here, two listdirs and no write when nothing moved.
    reg = registry.sync()["projects"]
    pins = projects.load_project_pins(users.uid_of(who), users.starts_unpinned(who))
    # One small file for the whole list, read here rather than per row: this
    # runs on the fifteen-second poll and a per-project read would be a dozen
    # opens for a dozen values that came from the same dictionary.
    # With the workspace, so each row also says what `bb test` would run
    # there with nothing set; the settings field offers it as what an
    # empty box means.
    project_prefs = prefs.all_projects(WORKSPACE)
    # ...and, in one read each, what the ACCOUNT ASKING chose per project and
    # the author its commits carry with nothing overridden. The model, the
    # effort and the commit identity are the person's, not the directory's
    # (prefs.for_user), so they are resolved against `who` here rather than
    # read off the project.
    mine_prefs = prefs.all_for_user(users.uid_of(who))
    base_git = users.git_identity(who)
    # One answer per node about its agent, for every project row on it.
    node_gaps = {}
    # ...and its name, for the row to wear beside the project's.
    node_names = {}
    # ...and which of them were un-enrolled: a project left on one keeps it,
    # named, so the person can see where it used to run (the operator, 5 Oct).
    removed_nodes = set()
    if not NODES_OK:
        for n in nodes.node_list(all=True):
            node_names[n["id"]] = n["name"]
            if n["state"] == "retired":
                removed_nodes.add(n["id"])
                continue
            if n["kind"] == "agent" and n.get("live"):
                why = nodes.agent_stale(n)
                if why:
                    node_gaps[n["id"]] = why
    # ...and the phone each node has, from one read (R120): a row's Phone
    # button and the lease line it shows everybody on the project.
    phones = phone.by_node(users.uid_of(who))
    # ...and the sharper answer for the Claude button: a node from another
    # WINDOW holds this project's sessions; one merely behind does not.
    held_nodes = node_holds()
    open_roadmap = roadmap.counts()
    # One batch spans the notebook, so the count the panel shows has to be
    # both halves added up; a banner reporting only the roadmap's would read
    # as "nothing much" while a dozen tracker changes sat unrecorded.
    roadmap_batches = roadmap.batches()
    for name, b in bugs.batches().items():
        if name in roadmap_batches:
            roadmap_batches[name]["changes"] += b.get("changes", 0)
            roadmap_batches[name]["at"] = min(roadmap_batches[name]["at"], b["at"])
        else:
            roadmap_batches[name] = b
    # Counts only. The notebook's six revisions used to ride here, which put
    # half of one tab on this fifteen-second poll while the other half rode
    # /api/revs at a second and a half; they are all on /api/revs now (see
    # revisions()), and this poll stopped paying to compute them.
    bug_counts = bugs.counts()          # open bugs per project, for the row and the app
    test_counts = testreg.counts()
    rule_counts = rules.counts()
    # What a session has waiting for the operator (roadmap #27): the count
    # lights the bell and the notebook band.
    pend_counts = pending.counts()
    out = []
    for f in facts:
        d, issues = f["dir"], f["issues"]
        branch, git_ok, linked, github = f["git"], f["git_ok"], f["linked"], f["github"]
        fhost, forge = f["fhost"], f["forge"]
        # Every directory is still reported. The dashboard decides what to show,
        # and SARIF paths are attributed by matching these names, so dropping
        # one here would silently orphan its findings.
        # Locking is reported by the boolean below and nothing else. It used to
        # add an issue too, which the row printed under the name: a whole
        # sentence restating what the padlock beside the name already says, on
        # every locked row, forever. It is also not a fault, and the issue list
        # is where faults go.
        sa = _session_at(d.name)
        sa["session_nodes"] = _session_nodes(d.name)
        mem_census = memory.census(d.name, home=home_for(users.uid_of(who)))
        out.append({"name": d.name, "git": branch, "git_ok": git_ok,
                    # The name people see and the project's id (R154); `name`
                    # stays the directory, which every store keys by.
                    "label": str((reg.get(d.name) or {}).get("name") or d.name),
                    "pid": int((reg.get(d.name) or {}).get("id") or 0),
                    "linked": linked, "github": github,
                    # Which host it is linked to, for the chain to say so in
                    # its own words. "" when there is no remote to be on, and
                    # the ADDRESS rather than the catalog's generic label when
                    # nobody has said what that server runs: "Unlink from
                    # Another git host" names nothing a person could check.
                    "forge": forge["id"] if linked else "",
                    "forge_name": ("" if not linked
                                   else forge["name"] if forge["id"] != forges.OTHER["id"]
                                   else fhost or forge["name"]),
                    "forge_host": fhost,
                    "locked": d.name in locked,
                    "pinned": True if pins is None else d.name in pins,
                    # Whether it carries its own access token, so the rename
                    # dialog can offer to change one without offering to
                    # invent one for a local repo that never had any.
                    "has_token": (STATE / "gitcreds" / d.name).is_file(),
                    # A brief waiting for the first Claude session: the
                    # Claude button opens its dialog rather than a session.
                    "brief": brief.pending(d.name),
                    "push": projects.may_push(d.name),
                    # The project's own settings: its node, what build and
                    # test run, the gates. NOT the model, the effort or the
                    # commit author, which are whoever is asking's.
                    "prefs": project_prefs.get(d.name, {}),
                    # Who may move its version (version.py's policy), for the
                    # settings panel's Move the version dial.
                    "version_policy": version.policy(d.name),
                    # ...and this account's own, on this project. On the row
                    # because the settings dialog draws from the poll like
                    # every other field it shows, and per account because two
                    # people on one project are two authors on two models.
                    # `yours`, because `mine` on this row is already taken by
                    # may_work: whether the project is this account's to change.
                    "yours": mine_prefs.get(d.name, {"model": "", "effort": "", "reply": "", "asks": "",
                                                     "git_name": "", "git_email": ""}),
                    # Whether a commit here would carry an author, asked WITH
                    # the override: somebody whose Profile has no email can
                    # still set one for this project, and then a session may
                    # start and push here even though the global flag is off.
                    "git_ready": _row_git_ready(base_git, mine_prefs.get(d.name))
                                 if users.uid_of(who) else True,
                    "push_how": projects.push_how(d.name),
                    # Whether this project has a compose file, which is the
                    # same question as "could its tests run in a container of
                    # its own": the settings dialog offers that choice only
                    # where there is something to run in (R68 step 6).
                    "has_compose": devapp.project_has_compose(d.name),
                    # The newest transcript, read through the home's link
                    # onto the projects share (lib/common.sh's
                    # claude_projects_link), so a conversation a node's
                    # session had is offered here and continued there.
                    "last_claude": last_claude(d, users.uid_of(who)),
                    # Where this project's sessions run (roadmap #24): the
                    # node's name, or "" for here, and why the button is
                    # dead when its node cannot take one. The proxy decides
                    # the same way, so the row and the refusal agree.
                    **sa,
                    # What Claude remembers here. On the row because a memory
                    # nobody knows about is the one that goes wrong quietly.
                    "memories": mem_census["count"],
                    # ...and what is still to do, which is the number on the row
                    # actually worth glancing at.
                    "roadmap": open_roadmap.get(d.name, 0),
                    # So the open notebook learns a session has started one
                    # without waiting for the operator to touch something.
                    "todo_batch": roadmap_batches.get(d.name),
                    "bugs": bug_counts.get(d.name, 0),
                    "tests": test_counts.get(d.name, 0),
                    # The test run going right now, if `bb test` said so:
                    # {since, cmd, by}, or null. The companion app times
                    # its turn note by it and the project's During-a-test-run
                    # setting.
                    "testing": testreg.running(d.name),
                    "rules": rule_counts.get(d.name, 0),
                    "pending": pend_counts.get(d.name, 0),
                    # Why nothing routed to this project's node runs right
                    # now (its agent behind, or from another window), so
                    # the Artifacts tab and the bell say so before a job is
                    # refused. "" is the ordinary state.
                    "node_gap": node_gaps.get(project_prefs.get(d.name, {}).get("node") or "", ""),
                    # Which node this project's work runs on, by name, or ""
                    # for none: the row says "(node: X)" beside the name.
                    "node_name": node_names.get(project_prefs.get(d.name, {}).get("node") or "", ""),
                    # The project's node was un-enrolled: the settings picker
                    # keeps it, marked, and the row says why Claude is off.
                    "node_removed": (project_prefs.get(d.name, {}).get("node") or "") in removed_nodes,
                    # The phone on its node: whose, whether it is this
                    # account's, and whom it is lent to (R120).
                    "phone": phones.get(project_prefs.get(d.name, {}).get("node") or ""),
                    # Why no Claude session may run here right now, or "":
                    # its own node's agent is from another compatibility
                    # window. The button ghosts on this and bb-tty refuses on
                    # the same fact; the sweep ends what is running. Per
                    # project: another project's node being out of window is
                    # not this row's hold.
                    "held": held_nodes.get(
                        project_prefs.get(d.name, {}).get("node") or "", "")
                    # ...or its map is still building (mapping.py): the
                    # same ghosting, for the seconds it takes.
                    or mapping.held(d.name),
                    "issues": issues})
    return out


def _projects_seen_by(who, rows):
    """Which of the rows the account asking may see at all, and which of
    those are its to work on (`mine`, users.may_work). The one decision
    about who sees what, made last, over rows that were described without
    regard to it.
    """
    # The last thing, so everything above it stays one description of the
    # share and this stays one decision about who sees it.
    #
    # Two decisions now, and they are different questions. A `user` is shown
    # only what it was given, because a project it cannot work on is one it
    # has no reason to know exists. An ADMINISTRATOR is shown everything and
    # told which of them are theirs to change: hiding a project from somebody
    # who administers the box would only send them looking for it, and the
    # list they keep is a seatbelt against editing the wrong one rather than a
    # wall (users.may_work).
    if not users.sees_all(who):
        allow = set((who or {}).get("projects") or [])
        rows = [p for p in rows if p["name"] in allow]
    for p in rows:
        p["mine"] = users.may_work(who, p["name"])
    return rows


def project_list(who):
    """Every directory under /workspace that is a project, with what is wrong
    with it. Named _list because `projects` is the module beside this one that
    creates them: one name for the reading and one for the writing.

    `who` is the account asking (Handler._who()), and it is REQUIRED rather
    than defaulted for the reason the whole scheme leans on: this is the one
    function that decides which projects exist, and a call site that forgot to
    say who was asking would quietly show every project to everybody. Missing
    it is a TypeError, which a test finds; defaulting it would be a hole
    nothing finds. The server's own non-request contexts pass users.ALL and
    say so.

    Filtering here is also most of the authorization. Fifteen handlers ask
    "is this a project?" against this list, so a project somebody cannot see
    is not refused to them: it does not exist, which is the same answer a
    typo gets and leaks nothing by comparison.
    """
    facts, fault = _projects_on_disk()
    if fault is not None:
        return fault
    return _projects_seen_by(who, _project_columns(who, facts))


def session_cwds():
    """Session name -> {cwd, title} of its active pane.

    cwd is where a terminal *is* right now, which is not where it was opened:
    the tab is labeled from this, so a `cd` shows up in the strip. The pane
    title rides along because for Claude sessions it is a status report;
    see claude_state below.
    """
    # Title last and split bounded, so a title containing a tab cannot shift
    # the fields before it.
    r = run(["tmux", "list-panes", "-a", "-F",
             "#{session_name}\t#{pane_active}\t#{pane_current_path}\t#{pane_title}"],
            timeout=10)
    out = {}
    if r["code"] != 0:
        return out
    for line in r["out"].splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4 and parts[1] == "1":
            out[parts[0]] = {"cwd": parts[2], "title": parts[3]}
    return out


# Claude Code reports its state through the terminal title, and tmux keeps
# that per pane. Observed lifecycle (verified against a live session, not
# guessed from docs): a working session's title starts with an animated
# spinner glyph and the task summary ("◐ Fix the login flow"); one waiting
# for input starts with ✳ ("✳ Claude Code" fresh, "✳ Fix the login flow"
# after a turn). Before the REPL (trust dialog, theme picker) no title is
# set at all, which the spinner rule correctly reads as "waiting": those
# screens are waiting for input.
#
# Activity timestamps are deliberately NOT the signal here: the TUI goes
# quiet while a long tool call runs, so "no output lately" cannot tell a
# session hard at work from one sitting at the prompt.
SPINNER_GLYPHS = tuple("◐◓◑◒")


def gpu_for(project, node_id=""):
    """Whether a session on `project` may compute on its node's NVIDIA card
    (R102): "on"; "node" when the node's switch is off; "project" when the
    project's own setting is. The project's says no first, being the
    narrower of the two. The node is the one the session was started on,
    else the project's own."""
    p = prefs.get(project) or {}
    if p.get("gpu") == "off":
        return "project"
    if not NODES_OK:
        nid = node_id or p.get("node") or ""
        n = nodes.node(nid) if nid else None
        if n and (n.get("config") or {}).get("no_gpu_compute"):
            return "node"
    return "on"


def _attention(who):
    """The bell's rows about nodes: an agent behind or from another window
    (nodes.attention) for whoever manages nodes, and a node with a
    toolchain behind what is out, Claude Code among them
    (toolchains.attention), for whoever may install toolchains on it."""
    if NODES_OK:
        return [], 0
    where = {p: (pr.get("node") or "") for p, pr in prefs.all_projects().items()}
    rows = (([] if users.may(who, "node") else nodes.attention(where))
            + [a for a in toolchains.attention(where)
               if not users.may_node(who, "toolchains-write", a["id"])]
            # ...and a node's nginx behind the newest line (nginxproxy.attention,
            # R192), for whoever may act on the Docker tab, which Update is.
            + ([] if users.may(who, "docker-write")
               else nginxproxy.attention(lambda nid: nginxproxy.deployed(devapp, nid))
               # ...and a container whose registry image moved (imagecheck, R195).
               + imagecheck.attention(lambda nid: (nodes.node(nid) or {}).get("name") or nid)
               # ...and a copy or move that did not happen (relocate.py).
               + relocate.attention(lambda nid: (nodes.node(nid) or {}).get("name") or nid)))
    # ...less what this account has put away (bellseen.py, R144): an update
    # to a version it dismissed, until a newer one is out.
    return bellseen.filter_rows(users.uid_of(who), rows)


def _claude_code_for(who, ps):
    """Claude Code per node against the latest known, for the Nodes tab's
    section: the registry's for whoever may manage nodes, and for anybody
    else the nodes their own projects are on, which are the ones that tab
    shows them."""
    cc = claudecode.payload()
    if not users.may(who, "node"):
        return cc
    mine = set()
    for p in ps:
        pr = prefs.get(p["name"])
        mine.update([pr["node"], *(pr.get("nodes") or [])])
    return cc | {"nodes": {k: v for k, v in cc["nodes"].items() if k in mine}}


def gpu_container_why(project, node_id):
    """Why a container of `project` on that node cannot be given its NVIDIA
    card, or "" (R102): the project's setting and the node's switch, which
    speak for containers as they do for sessions, then what the node's
    Toolchains tab holds (the driver running the card, the container
    toolkit, Docker's runtime)."""
    who = gpu_for(project, node_id)
    if who == "project":
        return "this project's settings say the node's GPU is not for it (The node's GPU)"
    n = nodes.node(node_id) if node_id and not NODES_OK else None
    if who == "node":
        return f"{n['name'] if n else 'its node'}'s GPU is switched off for sessions and jobs (Nodes tab, GPU)"
    return toolchains.container_why(n)


def claude_state(title):
    """(state, task) for a Claude pane title: "working" or "waiting"."""
    working = title.startswith(SPINNER_GLYPHS)
    task = title.lstrip("".join(SPINNER_GLYPHS) + "✳ ").strip()
    # A title Claude never set (tmux's hostname default) carries no task; a
    # fresh session's "Claude Code" is a name, not a task.
    if not title.startswith(SPINNER_GLYPHS + ("✳",)) or task == "Claude Code":
        task = ""
    return ("working" if working else "waiting"), task


# The `u:<uid>:` a browser may have sent on a terminal argument, which is
# stripped before the real one is put on. Anchored, so it can only ever take
# a prefix off the front.
_ARG_OWNER = re.compile(r"^u:[^:]*:")
# `:n:NODE` on a claude: argument: which of the project's nodes the person
# picked for this session (R82). Read here and taken off before the proxy,
# since bb-tty on the node reads the argument's tail by suffix (:r:, :b:)
# and would take the node for part of the project's name.
_ARG_NODE = re.compile(r":n:([A-Za-z0-9_-]+)")


def _arg_node(arg):
    m = _ARG_NODE.search(arg or "")
    return m.group(1) if m else ""


def _arg_project(arg):
    """The project a terminal argument is about, or "" (the workspace
    shell, a named scratch session)."""
    if arg.startswith("claude:"):
        return arg[len("claude:"):].split(":")[0]
    if arg.startswith("shell:"):
        return arg[len("shell:"):]
    if arg.startswith("sh:"):
        return arg.split(":", 2)[2] if arg.count(":") >= 2 else ""
    return ""


_hello_asked = {}


def _ask_hello(nid):
    """A fresh census from a node a session was just refused on, at most
    once a minute: the census rides hello every ten minutes, and the retry
    a person makes ten seconds later should reason about the node as it is."""
    now = time.time()
    if now - _hello_asked.get(nid, 0) >= 60:
        _hello_asked[nid] = now
        nodes.ask_hello(nid)


def session_target(project, claude=False, node="", uid=""):
    # `claude` is the question R47 added. A project's SHELL follows its node
    # (the tree is that machine's mount and its toolchains are what a build
    # there uses), and a project with NO node still gets a shell here, on the
    # same share. What it does not get is a Claude session: this container
    # carries no Claude Code, so the answer is a
    # refusal that says what to do rather than a conversation that cannot
    # build anything.
    """Where a session on this project runs (roadmap #24, phase 10b):

        {"where": "local"}                                   (this container)
        {"where": "node", "id", "name", "host", "port", "ro_port"}
        {"where": "refused", "name", "why"}                  (bound to a node
                                                              that cannot take one)

    A project bound to a node whose census says the session half is up and
    whose synced copy of the project is there gets its session THERE. One
    bound to a node that is offline, runs no sessions or has no copy yet is
    REFUSED rather than quietly started here: a session started on the
    wrong machine has the wrong toolchains and its transcripts land in the
    wrong home, and switching later splits a conversation across two boxes. The sentence says which
    of the three it was and what fixes it. A project with no node keeps its
    session here, as it always has.

    Two of the refusals are PASSING (the node is rebooting, or it just
    came up and its network mount has not landed), and the sentence for
    those says to wait, not to unbind the node: the operator who rebooted
    the sandbox and met "add the mount... unbind the node" had nothing to
    add and nothing to unbind. The census is asked for again on the
    strength of any refusal it decided, so the next look is current.

    A Claude session has no second place to run: this container carries no
    Claude Code, so a refusal is the whole answer and the sentence has to
    carry what to do about it. A SHELL still falls back here, which is what
    keeps the tree, the linters and git reachable while a node is away.
    """
    pf = prefs.get(project) if project else None
    nid = (pf or {}).get("node") or ""
    # The node the person picked, when it is one the project works on
    # (R82); any other name falls to the primary rather than to a refusal,
    # since the pick came off a list this side drew.
    if node and node in ((pf or {}).get("nodes") or []):
        nid = node
    # ONE SENTENCE, and not a red one on the page: a project with no node is
    # a normal state, not a fault. `name` is what tells the two apart
    # downstream (empty here, the node's name when a node refused), so the
    # row can say this plainly and keep red for the machine that is broken.
    no_node = {"where": "refused", "name": "",
               # The row says it whole, the fact and then what to do about
               # it (no tooltip carries a second half any more).
               "why": "no node to run a Claude session on: pick one in the project's settings, or enroll "
                      "one on the Nodes tab"} if claude \
        else {"where": "local"}
    if not nid or NODES_OK:
        return no_node
    n = nodes.node(nid)
    if not n or n.get("kind") == "local":
        return no_node
    name = n.get("name") or nid
    rep = n.get("reported") or {}
    se = rep.get("session")
    passing = waiting = False
    if nodes.host_only(n):
        # Made hosting-only after the project named it: no session goes
        # there, whatever the settings still say.
        why = (f"{name} hosts containers only, so no session runs there: pick another node in "
               f"{project}'s settings")
    elif n.get("state") == "retired":
        # Un-enrolled (the operator, 5 Oct): the fact first, then what to do
        # about it, both on the row.
        why = (f"{name} was removed from the Nodes tab. Pick another node in {project}'s settings, "
               "or enroll it again")
        passing = True          # its own sentence says the way on
    elif n.get("state") == "disabled":
        why = f"{name} is disabled on the Nodes tab: Enable it there, or pick another node in {project}'s settings"
    elif n.get("state") != "online":
        why = f"{project}'s sessions run on {name}, which is {n.get('state') or 'not online'}"
    elif n.get("live") is False and _reconnecting(n):
        # The controller has just started and this node was here a moment
        # before: its agent dials in again on its own schedule (two minutes,
        # some days). Said quietly, as a wait, rather than in red as a node
        # that is down (the operator, 7 Oct).
        why = f"{name} is reconnecting after the controller restarted"
        passing = waiting = True
    elif n.get("live") is False:
        # The agent has stopped dialing in: a reboot, an update, a machine
        # that is off. Its tmux sessions are still there when it comes
        # back, and the button comes back with it; nothing to change.
        seen = int((n.get("agent") or {}).get("last_seen") or 0)
        ago = int(time.time() - seen) if seen else 0
        when = (f"{ago // 60} minutes ago" if ago >= 120 else f"{ago} seconds ago") if seen else "never"
        why = (f"{project}'s sessions run on {name}, whose agent is not answering, last heard "
               f"from {when}. If it is restarting, its sessions are back when it dials in")
        passing = True
    elif not isinstance(se, dict):
        why = (f"{project}'s sessions run on {name}, which has not reported a "
               "session half yet; give it a moment, or provision it with "
               "--session-user")
    elif not se.get("up"):
        why = (f"{project}'s sessions run on {name}, which runs none yet"
               + (f": {se['why']}" if se.get("why") else
                  "; provision it with --session-user"))
        _ask_hello(nid)
    elif (n.get("config") or {}).get("leaving") or ((n.get("config") or {}).get("workspace") or "sync") != "sync":
        # Off its synced copy, or on the way off it (R164): nothing to open a
        # session on, and its row on the Nodes tab is the way back.
        why = (f"{project}'s sessions run on {name}, which "
               + ("is leaving its synced copy: what is left there is going up to the controller"
                  if (n.get("config") or {}).get("leaving") else "holds no projects now")
               + ". Its row on the Nodes tab moves it to a synced copy again,"
               " or bind the project to another node")
    elif not ((rep.get("sync") or {}).get(project) or {}).get("ready"):
        # A synced copy (R162) that is not there yet: a session started now
        # would open an empty or half-copied tree.
        got = (rep.get("sync") or {}).get(project) or {}
        why = (f"{project} is being copied to {name}"
               + (f" ({got['copying']} files to go)" if got.get("copying") else "")
               + (f": {got['error']}" if got.get("error") else "")
               + "; the session starts once the copy is there")
        passing = waiting = True
    elif uid and (wt := wssync.worktree_unit(project, uid)) \
            and not ((rep.get("sync") or {}).get(wt) or {}).get("ready"):
        # ...and this account's own worktree of it (B615): a session that
        # opened before it arrived made none of its own there and worked in
        # the owner's tree instead.
        why = (f"your worktree of {project} is being copied to {name}; "
               "the session starts once it is there")
        passing = waiting = True
    elif not se.get("boot"):
        # Without the node's boot the page would stamp this container's into
        # the tab, and bb-tty there would refuse every reconnect as a stale
        # tab (bug #56): a loop, not a session. Dead button, plain reason.
        why = (f"{project}'s sessions run on {name}, whose agent is too old to report "
               "its boot; use Update agent on its row on the Nodes tab, then open this again")
    else:
        return {"where": "node", "id": nid, "name": name, "host": nodes.route_host(nid),
                "port": int(se.get("port") or 0), "ro_port": int(se.get("ro_port") or 0),
                "boot": str(se.get("boot") or "")}
    return {"where": "refused", "name": name, "waiting": waiting,
            "why": why + ("." if passing else
                          ". Sessions run on a node and nowhere else (this container "
                          "carries no Claude Code), so the way on is that machine "
                          "coming back, or another node in the project's settings.")}

# A session name without the account that owns it. Shell sessions are named
# `<uid>~shell-…` since roadmap #26 (two people opening a terminal on one
# project must not land in each other's), and every question of the form
# "does this project still have terminals open" is about the part after the
# `~`, whoever owns it.
_SESS_OWNER = re.compile(r"^u_[0-9a-f]{8}~")


def _chat_summary(who, ps):
    """{online, people, unread, rev} for the chat button, or {} for a
    principal that is not a person."""
    uid = users.uid_of(who)
    if not uid:
        return {}
    store = users.load()["users"]
    mine = (who or {}).get("name", "")
    others = [u.get("uid") for n, u in store.items()
              if u.get("uid") and n != mine]
    seen = users.prefs(who).get("chat_seen") or {}
    return {"online": [n for n in chat.online(_polls) if n != mine],
            "rev": chat.rev(),
            "unread": chat.unread(uid, others, [p["name"] for p in ps], seen),
            # Everybody, not only who is here: a message waiting for somebody
            # who is away is most of what a history is for.
            "people": sorted(n for n in store if n != mine),
            # ...and when each was last here, for the name's "(3h ago)": the
            # newer of this run's polls and the time kept on the record.
            "seen": {n: int(max(_polls.get(n, 0), u.get("seen") or 0)) for n, u in store.items() if n != mine}}


def account_names():
    """{uid: account name} for every account that has an id."""
    return {u.get("uid"): n for n, u in users.load()["users"].items() if u.get("uid")}


def _term_arg(rest):
    """The `arg` a /term request carries, with any owner stamp a browser sent
    taken off. "" when there is none."""
    _, sep, query = rest.partition("?")
    if not sep:
        return ""
    for kv in query.split("&"):
        k, eq, v = kv.partition("=")
        if k == "arg" and eq:
            return _ARG_OWNER.sub("", urllib.parse.unquote_plus(v))
    return ""


def _session_visible(name, mine, seen, all_of_them):
    owner, base = tmux_owner(name), tmux_base(name)
    if owner:
        return owner == mine            # a shell belongs to exactly one account
    if all_of_them:
        return True
    # Unowned: a Claude session, or a terminal from before accounts. Judged by
    # the project in its name, which is what the account was or was not given.
    for pre in ("claude-", "shell-"):
        if base.startswith(pre):
            stem = base[len(pre):]
            return any(tmux_name(p) == stem or stem.startswith(tmux_name(p) + "-")
                       for p in seen)
    return False


_homes = {}


def home_for(uid):
    """Where that account's home is, from lib/common.sh's user_home.

    Shelled out to rather than reimplemented, because bb-tty calls the same
    function to decide where a terminal runs: two implementations of "where
    does this person's Claude login live" would eventually disagree, and the
    way you would find out is somebody signing in and the session not seeing
    it. Empty on any failure, which every caller reads as "the box's own".
    """
    lib = HERE.parent / "lib" / "common.sh"
    if not uid or not lib.is_file():
        return ""
    # Remembered, because this is on the status poll and the answer cannot
    # move: an account's home is derived from an id that never changes. The
    # first call per account also CREATES the directory, which is the other
    # reason not to do it fifteen times a minute per browser.
    if uid in _homes:
        return _homes[uid]
    r = run(["bash", "-c", f'. {shlex.quote(str(lib))}; user_home "$1"',
             "_", str(uid)], timeout=10)
    got = (r.get("out") or "").strip() if r.get("code") == 0 else ""
    if got:
        _homes[uid] = got
    return got


def tmux_base(name):
    return _SESS_OWNER.sub("", str(name))


def tmux_owner(name):
    m = _SESS_OWNER.match(str(name))
    return m.group(0)[:-1] if m else ""


def tmux_sessions():
    r = run(["tmux", "list-sessions", "-F", "#{session_name}\t#{session_attached}"],
            timeout=10)
    if r["code"] != 0:
        return []          # no server running yet is the normal empty case
    panes = session_cwds()
    rows = []
    for line in r["out"].splitlines():
        if "\t" in line:
            name, attached = line.split("\t", 1)
            info = panes.get(name, {})
            row = {"name": name, "attached": attached.strip() not in ("", "0"),
                   "cwd": info.get("cwd", "")}
            # By the unprefixed name, the way node rows are read, so another
            # account's session here says whether it is working too.
            if tmux_base(name).startswith("claude-"):
                state, task = claude_state(info.get("title", ""))
                row["claude"] = {"state": state, "task": task}
            rows.append(row)
    return rows


def claude_working(project, uid):
    """Whether that account's Claude session on this project is mid-prompt,
    here or on a node, by its pane title (claude_state). The owner's is the
    bare name, as everywhere else on the page."""
    want = claude_session(project)
    owner = users.uid_of(users.get(users.owner_name() or ""))
    return any(tmux_base(s["name"]) == want and (tmux_owner(s["name"]) or owner) == uid
               and (s.get("claude") or {}).get("state") == "working"
               for s in tmux_sessions() + node_tmux_sessions())


def sessions_anywhere():
    """Every Claude session's page name, here and on the nodes: what the
    notebook's Send to Claude has to choose from. Since sessions moved onto
    nodes (roadmap #24) the local half is the harness's and the node half
    is everybody's, and a list of only the first told every project it had
    no session while its own row showed one."""
    return [s["name"] for s in tmux_sessions()] + [s["name"] for s in node_tmux_sessions()]


def session_tokens_for(nid, sessions):
    """[{project, uid, token}] for the Claude sessions alive on one node.

    A session's token slides forward on every answer it gets, so one that is
    working never runs out. One that sits idle past twelve hours has nothing
    to slide it, and a dead token is deliberately never renewed: that refusal
    is what makes the life mean anything for a token that leaked. So the
    machine the session is running on is told a fresh one on its heartbeat,
    and a token then lives exactly as long as its tmux session does (R27).

    Matched from the PROJECT towards the session name, never the other way:
    tmux rewrites `.` and `:` in a name, so `ep.silon` runs as
    `claude-ep_silon` and the project cannot be read back out of it.
    """
    want = {}
    for p in project_list(users.ALL):
        want[claude_session(p["name"])] = p["name"]
    out = []
    seen = set()
    for row in sessions if isinstance(sessions, list) else []:
        real = str((row or {}).get("name") or "")
        uid, base = tmux_owner(real), tmux_base(real)
        project = want.get(base)
        if not uid or not project or (uid, project) in seen:
            continue
        seen.add((uid, project))
        out.append({"project": project, "uid": uid,
                    "token": users.mint_session(project, uid=uid)})
    return out[:64]


def node_tmux_sessions():
    """The sessions running on nodes (roadmap #24), shaped like this
    container's own so the Sessions card, the project rows and claude_with
    read them the same way, plus `node`, the name of the machine.

    NAMED BY THIS CONTAINER'S RULE. On a node every account is prefixed,
    the owner included; here the owner's sessions are the bare names, and
    everything on the page (the row's "is my session live", the labels,
    the kill dialog) is written against that. So the owner's node sessions
    are shown bare, and `node_name` keeps what the node calls it, which is
    what a kill has to send back. Nothing on a node is unowned, so an
    unprefixed name there is not a session of anybody's and is dropped.
    """
    if NODES_OK:
        return []
    owner = users.uid_of(users.get(users.owner_name() or "")) if users.owner_name() else ""
    rows = []
    for nid, (nname, sess) in nodes.node_sessions().items():
        for s in sess:
            real = s.get("name") or ""
            who = tmux_owner(real)
            if not who:
                continue
            name = tmux_base(real) if who == owner else real
            row = {"name": name, "node_name": real, "node": nname, "node_id": nid,
                   "attached": bool(s.get("attached")), "cwd": s.get("cwd", "")}
            if tmux_base(real).startswith("claude-"):
                state, task = claude_state(s.get("title", ""))
                row["claude"] = {"state": state, "task": task}
            rows.append(row)
    return rows


def project_busy(name, verb):
    """Why a project cannot be trashed right now, or "": its own
    terminals open, since a live session holds the directory as its working
    directory and would carry on writing wherever it went, or its dev
    instance's containers up, bound to paths that would stop existing.
    Refusals rather than things to tidy away: ending either on the
    operator's behalf is a bigger decision than the one being asked for.
    Here rather than in projects.py because these are the two that see
    outside the filesystem: tmux, and the daemon."""
    live = {s["name"] for s in tmux_sessions()}
    held = sorted(s for s in live
                  if tmux_base(s) == claude_session(name)
                  or tmux_base(s).startswith(tmux_name(f"shell-{name}") + "-"))
    if held:
        return ("close its terminals first: " + ", ".join(held[:3])
                + (" …" if len(held) > 3 else ""))
    # No daemon, or no compose file: nothing to protect. Broad because
    # the check reads the daemon, the store and the compose file, and
    # none of those failing is a reason to keep the project; logged, so
    # a trash that went past a fault says so.
    try:
        holds = devactions.state(name).get("exists")
    except Exception as e:                          # noqa: BLE001
        print(f"[dashboard] {verb} {name}: instance check skipped: "
              f"{type(e).__name__}: {e}", flush=True)
        holds = False
    if holds:
        return "its dev instance still has containers; press Down on the Artifacts tab first"
    return ""


def owner_session_open(project):
    """Whether the owner's Claude session is open in the project directory,
    here or on a node: every other account's wears its prefix (tmux_owner).
    What a branch switch waits for (git.in_use)."""
    mine = claude_session(project)
    return any(tmux_base(s["name"]) == mine and not tmux_owner(s["name"])
               for s in tmux_sessions() + node_tmux_sessions())


def node_heart(n):
    """(tmux names working, when that was seen) from a node's last heartbeat:
    a Claude pane whose title carries the spinner. A node that has stopped
    answering shows nothing working, since what it said last is not true any
    more."""
    rep = n.get("reported") or {}
    heart = set()
    if n.get("live"):
        for r in rep.get("sessions") or []:
            name = str((r or {}).get("name") or "")
            if tmux_base(name).startswith("claude-") \
                    and claude_state(str((r or {}).get("title") or ""))[0] == "working":
                heart.add(name)
    return heart, float((rep.get("sample") or {}).get("at") or 0)


def turn_scope(project, uid):
    """(node id, key, limit, heart, at) for a turn of `uid`'s session on
    `project` (turns.py), or None when there is no node to count on: the
    project runs on no agent node, so nothing here is the machine a session
    works on. The key is the session's tmux name on the node, which is what
    the heartbeat reports it as."""
    if NODES_OK:
        return None
    nid = prefs.get(project)["node"]
    n = nodes.node(nid) if nid else None
    if not n or n["kind"] != "agent":
        return None
    heart, at = node_heart(n)
    return nid, f"{uid}~{claude_session(project)}", nodes.turn_limit(nid), heart, at


def node_turns(n):
    """What a node's row says about its sessions' turns: how many are working
    and waiting now, and the limit."""
    st = turns.state(n["id"], *node_heart(n))
    return {"working": len(st["working"]), "waiting": st["waiting"],
            "limit": nodes.turn_limit(n["id"])}


def newest_transcript(project_dir, uid=""):
    """The most recent Claude transcript on a working directory, as its file,
    or None: the asking ACCOUNT's own (its ~/.claude/projects on the share,
    transcripts.dirs), and the container account's where nobody is asking.
    It read the container account's for everybody until B489: a new user's
    Claude button offered the owner's conversation from five days before,
    which bb-tty then could not find under that user's home."""
    if uid:
        dirs = transcripts.dirs(uid, Path(str(project_dir)).name)
    else:
        dirs = [CLAUDE_PROJECTS / str(project_dir).replace("/", "-")]
    files = []
    for d in dirs:
        try:
            files += [f for f in d.glob("*.jsonl") if f.is_file()]
        except OSError:
            continue
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def last_claude(project_dir, uid=""):
    """The most recent Claude transcript for a working directory, or None.

    Used to offer "resume" rather than silently starting a fresh conversation
    in a project that already had one: a session's tmux dies with the machine
    it ran on, but the transcript does not: every account's ~/.claude/projects
    is a link onto the projects share (lib/common.sh's claude_projects_link),
    so this reads what a session on a node wrote.
    """
    newest = newest_transcript(project_dir, uid)
    if newest is None:
        return None
    return {"id": newest.stem, "when": int(newest.stat().st_mtime)}


MODEL_FAMILY = re.compile(r'"model"\s*:\s*"claude-(opus|sonnet|haiku|fable)')


def claude_model_now(project_dir, uid=""):
    """The model family the newest transcript here last answered on, or "".

    Read from the tail of the file when a project's settings dialog opens,
    so with no model set the dialog can say what Claude's default actually
    is rather than "leave as is". The tail, because a transcript runs to
    megabytes and the answer is in its last line.
    """
    f = newest_transcript(project_dir, uid)
    if f is None:
        return ""
    try:
        with open(f, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 131072))
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    found = MODEL_FAMILY.findall(tail)
    return found[-1] if found else ""


def end_claude(project):
    """End this project's Claude session, so the next press of Claude starts
    one on the setting just saved.

    It used to RESPAWN the pane in place, with `tmux respawn-pane -k` running
    the launcher again with `--respawn`, which kept the session, and the browser
    tab attached to it, and meant the change landed somewhere nobody was
    looking. The operator's call (12 Sep): end it, and let the button start it
    again. Simpler to say and simpler to trust, and it asks nothing of a
    node's agent that killing a session from the Sessions card has not asked
    for months, so the version gate that came with the respawn op is gone
    with it.

    A session ended is not a conversation lost: the transcript is the
    account's own and the Claude button resumes it. What it costs is the turn
    in flight, which is what the dialog asking about it says.
    """
    session = claude_session(project)
    if session not in {s["name"] for s in tmux_sessions()}:
        # On a node, through its agent, under the name that machine knows it
        # by, which is the same path the Sessions card's kill takes.
        on_node = next((x for x in node_tmux_sessions()
                        if x["name"] == session), None)
        if not on_node:
            return {"ended": False, "why": "no session is running here"}
        r = nodes.session_kill(on_node["node_id"], on_node["node_name"])
        if r.get("error"):
            return {"ended": False, "why": r["error"]}
        return {"ended": True, "on_node": on_node["node"]}
    r = run(["tmux", "kill-session", "-t", "=" + session], timeout=10)
    if r["code"] != 0:
        return {"ended": False, "why": (r["out"] or "tmux refused").strip()[:200]}
    return {"ended": True}


def end_session(session, node=""):
    """End one session by its page name, wherever it runs: on a node through
    its agent's held poll, by node id when the caller knows it (one name can
    live here and there), else with this container's tmux. A name that is
    not a live session is already ended and answers {gone} rather than an
    error, because the caller that wants a clean slate (Sign in ending the
    sign-in terminal first) asks for exactly that ordinary case. The
    Sessions card's kill (_session) and an administrator's End in a
    project's settings (projsessions.py) are this one path."""
    here = {s["name"] for s in tmux_sessions()}
    on_node = next((s for s in node_tmux_sessions() if s["name"] == session
                    and (not node or s["node_id"] == node)), None)
    if on_node and (node or session not in here):
        return nodes.session_kill(on_node["node_id"], on_node["node_name"])
    if session not in here:
        return {"code": 0, "out": "", "err": "", "gone": True}
    return run(["tmux", "kill-session", "-t", session], timeout=10)


def uptime():
    # PID 1 started when the container did, so its elapsed time is the
    # container's; /proc/uptime alone is the host's under a shared kernel.
    # Read from /proc in ps's own etime shape ([[dd-]hh:]mm:ss) rather than
    # forking ps on every status poll (R94); ps where /proc does not say.
    try:
        start = int(open("/proc/1/stat").read().rsplit(")", 1)[1].split()[19])
        up = float(open("/proc/uptime").read().split()[0])
        secs = max(0, int(up - start / os.sysconf("SC_CLK_TCK")))
        d, rest = divmod(secs, 86400)
        h, rest = divmod(rest, 3600)
        m, sec = divmod(rest, 60)
        return (f"{d}-{h:02d}:{m:02d}:{sec:02d}" if d else f"{h:02d}:{m:02d}:{sec:02d}" if h
                else f"{m:02d}:{sec:02d}")
    except (OSError, ValueError, IndexError):
        r = run(["ps", "-o", "etime=", "-p", "1"], timeout=10)
        return r["out"].strip() or "?"


# The API surface the companion app is written against (android/). One
# number, moved with the app: android/api-surface.json names every path
# and field the app reads and carries the same number, test/appapi.mjs
# holds the running server to that file, and the app compares this against
# its own TARGET_API to say when it is behind. A change to a path or a
# field listed there bumps all three together: the app, the file, this.
APP_API = 9
# How long the app's live connection is held before an empty answer (R125):
# under the app's 60 s read timeout, and long enough to cost little.
PHONE_WAIT_S = 45


def app_apk():
    """The newest companion APK in BuilderBot's own dist/, if this
    controller has the repository as a project: what the app points at when
    it finds itself behind. Its filename only; the Artifacts tab serves it."""
    d = WORKSPACE / "BuilderBot" / "dist"
    try:
        apks = sorted((p for p in d.iterdir() if p.suffix == ".apk" and p.is_file()),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return ""
    # A signed build first: the app on a phone was installed signed, and
    # Android will not update it with anything signed otherwise. The newest
    # file was offered whatever it was, and on 5 Oct that was a debug build
    # of uncommitted changes, which the operator's phone refused (B507).
    # Without a signed one, a build of a commit; a dirty one never.
    pick = ([p for p in apks if "-signed" in p.name]
            or [p for p in apks if "-dirty" not in p.name and "dirty" not in p.stem.split("-")[-1]])
    return pick[0].name if pick else ""


def app_apk_sha():
    """The newest companion APK's sha256, for the app to check a download
    against before it installs (B273); "" when there is none."""
    name = app_apk()
    if not name:
        return ""
    try:
        h = hashlib.sha256()
        with open(WORKSPACE / "BuilderBot" / "dist" / name, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


# The page's own scripts, each named with its version as the page is served.
# `no-cache` makes a browser ask before it uses a copy, but a phone left on
# the page across an update still met the old Global rules dialog after it
# reloaded, and a URL that changes with the file cannot be answered from a
# copy of the file before it. The version is the script's size and mtime,
# the same thing its ETag is; the page's own tag covers them all, so a change
# to one script alone is still a new page.
_SCRIPT_TAG = re.compile(rb'<script src="((?:tab|nb|page)-[a-z-]+\.js)">')
_page_scripts = {"mtime": None, "names": frozenset()}


def page_scripts():
    """The companion scripts index.html loads, by name: the allow-list the
    server serves them from, read off the page's own script tags so a new
    file is added in one place, the page, and nothing else is served. Read
    again when index.html changes. The page-*.js files were missing from the
    versioning pattern above until this read it the same way (R77)."""
    p = HERE / "index.html"
    try:
        m = p.stat().st_mtime_ns
    except OSError:
        return frozenset()
    if _page_scripts["mtime"] != m:
        names = {n.decode() for n in _SCRIPT_TAG.findall(p.read_bytes())}
        _page_scripts.update(mtime=m, names=frozenset(names))
    return _page_scripts["names"]


def _versioned_page(raw, tag):
    parts = [tag]

    def named(m):
        try:
            st = (HERE / m.group(1).decode()).stat()
        except OSError:
            return m.group(0)
        v = f"{st.st_size:x}-{st.st_mtime_ns:x}"
        parts.append(v)
        return b'<script src="' + m.group(1) + b"?v=" + v.encode() + b'">'
    out = _SCRIPT_TAG.sub(named, raw)
    return out, 'W/"' + hashlib.sha256("|".join(parts).encode()).hexdigest()[:24] + '"'


# ---- the request trace (R75 step 4) -----------------------------------------
# Every request this server answered, lately: when, the method, the path with
# its query keys, and who (a person, a session, an agent, the companion app)
# by the user agent and the principal the handler proved. A ring, in memory,
# because the question it answers is "what is the page asking for right
# now": the adb probe that put a row a minute on the Jobs tab and the tab
# that asked for its listing three times were both visible in one such
# window and invisible everywhere else. /api/trace reads it; `bb dashboard
# trace` prints it. Nothing here is persisted.
_TRACE = collections.deque(maxlen=6000)
_trace_lock = threading.Lock()


def trace_note(handler, ms=0):
    # A note beside the request, never a fault in it: whatever goes wrong
    # here is swallowed, since the answer has already been sent. Broad
    # because it runs on every request and must never become one's 500;
    # the first fault is logged, the rest would only say it again.
    try:
        path, _, query = handler.path.partition("?")
        keys = "&".join(sorted(k for k in urllib.parse.parse_qs(query, keep_blank_values=True)))
        ua = (handler.headers.get("User-Agent") or "")[:40]
        who = getattr(_writing, "who", None) or {}
        by = ("session" if who.get("session") else "agent" if path.startswith("/api/v1/agent")
              else "user" if who.get("name") else "anon")
        with _trace_lock:
            _TRACE.append((time.time(), handler.command, path, keys, by, ua, int(ms)))
    except Exception as e:                                  # noqa: BLE001
        if not _trace_said:
            _trace_said.append(True)
            print(f"[dashboard] trace: {type(e).__name__}: {e} (said once)", flush=True)


_trace_said = []


def trace_since(since):
    now = time.time()
    with _trace_lock:
        rows = [r for r in _TRACE if r[0] >= since]
    groups = {}
    slow = []
    for t, method, path, keys, by, ua, ms in rows:
        agent = ("app" if "BuilderBot" in ua else "curl" if ua.startswith("curl")
                 else "browser" if "Mozilla" in ua else (ua.split("/")[0] or "?"))
        key = (method, path + ("?" + keys if keys else ""), by, agent)
        g = groups.setdefault(key, {"n": 0, "first": t, "last": t, "ms_max": 0, "ms_sum": 0})
        g["n"] += 1
        g["first"] = min(g["first"], t)
        g["last"] = max(g["last"], t)
        # How long each took (B245): a tab that loads slowly is one request
        # that took seconds, and a count alone cannot say which.
        g["ms_max"] = max(g["ms_max"], ms)
        g["ms_sum"] += ms
        slow.append((ms, t, method, key[1], by, agent))
    out = [{"method": k[0], "path": k[1], "by": k[2], "agent": k[3], "n": v["n"],
            "first": v["first"], "last": v["last"], "ms_max": v["ms_max"],
            "ms_avg": v["ms_sum"] // max(1, v["n"])} for k, v in groups.items()]
    out.sort(key=lambda r: -r["n"])
    slow.sort(key=lambda r: -r[0])
    return {"since": since, "now": now, "total": len(rows), "rows": out,
            "slow": [{"ms": r[0], "at": r[1], "method": r[2], "path": r[3], "by": r[4], "agent": r[5]}
                     for r in slow[:8] if r[0] >= 500]}


# ---- a session told the controller moved (R83) -----------------------------
# A session keeps the briefing it was handed at its start, and nothing
# re-briefs it when the controller is rebuilt within a compatibility window.
# So the build a session began on is kept, per session, and on its next
# prompt after a rebuild the hook's line says the controller moved and where
# to read what changed: once per build, since the file then carries the new
# one. Persisted, because the rebuild that this is about restarts this
# process. Node sessions only: the hook posts from a node, and a session
# runs on one.
SESSION_SEEN = "session-seen.json"
# What the operator can change on a project that a session should be told of
# on its next prompt (the operator, 25 Sep), with the verb that reads it. The
# roadmap is roadmap.catchup's, which says which item moved; these say the
# half. A session's own writes through the API are marked seen as they land
# (session_mark_own), so only somebody else's move is said.
SEEN_HALVES = (("bug", "bugs", "`bb bug`"), ("rules", "rules", "`bb rules`"),
               ("mem", "memories", "the notebook's Memory view"),
               ("prefs", "settings", "`bb settings`"))
OWN_WRITE_ROUTES = ("/api/roadmap", "/api/rules", "/api/bugs", "/api/memory", "/api/prefs")
_seen_lock = threading.Lock()


def _build_now():
    st = image_stamp()
    return st.get("version") or st.get("rev") or ""


def _seen_load():
    path = STATE / SESSION_SEEN
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def _seen_now(project, who):
    """The tokens a session is compared against: the poll's per-project
    revisions, a digest of the project's own settings (the poll's prefs
    token is one mtime for every project), and the count of memory edits
    made through the notebook by somebody who is not a session. Not the
    memory files' mtimes, which the poll's token is: a session's own memory
    tool writes those files without passing through here, and read as
    news to the session that wrote them (B269)."""
    r = revisions(who, [project])
    try:
        pf = json.dumps(prefs.get(project) or {}, sort_keys=True)
    except Exception:                                                     # noqa: BLE001
        pf = ""
    edits = _seen_load().get("_mem_edits")
    edits = edits if isinstance(edits, dict) else {}
    return {"bug": str(r.get(f"bug:{project}") or ""), "rules": str(r.get(f"rules:{project}") or ""),
            "mem": str(edits.get(project) or 0),
            "prefs": hashlib.sha1(pf.encode(), usedforsecurity=False).hexdigest()[:12] if pf else ""}


def _memory_written(req, held):
    """Whether a POST to /api/memory wrote a memory: one of memory.verb's
    writes, answered without an error. A history read writes nothing, and
    counting it told a project's sessions its memories had changed when a
    person had only read the log (B296); a refusal or a conflict writes
    nothing either. `held` is the reply _post is holding."""
    if field(req, "action") not in memory.WRITES or not held:
        return False
    obj, code, _cookie = held[-1]
    return code == 200 and isinstance(obj, dict) and not obj.get("error")


def _mem_edited(project):
    """One more memory edit on this project through the notebook, by
    somebody who is not a session: the seen note's memory half."""
    if not project:
        return
    try:
        with _seen_lock:
            d = _seen_load()
            edits = d.get("_mem_edits") if isinstance(d.get("_mem_edits"), dict) else {}
            edits[project] = int(edits.get(project) or 0) + 1
            d["_mem_edits"] = edits
            write_json(STATE / SESSION_SEEN, d)
    except Exception as e:                                                # noqa: BLE001
        print(f"[dashboard] session seen: {type(e).__name__}: {e}", flush=True)


def session_mark_own(project, uid, who, since=None):
    """A session's own write to the notebook or the settings is seen by it
    as it lands, so its next prompt does not read it back as news. With
    `since`, the tokens as they stood before the write, only the halves
    that moved across it are marked: a bb verb relayed from a node may be
    a read, and a read must not mark what somebody else changed as seen."""
    if not project or not uid:
        return
    try:
        now = _seen_now(project, who)
        if since is not None:
            now = {k: v for k, v in now.items() if since.get(k) != v}
            if not now:
                return
        with _seen_lock:
            d = _seen_load()
            for key, rec in d.items():
                if key.startswith(f"{project}|{uid}|") and isinstance(rec, dict):
                    rec["revs"] = {**(rec.get("revs") or {}), **now}
            write_json(STATE / SESSION_SEEN, d)
    except Exception as e:                                                # noqa: BLE001
        print(f"[dashboard] session seen: {type(e).__name__}: {e}", flush=True)


# The house rule that asks a project's sessions to watch the diagnostics
# reports (the operator, 6 Oct: check for new ones after every prompt). A
# rule is text read at a session's start; this is what makes it hold: a
# project that carries the rule is told on its next prompt when a report
# newer than any it was told of is open. Keyed by the rule rather than by
# who may read diagnostics, since every project of an administrator's on a
# granted node may, and only BuilderBot's own work answers them.
WATCH_DIAG_RULE = "watch-diagnostics"


def _diag_watch(project, uid):
    """The open reports, newest first, when this project carries the rule
    and its session may read the diagnostics; else None. The same gate as
    _diag_refused (debug mode on, the project granted them, an account with
    the debug grant): the notice named report #68 and its project to a
    session that was refused reading it (the operator, 6 Oct)."""
    try:
        if not any(r.get("name") == WATCH_DIAG_RULE for r in rules.rules(project)):
            return None
        if not settings.get("debug_mode") or not prefs.get(project)["diag"]:
            return None
        me = users.account_of({"session": project, "uid": uid})
        if not me.get("name") or users.may(me, "debug"):
            return None
        return reports.listing()
    except Exception:                                                     # noqa: BLE001
        return None


# The Settings tab's Debugging group, the debug grant's (roles.NAMED_ONLY).
DEBUG_SETTINGS = ("debug_mode", "offer_unvetted")


# A Reset that un-enrolls its nodes first: their uninstalls run, and the
# reset follows once each node is retired. Read by GET /api/reset.
_reset_job = {}
_reset_lock = threading.Lock()
RESET_WAIT_S = 20 * 60


def _reset_after(principal):
    """Wait for every node a Reset is un-enrolling to be retired, then reset.
    A node that has not reported in RESET_WAIT_S, or whose uninstall failed,
    stops it with the reason, and nothing is moved."""
    while True:
        rows = _reset_job.get("nodes") or []
        for x in rows:
            n = nodes.node(x["id"]) or {}
            if n.get("state") == "retired" or not n:
                x["done"] = True
            elif x.get("job"):
                j = nodes.job(x["job"], with_log=False) or {}
                if j.get("state") in ("failed", "canceled"):
                    x["error"] = f"its uninstall {j['state']}: {j.get('error') or 'no reason given'}"
        bad = [x for x in rows if x.get("error")]
        if bad or time.time() - _reset_job.get("started", 0) > RESET_WAIT_S:
            _reset_job.update(running=False, error="; ".join(f"{x['name']}: {x['error']}" for x in bad)
                              or "; ".join(f"{x['name']} has not reported its uninstall"
                                           for x in rows if not x.get("done")) + f" in {RESET_WAIT_S // 60} minutes")
            print(f"dashboard: reset stopped: {_reset_job['error']}", flush=True)
            return
        if all(x.get("done") for x in rows):
            break
        time.sleep(3)
    r, status = settings.reset(STATE)
    if status != 200:
        _reset_job.update(running=False, error=r.get("error") or "the reset failed")
        return
    _reset_job.update(running=False, moved_to=r["moved_to"])
    print(f"dashboard: {principal} reset this controller after un-enrolling "
          f"{', '.join(x['name'] for x in _reset_job['nodes'])}; the old state is in {r['moved_to']}", flush=True)
    threading.Timer(1.0, lambda: os.execv(sys.executable, [sys.executable, *sys.argv])).start()


def setup_node():
    """The name of a node enrolled and answering, for Finish on the setup
    page (R199), or ""."""
    if nodes is None:
        return ""
    return next((n["name"] for n in nodes.node_list()
                 if n.get("kind") == "agent" and n.get("state") == "online" and n.get("live")), "")
# ...and the home tunnel's (R176), applied by tunnel.py when they change.
TUNNEL_SETTINGS = ("tunnel_host", "tunnel_token", "cf_api_token")


# The project's settings a session takes once, when it starts: the trees
# in its view (reads, sees) and the model and effort Claude was started
# with. Changed mid-session they are on the record and not in the session,
# which spent a dozen commands finding that out (report #81, 7 Oct).
START_ONLY = (("reads", "Reads"), ("sees", "Also sees"), ("model", "Model"), ("effort", "Effort"))


def _start_only(project):
    p = prefs.get(project) or {}
    return {k: p.get(k) for k, _ in START_ONLY}


def session_seen_note(project, uid, node, who=None, begin=False):
    """`begin`: record the build and the notebook this session starts from.
    Otherwise what has moved since, in one line, and the record moved on:
    the controller's build (R83) and any half of this project's notebook or
    its settings that somebody else changed."""
    build = _build_now()
    key = f"{project}|{uid}|{node or ''}"
    try:
        revs_now = _seen_now(project, who) if who is not None else {}
        watched = _diag_watch(project, uid)
        top = max((int(r.get("id") or 0) for r in watched or []), default=0)
        with _seen_lock:
            d = _seen_load()
            rec = d.get(key) if isinstance(d.get(key), dict) else {}
            was_build, was_revs = str(rec.get("build") or ""), rec.get("revs") or {}
            was_diag = int(rec.get("diag") or 0)
            start_now = _start_only(project)
            started = start_now if begin or not isinstance(rec.get("start"), dict) else rec["start"]
            stale = [label for k, label in START_ONLY if started.get(k) != start_now.get(k)]
            # Said once for each change, not on every prompt after it.
            new_stale = stale and rec.get("stale_said") != start_now
            d[key] = {"build": build or was_build, "revs": revs_now or was_revs,
                      "diag": max(top, was_diag), "start": started,
                      "stale_said": start_now if new_stale else rec.get("stale_said")}
            write_json(STATE / SESSION_SEEN, d)
        if begin:
            return ""
        said = []
        if build and was_build and was_build != build:
            said.append(f"The controller moved to {build} since this session began (it was on {was_build}): "
                        "`bb catchup` says what changed, and `bb preamble` prints the briefing as "
                        "it is now; this session still holds the one it started with, so where the "
                        "change touches what you are doing, a new session is briefed with it.")
        if was_revs and revs_now:
            # A half with no revision yet (a project with no bug filed) is
            # "" and its first write is a change like any other.
            moved = [(name, verb) for k, name, verb in SEEN_HALVES
                     if k in was_revs and was_revs.get(k, "") != revs_now.get(k, "")]
            if moved:
                said.append("Since your last prompt somebody else changed this project's "
                            + ", ".join(n for n, _ in moved) + ": read "
                            + ", ".join(v for _, v in moved) + " before going on.")
        if new_stale:
            said.append(f"This project's {', '.join(stale)} changed since this session started, and "
                        "a session takes those when it starts: end it and start a new one to have "
                        "them (a project added to Reads answers bb -p already; its tree is mounted "
                        "by the new session).")
        fresh = [r for r in watched or [] if int(r.get("id") or 0) > was_diag]
        if fresh:
            said.append("New in diagnostics since your last prompt: "
                        + ", ".join(f"report #{r['id']} from {r.get('project') or 'the dashboard'}"
                                    for r in reversed(fresh[:5]))
                        + (f" and {len(fresh) - 5} more" if len(fresh) > 5 else "")
                        + f". `bb diag reports` reads them (the house rule {WATCH_DIAG_RULE}).")
        return " ".join(said)
    except Exception as e:                                                # noqa: BLE001
        print(f"[dashboard] session seen: {type(e).__name__}: {e}", flush=True)
        return ""


def image_stamp():
    """Which build of the image this container is running.

    Baked in at the end of the Dockerfile by CI (see BB_IMAGE_REV there).
    Empty when the image was built any other way, which the page reports as
    `unstamped` rather than guessing; the whole point of this is that the
    answer to "is that fix in here?" stops being an inference from uptime.

    Trimmed rather than validated: these come from the image's own build, not
    from anything a request can set, and they are only ever displayed.
    """
    return {"rev": os.environ.get("BB_IMAGE_REV", "").strip()[:40],
            "built": os.environ.get("BB_IMAGE_BUILT", "").strip()[:32],
            # The ordered name for the same build. Derived from the VERSION
            # file at build time, so an image built outside CI has none and
            # the page falls back to the commit, as it always did.
            "version": os.environ.get("BB_VERSION", "").strip()[:64]}


def claude_auth(home=""):
    """{"nodes": {node id: {email, plan}}}: which nodes report this account
    signed in to Claude, and as whom.

    `home` is the asking account's, because the answer is theirs: a login is
    one account's on one node, and the record of what each node reported is
    kept in that account's home (claudegrant.py). The record, and only the
    record: there is no `claude` here to ask, and asking one would answer
    about this container rather than about the machines the account's
    sessions actually run on. One small file, read when asked.
    """
    return {"nodes": {nid: {"email": v["email"], "plan": v["plan"]}
                      for nid, v in claudegrant.nodes_of(home).items()}}


# ---- toolchains ------------------------------------------------------------
# All of it (the catalog, the probes, the sizes, the versions and the worker
# that installs) lives in toolchains.py, which is handed the two helpers it
# needs and otherwise knows nothing about this file.
import toolchains                                                  # noqa: E402

toolchains.configure(run=run, write_json=write_json, state=STATE)
# The Android system images on each node's store, behind the Emulator tab:
# kept on the toolchain store without being toolchains (emulator.py).
import emulator                                                  # noqa: E402

# ---- reaching a running Claude session -------------------------------------
# One door, one rule about Enter, used by both the to-do list and the memory
# book. See notify.py: it presses Enter only when the line it typed visibly
# arrived, which is the one thing a permission dialog will not do.
import notify                                                    # noqa: E402

notify.configure(run=run,
                 # A session on a node: found by the name the page uses,
                 # told through its agent (roadmap #24). Resolved at call
                 # time: the nodes module is imported further down.
                 on_node=lambda s: next((x for x in node_tmux_sessions() if x["name"] == s), None),
                 node_tell=lambda *a: nodes.tell_wait(*a))

# ---- signing in ------------------------------------------------------------
# The flow runs as a job on a NODE, the machine Claude Code is installed on
# (R47), and the card here carries its link and takes the code back. See
# signin.py for why every part of doing it in a terminal turned out to be
# somewhere it could go wrong.
import signin                                                    # noqa: E402

# ---- who may sign in --------------------------------------------------------
# The dashboard's own accounts (docs/users.md, roadmap #22). Imported here so
# that everything it needs (STATE, write_json) is already built; nothing in
# it reaches back. The FIRST account is made on the first-run screen: there
# is no environment variable behind it.
import users                                                     # noqa: E402

users.configure(state=STATE, write_json=write_json)

# Messages between accounts, and what each project's people are doing. Its own
# module for the same reason nodes and users are: the rules about who may read
# a conversation belong beside the conversation, not scattered through here.
import chat                                                     # noqa: E402
chat.configure(state=STATE, write_json=write_json)

# ---- what each session is changing ------------------------------------------
# Written by the bb-work-note hook inside a session and read by `bb work`;
# the server touches it only for a session on a node, whose hook posts the
# note here because the node has no /config to write (roadmap #24).
import overlap                                                   # noqa: E402
overlap.configure(state=STATE, workspace=WORKSPACE, write_json=write_json)
import plugins                                                   # noqa: E402
plugins.configure(state=STATE, write_json=write_json)


# ---- the test registry ------------------------------------------------------
# The notebook's sixth view: what each test protects, and what it costs. The
# timings are parsed out of a run the operator ingests; nothing here runs a
# suite, and nothing self-reports a duration.
import testreg                                                   # noqa: E402

testreg.configure(write_json=write_json, state=STATE)


# Which PERSON the notebook's logs should name for a change. "you" and
# "claude" answer "a person or a session" and stop there, which was the whole
# answer while there was one person; with several on a project it says
# nothing about which of them dropped an item. The audit trail on the Nodes
# tab has recorded the account since accounts existed, for exactly this
# reason, and this is the same thing for the other four logs.
#
# A thread-local rather than another argument through thirty signatures: the
# modules ask at the moment they write an event. Set on every _who(), which
# every authenticated path calls, so a handler thread reused by the next
# request cannot carry the last one's name. Resolved lazily, so the users
# file is read when something is actually written and not once per request.
_writing = threading.local()


def writer_name():
    u = getattr(_writing, "who", None)
    return str((users.account_of(u) or {}).get("name") or "") if u else ""

# ---- new project, and linking one ------------------------------------------
# Creating and cloning, and the worker that runs the ones that touch the
# network. The credential half stays here (agent_keys and the ssh aliases are
# this box's, not any one project's) and is handed over.
import forges                                                    # noqa: E402
forges.configure(run=run, state=STATE, write_json=write_json)

import projects                                                  # noqa: E402
import mapping                                                   # noqa: E402

# ---- the operator's house rules ---------------------------------------------
# The one thing in the notebook a session reads and cannot write. It rides in
# front of every session started here; claude_scope() in bb-tty denies the
# file tools on the file. Roadmap #7.
import rules                                                     # noqa: E402
import codebase                                                  # noqa: E402
import pending                                                   # noqa: E402
import settings                                                  # noqa: E402

rules.configure(write_json=write_json, state=STATE, actor=writer_name)
codebase.configure(workspace=WORKSPACE)
# The three stores above configure this one too; done here as well so the
# endpoint works even if none of them has been touched yet this process.
pending.configure(write_json=write_json, state=STATE)
# The Settings tab's own store (roadmap R29): the knobs the operator sets from
# the page rather than the environment. The builder home is where the commit
# identity lands.
settings.configure(write_json=write_json, state=STATE)
settings.forget_runners = lambda: runners.reset()
# What may be offered: the catalogs gate their unvetted entries on this
# one switch (roadmap R54, step 6), read live so a save takes at once.
forges.unvetted_ok = lambda: bool(settings.get("offer_unvetted"))


# ---- who else is in the notebook --------------------------------------------
# The other half of the same question, for a browser rather than a session
# (roadmap #26). Nothing to configure: it holds live seats in memory and
# reads no state, which is the whole of its design; see its header.
import presence                                                  # noqa: E402


# ---- the bug tracker --------------------------------------------------------
# The notebook's third view. Same arrangement again: its own file, handed the
# two helpers it needs, nothing reaching back.
import bugs                                                      # noqa: E402

bugs.configure(write_json=write_json, state=STATE, tell=notify.tell,
               tmux_name=tmux_name, workspace=WORKSPACE, actor=writer_name)

# The notebook's fourth view keeps a log too, and it is the odd one: nothing
# here writes findings, so the entries are derived by comparing one read of
# the report against the last.
import findings                                                  # noqa: E402

findings.configure(write_json=write_json, state=STATE, workspace=WORKSPACE)

# A phone on the end of wireless adb, and pushing an extension to it. Its own
# file for the usual reason; handed the workspace because what it can push is
# derived from the projects rather than browsed for.
import phone                                                     # noqa: E402

phone.configure(write_json=write_json, state=STATE, workspace=WORKSPACE)

# What a project has built, from its dist/ directory: the notebook's fifth
# view. The convention is the module's docstring; the scratch dir is where an
# .xpi is unpacked for web-ext, never dist/ itself.
import artifacts                                                 # noqa: E402
import git as gitview                                            # noqa: E402
import workspace                                                 # noqa: E402

# Each account's git worktree of a project: <this>/<project>/<uid> (common.sh
# session_dir). The Git view and the Artifacts tab both read them.
WORKTREES = Path(os.environ.get("BB_WORKTREES") or str(WORKSPACE / ".worktrees"))
artifacts.configure(workspace=WORKSPACE, worktrees=WORKTREES, state=STATE, write_json=write_json)
import signing                                                   # noqa: E402


def _keytool():
    """The store's keytool, which checks a keystore before it is kept
    (signing.inspect), or None while no jdk is installed."""
    root = toolchains.sdk_root_path()
    p = os.path.join(root, "jdk", "bin", "keytool") if root else ""
    return p if p and os.access(p, os.X_OK) else None


signing.configure(state=STATE, project_name=PROJECT_NAME, keytool=_keytool)


def _apksigner():
    """The store's newest apksigner and the java it runs on, for a proof of
    rotation (signing.rotate), or (None, {})."""
    root = toolchains.sdk_root_path()
    if not root:
        return None, {}
    tools = sorted(glob.glob(os.path.join(root, "android", "build-tools", "*", "apksigner")),
                   key=lambda p: [int(x) if x.isdigit() else 0 for x in re.split(r"[.-]", os.path.basename(os.path.dirname(p)))])
    jdk = os.path.join(root, "jdk")
    if not tools or not os.access(os.path.join(jdk, "bin", "java"), os.X_OK):
        return None, {}
    return tools[-1], {"JAVA_HOME": jdk, "PATH": os.path.join(jdk, "bin") + os.pathsep + os.environ.get("PATH", "")}


signing.apksigner_path = _apksigner
import membership                                                # noqa: E402
import roles                                                     # noqa: E402
import registry                                                  # noqa: E402
import busy                                                      # noqa: E402
membership.configure(state=STATE, write_json=write_json)
roles.configure(state=STATE, write_json=write_json)
registry.configure(state=STATE, workspace=WORKSPACE, write_json=write_json)
# Roles as areas (R152), once: an account on `user` carries no role, and each
# project's owner holds PROJECT_owner on it. Marked done in the accounts store.
try:
    users.migrate_r152({p: (r or {}).get("owner") or "" for p, r in membership._owners()["projects"].items()})
except Exception as e:                                                # noqa: BLE001
    print(f"[dashboard] roles migration (R152) skipped: {type(e).__name__}: {e}", flush=True)
# ...and a role on a project given on the project alone (R155), once.
try:
    registry.sync()
    users.migrate_r155()
except Exception as e:                                                # noqa: BLE001
    print(f"[dashboard] roles migration (R155) skipped: {type(e).__name__}: {e}", flush=True)
gitview.configure(workspace=WORKSPACE,
                  worktrees=WORKTREES,
                  tell=notify.tell, tmux_name=tmux_name, state=STATE,
                  accounts=account_names,
                  owner_uid=lambda: users.uid_of(users.get(users.owner_name() or "")),
                  working=claude_working, owner_name=users.owner_name,
                  session_open=owner_session_open, sessions=sessions_anywhere,
                  git_env=lambda me, name: {k: v for k, v in {**projects._git_env(),
                                                              **users.git_env(me, name)}.items()
                                            if k != "DASHBOARD_AUTH"},
                  may_push=projects.may_push, exclude=mapping.exclude,
                  audit=lambda *row: None if NODES_OK else db.audit(*row),
                  host_of=forges.host_label, ci_of=lambda n: ciwatch.read(n),
                  ci_fix=lambda n, where: ciwatch.fix(n, where))
# Where what grows is kept, as the Settings tab sets it (paths.py): read at
# use by every module below that keeps one of them, so a change applies to
# the next write without a restart.
import paths                                                     # noqa: E402
paths.configure(state=STATE, workspace=WORKSPACE)
workspace.configure(workspace=WORKSPACE, state=STATE)


def no_node_advice(name):
    """What a project with no node can still do, said the same way
    everywhere: a session reads and edits regardless (that is what this
    box is for), and building happens on a node or on GitHub."""
    # Settings is the notebook's view now, and "can push" read as news
    # about a remote beside a repository with no upstream (B456): it is the
    # project's push rights, so it says what to do with them.
    return ("Pick one on the project's notebook Settings"
            + (", or push a commit and let CI build it."
               if projects.may_push(name)
               else ". This project has no push rights either, so CI is not a "
                    "fallback until it does.")
            + " Reading and editing the code needs no node.")


def build_state(name):
    """Where this project's compiling happens, for the Artifacts tab: its
    node and what that node carries, or the plain fact that it has none and
    what is left when it does not."""
    if NODES_OK:
        return {"node": "", "name": "", "why": "", "push": projects.may_push(name)}
    nid = prefs.get(name)["node"]
    n = nodes.node(nid) if nid else None
    tc = sorted((n.get("reported") or {}).get("toolchains") or {}) if n else []
    return {"node": nid if n else "", "name": n["name"] if n else "",
            "kind": n["kind"] if n else "", "tools": tc,
            "push": projects.may_push(name),
            "why": "" if n else no_node_advice(name),
            # Its agent behind or out of window: a build is refused until
            # the node is updated, and the tab says so before the refusal.
            "gap": nodes.agent_stale(n) if n else ""}


def artifacts_of(name):
    """dist/ as the tab lists it, each file carrying what built it when a
    job did (docs/nodes.md §6): the chain lives beside the file, and the
    listing is where somebody asks."""
    return [a | {"prov": workspace.provenance(name, a["path"])}
            for a in artifacts.listing(name)]

# ---- the memory book -------------------------------------------------------
# What Claude remembers about each project, read and edited from the projects
# card. Same arrangement as toolchains above: its own file, handed what it needs.
import memory                                                    # noqa: E402

memory.configure(run=run, workspace=WORKSPACE,
                 claude_projects=CLAUDE_PROJECTS, tmux_name=tmux_name,
                 write_json=write_json, state=STATE)
memory.configure_log(write_json=write_json, state=STATE, actor=writer_name)

# ---- the shared to-do list -------------------------------------------------
# The one surface both sides write: the operator adds an item, a session adds
# one and ticks it off. bb-tty puts the open items in front of every Claude
# session it starts, which is the whole reason it is worth having.
import roadmap                                                   # noqa: E402

roadmap.configure(write_json=write_json, state=STATE, tell=notify.tell,
               tmux_name=tmux_name, settle=notify.settle, actor=writer_name)
roadmap.configure_verbs(bugs_mod=bugs)
# A memory edit marks the list's unsaved flag, and presence names the others
# and says when a session last read the list; both are the roadmap's.
memory.mark_unsaved = roadmap.mark_unsaved
chat.users = users
presence.account_names = lambda: {u.get("uid"): n for n, u in users.load()["users"].items()
                                  if u.get("uid")}
presence.readers = roadmap.readers

# ---- what a session is handed ----------------------------------------------
# The three above, assembled in the order a session reads them. bb-tty asks
# for this rather than joining them itself, and the Briefing tab draws the
# same string rather than its own idea of it.
import preamble                                                  # noqa: E402
def live_block():
    """The build this controller is running, for the briefing every session
    starts with (R75 step 5): the fact a session otherwise assumes. Short,
    and pointing at the verbs that answer the rest."""
    st = image_stamp()
    what = st.get("version") or (st.get("rev") or "")[:12] or "an unstamped image"
    when = f", built {st['built']}" if st.get("built") else ""
    return ("## What is live\n\n"
            f"The controller is BuilderBot {what}{when}. A fix pushed since is not "
            "running until the operator rebuilds; `bb status` says what is, `bb catchup` "
            "what changed since, and this line is from the moment this session started.")


preamble.configure(rules_mod=rules, roadmap_mod=roadmap, bugs_mod=bugs, live=live_block)

# ---- a new project's brief -----------------------------------------------------
# What its maker wants built, kept out of CLAUDE.md and handed to the first
# session instead, through a dialog on the first Claude press: brief.py.
import brief                                                     # noqa: E402

brief.configure(workspace=WORKSPACE, state=STATE, write_json=write_json)

# ---- a project's design language and its pages ------------------------------
# What the project looks like, kept: colors as tokens, type, shape, space and
# the operator's rules, and pages laid out as labeled blocks; a prompt a
# session is pointed at and docs/design-language.md written from it: design.py.
import design                                                    # noqa: E402

design.configure(workspace=WORKSPACE, state=STATE, write_json=write_json)
# The notebook's wiki (R112): a repository of the controller's own per
# project, pushed with the project's granted rights and nothing the tree says.
import wiki                                                      # noqa: E402
wiki.configure(state=STATE, workspace=WORKSPACE, write_json=write_json,
               push_record_fn=lambda p: projects.load_push().get(p),
               token_helper_fn=projects.token_helper, parse_fn=forges.parse,
               config_fn=lambda d: gitrelay.config(d), env_fn=projects._git_env)

# A project's CI on GitHub's own runners (R115): its runs and a failed job's
# log, read with the controller's credential for a session that has none.
import cilogs                                                    # noqa: E402
cilogs.configure(state=STATE, workspace=WORKSPACE, push_record_fn=lambda p: projects.load_push().get(p),
                 config_fn=lambda d: gitrelay.config(d), parse_fn=forges.parse)
# ...and watched (R117): once a day per project with workflows, and at once
# when a project is linked; the Git view, bb catchup and the bell read it.
import ciwatch                                                   # noqa: E402
ciwatch.configure(state=STATE, workspace=WORKSPACE, write_json_fn=write_json,
                  projects=lambda: sorted(d.name for d in WORKSPACE.iterdir()
                                          if d.is_dir() and not d.name.startswith(".")))

# ---- the standing model and effort -----------------------------------------
# One preference for every send, on its own card; see the module docstring
# for why it stopped being a question inside each send box.
import logs                                                      # noqa: E402
import idle                                                      # noqa: E402
logs.configure(state=STATE, write_json=write_json)
logs.diag_report = lambda: diag.report()
logs.audit = lambda *row: db.audit(*row)
logs.conversation_text = lambda rid: reports.conversation(rid)
idle.configure(state=STATE, write_json=write_json,
               # A changed rule reaches every node on its next poll rather
               # than its next ten-minute hello.
               changed=lambda: [nodes.ask_hello(n["id"]) for n in nodes.node_list()
                                if n.get("kind") == "agent"])
# On boot, because that is when a generation was just rotated in and the oldest
# one fell off the end of the policy. Nothing else runs on a schedule here.
logs.prune()

import prefs                                                     # noqa: E402
# The briefing reads a project's own settings for its "While tests run"
# section (what a change asked for during a run does); prefs is imported
# after preamble is configured, so it is handed over here.
preamble.prefs_mod = prefs
preamble.label_of = registry.label


def _project_node_gpu(project):
    """Whether the project's own node reports an NVIDIA card: what decides
    the briefing's GPU section."""
    if NODES_OK:
        return False
    nid = (prefs.get(project) or {}).get("node") or ""
    n = nodes.node(nid) if nid else None
    return bool(n and (n.get("reported") or {}).get("gpu_card"))


preamble.node_gpu = _project_node_gpu

prefs.configure(write_json=write_json, state=STATE)
# Said again, now that prefs exists: users.git_identity resolves a per-project
# override of the commit author, and that override lives in prefs, which is
# configured after users because the login path must not depend on it.
users.configure(state=STATE, write_json=write_json, project_prefs=prefs.for_user,
                # The nodes of an account's projects: what a node grant's
                # scope "mine" means (R137 step 3).
                nodes_of=lambda u: {n for p in (u.get("projects") or [])
                                    for n in prefs._nodes_of(prefs.get(p) or {})})

# ---- the dev instance ------------------------------------------------------
# A project's compose app, built and run on the sandbox VM's daemon. The
# module's docstring carries the security reasoning.
import devapp                                                    # noqa: E402
devapp.label_of = registry.label
import devactions                                                # noqa: E402
import containers                                                # noqa: E402
import nginxproxy                                                # noqa: E402
import imagecheck                                                # noqa: E402
import relocate                                                  # noqa: E402
import tunnel                                                    # noqa: E402
import storage                                                   # noqa: E402
import db                                                        # noqa: E402
import nodes                                                     # noqa: E402
import claudecode                                                # noqa: E402
import projsessions                                              # noqa: E402
import turns                                                     # noqa: E402

# The node data plane first, because devapp's job claim asks it which node
# work belongs to. Guarded: a database that will not open (a corrupt file, a
# full disk) must degrade to the dashboard this always was, not take down the
# page that is the operator's way to see what is wrong; nodes.py's readers
# and audit already no-op when it never came up.
try:
    nodes.configure(state=STATE)
    # The registry answers hello; the catalog is toolchains.py's. Joined here
    # rather than by one importing the other, which is the same seam every
    # other module pair uses.
    nodes.layout_of = toolchains.layout_for_node
    # ...and the digest of the bb bundle, so a node can tell from hello alone
    # whether the bb its sessions run is the one this controller ships.
    nodes.bundle_digest = lambda: workspace.bundle()["digest"]
    nodes.idle_minutes = idle.minutes
    nodes.session_tokens_for = session_tokens_for
    # A project born with a starting version commits it the way the
    # Artifacts tab gives a first version (projects._init).
    projects.first_version = lambda name, value, env: version.init(name, value, by="operator", env=env)
    # Each session kept to its own project's network (R79): the setting is
    # the node's, what each project owns there is devapp's.
    # ...and the containers' (R178): whether each project's are kept apart
    # here, and what each compose project may reach, whatever the sessions'
    # switch says.
    nodes.session_net_for = lambda nid: (({"on": True, "own": devapp.session_net_own(nid)}
                                          if nodes.session_net_on(nid) else {"on": False, "own": {}})
                                         | {"ctr_on": nodes.container_net_on(nid),
                                            "ctr": devapp.container_net_own(nid) if nodes.container_net_on(nid) else {}})
    NODES_OK = ""
    # The job logs are the only copy of what a node's job wrote and had no
    # retention at all until R17 step 1. Swept once here for whatever ended
    # while this controller was down; a running one sweeps a project as its
    # own jobs end, which is when it gains a log.
    try:
        _gone = nodes.prune_job_logs()
        if _gone:
            print(f"[dashboard] job logs: dropped {_gone} past the policy", flush=True)
    except Exception as e:                                # noqa: BLE001
        print(f"[dashboard] job log sweep skipped: {e}", flush=True)
except Exception as e:                                    # noqa: BLE001
    NODES_OK = str(e)
    print(f"[dashboard] node store unavailable: {e}", flush=True)


def net_nudge():
    """Every session-net node says hello again (nodes.session_net_nudge),
    after a write that already succeeded: a container changing hands, an
    instance made or removed. What it reads is the store, so that is the
    one fault it absorbs, logged; the answer the caller sends is unchanged."""
    try:
        nodes.session_net_nudge()
    except sqlite3.Error as e:
        print(f"[dashboard] session network nudge skipped: {e}", flush=True)


# ---- a node's CI runners ----------------------------------------------------
# The root-only helper that keeps each runner's token and mints from it, and
# the list the Runner card draws: runners.py.
import runners                                                   # noqa: E402

runners.configure(run=run, nodes=None if NODES_OK else nodes)

# The controller's own runner (docs/nodes.md §2, phase 4): the thread that
# takes compose and local exec jobs off the queue and runs them here. devactions
# registers its compose runner through configure(), so the queue is the seam
# between the two and neither imports the other.
import jobs                                                      # noqa: E402

if not NODES_OK:
    jobs.configure(nodes_module=nodes)
    toolchains.nodes = nodes
    toolchains.claudecode = claudecode
    emulator.nodes = nodes
    phone.nodes = nodes            # every adb command is a job on a node
    # A compose action the AGENT ran still has records to write here; this is
    # where the module that queued it finishes it (roadmap #18).
    nodes.on_done("compose", devactions.compose_done)
    nodes.on_done(claudecode.JOB, claudecode.update_done)
# What Allow on a rebuild request actually starts (the Docker row's `ask`).
# Outside the block above: the ask has nothing to do with the node registry,
# and a controller without one still has projects whose containers run.
phone.rebuilder = devactions.rebuild
phone.container_maker = containers.create_container
phone.container_free = containers.name_free
phone.container_builds = containers.build_refusal
phone.instance_maker = devactions.make_instance
# What a renamed project is called now, for the name Send offers (R154).
devapp.label_of = registry.label
phone.env_writer = lambda project, text, instance: devapp.write_env(project, text, instance or devapp.MAIN)
phone.ctl_runner = containers.ctl_on
# ---- what the page may type into a terminal -------------------------------------
# The tables, the pins, the operator's own lists and the typing itself:
# macros.py. A node's session is typed into through its agent.
import macros                                                    # noqa: E402

macros.configure(state=STATE, write_json=write_json, lock=_state_lock, run=run,
                 tmux_sessions=tmux_sessions, tmux_base=tmux_base,
                 session_tmux=lambda nid, ops: nodes.session_tmux(nid, ops))
phone.remover = devactions.remove_instance
# ...and what the tab's verbs and the asking need about who is asking
# (phone.verb): the projects an account sees, a project's node and its Run
# its container dial, a container held to its project's node (R79).
phone.users = users
phone.project_names = lambda who: {p["name"] for p in project_list(who)}
phone.project_node = lambda p: prefs.get(p)["node"]
phone.project_hosts = lambda p: prefs.get(p).get("hosts") or []
phone.dial = lambda p: prefs.get(p)["devbuild"]
phone.on_project_node = devapp.on_project_node
# A phone lent to a project (R113): its sessions drive the project's own app.
import phonelease                                                # noqa: E402
phonelease.configure(workspace=WORKSPACE, project_node_fn=lambda p: prefs.get(p)["node"],
                     may_see_fn=users.may_see)
phone.leasing = phonelease
phone.run_denied = devapp.RUN_DENIED
phone.net_nudge = net_nudge
phone.resolve_artifact = artifacts.resolve
phone.artifact_list = artifacts_of
# ...and what the Artifacts tab's read composes (artifacts.tab_view).
artifacts.listing_of = artifacts_of
artifacts.account_names = account_names
artifacts.build_state = build_state

artifacts.instance_states = devactions.row_states
artifacts.capture_days = lambda name: prefs.get(name)["capture_days"]
artifacts.dev_keep = lambda name: prefs.get(name)["dev_keep"]
artifacts.phone_summary = lambda name, uid: phone.summary(
    prefs.get(name)["node"], uid,
    nodes.node(prefs.get(name)["node"]) if prefs.get(name)["node"] and not NODES_OK else None)
# The settings dialog's save (prefs.dialog_save).
prefs.configure_dialog(WORKSPACE=WORKSPACE, pin_instances=devapp.pin_to_current_node,
                       end_claude=end_claude, net_nudge=net_nudge)

# ---- the Profile tab -------------------------------------------------------------
# An account's own settings, read and saved: profiletab.py.
import profiletab                                                # noqa: E402

# An account's conversations with Claude as a download: transcripts.py.
import transcripts                                               # noqa: E402

transcripts.configure(workspace=WORKSPACE,
                      root_for=lambda uid: (Path(home_for(uid)) / ".claude" / "projects")
                      if home_for(uid) else CLAUDE_PROJECTS)
profiletab.configure(users=users,
                     claude_email=lambda uid: ", ".join(sorted(
                         {v["email"] for v in claudegrant.nodes_of(home_for(uid)).values()}, key=str.lower)),
                     plugins_of=plugins.of,
                     node_names=lambda: {n["id"]: n["name"]
                                         for n in ([] if NODES_OK else nodes.node_list())},
                     logs_of=lambda me: transcripts.mine(
                         users.uid_of(me), [p["name"] for p in project_list(me)]))
devapp.configure(workspace=WORKSPACE, state=STATE, write_json=write_json,
                 log_dir=logs.log_dir, field=field,
                 node_for=nodes.node_for if not NODES_OK else None,
                 # A hosting-only node has no docker address here: the controller
                 # holds no key to a VPS, and every `docker compose config` and
                 # data-directory mkdir addressed at it waited out a 30s ssh
                 # timeout, twice per nginx Save on draconis, holding the server
                 # with it (R85 step 1, the operator, 11 Oct). With no address
                 # the config check runs the compose plugin here, which parses
                 # without a daemon, and the directory is the agent's to make.
                 node_addr=(lambda nid: "" if nodes.host_only(nid) else nodes.ssh_addr_of(nid)) if not NODES_OK else None,
                 queue=nodes if not NODES_OK else None,
                 runner=jobs if not NODES_OK else None,
                 project_node=lambda p: prefs.get(p)["node"],
                 project_nodes=lambda p: prefs.get(p)["nodes"],
                 node_paths=nodes.node_paths if not NODES_OK else None)
# The layer on top of it: the compose runner is its, so it is the one that
# hands jobs.py the function.
devactions.configure(runner=jobs if not NODES_OK else None)
devapp.gpu_why = gpu_container_why
# ...and what its request() needs about who is asking, and who hears.
devactions.users = users
devactions.ask_rebuild = phone.ask_rebuild
devactions.say = chat.event
devactions.net_nudge = net_nudge
# ...and the Docker tab's container verbs (containers.py) the same.
containers.dial = lambda p: prefs.get(p)["devbuild"]
containers.users = users
containers.ask_rebuild = phone.ask_rebuild
containers.net_nudge = net_nudge
containers.project_hosts = lambda p: prefs.get(p).get("hosts") or []
containers.ports_local = nodes.ports_local_on
# One nginx per node, from the nginx tab (R171): its records here, the
# container through containers.py, and the node's own view of its ports.
imagecheck.configure(state=STATE, write_json=write_json, devapp_module=devapp)
nginxproxy.configure(state=STATE, write_json=write_json, node_list=nodes.node_list,
                     node_name=lambda nid: (nodes.node(nid) or {}).get("name") or nid,
                     taken_ports=devapp.taken_ports)
# ...and put on a node the moment it enrolls when the Enroll dialog asked
# for it (config.nginx), so a box runs the script and nginx appears.
# The home tunnel the controller runs itself (R176, tunnel.py): from the
# settings, started at boot below when they say so.
tunnel.configure(settings_mod=settings, dash_port=PORT)
nodes.ON_ENROLL.append(lambda nid: nginxproxy.deploy(nid, containers, devactions, devapp)
                       if ((nodes.node(nid) or {}).get("config") or {}).get("nginx") else None)

# ---- the version ----------------------------------------------------------
# One identity per project, rendered per target; the module's docstring says
# why one literal string cannot work. Handed the two notebook halves as well:
# the case for a bump is "what has happened since the target last moved", and
# only the roadmap's and the tracker's dated logs know that.
import changelog                                                 # noqa: E402
import claudegrant                                              # noqa: E402
# The Claude sign-in's verbs are signin.py's; the record of what each node
# reported is claudegrant.py's.
signin.nodes = None if NODES_OK else nodes
signin.mint = users.mint_session
claudegrant.home_for = home_for

# ---- the node agent's channel -----------------------------------------------------
# The verbs behind /api/v1/agent/: channel.py.
import channel                                                   # noqa: E402

channel.configure(home_for=home_for)
channel.unvetted_ok = lambda: bool(settings.get("offer_unvetted"))   # a Mac's provisioner is a dev feature
# A signing is a job on the project's node, of a build in its dist/ (R106).
signing.node_of = lambda name: prefs.get(name)["node"]
signing.node_refuses = lambda nid: nodes.agent_stale(nodes.node(nid)) if nid and not NODES_OK else ""
signing.job_add = nodes.job_add
signing.file_path = workspace.file_path
phone.signer = signing.start


def _releaser(project, comp, asker_name, principal):
    """A session's release, run as the Artifacts tab's Release runs it
    (version.verb's release), under the asking account's commit identity
    and with the project's own credentials (R138)."""
    # The asker's commit identity, else the project's owner's: a relayed bb
    # carries a token minted for the project and no account.
    who = (users.get(asker_name) if asker_name else None) or users.get(membership.owner_name(project) or "") \
        or {"name": asker_name or "claude"}
    return version.verb(project, "release", {"component": comp}, who, principal)


phone.releaser = _releaser


def _release_editor(project, plan, asker_name="", principal=""):
    """An edit of a published release (R139), made here with the project's
    own token, which the session never holds: the notes replaced, the
    files attached that edit_plan() checked."""
    r = forgerelease.edit(project, plan)
    if not NODES_OK:
        db.audit(principal, "version-release-edit", project,
                 {"tag": plan.get("tag"), "notes": plan.get("notes") is not None,
                  "files": [x["name"] for x in plan.get("files") or []], "error": r.get("error") or ""})
    said = forgerelease.edit_said(r)
    return ({"error": said, "forge": r.get("forge") or ""}, 400) if r.get("error") else ({"edited": r, "said": said}, 200)


phone.release_editor = _release_editor


def _release_remover(project, plan, asker_name="", principal=""):
    """Files taken off a published release, its own ask (the operator,
    5 Oct), with the project's own token."""
    r = forgerelease.remove(project, plan)
    if not NODES_OK:
        db.audit(principal, "version-release-remove", project,
                 {"tag": plan.get("tag"), "files": [x["name"] for x in plan.get("files") or []],
                  "removed": r.get("removed") or [], "error": r.get("error") or ""})
    said = forgerelease.remove_said(r)
    return ({"error": said}, 400) if r.get("error") else ({"removed": r, "said": said}, 200)


phone.release_remover = _release_remover


def _keymaker(action, project, args, by=""):
    """A new generated key or a package's key, for a session's auto dial and
    for Allow on its ask (R106 step 6)."""
    if action == "generate":
        return signing.generate(project, str(args.get("route") or ""), str(args.get("key") or "default"), by=by)
    if action == "map":
        return signing.set_map(project, str(args.get("package") or ""), str(args.get("key") or ""))
    if action == "rotate":
        return signing.rotate(project, str(args.get("from") or ""), str(args.get("to") or ""), by=by)
    return {"error": f"not a key change: {action}"}, 400


phone.keymaker = _keymaker
artifacts.sign_routes = signing.routes_held
import version                                                   # noqa: E402
import vmtemplate                                                # noqa: E402
vmtemplate.unvetted_ok = forges.unvetted_ok          # the same switch (R54, step 6)
# The Nodes tab's verbs are nodes.verb's, and these are what they compose
# with (a runner's forge and token, a daemon probe, Claude Code's update).
nodes.configure_verbs(vmtemplate=vmtemplate, forges=forges, devapp=devapp,
                      runner_store=runners, workspace=workspace,
                      project_prefs=prefs.get, may_push=projects.may_push,
                      no_node_advice=no_node_advice, turns_of=node_turns)

version.configure(workspace=WORKSPACE, state=STATE, write_json=write_json,
                  roadmap_mod=roadmap, bugs_mod=bugs, changelog_mod=changelog,
                  tell_fn=notify.tell, tmux_name_fn=tmux_name,
                  )
changelog.component_dir = version._sub
# Release's forge half (R123; Gitea and GitLab, R124): the release beside a pushed tag.
import forgerelease                                              # noqa: E402
forgerelease.configure(state=STATE, workspace=WORKSPACE, write_json_fn=write_json)
version.configure_verbs(PANEL=version_payload, GIT_ENV=users.git_env, CREDS_ENV=projects._git_env,
                        MAY_PUSH=projects.may_push, SESSIONS=sessions_anywhere,
                        FORGE=forgerelease.publish,
                        AUDIT=lambda *row: None if NODES_OK else db.audit(*row))



# Claude Code on the nodes (claudecode.py): what each runs against what is
# out, and the one way it is updated, which is an administrator's press.
if not NODES_OK:
    claudecode.configure(nodes_module=nodes, node_sessions=node_tmux_sessions,
                         tmux_base=tmux_base, audit=nodes.audit)

# Every account's sessions on a project, for its settings dialog, and an
# administrator ending one (projsessions.py): the rows the Sessions card is
# made from, and its kill.
projsessions.configure(sessions=lambda: tmux_sessions() + node_tmux_sessions(),
                       base=tmux_base, owner=tmux_owner, accounts=account_names,
                       owner_name=users.owner_name, end=end_session)

# The code map, built for a project the moment it exists (mapping.py): the
# same command a session runs by hand, started in the background by the
# create paths, and the one thing a Claude session on a new project waits for.
mapping.configure(workspace=WORKSPACE,
                  codemap=Path(__file__).resolve().parent.parent / "lib" / "codemap.py")
projects.configure(run=run, workspace=WORKSPACE, agent_keys=agent_keys,
                   gh_authed=gh_authed, ensure_deploy_alias=ensure_deploy_alias,
                   project_name=PROJECT_NAME,
                   state=STATE, home=os.environ.get("BUILDER_HOME", str(Path.home())),
                   write_json=write_json,
                   after_create=mapping.start)
# The session network reaches the containers of the projects a project reads.
devapp.reads_of = lambda p: (prefs.get(p) or {}).get("reads") or []
devapp.reaches_of = prefs.reaches_on
# ...and what the create dialog's follow-ups and the sidebar's pins need.
projects.lock = _state_lock
projects.take_on = users.take_on
projects.set_prefs = lambda name, **kw: prefs.set_prefs(name, workspace=WORKSPACE, **kw)
projects.live_sessions = tmux_sessions
projects.brief_writer = brief.write

# ---- a node's git, relayed --------------------------------------------------
# Push, fetch, pull and ls-remote from a session on a node, done in a
# repository of the controller's own rather than in the tree the session can
# write: gitrelay.py (B148).
import gitrelay                                                  # noqa: E402

gitrelay.configure(state=STATE, workspace=WORKSPACE,
                   push_record=lambda p: projects.load_push().get(p),
                   token_helper=projects.token_helper, parse_url=forges.parse,
                   host_of=forges.host_of, git_env=projects._git_env)
# The modules that keep something that grows read where from paths.py.
workspace.paths = gitview.paths = logs.paths = gitrelay.paths = paths

# ---- the bb relay -----------------------------------------------------------
# A bb verb from a session on a node, run here (roadmap #24): which verbs
# travel and what a token may do with them are bbrelay.py's.
import bbrelay                                                   # noqa: E402

bbrelay.configure(users=users, projects=projects, prefs=prefs, gitrelay=gitrelay, registry=registry,
                  WORKSPACE=WORKSPACE, STATE=STATE)

# ---- a session's hooks, from a node -------------------------------------------
# The overlap notes, the chat feed, the catch-up and the turn queue, posted by
# a node's hooks with the session's token (roadmap #24): hooks.py.
import hooks                                                     # noqa: E402

hooks.configure(users=users, overlap=overlap, chat=chat, roadmap=roadmap, pending=pending,
                turns=turns, nodes=nodes, seen_note=session_seen_note, turn_scope=turn_scope)


# Written by entrypoint.sh once every startup hook has finished. Named here as
# well as in lib/common.sh, which is the cost of the marker crossing the
# bash/python line; the comment there carries the reasoning.
BOOT_READY_FILE = Path(os.environ.get("BOOT_READY_FILE", "/run/builderbot-ready"))
BOOT_WAIT = 180
BOOT_GRACE = 300


# When this process started, for the one question only it can answer: which
# nodes have dialed in since.
STARTED = time.time()
NODE_WAIT = 300


def _reconnecting(n):
    """Whether a node not dialing in is one this controller saw shortly
    before it started, and is still inside the start's wait for it: the
    agent reconnects on its own clock, so it is coming back, not down."""
    seen = float((n.get("agent") or {}).get("last_seen") or 0)
    return time.time() - STARTED < NODE_WAIT and STARTED - 900 < seen < STARTED


def wait_for_nodes(limit=NODE_WAIT):
    """Hold until every node that was alive when this controller went down
    has dialed in again, or give up.

    The same race wait_for_boot closes, one step further out. An update
    restarts the controller and every agent reconnects on its own schedule
    (bb-sandbox-redhat took over two minutes on 18 Sep), so a doctor run in
    that window says "not dialing in" and "no node can run a session" about
    nodes that are fine, and keeps saying it for doctor.EVERY. Only nodes
    seen in the quarter hour before this start are waited for: one that has
    been off for a day is not coming back because the controller did.
    """
    if NODES_OK:
        return
    end = time.time() + limit
    while time.time() < end:
        try:
            owed = [n for n in nodes.node_list()
                    if n.get("kind") == "agent"
                    # Whole seconds: last_seen is stamped as an int, so a node
                    # that dialed in the same second this started (48 against
                    # 48.6) is back, not owed until its next heartbeat.
                    and STARTED - 900 < float((n.get("agent") or {}).get("last_seen") or 0) < int(STARTED)]
        except Exception as e:                                   # noqa: BLE001
            # A wait at startup, not a step of it: the store unreadable or a
            # row malformed means nobody is waited for, said once here.
            print(f"[dashboard] not waiting for nodes: {type(e).__name__}: {e}", flush=True)
            return
        if not owed:
            return
        time.sleep(5)


def wait_for_boot():
    """Hold until the container has finished starting, or give up.

    This dashboard is started BY hook 15 and the hooks after it are still
    running. A `bb doctor` run inside that window does not report an early
    truth, it reports a falsehood; and doctor.EVERY is half an hour, so it
    stuck. Measured when a GPU still booted here: doctor cached at +46s and
    the thing it was asking about came up at +48s, so the card was wrong
    until somebody pressed refresh. The operator's remedy for that message is
    to restart the container, which runs the same race again, so it read as
    the fault
    recurring rather than as a stale answer.

    It does not care whether the wait succeeded: a dashboard started outside the
    entrypoint (`bb dashboard dev`, the test harness, an image whose entrypoint
    predates the marker) has none coming, and checking anyway is the behavior
    this has always had. So the wait ends on the container's own age as well as
    on a clock: mid-boot is the only time a missing marker means anything, and
    at that point pid 1 is under a minute old.
    """
    for _ in range(BOOT_WAIT * 2):
        if BOOT_READY_FILE.exists():
            return True
        if _container_age() > BOOT_GRACE:
            return False
        time.sleep(0.5)
    return False


def _container_age():
    """Seconds since pid 1 started, which is this container's own age.

    Not /proc/uptime: under Docker that is the HOST's, four days here on a
    container three minutes old, so it answers a different question entirely.
    And not the mtime of /proc/1, which this used to read: that is when the
    kernel made the directory's inode, and it makes it again whenever it is
    evicted, so a process twenty minutes old read as two. Then the doctor
    waited out the boot, three minutes, and the suite's first page timed out
    on a Doctor card that had not come (19 Sep, in a session's view, where
    pid 1 is bb-session and there is no ready marker to end the wait early).
    The start time itself: /proc/1/stat's 22nd field, in clock ticks since
    the machine booted, on top of /proc/stat's btime.
    """
    try:
        with open("/proc/1/stat") as f:
            ticks = int(f.read().rsplit(")", 1)[1].split()[19])
        with open("/proc/stat") as f:
            btime = next(int(line.split()[1]) for line in f if line.startswith("btime "))
        return max(0.0, time.time() - (btime + ticks / os.sysconf("SC_CLK_TCK")))
    except (OSError, ValueError, IndexError, StopIteration):
        return float("inf")     # cannot tell: treat it as "not booting"


def client_gone(sock):
    """Whether the peer of a held request has closed: readable with nothing
    to read is EOF. Only a positive answer counts: an exception (a socket
    that cannot be peeked) reads as still there, so a held poll is never
    dropped on a guess."""
    try:
        sel = selectors.DefaultSelector()
        try:
            sel.register(sock, selectors.EVENT_READ)
            ready = sel.select(0)
        finally:
            sel.close()
        if not ready:
            return False
        return sock.recv(1, socket.MSG_PEEK) == b""
    except (OSError, ValueError):
        return False


# ---- bb doctor, cached for the Doctor card: doctor.py ----------------------
import doctor                                                    # noqa: E402

doctor.configure(run=run, wait_for_boot=lambda: (wait_for_boot(), wait_for_nodes()))
# A node dialing in after silence re-asks the doctor now rather than in up
# to half an hour: after a reboot the card kept saying no node could run a
# session long after they were all back (the operator, 25 Sep).
nodes.came_back = lambda nid: threading.Thread(target=doctor.refresh, name="doctor-after-hello",
                                               daemon=True).start()
# The Docker tab's first pick is derived from where the projects are bound.
# A job of a container written for a project is that project's (B321).
nodes.job_owner = lambda j: devapp.owner_of(j.get("project") or "",
                                           (j.get("spec") or {}).get("instance") or devapp.MAIN)
nodes.project_nodes = lambda: {p: (v or {}).get("node") or ""
                               for p, v in prefs.all_projects(WORKSPACE).items()}
devapp.all_project_nodes = lambda: {p: (v or {}).get("nodes") or []
                                    for p, v in prefs.all_projects(WORKSPACE).items()}

def _ftp_node(nid):
    """What ftp.py asks of a node: its name, the address it dials in from,
    and whether its store has the ftp toolchain (None while it has not
    reported its store)."""
    n = nodes.node(nid)
    if not n:
        return None
    has = toolchains.node_has(n)
    return {"name": n.get("name") or nid, "addr": (n.get("agent") or {}).get("addr") or "",
            "has_ftp": ("ftp" in has) if has else None}


# A project's file access over FTP (R151): the store and its checks are
# ftp.py's, the server is the node's (bb-ftpd from the ftp toolchain), and a
# login is relayed by the agent to channel's ftp-auth.
import ftp                                                       # noqa: E402
ftp.configure(state=STATE, workspace=WORKSPACE, write_json=write_json, users=users,
              audit=lambda who, act, target, params: db.audit(who, act, target, params),
              project_node=lambda p: prefs.get(p)["node"] or "",
              ask_hello=lambda nid: None if NODES_OK else nodes.ask_hello(nid),
              node_agent=lambda nid: "" if NODES_OK else ((nodes.node(nid) or {}).get("agent") or {}).get("version") or "",
              node_info=lambda nid: None if NODES_OK else _ftp_node(nid))
nodes.ftp_for = ftp.for_node
# The node's nginx container, for its log stream (R182): named only where the nginx tab put one.
nodes.nginx_for = lambda nid: nginxproxy.container_name(nid) if nginxproxy.deployed(devapp, nid) else ""

# The controller's diagnostics: read-only, for an administrator and, behind
# the debug switch and a node's tick, an administrator's session (diag.py).
import diag                                                      # noqa: E402

import reports                                                   # noqa: E402
import files                                                     # noqa: E402
files.configure(workspace=WORKSPACE, audit=db.audit)
# A node's projects as a synced copy (R162): the nodes in sync mode a
# project is bound to, and VS Code's writes reaching them at once.
import wssync                                                    # noqa: E402
import claudesync                                                # noqa: E402


def _sync_bound(project):
    if NODES_OK:
        return []
    pr = prefs.get(project)
    synced = nodes.sync_node_ids()
    return [i for i in dict.fromkeys([pr.get("node") or "", *(pr.get("nodes") or [])]) if i and i in synced]


wssync.configure(workspace=WORKSPACE, nodes_module=nodes, bound_nodes=_sync_bound,
                 changed=files._poke, audit_fn=db.audit)
wssync.configure_projects(lambda: list(prefs.all_projects()))
wssync.configure_reads(lambda p: prefs.get(p).get("reads") or [])
# Each project's daily snapshots (R165): what a node gone wrong through its
# synced copy is undone from, kept for the days its settings say.
import snapshots                                                 # noqa: E402
snapshots.configure(workspace=WORKSPACE, days=lambda p: prefs.get(p)["snapshot_days"],
                    names=lambda: [p for p in prefs.all_projects() if (WORKSPACE / p).is_dir()],
                    audit_fn=lambda *row: None if NODES_OK else db.audit(*row))
files.on_change = wssync.changed
# A synced node writes the transcripts of the projects it holds and nothing
# else: bound to it, never one it only reads (B613).
claudesync.configure(workspace=WORKSPACE, held=lambda nid: wssync.bound_projects(nid))
reports.configure(write_json=write_json, state=STATE, redact=diag.redact,
                  build=lambda: image_stamp().get("version") or image_stamp().get("rev") or "")
# A report says which node its project builds on, and clearing them all is
# audited like every other mutation.
reports.node_name = lambda p: ((nodes.node(prefs.get(p)["node"]) or {}).get("name", "")
                               if prefs.get(p)["node"] and not NODES_OK else "")
reports.audit = db.audit
diag.configure(image_stamp=image_stamp, uptime=uptime, doctor_payload=doctor.payload,
               settings=settings, nodes=nodes, db=db, log_dir=logs.log_dir,
               plugins=plugins, users=users, reports=reports)


# ---- revisions -------------------------------------------------------------
# One token per thing a view can depend on. A view says what it watches and is
# told when that moves; it never writes its own "should I re-read?" rule.
#
# Four bugs in one week came from every view inventing that rule out of
# knowledge it did not have: the roadmap's arrows not noticing a session
# start, the Artifacts tab not noticing a phone connect, and the phone view
# polling only when it ALREADY knew about a request, which meant it could
# never learn of the first one. Each was patched where it hurt. This is the
# shape that stops the fifth.
#
# Everything here must be cheap, because it is asked for every second or two.
# Files answer with their mtime; counters answer from memory. Nothing in this
# function runs git, lists tmux, or shells out; that is what makes it
# affordable to ask often, and it is the whole reason it is not snapshot().
def _mtime(path):
    try:
        return int(Path(path).stat().st_mtime_ns)
    except OSError:
        return 0


# A store's revisions(), recomputed only when its file moves.
#
# Those five functions each read and parse a whole state file, which was
# affordable on the fifteen-second poll they were written for and is not on
# the one-and-a-half-second one they moved to. The key is the file's mtime in
# nanoseconds, so a second write in the same second is still a miss, and a
# write from `bb`, in another process entirely, invalidates this the same way
# the dashboard's own does, because it is the file that is being watched and
# not a counter in here.
_rev_cache = {}


def _cached(path, fn):
    key = str(path)
    m = _mtime(path)
    hit = _rev_cache.get(key)
    if hit is not None and hit[0] == m:
        return hit[1]
    v = fn()
    _rev_cache[key] = (m, v)
    return v


def revisions(who=None, projects=None):
    """Every token a view watches, cheap enough to ask for every second or two.

    `projects` is what the page actually has open: the notebooks, which are
    the only things that watch a per-project key. Without it every project
    pays for every poll, which was affordable while the per-project half was
    three stats and stopped being when the memory stamp joined them. A client
    that sends nothing still gets all of them: `bb` and the tests do.
    """
    names = [d.name for d in WORKSPACE.iterdir()
             if d.is_dir() and not d.name.startswith(".")] \
        if WORKSPACE.is_dir() else []
    if projects is not None:
        want = set(projects)
        names = [n for n in names if n in want]
    # Read once for the whole request, and only when a notebook is open on
    # something: with no per-project work to do these are five files nobody
    # asked about.
    nb_revs = bug_revs = test_revs = rule_revs = pend_revs = {}
    if names:
        nb_revs = _cached(STATE / "roadmap.json", roadmap.revisions)
        bug_revs = _cached(STATE / "bugs.json", bugs.revisions)
        test_revs = _cached(STATE / "tests.json", testreg.revisions)
        rule_revs = _cached(STATE / "rules.json", rules.revisions)
        pend_revs = _cached(STATE / "pending.json", pending.revisions)
    revs = {
        # The container itself. A restart invalidates everything a page holds.
        "boot": layout.boot_id(),
        # One file each, so any write through any path moves the token: the
        # CLI's included, which no in-process counter would catch.
        "findings": _mtime(STATE / "findings-log.json"),
        "reports": findings.reports_mtime(),
        # In memory, free to read.
        "phone.asks": len(phone.requests_open()),
        "phone.dev": phone.device_rev(),
        # A phone lent to a project (R113): the lease and its newest shot.
        "phone.lease": phonelease.rev(),
        "toolchains": toolchains.job_rev(),
        # Google's image index landing; the images themselves ride the node
        # and job tokens, which the Emulator tab watches as well.
        "emulator": f"{emulator._choices['at']}:{emulator._choices['loading']}",
        # Node and job data never joins the status payload (docs/nodes.md
        # §13): the views that show it watch this and fetch their own.
        "nodes": 0 if NODES_OK else nodes.rev(),
        "jobs": 0 if NODES_OK else nodes.jobs_rev(),
        # Who has a session where, and whether it is working: the project
        # rows fetch /api/live when this moves.
        "live": projsessions.live_token(),
    }
    # Per project, for the views that are per project.
    for n in names:
        # ...and each account's worktree's, whose builds the tab lists too
        # (B237): a stat per worktree, and a project has a handful.
        wts = WORKTREES / n
        revs[f"dist:{n}"] = max([_mtime(WORKSPACE / n / "dist")]
                                + ([_mtime(d / "dist") for d in wts.iterdir()]
                                   if wts.is_dir() else []))
        # A session may bump while the operator has the tab open, and the
        # policy file moves when they change who may bump. Both are cheap
        # stats; neither shells out to git.
        revs[f"ver:{n}"] = _mtime(WORKSPACE / n / "VERSION")
        # The project's reflog: it moves on every commit, which is what the
        # dev row's "the code has moved since the last build" is derived
        # from. Without it that verdict only refreshed when something else
        # happened to move: a Rebuild button that wakes on the next poll
        # rather than the next time you happen to touch the tab. A stat, not
        # a git call.
        revs[f"git:{n}"] = _mtime(WORKSPACE / n / ".git" / "logs" / "HEAD")
        # The notebook's six halves. COUNTERS, not mtimes, and that is the
        # whole of why this is not three more stats: each of these panels
        # holds the number it last read, so it can tell somebody else's write
        # from the echo of its own. An mtime cannot, and a redraw a panel did
        # not need detaches the send box or the half-typed row under the
        # finger that opened it. testreg is the sharpest case: describing ONE
        # test deliberately does not move its counter, where writing the file
        # obviously moves its mtime.
        #
        # The memories are the one thing here that is not a file in the state
        # directory: they are files in an ACCOUNT's home, so that stamp is a
        # glob of one directory. Which is what `projects` is for: one open
        # notebook's worth rather than the whole share's, every second and a
        # half. home_for is memoised, so none of this shells out.
        revs[f"roadmap:{n}"] = (nb_revs.get(n) or {}).get("roadmap", 0)
        revs[f"bug:{n}"] = bug_revs.get(n, 0)
        revs[f"tests:{n}"] = test_revs.get(n, 0)
        revs[f"rules:{n}"] = rule_revs.get(n, rules.EMPTY_REV)
        revs[f"pending:{n}"] = pend_revs.get(n, 0)
        # The wiki's reflog, which every commit and pull moves: a stat.
        revs[f"wiki:{n}"] = wiki.rev(n)
        if who is not None:
            revs[f"mem:{n}"] = memory.census(
                n, home=home_for(users.uid_of(who)))["rev"]
    revs["vpolicy"] = _mtime(STATE / "versions.json")
    revs["prefs"] = _mtime(STATE / "claude-prefs.json")
    # The Settings tab's store (R29): a save has to reach the next poll, and
    # the payload is rebuilt only when something in this list moves.
    revs["settings"] = _mtime(STATE / "settings.json")
    # The dev-instance job and its files. In-memory counter plus mtimes, so
    # the poll never spawns docker.
    revs["devapp"] = devapp.job_rev()
    return revs


# Who has polled lately, in memory: presence, not a record. See chat.online.
_polls = {}
# ...and when each account's last-seen was last written to its record: at
# most every ten minutes while it polls, so chat can say when somebody was
# last here across a restart, without rewriting the file that holds the
# password hashes four times a minute per open browser.
_seen_written = {}
SEEN_WRITE_S = 600

def _findings_counts(who, ps):
    """Per-project finding counts for the poll, scoped the way the tab is.

    counts() is already narrowed to the projects the caller may see, but it
    buckets a path it could not place under "", and for a session that bucket
    holds every row the attribution refused: the rest of the box. So a session
    gets its own project's number and nothing beside it, and the unplaceable
    `heads` that go with it are dropped at the call site for the same reason.
    """
    c = findings.counts(ps)
    mine = (who or {}).get("session")
    return {k: v for k, v in c.items() if k == mine} if mine else c


def snapshot(who):
    if who and who.get("name") and users.uid_of(who):
        _polls[who["name"]] = time.time()
        if _polls[who["name"]] - _seen_written.get(who["name"], 0) > SEEN_WRITE_S:
            _seen_written[who["name"]] = _polls[who["name"]]
            users.touch(who["name"])
    ps = project_list(who)
    # Sessions this account has any business seeing: its own shells, and
    # anything on a project it was given. Filtered here for the same reason
    # the project list is (roadmap #22): a member restricted to one project
    # could otherwise read every other project's name off the session list,
    # which is exactly what hiding the projects was for. An account that sees
    # everything sees the unowned ones too: terminals opened before accounts,
    # or by something that is not a browser.
    mine, seen = users.uid_of(who), {p["name"] for p in ps}
    sessions = [s for s in tmux_sessions() + node_tmux_sessions()
                if _session_visible(s["name"], mine, seen, users.sees_all(who))]
    login = signin.state(mine)
    # Each shell's git context, resolved here where WORKSPACE is known: the
    # git/GitHub command cards ghost against the directory the active shell
    # is actually in, and matching a cwd to a project is this server's
    # knowledge, not something the page should re-derive from path strings.
    by_name = {p["name"]: p for p in ps}
    for s in sessions:
        cwd = s.get("cwd", "")
        top = cwd[len(str(WORKSPACE)) + 1:].split("/")[0] \
            if cwd.startswith(str(WORKSPACE) + "/") else ""
        p = by_name.get(top)
        s["git"] = bool(p and p["git_ok"])
        s["github"] = bool(p and p.get("github"))
    attention, bell_hidden = _attention(who)
    return {
        "host": os.uname().nodename,
        "uptime": uptime(),
        # How many phone requests are waiting on the operator. A count and not
        # the requests themselves: this rides on every poll, and it exists so
        # the Phone tab knows when to go and fetch the real thing. Reading it
        # is a length() on a list in memory: no adb, nothing to pay for.
        "phone_asks": len(phone.requests_open(users.uid_of(who), users.is_admin(who))),
        # The invitations to a project waiting on this account, for its bell
        # (membership.py): Accept and Decline are answered there.
        "invites": membership.mine(who),
        # A project this account sees whose main branch's newest CI run
        # failed (ciwatch.red, R117): a bell row while it is true.
        "ci_red": ciwatch.red([p["name"] for p in ps]),
        # A file changed on two synced copies at once (R162, wssync.py): the
        # copy kept beside it, listed until it is deleted.
        "sync_conflicts": wssync.conflicts(lambda p: users.may_see(who, p)),
        # What is pinned in the bell about nodes (an agent behind, or from
        # another window), computed here on every poll so an alert clears
        # the moment it stops being true; nothing is stored to dismiss.
        "attention": attention,
        # How many of them this account has put away, for the drawer's
        # "show them again".
        "bell_hidden": bell_hidden,
        # Claude Code per node against the latest known, for the Nodes
        # tab's section.
        "claude_code": {} if NODES_OK else _claude_code_for(who, ps),

        # Whether there is a daemon behind any of the Docker controls, and if
        # not, the sentence saying why. Memoised in devapp, because answering
        # it properly is a subprocess: this rides the poll, and the poll is the
        # page's heartbeat. Every Docker button on the page reads this one
        # answer rather than each finding out by failing.
        "docker": devapp.available_default(),
        "logs": logs.payload(),
        "idle": idle.payload(),
        # Which run of the container this is. The page stamps it into the URL
        # of every Claude terminal it opens, so bb-tty can tell a request made
        # now from one a browser carried across a restart.
        "boot": layout.boot_id(),
        "image": image_stamp(),
        "projects": ps,
        "sessions": sessions,
        # Every node with a runner on it: the Runner card is a view of these
        # and nothing else, since CI left this container (phase 7). Read from
        # the census, which already carries it.
        "node_runners": runners.listing(),
        "reports": findings.mounted(),
        "reports_mtime": findings.reports_mtime(),
        "findings_counts": _findings_counts(who, ps),
        # ...and, for the row they land on, what those paths actually look
        # like. Order matters: this reads what the call above computed. Empty
        # for a session: a head is a fragment of a path from outside its
        # project, which is the one thing it must not be shown.
        "findings_heads": [] if (who or {}).get("session") else findings.heads(),
        # ...and whether there is a readable report at all, which is what the
        # Static analysis button and the Analysis tab ghost on.
        "reports_ok": findings.reports_ok(),
        # ...and when each report was written, so one left behind by a failed
        # scanner is visible rather than silently counted as current.
        "reports_ages": findings.reports_ages(),
        "doctor": doctor.payload(),
        # Which nodes report this account signed in to Claude, and the
        # sign-in of theirs that is running, if one is.
        "claude_auth": claude_auth(home_for(users.uid_of(who))),
        "signin": login,
        # A clone or a first push runs in the background now, so the card can
        # say what it is doing without the dialog being open.
        # The clone or link in flight, for whoever may start one (B171): it
        # names a project the account may not have been given, and its
        # buttons are that account's.
        "project_job": {} if users.may(who, "create") else projects.job(),
        # The code maps being built for new projects, and the ones that just
        # finished: the row says "mapping the code" and then how many files.
        "mapping": mapping.payload(),
        "max_tabs": layout.max_tabs(),
        # Everything the Settings tab edits, with where each value came from.
        "settings": settings.payload() | {"tunnel": tunnel.status()},
        # ...and where the controller keeps what grows, an administrator's.
        "paths": {} if users.may(who, "admin") else paths.view(),
        # The command list is built from the table above rather than spelled out
        # again in the page, so a command added here appears as a button and one
        # removed cannot leave a button that posts a name the server rejects.
        # The command cards: the bb commands, the Linux and git/GitHub cards,
        # the pins and the operator's own lists.
        **macros.cards(),
        "cards": layout.load_cards(),
        # The open tabs, so a phone picks up the desktop's layout rather than
        # starting from scratch. Carried in the status poll because it is small
        # and every client is already asking for that every 15s. THIS
        # account's: the strip follows the person to any browser they sign in
        # on, and stops following them to somebody else's (roadmap #25).
        "layout": layout.load_layout(users.uid_of(who)),
        # Who this is, so the page can name a shell session the way bb-tty
        # will (index.html's myTmux). Not a secret: it is this account's own
        # id, and it is already the key to everything the page saves.
        "uid": users.uid_of(who),
        # What this account's shell sessions are named with, or "" for the
        # owner, who keeps the bare names (users.tmux_prefix says why). The
        # page has to agree with bb-tty about this exactly, or a tab addresses
        # a session that was never created under that name.
        "tmux_prefix": users.tmux_prefix(who),
        # What this account may do, by capability rather than by role: the
        # page should never branch on "is this a user", because the answer to
        # "may I" is the thing that moves and the role is only how it is
        # decided today. Every one of these is refused again on the server;
        # this is what stops a dead control being drawn, not what stops the
        # action (roadmap #27).
        # Whether any node has what the Emulator tab needs, and why not: the
        # Tools card ghosts its button on this.
        "emulator": {"ready": False, "why": "the node store did not open"} if NODES_OK
                    else emulator.ready(),
        "can": {name: not users.may(who, name) for name in
                ("terminal", "docker-write", "toolchains-write", "git-auth", "admin",
                 # The CI runner tab, a job run and a project's node, by
                 # grant (R137 step 3): the Tools card hides CI runner on it.
                 "runner", "jobs", "node",
                 # ...and what the sidebar and the dialogs offer (step 4):
                 # drawn from the same grants the server refuses on.
                 "lock", "rename", "trash", "version", "create", "command-pin",
                 # ...and the debug options, which a page without the grant
                 # does not show at all (the operator, 6 Oct).
                 "debug")}
               # ...and what other projects a session may read: the owner's
               # alone (the operator, 6 Oct), whatever the grants say.
               | {"reads": (who or {}).get("role") == "owner"},
        # Each area's level anywhere (R152 step 3), so the page hides a tab
        # whose area this account may not read: "", read or write.
        "areas": {a: ("write" if users.is_admin(who or {}) or (who or {}).get("session")
                      else roles.level_of(who or {}, a)) for a in roles.AREA_KEYS},
        # Projects whose Claude session belongs to somebody else, by NAME:
        # "alice has a session on this" is the whole value of the record, and
        # a bare refusal would tell you nothing you could act on. Only for
        # projects this account can see, and never their own, which is not
        # held against them (roadmap #26).
        # Who has a Claude session on each project: BuilderBot account names,
        # everybody including the asker. More than one may (roadmap #24), each
        # in a worktree of their own, so this is a list and it is information
        # rather than a refusal: the row says who is here and nothing is
        # grayed for it. The page decides how to word "you and alice".
        "claude_with": projsessions.with_(sessions),
        # ...and which of them are working on a prompt right now, for the
        # dot beside each name (the operator, 24 Sep).
        "claude_busy": projsessions.busy(sessions),
        # ...and the same, one row per account per node, for the project
        # row's list: which machine each session is on.
        "claude_where": projsessions.where(sessions),
        # This account's own name, so the row can say "you and alice" rather
        # than reading your own name back at you.
        "me": (who or {}).get("name", ""),
        # ...and whether it administers this controller, so the page can word
        # an empty Projects card for a user with nothing granted rather than
        # telling them the share is not mounted (16 Sep).
        "admin": bool(who) and users.is_admin(who),
        # Whether this account's commits would carry an author: the Claude
        # button ghosts on this, naming the Profile, before bb-tty refuses.
        "git_ready": users.git_ready(who) if users.uid_of(who) else True,
        # The chat panel's headline: who is here, and what has arrived since
        # this account last looked. The messages themselves are fetched when
        # the panel is open. This rides the poll because it is small and it
        # is what decides whether the button wears a dot.
        "chat": _chat_summary(who, ps),
        # This account's color scheme, for a browser that has none stored.
        # index.html's adoptTheme says why localStorage still outranks it.
        "theme": users.prefs(who).get("theme", ""),
        # Whether this account has read the getting-started guide, and
        # which image's changelog it acknowledged: the welcome panel opens
        # itself once for each (the guide on a first sign-in, the changelog
        # once per image update), and these are what make it once.
        "welcome": {"seen": bool(users.prefs(who).get("welcome_seen")),
                    "image_seen": str(users.prefs(who).get("image_seen") or "")},
    }


# The JSON API's GET routes, in the order they are matched, against the raw
# path: "/api/artifact?" is a different route from "/api/artifacts" because
# the query mark is part of what it matches. A prefix route takes every path
# it prefixes; auth.mjs fails on one an earlier route takes. The doors before
# these (setup, login, the agent, health, the terminal proxy, the page and
# its scripts) stay in _get, in front of the credential check (R60).
GET_ROUTES = (
    ("prefix", "/api/revs", "_get_revs"),
    ("exact", "/api/live", "_get_live"),
    ("prefix", "/api/trace", "_get_trace"),
    ("prefix", "/api/status", "_get_status"),
    ("exact", "/api/reset", "_get_reset"),
    ("prefix", "/api/findings", "_get_findings"),
    ("prefix", "/api/profile", "_profile"),
    ("prefix", "/api/transcripts", "_get_transcripts"),
    ("prefix", "/api/snapshots", "_get_snapshots"),
    ("prefix", "/api/transcript", "_get_transcript"),
    ("prefix", "/api/git", "_get_git"),
    ("prefix", "/api/project-sessions", "_get_project_sessions"),
    ("prefix", "/api/changelog", "_get_changelog"),
    ("prefix", "/api/version", "_get_version"),
    ("prefix", "/api/artifacts", "_get_artifacts"),
    ("prefix", "/api/artifact?", "_get_artifact"),
    ("prefix", "/api/signing-backup?", "_get_signing_backup"),
    ("prefix", "/api/node-busy", "_get_node_busy"),
    ("prefix", "/api/meta", "_get_meta"),
    ("prefix", "/api/welcome", "_get_welcome"),
    ("prefix", "/api/source?", "_get_source"),
    ("prefix", "/logs/download", "_get_logs_download"),
    ("prefix", "/api/phone/wait", "_get_phone_wait"),
    ("prefix", "/api/phone", "_get_phone"),
    ("prefix", "/api/toolchains", "_get_toolchains"),
    ("prefix", "/api/emulator", "_get_emulator"),
    ("prefix", "/api/roles", "_get_roles"),
    ("prefix", "/api/users", "_get_users"),
    ("prefix", "/api/nginx", "_get_nginx"),
    ("prefix", "/api/storage", "_get_storage"),
    ("prefix", "/api/v1/nodes", "_get_nodes"),
    ("prefix", "/api/v1/jobs", "_get_jobs"),
    ("prefix", "/api/docker", "_get_docker"),
    ("prefix", "/api/containers", "_get_containers"),
    ("prefix", "/api/project-job", "_get_project_job"),
    ("prefix", "/api/trash", "_get_trash"),
    ("prefix", "/api/claude-now", "_get_claude_now"),
    ("prefix", "/api/roadmap", "_get_todo"),
    ("prefix", "/api/rules", "_get_rules"),
    ("prefix", "/api/global-rules", "_get_global_rules"),
    ("prefix", "/api/preamble", "_get_preamble"),
    ("prefix", "/api/brief", "_get_brief"),
    ("prefix", "/api/design", "_get_design"),
    ("prefix", "/api/wiki-export", "_get_wiki_export"),
    ("prefix", "/api/wiki", "_get_wiki"),
    ("prefix", "/api/ci-runs", "_get_ci_runs"),
    ("prefix", "/api/ci-watch", "_get_ci_watch"),
    ("prefix", "/api/codebase", "_get_codebase"),
    ("prefix", "/api/pending", "_get_pending"),
    ("prefix", "/api/memory", "_get_memory"),
    ("prefix", "/api/tests", "_get_tests"),
    ("prefix", "/api/bugs", "_get_bugs"),
    ("prefix", "/api/pubkeys", "_get_pubkeys"),
)


# The JSON API's POST routes, in the order they are matched. A prefix route
# takes every path it prefixes, so a longer path sits before a shorter one
# that would take it; auth.mjs fails on one that does not. Each names the
# method that answers, and the method carries its own refusals (R60).
POST_ROUTES = (
    ("prefix", "/api/v1/nodes", "_nodes"),
    ("prefix", "/api/v1/jobs", "_jobs"),
    ("exact", "/api/v1/bb", "_bb_relay"),
    ("exact", "/api/v1/claude-login", "_claude_login"),
    ("exact", "/api/v1/hook", "_hook"),
    ("exact", "/api/v1/tty-grant", "_tty_grant"),
    ("prefix", "/api/lock", "_lock"),
    # NOT /api/pin, which is the command pin and has been since long before
    # this: startswith() means a route added above it silently takes every
    # path it prefixes, and both handlers were called _pin, so the later
    # definition quietly replaced the earlier one in the class body too.
    ("prefix", "/api/project-pin", "_project_pin"),
    ("prefix", "/api/project-auth", "_project_auth"),
    ("exact", "/api/project-ftp", "_project_ftp"),
    ("prefix", "/api/container", "_container"),
    ("prefix", "/api/dockerctl", "_docker_ctl"),
    ("prefix", "/api/rename", "_rename"),
    # These two before the bare prefix, or startswith swallows them.
    ("prefix", "/api/trash-restore", "_trash_restore"),
    ("prefix", "/api/trash-purge", "_trash_purge"),
    ("prefix", "/api/trash", "_trash"),
    ("prefix", "/api/session", "_session"),
    ("prefix", "/api/keys", "_keys"),
    ("prefix", "/api/send", "_send"),
    ("prefix", "/api/say", "_say"),
    ("prefix", "/api/chat", "_chat"),
    ("prefix", "/api/layout", "_layout"),
    ("exact", "/api/bell", "_bell"),
    ("exact", "/api/nginx", "_nginx"),
    ("exact", "/api/images", "_images"),
    ("exact", "/api/storage", "_storage"),
    ("prefix", "/api/cards", "_cards"),
    ("prefix", "/api/pin", "_pin"),
    ("exact", "/api/reset", "_reset"),
    ("prefix", "/api/create", "_create"),
    ("prefix", "/api/profile", "_profile"),
    ("prefix", "/api/git", "_git_act"),
    ("prefix", "/api/project-sessions", "_project_sessions"),
    ("prefix", "/api/unlink", "_unlink"),
    ("prefix", "/api/link", "_link"),
    ("prefix", "/api/project-job", "_project_job"),
    ("prefix", "/api/roadmap", "_roadmap"),
    ("prefix", "/api/roles", "_roles"),
    ("prefix", "/api/users", "_users"),
    ("prefix", "/api/toolchains", "_toolchains"),
    ("prefix", "/api/emulator", "_emulator"),
    ("prefix", "/api/logs", "_logs"),
    ("prefix", "/api/idle", "_idle"),
    ("prefix", "/api/paths", "_paths"),
    ("prefix", "/api/snapshots", "_snapshots"),
    ("prefix", "/api/settings", "_settings_post"),
    ("prefix", "/api/rules", "_rules"),
    ("prefix", "/api/global-rules", "_global_rules"),
    ("prefix", "/api/pending", "_pending"),
    ("prefix", "/api/memory", "_memory"),
    ("prefix", "/api/prefs", "_prefs_post"),
    ("prefix", "/api/brief", "_brief"),
    ("prefix", "/api/design", "_design"),
    ("exact", "/api/wiki", "_wiki"),
    ("exact", "/api/ci-watch", "_ci_watch"),
    ("prefix", "/api/devapp", "_devapp"),
    ("prefix", "/api/changelog", "_changelog"),
    ("prefix", "/api/version", "_version"),
    ("exact", "/api/signing", "_signing"),
    ("exact", "/api/members", "_members"),
    ("exact", "/api/signing-backup", "_post_signing_backup"),
    ("prefix", "/api/artifacts", "_artifacts"),
    ("prefix", "/api/nodelog", "_nodelog"),
    ("exact", "/api/diag", "_diag"),
    ("exact", "/api/reports", "_reports"),
    ("exact", "/api/v1/files", "_files"),
    ("prefix", "/api/phone", "_phone"),
    ("prefix", "/api/findings", "_findings_log"),
    ("prefix", "/api/tests", "_tests"),
    ("prefix", "/api/presence", "_presence"),
    ("prefix", "/api/bugs", "_bugs"),
    ("prefix", "/api/custom", "_custom"),
    ("prefix", "/api/doctor", "_doctor"),
    ("prefix", "/api/signout", "_signout"),
    ("prefix", "/api/login-code", "_login_code"),
    ("prefix", "/api/signin", "_signin"),
)


class Handler(BaseHTTPRequestHandler):
    server_version = "builderbot-dashboard"

    def log_message(self, fmt, *args):      # quieter than the default
        pass

    def _who(self):
        """The account making this request, or None. Kept for the notebook's
        logs on the way past (writer_name), so an entry can say WHICH person
        wrote it. See _who_raw for how the principal itself is proved."""
        u = self._who_raw()
        _writing.who = u
        return u

    def _who_raw(self):
        """The account making this request, or None.

        Deliberately NOT remembered on the handler. BaseHTTPRequestHandler
        reuses one instance for the life of a connection, so a principal
        cached on `self` outlives the request that proved it: harmless while
        protocol_version is HTTP/1.0 and every connection carries one request,
        and a cross-request credential leak the day somebody turns keep-alive
        on for the throughput. The cost it would have saved is already saved:
        users.authenticate_pair remembers a verified credential for a minute,
        so repeat calls are a digest and a dict lookup rather than a pbkdf2.

        Basic and the cookie both land here. Basic is what `bb` and the test
        suite send; the cookie is what a browser gets from the login page.
        """
        hdr = self.headers.get("Authorization", "")
        if hdr.startswith("Bearer "):
            # A session's scoped token: one project, user rights, an expiry.
            # Never a person, so it can do what a user can do on that project
            # and nothing else (bug #16).
            tok = hdr[7:].strip()
            who = users.session_principal(tok)
            # ...widened to the projects its own reads (prefs.reads), read
            # from the settings on every request rather than baked into the
            # token, so a change in the dialog reaches a running session.
            if who:
                who = users.with_reads(who, (prefs.get(who["session"]) or {}).get("reads") or [])
            # Past half its life, the answer to this request carries a fresh
            # one (users.renewal): set here, sent by _json, so a session in
            # use never runs out. Reset per request, because the handler instance
            # outlives one.
            self._renewed = users.renewal(tok) if who else ""
            return who
        if hdr.startswith("Basic "):
            try:
                given = base64.b64decode(hdr[6:]).decode("utf-8", "replace")
            except (ValueError, UnicodeDecodeError):
                return None
            # The whole "user:password" is checked at once, so a correct name
            # with a wrong password is indistinguishable from both being wrong.
            return users.authenticate_pair(given)
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "bb_session":
                u = token_user(v.strip())
                if u:
                    return u
        return None

    def _authed(self):
        return self._who() is not None

    def _principal(self):
        """What the audit rows should say this was: the account's name.

        `operator` was a placeholder from before there were accounts, true of
        every mutation because there was only ever one person who could make
        one. Now there can be several, and a log that calls them all the same
        thing is a log that answers no question worth asking.
        """
        u = self._who()
        return f"user:{u['name']}" if u else "anonymous"

    def _readonly(self, name):
        """True, with the 403 already written, when this account may see the
        project but has not taken it on.

        The counterpart to _refused for the handlers whose other check is "is
        this a project you can see". Seeing and working are separate
        questions, so every write that names a project asks this too.
        """
        why = users.may(self._who(), "write", name)
        if not why:
            return False
        self._json({"error": why}, 403)
        return True

    def _not_project(self, name):
        """True, with the 400 already written, when `name` is not a project
        this account sees. The same shape as _refused: a guard that returns
        a bool. Twenty-nine handlers each rebuilt the visible set and wrote
        the same reply before this existed (R60)."""
        if name and name in {p["name"] for p in project_list(self._who())}:
            return False
        self._json({"error": f"not a project: {name}" if name else "not a project"}, 400)
        return True

    def _result(self, r, bad=400):
        """A module's {ok} or {error} answer as the reply: `bad` when it
        carries an error, 200 otherwise."""
        return self._json(r, bad if r.get("error") else 200)

    def _refused(self, action, project=None):
        """True, with the 403 already written, when this account may not.

            if self._refused("rename", name):
                return

        Returns a BOOLEAN, and the name says so. The first version returned
        "the response" and read as `if (no := self._may(...)): return no`,
        which looks exactly like a guard and is not one: _json writes the
        reply and returns None, so the caller got its 403 while the handler
        carried on and did the thing anyway. The NODES suite caught it (a
        refused enrollment that left a node behind) because the assertion on
        the refusal itself passed perfectly. A guard that returns the thing it
        wrote is a guard that can be used wrongly, so it returns a bool.

        The project filter in project_list() does most of the authorizing;
        this is the rest: the verbs a `user` may not use on a project they DO
        have, and the surfaces that are not projects at all. Named actions
        rather than anything derived from the URL, so restricting a verb is a
        decision somebody makes rather than a default they inherit.
        """
        why = users.may(self._who(), action, project)
        if not why:
            return False
        self._json({"error": why}, 403)
        return True

    def _deny(self):
        """Not signed in. A person gets the login page, code gets a plain
        401, never a WWW-Authenticate challenge, which is what summons the
        browser's own dialog. Anything fetching /api/ is the page's JS (or
        curl), and both handle a 401 better than a redirect-to-HTML."""
        # /metrics too: a scraper following a redirect to the login page
        # would parse HTML as an exposition and report the target down.
        if self.path.split("?")[0].startswith("/api/") or self.path == "/metrics":
            return self._json({"error": "not signed in"}, 401)
        nxt = urllib.parse.quote(self.path, safe="/?=&")
        self.send_response(302)
        self.send_header("Location", f"/login?next={nxt}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _login_page(self, error="", setup=False):
        """The sign-in card, or the first-run card when nobody owns this box.

        One template: the difference between them is three fields and the
        copy, and two pages would have drifted apart the first time either was
        touched.
        """
        err = f'<p class="err">{error}</p>' if error else ""
        body = (LOGIN_HTML
                .replace("<!--TITLE-->", "set up" if setup else "sign in")
                .replace("<!--ACTION-->", "/setup" if setup else "/login")
                .replace("<!--FIELDS-->", SETUP_FIELDS if setup else LOGIN_FIELDS)
                .replace("<!--ERR-->", err)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _setup_post(self):
        """Make the owner, once. Refused the moment there is one.

        Checked against the store rather than a flag: "has anybody claimed
        this box" is a question with an answer already, and a second copy of
        it is one more thing that can disagree.
        """
        if users.all_users():
            return self._login_page("This container already has an account.")
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 <= n <= MAX_BODY:
                return self._json({"error": "body too large"}, 413)
            form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
        except (ValueError, TypeError):
            return self._json({"error": "bad request"}, 400)
        name = form.get("username", [""])[0]
        pw, pw2 = form.get("password", [""])[0], form.get("password2", [""])[0]
        if pw != pw2:
            return self._login_page("Those two passwords are not the same.",
                                    setup=True)
        r = users.claim(name, pw)
        if r.get("error"):
            return self._login_page(r["error"], setup=True)
        print(f"dashboard: {name} claimed this container as the owner",
              flush=True)
        # Then the rest of the setup page, which ends with a node (R199).
        settings.set_many({"setup_done": False})
        # Straight in, rather than back to a sign-in they just proved: they
        # typed the password twice thirty seconds ago.
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie",
                         f"bb_session={make_token(users.get(name))}; Path=/; "
                         f"Max-Age={SESSION_DAYS * 86400}; HttpOnly; SameSite=Lax")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _login_post(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 <= n <= MAX_BODY:
                return self._json({"error": "body too large"}, 413)
            form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
        except (ValueError, TypeError):
            return self._json({"error": "bad request"}, 400)
        u = users.authenticate(form.get("username", [""])[0],
                               form.get("password", [""])[0])
        if not u:
            # A beat of delay, so guessing costs something; the message does
            # not say which half was wrong for the same reason the store
            # checks name and password together.
            time.sleep(0.5)
            return self._login_page("Wrong username or password.")
        users.touch(u["name"])
        nxt = form.get("next", ["/"])[0]
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"
        self.send_response(303)
        self.send_header("Location", nxt)
        self.send_header("Set-Cookie",
                         f"bb_session={make_token(u)}; Path=/; "
                         f"Max-Age={SESSION_DAYS * 86400}; HttpOnly; SameSite=Lax")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _logout(self):
        self.send_response(302)
        self.send_header("Location", "/login")
        self.send_header("Set-Cookie",
                         "bb_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _node_scope(self):
        """Node ids this account may look at, or None for "no restriction".

        An account that may change a node is shown the registry, which is what
        the Nodes tab is. One that may not is shown only the machines its own
        projects build on, so every node-shaped surface is a window on its own
        work rather than an inventory of the box.

        Used by the listing AND by the two endpoints that read a node's
        contents. Scoping the picker alone would have been theatre: `?node=`
        is a string in a URL, and the answer is what actually carries the
        other projects' names (roadmap #27).
        """
        me = self._who()
        if not users.may(me, "node"):
            return None
        want = set()
        for p in project_list(me):
            pr = prefs.get(p["name"])
            want.update([pr["node"], *(pr.get("nodes") or [])])
        want.discard("")
        return want

    def _node_asked(self, nid):
        """Resolve and check a `?node=` for this account.

        Returns (node_id, error). An account with no restriction gets what it
        asked for, "" included, which is "the default node" and predates the
        picker. A restricted one must land on a node one of its own projects
        builds on, and when it named none, the first of those, because its
        picker only ever offered those anyway.
        """
        scope = self._node_scope()
        if scope is None:
            return nid, None
        if not scope:
            return "", "none of your projects builds on a node"
        if not nid:
            return sorted(scope)[0], None
        if nid not in scope:
            return "", "not a node one of your projects builds on"
        return nid, None

    def _nodes_for(self, rows):
        scope = self._node_scope()
        rows = rows if scope is None else [n for n in rows if n["id"] in scope]
        # Which of each node's runners has a token stored: asked of the
        # helper once, which names slots and never a token.
        tokens = runners.tokens() if any(n.get("kind") == "agent" for n in rows) else {}
        for n in rows:
            if n.get("kind") == "agent":
                n["runner_tokens"] = sorted(tokens.get(n["id"], set()))
        # Whether THIS account's Claude login has been given to each node,
        # answered here rather than by handing the page a uid to compare
        # against: the grant list is every account that has one, which is
        # nobody else's business to read off a row.
        return rows

    def _area_read_why(self, area, project=None, me=None):
        """Why this person may not READ `area` (R152 step 3: an area without
        Read is not shown, and its views are refused), or "". A session sees
        its own project's through its own routes, and the account behind it
        is held by users.may; an administrator reads everything."""
        me = me if me is not None else (self._who() or {})
        if me.get("session") or users.is_admin(me):
            return ""
        if roles.level_of(me, area, project, users.may_work):
            return ""
        label = next((a[1] for a in roles.AREAS if a[0] == area), area)
        return (f"your roles give no {label} Read" + (f" on {project}" if project else "")
                + ": the Roles tab gives one")

    def _term_refused(self, rest, me=None):
        """A sentence when this account may not have the terminal it is asking
        for, and "" when it may.

        Two rules, and they apply to different people.

        A Claude session is a write, the most write-shaped thing on the page,
        so it needs a project the account has actually taken on, whoever
        they are. An administrator is shown every project and works on the
        ones on their own list (users.may_work), so this is where that bites
        for them.

        And an account with no `terminal` right gets nothing else at all: not
        a shell, not somebody else's Claude, and not a project it cannot see.
        A read-only terminal pointed at another session is a way to WATCH one,
        which is the hole this closes rather than opens.

        `me` is the account to ask about when it is not the request's own:
        a node's bb-tty asking for the account a session token was minted
        for (_tty_grant).
        """
        me = me or self._who()
        arg = _term_arg(rest)
        if arg.startswith("claude:"):
            project = arg[len("claude:"):].split(":")[0]
            # Terminal Read is the shielded Claude console; without it there
            # is no terminal on the project at all (R152 (e)).
            return users.may(me, "claude", project) or self._area_read_why("terminal", project, me)
        return users.may(me, "terminal")

    def _claude_held(self, rest, me=None):
        """A sentence when this account may not open the Claude session it is
        asking for, and "" when it may.

        More than one conversation per project is allowed now (roadmap #24),
        and each works in a tree of its own, so they cannot overwrite each
        other. What is refused instead is a SECOND SESSION ON ONE ANTHROPIC
        ACCOUNT. Two dashboard accounts signed in to the same Anthropic login
        would share its limits and make whose-work-is-whose unanswerable, and
        the check is a real one rather than a guess: the node that signed each
        account in reported which Anthropic account it was, and that record is
        what this compares.

        Enforced HERE and not only in the page, for the reason bb-tty's own
        header gives about the lock file: a rule only the UI honors is a
        suggestion, because the ttyd URL is reachable directly.
        """
        arg = _term_arg(rest)
        me = me or self._who()
        uid = users.uid_of(me)
        # No author, no terminal: every project is a repository, a commit
        # with no name and email behind it is one git refuses halfway through
        # the work, and a shell is where git is typed. bb-tty asks the same
        # question on the node, from the same answer (bb settings --json's
        # git_ready). Asked WITH the project this terminal is for, so an
        # author set for one repository alone opens a session there.
        # claude:<project>[:r:<id>] and sh:<n>:<project> put it in different
        # places, so the shape decides rather than a fixed index.
        bits = arg.split(":")
        want = (bits[1] if arg.startswith("claude:") and len(bits) > 1
                else bits[2] if arg.startswith("sh:") and len(bits) > 2 else "")
        if uid and (arg == "shell" or arg.startswith("sh:") or arg.startswith("claude:")) \
                and not users.git_ready(me, want):
            return (f"{me['name']} has no name and email for commits yet: set them on your "
                    "Profile (the gear in the header), or for one project in its settings "
                    "dialog, and open this again")
        if not arg.startswith("claude:"):
            return ""
        project = arg[len("claude:"):].split(":")[0]
        # A project whose map is still building (mapping.py): its first
        # session waits the few seconds, so its first question about the
        # tree is answered from an index rather than by building one. The
        # button carries the same sentence, and this is the check behind it.
        if mapping.held(project):
            return mapping.held(project)
        if not uid or not project:
            return ""                     # not an account: nothing to scope
        t = session_target(project, claude=True, node=_arg_node(arg), uid=uid)
        if t["where"] != "node":
            return ""
        # Claude Code on that node first (claudecode.py): an update running
        # there holds the start, and with Keep Claude Code current on, a
        # node behind is updated now and this start waits for it.
        return claudecode.start_hold(project, t["id"]) or ""

    def _term_notice(self, sentence, code):
        """A refused terminal, in the shape the asker can read. The tab is
        an iframe navigating to /term, so a JSON answer landed in it as the
        browser's JSON viewer (B141): a navigation gets a page saying the
        sentence, and a fetch still gets the JSON the tests and the page's
        own checks read."""
        if "text/html" not in (self.headers.get("Accept") or ""):
            return self._json({"error": sentence}, code)
        body = ("<!doctype html><meta charset=utf-8><title>BuilderBot</title>"
                "<style>body{margin:0;padding:20px 24px;background:#0d1117;"
                "color:#c9d1d9;font:14px/1.5 system-ui,sans-serif}"
                "p{max-width:64ch;margin:0}</style>"
                f"<p>{html_escape(sentence)}</p>").encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ttyd_port(self):
        """Which ttyd this request is relayed to: the writable one, or the
        read-only twin for an account that may not have a shell."""
        return TTYD_RO_PORT if users.may(self._who(), "terminal") else TTYD_PORT

    def _scoped_arg(self, rest, node=False):
        """Stamp the terminal's argument with the account that asked for it.

        ttyd runs bb-tty with whatever `?arg=` says, so this is where a
        terminal learns whose it is: the account is taken from the credential
        this request already proved and any `u:` the BROWSER sent is thrown
        away first. Trusting the browser's would make the whole thing a
        suggestion: one edited URL and you are in somebody else's home with
        their Claude login (roadmap #26).

        A request with no account behind it is left alone rather than
        refused. bb-tty reads that as the box's own home and the unprefixed
        session names, which is what every terminal got before accounts.
        """
        head, sep, query = rest.partition("?")
        if not sep or "arg=" not in query:
            return rest
        me = self._who()
        uid = users.uid_of(me)
        out = []
        for kv in query.split("&"):
            k, eq, v = kv.partition("=")
            if k == "arg" and eq:
                want = _ARG_NODE.sub("", _ARG_OWNER.sub("", urllib.parse.unquote_plus(v)))
                v = urllib.parse.quote(f"u:{uid}:{want}" if uid else want,
                                       safe="")
                out.append(f"{k}{eq}{v}")
                # Going to a NODE (roadmap #24), two more: the account's
                # name, since the node has no users.json to look one up in,
                # and a session token for the project, since only this
                # container's key can mint one. ttyd hands each ?arg= to
                # bb-tty as one more argument, and bb-tty takes them only
                # in the shapes it expects. The token is the same scoped
                # one the launcher would have minted here (one project,
                # user rights, an expiry), never the account's credential.
                project = _arg_project(want)
                if node and uid and project:
                    out.append("arg=" + urllib.parse.quote(
                        f"tok:{users.mint_session(project, uid=uid)}", safe=""))
                    out.append("arg=" + urllib.parse.quote(
                        f"name:{me.get('name', '')}", safe=""))
                    # The owner keeps the project directory on the node as
                    # here (session_dir in lib/common.sh says why), and the
                    # node has no store to know who that is.
                    if me.get("role") == "owner":
                        out.append("arg=owner%3A1")
                continue
            out.append(f"{k}{eq}{v}")
        return head + "?" + "&".join(out)

    def _term_proxy(self):
        """Everything under /term, relayed byte-for-byte to ttyd on the
        loopback, websockets included.

        This is what makes one login cover the terminals: the browser only
        ever talks to this origin, so the session cookie (or basic auth)
        checked before this call is the whole story, and ttyd's own port
        stays unpublished. The /term prefix is stripped because ttyd's
        client asks for everything relative to the page while ttyd itself,
        here or on a node, is rooted at /.

        For a websocket the handshake is forwarded and then the two sockets
        are spliced until either side closes. The client sends nothing
        between its request and the 101, so the handler's buffered reader
        holds no stray bytes when the splice takes over the raw socket. A
        plain request instead gets Connection: close upstream, which turns
        "relay until EOF" into the complete response.
        """
        refused = self._term_refused(self.path[len("/term"):])
        if refused:
            return self._term_notice(refused, 403)
        held = self._claude_held(self.path[len("/term"):])
        if held:
            # 409, not 403: nothing is wrong with the credential, the thing
            # asked for is taken. The name is the whole value of the record:
            # "somebody else has it" tells you nothing you can act on.
            return self._term_notice(held, 409)
        # Where this terminal lives (roadmap #24, phase 10b): a project bound
        # to a node whose session half is up is relayed to THAT machine's
        # ttyd (the same two ports, the same bb-tty, with the account and
        # its token stamped into the URL), and everything else stays on the
        # loopback. session_target says why a node cannot take one, and the
        # row's button carries the same sentence.
        rest0 = self.path[len("/term"):]
        # A SHELL is this container's own and always has been: a tree to look
        # at, the linters, git. Only a CLAUDE session needs a node, because
        # only Claude is the thing this container does not carry, so the
        # question is asked about a claude: argument and about nothing else.
        arg0 = _term_arg(rest0)
        target = session_target(_arg_project(arg0),
                                claude=arg0.startswith("claude:"),
                                node=_arg_node(arg0),
                                uid=users.uid_of(self._who() or {}) or "")
        if target["where"] == "refused":
            return self._term_notice(target["why"], 503)
        rest = self._scoped_arg(self.path[len("/term"):], node=target["where"] == "node")
        if not rest or rest.startswith("?"):
            # ttyd's client resolves "token" and "ws" against the page URL,
            # so the page must live under a trailing slash.
            self.send_response(302)
            self.send_header("Location", "/term/" + rest)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if target["where"] == "node":
            writable = not users.may(self._who(), "terminal")
            upstream = (target["host"], target["port"] if writable else target["ro_port"])
        else:
            upstream = ("127.0.0.1", self._ttyd_port())
        try:
            up = socket.create_connection(upstream, timeout=5)
        except OSError:
            if target["where"] == "node":
                return self._term_notice(f"{target['name']} did not answer on "
                                         f"{upstream[0]}:{upstream[1]}: its terminal server is "
                                         "reported up, but this controller could not reach "
                                         "it. A firewall between the two?", 502)
            # Through the notice, like a refusal (B141): the tab is an iframe
            # navigating here, and raw JSON landed in it as the browser's JSON
            # viewer, "Pretty-print" box and all.
            return self._term_notice("The terminal server is not running on this "
                                     "controller, so this terminal cannot open. "
                                     "Restarting the container starts it again.", 502)
        # The connect timeout must not become a *relay* timeout: it stays on
        # the socket, and a sendall that blocks longer than it (a big paste
        # into a busy terminal, a slow reader) would raise and drop a live
        # websocket. Reads are safe either way (select says readable first),
        # writes are not. Blocking with no deadline is what a splice wants.
        up.settimeout(None)
        ws = "upgrade" in self.headers.get("Connection", "").lower()
        lines = [f"{self.command} {rest} HTTP/1.1"]
        for k, v in self.headers.items():
            if k.lower() in ("authorization", "cookie", "connection", "keep-alive"):
                continue
            lines.append(f"{k}: {v}")
        lines.append("Connection: " + (self.headers.get("Connection", "Upgrade")
                                       if ws else "close"))
        # No Authorization upstream: ttyd binds the loopback and is started
        # with no --credential, because this proxy is the gate (15-dashboard.sh
        # says the same from the other end). It was sending the operator's
        # password on every terminal connection to a server that never looked
        # at it, and with accounts, there is no longer one password to send.
        self.close_connection = True
        down = self.connection
        sel = selectors.DefaultSelector()
        try:
            up.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
            self.wfile.flush()
            sel.register(up, selectors.EVENT_READ, down)
            sel.register(down, selectors.EVENT_READ, up)
            while True:
                for key, _ in sel.select():
                    data = key.fileobj.recv(65536)
                    if not data:
                        return
                    key.data.sendall(data)
        except OSError:
            pass                          # either side hung up mid-relay
        finally:
            sel.close()
            up.close()

    def _static(self, rel, ctype):
        """A file that IS the app (index.html and the tab scripts), served so
        a browser notices when the image changes.

        They went out with no validator and no cache directive at all, which
        leaves it to the browser's own heuristics: a phone could hold the old
        page across a container update and show yesterday's dashboard against
        today's server, with nothing on screen admitting it. `no-cache` is not
        "do not store", it is "ask me first", so the usual answer stays a 304
        of a few bytes and the new bytes arrive the moment the file changes.
        The tag is the file's own size and mtime, which is what changes when
        an image does, and costs one stat rather than a hash of 700KB.
        """
        try:
            st = (HERE / rel).stat()
            raw = (HERE / rel).read_bytes()
        except OSError:
            return self._json({"error": "not found"}, 404)
        tag = f'W/"{st.st_size:x}-{st.st_mtime_ns:x}"'
        if rel == "index.html":
            raw, tag = _versioned_page(raw, tag)
        body, zipped = self._gzip(raw)
        if self.headers.get("If-None-Match") == tag:
            self.send_response(304)
            self.send_header("ETag", tag)
            self.send_header("Cache-Control", "no-cache")
            return self.end_headers()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if zipped:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", tag)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        return self.wfile.write(body)

    def _gzip(self, body):
        """The body, compressed when the client takes gzip and it pays.

        The page is ~150KB of inline everything and the status snapshot a
        phone polls every fifteen seconds is tens of KB of JSON, and both shrink
        by roughly four fifths. Below ~1400 bytes (one MTU) the header
        shuffle costs more than it saves, so small answers go as they are.
        """
        if (len(body) >= 1400
                and "gzip" in self.headers.get("Accept-Encoding", "")):
            return gzip.compress(body, 6), True
        return body, False

    def _json(self, obj, code=200, cookie=None):
        # Held while _post records what a write means for the sessions: it
        # sends the reply itself once that is done (B290).
        if getattr(self, "_held", None) is not None:
            self._held.append((obj, code, cookie))
            return None
        body, zipped = self._gzip(json.dumps(obj).encode())
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        # A fresh session cookie, when the answer changed what the old one
        # was signed over, such as an account renaming itself.
        if cookie:
            self.send_header("Set-Cookie", f"bb_session={cookie}; Path=/; "
                             f"Max-Age={SESSION_DAYS * 86400}; HttpOnly; SameSite=Lax")
        # A session token's renewal, when _who decided one was due: bb and
        # the hooks read this header and write the token where bb looks.
        fresh = getattr(self, "_renewed", "")
        if fresh:
            self.send_header("X-BB-Session", fresh)
            self._renewed = ""
        # no-store, declared rather than assumed: preloading /api/status made
        # it cache-eligible, and a reload that revived a stale layout snapshot
        # from the browser cache then overwrote the real one on the next save.
        # State answers are for right now, never for later.
        self.send_header("Cache-Control", "no-store")
        if zipped:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _safely(self, fn):
        """Turn a handler blowing up into a 500 the page can show.

        Without this the exception unwinds past handle_one_request and the
        connection just closes, which the browser reports as a network error,
        the one failure mode that looks identical to the container being gone.
        """
        t0 = time.monotonic()
        try:
            try:
                return fn()
            finally:
                trace_note(self, (time.monotonic() - t0) * 1000)
        except (BrokenPipeError, ConnectionResetError):
            # The other end went away mid-answer: a download canceled, a tab
            # closed. Nothing failed here and nobody is left to answer, so it
            # is one quiet line, not a traceback that bb diag lists as a fault
            # (B429).
            print(f"[dashboard] {self.command} {self.path.partition('?')[0]}: the client left "
                  "before the answer was sent", flush=True)
        except Exception as e:                          # noqa: BLE001 (last resort)
            # Broad by definition: this is the one place a handler's bug is
            # turned into an answer. The log gets the traceback the answer
            # cannot carry.
            print(f"[dashboard] {self.command} {self.path.partition('?')[0]}: "
                  f"{type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
            try:
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            except OSError:
                pass                                    # client already left

    def do_GET(self):
        if not self._tunnel_refused():
            self._safely(self._get)

    def do_POST(self):
        if not self._tunnel_refused():
            self._safely(self._post)

    def _tunnel_refused(self):
        """A node's tunnel address asks for the agent's API or nothing
        (nodes.tunnel_refuses, R161): by the socket's own address, and
        through a tunnel from home (R170) by the hostname the node was
        enrolled at, or an edge's own headers, which only narrow their writer."""
        if NODES_OK:
            return False
        host = self.headers.get("Host", "")
        own = settings.get("tunnel_host") if not NODES_OK else ""
        why = nodes.tunnel_refuses(self.client_address[0] if self.client_address else "",
                                   self.path.partition("?")[0], host=host,
                                   # Cloudflare's own mark; other tunnels are known by the
                                   # hostname, and the controller's own public hostname (R176)
                                   # is one whatever rule the tunnel carries, so a rule left
                                   # wide reaches no page (bb.neat.fish answered its login, 11 Oct).
                                   edge="Cf-Ray" in self.headers
                                        or bool(own and host.lower().rsplit(":", 1)[0] == own))
        if why:
            self._safely(lambda: self._json({"error": why}, 403))
        return bool(why)

    # The favicon set, generated by `bb tool graphics favicon` from static/favicon.svg (the
    # header robot as a standalone file) and committed. An allow-list by full
    # path (the same shape as everything else the page can ask for), so this
    # never grows into a general file server by accident.
    FAVICONS = {
        "/favicon.ico": ("favicon.ico", "image/x-icon"),
        "/favicon.svg": ("favicon.svg", "image/svg+xml"),
        "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
        # The Nostromo scheme's decals: hand-written SVG, text in the tree
        # like the favicon's source, drawn by the page's CSS and by nothing
        # else. Same allow-list, same rule.
        "/static/nostromo/plate.svg": ("nostromo/plate.svg", "image/svg+xml"),
        "/static/nostromo/rings.svg": ("nostromo/rings.svg", "image/svg+xml"),
        "/static/nostromo/glyphs.svg": ("nostromo/glyphs.svg", "image/svg+xml"),
    }

    def _get(self):
        path = self.path.split("?")[0]
        # Nobody owns this container yet: everything but the assets the card
        # itself needs is the first-run screen. Not a redirect from /login
        # alone: a bookmark, a phone reopening the app, and the WebUI link
        # all arrive at "/", and each of them should land on the thing that
        # has to happen rather than on a sign-in with nothing to sign in to.
        if not users.all_users() and path not in ("/favicon.ico", "/favicon.svg"):
            return self._login_page(setup=True)
        if path == "/login":
            return self._login_page()
        if path == "/logout":
            return self._logout()
        if path.startswith("/api/v1/agent/"):
            return self._agent()
        if path == "/api/v1/healthz":
            # Open, like the agent door: a monitor asks this without the
            # operator's credential, and it says alive-and-the-store-answers
            # with two counts, nothing that names a machine (docs/nodes.md §9).
            body, code = ((jobs.healthz() if not NODES_OK
                           else ({"ok": False, "error": NODES_OK}, 503)))
            return self._json(body, code)
        if not self._authed():
            return self._deny()
        if path == "/metrics":
            if NODES_OK:
                return self._json({"error": NODES_OK}, 503)
            body = jobs.metrics_text().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        if path == "/term" or path.startswith("/term/"):
            return self._term_proxy()
        # The page's companion scripts: a new surface is a new classic-script
        # file beside index.html (docs/nodes.md §13), served by name from the
        # list the page's own script tags make (page_scripts), so it never
        # grows into a general file server by accident.
        if path.startswith("/") and path[1:] in page_scripts():
            return self._static(path[1:], "text/javascript; charset=utf-8")
        if self.path.split("?")[0] in ("/", "/index.html"):
            return self._static("index.html", "text/html; charset=utf-8")
        if fav := self.FAVICONS.get(self.path.split("?")[0]):
            name, ctype = fav
            try:
                body = (HERE / "static" / name).read_bytes()
            except OSError:              # a checkout that predates the assets
                return self._json({"error": "not found"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # A day: the icon changes when the image does, and a stale tab
            # icon for a day is invisible next to re-fetching it every poll.
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            return self.wfile.write(body)
        for how, route, name in GET_ROUTES:
            if (self.path == route) if how == "exact" else self.path.startswith(route):
                return getattr(self, name)()
        self._json({"error": "not found"}, 404)

    def _get_trace(self):
        """GET /api/trace?since=T: what this server was asked since T,
        grouped by endpoint (R75 step 4). For an admin or a session: the
        page's own behavior is what it describes, and a session diagnosing
        a tab that asks too much is the reader it exists for. Paths and
        query KEYS only, never values: a project's name in a query is the
        one thing here that is somebody's."""
        who = self._who()
        if not who or not (users.is_admin(who) or who.get("session")):
            return self._json({"error": "the trace is for an administrator or a session"}, 403)
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        try:
            since = float((q.get("since") or ["0"])[0])
        except ValueError:
            since = 0.0
        return self._json(trace_since(since))

    def _get_revs(self):
        """GET /api/revs."""
        # Deliberately tiny and deliberately cheap: this is polled every
        # second or two, where /api/status is polled every fifteen because
        # it runs git for every project. `p` is the projects the page has
        # notebooks open on, so the per-project half is one project's work
        # rather than the whole share's.
        # Absent and empty are different answers: a page with no notebook
        # open sends `p=` and wants none of the per-project tokens, where
        # `bb` and the tests send no `p` at all and want them all.
        # keep_blank_values, or `p=` parses to nothing at all and reads
        # as the absent case, which is the opposite answer.
        q = urllib.parse.parse_qs(self.path.partition("?")[2],
                                  keep_blank_values=True)
        raw = q.get("p")
        ps = None if raw is None else [x for x in (raw[0] or "").split(",") if x]
        return self._json(revisions(self._who(), ps))

    def _get_status(self):
        """GET /api/status."""
        return self._json(snapshot(self._who()))

    def _get_live(self):
        """GET /api/live: who has a Claude session on each project and which
        of them are working, the two maps the status payload also carries,
        alone and cheap. Fetched when the revs token `live` moves."""
        sessions = tmux_sessions() + node_tmux_sessions()
        return self._json({"claude_with": projsessions.with_(sessions),
                           "claude_busy": projsessions.busy(sessions),
                           "claude_where": projsessions.where(sessions)})

    def _get_findings(self):
        """GET /api/findings: findings.view, scoped to the projects this
        account sees, and for a session to its own."""
        me = self._who() or {}
        return self._json(findings.view(project_list(me), me.get("session") or ""))

    def _get_git(self):
        """GET /api/git: the notebook's Git view (gitview.view), for a
        project this account may see."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        try:
            n = int(q.get("n", ["0"])[0])
        except ValueError:
            n = 0
        return self._result(gitview.view(name, q.get("what", [""])[0], sha=q.get("sha", [""])[0],
                                         path=q.get("path", [""])[0], n=n,
                                         branch=q.get("branch", [""])[0]))

    def _get_changelog(self):
        """GET /api/changelog: changelog.reading, for a project this account
        sees."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(*changelog.reading(name, q.get("component", [""])[0]))

    def _get_version(self):
        """GET /api/version."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(version_payload(name))

    def _get_artifacts(self):
        """GET /api/artifacts: artifacts.tab_view, for a project this account
        sees."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(artifacts.tab_view(name, users.uid_of(self._who())))

    def _get_artifact(self):
        """GET /api/artifact: one file of a project's, as a download
        (artifacts.download)."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        got, status = artifacts.download(name, q.get("path", [""])[0], q.get("tree", [""])[0])
        if status != 200:
            return self._json(got, status)
        return self._attachment(*got, "application/octet-stream")

    def _get_meta(self):
        """GET /api/meta."""
        # What the companion app asks first: the surface number this
        # dashboard serves, the image it is, and where a newer app is.
        return self._json({"api": APP_API, "version": image_stamp().get("version") or "",
                           "image": image_stamp().get("rev") or "",
                           "built": image_stamp().get("built") or "", "apk": app_apk(),
                           "apk_sha256": app_apk_sha()})

    def _get_welcome(self):
        """GET /api/welcome: BuilderBot's own changelog for the welcome panel
        (changelog.welcome), and where this account last looked."""
        return self._json(changelog.welcome(str(users.prefs(self._who()).get("image_seen") or "")))

    def _get_source(self):
        """GET /api/source: the code base as a zip, from the Artifacts tab
        (artifacts.source_download). A person's download, so a session's
        token is refused: a session has the tree already."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if (self._who() or {}).get("session"):
            return self._json({"error": "a session has the tree already"}, 403)
        if self._not_project(name):
            return
        got, status = artifacts.source_download(name)
        if status != 200:
            return self._json(got, status)
        return self._attachment(*got, "application/zip")

    def _attachment(self, fname, data, ctype):
        """Bytes as a download named `fname`, which the caller has made safe
        for the header."""
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return None

    def _get_logs_download(self):
        """GET /logs/download: the container's own log, every project's
        traffic in it, or the diagnostics whole (logs.download). An
        administrator's, and the diagnostics the debug grant's."""
        if self._refused("admin"):
            return None
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        if (q.get("what") or [""])[0] == "diag" and self._refused("debug"):
            return None
        got, status = logs.download((q.get("what") or [""])[0], self._principal())
        if status != 200:
            return self._json(got, status)
        return self._attachment(*got)

    def _get_phone(self):
        """GET /api/phone."""
        # Not on the status poll: a probe is a job on a node, so the tab
        # asks when it is opened or pressed, and reads the cache between.
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        # A probe is a job on the named node, and a session's token is
        # bound to one project's node and no other (the same rule the
        # jobs endpoint keeps): a session reads the cache, an account
        # may ask the node.
        return self._json(self._phone_payload(node=(q.get("node") or [""])[0],
                                              probe=bool(q.get("probe")) and not (self._who() or {}).get("session")))

    def _get_phone_wait(self):
        """GET /api/phone/wait?since=T: the companion app's live connection
        (R125). Answers {token} at once when this account's phone asks,
        lease or grants differ from T, else holds the request until they
        do or about 45 s pass, so an ask reaches the app in a second rather
        than on Android's alarm. A person's, not a session's."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "the live connection is the companion app's"}, 403)
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        since = q.get("since", [""])[0]
        uid, admin = users.uid_of(who), users.is_admin(who)
        end = time.time() + PHONE_WAIT_S
        while True:
            tok = phone.wait_token(uid, admin)
            if tok != since or time.time() >= end:
                return self._json({"token": tok})
            time.sleep(0.5)

    def _get_toolchains(self):
        """GET /api/toolchains."""
        # ?node= asks about another node's toolchain store: what its
        # census says it has, and the toolchain job in flight there. The
        # catalog is the same; the state is the node's (docs/nodes.md §6).
        # Without Toolchains Read the tab is not offered (R152 step 3), and
        # this answers only for the nodes of the person's own projects,
        # which _node_asked keeps it to: what their projects build with.
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        nid, why = self._node_asked(q.get("node", [""])[0])
        if why:
            return self._json({"error": why, "toolchains": []})
        if nid and nid != "local" and not NODES_OK:
            return self._json(toolchains.payload_for_node(nid))
        return self._json(toolchains.payload())

    def _get_emulator(self):
        """GET /api/emulator?node=ID: that node's system images, what could be
        added, and the image job there. The same node scope as Toolchains."""
        if NODES_OK:
            return self._json({"error": "the node store did not open"})
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        nid, why = self._node_asked(q.get("node", [""])[0])
        if why or not nid:
            return self._json({"error": why or "no node named"})
        return self._json(emulator.payload(nid))

    def _get_users(self):
        """GET /api/users."""
        # The listing never carries a hash; all_users() drops it. Projects
        # come from the same filtered list everything else reads, so an
        # admin cannot hand out what they cannot see themselves. Accounts
        # and roles Read lets one see it (R152 step 3).
        if (why := self._area_read_why("accounts")):
            return self._json({"error": why}, 403)
        return self._json(users.tab_view(self._who(), [p["name"] for p in project_list(self._who())],
                                         claudegrant.logins_of))

    def _get_roles(self):
        """GET /api/roles: the Roles tab (R152): the areas, every role, and
        each account with its Global roles, the roles it holds on each
        project and the projects it is on. An administrator's whole; a
        project's owner sees the people and roles of the projects they own,
        to give those (users.assignable)."""
        me = self._who() or {}
        can = users.assignable(me)
        if not can["admin"] and not can["projects"]:
            return self._json({"error": "the Roles tab is an administrator's, or a project owner's "
                                        "for their own projects"}, 403)
        scope = None if can["admin"] else set(can["projects"])
        people = []
        for u in users.all_users():
            full = users.get(u["name"]) or {}
            pr = full.get("project_roles") if isinstance(full.get("project_roles"), dict) else {}
            on = list(full.get("projects") or [])
            if scope is not None:
                pr = {p: r for p, r in pr.items() if p in scope}
                on = [p for p in on if p in scope]
            people.append({"name": u["name"], "uid": u["uid"], "role": u["role"],
                           "roles": [r for r in roles.roles_of(full) if r not in ("user",)] if can["admin"] else [],
                           "project_roles": pr, "projects": on})
        all_projects = [p["name"] for p in project_list(me)] if scope is None else sorted(scope)
        rs = roles.all_roles()
        if scope is not None:
            rs = {n: r for n, r in rs.items() if r.get("scope") == "projects"}
        # A project's owner role is named after its directory; the tab says
        # whose it is by the name the project is shown under (R154).
        owners_of = {roles.owner_role_name(d): d for d in registry.labels()}
        rs = {n: (dict(r, label=f"owner of {registry.label(owners_of[n])}") if n in owners_of else r)
              for n, r in rs.items()}
        return self._json({"roles": rs, "areas": [list(a) for a in roles.AREAS], "people": people,
                           "projects": all_projects, "admin": can["admin"], "me": me.get("name") or "",
                           "owner": users.owner_name() or "", "node_areas": sorted(roles.NODE_AREAS),
                           "nodes": [] if NODES_OK or not can["admin"] else
                           [{"id": n["id"], "name": n["name"]} for n in nodes.node_list()
                            if n.get("kind") != "local" and n.get("state") != "retired"]})

    def _get_nodes(self):
        """GET /api/v1/nodes: the Nodes tab's read (nodes.tab_view), scoped to
        this account."""
        # The versioned surface starts here (docs/nodes.md §3): new
        # endpoints land under /api/v1 with their shapes written down;
        # the unversioned paths above migrate later, never both at once.
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        # Without Nodes Read the tab is not offered (R152 step 3), and this
        # answers with the nodes of the person's own projects alone, which a
        # Claude sign-in on them needs, as below.
        # Scoped for an account that may not change a node: it sees the
        # ones its own projects build on and no others, because the list
        # is otherwise a way to learn what machines exist and what they
        # are called (roadmap #27). An administrator sees the registry.
        return self._json(nodes.tab_view(self._nodes_for(nodes.node_list()),
                                         users.may(self._who(), "admin") == ""))

    def _get_jobs(self):
        """GET /api/v1/jobs: nodes.jobs_view, narrowed to the projects this
        account may see unless it administers."""
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        me = self._who()
        mine = None if users.may(me, "admin") == "" \
            else {p["name"] for p in project_list(me)}
        # Without Jobs Read a person sees their projects' jobs alone, those
        # they may read (R152 step 3); the Jobs tab is hidden for them.
        if mine is not None and not (me or {}).get("session") and self._area_read_why("jobs"):
            mine = {p for p in mine if roles.level_of(me, "projects", p, users.may_work)}
        # The node's own jobs (a toolchain install, an update) for whoever may
        # read the controller's diagnostics, which list them: a job named
        # there that could not be opened was a dead end (the operator, 7 Oct).
        # Through diag's redaction, as the diagnostics themselves are.
        system = diag.redact if mine is not None and not self._diag_why() else None
        return self._json(*nodes.jobs_view(q.get("id", [""])[0], q, mine, system))

    def _get_docker(self):
        """GET /api/docker: the manager's whole page, containers.manager_view,
        for the node this account may read."""
        # No node named means the default, which is the arrangement that
        # predates the picker.
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        me = self._who() or {}
        sess = me.get("session") or ""
        # A session reads its own project's node, which is where it works,
        # whatever it asks for. Anybody else naming a project and no node
        # reads that project's (bb devapp ls outside a session).
        asked = q.get("node", [""])[0]
        proj = q.get("project", [""])[0]
        if sess or (not asked and proj):
            # A named project reads its own node's daemon, allowed by the
            # project being the account's to see rather than by the node
            # scope (B258); the filter below still keeps the answer to the
            # account's projects. A project with no node has no daemon and
            # no containers anywhere: there is no primary docker manager for
            # it to fall to (the operator, 25 Sep), so that is said.
            if not sess and self._not_project(proj):
                return None
            # A session reads its own project's containers, and those of a
            # project it reads (bb -p NAME devapp, B551/B552): reading them
            # is what reads means. Acting on them stays its own project's.
            name = proj if sess and proj and proj != sess and self._reads(proj) else sess or proj
            nid, why = devapp.project_daemon(name), None
            if not nid:
                return self._json({"error": f"{name} has no node, so it has no containers anywhere. "
                                            + no_node_advice(name),
                                   "blind": True, "instances": [], "containers": []})
        else:
            nid, why = self._node_asked(asked)
        if why:
            return self._json({"error": why, "blind": True,
                               "instances": [], "containers": []})
        # What an account that is not an administrator sees is what belongs
        # to its projects, a session's to its own one (the operator, 24 Sep).
        seen = None
        if sess or self._node_scope() is not None:
            seen = {name} if sess else {p["name"] for p in project_list(me)}
        # ...and of those, the projects whose Containers this person may
        # read (R152 step 3).
        if seen is not None and not sess and not users.is_admin(me):
            seen = {p for p in seen if roles.level_of(me, "containers", p, users.may_work)}
        return self._json(containers.manager_view(nid, seen))

    def _get_containers(self):
        """GET /api/containers."""
        # A read, and the only one this dashboard makes of the daemon
        # beyond `docker version` (see the guard in devapp.py, which
        # allows it and still refuses anything that would change something).
        # Everything on the daemon, every project's: an administrator's.
        if self._refused("admin"):
            return None
        return self._json(devapp.containers())

    def _get_project_job(self):
        """GET /api/project-job."""
        if self._refused("create"):
            return None
        return self._json(projects.job())

    def _get_trash(self):
        """GET /api/trash."""
        if self._refused("trash"):
            return None
        return self._trash_list()

    def _get_claude_now(self):
        """GET /api/claude-now."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json({"model": claude_model_now(WORKSPACE / name, users.uid_of(self._who()))})

    def _get_todo(self):
        """GET /api/roadmap."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json({"project": name} | roadmap.panel(name, sessions_anywhere(),
                                                            users.tmux_prefix(self._who())))

    def _get_rules(self):
        """GET /api/rules."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        # With the number a Save is checked against (B195): read in the same
        # answer as the rules, so the two cannot describe different moments.
        who = self._who() or {}
        # Whether this person may change the global rules themselves, which
        # the notebook offers beside the project's own switch for each.
        admin = users.is_admin(who) and not who.get("session")
        return self._json(rules.payload(name) | {"rev": rules.rev(name), "may_global": admin})

    def _get_global_rules(self):
        """GET /api/global-rules."""
        # Readable by anybody signed in, because it is the same text their
        # sessions are already handed. Hiding it would only make the Briefing
        # tab unable to say where a rule came from.
        return self._json({"rules": rules.globals_now(), "max": rules.MAX_RULES})

    def _get_preamble(self):
        """GET /api/preamble."""
        # What a session started here is handed, exactly: the Briefing tab
        # shows it so the block is a thing a person can read rather than
        # something that only exists inside a launcher. Readable by anyone
        # who can see the project: it is their own rules, roadmap and
        # bugs, already on the three tabs beside it.
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        # The asker's own reply style rides the block, as it does for the
        # session bb-tty starts for them.
        mine = prefs.all_for_user(users.uid_of(self._who())).get(name) or {}
        return self._json(preamble.payload(name, reply=mine.get("reply") or "", asks=mine.get("asks") or ""))

    def _get_brief(self):
        """GET /api/brief: brief.view, the brief waiting in a project's tree
        and the one kept after it left, for a project this account sees."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(brief.view(name, users.uid_of(self._who())))

    def _brief(self, req):
        """POST /api/brief: the first Claude press's Build it and Start
        without it, and a session's take as it starts: brief.verb, behind the
        gates here."""
        name = field(req, "project")
        if self._not_project(name):
            return
        who = self._who() or {}
        # A take is a session starting on its own project; the dialog's two
        # change the project's tree, so they are asked of an account that
        # works on it.
        if field(req, "action") != "take" and self._readonly(name):
            return
        return self._json(*brief.verb(name, req, users.uid_of(who), who.get("name") or "somebody",
                                      bool(who.get("session"))))

    def _get_design(self):
        """GET /api/design: design.view, a project's design language, its
        pages and the vocabulary they are drawn from, for a project this
        account sees; a session reads it too, through bb design."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        # ?show= is bb design's: the words rather than the record, so a
        # session prints what the tab shows and nothing is assembled twice.
        show = q.get("show", [""])[0]
        if show:
            text, err = design.text_for(name, show)
            return self._json({"error": err} if err else {"text": text}, 404 if err else 200)
        return self._json(design.view(name))

    def _design(self, req):
        """POST /api/design: a Design section's Save of the language and the
        pages, and the file written into the tree: design.verb, for an
        account that works on the project."""
        name = field(req, "project")
        if self._not_project(name) or self._readonly(name):
            return
        who = self._who() or {}
        req["mine"] = users.tmux_prefix(who)
        return self._json(*design.verb(name, req, who.get("name") or "somebody",
                                       bool(who.get("session"))))

    def _get_wiki(self):
        """GET /api/wiki: the project's wiki (wiki.view), or one page of it
        with ?page=, for an account that sees the project; a session reads
        it too, through bb wiki."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        no = wiki.hidden_for(name, bool((self._who() or {}).get("session")))
        if no:
            return self._json({"error": no}, 403)
        pg = q.get("page", [""])[0]
        if pg:
            try:
                return self._json(wiki.page(name, pg))
            except wiki.Refused as e:
                return self._json({"error": str(e)}, 404)
        return self._json(wiki.view(name))

    def _get_ci_runs(self):
        """GET /api/ci-runs: a project's runs on GitHub's own runners, or
        with ?run=N (0 the newest finished) that run's jobs and the end of
        each failed job's log (cilogs), for an account that sees the
        project; a session reads it through bb ci-log."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        run = q.get("run", [""])[0]
        if run and not run.isdigit():
            return self._json({"error": "a run is named by its number"}, 400)
        try:
            return self._json(cilogs.log(name, int(run)) if run else cilogs.runs(name))
        except cilogs.Refused as e:
            return self._json({"error": str(e)}, 409)

    def _get_ci_watch(self):
        """GET /api/ci-watch: what the last look at a project's CI found
        (ciwatch.read), for an account that sees the project."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(ciwatch.read(name))

    def _ci_watch(self, req):
        """POST /api/ci-watch: look at a project's CI now (ciwatch.look),
        for an account that sees the project; the answer is what it found."""
        name = field(req, "project")
        if self._not_project(name):
            return
        if not ciwatch.claim(name):
            return self._json({"error": "a look at this project's CI is already running"}, 409)
        try:
            return self._json(ciwatch.look(name))
        finally:
            ciwatch.release(name)

    def _get_wiki_export(self):
        """GET /api/wiki-export: the wiki as a zip of its Markdown pages,
        whether or not the project has a remote."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        no = wiki.hidden_for(name, bool((self._who() or {}).get("session")))
        if no:
            return self._json({"error": no}, 403)
        try:
            fname, data = wiki.export_zip(name)
        except wiki.Refused as e:
            return self._json({"error": str(e)}, 404)
        return self._attachment(fname, data, "application/zip")

    def _wiki(self, req):
        """POST /api/wiki: a page saved, removed or renamed, and the wiki
        pushed to or pulled from the forge's (wiki.verb), for an account
        that works on the project. A session's writes go through the
        project's dial, Claude may: Write the wiki."""
        name = field(req, "project")
        if self._not_project(name) or self._readonly(name):
            return
        who = self._who() or {}
        ident = users.git_identity(who, name) or {}
        author = {"name": ident.get("name") or who.get("name") or "somebody", "email": ident.get("email") or ""}
        return self._json(*wiki.verb(name, req, author, bool(who.get("session"))))

    def _get_codebase(self):
        """GET /api/codebase."""
        # What git tracks in the project, by language: the Briefing
        # tab's first section. Tracked files only, cached by commit.
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(codebase.payload(name))

    def _get_pending(self):
        """GET /api/pending."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(pending.payload(name))

    def _get_memory(self):
        """GET /api/memory."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        # Against what this account may see, like every read above it:
        # this one passed the name straight through (bug #68).
        if self._not_project(q.get("project", [""])[0]):
            return
        got = memory.payload(q.get("project", [""])[0], sessions_anywhere(),
                             home=home_for(users.uid_of(self._who())))
        return self._json(got if got is not None
                          else {"error": "not a project"}, 400 if got is None else 200)

    def _get_tests(self):
        """GET /api/tests."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(testreg.payload(name))

    def _get_bugs(self):
        """GET /api/bugs."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(bugs.payload(name))

    def _get_pubkeys(self):
        """GET /api/pubkeys."""
        # The shielded agent's public halves, for the New project dialog:
        # picking one selects it for the clone, and showing it is how the
        # operator gets it onto GitHub's deploy-key page in the first
        # place. Public keys are the shareable part: nothing here can
        # reach the private material, by construction. `pat` rides along
        # so the dialogs can say whether a deploy key is optional (a PAT
        # covers https) or the only way a push can authenticate. The
        # dialog is an administrator's, and so is this.
        if self._refused("create"):
            return None
        # The forge catalog rides along rather than costing a fetch of its
        # own: the dialog that wants the keys is the dialog that wants the
        # list of hosts, and it is drawn once from one answer. `hosts` is
        # what the operator has already said their own servers run, so the
        # clone form knows not to ask a question it has the answer to.
        return self._json({"keys": agent_keys(), "pat": gh_authed(),
                           "forges": forges.catalog(),
                           "hosts": forges.known()})

    def _read_json(self):
        """The body, once. Read here rather than in each handler: doing it
        after dispatch is how the request stream ends up consumed twice or
        not at all. None means an answer was already sent."""
        try:
            n = int(self.headers.get("Content-Length", "0"))
            most = MAX_BODY_FOR.get(self.path.partition("?")[0], MAX_BODY)
            if not 0 <= n <= most:
                self._json({"error": f"body too large: {n} bytes, and this takes {most}"}, 413)
                return None
            req = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, TypeError):
            self._json({"error": "bad request"}, 400)
            return None
        if not isinstance(req, dict):
            self._json({"error": "bad request"}, 400)
            return None
        return req

    def _post(self):
        # Before the credential check, because there is nothing to check
        # against yet, and closed by its own effect the moment there is.
        if self.path.split("?")[0] == "/setup":
            return self._setup_post()
        if self.path.split("?")[0] == "/login":
            return self._login_post()
        if self.path.split("?")[0].startswith("/api/v1/agent/"):
            # Its own door, before the operator's: an agent carries a node
            # token, never the dashboard credential (docs/nodes.md §8: the
            # controller holds nothing that logs in anywhere, and a node
            # holds nothing that opens this page).
            return self._agent()
        if not self._authed():
            return self._deny()
        # The one body that is not JSON: an archive to start a project from,
        # streamed to the spool by projects.spool_archive. Its own door
        # before the JSON read, and its own cap: MAX_BODY is sized for a
        # form, and an upload is not read into memory at all.
        if self.path.split("?")[0] == "/api/upload-archive":
            return self._upload_archive()
        req = self._read_json()
        if req is None:
            return None

        path = self.path.split("?")[0]
        # Door 2, at the one funnel every mutation passes: when, who, what,
        # on what, with a parameter digest, never the parameters, which
        # carry tokens and env text. The principal is the signed-in account
        # (`user:<name>`), which is a string rather than a boolean precisely
        # so it could become one: OIDC later is a new way to fill it in, not
        # a new row shape. (Bug #16's caveat still applies, narrowed: anything
        # holding an account's credential writes as that account, because the
        # server cannot tell the person from the session they started.)
        if not NODES_OK:
            act = path + (":" + str(req["action"])[:40]
                          if isinstance(req.get("action"), str) else "")
            db.audit(self._principal(), act,
                        str(req.get("project") or req.get("name")
                            or req.get("id") or "")[:120], req)
        for how, route, name in POST_ROUTES:
            if (path == route) if how == "exact" else path.startswith(route):
                # What a write to the notebook or the settings means for the
                # sessions is recorded before its reply goes, not after: the
                # reply is what lets a session send its next prompt, and one
                # that overtook the record was told about its own write as
                # somebody else's (B290). So the reply is held until then.
                own = any(path.startswith(r) for r in OWN_WRITE_ROUTES)
                self._held = [] if own else None
                try:
                    out = getattr(self, name)(req)
                    if own:
                        # A session's own write to its project's notebook or
                        # settings is seen by it as it lands (session_seen_note).
                        # The token's own uid, as the hook reads it: uid_of answers
                        # "" for a session on purpose, and that is the per-account
                        # stores' rule, not this one's.
                        who = self._who() or {}
                        if who.get("session"):
                            session_mark_own(who["session"], who.get("uid") or "", who)
                        elif path.startswith("/api/memory") and _memory_written(req, self._held):
                            _mem_edited(field(req, "project"))
                finally:
                    held, self._held = self._held, None
                for obj, code, cookie in held or ():
                    self._json(obj, code, cookie=cookie)
                return out
        self._json({"error": "not found"}, 404)

    def _reset(self, req):
        """POST /api/reset: start over at onboarding (settings.reset), and the
        dashboard re-executes itself so the next page is Create the owner.
        The confirm word is the whole of the safety: this is an
        administrator typing "reset" into a red box."""
        if self._refused("admin"):
            return None
        if str(req.get("confirm") or "") != "reset":
            return self._json({"error": "type reset to confirm; nothing was changed"}, 400)
        # The nodes to un-enroll first (the operator, 12 Oct): each uninstalled
        # and retired before anything is moved, since the record of them is
        # what moves, and the reset follows once every one has reported.
        ids = [str(x) for x in (req.get("unenroll") or []) if isinstance(x, str)]
        if ids:
            with _reset_lock:
                if _reset_job.get("running"):
                    return self._json({"error": "a reset is already under way"}, 409)
                rows = nodes.reset_unenroll(self._principal(), ids, req.get("stores") is True)
                bad = [x for x in rows if x["error"]]
                if bad:
                    return self._json({"error": "; ".join(f"{x['name']}: {x['error']}" for x in bad),
                                       "nodes": rows}, 409)
                _reset_job.clear()
                _reset_job.update(running=True, nodes=rows, error="", started=time.time())
            threading.Thread(target=_reset_after, args=(self._principal(),), daemon=True).start()
            return self._json({"ok": True, "unenrolling": rows})
        r, status = settings.reset(STATE)
        if status != 200:
            return self._json(r, status)
        print(f"dashboard: {self._principal()} reset this controller; the old state is in "
              f"{r['moved_to']}" + (f"; kept: {', '.join(r['kept'])}" if r["kept"] else ""), flush=True)
        threading.Timer(1.0, lambda: os.execv(sys.executable, [sys.executable, *sys.argv])).start()
        return self._json(r)

    def _settings_post(self, req):
        """POST /api/settings."""
        # The Settings tab's fields (R29): an administrator's, validated
        # and applied by the store; the answer is the tab's next drawing.
        if self._refused("admin"):
            return
        # The Debugging group (debug mode and what it opens) is the debug
        # grant's, named only (the operator, 6 Oct); only a change is asked.
        want = req.get("set") if isinstance(req.get("set"), dict) else {}
        if any(k in DEBUG_SETTINGS and want[k] != settings.get(k) for k in want) and self._refused("debug"):
            return
        # Finish on the setup page (R199): the first node is the one step
        # that cannot wait, so it is checked here and not only on the page.
        if want.get("setup_done") is True and not settings.get("setup_done") and not setup_node():
            return self._json({"error": "enroll a node first: Finish needs one enrolled and answering"}, 409)
        r = settings.set_many(req.get("set") or {})
        if r.get("error"):
            return self._json(r, 400)
        # The home tunnel follows its settings at once (R176): the process
        # started, restarted or stopped, and with an API token the hostname's
        # record and the tunnel's rules written; what happened rides back.
        if any(k in TUNNEL_SETTINGS for k in want):
            r["tunnel"] = tunnel.apply()
            if settings.secret("cf_api_token") and settings.secret("tunnel_token") and settings.get("tunnel_host"):
                r["published"] = tunnel.publish(settings.secret("cf_api_token"))
        return self._json(r | settings.payload())

    def _prefs_post(self, req):
        """POST /api/prefs: a project's settings dialog, saved by
        prefs.dialog_save behind the gates here."""
        name = req.get("project", "")
        # A session may not change the settings of the project it runs
        # in (the gate that holds its own additions, the commands a
        # build runs, the identity its commits carry), and nobody may
        # change a project they cannot see or have not taken on.
        if (self._who() or {}).get("session"):
            return self._json({"error": "a project's settings are the operator's: "
                                        "say what should change in your reply"}, 403)
        if self._not_project(name):
            return
        if self._readonly(name):
            return None
        # Everything else in this dialog is the project's own; the node is
        # not, because a node is shared and moving a project onto one
        # reaches every other project there. Only a CHANGE is asked about
        # (B488): the dialog sends every field on every save.
        if ("node" in req or "nodes" in req) and prefs.node_changed(name, req) \
                and self._refused("node", name):
            return
        # A hosting-only node holds no project: its code and its sessions are
        # what the flag keeps off it (nodes.host_only).
        if ("node" in req or "nodes" in req) and not NODES_OK:
            want = (req.get("nodes") if isinstance(req.get("nodes"), list) else []) + [req.get("node") or ""]
            host = [(nodes.node(n) or {}).get("name") or n for n in want if n and nodes.host_only(n)]
            if host:
                return self._json({"error": f"{', '.join(host)} hosts containers only: no project's code "
                                            "or sessions go there. Send a container to it from the "
                                            "Docker tab instead"}, 400)
            # A disabled node is kept but not offered (the operator, 11 Oct).
            off = [(nodes.node(n) or {}).get("name") or n for n in want
                   if n and (nodes.node(n) or {}).get("state") == "disabled"]
            if off:
                return self._json({"error": f"{', '.join(off)} is disabled on the Nodes tab: Enable it there first"}, 400)
        # The hosting nodes its containers may also go to (prefs.hosts): a
        # node is shared, so naming one is for whoever may set the project's
        # node, and only a hosting-only node is one: a node that holds the
        # project is in its node set already. Only a change is asked about.
        if req.get("hosts") is not None and prefs.hosts_changed(name, req.get("hosts")):
            if self._refused("node", name):
                return
            if not NODES_OK:
                got = req.get("hosts") if isinstance(req.get("hosts"), list) else str(req.get("hosts")).split(",")
                bad = [(nodes.node(n) or {}).get("name") or n for n in got
                       if str(n).strip() and not nodes.host_only(str(n).strip())]
                if bad:
                    return self._json({"error": f"{', '.join(bad)} is not a hosting-only node: a node the "
                                                "project works on takes its containers already, from Where it runs"}, 400)
        # Which other projects a session here may read is BuilderBot's
        # owner's alone (the operator, 6 Oct): it hands one project's sessions
        # another's code and notebook, which no administrator or user grants
        # on their own say. Only a change is asked about.
        if req.get("reads") is not None and prefs.reads_changed(name, req.get("reads")) \
                and (self._who() or {}).get("role") != "owner":
            return self._json({"error": "which other projects a project's sessions may read is set by "
                                        "BuilderBot's owner alone"}, 403)
        # ...and so are the places on it a session here is shown (sees): a
        # share on a node is every project's there, so naming one is for
        # whoever may set the node. Only a change is asked about.
        if req.get("sees") is not None and prefs.sees_changed(name, req.get("sees")) \
                and self._refused("node", name):
            return
        # ...and the addresses its sessions may still reach where the node
        # filters their network (the operator, 7 Oct): a hole in a shared
        # node's firewall that reaches past the project, so an
        # administrator's. The node hears it at once, since the sets it
        # fills are rebuilt live.
        reach = req.get("reaches") is not None and prefs.reaches_changed(name, req.get("reaches"))
        if reach and self._refused("admin"):
            return
        # The node's own address is not one this opens: a session's traffic
        # to its own node is judged on the way in, where only the controller
        # and the resolvers pass, and its containers are reached as its own.
        if reach and not NODES_OK:
            ids = req.get("nodes") if isinstance(req.get("nodes"), list) else (prefs.get(name) or {}).get("nodes") or []
            addr_of = {n: str(((nodes.node(n) or {}).get("agent") or {}).get("addr") or "") for n in ids}
            got = req.get("reaches") if isinstance(req.get("reaches"), list) else str(req.get("reaches")).split(",")
            for e in (prefs._reach_entry(x) for x in got):
                on = e["nodes"] or ids
                own = [n for n in on if addr_of.get(n) and addr_of[n] == e["addr"].split(":")[0]]
                if own:
                    name_of = (nodes.node(own[0]) or {}).get("name") or own[0]
                    return self._json({"error": f"{e['addr']} is {name_of} itself: a session there reaches its "
                                                "node's containers as its own, and nothing else on its node"}, 400)
        # ...and what its sessions may read for debugging (the machine logs
        # of named nodes, the controller's diagnostics): the debug grant's,
        # per project rather than per node (the operator, 6 Oct).
        if prefs.debug_changed(name, req) and self._refused("debug"):
            return
        # ...nor is the dial that hands a session this project's container:
        # it lets a session create one and set its env, which is Docker
        # configuration, an administrator's (docker-write). Only a CHANGE is
        # asked about, since the dialog sends every field on every save.
        if req.get("devbuild") is not None \
                and str(req.get("devbuild")) != prefs.get(name)["devbuild"] \
                and self._refused("docker-write"):
            return
        held = (("node" in req or "nodes" in req) and prefs.node_changed(name, req)) \
            or (req.get("reads") is not None and prefs.reads_changed(name, req.get("reads")))
        got = prefs.dialog_save(name, req, users.uid_of(self._who()))
        if reach and not got[0].get("error"):
            net_nudge()
        # A synced node that now holds this project (or stops) hears it at
        # once, so its first copy starts and the Claude button follows it.
        if held and not got[0].get("error") and not NODES_OK:
            wssync.held_changed()
        return self._json(*got)

    def _nodes(self, req):
        """The Nodes tab's verbs. Thin on purpose: an administrator's, and
        nodes.verb says what each one means and writes its audit row."""
        if self._refused("admin"):
            return
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        return self._json(*nodes.verb(self._principal(), req))

    def _jobs(self, req):
        """The Jobs tab's one verb, and where `bb run`, `bb build`, `bb test`
        and `bb emu` land from the controller (nodes.run_job). A queued job
        is ended; a running one is flagged and its runner told, and the row
        moves when the runner reports that it stopped, which is when it
        did."""
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        act = field(req, "action")
        if act in ("run", "emu"):
            # Never from a session (R35). A session is on its project's node and
            # runs these verbs where it is, inside its view; a job runs as the
            # node's enrolled account, outside every view and in the docker
            # group, so a session token that could queue one would read every
            # project on the machine and be root on it. Measured on
            # bb-dev-sandbox, 16 Sep, before this refusal.
            if (self._who() or {}).get("session"):
                return self._json({"error": "a session runs bb run, build, test and emu where it "
                                            "is, on its project's node; a job would run outside "
                                            "the session's view, so a session cannot queue one"}, 403)
            # ...nor from an account without the right: the same job queued with
            # a password instead of a token is the same command in the same
            # docker group. Nothing on the page queues one for a plain user; bb
            # on the controller does, for an administrator.
            if (why := users.may(self._who(), "jobs")):
                return self._json({"error": why}, 403)
            name = field(req, "project")
            if name not in {p["name"] for p in project_list(self._who())}:
                return self._json({"error": "not a project"}, 400)
            # ...and by grant on the node the job would run on (R137 step
            # 3): the one named, else the project's primary, as run_job
            # picks it.
            pf = prefs.get(name) or {}
            on = field(req, "node") or pf.get("node") or (pf.get("nodes") or [""])[0]
            if (why := users.may_node(self._who(), "jobs", on)):
                return self._json({"error": why}, 403)
            return self._json(*nodes.run_job(name, req, self._principal()))
        if act != "cancel":
            return self._json({"error": "unknown action"}, 400)
        # Whose it is, the way the read is scoped: an account cancels the
        # jobs of its projects and a session its own project's; a stranger's
        # job and a missing one answer alike.
        me = self._who()
        mine = None if users.may(me, "admin") == "" else {p["name"] for p in project_list(me)}
        if mine is not None:
            j = nodes.job(field(req, "id"), with_log=False)
            if not j or j.get("project") not in mine:
                return self._json({"error": "no such job of yours"}, 403)
        return self._result(jobs.cancel(self._principal(), field(req, "id")))

    def _claude_login(self, req):
        """A node saying what this account is signed in to Claude AS there
        (R47), or that it is not: never the login itself, which stays on the
        machine that made it (claudegrant.py says why).

        Only a session token minted FOR an account speaks here (the one the
        terminal proxy stamps into a node-bound terminal's URL, or the one a
        sign-in job carries), and only for that account: the account is in
        the token, signed, not in a parameter. Which node is reporting is
        not taken from the request either: a sign-in job's token names the
        node it was queued on, and a session's names a project, whose node
        it is on. A machine that could name itself could report for another.
        """
        me = self._who()
        if not me:
            return self._json({"error": "not signed in"}, 401)
        uid = me.get("uid") if me.get("session") else ""
        if not uid:
            return self._json({"error": "a Claude sign-in is reported with a session token "
                                        "minted for an account, the one a node-bound "
                                        "terminal carries"}, 403)
        proj = me.get("session") or ""
        if proj.startswith("node:"):
            nid = proj[5:] if nodes.node(proj[5:]) else ""
        else:
            # The node this session was started on, which the project's
            # other nodes make a question (R82): named by the session, and
            # believed only when it is one of the project's own.
            p = prefs.get(proj) or {} if proj else {}
            asked = field(req, "node")
            nid = asked if asked and asked in [p.get("node"), *(p.get("nodes") or [])] else p.get("node") or ""
        if not nid:
            return self._json({"error": "a sign-in is reported by a session on the "
                                        "node it happened on"}, 400)
        r = claudegrant.report(home_for(uid), nid, req.get("email") or "", req.get("plan") or "",
                               signed_in=bool(req.get("signed_in", True)))
        return self._json(r, 400 if r.get("error") else 200)

    def _tty_grant(self, req):
        """Whose terminal a node's bb-tty is about to start, answered here
        (B166).

        On this container ttyd is loopback-only and /term is the one way in,
        so the account _scoped_arg stamps is the account that proved itself.
        A node's ttyd is on the node, and a session there reaches it over
        loopback like any other process on the machine: whatever the URL
        says, bb-tty would have believed. So on a node bb-tty asks this, with
        the token that rode in on the URL, and takes the account, its name
        and whether it is the owner from the answer and never from the URL.

        The token is the proof. It is signed with a key only this container
        holds, names one project and one account, and expires; the proxy
        mints a fresh one for every terminal it relays. What is asked of it
        is what the proxy asked before relaying: the project the terminal is
        for is the token's, the account is still there and may open it
        (_term_refused, _claude_held), and a writable terminal is for an
        account with a shell, since the proxy sends everybody else to the
        read-only twin. A session holding its own token can therefore open
        what its own account could open through the proxy, and nothing else.
        """
        who = self._who() or {}
        if not who.get("session") or not users.uid_of(who):
            return self._json({"error": "a terminal on a node is granted to a session token "
                                        "minted for an account, and this is not one"}, 403)
        me = users.account_of(who)
        if me is who or not me.get("uid"):
            return self._json({"error": "the account this token was minted for is gone"}, 403)
        arg = str(req.get("arg") or "")
        if _ARG_OWNER.match(arg):
            return self._json({"error": "the argument names its account, which is this "
                                        "answer's to say"}, 400)
        project = _arg_project(arg)
        if not project or project != who["session"]:
            return self._json({"error": f"this token is for {who['session']}, and the terminal "
                                        f"asked for is {'for ' + project if project else 'not a project'}"},
                              403)
        rest = "/?arg=" + urllib.parse.quote(arg, safe="")
        refused = self._term_refused(rest, me) or self._claude_held(rest, me)
        if refused:
            return self._json({"error": refused}, 403)
        if not req.get("ro") and users.may(me, "terminal"):
            return self._json({"error": f"{me['name']} has no shell, so this terminal is the "
                                        "read-only one"}, 403)
        # ...and the projects this one reads, for the view bb-session builds
        # (their trees read-only) and the walls bb-tty gives Claude; and the
        # places on its node it is shown, which the view otherwise leaves out.
        return self._json({"uid": me["uid"], "name": me["name"], "project": project,
                           "owner": me.get("role") == "owner",
                           "reads": [r for r in (prefs.get(project) or {}).get("reads") or []
                                     if (WORKSPACE / r).is_dir()],
                           "sees": (prefs.get(project) or {}).get("sees") or [],
                           # Whether it may compute on its node's NVIDIA card
                           # (R102): "on", or who said no, the node or the
                           # project, which bb gpu then says to the session.
                           "gpu": gpu_for(project, _arg_node(arg)),
                           # Whether its Gradle builds on the node's disk (B439).
                           "build_local": (prefs.get(project) or {}).get("build_local", True),
                           # Which node this terminal is on, by id: what a
                           # session there names when it reports its Claude
                           # sign-in, since a project may work on several.
                           "node": _arg_node(arg) or (prefs.get(project) or {}).get("node") or ""})

    def _hook(self, req):
        """What a session's hooks have to say, from a NODE (roadmap #24):
        hooks.py says what each kind means. The account is the token's,
        never the request's: a session token minted for a node-bound
        terminal names its account, and that is who the note is filed under
        and who the feed says asked."""
        me = self._who()
        if not me:
            return self._json({"error": "not signed in"}, 401)
        uid = me.get("uid") if me.get("session") else ""
        project = me.get("session") or ""
        if not uid or not project:
            return self._json({"error": "a hook posts with a session token minted for an "
                                        "account, the one a node-bound terminal carries"}, 403)
        return self._json(*hooks.verb(field(req, "kind"), req, me, uid, project))

    def _bb_relay(self, req):
        """A bb verb from a session on a NODE, run here (roadmap #24). The
        door: a signed-in caller, and the account's `bb` right on the
        project. Which words travel, whose project a token names and what a
        session may push are bbrelay.py's."""
        me = self._who()
        if not me:
            return self._json({"error": "not signed in"}, 401)
        project, no = bbrelay.admit(me, req)
        if no:
            return self._json(*no)
        if self._refused("bb", project):
            return None
        # A session's bb bug add, bb rules add or bb settings set is its own
        # write like one through the notebook's routes, and was told to it
        # on its next prompt as somebody else's (B375): what moved across
        # the verb is marked seen for the session that ran it.
        before = _seen_now(project, me) if me.get("session") else None
        out = bbrelay.run(me, req, project)
        # What a relayed verb changed in the controller's copy reaches the
        # project's synced nodes now, and the session's bb waits for its own
        # copy to reach this revision before it goes on (R163, syncwait.py).
        argv0 = (req.get("argv") or [""])[0] if isinstance(req.get("argv"), list) else ""
        if argv0 in ("git", "version", "changelog") and out[1] == 200 and isinstance(out[0], dict) \
                and _sync_bound(project):
            wssync.changed(project)
            out = (out[0] | {"sync_rev": wssync.rev_of(project)}, out[1])
        if before is not None:
            session_mark_own(project, me.get("uid") or "", me, since=before)
        return self._json(*out)

    def _agent(self):
        """The node agent's door (docs/nodes.md §4): channel.py says what each
        verb means. What stays here is the HTTP: the node's token from the
        Authorization header, a file streamed, a body read, and the
        long-poll's empty answer."""
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        verb = self.path.split("?")[0][len("/api/v1/agent/"):]
        hdr = self.headers.get("Authorization", "")
        bearer = hdr[7:] if hdr.startswith("Bearer ") else ""
        auth = nodes.authenticate(bearer) if bearer else {"error": "no token"}
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        # A hosting-only node (nodes.host_only) is held to what running the
        # containers sent to it needs, before any verb is read: nothing of
        # it comes back otherwise, and asking is audited.
        if auth.get("kind") == "node":
            why = nodes.host_refuses(auth["node"], verb, q.get("what", [""])[0] if verb == "download" else "")
            if why:
                # Once an hour a node and verb: an agent from before the flag
                # asks for its sync every half minute.
                key = (auth["node"], verb)
                if time.monotonic() - _host_refused_at.get(key, -3600) >= 3600:
                    _host_refused_at[key] = time.monotonic()
                    db.audit(f"node:{auth['node']}", "host-refused", verb[:60], {})
                return self._json({"error": why}, 403)
        # The verbs that serve or take a FILE, on any method.
        if verb in ("source", "file", "download"):
            got, status = channel.fetch(verb, auth, q, authed=self._authed)
            if status != 200:
                return self._json(got, status)
            return self._send_file(got)
        if verb in ("artifact", "sync-put", "claude-put", "devimage-put", "devdata-put"):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if verb == "sync-put":
                return self._json(*channel.sync_put(auth, q, self.rfile, length))
            if verb == "claude-put":
                return self._json(*channel.claude_put(auth, q, self.rfile, length))
            if verb == "devimage-put":
                return self._json(*channel.devimage_put(auth, q, self.rfile, length))
            if verb == "devdata-put":
                return self._json(*channel.devdata_put(auth, q, self.rfile, length))
            return self._json(*channel.artifact(auth, q, self.rfile, length))
        if verb in ("sync-file", "sync-tar", "claude-file", "devimage", "devdata"):
            got, status = {"sync-file": channel.sync_file, "sync-tar": channel.sync_tar,
                           "claude-file": channel.claude_file, "devimage": channel.devimage_file,
                           "devdata": channel.devdata_file}[verb](auth, q)
            if status != 200:
                return self._json(got, status)
            return self._send_file(got)
        if self.command != "POST":
            return self._json({"error": "POST"}, 405)
        req = self._read_json()
        if req is None:
            return None
        if auth.get("error"):
            return self._json({"error": auth["error"]}, 401)
        # Where the node is, as seen from here: informational on the row,
        # and the address docker-over-ssh goes to for an agent node (see
        # nodes._addr). A proxy in front says so in the usual header.
        addr = (self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or self.client_address[0])
        if verb == "work":
            got = channel.work(auth, req, addr, alive=lambda: not client_gone(self.connection))
            if got is None:
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            return self._json(*got)
        return self._json(*channel.verb(verb, auth, req, addr))

    def _send_file(self, got):
        """A file the agent fetches, from a path or from bytes, never cached:
        channel.fetch's answer."""
        self.send_response(200)
        self.send_header("Content-Type", got["ctype"])
        self.send_header("Cache-Control", "no-store")
        for k, v in got["headers"].items():
            self.send_header(k, v)
        if "stream" in got:
            # Written as it is made, ended by closing the connection: this
            # server speaks HTTP/1.0, one request a connection (a synced
            # project's first copy, R163).
            self.end_headers()
            got["stream"](self.wfile)
        elif "path" in got:
            size = got["path"].stat().st_size
            self.send_header("Content-Length", str(size))
            self.end_headers()
            # Exactly what was promised: a transcript may grow while it is
            # sent (B613), and bytes past the length would be the next
            # response's to a client that reuses nothing but reads them.
            with open(got["path"], "rb") as f:
                while size > 0:
                    chunk = f.read(min(1 << 20, size))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    size -= len(chunk)
        else:
            self.send_header("Content-Length", str(len(got["body"])))
            self.end_headers()
            self.wfile.write(got["body"])
        return None

    def _signin_node(self, req):
        """(node id, refusal) for a sign-in or a sign-out: a person's, never
        a session's, on a node this account may look at, which for an
        account that does not administer is one its own projects work on."""
        me = self._who() or {}
        if me.get("session"):
            return "", ({"error": "a session does not sign an account in or out"}, 403)
        nid = field(req, "node")
        if not nid:
            return "", ({"error": "which node? A Claude sign-in is made on one node, "
                                  "from its row on the Nodes tab"}, 400)
        nid, why = self._node_asked(nid)
        if why:
            return "", ({"error": why}, 403)
        return nid, None

    def _signin(self, req):
        """Start a sign-in on one node, or stop the one that is running:
        signin.verb. Another account's flow is not this one's to replace or
        stop (the review of 26 Sep)."""
        me = self._who() or {}
        uid = users.uid_of(me)
        if signin.owner() not in ("", uid) and signin.state()["running"]:
            return self._json({"error": "another account is signing in right now: "
                                        "one sign-in at a time, so try again in a minute"}, 409)
        if field(req, "action") == "cancel":
            if me.get("session"):
                return self._json({"error": "a session does not sign an account in or out"}, 403)
            return self._json(*signin.verb("cancel", "", uid))
        nid, no = self._signin_node(req)
        if no:
            return self._json(*no)
        return self._json(*signin.verb("", nid, uid))

    def _login_code(self, req):
        """Hand the code from the browser to the sign-in flow: signin.take_code,
        for the person whose flow it is."""
        me = self._who() or {}
        if me.get("session"):
            return self._json({"error": "a session does not sign an account in or out"}, 403)
        if signin.owner() != users.uid_of(me):
            return self._json({"error": "no sign-in of yours is running"}, 403)
        return self._json(*signin.take_code(field(req, "code")))

    def _signout(self, req):
        """Sign this account out of Claude on one node (signin.sign_out):
        the login is that machine's, so that machine lets go of it."""
        nid, no = self._signin_node(req)
        if no:
            return self._json(*no)
        # Not while a conversation of THIS account's is running there.
        # Signing out pulls the ground from under the sessions it started,
        # and a page that has not polled for fifteen seconds can offer a
        # button the answer has moved past, so the refusal is here as well
        # as on the button. Theirs, and on this node: one person signing out
        # does nothing to somebody else's conversation, or to their own on
        # another machine.
        me = users.uid_of(self._who())
        busy = sorted(x["name"] for x in node_tmux_sessions()
                      if x.get("node_id") == nid and tmux_base(x["name"]).startswith("claude-")
                      and (tmux_owner(x["name"]) or users.uid_of(
                          users.get(users.owner_name() or ""))) == me)
        if busy:
            # Said as projects, not tmux names: "u_3deb3420~claude-hello"
            # named nothing a person recognizes, and every one listed is
            # the asker's own.
            projs = sorted({tmux_base(n)[len("claude-"):] for n in busy})
            return self._json({"error": "end your Claude session"
                               + ("s" if len(projs) > 1 else "") + " on "
                               + ", ".join(projs) + " first (Sessions, or the tab's Close)"}, 409)
        payload, status = signin.sign_out(nid, me)
        if status == 200:
            # The row says so at once; the node's own report, which the job
            # prompts, is what keeps it true.
            claudegrant.report(home_for(me), nid, "", signed_in=False)
        return self._json(payload, status)

    def _roadmap(self, req):
        """Add, send, edit or drop one item on a project's list: roadmap.verb
        says what each action means.

        The project is checked against the real list for the same reason every
        other endpoint here does it: a name that came back off the filesystem
        cannot name something that was never there.
        """
        name = field(req, "project")
        if self._not_project(name):
            return
        # Seeing a project and being able to change it are different
        # questions now (users.may_work): an administrator is shown every
        # project and works on the ones they took on. The reads are named,
        # so an action added later is a write until somebody says otherwise.
        if field(req, "action") not in ("history",) and self._readonly(name):
            return None
        act = field(req, "action")
        # "send" is a write to the roadmap (it marks a step sent) and starts a
        # session's turn, so it goes with the rest.
        if (bad := projects.locked_out(name)):
            return self._json(bad, 409)
        # Closing a batch its session will never close (B198) is an
        # administrator's, like the other decisions about other people's work.
        if act == "batch-close" and self._refused("admin"):
            return
        return self._json(*roadmap.verb(name, act, req, self._who() or {}, live=sessions_anywhere(),
                                        prefix=users.tmux_prefix(self._who())))

    def _phone_payload(self, node="", probe=False):
        """The Phone tab's data as this request reads it: who is asking, the
        nodes they may see (_node_scope) and this browser's own address and
        kind, which phone.tab_view decides whether to offer."""
        return phone.tab_view(users.uid_of(self._who()), admin=users.is_admin(self._who()),
                              project=(self._who() or {}).get("session") or "",
                              node=node, probe=probe, scope=self._node_scope(),
                              ua=self.headers.get("User-Agent", ""),
                              addr=self.client_address[0] if self.client_address else "",
                              who=self._who())

    def _reads(self, project):
        """Whether this session may read `project`: one its project reads
        (prefs.reads), the same answer the notebook's reads get."""
        me = self._who() or {}
        return bool(me.get("session")) and project in (me.get("reads") or []) \
            and not users.may(me, "read", project)

    def _docker_ctl(self, req):
        """Start, stop, restart or read the log of ONE container on a node.

        Any container on that daemon, which is the point: the operator asked
        for a manager rather than a list of what BuilderBot made, and what
        makes that acceptable is the same thing that makes the rest of this
        acceptable, namely that the daemon belongs to a machine whose only job
        is running containers (R68 steps 1 and 2).

        An administrator's, like every other docker write here, and the log
        with them: a container's log is whatever it decided to print, which
        on somebody else's container is not a thing to hand out by role.

        The one exception is a SESSION, on a container that belongs to its
        project (the operator, 24 Sep): containers.session_verb says what it
        may do with one.
        """
        me = self._who() or {}
        sess = me.get("session") or ""
        act, name = field(req, "action"), field(req, "container")
        if sess:
            # The log of a container that belongs to a project this session
            # reads is a read (B551); everything else is its own project's.
            proj = field(req, "project")
            if act == "logs" and proj and proj != sess and self._reads(proj):
                return self._json(*containers.session_verb(proj, me, act, name, req, read_only=True))
            return self._json(*containers.session_verb(sess, me, act, name, req))
        if self._refused("docker-write"):
            return
        nid, why = self._node_asked(field(req, "node"))
        if why:
            return self._json({"error": why}, 400)
        # Which project it belongs to: one of them, or none.
        under = field(req, "owner")
        if act == "owner" and under and under not in {p["name"] for p in project_list(me)}:
            return self._json({"error": f"no project called {under}"}, 400)
        return self._json(*containers.admin_verb(act, name, nid, under))

    def _container(self, req):
        """A container from a compose file written here, with no project:
        containers.tab_verb.

        Its own endpoint rather than an action on _devapp, because _devapp
        starts by insisting the caller names a project and this one has none:
        that is the whole of what it is.

        An administrator's, like every other write here that is configuration
        rather than a run of the code. It was the page alone that knew that
        (mayDocker hides the buttons), and a hidden button is not a refusal:
        writing a compose file and building from it is root-shaped power on
        the node, so the endpoint says no itself.
        """
        if self._refused("docker-write"):
            return
        return self._json(*containers.tab_verb(
            field(req, "action"), field(req, "name"), req,
            seen=lambda: [p["name"] for p in project_list(self._who())]))

    def _logs(self, req):
        """The log policy, and the two things that can be done to the pile:
        logs.verb. An administrator's."""
        if self._refused("admin"):
            return
        return self._json(*logs.verb(field(req, "action"), req))

    def _idle(self, req):
        """The idle rule for Claude sessions (idle.py): minutes, 0 for never.
        Operator-only, like the log policy beside it."""
        if self._refused("admin"):
            return
        r = idle.set_minutes(req.get("minutes"))
        return self._result(r)

    def _paths(self, req):
        """Where the controller keeps one kind of what grows (paths.py), and
        what is there moved across. An administrator's, never a session's:
        it is this machine's disks."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "the controller's storage is the operator's"}, 403)
        if self._refused("admin"):
            return
        name = field(req, "name")
        r = paths.set_path(name, field(req, "path"))
        if r.get("ok"):
            db.audit(self._principal(), "paths", name, {"path": field(req, "path"), "moving": r.get("moving")})
        return self._result(r)

    def _devapp(self, req):
        """The dev-instance controls: the Docker tab's buttons, and `bb devapp`
        from a session. Who may press which is decided below, by the verb, by
        whose the container is and by its project's Run its container."""
        me = self._who() or {}
        sess = me.get("session") or ""
        # Named as the Docker tab lists it, for one that is not the caller's
        # own project's: a container written here, or another project's
        # instance that belongs to this one (bb devapp --container NAME).
        ctr = field(req, "container")
        if ctr:
            row = devapp.row_named(ctr)
            if not row:
                return self._json({"error": f"no container called {ctr} on record here"}, 400)
            req["project"], req["instance"] = row
        name = field(req, "project")
        # A project, OR a container written here, which is not a project and
        # never will be, but carries every one of these controls. Checked
        # against the store rather than waved through: this name reaches a
        # compose call and a data directory either way.
        if name not in {p["name"] for p in project_list(me)} \
                and name not in containers.overview_names():
            return self._json({"error": f"not a project or container: {name}"}, 400)
        act = field(req, "action")
        # WHOSE IT IS, before anything else is asked: an account that is not
        # an administrator reaches what belongs to its projects, and a
        # session what belongs to its own one (the operator, 24 Sep). The
        # same answer a stranger's container gets, whatever the verb, so a
        # session cannot learn by asking what another project runs.
        if not users.is_admin(me):
            want = field(req, "instance") or (devapp.send_name(name, field(req, "compose")) if act == "new"
                                              else devapp.only_instance(name))
            owner = devapp.owner_of(name, want)
            # ...and a session reads what belongs to a project its own reads
            # (B551): the state and the starter env, never a change.
            reads = {owner} if sess and act in ("state", "starter") and owner and self._reads(owner) else set()
            if owner not in ({sess} | reads if sess else {p["name"] for p in project_list(me)}):
                return self._json({"error": containers.not_ours(devapp.pname(name, want), sess)}, 403)
        # Reading is everybody's; changing what is running is not (roadmap
        # #27). Named, not derived from the verb: an action that should be
        # restricted and is not on this list is a decision somebody has to
        # make, which is the same rule MACROS follows.
        #
        #   starter, state: reads, returning the project's .env.example and
        #     the row.
        #   rebuild, abort: a user's own work, on purpose. Somebody given a
        #     project has to be able to build what they committed and look at
        #     it, or the project is read-only in the way that matters. Rebuild
        #     is build-then-down-then-up, so it is also how a stopped instance
        #     comes back, and the page already ghosts it until the code has
        #     actually moved. Abort follows it: whoever may start a build may
        #     stop one, or a mistake is somebody else's problem to clear.
        #
        # Everything else (new, remove, env, route) is configuration rather
        # than a run of the code, and stays an administrator's: except, for a
        # SESSION, what its project's dial hands over below (its env, and
        # creating and removing the project's own container), which the dial
        # decides rather than this gate, since a session never passes this one.
        session = bool(sess)
        dialed = ("env-get", "env-set", "new", "remove") if session else ()
        if act not in ("starter", "state", "rebuild", "abort", "test") + dialed \
                and self._refused("docker-write"):
            return None
        # A compose file edited from the Docker tab is a file in the project's
        # tree: a write to the project as well as to its container.
        if act == "compose-set" and self._readonly(name):
            return None
        # Sending, copying or moving a container, or putting it under another
        # project, names only projects on the asker's own list, for an
        # administrator and the owner as for a user (the operator, 10 Oct):
        # they could add any project to their list first, and this is the
        # seatbelt against a container landing under the wrong one.
        if not session and act in ("new", "relocate", "owner", "move"):
            for target in [name if act in ("new", "relocate") else "",
                           field(req, "owner") if act in ("new", "owner") else "",
                           field(req, "to") if act == "move" else ""]:
                # A project, not a container written here: one of those is
                # nobody's list to be on.
                if target and registry.is_project(target) and not users.may_work(me, target):
                    return self._json({"error": f"{registry.label(target)} is not on your list of projects: "
                                                "add it to your own list on the Users tab first"}, 403)
        if act == "relocate" and session:
            return self._json({"error": "copying or moving a container to another node is a person's: "
                                        "it puts the project's data on another machine"}, 403)
        # A SESSION is a further question, and the answer is a per-project
        # dial with the notebook's own three words. Rebuild runs the project's
        # own Dockerfile and brings the container up on the node's daemon: for
        # a project whose loop is "change it, rebuild it, look at it" that is
        # exactly what you want a session doing; `ask` puts the reason in
        # front of a person first; `deny`, the default, keeps the button the
        # operator's. The read verbs are nobody's secret.
        #
        # It governs rebuild, abort, the env and creating the project's own
        # container, and NOTHING else: remove and route are docker-write
        # above, which a session's principal never has. A test run is not on
        # it: it runs the project's own test command inside a container that
        # is already up, which a session could run on the node anyway
        # (roadmap R48).
        # ...and before the dial, a session may only touch the instance on its
        # OWN node. A session runs on the project's node; an instance pinned
        # to another one is a container on a machine this session is not on,
        # left behind by a node change and still running on purpose. Using or
        # rebuilding it from here would act on somebody else's box through a
        # row that happens to carry this project's name, and a rebuild would
        # bounce a service still being used. The operator keeps both, through
        # the Docker manager, which is where an instance is removed.
        # The exception is one SENT there on purpose (R166): its image is
        # built on the project's own node and shipped, and the project's
        # sessions are the ones meant to rebuild it.
        # A node named by its name (bb devapp new --node NAME) is its id here.
        if act == "new" and req.get("node") and not NODES_OK and not nodes.node(str(req["node"])):
            hit = [n for n in nodes.node_list() if n.get("name") == str(req["node"]) and n.get("state") != "retired"]
            if hit:
                req["node"] = hit[0]["id"]
        if act == "new" and req.get("ship") is True:
            # A session may make one there when its project names the node
            # under Hosts its containers on (prefs.hosts, the operator, 10
            # Oct), under its Run its container dial below; anywhere else it
            # is a person's.
            if session and (name != sess or str(req.get("node") or "") not in (prefs.get(sess).get("hosts") or [])):
                return self._json({"error": "sending a project's container to a node it is not on is a "
                                            "person's, unless the node is under Hosts its containers on in "
                                            "the project's settings: it puts the project's image on another machine"}, 403)
            if not session and self._refused("node", name):
                return None
        if act not in ("starter", "state") and session:
            on = devapp.instance_node(name, field(req, "instance"))
            mine = devapp.project_daemon(sess)
            # A shipped one is the session's while its node is still under the
            # project's Hosts its containers on; taken off, the container stays
            # the project's and the session loses it like any other left behind.
            shipped_there = devapp._read_rec(name, devapp.instance_key(name, field(req, "instance") or devapp.MAIN)).get("ship") \
                and on in (prefs.get(sess).get("hosts") or [])
            if on and mine and on != mine and not shipped_there:
                return self._json({"error": "this dev instance is on another node: it stayed "
                                            "where it was running when this project moved, "
                                            "and a session works on its own node's. The "
                                            "operator uses or removes it from the Docker "
                                            "manager"}, 403)
        if act not in ("starter", "state", "test") and session:
            # The dial is the project's (Claude may: Run its container, in its
            # settings) and covers rebuilding its containers, changing their
            # env and sending the project to Docker, its own container or
            # another beside it: the operator's widenings of 24 and 26 Sep, so
            # a session can bring a container up by request. What a container
            # IS stays out of reach: `new` from a session is the project's own
            # compose file on its own node, never another project's and never
            # a file it wrote, which is `bb container ask` and an
            # administrator's.
            # The dial of the project it belongs to, which is the session's
            # own: the gate above let nothing else through.
            mode = prefs.get(sess)["devbuild"]
            if mode == "deny":
                return self._json({"error": devapp.RUN_DENIED}, 403)
            if act == "new":
                if "owner" in req and field(req, "owner") != name:
                    return self._json({"error": "a session creates its own project's container, "
                                                "belonging to its own project"}, 403)
                req.pop("owner", None)
                # ...on its own node: the node a session names is dropped,
                # except for one it ships to, which the hosts gate above has
                # already held to the project's Hosts its containers on.
                # Dropped whole, a shipped new passed that gate and then
                # landed, unshipped, on the project's own node (B645).
                if req.get("ship") is not True:
                    req["node"] = ""
        if act not in ("starter", "state") and name in {p["name"] for p
                                                        in project_list(me)} \
                and self._readonly(name):
            return None
        # ...and for a container written here, the project it belongs to,
        # for anybody but an administrator: a session of a locked project
        # does not work on its containers either.
        if act not in ("starter", "state") and not users.is_admin(me) \
                and name not in {p["name"] for p in project_list(me)} \
                and self._readonly(devapp.owner_of(name, field(req, "instance") or devapp.MAIN)):
            return None
        # `new` is the one action whose instance does not exist yet, which is
        # what it is for; the project it is made for is checked here, where
        # the account is known, and everything else is the module's: which
        # verb means what is devactions.py's to say (the one-file rule), and
        # this handler holds the gate. `owner` names a project the same way.
        if act == "new":
            under = field(req, "owner")
            if under and self._not_project(under):
                return
        # Moving one between projects crosses two of them: a person's, and
        # only into a project they can see.
        if act == "move":
            if me.get("session"):
                return self._json({"error": "moving a container to another project is a person's, "
                                            "on the Docker tab"}, 403)
            if field(req, "to") not in {p["name"] for p in project_list(me)}:
                return self._json({"error": f"no project called {field(req, 'to')}"}, 400)
        if act == "owner" and field(req, "owner") \
                and field(req, "owner") not in {p["name"] for p in project_list(me)}:
            return self._json({"error": f"no project called {field(req, 'owner')}"}, 400)
        # Which instance of that project. Absent means the one every project
        # has always had, so a caller that predates instances still works and
        # a request that names a strange one is answered rather than obeyed:
        # the name decides a compose project and a data directory, and those
        # are not places to let an arbitrary string reach.
        # A request naming no instance means the project's only one, when
        # it has exactly one: BuilderBot's own is called builderbot-dev, and
        # bb devapp from a session was answering for a `main` that did not
        # exist (15 Sep). With several, `main`; bb takes --instance for that.
        # A NEW one named by nobody takes the name Send would offer: the
        # project's own while it has none, then one beside it.
        inst = field(req, "instance") or (devapp.send_name(name, field(req, "compose")) if act == "new"
                                          else devapp.only_instance(name))
        # A session at `ask` puts the change in front of a person instead;
        # devactions.request says which changes those are.
        return self._json(*devactions.request(
            name, inst, act, req, me=me, principal=self._principal(),
            dial=prefs.get(sess)["devbuild"] if session else "",
            # The command is the project's own, from its settings.
            test_cmd=prefs.get(name)["test"] if act == "test" else ""))

    def _version(self, req):
        """Move a project's version, or change who is allowed to:
        version.verb, behind the gates here.

        A session's bump goes through `bb version bump`, which asks the same
        policy and passes `by="claude"`.
        """
        name = field(req, "project")
        if self._not_project(name):
            return
        act = field(req, "action")
        # B173: this is the panel's, and `by="operator"` is only true of an
        # administrator at it. A session moves its version with bb version
        # bump, under the project's policy, and never here, where it could
        # also have loosened that policy; a plain account may ask a session
        # to bump and no more.
        who = self._who() or {}
        if who.get("session") and act == "release":
            # bb version release (R138): its own project only, under its
            # dial. The tag and the forge's release are made here, with the
            # project's own credentials, which the session never holds.
            if name != who["session"]:
                return self._json({"error": "a session releases its own project and no other"}, 403)
            mode = (prefs.get(name) or {}).get("release") or "ask"
            if mode == "deny":
                return self._json({"error": f"{name}'s settings say Claude does not release it (Claude may: "
                                            "Tag and publish a release); a person cuts it with Release on "
                                            "the Artifacts tab"}, 403)
            comp = field(req, "component") or ""
            plan = version.release_plan(name, comp)
            if plan.get("error"):
                return self._json(plan, 400)
            acct = users.account_of(who) or {}
            if mode == "auto":
                return self._json(*_releaser(name, comp, str(acct.get("name") or ""), self._principal()))
            r = phone.ask_release(field(req, "why"), name, comp, plan, membership.owner_of(name),
                                  membership.owner_name(name) or "the project's owner",
                                  asker_name=str(acct.get("name") or ""), principal=self._principal())
            return self._json(r, 400 if r.get("error") else 200)
        if act == "release-remove":
            # Files off a published release: its own ask, never part of an
            # edit, under the release's dial (the operator, 5 Oct).
            if who.get("session") and name != who["session"]:
                return self._json({"error": "a session changes its own project's release and no other"}, 403)
            if not who.get("session") and self._refused("version", name):
                return None
            comp = field(req, "component") or ""
            tag = field(req, "tag")
            if not tag:
                tag, why = version.current_tag(name, comp)
                if why:
                    return self._json({"error": why}, 400)
            mode = (prefs.get(name) or {}).get("release") or "ask" if who.get("session") else "auto"
            if mode == "deny":
                return self._json({"error": f"{name}'s settings say Claude does not release it (Claude may: "
                                            "Tag and publish a release), which taking a file off its release is "
                                            "part of; a person removes it on the forge"}, 403)
            names = req.get("remove") if isinstance(req.get("remove"), list) else []
            plan = forgerelease.remove_plan(name, tag, names)
            if plan.get("error"):
                return self._json(plan, 400)
            acct = users.account_of(who) or {}
            if mode == "auto":
                return self._json(*_release_remover(name, plan, str(acct.get("name") or ""), self._principal()))
            r = phone.ask_release_remove(field(req, "why"), name, plan, membership.owner_of(name),
                                         membership.owner_name(name) or "the project's owner",
                                         asker_name=str(acct.get("name") or ""), principal=self._principal())
            return self._json(r, 400 if r.get("error") else 200)
        if act == "release-edit":
            # bb version release --edit (R139): the published release's
            # notes and files, under the same dial as the release itself, a
            # session's own project only, every edit its own ask.
            if who.get("session") and name != who["session"]:
                return self._json({"error": "a session edits its own project's release and no other"}, 403)
            if not who.get("session") and self._refused("version", name):
                return None
            comp = field(req, "component") or ""
            tag = field(req, "tag")
            if not tag:
                tag, why = version.current_tag(name, comp)
                if why:
                    return self._json({"error": why}, 400)
            attach = req.get("attach") if isinstance(req.get("attach"), list) else []
            notes = req.get("notes") if isinstance(req.get("notes"), str) else None
            mode = (prefs.get(name) or {}).get("release") or "ask" if who.get("session") else "auto"
            if mode == "deny":
                return self._json({"error": f"{name}'s settings say Claude does not release it (Claude may: "
                                            "Tag and publish a release), which an edit of its release is part of; "
                                            "a person edits it on the forge"}, 403)
            plan = forgerelease.edit_plan(name, tag, notes, attach)
            if plan.get("error"):
                return self._json(plan, 400)
            acct = users.account_of(who) or {}
            if mode == "auto":
                return self._json(*_release_editor(name, plan, str(acct.get("name") or ""), self._principal()))
            r = phone.ask_release_edit(field(req, "why"), name, plan, membership.owner_of(name),
                                       membership.owner_name(name) or "the project's owner",
                                       asker_name=str(acct.get("name") or ""), principal=self._principal())
            return self._json(r, 400 if r.get("error") else 200)
        if who.get("session"):
            return self._json({"error": "a session moves its version with bb version bump, "
                                        "under the project's policy, and releases with bb version release"}, 403)
        if act != "ask" and self._refused("version", name):
            return None
        return self._json(*version.verb(name, act, req, self._who(), self._principal()))

    def _members(self, req):
        """A project's owner, whether it is invite only, its people and its
        invitations, and an invitee's answer (membership.verb). A session
        is refused: who joins a project is a person's decision."""
        me = self._who() or {}
        if me.get("session"):
            return self._json({"error": "who joins a project is a person's decision"}, 403)
        if not me:
            return self._json({"error": "not signed in"}, 401)
        name = field(req, "project")
        # An invitee answers about a project it may not see yet.
        if field(req, "action") not in ("accept", "decline", "withdraw") and self._not_project(name):
            return None
        return self._json(*membership.verb(me, req))

    def _signing(self, req):
        """A project's Android signing keys (signing.verb, R106). A session
        is refused whatever it asks: it signs with bb sign, which never hands
        it the key, and has no reason to learn which keys exist from here.
        Listing is for whoever sees the project (no secret is in it); adding,
        replacing and removing a key are an administrator's."""
        name = field(req, "project")
        who = self._who() or {}
        if who.get("session"):
            # bb sign: its own project's build, under its dial (Claude may:
            # Sign a build). It never receives the key, the list, or a
            # backup; asking to sign is all a session does here.
            act = field(req, "action")
            if act not in ("sign", "keys", "generate", "map", "rotate") or name != who["session"]:
                return self._json({"error": "a session signs with bb sign, which never hands it the key; "
                                            "the keys are a person's to manage"}, 403)
            owner = membership.owner_of(name)
            acct = users.account_of(who) or {}
            if act in ("keys", "generate", "map", "rotate"):
                # Manage signing keys (R106 step 6): which keys there are
                # (names and fingerprints, never a secret), and a new key or
                # a package's key proposed, under its own dial.
                kmode = (prefs.get(name) or {}).get("keys") or "ask"
                if kmode == "deny":
                    return self._json({"error": f"{name}'s settings say Claude does not manage its signing "
                                                "keys (Claude may: Manage signing keys)"}, 403)
                if act == "keys":
                    return self._json(*signing.listing(name))
                # Said before anybody is asked to allow a key that could not
                # be made: no backup password yet.
                if act == "generate" and (no := signing.needs_lock(name)):
                    return self._json(*no)
                args = ({"key": field(req, "key") or "default", "route": field(req, "route")} if act == "generate"
                        else {"from": field(req, "from"), "to": field(req, "to")} if act == "rotate"
                        else {"package": field(req, "package"), "key": field(req, "key")})
                if kmode == "auto":
                    return self._json(*_keymaker(act, name, args, by="claude"))
                r = phone.ask_keys(field(req, "why"), name, act, args, owner,
                                   membership.owner_name(name) or "the project's owner",
                                   asker_name=str(acct.get("name") or ""))
                return self._json(r, 400 if r.get("error") else 200)
            mode = (prefs.get(name) or {}).get("sign") or "ask"
            if mode == "deny":
                return self._json({"error": f"{name}'s settings say Claude does not sign its builds "
                                            "(Claude may: Sign a build); a person signs from the "
                                            "Artifacts tab"}, 403)
            file, route, key = field(req, "file"), field(req, "route"), field(req, "key")
            no = signing.refusal(name, file, route, key)
            if no:
                return self._json(*no)
            if mode == "auto":
                return self._json(*signing.start(self._principal(), name, file, route, key))
            r = phone.ask_sign(field(req, "why"), name, file, route, owner,
                               membership.owner_name(name) or "the project's owner",
                               asker_name=str(acct.get("name") or ""), principal=self._principal(), key=key)
            return self._json(r, 400 if r.get("error") else 200)
        if self._not_project(name):
            return None
        if field(req, "action") == "sign":
            # Signing a build with a key already kept is working on the
            # project, not administering it.
            if self._readonly(name):
                return None
            return self._json(*signing.start(self._principal(), name, field(req, "file"), field(req, "route"),
                                             field(req, "key")))
        if field(req, "action") == "backup-password":
            # The project's owner's alone, BuilderBot's owner included only
            # when it owns the project: the point is that the dashboard's
            # accounts are not enough by themselves.
            if users.uid_of(who) != membership.owner_of(name):
                return self._json({"error": f"only {name}'s owner ({membership.owner_name(name) or 'its owner'}) "
                                            "sets its backup password"}, 403)
            return self._json(*signing.set_backup_password(name, str(req.get("current") or ""),
                                                           str(req.get("new") or ""), by=str(who.get("name") or "")))
        if field(req, "action") != "list" and self._refused("admin"):
            return None
        got, status = signing.verb(req, by=str(who.get("name") or ""))
        # Whether this person may take a backup, so the dialog offers it only
        # where it would be handed over.
        if field(req, "action") == "list" and status == 200:
            got["may_backup"] = users.is_admin(who) and users.may_work(who, name)
            got["may_lock"] = users.uid_of(who) == membership.owner_of(name)
        return self._json(got, status)

    def _get_node_busy(self):
        """GET /api/node-busy: whether one of a project's nodes is quiet
        enough to time anything on (busy.report, R108). For a session, its
        own project's nodes; for a person, any project they see. Another
        project's work there is counted, never named."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        who = self._who() or {}
        if who.get("session") and name != who["session"]:
            return self._json({"error": "a session asks about its own project's nodes"}, 403)
        if self._not_project(name):
            return None
        if NODES_OK:
            return self._json({"error": "the node store did not open"}, 500)
        pr = prefs.get(name) or {}
        mine = [pr.get("node")] + list(pr.get("nodes") or []) if pr.get("node") else []
        want = q.get("node", [""])[0]
        nodes_here = [n for n in (nodes.node(i) for i in dict.fromkeys(mine) if i) if n]
        n = next((x for x in nodes_here if want in (x["id"], x["name"])), None) if want \
            else (nodes_here[0] if nodes_here else None)
        if not n:
            return self._json({"error": f"{want} is not one of {name}'s nodes" if want
                                        else f"{name} has no node"}, 404)
        jobs = nodes.jobs_for(node_id=n["id"], active=True, n=100)
        working = sum(1 for s in node_tmux_sessions()
                      if s.get("node_id") == n["id"] and (s.get("claude") or {}).get("state") == "working")
        return self._json(busy.report(n, jobs, working, project=name))

    def _get_signing_backup(self):
        """GET /api/signing-backup: a project's keystore for an administrator's
        own copy (signing.backup), which marks it backed up. Never a session's.
        A project whose owner set a backup password is refused here and
        downloads through the POST, which carries it in the body."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        return self._signing_backup(q.get("project", [""])[0], q.get("route", [""])[0],
                                    q.get("key", ["default"])[0] or "default", None)

    def _post_signing_backup(self, req):
        """POST /api/signing-backup: the same, with the project's backup
        password in the body, never in a URL that lands in a log."""
        return self._signing_backup(field(req, "project"), field(req, "route"),
                                    field(req, "key") or "default", str(req.get("password") or ""))

    def _signing_backup(self, name, route, key, password):
        if (self._who() or {}).get("session"):
            return self._json({"error": "a session never receives a signing key"}, 403)
        if self._not_project(name) or self._refused("admin"):
            return None
        # ...and one who has the project on their own list (the operator,
        # 1 Oct): an administrator sees every project, and a key is the one
        # thing there that should not leave with somebody who only sees it.
        if not users.may_work(self._who(), name):
            return self._json({"error": f"a signing key's backup goes to an administrator on {name}: "
                                        "add it to your own projects first"}, 403)
        if password is None and signing.backup_locked(name):
            return self._json({"error": f"{name}'s key backups need their password: Download backup in its "
                                        "settings asks for it"}, 403)
        no = signing.backup_refusal(name, password or "")
        if no:
            return self._json(*no)
        got, status = signing.backup(name, route, key)
        if status != 200:
            return self._json(got, status)
        return self._attachment(*got, "application/zip" if got[0].endswith(".zip") else "application/octet-stream")

    def _artifacts(self, req):
        """Push an .xpi from a project's dist/ to the paired phone, install
        an .apk there, or stop a push: phone.artifact_verb, behind the gates
        here."""
        name = field(req, "project")
        if self._not_project(name):
            return
        # Seeing a project and being able to change it are different
        # questions now (users.may_work): an administrator is shown every
        # project and works on the ones they took on. The reads are named,
        # so an action added later is a write until somebody says otherwise.
        if self._readonly(name):
            return None
        who = self._who() or {}
        # A session asks for a phone (bb phone run) and a person answers; it
        # does not push or install by itself, and uid_of answering the
        # session's account made the owner check pass for it (the audit of
        # 26 Sep). A capture it lets go of with bb capture prune, in the tree.
        if who.get("session"):
            return self._json({"error": "a session asks for the phone with bb phone run and lets a "
                                        "capture go with bb capture prune NAME; neither is done from here, "
                                        "and a pin is a person's"}, 403)
        if field(req, "action") == "forget-capture":
            return self._json(*artifacts.forget_capture(name, field(req, "name")))
        # A build named with no version, which no sweep can judge: a person's Remove.
        if field(req, "action") == "forget-unnamed":
            return self._json(*artifacts.forget_unnamed(name, field(req, "path")))
        # A pin keeps an artifact from the dev builds' sweep, a person's.
        if field(req, "action") in ("pin", "unpin"):
            return self._json(*artifacts.pin(name, field(req, "path"), field(req, "action") == "pin",
                                             by=who.get("name") or ""))
        return self._json(*phone.artifact_verb(name, field(req, "action"), req,
                                               uid=users.uid_of(who), me=who.get("name") or "somebody",
                                               by=self._principal()))

    def _phone(self, req):
        """Pair, connect, and push an extension, and the asking: a session's
        ask for adb, root or a container, and a person's answer. phone.verb
        checks every argument against something already known (a discovered
        extension, an attached device, a Firefox that is actually installed)
        rather than taking it as given: this is one of the few places the
        page causes a program to run. Who may use which is here."""
        # NOT one gate for the whole endpoint. `ask` is what a session does
        # (bb phone run --why ...) and `outcome` is it reading the answer;
        # the control on those is that a person sees the reason and decides,
        # one command at a time. Pairing, connecting, disconnecting and
        # deciding are a PERSON's, any account and not only an administrator:
        # a phone is its owner's, and phone.py holds the ownership (only the
        # account that connected one can disconnect it or answer for it,
        # and root on a shared sandbox is an administrator's whoever asks).
        # A session's token may reach none of them.
        if field(req, "action") not in ("ask", "outcome", "use") and (self._who() or {}).get("session"):
            return self._json({"error": "a session asks; a person answers"}, 403)
        # The outcome of a request is the asking session's to read (scoped
        # to its project below) and an administrator's; not any account's
        # by id, since the output of a root command on a shared machine is
        # not a user's to browse.
        if field(req, "action") == "outcome" and not (self._who() or {}).get("session") \
                and not users.is_admin(self._who()):
            return self._json({"error": "an outcome is read by the session that asked, or an administrator"}, 403)
        act, nid = field(req, "action"), field(req, "node")
        return self._json(*phone.verb(act, req, self._who() or {}, fresh=lambda: self._phone_payload(
            node=nid, probe=act in ("connect", "disconnect", "pair"))))

    def _findings_log(self, req):
        """The Analysis view's log. Read-only by nature: the scan runs on the
        host and nothing here can write a finding, so `history` is the only
        action there is: the entries are made by findings.counts noticing the
        report changed."""
        name = field(req, "project")
        if self._not_project(name):
            return
        if field(req, "action") != "history":
            return self._json({"error": "the findings log is read-only"}, 400)
        return self._json({"history": findings.history(
            name, limit=req.get("limit"), since=req.get("since"),
            find=field(req, "find"))})

    def _rules(self, req):
        """The operator's house rules for one project: the whole list, saved
        (rules.verb).

        A SESSION IS REFUSED HERE, by name. `bb rules` having no write verb
        and the file tools being denied on the file cover what a session would
        do in the ordinary course of work; they do not cover a session with a
        shell and its own token, which authenticates as a principal with user
        rights over exactly this project, so without this the endpoint would
        have been the way around the whole arrangement. The only writer is a
        person signed in to this dashboard with the project on their list.
        """
        name = field(req, "project")
        if self._not_project(name):
            return
        if self._refused("rules", name) or self._readonly(name):
            return None
        if (bad := projects.locked_out(name)):
            return self._json(bad, 409)
        return self._json(*rules.verb(name, field(req, "action"), req))

    def _global_rules(self, req):
        """The rules that apply to EVERY project (R63): rules.global_verb.
        An administrator's.

        Per-project rules are the operator's for that project; a global one
        reaches projects the person saving it may not even work on, so this
        asks for admin where /api/rules asks only for the project. A session
        is refused the same way and for the same reason: its own token would
        otherwise be the way around the arrangement.
        """
        if self._refused("admin"):
            return None
        return self._json(*rules.global_verb(field(req, "action"), req))

    def _pending(self, req):
        """Approve or deny what a session has waiting (roadmap #27):
        pending.verb. The operator's, by name: a session's own token is
        refused here the way it is for the rules, because a session approving
        its own additions is the setting not existing."""
        name = field(req, "project")
        if self._not_project(name):
            return
        if self._refused("pending", name) or self._readonly(name):
            return None
        return self._json(*pending.verb(name, field(req, "action"), req))

    def _tests(self, req):
        """The hand-written half of the registry: testreg.verb."""
        name = field(req, "project")
        if self._not_project(name):
            return
        # A run's start and end are not a write to the notebook: a locked
        # project's tests still run, and the record is memory the status
        # poll reads (testreg.running).
        act = field(req, "action")
        if act in ("begin", "end"):
            me = self._who() or {}
            req = dict(req, by=me.get("name") or "")
            return self._json(*testreg.verb(name, act, req))
        if self._readonly(name):
            return None
        if (bad := projects.locked_out(name)):
            return self._json(bad, 409)
        return self._json(*testreg.verb(name, act, req))

    def _presence(self, req):
        """This browser is in a project's notebook, and who else is (roadmap
        #26): presence.heartbeat, for a signed-in account on a project it
        sees."""
        me = self._who()
        if not me:
            return self._json({"error": "not signed in"}, 401)
        name = field(req, "project")
        if name not in {p["name"] for p in project_list(me)}:
            return self._json({"error": f"not a project: {name}"}, 400)
        return self._json(presence.heartbeat(name, me.get("uid") or "",
                                             str(req.get("client") or "")[:64],
                                             field(req, "where"), leave=bool(req.get("leave"))))

    def _bugs(self, req):
        """Report, edit, or close one bug: bugs.verb, behind the gates here."""
        name = field(req, "project")
        if self._not_project(name):
            return
        # Seeing a project and being able to change it are different
        # questions now (users.may_work): an administrator is shown every
        # project and works on the ones they took on. The reads are named,
        # so an action added later is a write until somebody says otherwise.
        if field(req, "action") not in ("history",) and self._readonly(name):
            return None
        if (bad := projects.locked_out(name)):
            return self._json(bad, 409)
        return self._json(*bugs.verb(name, field(req, "action"), req, sessions=sessions_anywhere,
                                     prefix=users.tmux_prefix(self._who())))

    def _memory(self, req):
        """Edit, create or delete one of this project's memories, rewrite
        their index, or read the history: memory.verb, behind the gates
        here."""
        act = field(req, "action")
        proj = field(req, "project")
        # A project this account sees, whatever the action: the history
        # read had no project check at all (the audit of 26 Sep).
        if self._not_project(proj):
            return None
        if (bad := projects.locked_out(proj)):
            return self._json(bad, 409)
        # Seeing a project and being able to change it are different
        # questions now (users.may_work): an administrator is shown every
        # project and works on the ones they took on. The reads are named,
        # so an action added later is a write until somebody says otherwise.
        if act != "history" and self._readonly(proj):
            return None
        # Whose memories: the reader's own home, never the owner's (B67).
        # A session's are the account's that started it.
        return self._json(*memory.verb(proj, act, req, home_for(users.uid_of(self._who()))))

    def _custom(self, req):
        """Save or delete one of the operator's own command lists:
        macros.custom_edit."""
        # They run in terminals, so they are edited by accounts that may have
        # one: a command list a shell-less account could write and an
        # administrator would run is a shell by proxy.
        if self._refused("terminal"):
            return None
        return self._json(*macros.custom_edit(req.get("action"), req))

    def _create(self, req):
        """New project: a fresh local repo, a clone or a link, and what the
        dialog chose besides (projects.create_from_dialog)."""
        # An administrator's, for two reasons that both matter: a project this
        # account made would not be in the list it was given, so it would be
        # created and then invisible; and the clone dialog is one of the two
        # places a git token is stored (roadmap #27).
        if self._refused("create"):
            return None
        me = self._who()
        # On the nodes the account's New projects role names, when it names
        # any (R152, the operator, 7 Oct): a project made elsewhere, or on no
        # node, is refused by name. Its node is then the account's to set at
        # making it, though setting a node later is the Nodes area's.
        nid = field(req, "node")
        limited = roles.nodes_for(me, "newprojects")
        if limited is not None and nid not in limited:
            names = [n["name"] for n in ([] if NODES_OK else nodes.node_list()) if n["id"] in limited] or limited
            return self._json({"error": f"a project you make goes on {', '.join(names)}: pick "
                                        + ("that node" if len(names) == 1 else "one of those nodes")}, 403)
        return self._json(*projects.create_from_dialog(
            req, env=users.git_env(me, projects.sanitize_name(field(req, "name"))),
            account=me["name"] if me and users.uid_of(me) else "",
            may_node=lambda name: (limited is not None and nid in limited)
            or not users.may(self._who(), "node", name)))

    def _profile(self, req=None):
        """The signed-in account's own settings (the Profile tab): read on
        GET, saved on POST, by profiletab.py. Anybody signed in, because this
        is about themselves."""
        me = self._who()
        if not me or not users.uid_of(me):
            return self._json({"error": "not an account"}, 403)
        if req is None:
            return self._json(*profiletab.view(me))
        payload, status, renamed = profiletab.verb(me, field(req, "action"), req)
        return self._json(payload, status, cookie=make_token(renamed) if renamed else None)

    def _get_snapshots(self):
        """GET /api/snapshots?project=NAME: the days kept of the project's
        tree (snapshots.py), newest first, and how many it keeps. An
        administrator's, like a restore."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "a project's snapshots are the operator's"}, 403)
        if self._refused("admin"):
            return None
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return None
        return self._json({"project": name, "keep": prefs.get(name)["snapshot_days"],
                           "days": snapshots.days(name)})

    def _snapshots(self, req):
        """POST /api/snapshots: take one now, or restore the whole tree as of a
        day or one file of it (snapshots.restore, which snapshots the tree
        first so it can be undone). Never a session's: a session is what a
        restore may be undoing."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "a project's snapshots are the operator's"}, 403)
        if self._refused("admin"):
            return None
        name = field(req, "project")
        if self._not_project(name):
            return None
        act = field(req, "action")
        if act == "take":
            return self._result(snapshots.take(name))
        if act == "restore":
            return self._result(snapshots.restore(name, field(req, "day"), field(req, "path"),
                                                  who=self._principal()))
        return self._json({"error": "take or restore"}, 400)

    def _get_transcripts(self):
        """GET /api/transcripts?project=NAME: the signed-in account's own
        conversations with Claude on that project, newest first
        (transcripts.mine). Anybody signed in, their own only, a session
        included: on its own project and on one its project reads, it
        lists the account's conversations there for `bb transcripts`."""
        me = self._who()
        uid = users.uid_of(me) if me else ""
        if not me or not uid:
            return self._json({"error": "not an account"}, 403)
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json({"project": name, "rows": transcripts.mine(uid, [name])})

    def _get_transcript(self):
        """GET /api/transcript?project=NAME&id=SESSION: one of the signed-in
        account's own conversations with Claude on that project as a text
        file, every command and answer in it (transcripts.render); as JSON
        with as=json, which is what `bb transcripts show` reads. Anybody
        signed in, their own only, a session included on its own project
        and on one its project reads: the file is looked for under the
        account's own transcripts directory and nowhere else, so another
        account's id is simply not found."""
        me = self._who()
        uid = users.uid_of(me) if me else ""
        if not me or not uid:
            return self._json({"error": "not an account"}, 403)
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        if q.get("as", [""])[0] == "raw":
            # The file as Claude Code wrote it, for bb transcripts fetch: a
            # synced node resuming a conversation it does not have (B613).
            # Nothing when it is no longer than the copy the node has.
            f = transcripts.raw(uid, name, q.get("id", [""])[0])
            if f is None:
                return self._json({"error": "no such conversation of yours"}, 404)
            st = f.stat()
            try:
                have = int(q.get("have", ["-1"])[0])
            except ValueError:
                have = -1
            if st.st_size <= have:
                return self._json({"size": st.st_size}, 200)
            return self._send_file({"path": f, "ctype": "application/octet-stream",
                                    "headers": {"X-Mtime-Ms": str(st.st_mtime_ns // 1_000_000)}})
        text, fname = transcripts.render(uid, name, q.get("id", [""])[0],
                                         transcripts.zone(q.get("tz", [""])[0]))
        if text is None:
            return self._json({"error": fname}, 404)
        if q.get("as", [""])[0] == "json":
            return self._json({"name": fname, "text": text})
        return self._attachment(fname, text.encode("utf-8"), "text/plain; charset=utf-8")

    def _git_act(self, req):
        """The Git view's actions (roadmap R36 step 2): fixed git commands on
        the project's tree on the controller, under the acting account's
        author and the project's own credentials (gitview.verb). An
        account's, never a session's (a session has bb git), on a project it
        may see and has taken on, and not while the project is locked.
        Switching the tree's branch is refused while the owner's Claude
        session runs in the project directory, because that session is
        standing in it (gitview.in_use)."""
        me = self._who()
        if not me or not users.uid_of(me) or me.get("session"):
            return self._json({"error": "an account's, not a session's: a session uses bb git"}, 403)
        name = field(req, "project")
        if name not in {p["name"] for p in project_list(me)}:
            return self._json({"error": "not a project"}, 400)
        if self._readonly(name):
            return None
        if name in set(projects.load_locks()):
            return self._json({"error": "locked: the padlock on its row unlocks it"}, 403)
        action = field(req, "action")
        # A branch is its session's (git.py not_yours): another account's is
        # an administrator's to merge, asked each time and never while that
        # session is working, and nobody else's. Before the check below,
        # which is about the tree a session stands in, not the branch.
        mine_ = gitview.not_yours(WORKSPACE / name, action, req.get("args") or {},
                                  users.uid_of(me), field(req, "kind"), admin=users.is_admin(me))
        if mine_.get("error"):
            return self._json(mine_, 403)
        if mine_.get("confirm"):
            return self._json({"error": mine_["confirm"].split("\n\n")[-1], "confirm": mine_["confirm"]}, 409)
        if (busy := gitview.in_use(name, action, req.get("args") or {}, users.uid_of(me))):
            return self._json({"error": busy}, 409)
        return self._result(gitview.verb(name, action, req, me, prefix=users.tmux_prefix(me),
                                         principal=self._principal()))

    def _upload_archive(self):
        """Spool an archive for the create dialog; {id, name, size, kind}.
        The same gate as create, because it is the first half of one, and
        an upload that stops short of a project would otherwise be a way
        for a user account to fill the controller's disk."""
        if self._refused("create"):
            return None
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json({"error": "bad request"}, 400)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        r = projects.spool_archive(self.rfile, n, (q.get("name") or [""])[0])
        return self._result(r)

    def _link(self, req):
        """Link an existing local repo to an empty repo on a host. projects.py.

        The create gate, because this is the create dialog's third mode and
        one of the places a git token is written, the same reason that gate
        covers the other two. It went ungated from the day it was added: the
        dialog is only drawn for an administrator, so nothing offered it, and
        nothing refused a request that arrived anyway.
        """
        if self._refused("create"):
            return None
        body, code = projects.link(req)
        # A project linked is a project whose CI is worth a first look now,
        # not at the next round (R117).
        if code == 200:
            ciwatch.look_soon(field(req, "name").strip())
        return self._json(body, code)

    def _unlink(self, req):
        """Take the remote off a project, with the credential and the push
        grant that came with it. See projects.unlink: local, instant, and it
        touches no commit."""
        if self._refused("create"):
            return None
        body, code = projects.unlink(req)
        return self._json(body, code)

    def _project_job(self, req):
        """Stop the running project job, or clear the last one's outcome.

        The create gate, as for starting one (B171): a clone or a link is the
        create dialog's, and without it any account could stop an
        administrator's clone halfway or clear a failure before they read it.
        """
        if self._refused("create"):
            return None
        return self._json(*projects.job_verb(req.get("action", "")))

    def _users(self, req):
        """The Users tab's verbs. Thin, like _nodes: users.py owns the rules
        (that the owner cannot be deleted or demoted, that there is only ever
        one, what a password has to be), and this is the door.

        The owner protections live there rather than here on purpose. A rule
        enforced at the door holds for the door; a rule enforced in the store
        holds for `bb users` too, and that is the one an operator reaches for
        when they are locked out.
        """
        act = field(req, "action")
        # Ahead of the admin gate, because this one is nobody else's business:
        # an account setting its OWN appearance. Everything below acts on
        # another account and is an administrator's.
        if act == "prefs":
            me = self._who()
            if not me or not users.uid_of(me):
                return self._json({"error": "not an account"}, 403)
            return self._json(*users.own_prefs(me["name"], req.get("prefs")))
        if self._refused("admin"):
            return None
        me = self._who() or {}
        return self._result(users.verb(act, req, lambda: {p["name"] for p in project_list(me)},
                                       may_change=lambda p: membership.member_refusal(
                                           me, p, joining=field(req, "name") == me.get("name"))))

    def _roles(self, req):
        """POST /api/roles: assign (an account's Everywhere roles and its
        roles on each project, as far as the asker may, R152 and R155), set
        (make or change a role: its scope, its areas and note) or remove
        one; owner and admin are built in and refuse both. Roles themselves
        are an administrator's."""
        act = field(req, "action")
        if act == "assign":
            return self._json(*users.assign(self._who(), field(req, "name"),
                                             req.get("roles") if isinstance(req.get("roles"), list) else None,
                                             req.get("project_roles") if isinstance(req.get("project_roles"), dict) else None))
        if self._refused("admin"):
            return None
        if act == "set":
            # A role held by somebody keeps its kind: an Everywhere role is
            # given to the account and a project role on a project, so a
            # change of kind would leave every holder holding it in the
            # wrong place and silently without it (R155).
            was = roles.get(field(req, "name"))
            want = field(req, "scope") or "projects"
            if was and not was.get("builtin") and "perms" in req and was.get("scope") != want:
                held = sorted(u["name"] for u in users.all_users()
                              if field(req, "name") in (users.get(u["name"]) or {}).get("roles", [])
                              or any(field(req, "name") in rs for rs in
                                     ((users.get(u["name"]) or {}).get("project_roles") or {}).values()))
                if held:
                    return self._json({"error": f"{', '.join(held)} {'holds' if len(held) == 1 else 'hold'} "
                                                f"{field(req, 'name')}: take it off first, or make a new role "
                                                "of the other kind"}, 400)
            if "perms" in req:
                return self._result(roles.set_role(field(req, "name"), field(req, "scope") or "projects",
                                                   req.get("perms") if isinstance(req.get("perms"), dict) else {},
                                                   field(req, "note"),
                                                   nodes=req.get("nodes") if isinstance(req.get("nodes"), list) else []))
            return self._result(roles.set_role(field(req, "name"), grants=req.get("grants"), note=field(req, "note")))
        if act == "remove":
            return self._result(roles.remove(field(req, "name")))
        return self._json({"error": "unknown action"}, 400)

    def _toolchains(self, req):
        """Queue installs or removals of the toolchains the Tools card
        offers: an administrator's, and toolchains.verb says what each
        action does with which names."""
        # By grant, on the node named (R137 step 3): an administrator's
        # everywhere, a role of your own where it says.
        if (why := users.may_node(self._who(), "toolchains-write", field(req, "node"))):
            return self._json({"error": why}, 403)
        return self._json(*toolchains.verb(req.get("action"), req, self._principal()))

    def _emulator(self, req):
        """Add system images to a node, or remove one: a job there, against
        its toolchain store. An id must be one the tab was drawn from (add)
        or one the node reported (remove): what reaches a command line is a
        string this server handed out."""
        if self._refused("admin"):
            return
        if NODES_OK:
            return self._json({"error": "the node store did not open"}, 500)
        action, nid = req.get("action"), field(req, "node")
        iid = req.get("images") if isinstance(req.get("images"), list) else field(req, "image")
        if action not in ("add", "remove"):
            return self._json({"error": "an image is added or removed"}, 400)
        return self._result(emulator.node_job(self._principal(), nid, action, iid))

    def _changelog(self, req):
        """Write back the Unreleased section a person rearranged:
        changelog.editor_verb.

        A session does not get this. The CLI verbs it has (add, edit, merge,
        split, rm) each say what they are doing to one entry; handing it the
        whole section would make "the changelog is the operator's arrangement"
        a convention rather than a rule. The refusal names the verbs.
        """
        if (self._who() or {}).get("session"):
            return self._json({"error": "the changelog's arrangement is the "
                                        "operator's: a session writes entries with "
                                        "`bb changelog add`, and corrects one with "
                                        "`edit`, `merge`, `split` or `rm`"}, 403)
        name = req.get("project", "")
        if self._not_project(name):
            return
        if (bad := projects.locked_out(name)):
            return self._json(bad, 409)
        return self._json(*changelog.editor_verb(name, req))

    def _nodelog(self, req):
        """A machine's own log, for a session that has been granted it.

        Which node is ASKING is not taken from the request and never from the
        session's environment: a node session's BB_NODE is a variable it can
        set. It is the node of the session's own project, which the token
        proves, by the same derivation the phone's ask uses, for the same
        reason.
        """
        if NODES_OK:
            return self._json({"error": "the node store did not open: " + NODES_OK}, 500)
        who = self._who() or {}
        proj = who.get("session") or field(req, "project")
        if proj and not who.get("session") and not users.may_see(who, proj):
            return self._json({"error": "not a project"}, 400)
        asking = prefs.get(proj)["node"] if proj else ""
        # The debug grant's, named only (the operator, 6 Oct): the session's
        # account, or the person asking, must hold it as well as the project
        # its grant for the node.
        if who.get("session"):
            me = users.account_of(who)
            if me is who or users.may(me, "debug"):
                return self._json({"error": "a machine's logs are for an account with the debug "
                                            "grant, and this session's account has not got it: "
                                            "the Roles tab"}, 403)
        elif self._refused("debug"):
            return None
        return self._result(nodes.log_read_named(self._principal(), asking, field(req, "node"),
                                                 field(req, "stream"), req.get("lines"),
                                                 bool(settings.get("debug_mode")),
                                                 grants=prefs.get(proj)["log_from"] if proj else [],
                                                 project=proj), 403)

    def _diag(self, req):
        """The controller's diagnostics (diag.py). An administrator's, and a
        session's only when the debug switch is on, the session's node is
        ticked for it on Debug settings, and the session's account is an
        administrator: a node is shared, so the node's tick alone would hand
        it to every tester whose session runs there. POST, so each read is in
        the audit trail."""
        if self._diag_refused():
            return None
        want = req.get("sections") if isinstance(req.get("sections"), list) else None
        return self._json(diag.report([str(x) for x in want] if want else None))

    def _diag_why(self):
        """Why this caller may not read the controller's diagnostics, or "":
        see _diag. Asked, never written: _diag_refused writes it."""
        who = self._who() or {}
        if who.get("session"):
            if not settings.get("debug_mode"):
                return "debug mode is off, so the controller's diagnostics are not offered to any session"
            me = users.account_of(who)
            if me is who or users.may(me, "debug"):
                return ("the controller's diagnostics are for an account with the debug grant, "
                        "and this session's account has not got it: the Roles tab")
            if not prefs.get(who["session"])["diag"]:
                return (f"{who['session']} has not been granted the controller's "
                        "diagnostics: Debug in its settings")
            return ""
        return users.may(who, "debug")

    def _diag_refused(self):
        """True, with the refusal written, unless this caller may read the
        controller's diagnostics: see _diag. The reports sessions make about
        BuilderBot are read and acted on behind the same gate."""
        who = self._who() or {}
        if who.get("session"):
            why = self._diag_why()
            if why:
                self._json({"error": why}, 403)
                return True
            return False
        return self._refused("debug")

    def _files(self, req):
        """A project's files for a person's own editor (files.py, R159): the
        account this request proved, a project it sees, and the file access
        its settings give it through the editor's door, asked on this request
        (ftp.access_for), so the extension can do nothing the account cannot.
        A session is refused: it has the tree, and it is never a person."""
        me = self._who() or {}
        if me.get("session"):
            return self._json({"error": "a session has its project's tree already: this is a "
                                        "person's editor's"}, 403)
        if field(req, "action") == "projects":
            # The ones this account may open, each with its access: asked
            # project by project through the same gate as every call after.
            mine = []
            for p in project_list(me):
                a, _ = ftp.access_for(me, p["name"], "editor")
                if a:
                    mine.append({"name": p["name"], "access": a})
            return self._json({"api": files.API, "projects": mine})
        project = field(req, "project")
        if self._not_project(project):
            return None
        access, why = ftp.access_for(me, project, "editor")
        if not access:
            return self._json({"error": why}, 403)
        return self._json(*files.verb(field(req, "action"), project, req, access,
                                      by=self._principal()))

    def _reports(self, req):
        """Problems with BuilderBot itself, reported by any project's session
        (reports.py, bb report). Anybody signed in adds one for a project they
        may see, and a session only for its own. Reading them, and clearing
        them all (Controller settings), is the diagnostics' own gate, since
        that is where they are read (bb diag reports)."""
        me = self._who() or {}
        sess = me.get("session") or ""
        act = field(req, "action")
        name = str((users.account_of(me) or {}).get("name") or "")
        if act == "add":
            # Only the server attaches a conversation, never the caller.
            req.pop("_conversation", None)
            proj = sess or field(req, "project")
            # A person's report about no project in particular (the header's
            # Report a bug, the operator, 2 Oct): heard from any account, with
            # no project to check.
            if not sess and not proj:
                return self._json(*reports.own_verb(act, "", req, by=f"{name} (from the dashboard)"))
            if not sess and self._not_project(proj):
                return None
            # A person reports from a project they work on (the operator,
            # 2 Oct): an administrator shown every project but not on this
            # one cannot start a session here, so has nothing of its to report.
            if not sess and not users.may_work(me, proj):
                return self._json({"error": f"you are not on {proj}, so a bug from there is not yours to "
                                            "report: ask to be added, or report from a project you work on"}, 403)
            # The dial is Claude's (Claude may: Report BuilderBot bugs): a
            # person reporting from a project's row is always heard.
            if sess and prefs.get(proj)["report"] == "deny":
                return self._json({"error": f"reporting BuilderBot bugs is off for {proj}: its "
                                            "settings, Claude may: Report BuilderBot bugs. A "
                                            "problem goes into this project's tracker"}, 403)
            # The person's latest conversation on the project, when they
            # ticked Include it (the operator, 2 Oct): theirs only, found and
            # rendered here, never named by the page.
            if not sess and req.get("include_conversation"):
                uid = users.uid_of(me)
                rows = transcripts.mine(uid, [proj])
                if rows:
                    text, _ = transcripts.render(uid, proj, rows[0]["id"])
                    if text:
                        req["_conversation"] = {"id": rows[0]["id"], "text": text}
            # A person's report says it came from the dashboard, so the
            # diagnostics tell it from a session's `bb report`.
            return self._json(*reports.own_verb(act, proj, req, by=name if sess else f"{name} (from the dashboard)"))
        # Clearing is a person's, from Controller settings, whatever a
        # session may otherwise read here.
        if act == "clear" and sess:
            return self._json({"error": "clearing the reports is a person's, from "
                                        "Controller settings"}, 403)
        if self._diag_refused():
            return None
        return self._json(*reports.diag_verb(act, req, by=name, principal=self._principal()))

    def _doctor(self, req):
        """Re-run bb doctor now and answer with the fresh verdict.

        Synchronous on purpose: the caller pressed a button asking for an
        answer, and the threading server keeps everything else responsive
        while this one connection waits the half-minute a bad network takes.
        """
        if self._refused("admin"):
            return None
        if not doctor.refresh():
            return self._json({"error": "doctor is already running"}, 409)
        return self._json(doctor.payload())

    def _cards(self, req):
        """Store the sidebar card arrangement: layout.save_card_order."""
        return self._json(*layout.save_card_order(req))

    def _pin(self, req):
        """Pin or unpin a command: macros.pin."""
        # One set for everybody, so an administrator's: the project pins
        # beside it are each person's own since 27 Sep, this is not.
        if self._refused("command-pin"):
            return None
        return self._json(*macros.pin(req.get("name", ""), bool(req.get("pinned"))))

    def _get_storage(self):
        """The Storage tab (storage.view, R169): every node this account
        holds the Storage area on, what its disks hold, by project where
        the account sees the project and as one line otherwise. Never a
        session's: a session reads its node with bb node busy."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "a node's disks are a person's to read here"}, 403)
        if NODES_OK:
            return self._json({"error": "the node store did not open: " + NODES_OK}, 500)
        return self._json(*storage.view(nodes.node_list(), who, is_admin=users.is_admin,
                                        nodes_for=roles.nodes_for, may_see=users.may_see,
                                        level_of=roles.level_of))

    def _storage(self, req):
        """Measure now on the Storage tab: a node's disks walked at once
        (nodes.node_storage_measure). Write on Storage for that node."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "a node's disks are a person's to read here"}, 403)
        nid = field(req, "node")
        if not nid or not nodes.node(nid):
            return self._json({"error": "which node?"}, 400)
        if not users.is_admin(who) and roles.level_of(who, "storage", node=nid) != "write":
            return self._json({"error": "measuring a node's disks again is Write on Storage"}, 403)
        return self._result(nodes.node_storage_measure(self._principal(), nid))

    def _get_nginx(self):
        """The nginx tab (nginxproxy.view): every node's nginx, for an
        account that may read the Nodes tab; never a session's."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "a node's proxy is a person's"}, 403)
        if not users.is_admin(who) and not roles.level_of(who, "nodes"):
            return self._json({"error": "the nginx tab is the Nodes tab's area: ask for Read on Nodes"}, 403)
        return self._json(nginxproxy.view(devapp, devactions.state))

    def _nginx(self, req):
        """Deploy, save, certificate, remove, check and update on one node's
        nginx (nginxproxy.py): writing a compose file and building it on a
        node, so docker-write like a written container, and never a
        session's. Check reads the registry now; update pins the newest
        line on the node and rebuilds (R192)."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "a node's proxy is a person's"}, 403)
        if self._refused("docker-write"):
            return
        act, nid = field(req, "action"), field(req, "node")
        if not nid or not nodes.node(nid):
            return self._json({"error": "which node?"}, 400)
        if act == "deploy":
            r = nginxproxy.deploy(nid, containers, devactions, devapp)
        elif act == "save":
            r = nginxproxy.save_routes(nid, req.get("routes"))
            # The certificate pasted is the node's default, or one
            # hostname's own when cert_for names it (R175).
            saved = {}
            # A pair pasted is kept under the key its names say, or the one
            # cert_for names (R188); drop_cert names the key to take off.
            if not r.get("error") and isinstance(req.get("cert"), str) and req.get("cert").strip():
                r = nginxproxy.set_cert(nid, req.get("cert"), req.get("key"), field(req, "cert_for"))
                if not r.get("error"):
                    saved = {"host": r.get("host", "")}
            drop = req.get("drop_cert")
            if not r.get("error") and drop:
                r = nginxproxy.drop_cert(nid, drop if isinstance(drop, str) else field(req, "cert_for"))
            if not r.get("error"):
                r = nginxproxy.apply(nid, containers, devactions, devapp) | saved
        elif act == "remove":
            r = nginxproxy.remove(nid, devactions, devapp)
        elif act == "check":
            lt = nginxproxy.check_image()
            r = {"error": lt["error"]} if lt.get("error") else {"ok": True, "latest": lt}
        elif act == "update":
            r = nginxproxy.update(nid, containers, devactions, devapp)
        else:
            return self._json({"error": f"unknown action: {act}"}, 400)
        return self._result(r)

    def _images(self, req):
        """Check for updates on the Docker tab (imagecheck.py, R195): every
        container's registry images on one node, or all, asked now. A
        person's, under docker-write, since what it leads to is an Update."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "checking for image updates is a person's"}, 403)
        if self._refused("docker-write"):
            return
        if field(req, "action") != "check":
            return self._json({"error": "unknown action"}, 400)
        nid = field(req, "node")
        if nid and not nodes.node(nid):
            return self._json({"error": "which node?"}, 400)
        return self._result(imagecheck.check(nid or None))

    def _bell(self, req):
        """Put a bell note away for this account, or bring every one back
        (bellseen.py). The account's own, so no grant; a session has no bell."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "a session has no bell"}, 403)
        uid = users.uid_of(who)
        if field(req, "action") == "restore":
            return self._json(*bellseen.restore(uid))
        return self._json(*bellseen.dismiss(uid, req.get("keys")))

    def _layout(self, req):
        """Store this account's open tabs: layout.save_tabs."""
        return self._json(*layout.save_tabs(users.uid_of(self._who()), req))

    def _lock(self, req):
        """Lock or unlock a project: keep it, stop Claude running in it
        (projects.lock_verb).

        What it does NOT claim: a session in ANOTHER project still reaches this
        directory through Bash. The file tools are denied on every sibling
        already, and that is the whole of the guarantee here too: locking adds
        "no session of its own", not a sandbox, and says no more than that.
        """
        name, on = req.get("name", ""), bool(req.get("locked"))
        # A project this account was given, and the right (B174): a lock ends
        # whoever's Claude session is running there, so it is not a tester's
        # and not a session's.
        if self._not_project(name) or self._refused("lock", name):
            return None
        body, code = projects.lock_verb(name, on)
        # Every Claude session on the project, whoever's and wherever it
        # runs: lock_verb ends the owner's here, from before sessions moved
        # onto nodes (R47), and a lock that left another account's session
        # running on a node was a lock that had not taken (the operator,
        # 29 Sep). Named in the answer, so the page can say what went.
        if on and code == 200:
            want = claude_session(name)
            ended = []
            for s in [x for x in tmux_sessions() if tmux_base(x["name"]) == want] \
                    + [x for x in node_tmux_sessions() if tmux_base(x["name"]) == want]:
                r = end_session(s["name"], str(s.get("node_id") or ""))
                if not r.get("error") and not r.get("gone") and s["name"] not in ended:
                    ended.append(s["name"])
            body = dict(body) | {"ended": ended}
        return self._json(body, code)

    def _trash(self, req):
        """Move a project out of the workspace: projects.trash, once
        project_busy says nothing holds it (the same guards as renaming)."""
        name = req.get("name", "")
        if self._refused("trash", name):
            return
        if (busy := project_busy(name, "trash")):
            return self._json({"error": busy}, 409)
        return self._json(*projects.trash(req))

    def _trash_list(self):
        return self._json(projects.trash_list())

    def _trash_restore(self, req):
        if self._refused("trash"):
            return
        body, code = projects.trash_restore(req)
        return self._json(body, code)

    def _trash_purge(self, req):
        """Delete a trashed project for good. The guards are in projects.py
        (the path is resolved against the bin and the name has to be typed
        back), and this is only the route to them."""
        if self._refused("trash"):
            return
        return self._json(*projects.trash_purge(req))

    def _rename(self, req):
        """Rename a project: projects.rename, once project_busy says nothing
        holds it."""
        name = req.get("name", "")
        # Whether it is a project first, then whether this account may: a
        # name that is nothing answered "not taken on" to the owner once
        # their list was explicit (R135), where it is simply not a project.
        if self._not_project(name):
            return
        if self._refused("rename", name):
            return
        # Nothing on disk moves (R154): the name shown is the registry's, so
        # a session, a terminal or a container holding the project is not
        # in the way of it.
        return self._json(*projects.rename(req))

    def _project_auth(self, req):
        """What credential this project's remote uses, and what else it
        could: projects.auth_answer."""
        name = req.get("name", "")
        # The rename dialog's question, about a project this account sees
        # (B175): it says how the project's remote authenticates.
        if self._not_project(name) or self._refused("rename", name):
            return None
        # Test (the operator, 7 Oct): a read and a dry-run push with what it
        # authenticates with, or with a token typed and not saved yet.
        if req.get("action") == "test":
            return self._json(*projects.auth_test(name, str(req.get("token") or "")))
        # Its own deploy key, made or pasted beside the token (the operator,
        # 12 Oct): the private half goes to the root-only helper and no
        # further.
        if str(req.get("action") or "").startswith("key-"):
            return self._json(*projects.deploy_key(name, str(req["action"]), str(req.get("key") or "")))
        return self._json(*projects.auth_answer(name))

    def _project_ftp(self, req):
        """A project's file access over FTP (ftp.py, R151): what it is, for
        whoever sees the project, and a change, for an account with the ftp
        grant (named only: the owner, until a role names it)."""
        name = field(req, "project")
        if self._not_project(name):
            return None
        me = self._who() or {}
        may_set = not users.may(me, "ftp", name)
        if req.get("action") == "set":
            if self._refused("ftp", name):
                return None
            return self._json(*ftp.save(name, req, me.get("name") or "?"))
        # Who has access, and the port, are the setter's to know: anybody
        # else learns only whether it is on.
        v = ftp.view(name, may_set)
        if not may_set:
            v = {"on": v["on"], "may_set": False, "status": v["status"], "node": v["node"], "port": v["port"]}
        return self._json(v)

    def _project_pin(self, req):
        """Pin or unpin a project: whether the sidebar card shows it
        (projects.pin). No session is touched and nothing is blocked: this is
        the one control of the three that is purely about the view."""
        # A person's own set (the operator, 27 Sep): any signed-in account
        # may pin for itself; a session has no sidebar and pins for nobody.
        me = self._who() or {}
        if me.get("session"):
            return self._json({"error": "a session has no sidebar: the pins are a person's own"}, 403)
        return self._json(*projects.pin(users.uid_of(me), req.get("name", ""), bool(req.get("pinned")),
                                        users.starts_unpinned(me)))

    def _session(self, req):
        """Kill a session. Closing a tab that owns a Claude conversation should
        end it, or detached sessions accumulate invisibly behind a tidy UI."""
        session = req.get("session", "")
        if req.get("action") != "kill":
            return self._json({"error": "unknown action"}, 400)
        if self._not_theirs(session):
            return None
        # Wherever it runs, with already gone as ended (end_session). A name
        # that is not a live session never becomes a `-t` argument: nothing
        # runs for it. By node id when the row said which, and by name alone
        # for a caller that only knows the name (a tab closing).
        return self._result(end_session(session, str(req.get("node") or "")))

    def _get_reset(self):
        """GET /api/reset: how a Reset that un-enrolls its nodes first is
        getting on: each node, done or why not, and the error that stopped
        it. An administrator's."""
        if self._refused("admin"):
            return None
        return self._json({k: v for k, v in _reset_job.items() if k != "started"})

    def _get_project_sessions(self):
        """GET /api/project-sessions?project=NAME: every account's sessions on
        the project, for its settings dialog. An administrator's."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._refused("admin") or self._not_project(name):
            return None
        return self._json({"sessions": projsessions.of(name)})

    def _project_sessions(self, req):
        """POST /api/project-sessions {project, action: "end", session, node}:
        an administrator ending one of them (projsessions.py)."""
        name = field(req, "project")
        if self._refused("admin") or self._not_project(name):
            return None
        if field(req, "action") != "end":
            return self._json({"error": "unknown action"}, 400)
        return self._result(projsessions.end(name, field(req, "session"), field(req, "node")))

    def _not_theirs(self, session):
        """True, with the 403 written, when this account may not act on that
        session: end it, press a key in it or type a macro into it (B172).

        A session is its owner's. Its name says whose (u_<uid>~...), and the
        owner's own on this container keep bare names, so a bare name is the
        owner's. Nobody acts on anybody else's, administrators included: a
        key in another person's Claude session is an answer to a question
        it asked them. A session's token is held to its own project as well,
        the way everything else it does is. The one exception is ending one,
        an administrator's, from a project's settings (projsessions.py, the
        operator's call of 24 Sep); keys and typing stay the account's.
        """
        who = self._who() or {}
        mine = users.uid_of(who)
        owner = tmux_owner(session) or users.uid_of(users.get(users.owner_name() or ""))
        ok = bool(mine) and owner == mine
        if ok and who.get("session"):
            base = tmux_base(session)
            stem = base.split("-", 1)[1] if "-" in base else ""
            proj = tmux_name(who["session"])
            ok = stem == proj or stem.startswith(proj + "-")
        if not ok:
            self._json({"error": "that session is not yours"}, 403)
        return not ok

    def _session_on_node(self, session, node=""):
        """The node session row this page-name means, or None. For the
        three key paths, which type into a node's session through its
        agent exactly as they type into this container's tmux."""
        if session in {s["name"] for s in tmux_sessions()} and not node:
            return None
        return next((s for s in node_tmux_sessions() if s["name"] == session
                     and (not node or s["node_id"] == node)), None)

    def _keys(self, req):
        """Press one key from the tables in a session of the caller's:
        macros.press, here or on its node."""
        session, key = req.get("session", ""), req.get("key", "")
        if self._not_theirs(session):
            return None
        return self._json(*macros.press(session, key,
                                        self._session_on_node(session, str(req.get("node") or ""))))

    def _chat(self, req):
        """Read a conversation, send into one, or mark one seen: chat.converse.

        Who may read what is decided HERE and not in chat.py: a direct
        conversation is its two ends' and a project feed is whoever may see
        the project. The store holds lines; the door decides.
        """
        me = self._who()
        uid = users.uid_of(me)
        if not uid:
            return self._json({"error": "not an account"}, 403)
        act = field(req, "action") or "read"
        store = users.load()["users"]
        by_name = {n: u.get("uid") for n, u in store.items() if u.get("uid")}
        who, proj = field(req, "who"), field(req, "project")
        if proj:
            # may_see, not may_work: a project's channel is the group chat for
            # everybody on it, and saying something in one is not a change to
            # the project. So an administrator, who is shown every project,
            # can read and answer every channel, which is what makes it
            # useful to them, while a user has the channels they were given
            # and no others. The list marks which are actually theirs.
            if not users.may_see(me, proj):
                return self._json({"error": "not a project"}, 403)
            key, box = f"p:{proj}", ("project", proj)
        elif who:
            other = by_name.get(who)
            if not other or other == uid:
                return self._json({"error": "no such account"}, 403)
            key, box = f"dm:{other}", ("dm", other)
        else:
            return self._json({"error": "name a person or a project"}, 400)

        return self._json(*chat.converse(act, me, uid, box, key, req.get("text", ""),
                                         {u: n for n, u in by_name.items()}))

    def _say(self, req):
        """Type a message into a CLAUDE session and press Enter.

        The one place this server types free text into a pane, and every
        restriction on it is load-bearing. /api/send deliberately takes a
        macro name and never a command string, because a pane is usually a
        shell and free text there is arbitrary execution. This is the
        exception an account with no shell needs: its Claude session is a
        read-only terminal, so the only way to say anything is through here,
        and it is narrowed until the exception cannot become the rule:

          * the session has to be a `claude-…` one, matched against a project
            this account can actually see. Not a name from the request: a
            shell session named through here would be exactly the hole;
          * it has to be this account's conversation, by the same holder
            record the proxy checks;
          * control characters are stripped (macros.say), so a message
            cannot move the cursor, clear the screen, or carry an escape
            sequence.

        What is left is text into Claude's own input box, which is what the
        person would have typed if they had a terminal.
        """
        me = self._who()
        want = str(req.get("session", ""))
        # THEIR OWN session on a project they can work on. The name carries the
        # account (roadmap #24), so this is one comparison rather than a
        # lookup: a name that is not the one this account's session would have
        # is somebody else's conversation, and typing into it is the thing a
        # read-only console must not become.
        project = next((p["name"] for p in project_list(me)
                        if users.tmux_prefix(me) + claude_session(p['name'])
                        == want), "")
        if not project or users.may(me, "claude", project):
            return self._json({"error": "not a Claude session of yours"}, 403)
        on_node = self._session_on_node(want, str(req.get("node") or ""))
        if want not in {x["name"] for x in tmux_sessions()} and not on_node:
            return self._json({"error": "that conversation is not running"}, 409)
        return self._json(*macros.say(want, req.get("text", ""), on_node))

    def _send(self, req):
        """Type a macro's command lines into a shell session of the caller's
        and press Enter: macros.send. Neither kind is a command string from
        the request: a name from the fixed tables, or the id of a list the
        operator saved earlier through /api/custom."""
        session, name, cid = (req.get("session", ""), req.get("macro", ""),
                              req.get("custom", ""))
        if self._not_theirs(session):
            return None
        return self._json(*macros.send(session, name, cid,
                                       self._session_on_node(session, str(req.get("node") or ""))))


class Server(ThreadingHTTPServer):
    """The listen queue a room of people and sessions needs. socketserver's
    default is 5 connections waiting to be accepted: at 129 arriving together
    the kernel reset the rest, and the ones it kept retried on a backoff that
    turned seconds into a minute. Threads are daemons so a stop is not held
    up by a request still being answered."""
    request_queue_size = 128
    daemon_threads = True


# ---- function coverage (roadmap R76) ----------------------------------------
# Under `bb tests coverage` the harness names a file, and every function of
# this dashboard's own python that any thread enters is counted and written
# there, every few seconds and on the way out. A profile hook, not a trace
# hook: call and return events only, which is what function coverage needs
# and a tenth of the cost of line events. Nothing here runs otherwise.
_COV_OUT = os.environ.get("BB_COVERAGE_OUT", "")
_cov_counts = {}
_cov_lock = threading.Lock()
_COV_HERE = str(HERE)


def _cov_profile(frame, event, arg):
    if event != "call":
        return
    co = frame.f_code
    if not co.co_filename.startswith(_COV_HERE):
        return
    key = f"{co.co_filename}:{co.co_firstlineno}:{co.co_name}"
    with _cov_lock:
        _cov_counts[key] = _cov_counts.get(key, 0) + 1


def _cov_write():
    with _cov_lock:
        body = json.dumps({"suite": os.environ.get("BB_COVERAGE_SUITE") or "server",
                           "counts": dict(_cov_counts)})
    tmp = _COV_OUT + ".tmp"
    with contextlib.suppress(OSError):
        Path(tmp).write_text(body)
        os.replace(tmp, _COV_OUT)


def _cov_start():
    sys.setprofile(_cov_profile)
    threading.setprofile(_cov_profile)

    def loop():
        while True:
            time.sleep(3)
            _cov_write()
    threading.Thread(target=loop, daemon=True, name="coverage").start()
    atexit.register(_cov_write)


def main():
    if _COV_OUT:
        _cov_start()
    # No accounts is a normal first boot, not a failure. It used to be one:
    # the owner came from DASHBOARD_AUTH and the dashboard refused to start
    # without it, which put a password in the container's environment, where
    # it is visible to anything that can read the template, stays readable
    # forever, and is the one credential that opens a shell on this box.
    #
    # It is the first-run screen instead, and until somebody claims the
    # container that is the only page it serves. Nothing else is reachable
    # unauthenticated, which is the property the old refusal was protecting.
    if not users.all_users():
        print("dashboard: no accounts yet; the first page served will ask "
              "you to make the owner. Do it now: until you do, whoever "
              "reaches this port can.", flush=True)
    layout.prune_claude_tabs()
    # The owner takes projects on like everybody (R135): a record that
    # carried "*" gets the projects that exist now, so nothing they were on
    # is lost. Here, once every module is configured: at import it ran
    # before project_list could answer, failed, and the dev instance's
    # owner kept "*" (B496).
    try:
        moved = users.migrate_star([p["name"] for p in project_list(users.ALL)])
        if moved:
            print(f"dashboard: {moved} account(s) moved from every project to the ones that exist (R135)", flush=True)
    except Exception as e:  # noqa: BLE001 (a migration never keeps the dashboard from starting)
        print(f"dashboard: the owner's project list was not migrated (R135): {e}", flush=True)
    # Daemons: these loops must die with the server, not hold it open.
    doctor.start()
    idle.start()
    if not NODES_OK:
        claudecode.start()        # the first check soon after the start, then every six hours
    threading.Thread(target=_compat_loop, name="compat", daemon=True).start()
    artifacts.start()         # every project's dist/ to its newest builds, every few minutes
    ciwatch.start()           # a project's CI, once a day (R117)
    tunnel.apply()            # the home tunnel, where the settings say so (R176)
    if toolchains.AUTOCHECK:
        threading.Thread(target=toolchains.versions_loop, daemon=True).start()
    # The copies the nodes hold, looked at here on a timer and announced when
    # they moved, so a node need not keep asking (B643).
    threading.Thread(target=wssync.look_loop, name="sync-look", daemon=True).start()
    if imagecheck.AUTOCHECK:          # every container's registry images, weekly (R195)
        threading.Thread(target=imagecheck.check_loop, name="image-check", daemon=True).start()
    if nginxproxy.AUTOCHECK:          # the nginx image against the registry, weekly (R192)
        threading.Thread(target=nginxproxy.check_loop, name="nginx-check", daemon=True).start()
    Server(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
