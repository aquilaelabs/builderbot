#!/usr/bin/env python3
"""BuilderBot dashboard — status, project list and bb macros over HTTP.

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
import gzip
import hashlib
import hmac
import ipaddress
import json
import os
import posixpath
import re
import selectors
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time

# Beside this file. Imported up here rather than with the modules below,
# because write_json is defined from it before any of those load.
import statefile
import shutil
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
PORT = int(os.environ.get("DASHBOARD_PORT", "7680"))
# Loopback only: the browser reaches terminals through this server's own
# /term proxy, so there is no second port for the page to be told about —
# which is what DASHBOARD_TTYD_PUBLIC_PORT used to exist for.
TTYD_PORT = int(os.environ.get("DASHBOARD_TTYD_PORT", "7681"))
# The read-only twin (roadmap #27). ttyd is read-only unless started with
# --writable, so an account that may not have a shell reaches this one and
# cannot type into the socket at all — its Claude input goes through the send
# path, which is a table lookup and literal text like every other thing this
# page can make happen.
TTYD_RO_PORT = int(os.environ.get("DASHBOARD_TTYD_RO_PORT", str(TTYD_PORT + 1)))

# ---- one login for everything ---------------------------------------------
# The browser used to be asked twice — once by this server, once by ttyd on
# its own port, each with the built-in credentials dialog. The terminals are
# proxied under /term on this origin now, so a single sign-in on a real login
# page covers both, and ttyd's port no longer needs to be published at all.
#
# The cookie is a signed expiry, not a server-side session: the secret lives
# on the /config volume, so a container update does not log every phone out,
# and there is no session table to grow, lock, or clean. Basic auth still
# works on every request — curl, bb shot and the tests send it preemptively —
# but no response carries a WWW-Authenticate challenge any more, because the
# challenge is precisely what made browsers pop their own dialog.
SESSION_DAYS = 30
STATE = Path(os.environ.get("DASHBOARD_STATE", "/config"))


def _session_secret():
    """The key the session cookie is signed with, kept on the state volume.

    Every other read of that volume degrades rather than raises, and this one
    has to as well: it runs at import, so a /config that is missing or
    read-only took the whole dashboard down at startup — where the honest
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

    Stateless, like the one before it — there is no token table to keep. What
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
# managers offer to fill and to save — the thing the browser dialog never did
# well on a phone.
# The first-run screen. Same card as the sign-in — one look, and one place to
# change it — with the copy and the fields the first account needs.
#
# It is served ONLY while the store holds no accounts, and creating one closes
# it for good. That window is the honest cost of not putting a password in the
# container's environment: until somebody claims the box, whoever reaches the
# port can. Which is why the page says to do it now rather than leaving it to
# be inferred, and why the dashboard refuses everything else until it is done.
SETUP_FIELDS = """  <p class="note">Nobody owns this container yet. The first account you make
    here is the <b>owner</b>: it cannot be deleted, and it is how you add
    everyone else. Do it now — until you do, anyone who can reach this page
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
<title>BuilderBot — <!--TITLE--></title>
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<style>
  /* dvh, not vh: on a phone `vh` resolves against the LARGE viewport — the
     page as it would be with the URL bar retracted — so min-height:100vh
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

# Every command the UI can run, by name. The UI posts a key from this table and
# nothing else — no argument passthrough, no shell. A dashboard that accepted a
# command string would be a remote shell with extra steps, and there is already
# a real terminal one port over for anything not listed here.
#
# In `bb help`'s order. Commands that prompt or follow (`login`, `logs -f`)
# belong here because a macro is typed into the real terminal rather than
# captured: the operator answers the prompt or presses Ctrl-C exactly as if
# they had typed it.
#
# What is NOT here, and why. Nothing but `bb` — anything else belongs in the
# terminal, one click away. Nothing that needs an argument to mean anything
# (`bb shot URL`): a button is never a half-written command line. Nothing a
# card already does better: the Projects card lists projects and offers the
# CLAUDE.md fixes per row, the Doctor card runs doctor, the findings report
# beats `bb findings` on every count. And nothing that only means anything
# from a checkout of this repo (`bb drift`, `bb dashboard dev`) — those are
# for sessions developing the container, not for the operator's dashboard.
# The runner controls stay because the Runner card sends them, but they are
# not repeated in the bb commands card (CARD_HIDDEN below).
# The bb verbs a session on a node may run HERE through /api/v1/bb (roadmap
# #24): the ones whose state is this container's. The same list bb keeps in
# BB_RELAY_VERBS, and a test compares the two — a verb added to one side only
# is either refused on arrival or never sent.
RELAY_VERBS = frozenset((
    "roadmap", "todo", "bug", "bugs", "tests", "rules", "history", "version",
    "changelog", "work",
    "findings", "findings-history", "catchup", "claude-md", "claudemd",
    "settings", "nodes", "jobs", "ci-labels",
    # git's network half (docs/nodes.md §20, rule 2): the keys are here and
    # nowhere else, and the tree is the share, so the push runs here.
    "git"))

MACROS = {
    "status":           ["bb", "status"],
    "update":           ["bb", "update"],
    "login":            ["bb", "login"],
    "emu-start":        ["bb", "emu", "start"],
    "emu-stop":         ["bb", "emu", "stop"],
    "emu-status":       ["bb", "emu", "status"],
    "emu-list":         ["bb", "emu", "list"],
    "lint":             ["bb", "lint"],
    "logs":             ["bb", "logs"],
    "logs-follow":      ["bb", "logs", "-f"],
}
# Sendable, but not listed in the bb commands card: another card owns them.
# Empty since the controller's own runner went (the Runner card is a view of
# the nodes' runners now, and those are driven from the Nodes tab).
CARD_HIDDEN = set()

# The Linux and git/GitHub cards. Strings typed into the shell as-is — not
# argv lists like MACROS, because half of these are pipelines and shlex.join
# would quote the pipe into a literal. Still a table, for the same reason as
# MACROS: send-keys will happily type anything, so the page only ever names
# an entry. The label the card shows IS the command — these are buttons for
# things an operator would type, so hiding the text would only add mystery.
LINUX_MACROS = {
    "lx-ls":    "ls -lah",
    "lx-du":    "du -sh * | sort -rh | head -20",
    "lx-df":    "df -h /workspace /config ~",
    "lx-free":  "free -h",
    "lx-ps":    "ps aux --sort=-%mem | head -15",
    "lx-ports": "lsof -nP -iTCP -sTCP:LISTEN",
}
GIT_MACROS = {
    "git-status": "git status",
    "git-log":    "git log --oneline --graph --decorate -15",
    "git-diff":   "git diff",
    "git-stat":   "git diff --stat",
    "git-branch": "git branch -av",
    "git-stash":  "git stash list",
    "git-fetch":  "git fetch --all --prune",
    "git-pull":   "git pull",
}
# Ghosted separately from the git ones: they need the shell's repo to have a
# GitHub remote, not just to be a repo.
GH_MACROS = {
    "gh-prs":    "gh pr list",
    "gh-status": "gh pr status",
    "gh-runs":   "gh run list --limit 10",
    "gh-issues": "gh issue list",
}
SHELL_MACROS = {**LINUX_MACROS, **GIT_MACROS, **GH_MACROS}

# Keys an Android keyboard has no way to send. Names on the left are what the
# page posts; values are tmux key names. A table rather than passthrough for the
# same reason as MACROS — `send-keys` will happily type anything it is given.
TMUX_KEYS = {
    "escape": "Escape", "tab": "Tab", "enter": "Enter", "bspace": "BSpace",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "home": "Home", "end": "End", "pgup": "PPage", "pgdn": "NPage",
    "ctrl-c": "C-c", "ctrl-d": "C-d", "ctrl-z": "C-z", "ctrl-l": "C-l",
    "ctrl-r": "C-r", "ctrl-a": "C-a", "ctrl-e": "C-e", "ctrl-u": "C-u",
    "ctrl-k": "C-k", "ctrl-w": "C-w",
}

# Characters that are buried behind two taps on a phone keyboard. Sent with
# send-keys -l so tmux treats them as literal text, never as key names.
TMUX_LITERALS = {
    "pipe": "|", "tilde": "~", "slash": "/", "backslash": "\\", "dash": "-",
    "under": "_", "star": "*", "amp": "&", "dollar": "$", "caret": "^",
    "lt": "<", "gt": ">", "brace-l": "{", "brace-r": "}",
}


# How many tabs the page will open. Each terminal tab is an iframe running a
# full xterm.js with its own websocket, so this is a real ceiling on browser
# memory rather than a tidiness rule — and a phone hits it far earlier than a
# desktop does.
# The tab cap: a constant, because each terminal tab is a live terminal over
# its own socket and twelve is what a browser on this box takes without
# falling over. It was a setting for one afternoon (R29) and nobody needed to
# move it.
MAX_TABS = 12


def max_tabs():
    return MAX_TABS

# Where Claude Code keeps transcripts: one directory per working directory,
# with the path's slashes turned into dashes, holding one .jsonl per session.
CLAUDE_PROJECTS = Path(
    os.environ.get("BUILDER_HOME", str(Path.home()))) / ".claude" / "projects"


# Every request body here is a handful of short JSON fields. Anything larger is
# a mistake or a probe, and reading it into memory unbounded helps neither.
MAX_BODY = 64 * 1024


def field(req, key, default=""):
    """One string field out of a request body, or the default.

    JSON carries types, and `(req.get(k) or "").strip()` only defends against
    the field being absent. A number, a list or a dict reaches `.strip()` and
    the handler dies on an AttributeError — which is a 500 on a surface that
    runs commands, and a class of bug worth removing at the boundary rather
    than one field at a time.
    """
    v = req.get(key)
    return v if isinstance(v, str) else default


def field_list(req, key):
    """A list of strings out of a request body. Anything else is nothing."""
    v = req.get(key)
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}")
REPORTS = Path(os.environ.get("FINDINGS_DIR", "/reports"))

# Locked projects live on the /config volume so the list survives the image
# updates this container is built to expect. bb-tty reads the same file — a
# rule only the dashboard honored would be advice, since the terminal URL is
# reachable on its own.
#
# There used to be two of these. "Excluded" meant "this is not a project, stop
# showing it work" and locked meant "this one is mine to run", and the operator
# found the distinction too fine to be worth two buttons that looked alike and
# sat next to each other. Locked is the survivor and it carries the whole
# meaning now: no session starts here, the notebook is readable but not
# writable, and nothing may be created in the project on Claude's behalf. What
# it does NOT touch is everything the operator does themselves — the artifacts,
# a dev instance, the findings and their history.
LOCKS_FILE = STATE / "locked-projects.json"
# Which projects the sidebar card shows. A THIRD axis, and independent of the
# other two: pinning says nothing about what may run, only about what is worth
# looking at from the sidebar. Everything unpinned is still on the Projects
# tab, whole and with every control.
#
# PROJECT_PINS_FILE and not PINS_FILE, which is the command pin's a few lines
# below — as were load_pins, save_pins, _pin, /api/pin and the page's
# setPinned. Taking all five split this feature across two files: the constant
# resolved to theirs, the functions to mine, and project names were written
# into pinned-commands.json while nothing went red, because the command pin has
# no test (bug #20).
PROJECT_PINS_FILE = STATE / "pinned-projects.json"

# Which commands the operator keeps at the top of the card. Stored beside the
# other state for the same reason the tab strip is: this is one machine with one
# operator, and a pin made on the desktop should be there on the phone.
PINS_FILE = STATE / "pinned-commands.json"

# The operator's own command lists. Stored, never executed here: pressing one
# types its lines into a terminal exactly as `bb` macros do. That is why this is
# not the "arbitrary command string" the API refuses everywhere else — the text
# goes to a tty the same authenticated operator is already sitting at, and they
# could have typed it themselves. Nothing runs in the server's own process.
CUSTOM_FILE = STATE / "custom-commands.json"
CUSTOM_MAX = 40                 # macros
CUSTOM_TITLE_MAX = 60           # characters
CUSTOM_LINES_MAX = 20           # lines per macro
CUSTOM_LINE_MAX = 500           # characters per line


TABS_FILE = STATE / "tabs.json"

# How the sidebar is arranged: card order and which cards are collapsed, by
# the data-card keys the page uses. Validated against this list both ways, so
# the stored file can never hold a card the page would not know how to place.
CARDS_FILE = STATE / "cards.json"
# Doctor first: this order is the default an unwritten (or reset) sidebar
# gets, and the verdict on the whole box outranks any one card below it.
#
# The command lists and Sessions are NOT here any more: they live under the
# terminal, in the bar that used to be the phone's alone, because they are
# about the shell in front of you rather than about the box — and seven cards
# is a sidebar you can read where twelve was a list you scrolled past. Their
# keys dropping out of this list is also the migration: load_layout filters an
# existing cards.json against it, so a file still naming them is cleaned on
# the next read rather than needing anything done to it.
# Tools between Doctor and Runner: the reach-for-it card next to the
# health line, ahead of the two that are read rather than pressed.
CARD_KEYS = ["doctor", "tools", "admin", "runner", "projects"]


# The one implementation, in statefile.py, along with the file lock that makes
# a read-modify-write safe against the OTHER writer — a `bb` invocation, which
# is a different process. Kept as a name here because thirty-odd call sites and
# every configure() injection already say write_json.
write_json = statefile.write_json


# One lock for every read-modify-write of a state file. The revision the
# layout carries is what lets two browsers share a strip without fighting;
# two saves reading the same file and both stamping rev+1 handed both pages
# the same number, and each then took the other's writes for its own and
# skipped them. Coarse on purpose: these are tiny files and rare writes.
_state_lock = threading.Lock()


def load_cards():
    try:
        v = json.loads(CARDS_FILE.read_text())
    except (OSError, ValueError):
        v = {}
    if not isinstance(v, dict):         # a hand-edited file is not fatal
        v = {}
    # Filter before deduping: membership tolerates any junk a hand-edited file
    # can hold, where hashing it for dict.fromkeys would not.
    order = v.get("order") if isinstance(v.get("order"), list) else []
    order = list(dict.fromkeys(k for k in order if k in CARD_KEYS))
    # A card this image knows about that the stored file predates still has to
    # land somewhere, and "its default position" means exactly that: inserted
    # where CARD_KEYS puts it, not appended. Appending is how a new card
    # arrived at the bottom of an existing sidebar and looked misplaced until
    # somebody hit reset.
    for i, k in enumerate(CARD_KEYS):
        if k not in order:
            order.insert(min(i, len(order)), k)
    closed = v.get("closed") if isinstance(v.get("closed"), list) else []
    closed = list(dict.fromkeys(k for k in closed if k in CARD_KEYS))
    return {"order": order, "closed": closed}


def save_cards(v):
    write_json(CARDS_FILE, v)

# What a stored tab may contain. Anything else is dropped rather than trusted:
# this file is written by one browser and handed to every other one, so it is
# the one place where a bad value could travel between devices.
# Every kind of tab the saved layout may carry. A kind missing from here is
# dropped on read without a word — which is how the notebook came back from a
# refresh as no tab at all: it was written to the file and filtered out of it.
# "findings" left the set when the report became the notebook's Analysis
# view — a stored layout that still carries one sheds it on read.
TAB_KINDS = {"term", "packages", "todo", "projects", "docker", "findings",
             "nodes", "settings", "jobs", "users", "phone", "profile"}


def _layouts():
    """The whole file: {"boot": ..., "users": {uid: layout}}.

    One strip per ACCOUNT, keyed by the minted id rather than the name so a
    rename keeps it (users.mint_uid says why). It was one layout for the whole
    box until roadmap #25 — written by whoever last saved and handed to
    everybody else, which is fine for one operator and wrong the moment there
    are two.

    A file from before that has the layout at the top level. It is moved to
    the owner, once, on the first read: the owner is who was using it, and
    dropping it instead would cost somebody their tab strip on an upgrade for
    no reason.
    """
    try:
        v = json.loads(TABS_FILE.read_text())
    except (OSError, ValueError):
        v = {}
    if not isinstance(v, dict):
        v = {}
    if not isinstance(v.get("users"), dict):
        moved = {k: v[k] for k in ("rev", "tabs", "panes", "active") if k in v}
        v = {"boot": v.get("boot"), "users": {}}
        if moved:
            owner = users.get(users.owner_name() or "")
            if owner and owner.get("uid"):
                v["users"][owner["uid"]] = moved
    return v


def load_layout(uid):
    """One account's strip, shape-checked. `uid` is users.uid_of(who)."""
    v = (_layouts().get("users") or {}).get(str(uid or ""))
    # Shape-checked field by field, not trusted: this runs inside every status
    # poll and once at startup (prune_claude_tabs), so a file holding
    # `"tabs": 5` — a hand edit, or a client that posted junk before the
    # handler checked — must read as "no layout", not raise and take the
    # whole dashboard down with a 500 per poll and a crash at the next boot.
    if not isinstance(v, dict):
        v = {}
    tabs, ids = [], set()
    stored = v.get("tabs") if isinstance(v.get("tabs"), list) else []
    for t in stored[:max_tabs()]:
        if not isinstance(t, dict) or t.get("kind") not in TAB_KINDS:
            continue
        tid, arg, label = t.get("id"), t.get("arg"), t.get("label")
        if not all(isinstance(x, str) for x in (tid, arg, label)):
            continue
        if len(tid) > 32 or len(arg) > 200 or len(label) > 80:
            continue
        # Ids address panes and are how a tab is closed; a duplicate would make
        # two tabs indistinguishable to everything downstream.
        if tid in ids:
            continue
        ids.add(tid)
        tabs.append({"id": tid, "kind": t["kind"], "arg": arg, "label": label,
                     "fixed": bool(t.get("fixed"))})
    stored = v.get("panes") if isinstance(v.get("panes"), list) else []
    panes = [p if isinstance(p, str) and p in ids else None for p in stored[:2]]
    while len(panes) < 2:
        panes.append(None)
    rev = v.get("rev")
    return {"rev": rev if isinstance(rev, int) and rev >= 0 else 0,
            "tabs": tabs, "panes": panes,
            "active": 1 if v.get("active") == 1 and panes[1] else 0}


def save_layout(uid, v):
    """Write one account's strip, leaving every other account's alone."""
    uid = str(uid or "")
    if not uid:
        return                            # not a person: nothing to remember
    all_of = _layouts()
    all_of["users"][uid] = v
    write_json(TABS_FILE, all_of | {"boot": boot_id()})


def boot_id():
    """An identifier for this run of the container.

    PID 1 is the container's init, so when it changes the container was
    restarted. Pairing its start time with the host's boot time keeps the value
    from repeating across a host reboot. Restarting only the dashboard leaves
    both untouched, which is the distinction this is for.

    An unreadable /proc gives "", which compares equal to nothing and so is
    treated as "cannot tell" by the one caller that acts on a difference.
    """
    try:
        start = Path("/proc/1/stat").read_text().rsplit(")", 1)[1].split()[19]
        btime = next(l for l in Path("/proc/stat").read_text().splitlines()
                     if l.startswith("btime "))
        return f"{btime.split()[1]}.{start}"
    except (OSError, IndexError, StopIteration):
        return ""


def prune_claude_tabs():
    """Drop Claude tabs left over from a previous run of the container.

    A shell tab survives a restart because it can: bb-tty recreates the session
    in the same directory and the operator carries on. A Claude tab cannot — the
    conversation ended with the container, and restoring the tab would start a
    brand new session wearing the old one's name. The transcript is still on
    disk, so the project's Claude button offers to resume it; that is a decision
    to make, not one to make silently at boot.

    Called once at startup, and once for EVERY account: the strip is per
    person now (roadmap #25), and a boot that pruned only one of them would
    leave everyone else's dead Claude tabs on their strip.

    The revision is bumped so a browser left open across the restart adopts
    the pruned strip instead of saving its stale tabs back.
    """
    try:
        stored = json.loads(TABS_FILE.read_text())
    except (OSError, ValueError):
        return
    here = boot_id()
    if not here or stored.get("boot") == here:
        return
    for uid in list((_layouts().get("users") or {})):
        v = load_layout(uid)
        kept = [t for t in v["tabs"] if not t["arg"].startswith("claude:")]
        if len(kept) == len(v["tabs"]):
            continue                    # nothing to drop for this one
        ids = {t["id"] for t in kept}
        panes = [p if p in ids else None for p in v["panes"]]
        if panes[0] is None:
            panes = [panes[1], None]
        try:
            save_layout(uid, {"rev": v["rev"] + 1, "tabs": kept, "panes": panes,
                              "active": 1 if panes[1] else 0})
        except OSError:
            return                      # a read-only /config is not fatal here
    # The boot stamp regardless, so a run that dropped nothing is not asked
    # again on every restart afterwards.
    try:
        write_json(TABS_FILE, _layouts() | {"boot": here})
    except OSError:
        pass


def load_pins():
    try:
        v = json.loads(PINS_FILE.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(v, list):
        return []
    return sorted({x for x in v if isinstance(x, str) and x in MACROS})


def load_custom():
    """The stored custom macros, validated on the way out.

    Read back through the same checks the writer applies, so a hand-edited file
    cannot put something in the page that the page could not have saved.
    """
    try:
        v = json.loads(CUSTOM_FILE.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(v, list):
        return []
    out, seen = [], set()
    for m in v[:CUSTOM_MAX]:
        if not isinstance(m, dict):
            continue
        mid, title, lines = m.get("id"), m.get("title"), m.get("lines")
        if not isinstance(mid, str) or not re.fullmatch(r"c[0-9]{1,6}", mid) or mid in seen:
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(lines, list) or not lines:
            continue
        lines = [l for l in lines[:CUSTOM_LINES_MAX]
                 if isinstance(l, str) and l.strip() and len(l) <= CUSTOM_LINE_MAX]
        if not lines:
            continue
        seen.add(mid)
        out.append({"id": mid, "title": title.strip()[:CUSTOM_TITLE_MAX], "lines": lines})
    return out


def save_custom(macros):
    write_json(CUSTOM_FILE, macros)


def clean_lines(body):
    """Split an edit box into command lines.

    Blank lines and comment-only lines are dropped rather than typed: pressing
    Enter on an empty line is noise in a terminal, and a stored macro that
    silently includes them looks like it did something wrong.
    """
    lines = []
    for raw in (body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        # Control characters would go through send-keys -l as literal bytes and
        # could move the cursor or clear the screen mid-macro.
        line = "".join(ch for ch in line if ch == "\t" or ord(ch) >= 32)
        if line.strip():
            lines.append(line[:CUSTOM_LINE_MAX])
    return lines[:CUSTOM_LINES_MAX]


def save_pins(names):
    write_json(PINS_FILE, sorted(set(names)))


def load_locks():
    try:
        v = json.loads(LOCKS_FILE.read_text())
        return sorted({x for x in v if isinstance(x, str)}) if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def save_locks(names):
    write_json(LOCKS_FILE, sorted(set(names)))


def load_project_pins():
    """The pinned set, or None when nobody has ever pinned anything.

    None is not the same as empty and the difference decides what a fresh
    install looks like. No file means the operator has not had this thought
    yet, so every project is pinned and the card is what it always was; an
    empty LIST means they unpinned the last one on purpose, and a sidebar that
    quietly refilled itself would be arguing with them.
    """
    try:
        v = json.loads(PROJECT_PINS_FILE.read_text())
    except (OSError, ValueError):
        return None
    return sorted({x for x in v if isinstance(x, str)}) if isinstance(v, list) else None


def save_project_pins(names):
    write_json(PROJECT_PINS_FILE, sorted(set(names)))


def _project_of(uri, known, nonproject=frozenset()):
    """Which mounted project a scanner-recorded path belongs to.

    The scanner records where *it* saw the code, which is never where this
    container mounts it, so the only reliable anchor is a path component that
    matches a directory in the workspace.

    A component that matches a directory in the share that is NOT a project —
    the SDK share, the runner's tree, anything else living in there —
    attributes to IGNORED rather than to nothing. The host scanner sweeps the
    whole share, so the flutter checkout alone lands thousands of findings,
    and filing those as "unattributed" buried the handful of genuinely
    unplaceable paths under them: 9,000 rows of vendored toolchain wearing the
    label that was meant to say "look at this one, its path is wrong".

    `nonproject` is everything in the share minus the projects, so this needs
    no list of what to skip and nothing has to be excluded on the scanner.
    """
    parts = [p for p in uri.replace("\\", "/").split("/") if p]
    for i, part in enumerate(parts):
        if part in known:
            return part, "/".join(parts[i + 1:]) or part
        if part in nonproject:
            return IGNORED, "/".join(parts[i:])
    return None, "/".join(parts)


# The sentinel a finding attributes to when its path resolves into a directory
# the dashboard knows and deliberately does not treat as a project. Impossible
# as a real project name (a slash never survives a directory name).
IGNORED = "not/a/project"


def share_siblings():
    """Shares mounted beside the projects folder, by the name the host calls them.

    The subtraction below derives "not a project" from what sits INSIDE
    /workspace, which worked while /workspace was the whole development share:
    the SDK share was a directory in it, so it fell out for free. Pointing
    /workspace at the projects folder — a better arrangement, and the one that
    cut most of this noise — took the SDK share outside it, and 267 findings
    about downloaded Flutter, Go and Android toolchains went straight to
    "unattributed", which is the label meant for a path that is genuinely
    wrong. Improving the layout regressed the classifier.

    So the wider question is asked instead: what does this container mount from
    beside its own projects folder? /proc/self/mountinfo answers it —

        /development/projects -> /workspace
        /development/SDK      -> /sdk

    — so `SDK` is a sibling of the projects folder, and a scanner sweeping the
    share reports its paths as SDK/flutter/... . Derived, so it keeps working
    wherever the shares are moved to next, and no list of what to skip.

    Two things it deliberately will not do. A mount whose source is a whole
    filesystem (root "/") says nothing about a directory name and is skipped.
    And a name that IS a valid project never enters the set, whatever it is
    mounted from — /mnt/user/appdata/BuilderBot would otherwise teach this to
    ignore the BuilderBot project's own findings, which is the one mistake
    here that would hide real work rather than noise.
    """
    try:
        with open("/proc/self/mountinfo") as f:
            return siblings_of(f.read(), str(WORKSPACE))
    except OSError:
        return set()


def siblings_of(mountinfo, workspace):
    """The parsing half of share_siblings, given the file's text.

    Split out to be driven with a real mount table rather than this one: the
    case that must not regress — a mount whose basename happens to be a
    project's name — cannot be produced by mounting something here."""
    src = {}
    for line in mountinfo.splitlines():
        bits = line.split()
        if len(bits) > 4:
            src[bits[4]] = bits[3]              # mount point -> path in source fs
    ws = src.get(workspace)
    if not ws or ws == "/":
        return set()
    parent = posixpath.dirname(ws)
    out = set()
    for point, path in src.items():
        if point == workspace or path == "/":
            continue
        if posixpath.dirname(path) == parent:
            name = posixpath.basename(path)
            if name:
                out.add(name)
    return out


def nonproject_dirs(valid):
    """Top-level workspace directories that are not projects.

    Derived by subtraction rather than by recognising each kind: everything in
    the share that is not a project worth reading findings for is one of these.
    That set is the one the card already computes — listed, not excluded, no
    error-level issue — so asking for it and taking the remainder needs no
    maintenance when a new sort of directory turns up in the share.

    Subtracting the *valid* projects rather than merely the listed ones is what
    makes it cover the case that started this. A share mapped inside the
    projects folder with nothing to mark it is still a directory, so the card
    lists it — as a project with an error, because it is not a repository. Take
    away only the listed names and its thousands of findings stay in play; take
    away the valid ones and it falls out with the rest.

    That width is the point. The SDK share is the case that made it matter: on
    this box it lives *inside* the development share, so the host's scanner
    walks it like anything else and a report grew nine thousand findings
    attributed to a "project" that is a pile of downloaded toolchains. Those
    now attribute to IGNORED and are counted aside, rather than burying the
    handful of genuinely unplaceable paths that the "unattributed" label is
    for. Nothing had to be excluded on the scanner to get there.

    Listed fresh per parse; it is one readdir and one small file."""
    out = set()
    try:
        for d in WORKSPACE.iterdir():
            if d.is_dir() and d.name not in valid:
                out.add(d.name)
    except OSError:
        pass
    # ...plus the shares mounted beside the projects folder, which the
    # subtraction above cannot see now that it is not the whole share.
    out |= share_siblings()
    out -= set(valid)               # never a project, whatever it is mounted from
    return out


def _parse_run(runinfo, known, nonproject=frozenset()):
    """One SARIF run -> (tool name, rows)."""
    driver = (runinfo.get("tool") or {}).get("driver") or {}
    rules = {}
    for r in driver.get("rules") or []:
        rules[r.get("id")] = {
            "desc": ((r.get("shortDescription") or {}).get("text")
                     or (r.get("fullDescription") or {}).get("text") or ""),
            "help": ((r.get("help") or {}).get("text") or ""),
            "uri": r.get("helpUri") or "",
            "level": ((r.get("defaultConfiguration") or {}).get("level") or "warning"),
        }
    rows = []
    for res in runinfo.get("results") or []:
        rid = res.get("ruleId") or "unknown"
        meta = rules.get(rid, {})
        msg = ((res.get("message") or {}).get("text") or "")
        loc = ((res.get("locations") or [{}])[0].get("physicalLocation") or {})
        uri = ((loc.get("artifactLocation") or {}).get("uri") or "?")
        line = ((loc.get("region") or {}).get("startLine") or 0)
        proj, rel = _project_of(uri, known, nonproject)
        # CVEs turn up in the rule id (Trivy) or the prose (most others).
        cves = sorted(set(CVE_RE.findall(" ".join([rid, msg, meta.get("desc", ""),
                                                   meta.get("help", "")]))))
        rows.append({
            "rule": rid,
            "level": res.get("level") or meta.get("level") or "warning",
            "desc": meta.get("desc") or msg.split("\n")[0],
            "message": msg.strip(),
            "uri": meta.get("uri", ""),
            "project": proj,
            "path": rel,
            "line": line,
            "cves": cves,
        })
    return driver.get("name") or "", rows


def parse_sarif(path, known, nonproject=frozenset()):
    """SARIF 2.1.0 -> flat findings. Tolerant: a malformed run is skipped, not
    fatal, because one bad report should not blank the whole page."""
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return {"file": path.name, "tool": "?", "error": str(e), "findings": []}

    tools, rows = [], []
    for runinfo in doc.get("runs") or []:
        # "Tolerant" has to mean it: SARIF in the wild has arrays where objects
        # belong, and one such run used to take the whole endpoint down with an
        # AttributeError rather than being skipped as documented.
        try:
            name, got = _parse_run(runinfo, known, nonproject)
        except (AttributeError, TypeError, IndexError, KeyError):
            continue
        if name and name not in tools:
            tools.append(name)
        rows.extend(got)
    # A file can hold runs from several tools; naming it after the last one seen
    # was arbitrary.
    return {"file": path.name, "tool": " + ".join(tools) or "?", "findings": rows}


# What a locked project refuses, in one place.
#
# The button being hidden is not the rule; this is. The dashboard's own URLs
# are reachable without it, so a lock enforced only by a missing control is
# advice — the same reasoning that put the lock file where bb-tty can read it
# rather than keeping it in the page.
#
# READS are never refused, and the list of what stays is the point of the
# feature: the notebook opens, the findings and their history are there, the
# artifacts list and a dev instance still work. What goes is everything that
# writes on Claude's behalf — the notebook's three tabs, and creating or
# refreshing a CLAUDE.md, which is a file put into somebody else's project.
LOCKED_REFUSAL = ("{name} is locked — yours to run. Unlock it to change its "
                  "notebook or its CLAUDE.md; everything you read here still "
                  "works while it stays locked.")


def locked_out(name):
    """The refusal for a write into a locked project, or None."""
    if name and name in set(load_locks()):
        return {"error": LOCKED_REFUSAL.format(name=name)}
    return None


def _valid_projects(ps):
    """The projects whose findings are worth surfacing: no error-level issue.

    A repo that is broken gets triaged in the Projects card first — its
    findings would only pad the numbers for code nobody can currently work on.
    A LOCKED one is not in that category and never was: locking says who runs
    it, not whether its code is worth reading about, and the operator asked
    for the analysis to keep working on a locked project."""
    return {p["name"] for p in ps
            if not any(i["level"] == "error" for i in p["issues"])}


def findings_payload(who):
    ps = project_list(who)
    known = {p["name"] for p in ps}
    if not REPORTS.is_dir():
        return {"available": False, "reports": [], "projects": sorted(known)}
    files = sorted(f for f in REPORTS.glob("*.sarif")) + \
            sorted(f for f in REPORTS.glob("*.sarif.json"))
    # The same rule the counts apply: a report a whole cycle behind its
    # siblings is not read. Its scanner has probably died and left its last
    # good output in place, and this payload feeding the Analysis tab while
    # the counts refused the same file meant the tab could show findings the
    # rest of the page said did not exist — a stale COPY of a live report
    # doubled every rule it contained.
    dropped = stale_reports()
    files = [f for f in files if f.name not in dropped]
    # Only the projects worth reading findings for get attributed to: listed,
    # no error-level issue. Everything else under the share —
    # a project shut out, one that is broken, the SDK share, a directory
    # nobody has explained — attributes to IGNORED and is counted aside.
    #
    # Counted rather than silently dropped: a report that quietly shrinks
    # reads as "covered everything" when it did not.
    valid = _valid_projects(ps)
    nonproject = nonproject_dirs(valid)
    reports, aside = [], 0
    for f in files:
        rep = parse_sarif(f, valid, nonproject)
        keep = []
        for r in rep["findings"]:
            if r["project"] == IGNORED:
                aside += 1
            else:
                keep.append(r)
        rep["findings"] = keep
        reports.append(rep)
    # One number rather than the two this used to keep. They were never shown
    # anywhere, and the distinction they drew — shut out on purpose vs. not a
    # project — stopped being one this code could make once attribution became
    # "valid projects only": a broken project and a vendored toolchain now
    # leave by the same door, which is the point.
    return {"available": True, "projects": sorted(known),
            "aside": aside, "reports": reports}


# `bb sdk install|update|remove` refuses when CLAUDECODE is set, and the
# message it prints tells the session to ask the operator to use this page.
# So this page must never carry that variable — and it can: `bb dashboard dev`
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


# Where the image keeps the CLAUDE.md the environment block is copied from.
# Same file `bb claude-md` reads; overridable only so the tests can point at a
# checkout instead of an installed image.
TEMPLATE_MD = Path(os.environ.get("TEMPLATE_MD",
                                  "/opt/builderbot/templates/project-CLAUDE.md"))
ENV_BEGIN = "<!-- BUILDERBOT:ENV:BEGIN -->"
ENV_END = "<!-- BUILDERBOT:ENV:END -->"


def md_block(path):
    """The environment block of a CLAUDE.md, markers included, or None.

    The same span `bb claude-md` compares — everything below the end marker is
    the project's own writing and is never read here.
    """
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    lines, out = text.splitlines(), []
    for line in lines:
        if not out and ENV_BEGIN not in line:
            continue
        out.append(line)
        if ENV_END in line:
            return "\n".join(out)
    return None                          # no begin marker, or no end after it


def md_state(path):
    """"current" | "stale" | "unmarked" | "unknown" for a project's CLAUDE.md.

    Compared here rather than by shelling out to `bb claude-md` once per project
    on every fifteen-second poll: the comparison is two file reads, and a
    subprocess per project per poll is not.
    """
    want = md_block(TEMPLATE_MD)
    if want is None:
        return "unknown"                 # no template to compare against
    have = md_block(path)
    if have is None:
        return "unmarked"
    return "current" if have == want else "stale"


_WINDOW_RE = re.compile(r"BUILDERBOT:ENV:WINDOW (\d+\.\d+)")


def md_window(path):
    """The compatibility window a CLAUDE.md's environment block was written
    for — "0.4", from the BUILDERBOT:ENV:WINDOW line under the begin marker
    — or "" for a block that predates the line. Only the line inside the
    markers counts, so a project's own notes cannot claim one. Empty means
    "cannot say", read the way nodes.agent_window reads it: never as a gap."""
    m = _WINDOW_RE.search(md_block(path) or "")
    return m.group(1) if m else ""


def md_gap(path):
    """A sentence when a project's block is from ANOTHER compatibility window
    than the template this controller ships, else "".

    The window is the same promise the agent's is (nodes.agent_window): while
    BuilderBot is 0.4.x, a 0.4 block briefs a session truthfully enough for
    it to work, and drift inside the window — a feature the block does not
    mention yet — is routine: the row offers the update, and nothing stops
    for it. Across a window that promise was never made, and a session
    briefed with the old block would be told about a different container
    — so that is the one state a session is refused, ghosted and ended over,
    until the block is updated (compat_reap_once, bb-tty, the row's button).
    """
    ours, theirs = md_window(TEMPLATE_MD), md_window(path)
    if not ours or not theirs or ours == theirs:
        return ""
    return (f"CLAUDE.md's environment block is from another compatibility window "
            f"({theirs} against {ours}) — a session briefed with it would be told about "
            "a different BuilderBot. The update link on the row fixes it in one press")


def node_holds():
    """{node id: why} for every agent node whose agent is from another
    compatibility window than this controller ships — the half of a
    project's hold that is its node's. Being merely behind is not here:
    inside a window an older agent takes a job and a session, and the Nodes
    tab's Update is a courtesy rather than a gate."""
    out = {}
    if NODES_OK:
        return out
    for n in nodes.node_list():
        if n["kind"] == "agent" and nodes.agent_gap(n):
            out[n["id"]] = nodes.agent_stale(n)
    return out


def compat_holds():
    """{project: why} for every project no Claude session may run on right
    now: its CLAUDE.md block from another window, or its node's agent from
    one. Per project on purpose — another project's node being out of window
    is that project's problem, and this one's button stays live."""
    out = {}
    holds = node_holds()
    pp = prefs.all_projects()
    try:
        dirs = [d for d in WORKSPACE.iterdir() if d.is_dir()]
    except OSError:
        return out
    for d in dirs:
        md = d / "CLAUDE.md"
        why = md_gap(md) if md.is_file() else ""
        if not why:
            why = holds.get((pp.get(d.name) or {}).get("node") or "", "")
        if why:
            out[d.name] = why
    return out


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
    it. Inside a window nothing here fires — an update to the block or the
    agent that keeps the window leaves every session running. Run once at
    start, which is the moment after a controller update, and on a timer
    after that for a window that moves under a running server (a bump
    landing on a `bb dashboard dev` restart, a node enrolled behind)."""
    holds = compat_holds()
    if not holds:
        return []
    wanted = {tmux_name(f"claude-{p}"): why for p, why in holds.items()}
    ended = []
    for s in tmux_sessions():
        why = wanted.get(tmux_base(s["name"]))
        if not why:
            continue
        r = run(["tmux", "kill-session", "-t", "=" + s["name"]], timeout=10)
        if r["code"] == 0:
            ended.append(s["name"])
            print(f"dashboard: compat: ended {s['name']} — {why}", flush=True)
    if not NODES_OK:
        for nid, (nname, sess) in nodes.node_sessions().items():
            for s in sess:
                real = str(s.get("name") or "")
                why = wanted.get(tmux_base(real))
                if not why:
                    continue
                nodes.session_kill(nid, real)
                ended.append(real)
                print(f"dashboard: compat: ending {real} on {nname} — {why}", flush=True)
    return ended


def _compat_loop():
    while True:
        try:
            compat_reap_once()
        except Exception as e:        # noqa: BLE001 — a sweeper must not die
            print(f"dashboard: compat: {e}", flush=True)
        time.sleep(max(1.0, COMPAT_SWEEP_S))


# What a new project may be called, and where a clone may come from. The name
# becomes a directory under /workspace and part of a tmux session name, so it
# gets the strictest charset of the two — one path segment, starting with a
# letter or digit, which also rules out `_work`, dotfiles and `..`. The URL is
# one of GitHub's address shapes and nothing else: `git clone` accepts
# transports a browser form must never reach (`ext::` runs commands), so
# anything unrecognized is refused rather than passed along.
PROJECT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")  # GitHub caps repos at 100
GITHUB_URL = re.compile(
    r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*?(?:\.git)?/?")

def build_claude_md(about):
    """A new project's CLAUDE.md: the shipped template, with the section below
    the end marker replaced by the operator's own notes when they gave any.

    The same file `bb claude-md --init` copies; building it here as well means
    the notes land in one write instead of a copy the operator then has to
    edit. No notes → the template verbatim, placeholder section and all.
    """
    try:
        text = TEMPLATE_MD.read_text()
    except OSError:
        return None                      # no template: older image, say so
    if not about:
        return text
    i = text.find(ENV_END)
    if i < 0:
        return text                      # unmarked template: nothing to split on
    head = text[:i + len(ENV_END)]
    return head + "\n\n---\n\n## About this project\n\n" + about.rstrip() + "\n"


# The builder user's ssh directory. Overridable through BUILDER_HOME for the
# same reason CLAUDE_PROJECTS is: the tests point it at a scratch home, and
# nothing they write may land in the real one.
SSH_DIR = Path(os.environ.get("BUILDER_HOME", str(Path.home()))) / ".ssh"


def agent_keys():
    """[{name, pub}] for every key the shielded agent holds.

    ssh-add -L prints the *public* halves — the one part of a shielded key
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
    """Whether git-over-https can authenticate — i.e. a PAT is wired up.

    Asked of gh rather than the environment, because gh is what actually
    answers the credential prompt (`gh auth setup-git` at startup): this is
    true exactly when an https remote will work, whether a session-visible
    GITHUB_PAT or a manual `gh auth login` made it so. `gh auth token` is
    offline and instant; `gh auth status` phones home.
    """
    return run(["gh", "auth", "token"], timeout=10)["code"] == 0


def repo_path(url):
    """owner/repo from an already-validated GitHub URL."""
    path = re.sub(r"^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)",
                  "", url).rstrip("/")
    return path[:-4] if path.endswith(".git") else path


def ensure_deploy_alias(name, pub):
    """A per-repo ssh alias for one agent key, created idempotently; returns
    the alias.

    Why an alias at all: deploy keys are scoped to a single repository, and
    ssh offers every agent key in order — GitHub authenticates the first
    valid one and then refuses the repo it does not belong to. The fix is
    IdentitiesOnly plus an IdentityFile naming the *public* half, which acts
    purely as a selector for the agent key (the private half stays shielded).

    Everything written lives in a namespace of our own — bb_<name>.pub and
    Host bb-<name> — so a .pub or an alias the operator maintains by hand is
    never touched, and rewriting ours is always safe.

    The lock makes the check-then-append on ~/.ssh/config actually atomic:
    two concurrent requests using the same key would otherwise both miss the
    marker and both append the block. ssh would still behave (first match
    wins), but "idempotent" should not mean "single-threaded".
    """
    alias = f"bb-{name}"
    with _ssh_lock:
        return _ensure_deploy_alias(alias, name, pub)


_ssh_lock = threading.Lock()


def _ensure_deploy_alias(alias, name, pub):
    SSH_DIR.mkdir(mode=0o700, exist_ok=True)
    pub_path = SSH_DIR / f"bb_{name}.pub"
    try:
        current = pub_path.read_text()
    except OSError:
        current = None
    if current != pub + "\n":
        pub_path.write_text(pub + "\n")
    cfg = SSH_DIR / "config"
    marker = f"# builderbot:deploy-key:{name}"
    try:
        have = cfg.read_text()
    except OSError:
        have = ""
    if marker not in have:
        block = (f"\n{marker}\nHost {alias}\n"
                 f"    HostName github.com\n"
                 f"    IdentityFile {pub_path}\n"
                 f"    IdentitiesOnly yes\n")
        with open(cfg, "a") as f:
            f.write(block)
        os.chmod(cfg, 0o600)
    return alias


def _github_remote(remotes):
    """Whether any of `git remote -v`'s lines points at GitHub — ssh host
    aliases included.

    The literal string only covers remotes written as github.com. The
    standard multi-deploy-key setup — including the bb- aliases this
    dashboard's own clone and link flows write — hides the real host behind
    a ~/.ssh/config Host alias, and this box's own repos are addressed that
    way. `ssh -G` resolves an alias to its HostName from the config alone,
    no network involved. Hosts are charset-checked (and must not start with
    a dash) before reaching an argv.
    """
    if "github.com" in remotes:
        return True
    hosts = set()
    for line in remotes.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        url = parts[1]
        if "://" in url:                     # ssh://git@host/... — https etc.
            m = re.match(r"ssh://(?:[^@/]+@)?([A-Za-z0-9][A-Za-z0-9._-]*)", url)
        else:                                # scp form: git@host:path
            m = re.match(r"(?:[^@:/]+@)?([A-Za-z0-9][A-Za-z0-9._-]*):", url)
        if m:
            hosts.add(m.group(1))
    for h in hosts:
        r = run(["ssh", "-G", h], timeout=10)
        if r["code"] == 0 and any(l.strip() == "hostname github.com"
                                  for l in r["out"].splitlines()):
            return True
    return False


# A directory holding this file is not a project: not listed, not offered a
# Claude session, not counted. Written by the container into its own paths
# under the projects share, and by hand for anything else.
IGNORE_MARKER = ".bbignore"


def _session_at(name):
    t = session_target(name)
    if t["where"] == "node":
        # The node's boot, for the page to stamp into a terminal's URL in
        # place of this container's: bb-tty on the node compares against the
        # node's own run, and a tab carrying the controller's boot was
        # refused there as "from before the container restarted" on every
        # connection — a loop nobody could end from the Sessions card,
        # because the session never started.
        return {"session_at": t["name"], "session_why": "",
                "session_boot": t.get("boot") or ""}
    if t["where"] == "refused":
        return {"session_at": t["name"], "session_why": t["why"], "session_boot": ""}
    return {"session_at": "", "session_why": "", "session_boot": ""}


def project_list(who):
    """Every directory under /workspace that is a project, with what is wrong
    with it. Named _list because `projects` is the module beside this one that
    creates them — one name for the reading and one for the writing.

    `who` is the account asking (Handler._who()), and it is REQUIRED rather
    than defaulted for the reason the whole scheme leans on: this is the one
    function that decides which projects exist, and a call site that forgot to
    say who was asking would quietly show every project to everybody. Missing
    it is a TypeError, which a test finds; defaulting it would be a hole
    nothing finds. The server's own non-request contexts pass users.ALL and
    say so.

    Filtering here is also most of the authorization. Fifteen handlers ask
    "is this a project?" against this list, so a project somebody cannot see
    is not refused to them — it does not exist, which is the same answer a
    typo gets and leaks nothing by comparison.
    """
    out = []
    uid, gid = os.getuid(), os.getgid()
    try:
        if not WORKSPACE.is_dir():
            return out
    except OSError:
        pass                    # unreadable: reported by the listing below
    locked = set(load_locks())
    pins = load_project_pins()
    stopped = last_stop()
    # One small file for the whole list, read here rather than per row: this
    # runs on the fifteen-second poll and a per-project read would be a dozen
    # opens for a dozen values that came from the same dictionary.
    project_prefs = prefs.all_projects()
    # One answer per node about its agent, for every project row on it.
    node_gaps = {}
    if not NODES_OK:
        for n in nodes.node_list():
            if n["kind"] == "agent" and n.get("live"):
                why = nodes.agent_stale(n)
                if why:
                    node_gaps[n["id"]] = why
    # ...and the sharper answer for the Claude button: a node from another
    # WINDOW holds this project's sessions; one merely behind does not.
    held_nodes = node_holds()
    try:
        here = sorted(WORKSPACE.iterdir())
    except OSError:
        # A workspace this user cannot list is a mount to fix, not a reason for
        # the runner card and the terminal to stop working too.
        return [{"name": str(WORKSPACE), "git": None,
                 "last_claude": None,
                 "issues": [{"level": "error",
                             "text": f"cannot list this directory as uid {uid}:{gid}"
                                     " — chown it to PUID:PGID on the host"}]}]
    cloning = projects.busy_name()
    open_todo = todo.counts()
    # One batch spans the notebook, so the count the panel shows has to be
    # both halves added up — a banner reporting only the roadmap's would read
    # as "nothing much" while a dozen tracker changes sat unrecorded.
    todo_batches = todo.batches()
    for name, b in bugs.batches().items():
        if name in todo_batches:
            todo_batches[name]["changes"] += b.get("changes", 0)
            todo_batches[name]["at"] = min(todo_batches[name]["at"], b["at"])
        else:
            todo_batches[name] = b
    bug_revs = bugs.revisions()
    # ...and the roadmap's, so an open notebook stops being the one surface
    # here that never notices somebody else writing (roadmap #26). The Bugs
    # tab has polled bug_rev since it was built; the Roadmap and Memory views
    # loaded once when the tab opened and then held that drawing forever.
    nb_revs = todo.revisions()
    test_revs = testreg.revisions()
    test_counts = testreg.counts()
    rule_revs = rules.revisions()
    rule_counts = rules.counts()
    # What a session has waiting for the operator (roadmap #27): the count
    # lights the bell and the notebook band; the revision tells an open
    # notebook to re-read the queue.
    pend_counts = pending.counts()
    pend_revs = pending.revisions()
    for d in here:
        # Mid-clone: a directory with a .git and not much else, which every
        # check below reads as a repository in a strange state. The job row is
        # already saying what it really is.
        if d.name == cloning:
            continue
        # `_work` is the runner's checkout area, not a project. Hidden
        # directories are not projects either: the whole projects folder is
        # mounted now, so this list would otherwise open with the share's own
        # furniture (.Recycle.Bin and friends) presented as things to fix.
        #
        # .bbignore is the general form of the same idea, and the one thing
        # here an operator can drive: a directory holding that file is not a
        # project and is not listed. The container drops it into any path of
        # its own that lands inside the projects share — the SDK share, when
        # someone maps it inside the projects folder rather than beside it —
        # and anyone can create one by hand for a directory they would rather
        # not see. It hides; locking a project is the thing that *blocks*, and
        # that is a different control with a different guarantee.
        if (not d.is_dir() or d.name == "_work" or d.name.startswith(".")
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
                                   f"uid {uid}:{gid} — chown it to PUID:PGID on the host"})

        # Path.is_file() only swallows ENOENT/ENOTDIR/EBADF/ELOOP — EACCES is
        # re-raised, so an unreadable project directory took out the whole
        # status endpoint rather than being reported as the one thing wrong.
        md_hold = ""
        try:
            has_md = (d / "CLAUDE.md").is_file()
        except OSError:
            has_md = False

        # linked defaults to True and github to False: each gates an offered
        # action (the link-to-GitHub button; the GitHub command buttons), and
        # a project this loop could not examine must get no offer rather than
        # a broken one — which is the opposite default for the two.
        branch, git_ok, linked, github = None, False, True, False
        if not missing:
            # An empty directory is the one thing never reported. It is not a
            # problem to fix — it is a mount point waiting for content, or a
            # leftover — and flagging it would be noise on every boot.
            try:
                if not any(d.iterdir()):
                    continue
            except OSError:
                pass                    # unreadable: covered by `missing` above

            if (d / ".git").exists():
                # Asking git rather than trusting the directory's existence: a
                # half-copied or corrupt .git looks identical from out here, and
                # a repo git cannot read is not one anything can act on.
                git_ok = run(["git", "-C", str(d), "rev-parse", "--is-inside-work-tree"],
                             timeout=10)["out"].strip() == "true"
            if not git_ok:
                issues.append({"level": "error", "text": "no valid git repository"})
            else:
                # Asked of git, not read out of .git/config: a worktree or a
                # submodule keeps its config elsewhere, and both flags drive
                # visible controls (the link-to-GitHub button; the GitHub
                # command card's ghosting), so a wrong guess here offers an
                # action that cannot work. -v for the URLs, which is what
                # tells a GitHub remote from any other.
                remotes = run(["git", "-C", str(d), "remote", "-v"],
                              timeout=10)["out"]
                linked = bool(remotes.strip())
                github = linked and _github_remote(remotes)
                r = run(["git", "-C", str(d), "symbolic-ref", "--short", "-q", "HEAD"],
                        timeout=10)
                # `out` carries stderr too, so a detached HEAD would otherwise
                # put a `fatal:` line where the branch name goes.
                branch = (r["out"].strip() or "(detached)") if r["code"] == 0 else "(detached)"
                if not has_md:
                    issues.append({"level": "warning", "action": "claude-md-init",
                                   "text": "no CLAUDE.md — create one"})
                elif (md := md_state(d / "CLAUDE.md")) == "stale":
                    # Offered as an action, not just a complaint: the fix is one
                    # command with no decisions in it, and the block goes stale
                    # every time the image gains a feature. From another
                    # window it is the same link with the sharper words —
                    # that one stops the project's sessions until pressed.
                    md_hold = md_gap(d / "CLAUDE.md")
                    issues.append({"level": "warning", "action": "claude-md-update",
                                   "text": ("CLAUDE.md environment block is from another "
                                            f"compatibility window ({md_window(d / 'CLAUDE.md')} "
                                            f"against {md_window(TEMPLATE_MD)}) — update")
                                   if md_hold else
                                   "CLAUDE.md environment block is out of date — update"})
                elif md == "unmarked":
                    # `bb claude-md --update` refuses this one, so it must not be
                    # offered as a link that would do nothing.
                    issues.append({"level": "warning",
                                   "text": "CLAUDE.md predates the BUILDERBOT:ENV markers"
                                           " — merge the block in by hand once"})

        # Every directory is still reported. The dashboard decides what to show,
        # and SARIF paths are attributed by matching these names — dropping one
        # here would silently orphan its findings.
        # Locking is reported by the boolean below and nothing else. It used to
        # add an issue too, which the row printed under the name: a whole
        # sentence restating what the padlock beside the name already says, on
        # every locked row, forever. It is also not a fault, and the issue list
        # is where faults go.
        sa = _session_at(d.name)
        mem_census = memory.census(d.name, home=home_for(users.uid_of(who)))
        out.append({"name": d.name, "git": branch, "git_ok": git_ok,
                    "linked": linked, "github": github,
                    "claude_md": has_md,
                    "locked": d.name in locked,
                    "pinned": True if pins is None else d.name in pins,
                    # Whether it carries its own access token — so the rename
                    # dialog can offer to change one without offering to
                    # invent one for a local repo that never had any.
                    "has_token": (STATE / "gitcreds" / d.name).is_file(),
                    "push": projects.may_push(d.name),
                    # Which model and effort this project's sessions launch on.
                    # On the row because the settings dialog draws from the poll
                    # like every other field it shows.
                    "prefs": project_prefs.get(d.name, {"model": "", "effort": ""}),
                    "push_how": projects.push_how(d.name),
                    # The newest transcript — read through the home's link
                    # onto the projects share (lib/common.sh's
                    # claude_projects_link), so a conversation a node's
                    # session had is offered here and continued there.
                    "last_claude": last_claude(d, d.name, stopped),
                    # Where this project's sessions run (roadmap #24): the
                    # node's name, or "" for here — and why the button is
                    # dead when its node cannot take one. The proxy decides
                    # the same way, so the row and the refusal agree.
                    **sa,
                    # What Claude remembers here. On the row because a memory
                    # nobody knows about is the one that goes wrong quietly.
                    "memories": mem_census["count"],
                    # ...and what is still to do, which is the number on the row
                    # actually worth glancing at.
                    "todo": open_todo.get(d.name, 0),
                    # So the open notebook learns a session has started one
                    # without waiting for the operator to touch something.
                    "todo_batch": todo_batches.get(d.name),
                    # So an open Bugs tab notices a session filing or closing
                    # one without polling the tracker itself.
                    "bug_rev": bug_revs.get(d.name, 0),
                    # Two, because the two halves are re-read separately and
                    # a memory edit must not throw away a half-typed roadmap
                    # item beside it.
                    "todo_rev": (nb_revs.get(d.name) or {}).get("todo", 0),
                    # ...and the registry's, which moves only when a run is
                    # ingested: describing one test redraws its own row.
                    "tests_rev": test_revs.get(d.name, 0),
                    "tests": test_counts.get(d.name, 0),
                    # ...and the rules', which move only when the operator
                    # writes one: nothing else can.
                    "rules_rev": rule_revs.get(d.name, 0),
                    "rules": rule_counts.get(d.name, 0),
                    "pending": pend_counts.get(d.name, 0),
                    # Why nothing routed to this project's node runs right
                    # now — its agent behind, or from another window — so
                    # the Artifacts tab and the bell say so before a job is
                    # refused. "" is the ordinary state.
                    "node_gap": node_gaps.get(project_prefs.get(d.name, {}).get("node") or "", ""),
                    # Why no Claude session may run here right now, or "":
                    # its CLAUDE.md block from another compatibility window,
                    # else its own node's agent from one. The button ghosts
                    # on this and bb-tty refuses on the same facts; the sweep
                    # ends what is running. Per project: another project's
                    # node being out of window is not this row's hold.
                    "held": md_hold or held_nodes.get(
                        project_prefs.get(d.name, {}).get("node") or "", ""),
                    "md_window": md_window(d / "CLAUDE.md") if has_md else "",
                    "pending_rev": pend_revs.get(d.name, 0),
                    # The memories are files, and the writer that moves one
                    # most often is a session's own Write tool, which passes
                    # through nothing that could count. So this one is the
                    # directory itself — how many and how lately touched.
                    "mem_rev": mem_census["rev"],
                    "issues": issues})
    # Two projects whose names slug alike are one dev instance: `My.App` and
    # `my-app` both slug to my-app, which is one compose project name, one env
    # file and one data directory driven by two rows that know nothing about
    # each other. Nothing owns the moment a directory appears under /workspace,
    # so it cannot be refused the way a container's name is — but this is the
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
                "text": f"this name and {others} both shorten to “{slug}” — a "
                        f"dev instance of either is the same containers, env "
                        f"file and data directory. Rename one before using it"})
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
        out = [p for p in out if p["name"] in allow]
    for p in out:
        p["mine"] = users.may_work(who, p["name"])
    return out


def session_cwds():
    """Session name -> {cwd, title} of its active pane.

    cwd is where a terminal *is* right now, which is not where it was opened:
    the tab is labeled from this, so a `cd` shows up in the strip. The pane
    title rides along because for Claude sessions it is a status report —
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
# after a turn). Before the REPL — trust dialog, theme picker — no title is
# set at all, which the spinner rule correctly reads as "waiting": those
# screens are waiting for input.
#
# Activity timestamps are deliberately NOT the signal here: the TUI goes
# quiet while a long tool call runs, so "no output lately" cannot tell a
# session hard at work from one sitting at the prompt.
SPINNER_GLYPHS = tuple("◐◓◑◒")


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


def session_target(project):
    """Where a session on this project runs (roadmap #24, phase 10b):

        {"where": "local"}                                   — this container
        {"where": "node", "id", "name", "host", "port", "ro_port"}
        {"where": "refused", "name", "why"}                  — bound to a node
                                                               that cannot take one

    A project bound to a node whose census says the session half is up and
    the projects share is mounted gets its session THERE. One bound to a
    node that is offline, runs no sessions or mounts no /workspace is
    REFUSED rather than quietly started here: the tree is the same share
    either way, but a session started on the wrong machine has the wrong
    toolchains and its transcripts land in the wrong home, and switching
    later splits a conversation across two boxes. The sentence says which
    of the three it was and what fixes it. A project with no node keeps its
    session here, as it always has.
    """
    nid = (prefs.get(project) or {}).get("node") or "" if project else ""
    if not nid or NODES_OK:
        return {"where": "local"}
    n = nodes.node(nid)
    if not n or n.get("kind") == "local":
        return {"where": "local"}
    name = n.get("name") or nid
    rep = n.get("reported") or {}
    se = rep.get("session")
    if n.get("state") != "online" or not n.get("live", True) and n.get("state") != "online":
        why = f"{project}'s sessions run on {name}, which is {n.get('state') or 'not online'}"
    elif not isinstance(se, dict):
        why = (f"{project}'s sessions run on {name}, whose agent predates sessions on a "
               "node — update the agent from the Nodes tab")
    elif not se.get("up"):
        why = (f"{project}'s sessions run on {name}, which runs none yet"
               + (f": {se['why']}" if se.get("why") else
                  " — provision it with --session-user"))
    elif not se.get("workspace"):
        why = (f"{project}'s sessions run on {name}, which does not mount the projects "
               "share at /workspace — add the mount on its row on the Nodes tab")
    elif se.get("writable") is False:
        # Read-only was the right way to mount the share for a Docker-only
        # sandbox and is the wrong way for one that runs sessions: nothing
        # could be saved, and the transcripts link cannot be made there.
        why = (f"{project}'s sessions run on {name}, which mounts the projects share "
               "read-only — a session there could not save a file. Untick read-only on "
               "the /workspace mount on its row on the Nodes tab and apply, or `sudo "
               "bb-sandbox readonly /workspace off` on the machine")
    elif not se.get("boot"):
        # Without the node's boot the page would stamp this container's into
        # the tab, and bb-tty there would refuse every reconnect as a stale
        # tab (bug #56) — a loop, not a session. Dead button, plain reason.
        why = (f"{project}'s sessions run on {name}, whose agent is too old to report "
               "its boot — Update agent on its row on the Nodes tab, then open this again")
    else:
        return {"where": "node", "id": nid, "name": name, "host": nodes.route_host(nid),
                "port": int(se.get("port") or 0), "ro_port": int(se.get("ro_port") or 0),
                "boot": str(se.get("boot") or "")}
    return {"where": "refused", "name": name,
            "why": why + ". Unbind the node in the project's settings dialog to work here instead."}

# A session name without the account that owns it. Shell sessions are named
# `<uid>~shell-…` since roadmap #26 — two people opening a terminal on one
# project must not land in each other's — and every question of the form
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
            "people": sorted(n for n in store if n != mine)}


def claude_sessions(sessions):
    """{project: [account name, ...]} for every Claude session running.

    Derived from the session NAMES rather than kept in a file. It used to be a
    record, because one conversation per project meant the single name
    `claude-<proj>` could not say whose it was. More than one is allowed now
    (roadmap #24) and each carries its account's prefix, so the name answers
    it — and a record that could go stale, be orphaned by a deleted account,
    or disagree with tmux stopped being worth keeping.

    The unprefixed name is the OWNER's, by the same rule as their home and
    their shells.
    """
    by_uid = {u.get("uid"): n for n, u in users.load()["users"].items()
              if u.get("uid")}
    owner = users.owner_name()
    out = {}
    for s in sessions:
        base = tmux_base(s["name"])
        if not base.startswith("claude-"):
            continue
        stem = base[len("claude-"):]
        who = by_uid.get(tmux_owner(s["name"]), owner)
        if who:
            out.setdefault(stem, []).append(who)
    return out


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


def claude_logins(rows):
    """Which Claude account each BuilderBot account is signed in as, read
    from the login Claude Code keeps in that account's home, and whether
    two of them share one. Anthropic's consumer terms allow one person per
    Claude account, so two BuilderBot accounts on one login is the thing
    the per-account homes exist to avoid — said on the row rather than
    left for somebody to work out."""
    out = []
    for u in rows:
        email = ""
        home = home_for(u.get("uid", "")) or os.environ.get("BUILDER_HOME", str(Path.home()))
        try:
            j = json.loads((Path(home) / ".claude.json").read_text())
            email = str(((j.get("oauthAccount") or {}).get("emailAddress")) or "")[:200]
        except (OSError, ValueError, AttributeError):
            email = ""
        out.append(u | {"claude": email})
    seen = {}
    for u in out:
        if u["claude"]:
            seen.setdefault(u["claude"], []).append(u["name"])
    for u in out:
        others = [n for n in seen.get(u["claude"], []) if n != u["name"]]
        u["claude_shared_with"] = others
    return out


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


def tmux_name(s):
    """What tmux will actually call a session asked for under this name.

    tmux rewrites `.` and `:` in a session name to `_` (they are its target
    syntax) and says nothing. A project called `example.com` therefore runs
    as `claude-example_com`, and every place that derives the session name
    from the project name — here, bb-tty, the page — has to make the same
    substitution, or the kill / keys / macro paths look for a session that
    was never called that.
    """
    return re.sub(r"[.:]", "_", s)


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
            if name.startswith("claude-"):
                state, task = claude_state(info.get("title", ""))
                row["claude"] = {"state": state, "task": task}
            rows.append(row)
    return rows


def node_tmux_sessions():
    """The sessions running on nodes (roadmap #24), shaped like this
    container's own so the Sessions card, the project rows and claude_with
    read them the same way — plus `node`, the name of the machine.

    NAMED BY THIS CONTAINER'S RULE. On a node every account is prefixed,
    the owner included; here the owner's sessions are the bare names, and
    everything on the page — the row's "is my session live", the labels,
    the kill dialog — is written against that. So the owner's node sessions
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


def last_stop():
    """Project -> transcript id, as recorded by the supervisor on its way down.

    Written by scripts/supervisor.sh on SIGTERM. Distinguishes "this project
    has an old transcript lying about" from "this conversation was open when
    the container stopped", which is the one worth offering to resume.
    """
    try:
        v = json.loads((STATE / "last-sessions.json").read_text())
        s = v.get("sessions")
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def last_claude(project_dir, name, stopped):
    """The most recent Claude transcript for a working directory, or None.

    Used to offer "resume" rather than silently starting a fresh conversation
    in a project that already had one — the tmux session dies with a container
    restart, but the transcript does not.
    """
    d = CLAUDE_PROJECTS / str(project_dir).replace("/", "-")
    try:
        files = [f for f in d.glob("*.jsonl") if f.is_file()]
    except OSError:
        return None
    if not files:
        return None
    newest = max(files, key=lambda f: f.stat().st_mtime)
    return {"id": newest.stem, "when": int(newest.stat().st_mtime),
            # True when this is the conversation that was actually open when
            # the container was stopped, not merely the last file touched.
            "was_open": stopped.get(name) == newest.stem}


def claude_launcher_path(project):
    """The script bb-tty writes to start this project's session.

    bb-tty owns the name and the directory; this mirrors them because the
    restart below runs that same file. Mirrored rather than shared for the
    reason tmux_name is mirrored in three places: one is bash, one is python,
    and the rule is short enough to state twice and check with a test.
    """
    home = Path(os.environ.get("BUILDER_HOME", str(Path.home())))
    d = os.environ.get("XDG_CACHE_HOME") or str(home / ".cache")
    return Path(d) / "builderbot" / f"claude-run-{project}.sh"


def respawn_claude(project):
    """Restart a project's Claude session onto the setting just saved.

    `tmux respawn-pane -k` replaces the pane's process and keeps the session,
    so the browser stays attached and nothing has to reload — where killing the
    session would leave a dead terminal in an iframe and a tab to repair. The
    launcher re-reads the preference when it runs, and `--respawn` tells it to
    resume the newest transcript, so the conversation continues on the new
    model rather than being replaced by a fresh one.

    What is lost is a turn in flight, which is why the dialog asks first.
    """
    session = tmux_name("claude-" + project)
    if session not in {s["name"] for s in tmux_sessions()}:
        return {"restarted": False, "why": "no session is running here"}
    launcher = claude_launcher_path(project)
    if not launcher.is_file():
        # Started by an image that predates the self-resolving launcher, or the
        # cache was cleared. Saying so beats killing the session to make a
        # point: the setting is saved and the next start will use it.
        return {"restarted": False,
                "why": "this session predates the restartable launcher — "
                       "it keeps its current model until you start a new one"}
    r = run(["tmux", "respawn-pane", "-k", "-t", session,
             str(launcher), "--respawn"], timeout=20)
    if r["code"] != 0:
        return {"restarted": False, "why": (r["out"] or "tmux refused").strip()[:200]}
    return {"restarted": True}


def github_url():
    """The org or repo a node's runner registers with: GITHUB_URL, and
    nothing else now that this container runs no runner of its own to read
    a registration back from. Empty when unset."""
    return os.environ.get("GITHUB_URL", "")


def mint_runner_token(kind):
    """A runner token for a node: the root-only helper via its one sudo
    rule, or a session-visible PAT."""
    r = run(["sudo", "-n", "/opt/builderbot/scripts/mint-runner-token", kind], timeout=60)
    if r["code"] == 0 and r["out"].strip():
        return {"token": r["out"].strip().splitlines()[-1]}
    pat, url = os.environ.get("GITHUB_PAT", ""), github_url()
    if pat and url:
        path = url.split("://", 1)[-1].split("/", 1)[-1].strip("/")
        scope = f"/repos/{path}" if "/" in path else f"/orgs/{path}"
        req = urllib.request.Request(
            f"https://api.github.com{scope}/actions/runners/{kind}-token",
            method="POST", headers={"Authorization": "Bearer " + pat,
                                    "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return {"token": json.load(resp).get("token", "")}
        except (OSError, ValueError) as e:
            return {"error": f"GitHub refused: {e}"}
    return {"error": "no runner credential here — GITHUB_PAT is not stashed on the controller"
                     + (f" ({r['out'].strip()[:120]})" if r["out"].strip() else "")}


def node_runners():
    """[{node, name, listening, busy, labels, url}] for every node whose
    census reports a runner, or that has been asked for one. Quiet nodes are
    included and marked: a runner nobody can hear from is a fact worth
    seeing, not a row to hide."""
    if NODES_OK or not nodes:
        return []
    out = []
    for n in nodes.node_list():
        if n["kind"] != "agent":
            continue
        rep = ((n.get("reported") or {}).get("services") or {}).get("actions-runner") or {}
        want = (n.get("services") or {}).get("actions-runner") or {}
        if not (rep.get("installed") or want.get("want")):
            continue
        out.append({"node": n["name"], "id": n["id"], "live": bool(n.get("live")),
                    "installed": bool(rep.get("installed")),
                    "listening": bool(rep.get("active")), "busy": bool(rep.get("busy")),
                    "name": rep.get("name") or "", "url": rep.get("url") or "",
                    "labels": rep.get("labels") or want.get("labels") or []})
    return out


def uptime():
    # PID 1 started when the container did, so its elapsed time is the
    # container's — /proc/uptime is the host's under a shared kernel.
    r = run(["ps", "-o", "etime=", "-p", "1"], timeout=10)
    return r["out"].strip() or "?"


def image_stamp():
    """Which build of the image this container is running.

    Baked in at the end of the Dockerfile by CI (see BB_IMAGE_REV there).
    Empty when the image was built any other way, which the page reports as
    `unstamped` rather than guessing — the whole point of this is that the
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


# ---------------------------------------------------------------------------
# bb doctor, cached. The checks take up to half a minute of network timeouts
# when something is down, which rules out running them on the 15-second poll —
# so a background thread keeps a cached verdict warm and the poll just carries
# it. The card's refresh button re-runs on demand for the "did my fix work"
# moment.
# ---------------------------------------------------------------------------
# Half an hour, a constant (R29): the card's own button re-runs it on demand,
# which is the control anybody actually reached for.
DOCTOR_EVERY = 1800

_doctor_lock = threading.Lock()
_doctor = {"when": 0, "checks": [], "failed": False, "running": True}

# bb doctor's own line shape: "  [ok]   claude on PATH". Indented lines that
# carry no tag are elaboration on the check above them (the ssh diagnosis
# hint, the GPU capability note) and travel with it as detail.
DOCTOR_LINE = re.compile(r"^\s*\[(ok|FAIL|skip|warn)\]\s+(.*\S)")


def run_doctor():
    """Run bb doctor and cache the parsed result. False if one is mid-run —
    two at once would double every network probe for the same answer."""
    with _doctor_lock:
        if _doctor.get("busy"):
            return False
        _doctor["busy"] = True
        _doctor["running"] = True
    r = run(["bb", "doctor"], timeout=180)
    checks = []
    for line in r["out"].splitlines():
        m = DOCTOR_LINE.match(line)
        if m:
            checks.append({"level": m.group(1), "text": m.group(2), "detail": ""})
        elif checks and line.strip() and not line.startswith("=="):
            checks[-1]["detail"] = (checks[-1]["detail"] + "\n" + line.strip()).strip()
    with _doctor_lock:
        _doctor.update(when=int(time.time()), checks=checks,
                       failed=r["code"] != 0, running=False, busy=False)
    return True


# Who this container is signed in as, for the Doctor card. `claude auth
# status --json` answers it locally and instantly — no network — so this is a
# short cache against a poll every fifteen seconds rather than a real one.
# Per HOME, because accounts have a home each and a Claude login lives in one
# (roadmap #26). One global answer meant a new account was shown the owner's
# sign-in state: the Claude button offered itself, and bb-tty — which reads
# the RIGHT home — then refused with "not signed in", which is a dead end on
# the one path a new person has to walk. Keyed by the home rather than the
# account so the owner and an unauthenticated context share one entry, which
# is what they are.
_auth = {}
_AUTH_EMPTY = {"at": 0.0, "state": {}}
_auth_lock = threading.Lock()
# Settable only so the suite can stop paying it: the fixture is rewritten
# behind this cache's back, so a test that changes who is signed in waits the
# full TTL for the page to agree. Nothing else sets it.
AUTH_TTL = int(os.environ.get("BB_AUTH_TTL") or 20)
# While a sign-in is open and this box is still signed out, the answer is about
# to change and is worth re-reading sooner. Not *every* poll, though: one check
# is a full node runtime — measured at 357MB and 0.68s — so bypassing the cache
# meant every status request spawning its own, several at once across a phone,
# a desktop and a preload. The dashboard stopped updating and the container ran
# out of memory, which is what "it freezes until I reload the page" was.
AUTH_TTL_FAST = 5


def claude_auth(fresh=False, home=""):
    """{signed_in, email} — or {"unknown": True} on a claude too old to ask.

    The one piece of container health that has an action attached, which is
    why it is a field of its own rather than a line in the doctor verdict: a
    verdict is read, and this is pressed.

    `home` is the asking account's, because the answer is theirs: the
    credential lives in $HOME/.claude and every account has a home.
    """
    got = _auth.get(home) or _AUTH_EMPTY
    # Signed in already: nothing a running sign-in does changes that answer,
    # so it keeps the long cache however busy the flow looks.
    ttl = AUTH_TTL_FAST if fresh and not got["state"].get("signed_in") else AUTH_TTL
    if time.monotonic() - got["at"] < ttl and got["state"]:
        return got["state"]
    # One at a time, and checked again on the way in: without this every
    # request that arrives during the 0.68s answer starts its own copy, which
    # is the difference between one node process and a handful.
    with _auth_lock:
        got = _auth.get(home) or _AUTH_EMPTY
        if time.monotonic() - got["at"] < ttl and got["state"]:
            return got["state"]
        return _read_auth(home)


def _read_auth(home=""):
    env = dict(os.environ) | ({"HOME": home} if home else {})
    r = run(["claude", "auth", "status", "--json"], timeout=20, env=env)
    try:
        d = json.loads(r["out"]) if r["code"] == 0 else {}
        state = {"signed_in": bool(d.get("loggedIn")),
                 "email": d.get("email") or "",
                 "plan": d.get("subscriptionType") or ""}
    except (ValueError, TypeError):
        # An older claude has no `auth` subcommand and says so on stderr. Not
        # knowing is not the same as being signed out, and offering to sign
        # somebody out of nothing is worse than offering nothing.
        state = {"unknown": True}
    _auth[home] = {"at": time.monotonic(), "state": state}
    return state


# What gets removed from a pasted code before it is handed to the flow:
# whitespace of every kind (a wrapped copy brings line breaks, a phone
# keyboard adds a trailing space), control characters, and the zero-width
# marks HTML copy buttons smuggle along. Everything printable stays. This is
# deliberately a strip-list and not an allow-list: two rounds of guessing the
# code's alphabet each refused a real code with advice to copy it again, to an
# operator who had copied it. The code is somebody else's credential format;
# judging it is the flow's job, and the flow says why in its own words.
CODE_JUNK = re.compile(r"[^!-~]+")


def doctor_payload():
    with _doctor_lock:
        return {k: _doctor[k] for k in ("when", "checks", "failed", "running")}


# ---- additional packages ---------------------------------------------------
# All of it — the catalog, the probes, the sizes, the versions and the worker
# that installs — lives in packages.py, which is handed the two helpers it
# needs and otherwise knows nothing about this file.
import packages                                                  # noqa: E402

packages.configure(run=run, write_json=write_json, state=STATE)

# ---- reaching a running Claude session -------------------------------------
# One door, one rule about Enter, used by both the to-do list and the memory
# book. See notify.py: it presses Enter only when the line it typed visibly
# arrived, which is the one thing a permission dialog will not do.
import notify                                                    # noqa: E402

notify.configure(run=run)

# ---- signing in ------------------------------------------------------------
# The flow runs under a pty this server holds, rather than in a terminal the
# operator has to work in. See signin.py for why every part of the terminal
# turned out to be somewhere it could go wrong.
import signin                                                    # noqa: E402

# ---- who may sign in --------------------------------------------------------
# The dashboard's own accounts (docs/users.md, roadmap #22). Imported here so
# that everything it needs — STATE, write_json — is already built; nothing in
# it reaches back. The FIRST account is made on the first-run screen — there
# is no environment variable behind it any more.
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


# ---- the test registry ------------------------------------------------------
# The notebook's sixth view: what each test protects, and what it costs. The
# timings are parsed out of a run the operator ingests — nothing here runs a
# suite, and nothing self-reports a duration.
import testreg                                                   # noqa: E402

testreg.configure(write_json=write_json, state=STATE)


# ---- the operator's house rules ---------------------------------------------
# The one thing in the notebook a session reads and cannot write. It rides in
# front of every session started here; claude_scope() in bb-tty denies the
# file tools on the file. Roadmap #7.
import rules                                                     # noqa: E402
import pending                                                   # noqa: E402
import settings                                                  # noqa: E402

rules.configure(write_json=write_json, state=STATE)
# The three stores above configure this one too; done here as well so the
# endpoint works even if none of them has been touched yet this process.
pending.configure(write_json=write_json, state=STATE)
# The Settings tab's own store (roadmap R29): what used to be fourteen
# environment variables. The builder home is where the commit identity lands.
settings.configure(write_json=write_json, state=STATE)


# ---- who else is in the notebook --------------------------------------------
# The other half of the same question, for a browser rather than a session
# (roadmap #26). Nothing to configure: it holds live seats in memory and
# reads no state, which is the whole of its design — see its header.
import presence                                                  # noqa: E402


# ---- the bug tracker --------------------------------------------------------
# The notebook's third view. Same arrangement again: its own file, handed the
# two helpers it needs, nothing reaching back.
import bugs                                                      # noqa: E402

bugs.configure(write_json=write_json, state=STATE, tell=notify.tell,
               tmux_name=tmux_name, workspace=WORKSPACE)

# The notebook's fourth view keeps a log too, and it is the odd one: nothing
# here writes findings, so the entries are derived by comparing one read of
# the report against the last.
import findings                                                  # noqa: E402

findings.configure(write_json=write_json, state=STATE)

# A phone on the end of wireless adb, and pushing an extension to it. Its own
# file for the usual reason; handed the workspace because what it can push is
# derived from the projects rather than browsed for.
import phone                                                     # noqa: E402

phone.configure(write_json=write_json, state=STATE, workspace=WORKSPACE)

# What a project has built, from its dist/ directory — the notebook's fifth
# view. The convention is the module's docstring; the scratch dir is where an
# .xpi is unpacked for web-ext, never dist/ itself.
import artifacts                                                 # noqa: E402
import workspace                                                 # noqa: E402

artifacts.configure(workspace=WORKSPACE)
workspace.configure(workspace=WORKSPACE, state=STATE)


def no_node_advice(name):
    """What a project with no node can still do, said the same way
    everywhere: a session reads and edits regardless — that is what this
    box is for — and building happens on a node or on GitHub."""
    return ("Pick one in the project's settings dialog"
            + (", or commit and let CI build it — this project can push."
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
# card. Same arrangement as packages above: its own file, handed what it needs.
import memory                                                    # noqa: E402

memory.configure(run=run, workspace=WORKSPACE,
                 claude_projects=CLAUDE_PROJECTS, tmux_name=tmux_name,
                 write_json=write_json, state=STATE)

# ---- the shared to-do list -------------------------------------------------
# The one surface both sides write: the operator adds an item, a session adds
# one and ticks it off. bb-tty puts the open items in front of every Claude
# session it starts, which is the whole reason it is worth having.
import todo                                                      # noqa: E402

todo.configure(write_json=write_json, state=STATE, tell=notify.tell,
               tmux_name=tmux_name, settle=notify.settle)

# ---- the standing model and effort -----------------------------------------
# One preference for every send, on its own card — see the module docstring
# for why it stopped being a question inside each send box.
import logs                                                      # noqa: E402
import idle                                                      # noqa: E402
logs.configure(state=STATE, write_json=write_json)
idle.configure(state=STATE, write_json=write_json,
               # A changed rule reaches every node on its next poll rather
               # than its next ten-minute hello.
               changed=lambda: [nodes.ask_hello(n["id"]) for n in nodes.node_list()
                                if n.get("kind") == "agent"])
# On boot, because that is when a generation was just rotated in and the oldest
# one fell off the end of the policy. Nothing else runs on a schedule here.
logs.prune()

import prefs                                                     # noqa: E402

prefs.configure(write_json=write_json, state=STATE)
# The old shape was one global pair. Moved onto each project here, once, with
# the project list this only has at runtime — so an install that had a standing
# preference keeps exactly it, per project, and can then diverge.
try:
    prefs.migrate([d.name for d in WORKSPACE.iterdir() if d.is_dir()])
except OSError:
    pass                    # no workspace to read: nothing to migrate onto

# ---- the dev instance ------------------------------------------------------
# A project's compose app, built and run on the sandbox VM's daemon. The
# module's docstring carries the security reasoning.
import devapp                                                    # noqa: E402
import nodes                                                     # noqa: E402

# The node data plane first, because devapp's job claim asks it which node
# work belongs to. Guarded: a database that will not open (a corrupt file, a
# full disk) must degrade to the dashboard this always was, not take down the
# page that is the operator's way to see what is wrong — nodes.py's readers
# and audit already no-op when it never came up.
try:
    nodes.configure(state=STATE)
    # The registry answers hello; the catalog is packages.py's. Joined here
    # rather than by one importing the other, which is the same seam every
    # other module pair uses.
    nodes.layout_of = packages.layout_for_node
    # ...and the digest of the bb bundle, so a node can tell from hello alone
    # whether the bb its sessions run is the one this controller ships.
    nodes.bundle_digest = lambda: workspace.bundle()["digest"]
    nodes.idle_minutes = idle.minutes
    NODES_OK = ""
except Exception as e:                                    # noqa: BLE001
    NODES_OK = str(e)
    print(f"[dashboard] node store unavailable: {e}", flush=True)

# The controller's own runner (docs/nodes.md §2, phase 4): the thread that
# takes compose and local exec jobs off the queue and runs them here. devapp
# registers its compose runner through configure(), so the queue is the seam
# between the two and neither imports the other.
import jobs                                                      # noqa: E402

if not NODES_OK:
    jobs.configure(nodes_module=nodes)
    packages.nodes = nodes
    phone.nodes = nodes            # every adb command is a job on a node
    # A compose action the AGENT ran still has records to write here; this is
    # where the module that queued it finishes it (roadmap #18).
    nodes.on_done("compose", devapp.compose_done)
devapp.configure(workspace=WORKSPACE, state=STATE, write_json=write_json,
                 log_dir=logs.log_dir,
                 node_for=nodes.node_for if not NODES_OK else None,
                 node_addr=nodes.ssh_addr_of if not NODES_OK else None,
                 queue=nodes if not NODES_OK else None,
                 runner=jobs if not NODES_OK else None,
                 project_node=lambda p: prefs.get(p)["node"],
                 node_paths=nodes.node_paths if not NODES_OK else None)

# ---- the version ----------------------------------------------------------
# One identity per project, rendered per target — the module's docstring says
# why one literal string cannot work. Handed the two notebook halves as well:
# the case for a bump is "what has happened since the target last moved", and
# only the roadmap's and the tracker's dated logs know that.
import changelog                                                 # noqa: E402
import version                                                   # noqa: E402

version.configure(workspace=WORKSPACE, state=STATE, write_json=write_json,
                  todo_mod=todo, bugs_mod=bugs, changelog_mod=changelog,
                  tell_fn=notify.tell, tmux_name_fn=tmux_name,
                  )

# ---- new project, and linking one ------------------------------------------
# Creating and cloning, and the worker that runs the ones that touch the
# network. The credential half stays here — agent_keys and the ssh aliases are
# this box's, not any one project's — and is handed over.
import projects                                                  # noqa: E402

def _seed_push_rights():
    """One-off: the projects that were already being pushed to keep pushing.

    Before this existed, whether a working copy could push was whatever its
    remote and the agent's keys happened to allow — and on this box that means
    every repo addressed over ssh through a deploy-key alias. Starting to
    refuse those would be taking away something that worked, to enforce a rule
    made afterwards, which is not what a new rule is for.

    So: absent the file, every project whose GitHub remote is an ssh one is
    granted, recorded as `key`, and the file exists from then on. https
    remotes are not seeded — those authenticated with the container-wide PAT,
    which is the arrangement being moved away from, and a token of their own
    is the way back to pushing.
    """
    if (STATE / "push-rights.json").exists() or not WORKSPACE.is_dir():
        return
    seeded = {}
    try:
        here = sorted(WORKSPACE.iterdir())
    except OSError:
        return
    for d in here:
        if not d.is_dir() or d.name == "_work" or d.name.startswith("."):
            continue
        remotes = run(["git", "-C", str(d), "remote", "-v"], timeout=10)["out"]
        if not remotes.strip() or not _github_remote(remotes):
            continue
        # ssh, in either spelling — an https remote is the PAT arrangement.
        if not any(l.split()[1].startswith(("git@", "ssh://"))
                   for l in remotes.splitlines() if len(l.split()) > 1):
            continue
        repo = projects.repo_of_remotes(remotes)
        if repo and repo not in {v["repo"] for v in seeded.values()}:
            seeded[d.name] = {"repo": repo, "how": "key", "at": int(time.time())}
    write_json(STATE / "push-rights.json", seeded)
    if seeded:
        print(f"[dashboard] push rights seeded for {len(seeded)} project(s) "
              f"already pushing over ssh", flush=True)


projects.configure(run=run, workspace=WORKSPACE, agent_keys=agent_keys,
                   gh_authed=gh_authed, ensure_deploy_alias=ensure_deploy_alias,
                   repo_path=repo_path, build_claude_md=build_claude_md,
                   project_name=PROJECT_NAME, github_url=GITHUB_URL,
                   state=STATE, home=os.environ.get("BUILDER_HOME", str(Path.home())),
                   write_json=write_json,
                   rename_project_data=devapp.rename_project_data)

_seed_push_rights()


# Written by entrypoint.sh once every startup hook has finished. Named here as
# well as in lib/common.sh, which is the cost of the marker crossing the
# bash/python line; the comment there carries the reasoning.
BOOT_READY_FILE = Path(os.environ.get("BOOT_READY_FILE", "/run/builderbot-ready"))
BOOT_WAIT = 180
BOOT_GRACE = 300


def wait_for_boot():
    """Hold until the container has finished starting, or give up.

    This dashboard is started BY hook 15 and the hooks after it are still
    running: 48-gpu-display.root.sh does not start Xorg for another few
    seconds. A `bb doctor` run inside that window does not report an early
    truth, it reports a falsehood — and DOCTOR_EVERY is half an hour, so it
    stuck. Measured on the 27 Aug 23:31 boot: doctor cached at +46s, Xorg up at
    +48s, and the card said the GPU had no display to render on until somebody
    pressed refresh. The operator's remedy for that message is to restart the
    container, which runs the same race again, so it read as the fault
    recurring rather than as a stale answer.

    It does not care whether the wait succeeded: a dashboard started outside the
    entrypoint — `bb dashboard dev`, the test harness, an image whose entrypoint
    predates the marker — has none coming, and checking anyway is the behavior
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

    Not /proc/uptime — under Docker that is the HOST's, four days here on a
    container three minutes old, so it answers a different question entirely.
    A /proc/<pid> directory carries the process's start time as its mtime.
    """
    try:
        return max(0.0, time.time() - os.path.getmtime("/proc/1"))
    except OSError:
        return float("inf")     # cannot tell: treat it as "not booting"


def client_gone(sock):
    """Whether the peer of a held request has closed: readable with nothing
    to read is EOF. Only a positive answer counts — an exception (a socket
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


def _doctor_loop():
    wait_for_boot()
    while True:
        run_doctor()
        time.sleep(DOCTOR_EVERY)


# How far behind the newest report a report may be and still be believed.
#
# A scanner that dies leaves its PREVIOUS report in place — a host script worth
# having does not overwrite a good report with nothing — so a dead scanner and
# a live one are the same file to everything downstream. On 28 Aug a trivy that
# had been crashing for four days was still supplying most of this box's
# findings, against a directory layout that had been changed in between: the
# operator fixed the scanner's volume, the numbers did not move, and the fix
# looked broken.
#
# A day, and the size is the argument. One scan run writes every report within
# minutes of itself, so anything measured in hours is the same run. Re-running
# ONE scanner by hand — the obvious thing to do after fixing one — leaves its
# siblings a few hours behind, and they must not vanish for it. A report left
# behind by a scanner that failed is behind by a whole cycle, which for any
# cadence anybody runs is more than this.
STALE_AFTER = 86400


def reports_ages():
    """Each report, when it was written, and whether it is too far behind."""
    out = []
    try:
        for f in sorted(REPORTS.glob("*.sarif")) + sorted(REPORTS.glob("*.sarif.json")):
            try:
                out.append({"name": f.name, "when": int(f.stat().st_mtime)})
            except OSError:
                pass
    except OSError:
        return []
    out.sort(key=lambda r: -r["when"])
    newest = out[0]["when"] if out else 0
    for r in out:
        r["behind"] = newest - r["when"]
        r["stale"] = r["behind"] >= STALE_AFTER
    return out


def stale_reports():
    """The names of the reports being left out, as a set."""
    return {r["name"] for r in reports_ages() if r["stale"]}


def reports_mtime():
    """Newest mtime among the scanner reports, so a client showing the
    findings tab can notice a re-run scan without anyone pressing reload."""
    try:
        files = list(REPORTS.glob("*.sarif")) + list(REPORTS.glob("*.sarif.json"))
        return max((int(f.stat().st_mtime) for f in files), default=0)
    except OSError:
        return 0


# The sidebar card wants per-project headline numbers without every client
# fetching and parsing the full reports, so the totals ride the status poll —
# cached on report mtime, because the SARIF can run to megabytes and the poll
# arrives every 15 seconds.
_findings_counts = {"mtime": -1, "projects": {}, "heads": [], "ok": False}


def findings_counts(ps):
    """{project: {level: count}} across every report, valid projects only —
    same rule as findings_payload. An unattributed path (the scanner saw a
    directory this workspace does not mount) counts under "", which the
    client labels rather than hiding — a finding with a bad path is still a
    finding. The cache holds the unfiltered counts: validity can change
    (a project locked, a permission fixed) without any report changing,
    so the filter runs per call and only the parse is cached."""
    # Keyed on the valid project names too: attribution matches path components
    # against them, so a project that appears — or stops being valid — between
    # scans would otherwise keep being counted the old way here while the
    # notebook's view, which parses fresh, files it correctly.
    known = {p["name"] for p in ps}
    valid = _valid_projects(ps)
    files = []
    if REPORTS.is_dir():
        files = sorted(REPORTS.glob("*.sarif")) + \
            sorted(REPORTS.glob("*.sarif.json"))
    # A report a whole cycle behind its siblings is not read. Its scanner
    # failed and the host left the previous file in place, so what it contains
    # describes a tree that has since moved — counting it does not make the
    # picture more complete, it makes it wrong, and quietly. Said on the card
    # rather than merely done: see reports_ages.
    dropped = stale_reports()
    files = [f for f in files if f.name not in dropped]
    # Nanosecond mtime plus size, per file: a report parsed mid-write and
    # finished within the same second must not stay cached as "no findings"
    # until the next scan.
    try:
        stamp = tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in files)
    except OSError:
        stamp = ()
    nonproject = nonproject_dirs(valid)
    key = (stamp, tuple(sorted(valid)), tuple(sorted(nonproject)),
           tuple(sorted(dropped)))
    if _findings_counts["mtime"] != key:
        per, rows_by, broken, good = {}, {}, False, 0
        # Where the unplaceable ones came from, counted by the head of their
        # path. A bare number on that row says something is wrong and nothing
        # about what: the honest answer for the nine left here is "mobsfscan
        # reports file:/src, its own container path", which is a fact about a
        # scanner's configuration and not about any project. Two components,
        # because one is usually a scheme and three is usually a filename.
        heads = {}
        for f in files:
            rep = parse_sarif(f, valid, nonproject)
            broken = broken or bool(rep.get("error"))
            good += 0 if rep.get("error") else 1
            for row in rep["findings"]:
                if row["project"] == IGNORED:
                    continue        # the SDK share et al: see _project_of
                lv = per.setdefault(row["project"] or "", {})
                lv[row["level"]] = lv.get(row["level"], 0) + 1
                rows_by.setdefault(row["project"] or "", []).append(row)
                if not row["project"]:
                    bits = [b for b in (row.get("path") or "").split("/") if b][:2]
                    head = "/".join(bits) or "(no path)"
                    heads[head] = heads.get(head, 0) + 1
        _findings_counts["heads"] = sorted(
            ({"head": k, "n": v} for k, v in heads.items()),
            key=lambda h: -h["n"])[:4]
        # Whether anything here is readable at all, counted while the parse is
        # in hand rather than paid for again: the Analysis surfaces ghost on
        # this, and re-reading every report to answer "is there a report" would
        # be the expensive half of the poll run for a disabled button. A report
        # that parses and holds no findings is readable — a clean scan is a
        # result, not an absence.
        _findings_counts["ok"] = good > 0
        # A report that failed to parse is not cached: half-written is the
        # usual reason, and the next poll should read it whole.
        _findings_counts.update(mtime=None if broken else key, projects=per)
        # The findings log, written here because here is where the report is
        # known to have *changed* — this block runs on a new mtime and not on
        # the reads in between.
        #
        # Not on a broken or missing report, which is the whole point of the
        # guard: a half-written file, or a reports directory that is not there
        # this minute, has nothing to say about what was fixed, and logging
        # every finding as gone off one would be the SARIF mistake this
        # project is careful about everywhere else.
        #
        # Coverage is assumed for every known project when a report does parse,
        # and that assumption is specific to this setup rather than general:
        # the scanners are pointed at the whole development share, so a project
        # in it was in scope of the run whether or not it produced a row. Point
        # them at one project and this would need to learn better.
        if files and not broken:
            for name in known:
                findings.seen(name, rows_by.get(name, []), covered=True)
    # No filter on the way out any more: nothing but a valid project (or the
    # empty key, which is an unattributed path) can be in there at all, and
    # the cache is keyed on the valid set so a change to it re-parses.
    return dict(_findings_counts["projects"])


def reports_ok():
    """Whether the Analysis surfaces have anything they can actually read.

    Three ways to have nothing: no /reports mount, nothing in it, or nothing in
    it that parses — and a control that is off wants one answer, not three. Read
    after findings_counts, which is what fills it.
    """
    return bool(REPORTS.is_dir() and _findings_counts["ok"])


def findings_heads():
    """Where the unplaceable findings came from, commonest first.

    Read after findings_counts, which is what fills it: the parse is cached and
    doing it twice to answer a subtitle would be the expensive half of the poll
    run for a line of text."""
    return list(_findings_counts["heads"])


# ---- revisions -------------------------------------------------------------
# One token per thing a view can depend on. A view says what it watches and is
# told when that moves; it never writes its own "should I re-read?" rule.
#
# Four bugs in one week came from every view inventing that rule out of
# knowledge it did not have — the roadmap's arrows not noticing a session
# start, the Artifacts tab not noticing a phone connect, and the phone view
# polling only when it ALREADY knew about a request, which meant it could
# never learn of the first one. Each was patched where it hurt. This is the
# shape that stops the fifth.
#
# Everything here must be cheap, because it is asked for every second or two.
# Files answer with their mtime; counters answer from memory. Nothing in this
# function runs git, lists tmux, or shells out — that is what makes it
# affordable to ask often, and it is the whole reason it is not snapshot().
def _mtime(path):
    try:
        return int(Path(path).stat().st_mtime_ns)
    except OSError:
        return 0


def revisions():
    names = [d.name for d in WORKSPACE.iterdir()
             if d.is_dir() and not d.name.startswith(".")] \
        if WORKSPACE.is_dir() else []
    revs = {
        # The container itself. A restart invalidates everything a page holds.
        "boot": boot_id(),
        # One file each, so any write through any path moves the token — the
        # CLI's included, which no in-process counter would catch.
        "todo": _mtime(STATE / "todos.json"),
        "bugs": _mtime(STATE / "bugs.json"),
        "findings": _mtime(STATE / "findings-log.json"),
        "reports": reports_mtime(),
        # In memory, free to read.
        "phone.asks": len(phone.requests_open()),
        "phone.dev": phone.device_rev(),
        "packages": packages.job_rev(),
        # Node and job data never joins the status payload (docs/nodes.md
        # §13): the views that show it watch this and fetch their own.
        "nodes": 0 if NODES_OK else nodes.rev(),
        "jobs": 0 if NODES_OK else nodes.jobs_rev(),
    }
    # Per project, for the views that are per project.
    for n in names:
        revs[f"dist:{n}"] = _mtime(WORKSPACE / n / "dist")
        # A session may bump while the operator has the tab open, and the
        # policy file moves when they change who may bump. Both are cheap
        # stats; neither shells out to git.
        revs[f"ver:{n}"] = _mtime(WORKSPACE / n / "VERSION")
        # The project's reflog: it moves on every commit, which is what the
        # dev row's "the code has moved since the last build" is derived
        # from. Without it that verdict only refreshed when something else
        # happened to move — a Rebuild button that wakes on the next poll
        # rather than the next time you happen to touch the tab. A stat, not
        # a git call.
        revs[f"git:{n}"] = _mtime(WORKSPACE / n / ".git" / "logs" / "HEAD")
    revs["vpolicy"] = _mtime(STATE / "versions.json")
    revs["prefs"] = _mtime(STATE / "claude-prefs.json")
    # The Settings tab's store (R29): a save has to reach the next poll, and
    # the payload is rebuilt only when something in this list moves.
    revs["settings"] = _mtime(STATE / "settings.json")
    # The dev-instance job and its files. In-memory counter plus mtimes — the
    # poll never spawns docker.
    revs["devapp"] = devapp.job_rev()
    return revs


# Who has polled lately, in memory: presence, not a record. See chat.online.
_polls = {}

# The last time each (project, account) was announced as starting a session,
# so a race between two requests in the same instant cannot say it twice. In
# memory because it is about this run of the container, and a restart having
# forgotten is right: the sessions went with it.
_announced = {}
ANNOUNCE_S = 60


def snapshot(who):
    if who and who.get("name") and users.uid_of(who):
        _polls[who["name"]] = time.time()
    ps = project_list(who)
    # Sessions this account has any business seeing: its own shells, and
    # anything on a project it was given. Filtered here for the same reason
    # the project list is (roadmap #22): a member restricted to one project
    # could otherwise read every other project's name off the session list,
    # which is exactly what hiding the projects was for. An account that sees
    # everything sees the unowned ones too — terminals opened before accounts,
    # or by something that is not a browser.
    mine, seen = users.uid_of(who), {p["name"] for p in ps}
    sessions = [s for s in tmux_sessions() + node_tmux_sessions()
                if _session_visible(s["name"], mine, seen, users.sees_all(who))]
    login = signin.state()
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
    return {
        "host": os.uname().nodename,
        "uptime": uptime(),
        # How many phone requests are waiting on the operator. A count and not
        # the requests themselves: this rides on every poll, and it exists so
        # the Phone tab knows when to go and fetch the real thing. Reading it
        # is a length() on a list in memory — no adb, nothing to pay for.
        "phone_asks": len(phone.requests_open(users.uid_of(who))),
        # What is pinned in the bell about nodes (an agent behind, or from
        # another window), computed here on every poll so an alert clears
        # the moment it stops being true — nothing is stored to dismiss.
        "attention": ([] if NODES_OK or users.may(who, "node") else nodes.attention(
            {p: (pr.get("node") or "") for p, pr in prefs.all_projects().items()}))
        # ...and a project whose CLAUDE.md block is from another window: red
        # like an agent out of window, since it stops the same thing, and
        # only for projects this account sees — ps is already that list.
        + [{"kind": "md", "project": p["name"], "from": p.get("md_window") or "?",
            "to": md_window(TEMPLATE_MD), "window": True}
           for p in ps if p.get("held") and p.get("md_window")
           and p["md_window"] != md_window(TEMPLATE_MD)],
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
        "boot": boot_id(),
        "image": image_stamp(),
        "projects": ps,
        "sessions": sessions,
        # Every node with a runner on it: the Runner card is a view of these
        # and nothing else, since CI left this container (phase 7). Read from
        # the census, which already carries it.
        "node_runners": node_runners(),
        "reports": REPORTS.is_dir(),
        "reports_mtime": reports_mtime(),
        "findings_counts": findings_counts(ps),
        # ...and, for the row they land on, what those paths actually look
        # like. Order matters: this reads what the call above computed.
        "findings_heads": findings_heads(),
        # ...and whether there is a readable report at all, which is what the
        # Static analysis button and the Analysis tab ghost on.
        "reports_ok": reports_ok(),
        # ...and when each report was written, so one left behind by a failed
        # scanner is visible rather than silently counted as current.
        "reports_ages": reports_ages(),
        "doctor": doctor_payload(),
        # Asked in this order: whether a sign-in is running decides whether
        # the answer to "signed in?" is worth re-reading rather than serving
        # from the cache.
        "claude_auth": claude_auth(fresh=login["running"],
                                   home=home_for(users.uid_of(who))),
        "signin": login,
        # A clone or a first push runs in the background now, so the card can
        # say what it is doing without the dialog being open.
        "project_job": projects.job(),
        "max_tabs": max_tabs(),
        # Everything the Settings tab edits, with where each value came from.
        "settings": settings.payload(),
        # The command list is built from the table above rather than spelled out
        # again in the page, so a command added here appears as a button and one
        # removed cannot leave a button that posts a name the server rejects.
        "macros": [{"name": k, "label": " ".join(v[1:])}
                   for k, v in MACROS.items() if k not in CARD_HIDDEN],
        # The Linux and git/GitHub cards, from their tables for the same
        # reason as macros above. `need` is what the button requires of the
        # active shell's directory; the page ghosts accordingly.
        "linux": [{"name": k, "label": v} for k, v in LINUX_MACROS.items()],
        "gitcmds": [{"name": k, "label": v, "need": "git"}
                    for k, v in GIT_MACROS.items()]
                   + [{"name": k, "label": v, "need": "github"}
                      for k, v in GH_MACROS.items()],
        "pinned": load_pins(),
        "custom": load_custom(),
        "cards": load_cards(),
        # The open tabs, so a phone picks up the desktop's layout rather than
        # starting from scratch. Carried in the status poll because it is small
        # and every client is already asking for that every 15s. THIS
        # account's — the strip follows the person to any browser they sign in
        # on, and stops following them to somebody else's (roadmap #25).
        "layout": load_layout(users.uid_of(who)),
        # Who this is, so the page can name a shell session the way bb-tty
        # will (index.html's myTmux). Not a secret — it is this account's own
        # id, and it is already the key to everything the page saves.
        "uid": users.uid_of(who),
        # What this account's shell sessions are named with — "" for the
        # owner, who keeps the bare names (users.tmux_prefix says why). The
        # page has to agree with bb-tty about this exactly, or a tab addresses
        # a session that was never created under that name.
        "tmux_prefix": users.tmux_prefix(who),
        # What this account may do, by capability rather than by role: the
        # page should never branch on "is this a user", because the answer to
        # "may I" is the thing that moves and the role is only how it is
        # decided today. Every one of these is refused again on the server —
        # this is what stops a dead control being drawn, not what stops the
        # action (roadmap #27).
        "can": {name: not users.may(who, name) for name in
                ("terminal", "docker-write", "packages-write", "git-auth", "admin")},
        # Projects whose Claude session belongs to somebody else, by NAME —
        # "alice has a session on this" is the whole value of the record, and
        # a bare refusal would tell you nothing you could act on. Only for
        # projects this account can see, and never their own, which is not
        # held against them (roadmap #26).
        # Who has a Claude session on each project — BuilderBot account names,
        # everybody including the asker. More than one may (roadmap #24), each
        # in a worktree of their own, so this is a list and it is information
        # rather than a refusal: the row says who is here and nothing is
        # greyed for it. The page decides how to word "you and alice".
        "claude_with": claude_sessions(sessions),
        # This account's own name, so the row can say "you and alice" rather
        # than reading your own name back at you.
        "me": (who or {}).get("name", ""),
        # Whether this account's commits would carry an author: the Claude
        # button ghosts on this, naming the Profile, before bb-tty refuses.
        "git_ready": users.git_ready(who) if users.uid_of(who) else True,
        # The chat panel's headline: who is here, and what has arrived since
        # this account last looked. The messages themselves are fetched when
        # the panel is open — this rides the poll because it is small and it
        # is what decides whether the button wears a dot.
        "chat": _chat_summary(who, ps),
        # This account's colour scheme, for a browser that has none stored.
        # index.html's adoptTheme says why localStorage still outranks it.
        "theme": users.prefs(who).get("theme", ""),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "builderbot-dashboard"

    def log_message(self, fmt, *args):      # quieter than the default
        pass

    def _who(self):
        """The account making this request, or None.

        Deliberately NOT remembered on the handler. BaseHTTPRequestHandler
        reuses one instance for the life of a connection, so a principal
        cached on `self` outlives the request that proved it — harmless while
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
            # Past half its life, the answer to this request carries a fresh
            # one (users.renewal): set here, sent by _json, so a session in
            # use never runs out. Reset per request — the handler instance
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

        `operator` was a placeholder from before there were accounts — true of
        every mutation because there was only ever one person who could make
        one. Now there can be several, and a log that calls them all the same
        thing is a log that answers no question worth asking.
        """
        u = self._who()
        return f"user:{u['name']}" if u else "anonymous"

    def _readonly(self, name):
        """True — with the 403 already written — when this account may see the
        project but has not taken it on.

        The counterpart to _refused for the handlers whose only check was "is
        this a project you can see". That was the whole authorization while
        seeing and working were the same question; they are not any more, so
        every write that names a project asks this too.
        """
        why = users.may(self._who(), "write", name)
        if not why:
            return False
        self._json({"error": why}, 403)
        return True

    def _refused(self, action, project=None):
        """True — with the 403 already written — when this account may not.

            if self._refused("rename", name):
                return

        Returns a BOOLEAN, and the name says so. The first version returned
        "the response" and read as `if (no := self._may(...)): return no`,
        which looks exactly like a guard and is not one: _json writes the
        reply and returns None, so the caller got its 403 while the handler
        carried on and did the thing anyway. The NODES suite caught it — a
        refused enrollment that left a node behind — because the assertion on
        the refusal itself passed perfectly. A guard that returns the thing it
        wrote is a guard that can be used wrongly, so it returns a bool.

        The project filter in project_list() does most of the authorizing;
        this is the rest — the verbs a `user` may not use on a project they DO
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
        401 — never a WWW-Authenticate challenge, which is what summons the
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

        An account that may change a node is shown the registry — that is what
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
        want = {prefs.get(p["name"])["node"] for p in project_list(me)}
        want.discard("")
        return want

    def _node_asked(self, nid):
        """Resolve and check a `?node=` for this account.

        Returns (node_id, error). An account with no restriction gets what it
        asked for, "" included, which is "the default node" and predates the
        picker. A restricted one must land on a node one of its own projects
        builds on — and when it named none, the first of those, because its
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
        return rows if scope is None else [n for n in rows if n["id"] in scope]

    def _term_refused(self, rest):
        """A sentence when this account may not have the terminal it is asking
        for, and "" when it may.

        Two rules, and they apply to different people.

        A Claude session is a write — the most write-shaped thing on the page
        — so it needs a project the account has actually taken on, whoever
        they are. An administrator is shown every project and works on the
        ones on their own list (users.may_work), so this is where that bites
        for them.

        And an account with no `terminal` right gets nothing else at all: not
        a shell, not somebody else's Claude, and not a project it cannot see.
        A read-only terminal pointed at another session is a way to WATCH one,
        which is the hole this closes rather than opens.
        """
        me = self._who()
        arg = _term_arg(rest)
        if arg.startswith("claude:"):
            return users.may(me, "claude", arg[len("claude:"):].split(":")[0])
        return users.may(me, "terminal")

    def _claude_held(self, rest):
        """A sentence when this account may not open the Claude session it is
        asking for, and "" when it may.

        More than one conversation per project is allowed now (roadmap #24) —
        each works in a tree of its own, so they cannot overwrite each other —
        and what is refused instead is a SECOND SESSION ON ONE ANTHROPIC
        ACCOUNT. Two dashboard accounts signed in to the same Anthropic login
        would share its limits and make whose-work-is-whose unanswerable, and
        the check is a real one rather than a guess: every account has its own
        home and its own ~/.claude, so the login in it says who it is.

        Enforced HERE and not only in the page, for the reason bb-tty's own
        header gives about the lock file: a rule only the UI honors is a
        suggestion, because the ttyd URL is reachable directly.
        """
        arg = _term_arg(rest)
        me = self._who()
        uid = users.uid_of(me)
        # No author, no terminal: every project is a repository, a commit
        # with no name and email behind it is one git refuses halfway through
        # the work, and a shell is where git is typed. bb-tty asks the same
        # question on the node, from the same answer (bb settings --json's
        # git_ready).
        if uid and (arg == "shell" or arg.startswith("sh:") or arg.startswith("claude:")) \
                and not users.git_ready(me):
            return (f"{me['name']} has no name and email for commits yet — set them "
                    "on your Profile (the gear in the header) and open this again")
        if not arg.startswith("claude:"):
            return ""
        project = arg[len("claude:"):].split(":")[0]
        if not uid or not project:
            return ""                     # not an account: nothing to scope
        # A session on a node is in THAT machine's tmux with that account's
        # login there, neither of which this container can see: the
        # announcement and the one-Anthropic-account rule are the node's
        # own to make (phase 10c gives its hooks the API for the first).
        if session_target(project)["where"] != "local":
            return ""
        # Announced to everybody sharing the project, ONCE. Three things make
        # one start look like several, and the first two were what put the
        # same line in the channel twice:
        #
        #   * ttyd's client asks for /term/token and then /term/ws, both
        #     carrying the same ?arg=, and BOTH arrive before bb-tty has made
        #     the session — so "does it exist yet" was false for each of them
        #     and the line landed twice, which is what a phone showed;
        #   * a dropped socket reconnects and a waking phone reloads the
        #     iframe. By then the session exists, which the check does catch.
        #
        # The window covers both without knowing anything about ttyd's URLs or
        # its headers — gating on the upgrade was the first fix and it cannot
        # be tested through fetch, which refuses to set Connection.
        mysess = users.tmux_prefix(me) + tmux_name(f"claude-{project}")
        fresh = mysess not in {x["name"] for x in tmux_sessions()}
        if fresh and time.time() - _announced.get((project, uid), 0) > ANNOUNCE_S:
            _announced[(project, uid)] = time.time()
            chat.event(project, uid,
                       f"{me['name']} started a Claude session on {project}")
        mine = claude_auth(home=home_for(uid)).get("email") or ""
        if not mine:
            return ""                     # not signed in: bb-tty says so, better
        if settings.get("claude_shared_login"):
            return ""                     # the Settings tab stood the refusal down
        store = users.load()["users"]
        by_uid = {u.get("uid"): n for n, u in store.items() if u.get("uid")}
        owner = users.owner_name()
        for s in tmux_sessions():
            if tmux_base(s["name"]) != tmux_name(f"claude-{project}"):
                continue
            other = tmux_owner(s["name"]) or users.uid_of(users.get(owner or ""))
            if not other or other == uid:
                continue                  # our own session: this is a reattach
            if (claude_auth(home=home_for(other)).get("email") or "") == mine:  # noqa: E501
                return (f"{by_uid.get(other, 'another account')} already has a "
                        f"Claude session on {project} signed in to {mine}. Two "
                        "sessions on one Anthropic account share its limits, "
                        "and nothing afterwards can say which of them did "
                        "what — so this one waits for that to end.")
        return ""

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
        suggestion — one edited URL and you are in somebody else's home with
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
                want = _ARG_OWNER.sub("", urllib.parse.unquote_plus(v))
                v = urllib.parse.quote(f"u:{uid}:{want}" if uid else want,
                                       safe="")
                out.append(f"{k}{eq}{v}")
                # Going to a NODE (roadmap #24), two more: the account's
                # name, since the node has no users.json to look one up in,
                # and a session token for the project, since only this
                # container's key can mint one. ttyd hands each ?arg= to
                # bb-tty as one more argument, and bb-tty takes them only
                # in the shapes it expects. The token is the same scoped
                # one the launcher would have minted here — one project,
                # user rights, an expiry — never the account's credential.
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
        loopback — websockets included.

        This is what makes one login cover the terminals: the browser only
        ever talks to this origin, so the session cookie (or basic auth)
        checked before this call is the whole story, and ttyd's own port
        stays unpublished. The /term prefix is stripped because ttyd's
        client asks for everything relative to the page, so the same relay
        serves an old image's ttyd (rooted at /, with its own credential —
        injected here, never from the browser) and the new loopback-only
        one alike.

        For a websocket the handshake is forwarded and then the two sockets
        are spliced until either side closes. The client sends nothing
        between its request and the 101, so the handler's buffered reader
        holds no stray bytes when the splice takes over the raw socket. A
        plain request instead gets Connection: close upstream, which turns
        "relay until EOF" into the complete response.
        """
        refused = self._term_refused(self.path[len("/term"):])
        if refused:
            return self._json({"error": refused}, 403)
        held = self._claude_held(self.path[len("/term"):])
        if held:
            # 409, not 403: nothing is wrong with the credential, the thing
            # asked for is taken. The name is the whole value of the record —
            # "somebody else has it" tells you nothing you can act on.
            return self._json({"error": held}, 409)
        # Where this terminal lives (roadmap #24, phase 10b): a project bound
        # to a node whose session half is up is relayed to THAT machine's
        # ttyd — the same two ports, the same bb-tty, with the account and
        # its token stamped into the URL — and everything else stays on the
        # loopback. session_target says why a node cannot take one, and the
        # row's button carries the same sentence.
        target = session_target(_arg_project(_term_arg(self.path[len("/term"):])))
        if target["where"] == "refused":
            return self._json({"error": target["why"]}, 503)
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
                return self._json({"error": f"{target['name']} did not answer on "
                                            f"{upstream[0]}:{upstream[1]} — its ttyd is "
                                            "reported up, but this container could not "
                                            "reach it. A firewall between the two?"}, 502)
            return self._json({"error": "the terminal server is not running"}, 502)
        # The connect timeout must not become a *relay* timeout: it stays on
        # the socket, and a sendall that blocks longer than it — a big paste
        # into a busy terminal, a slow reader — would raise and drop a live
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
        # at it — and with accounts, there is no longer one password to send.
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

    def _gzip(self, body):
        """The body, compressed when the client takes gzip and it pays.

        The page is ~150KB of inline everything and the status snapshot a
        phone polls every fifteen seconds is tens of KB of JSON — both shrink
        by roughly four fifths. Below ~1400 bytes (one MTU) the header
        shuffle costs more than it saves, so small answers go as they are.
        """
        if (len(body) >= 1400
                and "gzip" in self.headers.get("Accept-Encoding", "")):
            return gzip.compress(body, 6), True
        return body, False

    def _json(self, obj, code=200, cookie=None):
        body, zipped = self._gzip(json.dumps(obj).encode())
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        # A fresh session cookie, when the answer changed what the old one
        # was signed over — an account renaming itself.
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
        connection just closes, which the browser reports as a network error —
        the one failure mode that looks identical to the container being gone.
        """
        try:
            return fn()
        except Exception as e:                          # noqa: BLE001 — last resort
            try:
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            except OSError:
                pass                                    # client already left

    def do_GET(self):
        self._safely(self._get)

    def do_POST(self):
        self._safely(self._post)

    # The favicon set, generated by `bb favicon` from static/favicon.svg (the
    # header robot as a standalone file) and committed. An allow-list by full
    # path — the same shape as everything else the page can ask for — so this
    # never grows into a general file server by accident.
    FAVICONS = {
        "/favicon.ico": ("favicon.ico", "image/x-icon"),
        "/favicon.svg": ("favicon.svg", "image/svg+xml"),
        "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
    }

    def _get(self):
        path = self.path.split("?")[0]
        # Nobody owns this container yet: everything but the assets the card
        # itself needs is the first-run screen. Not a redirect from /login
        # alone — a bookmark, a phone reopening the app, and the WebUI link
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
        # file beside index.html (docs/nodes.md §13), and this allowlist is
        # how they are served — full paths, same shape as the favicons, so it
        # never grows into a general file server by accident.
        if path in ("/tab-nodes.js", "/tab-settings.js", "/tab-jobs.js",
                    "/tab-users.js", "/tab-phone.js", "/tab-profile.js"):
            try:
                body, zipped = self._gzip((HERE / path[1:]).read_bytes())
            except OSError:
                return self._json({"error": "not found"}, 404)
            self.send_response(200)
            self.send_header("Content-Type",
                             "text/javascript; charset=utf-8")
            if zipped:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if self.path.split("?")[0] in ("/", "/index.html"):
            body, zipped = self._gzip((HERE / "index.html").read_bytes())
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if zipped:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
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
        if self.path.startswith("/api/revs"):
            # Deliberately tiny and deliberately cheap: this is polled every
            # second or two, where /api/status is polled every fifteen because
            # it runs git for every project.
            return self._json(revisions())
        if self.path.startswith("/api/status"):
            return self._json(snapshot(self._who()))
        if self.path.startswith("/api/findings"):
            return self._json(findings_payload(self._who()))
        if self.path.startswith("/api/profile"):
            return self._profile()
        if self.path.startswith("/api/changelog"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            if name not in {p["name"] for p in project_list(self._who())}:
                return self._json({"error": "not a project"}, 400)
            d = version._sub(name, q.get("component", [""])[0])
            if d is None:
                return self._json({"error": "no such component"}, 400)
            return self._json({"text": changelog.read(d)})
        if self.path.startswith("/api/version"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            if name not in {p["name"] for p in project_list(self._who())}:
                return self._json({"error": "not a project"}, 400)
            return self._json(version.payload(name))
        if self.path.startswith("/api/artifacts"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            if name not in {p["name"] for p in project_list(self._who())}:
                return self._json({"error": "not a project"}, 400)
            # `devapp` is the main instance, which is what the row shows;
            # `devapps` is every instance, which the manager reads. Both, so
            # the row keeps working while the manager grows around it.
            return self._json({"artifacts": artifacts_of(name),
                               # What this project can and cannot do off this
                               # box, said on the tab that lists what it built.
                               "build": build_state(name),
                               "devapp": devapp.state(name),
                               "devapps": devapp.states(name)}
                              | phone.summary(prefs.get(name)["node"], users.uid_of(self._who()),
                                              nodes.node(prefs.get(name)["node"])
                                              if prefs.get(name)["node"] and not NODES_OK else None))
        if self.path.startswith("/api/artifact?"):
            # The download. Resolved and prefix-checked in artifacts.resolve —
            # a symlink inside dist/ must not turn this into a file server for
            # the whole box.
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            rel = q.get("path", [""])[0]
            if name not in {p["name"] for p in project_list(self._who())}:
                return self._json({"error": "not a project"}, 400)
            f = artifacts.resolve(name, rel)
            if f is None:
                return self._json({"error": "no such artifact"}, 404)
            try:
                data = f.read_bytes()
            except OSError as e:
                return self._json({"error": str(e)}, 500)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition",
                             f'attachment; filename="{f.name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return None
        if self.path.startswith("/logs/download"):
            # The container's own log, every project's traffic in it.
            if self._refused("admin"):
                return None
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            what = (q.get("what") or [""])[0]
            if what == "archive":
                data, err = logs.archive_bytes()
                if data is None:
                    return self._json({"error": err}, 500)
                fname, ctype = "builderbot-logs.tar.gz", "application/gzip"
            else:
                data = logs.session_bytes()
                fname, ctype = "builderbot-session.log", "text/plain; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Disposition",
                             f'attachment; filename="{fname}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return None
        if self.path.startswith("/api/phone"):
            # Not on the status poll: a probe is a job on a node, so the tab
            # asks when it is opened or pressed, and reads the cache between.
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            # A probe is a job on the named node, and a session's token is
            # bound to one project's node and no other (the same rule the
            # jobs endpoint keeps): a session reads the cache, an account
            # may ask the node.
            return self._json(self._phone_payload(node=(q.get("node") or [""])[0],
                                                  probe=bool(q.get("probe")) and not (self._who() or {}).get("session")))
        if self.path.startswith("/api/packages"):
            # ?node= asks about another node's packages store: what its
            # census says it has, and the package job in flight there. The
            # catalog is the same; the state is the node's (docs/nodes.md §6).
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            nid, why = self._node_asked(q.get("node", [""])[0])
            if why:
                return self._json({"error": why, "packages": []})
            if nid and nid != "local" and not NODES_OK:
                return self._json(packages.payload_for_node(nid))
            return self._json(packages.payload())
        if self.path.startswith("/api/users"):
            # The listing never carries a hash; all_users() drops it. Projects
            # come from the same filtered list everything else reads, so an
            # admin cannot hand out what they cannot see themselves.
            if self._refused("admin"):
                return None
            return self._json({
                "users": claude_logins(users.all_users()), "owner": users.owner_name(),
                "me": (self._who() or {}).get("name", ""),
                "roles": list(users.ROLES),
                "projects": [p["name"] for p in project_list(self._who())]})
        if self.path == "/api/v1/claude-login":
            return self._claude_login()
        if self.path.startswith("/api/v1/nodes"):
            # The versioned surface starts here (docs/nodes.md §3): new
            # endpoints land under /api/v1 with their shapes written down;
            # the legacy paths above migrate later, never both at once.
            if NODES_OK:
                return self._json({"error": "the node store did not open: "
                                            + NODES_OK}, 500)
            # The agent this controller ships rides beside the rows, once,
            # so a row can say when its node's agent is behind.
            #
            # Scoped for an account that may not change a node: it sees the
            # ones its own projects build on and no others, because the list
            # is otherwise a way to learn what machines exist and what they
            # are called (roadmap #27). An administrator sees the registry.
            return self._json({"nodes": self._nodes_for(nodes.node_list()),
                               "agent": nodes.agent_shipped()})
        if self.path.startswith("/api/v1/jobs"):
            # One job with its log so far (?id=), or the recent ones —
            # narrowed by ?node=, ?project=, ?type=, ?active=1, at most ?n=.
            # The Jobs tab's whole read surface, and a test's.
            if NODES_OK:
                return self._json({"error": "the node store did not open: "
                                            + NODES_OK}, 500)
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            jid = q.get("id", [""])[0]
            # A job and its log are the project's: an account reads the ones
            # on projects it may see, and a job with no project (a node's
            # own — an update, a store move) is an administrator's. Same
            # answer as a typo, so the listing says nothing about what else
            # is queued on the box.
            me = self._who()
            mine = None if users.may(me, "admin") == "" \
                else {p["name"] for p in project_list(me)}
            if jid:
                j = nodes.job(jid)
                if j and mine is not None and j.get("project") not in mine:
                    j = None
                return self._json(j if j else {"error": "no such job"},
                                  200 if j else 404)
            try:
                n = min(500, max(1, int(q.get("n", ["100"])[0])))
            except ValueError:
                n = 100
            rows = nodes.jobs_for(
                q.get("node", [""])[0] or None, n=n,
                project=q.get("project", [""])[0] or None,
                type=q.get("type", [""])[0] or None,
                active=q.get("active", [""])[0] == "1")
            if mine is not None:
                rows = [j for j in rows if j.get("project") in mine]
            return self._json({"jobs": rows,
                "nodes": {x["id"]: x["name"] for x in nodes.node_list(all=True)}})
        if self.path.startswith("/api/docker"):
            # Refresh is the retry: drop the memoised availability first, so a
            # daemon wired up thirty seconds ago is noticed by pressing the
            # button rather than by waiting for the memo to lapse.
            devapp.forget_available()
            # The manager's whole page in one answer: every instance bound to
            # the picked node, and every container on that node's daemon that
            # is not one of them. No node named means the default, which is
            # the arrangement that predates the picker.
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            nid, why = self._node_asked(q.get("node", [""])[0])
            if why:
                return self._json({"error": why, "blind": True,
                                   "instances": [], "containers": []})
            got = devapp.overview(nid or None)
            # An instance of a project this account was not given is one of
            # the projects hidden from it, wearing a different hat — and a
            # node is shared, so a restricted account asking about its own
            # node would otherwise read every other project's name off this
            # answer. The unowned containers go with them: they are somebody's
            # work too, and nothing here says whose.
            if self._node_scope() is not None:
                seen = {p["name"] for p in project_list(self._who())}
                got["instances"] = [i for i in got.get("instances") or []
                                    if i.get("project") in seen]
                got["containers"] = []
            return self._json(got)
        if self.path.startswith("/api/containers"):
            # A read, and the only one this dashboard makes of the daemon
            # beyond `docker version` — see the guard in devapp.py, which
            # allows it and still refuses anything that would change something.
            # Everything on the daemon, every project's: an administrator's.
            if self._refused("admin"):
                return None
            return self._json(devapp.containers())
        if self.path.startswith("/api/project-job"):
            if self._refused("create"):
                return None
            return self._json(projects.job())
        if self.path.startswith("/api/trash"):
            if self._refused("trash"):
                return None
            return self._trash_list()
        if self.path.startswith("/api/todo"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            if name not in {p["name"] for p in project_list(self._who())}:
                return self._json({"error": "not a project"}, 400)
            live = [s["name"] for s in tmux_sessions()]
            return self._json({"project": name} | self._todo_state(name, live))
        if self.path.startswith("/api/rules"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            if name not in {p["name"] for p in project_list(self._who())}:
                return self._json({"error": "not a project"}, 400)
            return self._json(rules.payload(name))
        if self.path.startswith("/api/pending"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            if name not in {p["name"] for p in project_list(self._who())}:
                return self._json({"error": "not a project"}, 400)
            return self._json(pending.payload(name))
        if self.path.startswith("/api/memory"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            # Against what this account may see, like every read above it —
            # this one passed the name straight through (bug #68).
            if q.get("project", [""])[0] not in {p["name"] for p in project_list(self._who())}:
                return self._json({"error": "not a project"}, 400)
            got = memory.payload(q.get("project", [""])[0],
                                 [s["name"] for s in tmux_sessions()],
                                 home=home_for(users.uid_of(self._who())))
            return self._json(got if got is not None
                              else {"error": "not a project"}, 400 if got is None else 200)
        if self.path.startswith("/api/tests"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            if name not in {p["name"] for p in project_list(self._who())}:
                return self._json({"error": f"not a project: {name}"}, 400)
            return self._json(testreg.payload(name))
        if self.path.startswith("/api/bugs"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            if name not in {p["name"] for p in project_list(self._who())}:
                return self._json({"error": f"not a project: {name}"}, 400)
            return self._json(bugs.payload(name))
        if self.path.startswith("/api/pubkeys"):
            # The shielded agent's public halves, for the New project dialog:
            # picking one selects it for the clone, and showing it is how the
            # operator gets it onto GitHub's deploy-key page in the first
            # place. Public keys are the shareable part — nothing here can
            # reach the private material, by construction. `pat` rides along
            # so the dialogs can say whether a deploy key is optional (a PAT
            # covers https) or the only way a push can authenticate. The
            # dialog is an administrator's, and so is this.
            if self._refused("create"):
                return None
            return self._json({"keys": agent_keys(), "pat": gh_authed()})
        self._json({"error": "not found"}, 404)

    def _read_json(self):
        """The body, once. Read here rather than in each handler: doing it
        after dispatch is how the request stream ends up consumed twice or
        not at all. None means an answer was already sent."""
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 <= n <= MAX_BODY:
                self._json({"error": "body too large"}, 413)
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
        # against yet — and closed by its own effect the moment there is.
        if self.path.split("?")[0] == "/setup":
            return self._setup_post()
        if self.path.split("?")[0] == "/login":
            return self._login_post()
        if self.path.split("?")[0].startswith("/api/v1/agent/"):
            # Its own door, before the operator's: an agent carries a node
            # token, never the dashboard credential (docs/nodes.md §8 — the
            # controller holds nothing that logs in anywhere, and a node
            # holds nothing that opens this page).
            return self._agent()
        if not self._authed():
            return self._deny()
        # The one body that is not JSON: an archive to start a project from,
        # streamed to the spool by projects.spool_archive. Its own door
        # before the JSON read, and its own cap — MAX_BODY is sized for a
        # form, and an upload is not read into memory at all.
        if self.path.split("?")[0] == "/api/upload-archive":
            return self._upload_archive()
        req = self._read_json()
        if req is None:
            return None

        path = self.path.split("?")[0]
        # Door 2, at the one funnel every mutation passes: when, who, what,
        # on what, with a parameter digest — never the parameters, which
        # carry tokens and env text. The principal is the signed-in account
        # (`user:<name>`), which is a string rather than a boolean precisely
        # so it could become one — OIDC later is a new way to fill it in, not
        # a new row shape. (Bug #16's caveat still applies, narrowed: anything
        # holding an account's credential writes as that account, because the
        # server cannot tell the person from the session they started.)
        if not NODES_OK:
            act = path + (":" + str(req["action"])[:40]
                          if isinstance(req.get("action"), str) else "")
            nodes.audit(self._principal(), act,
                        str(req.get("project") or req.get("name")
                            or req.get("id") or "")[:120], req)
        if path.startswith("/api/v1/nodes"):
            return self._nodes(req)
        if path.startswith("/api/v1/jobs"):
            return self._jobs(req)
        if path == "/api/v1/bb":
            return self._bb_relay(req)
        if path == "/api/v1/claude-login":
            return self._claude_login(req)
        if path == "/api/v1/hook":
            return self._hook(req)
        if path.startswith("/api/lock"):
            return self._lock(req)
        # NOT /api/pin, which is the command pin and has been since long before
        # this: startswith() means a route added above it silently takes every
        # path it prefixes, and both handlers were called _pin, so the later
        # definition quietly replaced the earlier one in the class body too.
        if path.startswith("/api/project-pin"):
            return self._project_pin(req)
        if path.startswith("/api/project-auth"):
            return self._project_auth(req)
        if path.startswith("/api/container"):
            return self._container(req)
        if path.startswith("/api/rename"):
            return self._rename(req)
        # These two before the bare prefix, or startswith swallows them.
        if path.startswith("/api/trash-restore"):
            return self._trash_restore(req)
        if path.startswith("/api/trash-purge"):
            return self._trash_purge(req)
        if path.startswith("/api/trash"):
            return self._trash(req)
        if path.startswith("/api/session"):
            return self._session(req)
        if path.startswith("/api/keys"):
            return self._keys(req)
        if path.startswith("/api/send"):
            return self._send(req)
        if path.startswith("/api/say"):
            return self._say(req)
        if path.startswith("/api/chat"):
            return self._chat(req)
        if path.startswith("/api/layout"):
            return self._layout(req)
        if path.startswith("/api/cards"):
            return self._cards(req)
        if path.startswith("/api/pin"):
            return self._pin(req)
        if path.startswith("/api/claude-md"):
            return self._claude_md(req)
        if path.startswith("/api/create"):
            return self._create(req)
        if path.startswith("/api/profile"):
            return self._profile(req)
        if path.startswith("/api/link"):
            return self._link(req)
        if path.startswith("/api/project-job"):
            return self._project_job(req)
        if path.startswith("/api/todo"):
            return self._todo(req)
        if path.startswith("/api/users"):
            return self._users(req)
        if path.startswith("/api/packages"):
            return self._packages(req)
        if path.startswith("/api/logs"):
            return self._logs(req)
        if path.startswith("/api/idle"):
            return self._idle(req)
        if path.startswith("/api/settings"):
            # The Settings tab's fields (R29): an administrator's, validated
            # and applied by the store; the answer is the tab's next drawing.
            if self._refused("admin"):
                return
            r = settings.set_many(req.get("set") or {})
            if r.get("error"):
                return self._json(r, 400)
            return self._json(r | settings.payload())
        if path.startswith("/api/rules"):
            return self._rules(req)
        if path.startswith("/api/pending"):
            return self._pending(req)
        if path.startswith("/api/memory"):
            return self._memory(req)
        if path.startswith("/api/prefs"):
            name = req.get("project", "")
            # A session may not change the settings of the project it runs
            # in — the gate that holds its own additions, the commands a
            # build runs, the identity its commits carry — and nobody may
            # change a project they cannot see or have not taken on.
            if (self._who() or {}).get("session"):
                return self._json({"error": "a project's settings are the operator's — "
                                            "say what should change in your reply"}, 403)
            if name not in {p["name"] for p in project_list(self._who())}:
                return self._json({"error": "not a project"}, 400)
            if self._readonly(name):
                return None
            # Everything else in this dialog is the project's own; the node is
            # not, because a node is shared and moving a project onto one
            # reaches every other project there.
            if ("node" in req or "dockernode" in req) \
                    and self._refused("node", name):
                return
            r = prefs.set_prefs(name, model=req.get("model"),
                                effort=req.get("effort"),
                                node=req.get("node") if "node" in req else req.get("dockernode"),
                                build=req.get("build"),
                                test=req.get("test"), outputs=req.get("outputs"),
                                gate=req.get("gate"),
                                workspace=WORKSPACE)
            # The restart is asked for by the dialog, which is where the
            # operator was told what it costs — never inferred here from the
            # change alone, because the same write happens when nothing is
            # running and there is nothing to interrupt.
            if not r.get("error") and req.get("restart"):
                r |= respawn_claude(name)
            return self._json(r, 400 if r.get("error") else 200)
        if path.startswith("/api/devapp"):
            return self._devapp(req)
        if path.startswith("/api/version"):
            return self._version(req)
        if path.startswith("/api/artifacts"):
            return self._artifacts(req)
        if path.startswith("/api/phone"):
            return self._phone(req)
        if path.startswith("/api/findings"):
            return self._findings_log(req)
        if path.startswith("/api/tests"):
            return self._tests(req)
        if path.startswith("/api/presence"):
            return self._presence(req)
        if path.startswith("/api/bugs"):
            return self._bugs(req)
        if path.startswith("/api/custom"):
            return self._custom(req)
        if path.startswith("/api/doctor"):
            return self._doctor(req)
        if path.startswith("/api/signout"):
            return self._signout(req)
        if path.startswith("/api/login-code"):
            return self._login_code(req)
        if path.startswith("/api/signin"):
            return self._signin(req)
        self._json({"error": "not found"}, 404)

    def _nodes(self, req):
        """The Nodes tab's verbs. Thin on purpose: nodes.py owns the rules
        and writes the audit rows; what belongs here is only the principal
        and the one probe that composes two modules (test)."""
        if self._refused("admin"):
            return
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        act = field(req, "action")
        nid = field(req, "id")
        if act == "add":
            r = nodes.node_add(self._principal(), field(req, "name"),
                               field(req, "addr"),
                               req.get("capabilities"),
                               field(req, "pool") or "default")
        elif act == "update":
            r = nodes.node_update(self._principal(), nid, req.get("fields") or {})
        elif act in ("drain", "online", "retire"):
            r = nodes.node_state(self._principal(), nid,
                                 {"drain": "draining", "online": "online",
                                  "retire": "retired"}[act])
        elif act == "enroll":
            r = nodes.enroll_mint(self._principal(), field(req, "name"),
                                  req.get("capabilities"),
                                  field(req, "user") or "bb")
        elif act == "revoke":
            r = nodes.node_revoke(self._principal(), nid)
        elif act == "config":
            # The configuration plane (docs/nodes.md §12): what the operator
            # wants the node to mount and be addressed as. Stored here,
            # applied by the next action as a system job the agent runs.
            r = nodes.node_config_set(self._principal(), nid, req.get("config"))
        elif act == "apply":
            r = nodes.node_apply(self._principal(), nid, field(req, "what"))
        elif act == "runner":
            # The Actions runner on a node (phase 7): a system job, with
            # the URL from the controller's environment unless one is typed.
            r = nodes.node_runner(self._principal(), nid, bool(req.get("want", True)),
                                  req.get("labels"),
                                  field(req, "url") or github_url())
        elif act == "paths":
            # What this container's paths are called on the node's machine
            # (docs/nodes.md §11): the mapping that was DOCKER_HOST_PATHS.
            r = nodes.node_paths_set(self._principal(), nid, field(req, "paths"))
        elif act == "check-paths":
            # Whether the two machines mean the same directory by the
            # projects share (roadmap #13): a marker made here, looked for
            # through the node's daemon. Off the poll, on purpose.
            r = ({"error": "no such node"} if not nodes.node(nid)
                 else devapp.check_paths(nid))
        elif act == "funnel":
            # Tailscale Funnel for a port on the node, raw: the manager's
            # route picker goes through the instance's record; this is the
            # same job by hand, for a port that is not an instance's.
            r = nodes.node_funnel(self._principal(), nid, req.get("port"), bool(req.get("on", True)))
        elif act == "update-agent":
            r = nodes.node_update_agent(self._principal(), nid)
        elif act == "cache-clear":
            # Drop a node's build caches — one project's, or all (docs/nodes.md
            # §6): a job the agent runs, so it is logged and audited like
            # everything else that touches a node's disk.
            n = nodes.node(nid)
            if not n or n["kind"] != "agent":
                return self._json({"error": "only an agent node keeps caches to clear"}, 400)
            r = nodes.job_add(self._principal(), {"node": nid}, "cache-clear",
                              {"project": field(req, "project")})
        elif act == "exec":
            # The channel's one job type, from the tab or from curl: run
            # this argv on that node, as the enrolled account, and read the
            # log back from /api/v1/jobs. What the Test button sends, and
            # what a session holding the credential could — the same reach
            # a session already has over ssh to the sandbox, audited now.
            argv = [str(a) for a in (req.get("argv") or []) if str(a)][:64]
            if not argv:
                return self._json({"error": "argv is empty"}, 400)
            spec = {"argv": argv, "timeout": 600}
            # What the job needs the node to be enrolled for. The node
            # checks it, not the row (door 7) — this is how that is exercised.
            need = [str(c) for c in (req.get("requires") or []) if str(c)][:8]
            if need:
                spec["requires"] = need
            # Placed on the node named, or — with `select` and no id — on
            # whichever node fits the selector when one asks (phase 4).
            place = ({"select": req["select"]} if not nid
                     and isinstance(req.get("select"), dict) else {"node": nid})
            r = nodes.job_add(self._principal(), place, "exec", spec, field(req, "project"))
        elif act == "test":
            n = nodes.node(nid)
            if not n:
                return self._json({"error": "no such node"}, 400)
            if n["kind"] == "local":
                return self._json({"on": False,
                                   "why": "the local node runs no daemon"})
            if n["kind"] == "agent":
                return self._json(self._agent_test(n))
            # The same verdict the Docker manager gates on, asked of THIS
            # node's daemon right now: drop the memo, probe, answer. The
            # sandbox-stamp check rides along, because a node that answers
            # docker but is not a sandbox is the case worth a button.
            devapp.forget_available()
            with devapp.on_node(nid):
                got = devapp.available_cached()
            nodes.audit(self._principal(), "node-test", nid,
                        {"on": got.get("on")})
            return self._json({"on": bool(got.get("on")),
                               "why": got.get("why") or ""})
        else:
            return self._json({"error": "unknown action"}, 400)
        return self._json(r, 400 if r.get("error") else 200)

    def _jobs(self, req):
        """The Jobs tab's one verb. A queued job is ended; a running one is
        flagged and its runner told, and the row moves when the runner
        reports that it stopped — which is when it did."""
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        act = field(req, "action")
        if act in ("run", "emu"):
            return self._json(*self._run_job(req))
        if act != "cancel":
            return self._json({"error": "unknown action"}, 400)
        r = jobs.cancel(self._principal(), field(req, "id"))
        return self._json(r, 400 if r.get("error") else 200)

    def _claude_login(self, req=None):
        """This account's Claude login, both directions (roadmap #24, bug
        #64): the credentials file from the account's home here, so the
        node's copy of that home is signed in the same — and, with a body,
        the node handing back a NEWER one.

        Only a session token minted FOR an account fetches it — the one the
        terminal proxy stamps into a node-bound terminal's URL — and only
        that account's: the account is in the token, signed, not in a
        parameter. A session on the node can read the same file out of its
        own home once it is there, so this hands it nothing it will not
        hold anyway. What it is not is a share: the credential goes to the
        one machine, into the one home, 0600, and only when that home is
        not signed in already (bb login decides that on the node).

        The file is the OAuth grant — a refresh token as well as the access
        token — and the refresh DOES rotate it: the operator ran sessions on
        a node for a day and came back to a controller that said it was
        signed out, because the node had refreshed and this copy still held
        a refresh token the server had retired (bug #64). Two machines
        cannot each keep a copy and expect both to work, so the copies are
        kept in step instead: whichever machine refreshes has the newer
        grant and puts it back here, and this container stays the one place
        that holds the account's current one.

        Newer means a later `expiresAt`, which is what a refresh moves. An
        older grant is refused rather than stored, so a node that has been
        offline for a week cannot undo a sign-in that happened while it was
        away, and the copy it replaces is kept beside it for one round —
        a bad write signs somebody out, and that file is the way back.
        """
        me = self._who()
        if not me:
            return self._json({"error": "not signed in"}, 401)
        uid = me.get("uid") if me.get("session") else ""
        if not uid:
            return self._json({"error": "a Claude login is fetched with a session token "
                                        "minted for an account — the one a node-bound "
                                        "terminal carries"}, 403)
        home = home_for(uid)
        if req is not None:
            return self._claude_login_put(req, home)
        path = Path(home) / ".claude" / ".credentials.json" if home else None
        if not path or not path.is_file():
            return self._json({"error": "this account is not signed in to Claude on the "
                                        "controller — the Doctor card's sign-in does that"}, 404)
        try:
            text = path.read_text()
            json.loads(text)
        except (OSError, ValueError):
            return self._json({"error": "the credentials file here could not be read"}, 500)
        return self._json({"credentials": text,
                           "email": claude_auth(home=home).get("email") or ""})

    @staticmethod
    def _grant_at(text):
        """When a grant stops being good, as the number a refresh moves.
        0 for anything that is not one, so a real grant always wins."""
        try:
            return int((json.loads(text).get("claudeAiOauth") or {}).get("expiresAt") or 0)
        except (ValueError, AttributeError, TypeError):
            return 0

    def _claude_login_put(self, req, home):
        """A node handing back the grant it refreshed."""
        if not home:
            return self._json({"error": "this account has no home here"}, 500)
        text = req.get("credentials")
        if not isinstance(text, str) or len(text) > 65536:
            return self._json({"error": "a credentials file is a JSON string"}, 400)
        mine = self._grant_at(text)
        if not mine:
            return self._json({"error": "that is not a Claude grant — no claudeAiOauth.expiresAt"}, 400)
        path = Path(home) / ".claude" / ".credentials.json"
        have = ""
        with contextlib.suppress(OSError):
            have = path.read_text()
        theirs = self._grant_at(have)
        if theirs and theirs >= mine:
            return self._json({"ok": True, "stored": False,
                               "why": "the grant here is the same or newer"})
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if have:
                # One round of history, because a bad write signs the
                # operator out and this is the way back.
                with contextlib.suppress(OSError):
                    (path.parent / ".credentials.json.prev").write_text(have)
                    os.chmod(path.parent / ".credentials.json.prev", 0o600)
            tmp = path.with_suffix(".json.new")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(text)
            os.replace(tmp, path)
        except OSError as e:
            return self._json({"error": f"could not store it: {e}"}, 500)
        print(f"[dashboard] claude login: a node handed back a newer grant for {home}",
              file=sys.stderr, flush=True)
        return self._json({"ok": True, "stored": True})

    def _hook(self, req):
        """What a session's hooks have to say, from a NODE (roadmap #24).

        bb-work-note and bb-prompt-relay write this container's /config
        when they run here — the overlap notes, the project's chat feed. On
        a node there is no /config, so they post the same four things to
        this endpoint with the session's token, and the same modules write
        them: `note` (a file the session is about to edit, with a guess at
        the symbol; answers who else has it open), `asked` (what the person
        typed, into the project feed), `started` (the session began,
        which _claude_held announces for a local session and cannot see
        for one on a node), and `seen` (what the notebook has done since
        this session was last told — the answer goes back into the turn the
        hook is already in, which is how a session stays current without
        anybody pressing a button, roadmap #27).

        The account is the token's, never the request's: a session token
        minted for a node-bound terminal names its account, and that is
        who the note is filed under and who the feed says asked.
        """
        me = self._who()
        if not me:
            return self._json({"error": "not signed in"}, 401)
        uid = me.get("uid") if me.get("session") else ""
        project = me.get("session") or ""
        if not uid or not project:
            return self._json({"error": "a hook posts with a session token minted for an "
                                        "account — the one a node-bound terminal carries"}, 403)
        kind = field(req, "kind")
        store = users.load()["users"]
        name = next((n for n, u in store.items() if u.get("uid") == uid), "") or uid
        if kind == "note":
            path = str(req.get("path") or "")[:400]
            if not path:
                return self._json({"error": "a note names a file"}, 400)
            others = overlap.others_touching(project, uid, path)
            overlap.note(project, uid, path, str(req.get("symbol") or "")[:120])
            by_uid = {u.get("uid"): n for n, u in store.items() if u.get("uid")}
            return self._json({"ok": True, "others": [by_uid.get(o, o) for o in others]})
        if kind == "asked":
            text = str(req.get("text") or "").strip()[:800]
            if not text:
                return self._json({"error": "nothing asked"}, 400)
            chat.post(project, uid, f"{name} asked: {text}", kind="asked")
            return self._json({"ok": True})
        if kind == "started":
            chat.event(project, uid, f"{name} started a Claude session on {project}"
                                     + (f" ({field(req, 'node')})" if field(req, "node") else ""))
            return self._json({"ok": True})
        if kind == "seen":
            # What this session has not been told about the notebook, and
            # marked told (roadmap #27). The answer rides back into the turn
            # the hook is already in, so nothing is spent on saying it.
            # ...and what the operator decided about anything it had waiting
            # for approval, which is the other half of #27.
            line = " ".join(x for x in (todo.catchup(project, uid),
                                        pending.settled_line(project)) if x)
            return self._json({"ok": True, "line": line})
        return self._json({"error": "a hook is note, asked, started or seen"}, 400)

    def _bb_relay(self, req):
        """A bb verb from a session on a NODE, run here (roadmap #24).

        The notebook, the settings, the registry and the version policy all
        live in this container's /config, and a node keeps none of it. So a
        session over there does not carry copies of the modules that read
        them: it sends the words — `roadmap add "..."`, `bug show 3`,
        `version --file` — with its own token, and this runs the same bb it
        would have run here, in the same tree (the projects share is mounted
        at /workspace on both sides, which is what makes `cwd` meaningful),
        and hands back what it printed. One implementation of every verb.

        WHAT THE TOKEN DECIDES. A session token stands for one project with
        user rights; the relay refuses a request naming another, and every
        verb runs with that project pinned into the environment, so `bb
        roadmap` cannot be pointed elsewhere by a working directory. A
        person's credential (an operator at a node's console) is held to the
        same rule the page holds them to: a project on their list.

        WHAT IT RUNS. Only the verbs bb itself relays (BB_RELAY_VERBS in
        scripts/bb) — the notebook, the settings, the registry, the version
        and changelog, the findings. Not `sdk`, `emu`, `run`, `build`: those
        answer for the machine the session is on, and relaying them would
        make a node's session act on this container, which is the very thing
        roadmap #24 exists to end. Not `users`, `dashboard`, `lint`: nothing
        that administers this box. The audit row at the top of POST records
        the argv with the principal, like every other mutation.
        """
        me = self._who()
        if not me:
            return self._json({"error": "not signed in"}, 401)
        argv = [str(a) for a in (req.get("argv") or []) if isinstance(a, (str, int))][:64]
        # git's network half runs under the account's author like everything
        # else it does with a repository: none set, none run.
        if argv and argv[0] == "git" and users.uid_of(me) and not users.git_ready(me):
            return self._json({"error": "no name and email for commits yet — set them on "
                                        "your Profile (the gear in the dashboard's header) first"}, 403)
        if not argv or argv[0] not in RELAY_VERBS:
            return self._json({"error": f"bb {argv[0] if argv else ''} is not relayed — "
                               "it answers for the machine the session is on"}, 400)
        project = field(req, "project") or me.get("session") or ""
        if me.get("session") and project != me["session"]:
            return self._json({"error": "this session's token is for another project"}, 403)
        if not project or (WORKSPACE / project).name != project \
                or not (WORKSPACE / project).is_dir():
            return self._json({"error": "not a project"}, 400)
        if self._refused("bb", project):
            return None
        # The tree the session is in: the project directory, or one of its
        # worktrees. Anything else — a path outside the share, a sibling
        # project — runs in the project directory instead of being trusted.
        cwd = WORKSPACE / project
        want = str(req.get("cwd") or "")
        if want.startswith("/"):
            real = Path(want).resolve()
            mine = (WORKSPACE / project).resolve()
            trees = (WORKSPACE / ".worktrees" / project).resolve()
            if real.is_dir() and (real == mine or mine in real.parents
                                  or trees in real.parents):
                cwd = real
        env = {k: v for k, v in os.environ.items() if k != "DASHBOARD_AUTH"}
        env.update({"BB_PROJECT": project, "BB_ROADMAP_PROJECT": project,
                    "BB_BUG_PROJECT": project, "BB_VERSION_PROJECT": project,
                    "DASHBOARD_STATE": str(STATE), "WORKSPACE": str(WORKSPACE),
                    "BB_TOKEN": users.mint_session(project), "BB_RELAYED": "1",
                    "BUILDERBOT_ROLE": "controller"})
        # Which seat the caller sits in, so a node's session is the same one
        # here: it is what says whether the roadmap has moved since that
        # session last read it, and whether a change was its own (#26, #27).
        # Only for a session token — a person at a node's console writes as a
        # person, and a person's writes are news to every session.
        if me.get("session") and me.get("uid"):
            env["BB_ACCOUNT_UID"] = me["uid"]
        else:
            env.pop("BB_ACCOUNT_UID", None)
        if field(req, "from") == "session":
            env["CLAUDECODE"] = "1"
        else:
            env.pop("CLAUDECODE", None)
        try:
            r = subprocess.run(["bash", str(HERE.parent / "bb"), *argv], cwd=str(cwd),
                               env=env, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            return self._json({"error": f"bb {argv[0]} took longer than three minutes",
                               "code": 124, "out": "", "err": ""}, 504)
        except OSError as e:
            return self._json({"error": str(e), "code": 1, "out": "", "err": ""}, 500)
        return self._json({"code": r.returncode, "out": r.stdout[-200000:],
                           "err": r.stderr[-20000:]})

    def _run_job(self, req):
        """`bb run`, `bb build` and `bb test` land here (docs/nodes.md §6):
        snapshot the project's working tree, dirty edits included, and queue
        an exec on the project's node — or on the node named. Outputs are
        globs; what matches comes back into dist/. The
        principal is the session when the request says so, which is a label
        the credential cannot prove (bug #16) but is worth writing down."""
        if NODES_OK:
            return {"error": "the node store did not open: " + NODES_OK}, 500
        name = field(req, "project")
        if name not in {p["name"] for p in project_list(self._who())}:
            return {"error": "not a project"}, 400
        argv = [str(a) for a in (req.get("argv") or []) if str(a)][:64]
        if not argv:
            return {"error": "argv is empty"}, 400
        # `emu` (docs/nodes.md phase 9): a bb verb the node runs from the
        # bundle with its own packages store as the SDK — no snapshot, since
        # the emulator is not the tree's; inputs come from dist/ by name and
        # what it writes comes back the same way.
        emu = field(req, "action") == "emu"
        pf = prefs.get(name)
        nid = field(req, "node") or pf["node"]
        # A session runs on its project's node and no other: naming one in
        # the request is how a token for one project would reach a machine
        # it was never bound to.
        if (self._who() or {}).get("session") and field(req, "node") \
                and field(req, "node") != pf["node"]:
            return {"error": "a session's jobs run on its project's node — "
                             "which node that is, is the operator's to change"}, 403
        if not nid:
            return {"error": f"{name} has no node, so nothing can be compiled for it. "
                             + no_node_advice(name)}, 400
        n = nodes.node(nid)
        if not n:
            return {"error": f"no such node: {nid}"}, 400
        if n["kind"] != "agent":
            return {"error": f"{n['name']} runs no agent — a build node is an agent "
                             "node with a workspace of its own (docs/nodes.md §6)"}, 400
        # A node that visibly cannot run this is refused before the job is
        # queued rather than after it fails on "gradlew: not found", and the
        # two ways out are named. Only fires when the command NAMES a
        # toolchain the node's census does not report; an unknown build
        # script is left alone.
        gap = nodes.toolchain_gap(nid, argv)
        if gap:
            # How old that answer is, because the census rides hello every
            # ten minutes and a refusal can be reasoning about the node as
            # it was nine of them ago. The node has just been asked for a
            # fresh one, so the sentence says a retry may differ.
            age = nodes.census_age(nid)
            when = (f" — as of what it reported {age // 60}m ago; it has been "
                    "asked for a fresh answer, so a retry shortly may differ"
                    if age and age > 90 else "")
            return {"error": f"{n['name']} has no {gap}{when}. Install it from the Tools tab "
                             f"with {n['name']} picked, "
                             + ("or push and let CI build it."
                                if projects.may_push(name)
                                else f"or give {name} push rights and let CI build it — "
                                     "it has none, so there is no fallback here.")}, 400
        outputs = [str(g)[:200] for g in (req.get("outputs") or []) if str(g)][:16]
        try:
            timeout = min(4 * 3600, max(30, int(req.get("timeout") or 3600)))
        except (TypeError, ValueError):
            timeout = 3600
        who = f"session:{name}" if field(req, "from") == "session" else self._principal()
        if emu:
            files, sizes = [], {}
            for f in (req.get("files") or [])[:8]:
                p = workspace.file_path(name, str(f))
                if p is None:
                    return {"error": f"{f} is not a file in {name}'s dist/"}, 400
                files.append(str(f))
                # So the node can tell its own copy from a new build without
                # fetching it again (docs/nodes.md §6, the artifacts store).
                sizes[str(f)] = p.stat().st_size
            spec = {"bb": argv, "files": files, "sizes": sizes, "timeout": timeout,
                    "outputs": outputs, "project": name}
            r = nodes.job_add(who, {"node": nid}, "exec", spec, name)
            if r.get("error"):
                return r, 400
            return r | {"node": nid}, 200
        snap = workspace.snapshot(name)
        if snap.get("error"):
            return snap, 400
        spec = {"argv": argv, "timeout": timeout, "outputs": outputs, "project": name}
        r = nodes.job_add(who, {"node": nid}, "exec", spec, name,
                          source={"digest": snap["digest"], "project": name,
                                  "files": snap["files"], "bytes": snap["bytes"]})
        if r.get("error"):
            return r, 400
        return r | {"node": nid, "snapshot": snap["digest"], "files": snap["files"]}, 200

    def _agent_test(self, n):
        """Test on an agent node: an exec job, waited for. The channel is
        the thing being tested, so the proof is a round trip through it —
        queued here, picked up by the next poll, run there, logged back —
        and a node that is not dialing in says so rather than timing out."""
        if not n.get("live"):
            return {"on": False, "why": ("waiting for enrollment"
                                         if n["state"] == "pending"
                                         else "not connected — the agent has "
                                         "not dialed in lately")}
        r = nodes.job_add(self._principal(), {"node": n["id"]}, "exec",
                          {"argv": ["uname", "-srm"], "timeout": 20})
        if r.get("error"):
            return {"on": False, "why": r["error"]}
        deadline = time.time() + 15
        while time.time() < deadline:
            j = nodes.job(r["job"])
            if j and j["state"] in nodes.JOB_END:
                out = (j.get("log") or "").strip()
                nodes.audit(self._principal(), "node-test", n["id"],
                            {"on": j["state"] == "succeeded"})
                return {"on": j["state"] == "succeeded",
                        "why": out or f"{j['state']} (exit {j['exit_code']})"}
            time.sleep(0.3)
        return {"on": False, "why": "the agent took the job but did not "
                                    "report back within 15s"}

    # The agent's verbs (docs/nodes.md §4). Four of the six land in phase 3
    # — enroll, hello, work, log, result — plus download, which is how a node
    # gets the agent in the first place and how self-update fetches the next
    # one. artifact and source are phase 6, when there is a workspace to ship
    # and an artifact store to land in.
    def _agent(self):
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        verb = self.path.split("?")[0][len("/api/v1/agent/"):]
        hdr = self.headers.get("Authorization", "")
        bearer = hdr[7:] if hdr.startswith("Bearer ") else ""
        auth = nodes.authenticate(bearer) if bearer else {"error": "no token"}
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        if verb == "download" and q.get("what", [""])[0] == "bundle":
            # bb, its library and the catalog, for a node installing a
            # toolchain into its own packages store (docs/nodes.md §6).
            if auth.get("error") or auth.get("kind") != "node":
                return self._json({"error": auth.get("error") or "a node's token"}, 401)
            b = workspace.bundle()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-tar")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Bundle-Digest", b["digest"])
            self.send_header("Content-Length", str(len(b["body"])))
            self.end_headers()
            self.wfile.write(b["body"])
            return None
        if verb == "source":
            # A job's workspace snapshot, by digest (docs/nodes.md §6). The
            # digest is the file name, so nothing else is reachable here.
            if auth.get("error") or auth.get("kind") != "node":
                return self._json({"error": auth.get("error") or "a node's token"}, 401)
            path = workspace.path_for(q.get("digest", [""])[0])
            if path is None:
                return self._json({"error": "no such snapshot — the tree has "
                                            "moved on; queue the job again"}, 404)
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/x-tar")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
            return None
        if verb == "file":
            # A job input from the project's dist/ — the APK an emulator
            # job installs (docs/nodes.md phase 9). Only the job's own node,
            # only while it runs, only dist/.
            if auth.get("error") or auth.get("kind") != "node":
                return self._json({"error": auth.get("error") or "a node's token"}, 401)
            j = nodes.job(q.get("job", [""])[0], with_log=False)
            if not j or j["node"] != auth["node"] or j["state"] not in nodes.JOB_ACTIVE:
                return self._json({"error": "not this node's running job"}, 403)
            path = workspace.file_path(j.get("project") or "", q.get("path", [""])[0])
            if path is None:
                return self._json({"error": "no such file in the project's dist/"}, 404)
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
            return None
        if verb == "artifact":
            # A file a job produced, raw in the body: into the project's
            # dist/ with its provenance beside it. Only the job's own node,
            # only while the job runs — a result already posted closes it.
            if auth.get("error") or auth.get("kind") != "node":
                return self._json({"error": auth.get("error") or "a node's token"}, 401)
            j = nodes.job(q.get("job", [""])[0], with_log=False)
            if not j or j["node"] != auth["node"]:
                return self._json({"error": "not this node's job"}, 403)
            if j["state"] not in nodes.JOB_ACTIVE:
                return self._json({"error": "the job has ended"}, 409)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            r = workspace.artifact_put(j, q.get("name", [""])[0], self.rfile, length)
            if not r.get("error"):
                nodes.audit(auth["principal"], "artifact", j["id"],
                            {"path": r["path"], "sha256": r["sha256"]})
            return self._json(r, 400 if r.get("error") else 200)
        if verb == "download":
            # The file itself. Any token gets it — the provisioner fetches
            # it with the enroll token before there is a node — and so does
            # the operator's own login, for reading it in a browser.
            if auth.get("error") and not self._authed():
                return self._json({"error": auth["error"]}, 401)
            f = nodes.agent_file()
            if not f["body"]:
                return self._json({"error": "this controller ships no agent"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "text/x-python; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Agent-Digest", f["digest"])
            self.send_header("Content-Length", str(len(f["body"])))
            self.end_headers()
            self.wfile.write(f["body"])
            return None
        if self.command != "POST":
            return self._json({"error": "POST"}, 405)
        req = self._read_json()
        if req is None:
            return None
        if auth.get("error"):
            return self._json({"error": auth["error"]}, 401)
        # Where the node is, as seen from here — informational on the row,
        # and the address docker-over-ssh goes to for an agent node (see
        # nodes._addr). A proxy in front says so in the usual header.
        addr = (self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or self.client_address[0])
        if verb == "enroll":
            if auth["kind"] != "enroll":
                return self._json({"error": "an enrollment token is needed "
                                            "here, not a node's"}, 403)
            r = nodes.enroll(auth, req.get("census"), addr,
                             field(req, "version"), field(req, "digest"),
                             field(req, "user"))
            return self._json(r, 400 if r.get("error") else 200)
        if auth["kind"] != "node":
            return self._json({"error": "an enrollment token enrolls, and "
                                        "nothing else"}, 403)
        nid = auth["node"]
        if verb == "runner-token":
            # A registration or removal token for the node's runner, minted
            # now from the root-only stash and never stored: the PAT stays
            # here, the hour-long token goes to the node that asked.
            kind = "remove" if field(req, "kind") == "remove" else "registration"
            r = mint_runner_token(kind)
            nodes.audit(auth["principal"], "runner-token", nid, {"kind": kind, "ok": not r.get("error")})
            return self._json(r, 400 if r.get("error") else 200)
        if verb == "hello":
            r = nodes.hello(nid, req.get("census"), addr,
                            field(req, "version"), field(req, "digest"),
                            req.get("running"))
        elif verb == "work":
            # The heartbeat and the long-poll in one: the sample is recorded
            # first, so a node that is only ever waiting still reads as
            # alive and its numbers still move; then the request is held.
            nodes.heartbeat(nid, req.get("sample"), addr, req.get("running"))
            try:
                wait = min(nodes.POLL_S, max(0.0, float(req.get("wait", nodes.POLL_S))))
            except (TypeError, ValueError):
                wait = nodes.POLL_S
            j = nodes.job_next(nid, wait, runner="node",
                               alive=lambda: not client_gone(self.connection))
            if j is None:
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            return self._json(j)
        elif verb == "log":
            r = nodes.job_log(nid, field(req, "job"), req.get("chunks"),
                              req.get("step"))
        elif verb == "result":
            r = nodes.job_result(nid, field(req, "job"), field(req, "state"),
                                 req.get("exit"), field(req, "error"),
                                 req.get("outputs"))
        else:
            return self._json({"error": "not found"}, 404)
        return self._json(r, 400 if r.get("error") else 200)

    def _signin(self, req):
        """Start a sign-in, or stop the one that is running."""
        _auth.clear()               # every home: the flow may have changed any
        if field(req, "action") == "cancel":
            return self._json(signin.cancel() | {"signin": signin.state()})
        # In the asking account's home: `claude auth login` writes to
        # $HOME/.claude, and this card is how a new account signs in to their
        # OWN Claude (roadmap #26).
        return self._json(signin.start(home_for(users.uid_of(self._who())))
                          | {"signin": signin.state()})

    def _login_code(self, req):
        """Hand the code from the browser to the sign-in flow.

        Transport, not judgment. The only property this end owes the pty is
        that a paste is one line of printable text — so the junk a copy brings
        along is stripped rather than refused, and whether what remains is a
        valid code is decided by the flow, whose refusal the card repeats in
        the flow's own words. Two shape checks in a row each turned out to
        refuse a real code (an allow-listed alphabet without base64's `+/=`,
        then the page's own authorize URL glued to the code by its Copy
        button); the only refusals left are the ones that cannot be wrong —
        nothing left to send, or far too much to be a code.
        """
        code = field(req, "code")
        # Anything from a URL onward was never part of the code. The page that
        # hands it out sets the authorize URL flush against it, so Copy takes
        # both. A code is base64url and a `#` — no colon, no slash — so the
        # cut cannot land inside a real one.
        code = re.split(r"https?://", code, 1)[0]
        code = CODE_JUNK.sub("", code)
        if not code:
            return self._json({"error": "no code in that paste — copy the "
                                        "code itself, not the page's link"}, 400)
        if len(code) > 2048:
            return self._json({"error": "that is far too long to be a code — "
                                        "copy just the code"}, 400)
        r = signin.submit(code)
        # Whatever the cache is holding is about to be wrong either way.
        _auth.clear()
        return self._json(r | {"signin": signin.state()},
                          400 if r.get("error") else 200)

    def _signout(self, req):
        """Sign this container out of Claude.

        The other half — signing in — is not here, because it cannot be: the
        flow wants a browser and a code pasted back, so the page opens a
        terminal for it. Signing out is one command with no conversation in
        it, so it is a button.
        """
        # Not while a conversation of THIS account's is running. Signing out
        # pulls the ground from under the sessions it started, and a page that
        # has not polled for fifteen seconds can offer a button the answer has
        # moved past — so the refusal is here as well as on the button.
        #
        # Theirs, not everyone's: logins are per account now (roadmap #26), so
        # one person signing out does nothing to somebody else's conversation
        # and refusing on it would be a rule with no reason behind it. An
        # account that sees everything still only owns what it opened.
        me = users.uid_of(self._who())
        # The name says whose (roadmap #24): a prefix is that account's, and
        # the bare one is the owner's.
        busy = sorted(n for n in (x["name"] for x in tmux_sessions())
                      if tmux_base(n).startswith("claude-")
                      and (tmux_owner(n) or users.uid_of(
                          users.get(users.owner_name() or ""))) == me)
        if busy:
            return self._json({"error": "end these first: " + ", ".join(busy)}, 409)
        # In the asking account's home, like the sign-in: signing out is
        # signing THIS account out, and the credential is in their ~/.claude.
        home = home_for(users.uid_of(self._who()))
        r = run(["claude", "auth", "logout"], timeout=60,
                env=dict(os.environ) | ({"HOME": home} if home else {}))
        _auth.clear()
        if r["code"] != 0:
            return self._json({"error": r["out"].strip()[-500:] or "logout failed"}, 500)
        return self._json({"ok": True,
                           "auth": claude_auth(home=home_for(users.uid_of(self._who())))})

    def _todo(self, req):
        """Add, send, edit or drop one item on a project's list.

        The project is checked against the real list for the same reason every
        other endpoint here does it: a name that came back off the filesystem
        cannot name something that was never there.
        """
        name = field(req, "project")
        if name not in {p["name"] for p in project_list(self._who())}:
            return self._json({"error": f"not a project: {name}"}, 400)
        # Seeing a project and being able to change it are different
        # questions now (users.may_work): an administrator is shown every
        # project and works on the ones they took on. The reads are named,
        # so an action added later is a write until somebody says otherwise.
        if field(req, "action") not in ("history",) and self._readonly(name):
            return None
        act = field(req, "action")
        # "send" is a write to the roadmap (it marks a step sent) and starts a
        # session's turn, so it goes with the rest.
        if (bad := locked_out(name)):
            return self._json(bad, 409)
        live = [s["name"] for s in tmux_sessions()]
        # What the caller believes it is replacing, for the verbs that
        # replace something (roadmap #26). A field's own words rather than a
        # version for the row: a session attaching details while the operator
        # rewords the same line is not a conflict. Absent from a client that
        # has not been taught to send it, which is then unchecked.
        was = req.get("was")
        # And who is writing, but only when a SESSION is: its own change must
        # not come back to it as news on its next prompt (#27's watermark),
        # while the operator's must, which is the whole point of that channel.
        # A browser's cookie names the same account and is deliberately not
        # credited.
        me = self._who() or {}
        who = me.get("uid", "") if me.get("session") else ""
        if act == "save":
            # The panel's one Save: settle the marker, say nothing. There used
            # to be a second action here that typed the change into a running
            # session, back when that was the only way anything reached one.
            # A session is told by itself now, on the next prompt it is given
            # (roadmap #27), so the panel has one button and this has one
            # action. `announce` is still live — the send path below carries
            # the same line on a message that was going anyway.
            todo.mark_told(name)
            return self._json({"ok": True} | self._todo_state(name, live))
        if act == "add":
            r = todo.add(name, field(req, "text"), steps=field_list(req, "steps"),
                         who=who)
        elif act == "send":
            r = todo.send(name, req.get("id"), req.get("step"), live,
                          also_told=todo.unsaved(name) if req.get("tell") else False,
                          note=field(req, "note"))
            if r.get("sent") and req.get("tell"):
                todo.mark_told(name)
        elif act == "edit":
            r = todo.edit(name, req.get("id"), field(req, "text"), req.get("step"),
                          was=was, who=who)
        elif act == "move":
            r = todo.move(name, req.get("id"), req.get("step"), req.get("dir"))
        elif act == "info":
            r = todo.set_info(name, req.get("id"), field(req, "text"),
                              step=req.get("step"), was=was, who=who)
        elif act == "add-step":
            r = todo.add_step(name, req.get("id"), field(req, "text"))
        elif act == "cross":
            r = todo.cross(name, req.get("id"), req.get("step"),
                           bool(req.get("on", True)))
        elif act == "remove":
            r = todo.remove(name, req.get("id"), req.get("step"),
                            why=field(req, "why"), was=was, who=who)
        elif act == "shelve":
            r = todo.shelve(name, req.get("id"), bool(req.get("on", True)))
        elif act == "history":
            # Fetched only when the panel is showing it. It rides in no poll:
            # a log nobody has opened is bytes on every status request for
            # every project, forever. Narrowed server-side for the same
            # reason: the panel asks for a window, not for everything.
            return self._json({"history": todo.history(
                name, limit=req.get("limit"), since=req.get("since"),
                find=field(req, "find"))})
        else:
            return self._json({"error": f"unknown action: {act}"}, 400)
        if r.get("error"):
            # A conflict answers 200. Not because it is a success — the write
            # was refused — but because the only client is this page, which
            # branches on `conflict` before `error`, and a 4xx here would put
            # "Failed to load resource" in the browser console for an outcome
            # the page handles. The suite holds every tab to zero console
            # errors, and that rule is worth more than the status code.
            # It answers with the item as it now stands so the panel can show
            # both, and with the fresh list so nothing else on screen is stale.
            if r.get("conflict"):
                return self._json(r | self._todo_state(name, live))
            return self._json(r, 400)
        return self._json(r | self._todo_state(name, live))

    def _todo_state(self, name, live):
        """What the panel needs after any change: the list, whether there is
        anywhere to send, and whether a session has been told about it yet."""
        session = todo.tmux_name("claude-" + name)
        return {"items": todo.items(name),
                # What the poll compares against, handed back with every read
                # AND every write — so this panel's own change never reads as
                # somebody else's on the next poll, and a change that lands
                # between opening the tab and the first poll is not missed
                # (roadmap #26).
                "rev": (todo.revisions().get(name) or {}).get("todo", 0),
                "session": session if session in set(live) else None,
                "unsaved": todo.unsaved(name),
                # A session part-way through a batch. The panel refuses to save
                # over one: the list on screen is a copy taken before the
                # session started, and replaying edits onto a list that has
                # moved underneath is how two people writing one file lose
                # each other's work.
                "batch": todo.batch(name)}

    def _phone_payload(self, node="", probe=False):
        """The tab's data for this account, plus this browser's own address
        when it is a phone.

        The whole point of the IP field is a number the operator has to go and
        read off the device — and when the dashboard is being viewed ON that
        device, the server already has it: the client address of this very
        request. Docker's bridge does not masquerade it, so what arrives is the
        real LAN address rather than the gateway's.

        Only offered for an Android client. From a desktop the client address
        is the desktop's, which is emphatically not the phone, and filling the
        field with it would be a confident wrong answer — the worst kind.
        """
        out = phone.payload(users.uid_of(self._who()), node=node, probe=probe)
        ua = self.headers.get("User-Agent", "")
        if "Android" in ua:
            try:
                ip = ipaddress.ip_address(self.client_address[0])
                if ip.is_private and not ip.is_loopback:
                    out["you"] = str(ip)
            except (ValueError, IndexError):
                pass
        return out

    def _container(self, req):
        """A container from a compose file written here, with no project.

        Its own endpoint rather than an action on _devapp, because _devapp
        starts by insisting the caller names a project and this one has none —
        that is the whole of what it is.
        """
        act = field(req, "action")
        name = field(req, "name")
        if act == "read":
            if name not in devapp.overview_names():
                return self._json({"error": f"no container {name}"}, 400)
            return self._json(devapp.read_container(name))
        if act == "save":
            if name not in devapp.overview_names():
                return self._json({"error": f"no container {name}"}, 400)
            r = devapp.update_container(name, req.get("compose") or "",
                                        req.get("env") or "")
            return self._json(r, 400 if r.get("error") else 200)
        if act != "create":
            return self._json({"error": f"unknown action: {act}"}, 400)
        # A name that is also a project would collide in the store, which is
        # keyed by one namespace for both kinds — and the collision is on the
        # SLUG, not the typing. `builderbot` is not the project `BuilderBot`
        # by string comparison and is exactly it by the time _pname has run:
        # same compose project name, same env file, same data directory, with
        # nothing anywhere saying the two had met.
        clash = next((p["name"] for p in project_list(self._who())
                      if devapp._slug(p["name"]) == devapp._slug(name)), "")
        if name and clash:
            return self._json({"error": f"that is the project {clash} — a "
                                        f"container written here needs a name "
                                        f"of its own"}, 400)
        r = devapp.create_container(name, req.get("compose") or "",
                                    req.get("env") or "", field(req, "node"))
        return self._json(r, 400 if r.get("error") else 200)

    def _logs(self, req):
        """The log policy, and the two things that can be done to the pile.

        Reading is a download rather than a view: these are megabytes of
        plain text, and a browser is better at saving one than this is at
        paginating it.
        """
        if self._refused("admin"):
            return
        act = field(req, "action")
        if act == "days":
            r = logs.set_days(req.get("days"))
            return self._json(r, 400 if r.get("error") else 200)
        if act == "clear":
            return self._json(logs.clear())
        return self._json({"error": f"unknown action: {act}"}, 400)

    def _idle(self, req):
        """The idle rule for Claude sessions (idle.py): minutes, 0 for never.
        Operator-only, like the log policy beside it."""
        if self._refused("admin"):
            return
        r = idle.set_minutes(req.get("minutes"))
        return self._json(r, 400 if r.get("error") else 200)

    def _devapp(self, req):
        """The dev-instance controls. Operator-only by construction — these
        buttons live on the panel, and a session's path to docker is the
        proxy's allowlist, not this endpoint."""
        name = field(req, "project")
        # A project, OR a container written here — which is not a project and
        # never will be, but carries every one of these controls. Checked
        # against the store rather than waved through: this name reaches a
        # compose call and a data directory either way.
        if name not in {p["name"] for p in project_list(self._who())} \
                and name not in devapp.overview_names():
            return self._json({"error": f"not a project or container: {name}"}, 400)
        act = field(req, "action")
        # Reading is everybody's; changing what is running is not (roadmap
        # #27). Named, not derived from the verb: an action that should be
        # restricted and is not on this list is a decision somebody has to
        # make, which is the same rule MACROS follows.
        #
        #   starter, state — reads: the project's .env.example, and the row.
        #   rebuild, abort — a user's own work, on purpose. Somebody given a
        #     project has to be able to build what they committed and look at
        #     it, or the project is read-only in the way that matters. Rebuild
        #     is build-then-down-then-up, so it is also how a stopped instance
        #     comes back, and the page already ghosts it until the code has
        #     actually moved. Abort follows it: whoever may start a build may
        #     stop one, or a mistake is somebody else's problem to clear.
        #
        # Everything else — new, remove, env, route — is configuration rather
        # than a run of the code, and stays an administrator's.
        if act not in ("starter", "state", "rebuild", "abort") \
                and self._refused("docker-write"):
            return None
        if act not in ("starter", "state") and name in {p["name"] for p
                                                        in project_list(self._who())} \
                and self._readonly(name):
            return None
        # Which instance of that project. Absent means the one every project
        # has always had, so a caller that predates instances still works and
        # a request that names a strange one is answered rather than obeyed:
        # the name decides a compose project and a data directory, and those
        # are not places to let an arbitrary string reach.
        inst = field(req, "instance") or devapp.MAIN
        # What the others sharing this project would want to know before they
        # press the same button. After `inst` is resolved, because the line
        # names it — the first version read it above and took every compose
        # action down with an UnboundLocalError. Reads and the env editor are
        # not news, so they are not on this list.
        if act in ("up", "down", "rebuild", "remove", "abort"):
            chat.event(name, users.uid_of(self._who()),
                       f"{self._principal()[len('user:'):]} ran {act} on "
                       f"{name}" + (f" ({inst})" if inst != devapp.MAIN else ""))
        # `new` is the one action whose instance does not exist yet — that is
        # what it is for. Everything else names one that must exist, because
        # the string decides a compose project and a data directory and is not
        # somewhere an arbitrary one should reach.
        if act == "abort":
            # Before the instance check below: a job can be running against an
            # instance that has since been removed, and stopping it must not
            # depend on the thing it is building still existing.
            return self._json({"ok": True, "stopped": devapp.abort_job(name, inst)})
        if act == "starter":
            # The project's .env.example, for a container that does not exist
            # yet — the send dialog opens on it so the env is filled in before
            # the first build rather than after it stops at the gate. Reads
            # nothing of the instance, which is the point: there is none.
            return self._json({"text": devapp.starter(name)})
        if act == "new":
            r = devapp.create_instance(name, inst, field(req, "node"))
            if not r.get("error") and isinstance(req.get("text"), str) \
                    and req["text"].strip():
                # Written before the build that follows, so the first one has
                # the env it needs instead of stopping at the gate and asking
                # for it afterwards.
                devapp.write_env(name, req["text"], r["instance"])
            return self._json(r, 400 if r.get("error") else 200)
        if inst not in devapp.instances(name):
            return self._json({"error": f"no instance {inst} of {name}"}, 400)
        if act == "remove":
            r = devapp.remove_instance(name, inst)
            return self._json(r, 400 if r.get("error") else 200)
        if act == "migrate-name":
            return self._json(devapp.migrate_name(name, inst))
        if act == "state":
            # The full picture for one instance — risks, problems, the parsed
            # compose — which overview() deliberately does not compute for
            # every instance at once. Asked when somebody is about to act.
            return self._json({"state": devapp.state(name, inst)})
        # `ack` is the digest of the risk list the operator was actually
        # shown — not a bare yes. A compose file that gains a mount between
        # the row rendering and the button being pressed does not inherit the
        # acknowledgement of the one before it.
        if act == "up":
            r = devapp.up(name, inst, field(req, "ack"))
        elif act == "down":
            r = devapp.down(name, inst)
        elif act == "rebuild":
            r = devapp.rebuild(name, inst, field(req, "ack"))
        elif act == "env-get":
            # An empty env opens on the example rather than on nothing. The
            # `missing` list still answers about what is STORED, so the hint
            # under the box stays true while the box is only a draft.
            stored = devapp.read_env(name, inst)
            return self._json({"text": stored or devapp.starter(name, inst),
                               "seeded": not stored,
                               "missing": devapp.missing_env(name, inst)})
        elif act == "env-set":
            r = devapp.write_env(name, req.get("text") or "", inst)
        elif act == "route":
            # How the instance is reached (docs/nodes.md §7): lan or funnel,
            # on which published port.
            r = devapp.route_set(name, inst, field(req, "mode"), req.get("port"))
        else:
            return self._json({"error": f"unknown action: {act}"}, 400)
        if r.get("error"):
            return self._json(r, 400)
        return self._json(r | {"state": devapp.state(name, inst)})

    def _version(self, req):
        """Move a project's version, or change who is allowed to.

        `by` is a ROLE here, not a name: version.may() compares it against
        "operator" to tell a person at the panel from a session, and this
        endpoint is only reachable from the panel. Passing the account name
        instead turned the operator into a session and a locked project
        refused its own bump — which is what version.mjs caught. Which PERSON
        it was belongs in the audit row, and is there.

        A session's bump goes through `bb version bump`, which asks the same
        policy and passes `by="claude"`.
        """
        name = field(req, "project")
        if name not in {p["name"] for p in project_list(self._who())}:
            return self._json({"error": f"not a project: {name}"}, 400)
        act = field(req, "action")
        if act == "bump":
            r = version.bump(name, field(req, "part"), by="operator", env=users.git_env(self._who()),
                             comp=field(req, "component") or "")
            if r.get("error"):
                return self._json(r, 400)
            return self._json(version.payload(name) | {"bumped": r})
        if act == "init":
            r = version.init(name, field(req, "value"), by="operator", env=users.git_env(self._who()),
                             comp=field(req, "component") or "")
            if r.get("error"):
                return self._json(r, 400)
            return self._json(version.payload(name) | {"created": r})
        if act == "unbump":
            r = version.unbump(name, by="operator", env=users.git_env(self._who()),
                               comp=field(req, "component") or "")
            if r.get("error"):
                return self._json(r, 400)
            return self._json(version.payload(name) | {"unbumped": r})
        if act == "ask":
            # Put to the project's own session rather than answered here: it
            # can read the code and be argued with, and neither is true of a
            # function counting commits.
            live = [x["name"] for x in tmux_sessions()]
            r = version.ask(name, live, comp=field(req, "component") or "")
            return self._json(r, 400 if r.get("error") else 200)
        if act == "policy":
            r = version.set_policy(name, field(req, "policy"))
            if r.get("error"):
                return self._json(r, 400)
            return self._json(version.payload(name))
        return self._json({"error": f"unknown action: {act}"}, 400)

    def _artifacts(self, req):
        """Push an .xpi from a project's dist/ to the paired phone, or stop
        one. The path is resolved against dist/ and unpacked before anything
        runs — push_dir never sees a caller-supplied path."""
        name = field(req, "project")
        if name not in {p["name"] for p in project_list(self._who())}:
            return self._json({"error": f"not a project: {name}"}, 400)
        # Seeing a project and being able to change it are different
        # questions now (users.may_work): an administrator is shown every
        # project and works on the ones they took on. The reads are named,
        # so an action added later is a write until somebody says otherwise.
        if self._readonly(name):
            return None
        act = field(req, "action")
        nid = prefs.get(name)["node"]
        node = nodes.node(nid) if nid and not NODES_OK else None
        who = self._who() or {}
        uid, me = users.uid_of(who), who.get("name") or "somebody"
        # Both verbs touch the phone, so both are the connection owner's:
        # the phone is on somebody's desk, and they are the one who said
        # yes to it. The tab ghosts the buttons for anybody else; this is
        # the line that holds.
        if act in ("push", "install"):
            if not node:
                return self._json({"error": f"{name} has no node, and a phone is "
                                            "driven from the project's node"}, 400)
            if not phone.phone_on(nid):
                return self._json({"error": f"no phone is connected on {node['name']} — "
                                            "connect one on the Phone tab with that "
                                            "node picked"}, 400)
            held = phone.owner_of(nid)
            if held and held["uid"] != uid:
                return self._json({"error": f"the phone on {node['name']} was connected "
                                            f"by {held['name']} — only they can push to "
                                            "it or install on it"}, 400)
            if not held:
                return self._json({"error": f"the phone on {node['name']} has no owner — "
                                            "connect it on the Phone tab first"}, 400)
        if act == "push":
            # A temporary add-on, through web-ext on the phone's node. A push
            # is a decision, made each time — nothing auto-pushes on a change.
            rel = field(req, "path")
            f = artifacts.resolve(name, rel)
            if f is None or f.suffix.lower() != ".xpi":
                return self._json({"error": "not an .xpi in this project's dist/"}, 400)
            r = phone.push(nid, node, rel, f.stat().st_size, name, field(req, "apk"),
                           uid, me, by=self._principal())
        elif act == "install":
            # An APK, installed for real and kept — unlike the extension push,
            # which is a temporary add-on. `adb install -r` replaces an
            # existing copy in place and keeps its data, so this is the update
            # path too and there is no second verb.
            rel = field(req, "path")
            f = artifacts.resolve(name, rel)
            if f is None or f.suffix.lower() not in (".apk",):
                return self._json({"error": "not an .apk in this project's "
                                            "dist/"}, 400)
            r = phone.install_apk(nid, {"stores": (node.get("reported") or {}).get("stores") or {}},
                                  rel, f.stat().st_size, name, label=rel,
                                  by=self._principal())
        elif act == "stop":
            r = phone.stop_push(uid, by=self._principal())
        else:
            return self._json({"error": f"unknown action: {act}"}, 400)
        if r.get("error"):
            return self._json(r, 400)
        return self._json(r | {"artifacts": artifacts_of(name)}
                          | phone.summary(nid, uid, node))

    def _phone(self, req):
        """Pair, connect, and push an extension. Every argument is checked by
        phone.py against something already known — a discovered extension, an
        attached device, a Firefox that is actually installed — rather than
        taken as given: this is one of the few places the page causes a program
        to run."""
        # NOT one gate for the whole endpoint. `ask` is what a session does
        # (bb phone run --why ...) and `outcome` is it reading the answer;
        # the control on those is that the operator sees the reason and
        # decides, one command at a time. Pairing, connecting and deciding
        # are the operator's, and a session may not reach them.
        if field(req, "action") not in ("ask", "outcome") and self._refused("admin"):
            return None
        act = field(req, "action")
        who = self._who() or {}
        uid, me = users.uid_of(who), who.get("name") or "somebody"
        nid = field(req, "node")
        if act in ("pair", "connect", "disconnect"):
            if NODES_OK or not nid or not nodes.node(nid):
                return self._json({"error": "pick a node — a phone is driven from "
                                            "a node that has adb"}, 400)
            if not nodes.node(nid).get("live"):
                return self._json({"error": f"{nodes.node(nid)['name']} is not dialing "
                                            "in — nothing reaches its adb right now"}, 400)
        if act == "pair":
            r = phone.pair(nid, field(req, "ip"), field(req, "port"), field(req, "code"), uid, me)
        elif act == "connect":
            r = phone.connect(nid, field(req, "ip"), field(req, "port") or None, uid, me)
        elif act == "disconnect":
            r = phone.disconnect(nid, uid, me)
        elif act == "ask":
            # A session asking to reach the phone on its project's node. It
            # runs nothing itself; the account that connected that phone is
            # asked, and on Allow the node runs it. The project is the
            # session's own; a person asking through the API names one they
            # may see.
            proj = who.get("session") or field(req, "project")
            if proj and not who.get("session") and not users.may_see(who, proj):
                proj = ""
            pnid = prefs.get(proj)["node"] if proj else ""
            pn = nodes.node(pnid) if pnid and not NODES_OK else None
            r = phone.ask(field(req, "why"), req.get("cmd"), pnid if pn else "",
                          pn["name"] if pn else "", proj)
        elif act == "allow" or act == "deny":
            r = phone.decide(req.get("id"), act == "allow", uid, me)
        elif act == "outcome":
            r = phone.outcome(req.get("id"), project=who.get("session") or "")
            if not r.get("error"):
                return self._json(r)
        else:
            return self._json({"error": f"unknown action: {act}"}, 400)
        if r.get("error"):
            return self._json(r, 400)
        return self._json(r | self._phone_payload(node=nid, probe=act in ("connect", "disconnect", "pair")))

    def _findings_log(self, req):
        """The Analysis view's log. Read-only by nature: the scan runs on the
        host and nothing here can write a finding, so `history` is the only
        action there is — the entries are made by findings_counts noticing the
        report changed."""
        name = field(req, "project")
        if name not in {p["name"] for p in project_list(self._who())}:
            return self._json({"error": f"not a project: {name}"}, 400)
        if field(req, "action") != "history":
            return self._json({"error": "the findings log is read-only"}, 400)
        return self._json({"history": findings.history(
            name, limit=req.get("limit"), since=req.get("since"),
            find=field(req, "find"))})

    def _rules(self, req):
        """The operator's house rules for one project — the whole list, saved.

        Whole rather than per-rule because the tab is an editor rather than a
        form: somebody rewords two rules and drops a third before pressing
        Save, and replaying that as five operations is five chances to land
        half of it. The memories beside them are staged the same way and for
        the same reason.

        A SESSION IS REFUSED HERE, by name. `bb rules` having no write verb
        and the file tools being denied on the file cover what a session would
        do in the ordinary course of work; they do not cover a session with a
        shell and its own token, which authenticates as a principal with user
        rights over exactly this project — so without this the endpoint would
        have been the way around the whole arrangement. The only writer is a
        person signed in to this dashboard with the project on their list.
        """
        name = field(req, "project")
        if name not in {p["name"] for p in project_list(self._who())}:
            return self._json({"error": f"not a project: {name}"}, 400)
        if self._refused("rules", name) or self._readonly(name):
            return None
        if (bad := locked_out(name)):
            return self._json(bad, 409)
        if field(req, "action") != "save":
            return self._json({"error": "unknown action"}, 400)
        r = rules.replace(name, req.get("rules") or [])
        if r.get("error"):
            return self._json(r, 400)
        return self._json(rules.payload(name))

    def _pending(self, req):
        """Approve or deny what a session has waiting (roadmap #27).

        The operator's, by name: a session's own token is refused here the
        way it is for the rules, because a session approving its own
        additions is the setting not existing. The reply carries what each
        record became — approved, failed with the store's own reason, or
        skipped because its parent is still waiting — and the queue as it
        now stands, so the modal redraws from one answer.
        """
        name = field(req, "project")
        if name not in {p["name"] for p in project_list(self._who())}:
            return self._json({"error": f"not a project: {name}"}, 400)
        if self._refused("pending", name) or self._readonly(name):
            return None
        act = field(req, "action")
        ids_ = req.get("ids") if isinstance(req.get("ids"), list) else []
        if act == "approve":
            r = pending.approve(name, ids_)
        elif act == "deny":
            r = pending.deny(name, ids_)
        else:
            return self._json({"error": "action is approve or deny"}, 400)
        return self._json(r | pending.payload(name))

    def _tests(self, req):
        """The hand-written half of the registry, and ingesting a run.

        Describing a test is a write-through edit of one row, like the bug
        tracker's fields — there is nothing to stage, because what is being
        written is a sentence about a thing that already exists.

        Ingesting is NOT here, and that is not an omission. It was, and it
        could never have worked: every body this server takes is capped at
        MAX_BODY, 64kB, and a full run log is a couple of hundred — so the
        action existed and returned "body too large" for the only input it was
        for. `bb tests ingest` does it in process, on the machine whose /config
        this is, which is where reading a runner's output belongs anyway.
        """
        name = field(req, "project")
        if name not in {p["name"] for p in project_list(self._who())}:
            return self._json({"error": f"not a project: {name}"}, 400)
        if self._readonly(name):
            return None
        if (bad := locked_out(name)):
            return self._json(bad, 409)
        act = field(req, "action")
        if act == "describe":
            r = testreg.describe(name, field(req, "key"),
                                 protects=req.get("protects"),
                                 notes=req.get("notes"))
        elif act == "accept":
            r = testreg.accept(name, field(req, "key"), field(req, "why"))
        else:
            return self._json({"error": f"unknown action: {act}"}, 400)
        if r.get("error"):
            return self._json(r, 400)
        return self._json(r | testreg.payload(name))

    def _presence(self, req):
        """This browser is in a project's notebook — who else is (roadmap #26).

        A heartbeat, ridden on the panel's own poll, answered with the others
        in the same breath so that asking and being told cost one request
        rather than two. `leave` is the same call saying the tab has gone,
        which a seat would work out for itself in fifty seconds; sending it
        is what stops the panel claiming somebody is here who has just closed
        the window.

        Names, not accounts: the answer is read by a person, and a uid on
        screen is a question rather than an answer. Resolved here for the same
        reason the hook endpoint does it — the module holds ids and knows
        nothing about who they are.
        """
        me = self._who()
        if not me:
            return self._json({"error": "not signed in"}, 401)
        name = field(req, "project")
        if name not in {p["name"] for p in project_list(me)}:
            return self._json({"error": f"not a project: {name}"}, 400)
        uid = me.get("uid") or ""
        client = str(req.get("client") or "")[:64]
        if req.get("leave"):
            presence.gone(name, uid, client)
            return self._json({"ok": True, "here": []})
        others = presence.mark(name, uid, client, field(req, "where"))
        by_uid = {u.get("uid"): n for n, u in users.load()["users"].items()
                  if u.get("uid")}
        return self._json({
            "ok": True,
            "here": [{"who": by_uid.get(o["uid"], "somebody"),
                      "mine": o["uid"] == uid,
                      "where": o["where"], "at": o["at"]} for o in others],
            # ...and when a SESSION here last read the roadmap, which is the
            # other half of "is anybody else in this". Being told is #27's
            # channel and arrives on the session's next prompt; this is the
            # act of going and reading, which is what the operator is
            # actually asking about after changing something.
            "read": max(todo.readers(name).values(), default=0)})

    def _bugs(self, req):
        """Report, edit, or close one bug. The fields go through bugs.py's own
        cleaner; this only picks the action and answers with the fresh list,
        so the tab never has to guess what the write left behind."""
        name = field(req, "project")
        if name not in {p["name"] for p in project_list(self._who())}:
            return self._json({"error": f"not a project: {name}"}, 400)
        # Seeing a project and being able to change it are different
        # questions now (users.may_work): an administrator is shown every
        # project and works on the ones they took on. The reads are named,
        # so an action added later is a write until somebody says otherwise.
        if field(req, "action") not in ("history",) and self._readonly(name):
            return None
        act = field(req, "action")
        if (bad := locked_out(name)):
            return self._json(bad, 409)
        fields = {k: field(req, k) for k in ("title", "area", "repro",
                                             "expected", "actual", "notes")}
        if act == "add":
            r = bugs.add(name, fields.pop("title"),
                         severity=field(req, "severity", "medium"), **fields)
        elif act == "edit":
            r = bugs.edit(name, req.get("id"), rev=req.get("rev"),
                          severity=field(req, "severity", "medium"), **fields)
        elif act == "status":
            r = bugs.set_status(name, req.get("id"), field(req, "status"),
                                note=field(req, "note"))
        elif act == "remove":
            r = bugs.remove(name, req.get("id"), why=field(req, "why"))
        elif act == "send":
            r = bugs.send(name, req.get("id"),
                          [s["name"] for s in tmux_sessions()],
                          note=field(req, "note"))
            if r.get("error"):
                return self._json(r, 400)
            # The send's own answer rides along with the fresh list: whether
            # the line landed is the whole question, and the tab has to be
            # able to say so rather than quietly redrawing as if it had.
            return self._json(r | bugs.payload(name))
        elif act == "history":
            return self._json({"history": bugs.history(
                name, limit=req.get("limit"), since=req.get("since"),
                find=field(req, "find"))})
        else:
            return self._json({"error": f"unknown action: {act}"}, 400)
        if r.get("error"):
            # Somebody else edited this report first: answered with what it
            # now says and the fresh tracker, so the tab can offer the choice
            # rather than only refusing (roadmap #26). 200 for the same
            # reason as _todo above.
            if r.get("conflict"):
                return self._json(r | bugs.payload(name))
            return self._json(r, 400)
        return self._json(bugs.payload(name))

    def _memory(self, req):
        """Edit, delete, or point a running session at this project's memories.

        Every path here is memory.py's; this only picks which one. The project
        and file names go through untouched because that module is the thing
        that checks them against what is on disk — doing it in two places is
        how the two answers drift apart.
        """
        act = field(req, "action")
        proj, file = field(req, "project"), field(req, "file")
        if (bad := locked_out(proj)):
            return self._json(bad, 409)
        # Seeing a project and being able to change it are different
        # questions now (users.may_work): an administrator is shown every
        # project and works on the ones they took on. The reads are named,
        # so an action added later is a write until somebody says otherwise.
        if act != "history" and self._readonly(proj):
            return None
        # Whose memories: the reader's own home, never the owner's (B67) —
        # a session's are the account's that started it.
        home = home_for(users.uid_of(self._who()))
        if act == "save":
            r = memory.save(proj, file, field(req, "text"), rev=field(req, "rev"), home=home)
        elif act == "index":
            r = memory.save_index(proj, [e for e in (req.get("lines") or [])
                                         if isinstance(e, dict)],
                                  rev=field(req, "rev"), home=home)
        elif act == "create":
            r = memory.create(proj, field(req, "name"), field(req, "title"),
                              field(req, "hook"), field(req, "type"),
                              field(req, "body"), home=home)
        elif act == "delete":
            r = memory.delete(proj, file, home=home)
        elif act == "history":
            return self._json({"history": memory.history(
                proj, limit=req.get("limit"), since=req.get("since"),
                find=field(req, "find"))})
        else:
            return self._json({"error": f"unknown action: {act}"}, 400)
        # One Save for the project, not one per thing in the panel: a memory
        # edit marks the same flag the list does, and the one button spends the
        # one line telling a session about all of it.
        if not r.get("error") and act in ("save", "index", "create", "delete"):
            todo.mark_unsaved(proj, "memory")
        # A conflict answers 200 — see _todo. The whole file as it now stands
        # rides back in it, which is what lets the editor show both versions
        # instead of just losing the typing.
        return self._json(r, 400 if r.get("error") and not r.get("conflict") else 200)

    def _custom(self, req):
        """Save or delete one of the operator's own command lists.

        Ids are minted here rather than accepted from the page, so the file
        cannot grow a key that came from a request, and every stored macro is
        addressable by something this server chose.
        """
        # They run in terminals, so they are edited by accounts that may have
        # one — a command list a shell-less account could write and an
        # administrator would run is a shell by proxy.
        if self._refused("terminal"):
            return None
        action = req.get("action")
        with _state_lock:                   # read, edit, write — one at a time
            return self._custom_edit(req, action)

    def _custom_edit(self, req, action):
        macros = load_custom()
        if action == "delete":
            mid = req.get("id")
            macros = [m for m in macros if m["id"] != mid]
        elif action == "save":
            title = (req.get("title") or "").strip()[:CUSTOM_TITLE_MAX]
            lines = clean_lines(req.get("body"))
            if not title:
                return self._json({"error": "a title is required"}, 400)
            if not lines:
                return self._json({"error": "no commands to run"}, 400)
            mid = req.get("id")
            if mid and any(m["id"] == mid for m in macros):
                macros = [{"id": m["id"], "title": title, "lines": lines}
                          if m["id"] == mid else m for m in macros]
            else:
                if len(macros) >= CUSTOM_MAX:
                    return self._json({"error": f"at most {CUSTOM_MAX} custom commands"}, 400)
                used = {int(m["id"][1:]) for m in macros}
                mid = "c" + str(max(used, default=0) + 1)
                macros.append({"id": mid, "title": title, "lines": lines})
        else:
            return self._json({"error": "unknown action"}, 400)
        try:
            save_custom(macros)
        except OSError as e:
            return self._json({"error": f"could not save: {e}"}, 500)
        return self._json({"custom": load_custom()})

    def _create(self, req):
        """New project — a fresh local repo, or a clone. See projects.py."""
        # An administrator's, for two reasons that both matter: a project this
        # account made would not be in the list it was given, so it would be
        # created and then invisible; and the clone dialog is one of the two
        # places a git token is stored (roadmap #27).
        if self._refused("create"):
            return None
        body, code = projects.create(req)
        # Pinned on arrival, once anything has ever been pinned. Without this a
        # project made while a pins file exists is absent from it, so it lands
        # on disk and never reaches the sidebar — created, and apparently gone.
        # No file still means "all of them", so there is nothing to write then
        # and writing one would turn the first create into an unasked-for
        # decision about every other project.
        if code == 200 and body.get("name") and load_project_pins() is not None:
            with _state_lock:
                pins = load_project_pins()
                if pins is not None:
                    try:
                        save_project_pins(set(pins) | {body["name"]})
                    except OSError:
                        pass          # the project exists; the sidebar is not
                                      # worth failing the create over
        return self._json(body, code)

    def _profile(self, req=None):
        """The signed-in account's own settings (the Profile tab): read on
        GET, saved on POST. Anybody signed in — this is about themselves —
        which is why it is not behind the admin gate the Users tab wears.
        """
        me = self._who()
        if not me or not users.uid_of(me):
            return self._json({"error": "not an account"}, 403)
        if req is None:
            rec = users.get(me["name"]) or {}
            return self._json({"name": me["name"], "uid": users.uid_of(me),
                               "role": rec.get("role", "user"),
                               "profile": users.profile(me),
                               "git": users.git_identity(me),
                               "git_ready": users.git_ready(me),
                               "claude": claude_auth(home=home_for(users.uid_of(me))).get("email") or ""})
        act = field(req, "action")
        if act == "password":
            r = users.change_password(me["name"], str(req.get("current") or ""),
                                      str(req.get("password") or ""))
            return self._json(r, 400 if r.get("error") else 200)
        if act == "save":
            r = users.profile_set(me["name"], req.get("profile") or {})
            if r.get("error"):
                return self._json(r, 400)
            # The account name last, because it is what the cookie is signed
            # over: the answer carries a fresh one so the page stays signed
            # in, and Basic callers simply use the new name.
            to = field(req, "account").strip()
            cookie = None
            if to and to != me["name"]:
                rr = users.rename(me["name"], to)
                if rr.get("error"):
                    return self._json(rr, 400)
                me = users.get(to)
                cookie = make_token(me)
            return self._json({"ok": True, "name": me["name"], "profile": users.profile(me),
                               "git": users.git_identity(me), "git_ready": users.git_ready(me)},
                              cookie=cookie)
        return self._json({"error": "unknown action"}, 400)

    def _upload_archive(self):
        """Spool an archive for the create dialog; {id, name, size, kind}.
        The same gate as create, because it is the first half of one — and
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
        return self._json(r, 400 if r.get("error") else 200)

    def _link(self, req):
        """Link an existing local repo to an empty GitHub repo. See projects.py."""
        body, code = projects.link(req)
        return self._json(body, code)

    def _project_job(self, req):
        """Stop the running project job, or clear the last one's outcome."""
        act = req.get("action", "")
        if act == "abort":
            return self._json(projects.abort())
        if act == "dismiss":
            return self._json(projects.dismiss())
        return self._json({"error": f"unknown action: {act}"}, 400)

    def _users(self, req):
        """The Users tab's verbs. Thin, like _nodes: users.py owns the rules —
        that the owner cannot be deleted or demoted, that there is only ever
        one, what a password has to be — and this is the door.

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
            want = req.get("prefs")
            if not isinstance(want, dict):
                return self._json({"error": "prefs is an object"}, 400)
            # Named, not merged wholesale. This file is read on the login path
            # and holds password hashes; an unbounded dict here would be a
            # place to park arbitrary data in it.
            keep = {}
            theme = str(want.get("theme") or "")
            if re.fullmatch(r"[a-z]{2,12}", theme):
                keep["theme"] = theme
            if not keep:
                return self._json({"error": "nothing here is a setting"}, 400)
            return self._json(users.prefs_set(me["name"], keep))
        if self._refused("admin"):
            return None
        name = field(req, "name")
        pw = req.get("password") or ""
        if act == "add":
            r = users.add(name, pw, role=field(req, "role") or "user",
                          projects=req.get("projects") or [])
        elif act == "passwd":
            r = users.set_password(name, pw)
        elif act == "role":
            r = users.set_role(name, field(req, "role"))
        elif act == "projects":
            # Only projects this admin can see — otherwise the tab becomes a
            # way to learn what exists by handing it out.
            mine = {p["name"] for p in project_list(self._who())}
            r = users.set_projects(name, [p for p in (req.get("projects") or [])
                                          if p in mine])
        elif act == "rename":
            r = users.rename(name, field(req, "to"))
        elif act == "edit":
            # The Users tab's modal: everything about one account in one
            # Save. Each part is the same store function the single verbs
            # use, so the owner protections hold here too; the rename goes
            # last so every other part lands under the name it was asked for.
            r = {"ok": True, "name": name}
            if isinstance(req.get("profile"), dict) and req["profile"]:
                r = users.profile_set(name, req["profile"])
            if not r.get("error") and field(req, "role"):
                r = users.set_role(name, field(req, "role")) if (users.get(name) or {}).get("role") != field(req, "role") else r
            if not r.get("error") and isinstance(req.get("projects"), list):
                mine = {p["name"] for p in project_list(self._who())}
                r = users.set_projects(name, [p for p in req["projects"] if p in mine])
            if not r.get("error") and pw:
                r = users.set_password(name, pw)
            if not r.get("error") and field(req, "to").strip() and field(req, "to").strip() != name:
                r = users.rename(name, field(req, "to").strip())
        elif act == "remove":
            r = users.remove(name)
        else:
            return self._json({"error": "unknown action"}, 400)
        return self._json(r, 400 if r.get("error") else 200)

    def _packages(self, req):
        """Queue installs or removals of the packages the Tools card offers.

        Names are checked against PACKAGES rather than passed through: what
        reaches a command line is a string this server chose, which is the
        rule every other executing endpoint here follows.
        """
        if self._refused("admin"):
            return
        action = req.get("action")
        nid = field(req, "node")
        if nid and nid != "local":
            # On another node the install is a job against that node's
            # packages store (docs/nodes.md §6): same catalog, same names,
            # audited, one at a time there — and gated on the store's
            # headroom before a byte is downloaded.
            if NODES_OK:
                return self._json({"error": "the node store did not open"}, 500)
            if action not in ("install", "remove"):
                return self._json({"error": "a node takes install or remove"}, 400)
            node = nodes.node(nid)
            if not node:
                return self._json({"error": "no such node"}, 400)
            known = {p["name"] for p in packages.PACKAGES}
            # ...or an android system image. Same rule as the local endpoint:
            # what reaches a command line is a string this server handed out —
            # for an install, one of the ids the picker was drawn from; for a
            # removal, one THIS node reported having (roadmap #20).
            names = [n for n in (req.get("names") or [])
                     if n in known
                     or (action == "install" and packages.is_choosable_image(n))
                     or (action == "remove" and packages.is_node_image(node, n))][:8]
            if not names:
                return self._json({"error": "nothing selected"}, 400)
            r = packages.node_job(self._principal(), nid, action, names)
            return self._json(r, 400 if r.get("error") else 200)
        if action == "abort":
            return self._json({"ok": packages.abort_job()})
        if action not in ("install", "remove", "update", "check"):
            return self._json({"error": "unknown action"}, 400)
        known = {p["name"] for p in packages.PACKAGES}
        # ...or an android image this server listed a moment ago. Those are not
        # catalog rows — which exist depends on what has been installed — so
        # they are checked against the list rather than against a table.
        names = [n for n in (req.get("names") or [])
                 if n in known
                 or (action == "remove" and packages.is_installed_image(n))
                 or (action == "install" and packages.is_choosable_image(n))]
        # Checking is about everything, not a selection: the question it
        # answers is "is any of this out of date, and what would the rest of
        # it install". The uninstalled rows are half the reason to press it —
        # a version you can read before spending the gigabytes.
        if action == "check" and not names:
            names = [p["name"] for p in packages.PACKAGES]
        if not names:
            return self._json({"error": "nothing selected"}, 400)
        if not packages.start_job(action, names):
            # Which one, because the automatic version check holds the queue
            # too and being told "an install is already running" when nobody
            # started an install is the kind of answer that wastes an evening.
            return self._json({"error": "a version check is running — try again in a moment"
                               if packages.job_is_automatic()
                               else "an install is already running"}, 409)
        return self._json({"ok": True, "queued": names})

    def _claude_md(self, req):
        """Create or refresh one project's CLAUDE.md.

        Run here rather than typed into a terminal: the project has no terminal
        open in the general case, and neither command takes a decision — one
        copies the template in, the other replaces a delimited block and leaves
        everything below it alone.

        Creating one is deliberately a thing a *person* asks for; sessions are
        told not to. That is what this link is — the person asking.

        The project name is checked against the directories that exist, so the
        path handed to `bb` is one this server built, never one the page sent.
        """
        name, action = req.get("name", ""), req.get("action", "update")
        if action not in ("update", "init"):
            return self._json({"error": "unknown action"}, 400)
        # A locked project does not get a file written into it on Claude's
        # behalf, which is what both of these are.
        if (bad := locked_out(name)):
            return self._json(bad, 409)
        try:
            here = {d.name for d in WORKSPACE.iterdir() if d.is_dir()}
        except OSError:
            here = set()
        if name not in here:
            return self._json({"error": f"unknown project: {name}"}, 400)
        md = WORKSPACE / name / "CLAUDE.md"
        if action == "init" and md.is_file():
            return self._json({"error": f"{name} already has a CLAUDE.md"}, 400)
        if action == "update" and not md.is_file():
            return self._json({"error": f"{name} has no CLAUDE.md"}, 400)
        r = run(["bb", "claude-md", f"--{action}", str(md)], timeout=60)
        if r["code"] != 0:
            return self._json({"error": r["out"].strip() or f"{action} failed"}, 500)
        return self._json({"state": md_state(md), "out": r["out"].strip()})

    def _doctor(self, req):
        """Re-run bb doctor now and answer with the fresh verdict.

        Synchronous on purpose: the caller pressed a button asking for an
        answer, and the threading server keeps everything else responsive
        while this one connection waits the half-minute a bad network takes.
        """
        if not run_doctor():
            return self._json({"error": "doctor is already running"}, 409)
        return self._json(doctor_payload())

    def _cards(self, req):
        """Store the sidebar card arrangement. Last write wins, like the pins:
        this only changes on an explicit gesture, so two browsers cannot fight
        over it the way their fifteen-second layout saves would."""
        if not isinstance(req.get("order"), list) or not isinstance(req.get("closed"), list):
            return self._json({"error": "bad request"}, 400)
        v = {"order": [k for k in req["order"] if k in CARD_KEYS],
             "closed": [k for k in req["closed"] if k in CARD_KEYS]}
        try:
            save_cards(v)
        except OSError as e:
            return self._json({"error": f"could not save: {e}"}, 500)
        return self._json({"cards": load_cards()})

    def _pin(self, req):
        """Pin or unpin a command. Names are keys from MACROS, so this file can
        never grow an entry the card would not know what to do with."""
        name, on = req.get("name", ""), bool(req.get("pinned"))
        if name not in MACROS:
            return self._json({"error": f"unknown macro: {name}"}, 400)
        with _state_lock:
            names = set(load_pins())
            names.add(name) if on else names.discard(name)
            try:
                save_pins(names)
            except OSError as e:
                return self._json({"error": f"could not save: {e}"}, 500)
        return self._json({"pinned": sorted(names)})

    def _layout(self, req):
        """Store the open tabs, bumping a revision so other clients notice.

        The revision is what keeps two browsers from fighting: each polls, sees
        a number it did not write, and adopts. Without it they would take turns
        overwriting each other every fifteen seconds.
        """
        # The lists are validated entry by entry when read back, but they have
        # to BE lists: a stored non-list is what load_layout would otherwise
        # have to survive on every poll from then on.
        if not isinstance(req.get("tabs", []), list) or not isinstance(req.get("panes", []), list):
            return self._json({"error": "bad request"}, 400)
        uid = users.uid_of(self._who())
        with _state_lock:
            cur = load_layout(uid)
            v = {"rev": cur["rev"] + 1,
                 "tabs": req.get("tabs") or [],
                 "panes": req.get("panes") or [None, None],
                 "active": 1 if req.get("active") == 1 else 0}
            try:
                save_layout(uid, v)
            except OSError as e:
                return self._json({"error": f"could not save: {e}"}, 500)
            # Re-read so the caller gets exactly what every other client will
            # see, including anything the validator dropped.
            return self._json(load_layout(uid))

    def _lock(self, req):
        """Lock or unlock a project: keep it, stop Claude running in it.

        A name-checked write, and the enforcement is deliberately not this
        handler's — bb-tty reads the file, because a rule only this UI honors
        is a suggestion when the ttyd URL is reachable directly.

        What it does NOT claim: a session in ANOTHER project still reaches this
        directory through Bash. The file tools are denied on every sibling
        already, and that is the whole of the guarantee here too — locking adds
        "no session of its own", not a sandbox. The tooltip says so.
        """
        name, on = req.get("name", ""), bool(req.get("locked"))
        try:
            here = {d.name for d in WORKSPACE.iterdir() if d.is_dir()}
        except OSError:
            here = set()
        if name not in here:
            return self._json({"error": f"unknown project: {name}"}, 400)
        with _state_lock:
            names = set(load_locks())
            names.add(name) if on else names.discard(name)
            try:
                save_locks(names)
            except OSError as e:
                return self._json({"error": f"could not save: {e}"}, 500)

        # A lock that waits for the current session to end is a lock that
        # did not take, and the button does not say that.
        killed = None
        sess = tmux_name(f"claude-{name}")
        if on and sess in {s["name"] for s in tmux_sessions()}:
            run(["tmux", "kill-session", "-t", sess], timeout=10)
            killed = sess
        return self._json({"locked": sorted(names), "killed": killed})

    def _trash(self, req):
        """Move a project out of the workspace. The same guards as renaming.

        A live session holds the directory as its working directory and would
        carry on writing into it wherever it went; a dev instance's containers
        are bound to paths that would stop existing. Neither is ended here for
        the same reason renaming does not: that is a bigger decision than the
        one being asked for.
        """
        name = req.get("name", "")
        if self._refused("trash", name):
            return
        live = {s["name"] for s in tmux_sessions()}
        held = sorted(s for s in live
                      if tmux_base(s) == tmux_name(f"claude-{name}")
                      or tmux_base(s).startswith(tmux_name(f"shell-{name}") + "-"))
        if held:
            return self._json({"error": "close its terminals first — "
                                        + ", ".join(held[:3])
                                        + (" …" if len(held) > 3 else "")}, 409)
        try:
            if devapp.state(name).get("exists"):
                return self._json({"error": "its dev instance still has "
                                            "containers — press Down on the "
                                            "Artifacts tab first"}, 409)
        except Exception:
            pass
        body, code = projects.trash(req)
        return self._json(body, code)

    def _trash_list(self):
        return self._json(projects.trash_list())

    def _trash_restore(self, req):
        if self._refused("trash"):
            return
        body, code = projects.trash_restore(req)
        return self._json(body, code)

    def _trash_purge(self, req):
        if self._refused("trash"):
            return
        """Delete a trashed project for good. The guards are in projects.py —
        the path is resolved against the bin and the name has to be typed back
        — and this is only the route to them."""
        body, code = projects.trash_purge(req)
        return self._json(body, code)

    def _rename(self, req):
        """Rename a project. The guards live here; the work is in projects.py.

        These two are checked here rather than there because they are the ones
        that need to see outside the filesystem — tmux, and the daemon. Both
        are refusals rather than things to tidy away automatically: a running
        session holds the old path as its working directory and would carry on
        writing to it, and a dev instance's containers are named for the old
        project on a machine this may not even be able to reach. Ending either
        on the operator's behalf, to complete a rename, is a larger decision
        than the rename.
        """
        name = req.get("name", "")
        if self._refused("rename", name):
            return
        live = {s["name"] for s in tmux_sessions()}
        held = sorted(s for s in live
                      if tmux_base(s) == tmux_name(f"claude-{name}")
                      or tmux_base(s).startswith(tmux_name(f"shell-{name}") + "-"))
        if held:
            return self._json({"error": "close its terminals first — "
                                        + ", ".join(held[:3])
                                        + (" …" if len(held) > 3 else "")}, 409)
        try:
            if devapp.state(name).get("exists"):
                return self._json({"error": "its dev instance still has "
                                            "containers — press Down on the "
                                            "Artifacts tab first"}, 409)
        except Exception:
            pass          # no daemon, or no compose file: nothing to protect
        body, code = projects.rename(req)
        return self._json(body, code)

    def _project_auth(self, req):
        """What credential this project's remote uses, and what else it could.

        Asked when the rename dialog opens rather than carried on the status
        poll: answering it means running `git remote get-url` in the project,
        and the poll already walks every project every fifteen seconds. One
        subprocess per dialog is nothing; one per project per poll is not.
        """
        name = req.get("name", "")
        if not PROJECT_NAME.fullmatch(name or ""):
            return self._json({"error": "unknown project"}, 400)
        d = WORKSPACE / name
        if not d.is_dir():
            return self._json({"error": "unknown project"}, 400)
        return self._json(projects.auth_options(name, d))

    def _project_pin(self, req):
        """Pin or unpin a project: whether the sidebar card shows it.

        No session is touched and nothing is blocked — this is the one control
        of the three that is purely about the view. Unpinning something running
        a build leaves it running, and the Projects tab still has every button.

        The first unpin has to write the whole current set, not just remove
        one: until then there is no file, which means "all of them", and
        saving a single removal would have read as "only this one is pinned".
        """
        name, on = req.get("name", ""), bool(req.get("pinned"))
        try:
            here = {d.name for d in WORKSPACE.iterdir()
                    if d.is_dir() and d.name != "_work"
                    and not d.name.startswith(".")}
        except OSError:
            here = set()
        if name not in here:
            return self._json({"error": f"unknown project: {name}"}, 400)
        with _state_lock:
            pins = load_project_pins()
            names = here.copy() if pins is None else set(pins)
            names.add(name) if on else names.discard(name)
            try:
                save_project_pins(names)
            except OSError as e:
                return self._json({"error": f"could not save: {e}"}, 500)
        return self._json({"pinned": sorted(names)})

    def _session(self, req):
        """Kill a session. Closing a tab that owns a Claude conversation should
        end it, or detached sessions accumulate invisibly behind a tidy UI."""
        session = req.get("session", "")
        if req.get("action") != "kill":
            return self._json({"error": "unknown action"}, 400)
        # Already gone is already ended. The check is here so an arbitrary name
        # never becomes a `-t` argument, which holds either way — nothing runs
        # for a name that is not a live session. Answering with an error
        # instead made the caller that wants a clean slate (Sign in, which ends
        # the sign-in terminal before starting a new flow) report a failure for
        # the ordinary case of there being nothing to end.
        # A session on a node (roadmap #24): the kill goes to its agent
        # through the held poll, under the name the node knows it by, and
        # the row disappears with the next heartbeat. By node id when the
        # row said which — the same name can exist here and there — and by
        # name alone for a caller that only knows the name (a tab closing).
        want_node = str(req.get("node") or "")
        on_node = next((s for s in node_tmux_sessions() if s["name"] == session
                        and (not want_node or s["node_id"] == want_node)), None)
        if on_node and (want_node or session not in {s["name"] for s in tmux_sessions()}):
            r = nodes.session_kill(on_node["node_id"], on_node["node_name"])
            return self._json(r, 400 if r.get("error") else 200)
        if session not in {s["name"] for s in tmux_sessions()}:
            return self._json({"code": 0, "out": "", "err": "", "gone": True})
        return self._json(run(["tmux", "kill-session", "-t", session], timeout=10))

    def _session_on_node(self, session, node=""):
        """The node session row this page-name means, or None — for the
        three key paths, which type into a node's session through its
        agent exactly as they type into this container's tmux."""
        if session in {s["name"] for s in tmux_sessions()} and not node:
            return None
        return next((s for s in node_tmux_sessions() if s["name"] == session
                     and (not node or s["node_id"] == node)), None)

    def _keys(self, req):
        session, key = req.get("session", ""), req.get("key", "")
        on_node = self._session_on_node(session, str(req.get("node") or ""))
        if on_node:
            # The same table, queued for the node's agent (roadmap #24); the
            # paging decision is the agent's, on the pane it can see.
            real = on_node["node_name"]
            if key in ("pgup", "pgdn"):
                op = {"session": real, "page": "up" if key == "pgup" else "down"}
            elif key in TMUX_KEYS:
                op = {"session": real, "argv": ["send-keys", "-t", real, TMUX_KEYS[key]]}
            elif key in TMUX_LITERALS:
                op = {"session": real, "argv": ["send-keys", "-t", real, "-l", "--",
                                                TMUX_LITERALS[key]]}
            else:
                return self._json({"error": f"unknown key: {key}"}, 400)
            r = nodes.session_tmux(on_node["node_id"], [op])
            return self._json(r, 400 if r.get("error") else 200)
        # Only sessions that currently exist — never an arbitrary -t argument.
        if session not in {s["name"] for s in tmux_sessions()}:
            return self._json({"error": f"no such session: {session}"}, 400)
        # Paging is how a finger scrolls: a drag reaches nothing (the terminal
        # sits on tmux's alternate screen, and xterm.js turns only wheel events
        # into anything tmux sees), so PgUp at a prompt enters copy mode a page
        # up and PgDn pages back, copy mode ending by itself at the bottom
        # (-e). The tmux config binds a real keyboard's PgUp the same way, but
        # send-keys goes straight to the pane, past the key table that binding
        # lives in — so the same decision is made here, as commands. Inside a
        # full-screen program (less, vim) the key is the program's.
        if key in ("pgup", "pgdn"):
            flags = run(["tmux", "display-message", "-p", "-t", session,
                         "#{alternate_on} #{pane_in_mode}"], timeout=10)
            alt, mode = (flags["out"].split() + ["0", "0"])[:2]
            if key == "pgup":
                cmd = ["send-keys", "-t", session, "PPage"] if alt == "1" \
                    else ["copy-mode", "-eu", "-t", session]
            else:
                cmd = ["send-keys", "-t", session, "-X", "page-down"] if mode == "1" \
                    else ["send-keys", "-t", session, "NPage"]
            return self._json(run(["tmux", *cmd], timeout=10))
        if key in TMUX_KEYS:
            return self._json(run(["tmux", "send-keys", "-t", session,
                                   TMUX_KEYS[key]], timeout=10))
        if key in TMUX_LITERALS:
            return self._json(run(["tmux", "send-keys", "-t", session, "-l", "--",
                                   TMUX_LITERALS[key]], timeout=10))
        self._json({"error": f"unknown key: {key}"}, 400)

    def _chat(self, req):
        """Read a conversation, send into one, or mark one seen.

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
            # can read and answer every channel — which is what makes it
            # useful to them — while a user has the channels they were given
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

        if act == "send":
            text = req.get("text", "")
            r = (chat.post(proj, uid, text) if box[0] == "project"
                 else chat.say(uid, box[1], text))
            if r.get("error"):
                return self._json(r, 400)
        if act in ("send", "seen", "read"):
            # Reading it IS seeing it: the panel only asks for a conversation
            # somebody is looking at.
            users.prefs_set(me["name"], {"chat_seen":
                users.prefs(me).get("chat_seen", {}) | {key: chat.now()}})
        msgs = (chat.feed(proj) if box[0] == "project"
                else chat.direct(uid, box[1]))
        names = {u: n for n, u in by_name.items()}
        return self._json({"messages": [m | {"who": names.get(m.get("from"), "")}
                                        for m in msgs[-200:]],
                           "rev": chat.rev()})

    def _say(self, req):
        """Type a message into a CLAUDE session and press Enter.

        The one place this server types free text into a pane, and every
        restriction on it is load-bearing. /api/send deliberately takes a
        macro name and never a command string, because a pane is usually a
        shell and free text there is arbitrary execution. This is the
        exception an account with no shell needs — its Claude session is a
        read-only terminal, so the only way to say anything is through here —
        and it is narrowed until the exception cannot become the rule:

          * the session has to be a `claude-…` one, matched against a project
            this account can actually see. Not a name from the request: a
            shell session named through here would be exactly the hole;
          * it has to be this account's conversation, by the same holder
            record the proxy checks;
          * control characters are stripped, so a message cannot move the
            cursor, clear the screen, or carry an escape sequence.

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
                        if users.tmux_prefix(me) + tmux_name(f"claude-{p['name']}")
                        == want), "")
        if not project or users.may(me, "claude", project):
            return self._json({"error": "not a Claude session of yours"}, 403)
        on_node = self._session_on_node(want, str(req.get("node") or ""))
        if want not in {x["name"] for x in tmux_sessions()} and not on_node:
            return self._json({"error": "that conversation is not running"}, 409)
        text = "".join(ch for ch in str(req.get("text", ""))
                       if ch == "\t" or ord(ch) >= 32)[:CUSTOM_LINE_MAX]
        if not text.strip():
            return self._json({"error": "nothing to say"}, 400)
        if on_node:
            # Into the conversation on the node, through its agent: the same
            # two keystrokes, the same narrowing above (roadmap #24).
            real = on_node["node_name"]
            r = nodes.session_tmux(on_node["node_id"], [
                {"session": real, "argv": ["send-keys", "-t", real, "-l", "--", text]},
                {"session": real, "argv": ["send-keys", "-t", real, "Enter"]}])
            return self._json(r, 400 if r.get("error") else 200)
        r = run(["tmux", "send-keys", "-t", want, "-l", "--", text], timeout=10)
        if r["code"] != 0:
            return self._json({"error": r["out"].strip()[:200] or "send failed"}, 500)
        run(["tmux", "send-keys", "-t", want, "Enter"], timeout=10)
        return self._json({"ok": True})

    def _send(self, req):
        """Type a macro's command line into a shell session and press Enter.

        Two kinds, and neither is a command string from the request: a name from
        the fixed `bb` table, or the id of a custom macro the operator saved
        earlier through /api/custom. What lands in the terminal is exactly what
        they would have typed, in a tty they are already sitting at.
        """
        session, name, cid = (req.get("session", ""), req.get("macro", ""),
                              req.get("custom", ""))
        if cid:
            m = next((x for x in load_custom() if x["id"] == cid), None)
            if not m:
                return self._json({"error": f"unknown custom command: {cid}"}, 400)
            lines = m["lines"]
        else:
            if name in MACROS:
                lines = [shlex.join(MACROS[name])]
            elif name in SHELL_MACROS:
                lines = [SHELL_MACROS[name]]
            else:
                return self._json({"error": f"unknown macro: {name}"}, 400)
        on_node = self._session_on_node(session, str(req.get("node") or ""))
        if session not in {s["name"] for s in tmux_sessions()} and not on_node:
            return self._json({"error": f"no such session: {session}"}, 400)
        # Never into a Claude session: that would not run the command, it would
        # submit it as a prompt.
        if tmux_base(session).startswith("claude-"):
            return self._json({"error": "refusing to type into a Claude session"}, 400)
        if on_node:
            # A shell on the node: the same lines, through its agent.
            real = on_node["node_name"]
            ops = [{"session": real, "argv": ["send-keys", "-t", real, "C-e", "C-u"]}]
            for line in lines:
                ops.append({"session": real, "argv": ["send-keys", "-t", real, "-l", "--", line]})
                ops.append({"session": real, "argv": ["send-keys", "-t", real, "Enter"]})
            r = nodes.session_tmux(on_node["node_id"], ops)
            return self._json(r | {"sent": lines[0] if len(lines) == 1
                                   else f"{len(lines)} commands"},
                              400 if r.get("error") else 200)
        # Clear whatever was half-typed at the prompt first, or the command
        # arrives glued to the end of it. End-of-line then kill-line, which is
        # readline editing and not a signal: Ctrl-C would also interrupt
        # whatever is running in there, which is not what pressing a button
        # labeled `bb status` should be able to do.
        run(["tmux", "send-keys", "-t", session, "C-e", "C-u"], timeout=10)
        # Typed one after another without waiting. That is what happens when a
        # person types ahead too — the tty buffers the input and the shell reads
        # each line when it is ready for one.
        for line in lines:
            # `--`: a line that starts with a dash ("-la", "--version") is
            # otherwise read by tmux as flags and refused as "unknown flag",
            # after the prompt has already been cleared — a macro that just
            # silently did nothing.
            r = run(["tmux", "send-keys", "-t", session, "-l", "--", line], timeout=10)
            if r["code"] != 0:
                return self._json(r)
            r = run(["tmux", "send-keys", "-t", session, "Enter"], timeout=10)
            if r["code"] != 0:
                return self._json(r)
        return self._json(r | {"sent": lines[0] if len(lines) == 1
                               else f"{len(lines)} commands"})


def main():
    # No accounts is a normal first boot, not a failure. It used to be one:
    # the owner came from DASHBOARD_AUTH and the dashboard refused to start
    # without it, which put a password in the container's environment — where
    # it is visible to anything that can read the template, stays readable
    # forever, and is the one credential that opens a shell on this box.
    #
    # It is the first-run screen instead, and until somebody claims the
    # container that is the only page it serves. Nothing else is reachable
    # unauthenticated, which is the property the old refusal was protecting.
    if not users.all_users():
        print("dashboard: no accounts yet — the first page served will ask "
              "you to make the owner. Do it now: until you do, whoever "
              "reaches this port can.", flush=True)
    prune_claude_tabs()
    # Daemons: these loops must die with the server, not hold it open.
    threading.Thread(target=_doctor_loop, daemon=True).start()
    idle.start()
    threading.Thread(target=_compat_loop, name="compat", daemon=True).start()
    if packages.AUTOCHECK:
        threading.Thread(target=packages.versions_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
