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
from html import escape as html_escape
import gzip
import hashlib
import hmac
import ipaddress
import json
import os
import sys
import re
import selectors
import shlex
import socket
import subprocess
import threading
import time

# Beside this file. Imported up here rather than with the modules below,
# because write_json is defined from it before any of those load.
import statefile
from names import PROJECT_NAME, claude_session, tmux_name   # noqa: F401 - re-exported to the modules
from claudemd import (TEMPLATE_MD, build_claude_md, md_block, md_file,   # noqa: F401
                     md_for, md_gap, md_state, md_window)
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
# #24): the ones whose state is this container's, git's network half among
# them (docs/nodes.md §20: the keys are here and the tree is the share). One
# list, in lib/relay-verbs, read by bb on the node and by this side, so a
# verb cannot be added to one and not the other.
RELAY_VERBS = frozenset((HERE.parent / "lib" / "relay-verbs").read_text().split())

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
# "findings" is the Analysis tab the Static analysis button opens, the
# report as a document tab beside the notebook's own view of it.
TAB_KINDS = {"term", "packages", "todo", "projects", "docker", "findings",
             "nodes", "settings", "jobs", "users", "phone", "profile"}


def _layouts():
    """The whole file: {"boot": ..., "users": {uid: layout}}.

    One strip per ACCOUNT, keyed by the minted id rather than the name so a
    rename keeps it (users.mint_uid says why): a layout written by whoever
    last saved and handed to everybody else is fine for one operator and
    wrong the moment there are two.
    """
    try:
        v = json.loads(TABS_FILE.read_text())
    except (OSError, ValueError):
        v = {}
    if not isinstance(v, dict):
        v = {}
    if not isinstance(v.get("users"), dict):
        v = {"boot": v.get("boot"), "users": {}}
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


# `bb packages install|update|remove` refuses when CLAUDECODE is set, and the
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


def version_payload(name):
    """The Artifacts tab's version block, plus what a window move would cost
    here. One function so every answer the tab gets carries the same warning —
    the staged line is drawn from whichever of them came back last."""
    cost = window_cost(name)
    return version.payload(name) | ({"window_cost": cost} if cost else {})


def window_cost(name):
    """What a MINOR bump of this project would cost the others, or {}.

    Only one project can answer yes: the one whose checkout carries the
    CLAUDE.md template, because its minor IS the compatibility window every
    other project's environment block is compared against. Moving it holds
    each of them — sessions ended, Claude button ghosted — until its block is
    updated, and nothing said so before the button was pressed (B92). The
    test is the two files that do it rather than a project's name:
    tools/version-stamp is what rewrites the window line, and the template is
    the line it rewrites.
    """
    try:
        here = WORKSPACE / name
        if not ((here / "tools" / "version-stamp").is_file()
                and md_window(here / "config" / "templates" / "project-CLAUDE.md")):
            return {}
    except OSError:
        return {}
    held = []
    try:
        for d in sorted(WORKSPACE.iterdir()):
            if not d.is_dir() or (d / IGNORE_MARKER).exists():
                continue
            if md_window(md_file(d)):
                held.append(d.name)
    except OSError:
        return {}
    return {"window": md_window(TEMPLATE_MD), "projects": held}


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
        md = md_file(d)
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
    wanted = {claude_session(p): why for p, why in holds.items()}
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


# What a new project may be called. It becomes a directory under /workspace and
# part of a tmux session name, so it gets the strictest charset here — one path
# segment, starting with a letter or digit, which also rules out `_work`,
# dotfiles and `..`. Where a clone may come from is forges.URL, next door: the
# same allowlist reasoning (`git clone` accepts transports a browser form must
# never reach — `ext::` runs commands) applied to more than one host.

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
    true exactly when an https remote will work, which only a `gh auth login`
    typed in a shell makes so. `gh auth token` is offline and instant;
    `gh auth status` phones home.
    """
    return run(["gh", "auth", "token"], timeout=10)["code"] == 0


def ensure_deploy_alias(name, pub, host):
    """A per-repo ssh alias for one agent key on one host, created
    idempotently; returns the alias.

    Why an alias at all: deploy keys are scoped to a single repository, and
    ssh offers every agent key in order — the host authenticates the first
    valid one and then refuses the repo it does not belong to. The fix is
    IdentitiesOnly plus an IdentityFile naming the *public* half, which acts
    purely as a selector for the agent key (the private half stays shielded).

    The host is in the alias because one key can serve two of them: the same
    ed25519 on GitHub and on the Gitea in the cupboard is two different
    HostName lines, and an alias named after the key alone could only ever
    carry one of them.

    Everything written lives in a namespace of our own — bb_<name>.pub and
    Host bb-<name>-<host> — so a .pub or an alias the operator maintains by
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

    Not the host as written: the standard multi-deploy-key setup — including
    the bb- aliases this dashboard's own clone and link flows write — hides
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


def _session_at(name):
    t = session_target(name, claude=True)
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
    # One small file for the whole list, read here rather than per row: this
    # runs on the fifteen-second poll and a per-project read would be a dozen
    # opens for a dozen values that came from the same dictionary.
    # With the workspace, so each row also says what `bb test` would run
    # there with nothing set — the settings field offers it as what an
    # empty box means.
    project_prefs = prefs.all_projects(WORKSPACE)
    # One answer per node about its agent, for every project row on it.
    node_gaps = {}
    # ...and its name, for the row to wear beside the project's.
    node_names = {}
    if not NODES_OK:
        for n in nodes.node_list():
            node_names[n["id"]] = n["name"]
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
        # its own that lands inside the projects share — the package store, when
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
            mdf = md_file(d)
            has_md = mdf.is_file()
        except OSError:
            mdf, has_md = d / "CLAUDE.local.md", False

        # linked defaults to True and github to False: each gates an offered
        # action (the chain on the row; the GitHub command buttons), and a
        # project this loop could not examine must get no offer rather than a
        # broken one — which is the opposite default for the two. The forge
        # defaults with them, and to the entry that promises nothing.
        branch, git_ok, linked, github = None, False, True, False
        fhost, forge = "", forges.OTHER
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
                # submodule keeps its config elsewhere, and these drive
                # visible controls (the chain on the row; the GitHub command
                # card's ghosting), so a wrong guess here offers an action
                # that cannot work. -v for the URLs, which is what says which
                # host it is on.
                remotes = run(["git", "-C", str(d), "remote", "-v"],
                              timeout=10)["out"]
                linked = bool(remotes.strip())
                # Which forge, for the chain's own words — and `github` still
                # on its own, because the command card runs `gh` and that is
                # GitHub's and nobody else's.
                fhost = _remote_host(remotes) if linked else ""
                forge = forges.forge_of(fhost)
                github = fhost.lower().split(":")[0] == "github.com"
                r = run(["git", "-C", str(d), "symbolic-ref", "--short", "-q", "HEAD"],
                        timeout=10)
                # `out` carries stderr too, so a detached HEAD would otherwise
                # put a `fatal:` line where the branch name goes.
                branch = (r["out"].strip() or "(detached)") if r["code"] == 0 else "(detached)"
                if not has_md:
                    issues.append({"level": "warning", "action": "claude-md-init",
                                   "text": "no environment block — create one"})
                elif (md := md_state(mdf)) == "stale":
                    # Offered as an action, not just a complaint: the fix is one
                    # command with no decisions in it, and the block goes stale
                    # every time the image gains a feature. From an OLDER
                    # window it is the same link with the sharper words —
                    # that one stops the project's sessions until pressed. A
                    # block from a later window is drift like any other: the
                    # container has not been rebuilt yet, which md_gap says
                    # more about.
                    md_hold = md_gap(mdf)
                    issues.append({"level": "warning", "action": "claude-md-update",
                                   "text": ("the environment block is from an older "
                                            f"compatibility window ({md_window(mdf)} "
                                            f"against {md_window(TEMPLATE_MD)}): update")
                                   if md_hold else
                                   "CLAUDE.md environment block is out of date: update"})
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
                    # Which host it is linked to, for the chain to say so in
                    # its own words. "" when there is no remote to be on, and
                    # the ADDRESS rather than the catalog's generic label when
                    # nobody has said what that server runs — "Unlink from
                    # Another git host" names nothing a person could check.
                    "forge": forge["id"] if linked else "",
                    "forge_name": ("" if not linked
                                   else forge["name"] if forge["id"] != forges.OTHER["id"]
                                   else fhost or forge["name"]),
                    "forge_host": fhost,
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
                    "last_claude": last_claude(d),
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
                    "bugs": bug_counts.get(d.name, 0),
                    "tests": test_counts.get(d.name, 0),
                    "rules": rule_counts.get(d.name, 0),
                    "pending": pend_counts.get(d.name, 0),
                    # Why nothing routed to this project's node runs right
                    # now — its agent behind, or from another window — so
                    # the Artifacts tab and the bell say so before a job is
                    # refused. "" is the ordinary state.
                    "node_gap": node_gaps.get(project_prefs.get(d.name, {}).get("node") or "", ""),
                    # Which node this project's work runs on, by name, or ""
                    # for none: the row says "(node: X)" beside the name.
                    "node_name": node_names.get(project_prefs.get(d.name, {}).get("node") or "", ""),
                    # Why no Claude session may run here right now, or "":
                    # its CLAUDE.md block from another compatibility window,
                    # else its own node's agent from one. The button ghosts
                    # on this and bb-tty refuses on the same facts; the sweep
                    # ends what is running. Per project: another project's
                    # node being out of window is not this row's hold.
                    "held": md_hold or held_nodes.get(
                        project_prefs.get(d.name, {}).get("node") or "", ""),
                    "md_window": md_window(mdf) if has_md else "",
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


# A node that came up this recently and reports no /workspace is one whose
# network mount has not landed yet, not one missing a mount.
BOOT_GRACE_S = 600
_hello_asked = {}


def _ask_hello(nid):
    """A fresh census from a node a session was just refused on, at most
    once a minute: the census rides hello every ten minutes, and the retry
    a person makes ten seconds later should reason about the node as it is."""
    now = time.time()
    if now - _hello_asked.get(nid, 0) >= 60:
        _hello_asked[nid] = now
        nodes.ask_hello(nid)


def session_target(project, claude=False):
    # `claude` is the one thing that changed with R47. A project's SHELL still
    # follows its node — the tree is that machine's mount and its toolchains
    # are what a build there uses — and a project with NO node still gets a
    # shell here, on the same share. What it no longer gets is a Claude
    # session: this container carries no Claude Code, so the answer is a
    # refusal that says what to do rather than a conversation that cannot
    # build anything.
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

    Two of the refusals are PASSING — the node is rebooting, or it just
    came up and its network mount has not landed — and the sentence for
    those says to wait, not to unbind the node: the operator who rebooted
    the sandbox and met "add the mount... unbind the node" had nothing to
    add and nothing to unbind. The census is asked for again on the
    strength of any refusal it decided, so the next look is current.

    A Claude session has no second place to run: this container carries no
    Claude Code, so a refusal is the whole answer and the sentence has to
    carry what to do about it. A SHELL still falls back here, which is what
    keeps the tree, the linters and git reachable while a node is away.
    """
    nid = (prefs.get(project) or {}).get("node") or "" if project else ""
    # ONE SENTENCE, and not a red one on the page: a project with no node is
    # a normal state, not a fault. `name` is what tells the two apart
    # downstream — empty here, the node's name when a node refused — so the
    # row can say this plainly and keep red for the machine that is broken.
    no_node = {"where": "refused", "name": "",
               # A full stop, not a dash: shortWhy() on the page cuts this
               # at the first sentence end to put the fact on the row and
               # leave the instruction to the tooltip, and the dash it used
               # to cut at is gone from the page's vocabulary.
               "why": "no node: pick one in the project's settings, or enroll "
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
    passing = False
    if n.get("state") != "online":
        why = f"{project}'s sessions run on {name}, which is {n.get('state') or 'not online'}"
    elif n.get("live") is False:
        # The agent has stopped dialing in: a reboot, an update, a machine
        # that is off. Its tmux sessions are still there when it comes
        # back, and the button comes back with it — nothing to change.
        seen = int((n.get("agent") or {}).get("last_seen") or 0)
        ago = int(time.time() - seen) if seen else 0
        when = (f"{ago // 60} minutes ago" if ago >= 120 else f"{ago} seconds ago") if seen else "never"
        why = (f"{project}'s sessions run on {name}, whose agent is not answering — last heard "
               f"from {when}. If it is restarting, its sessions are back when it dials in")
        passing = True
    elif not isinstance(se, dict):
        why = (f"{project}'s sessions run on {name}, which has not reported a "
               "session half yet — give it a moment, or provision it with "
               "--session-user")
    elif not se.get("up"):
        why = (f"{project}'s sessions run on {name}, which runs none yet"
               + (f": {se['why']}" if se.get("why") else
                  " — provision it with --session-user"))
        _ask_hello(nid)
    elif not se.get("workspace"):
        up = se.get("up_s")
        # The server's own reason, when the agent tried the mount and kept
        # what it said: a refused mount is not a missing one, and the fix
        # is on the host, not on this row.
        merr = next((str(m.get("error") or "") for m in (rep.get("mounts") or [])
                     if isinstance(m, dict) and m.get("path") == "/workspace" and m.get("error")), "")
        if merr and "access denied" in merr.lower():
            why = (f"{project}'s sessions run on {name}, which cannot mount the projects share at "
                   f"/workspace: {merr}. The host's NFS export names another address, and this "
                   f"node is on {nodes.route_host(nid) or 'a new one'} — change the rule on the "
                   "host (Unraid: Shares → the share → NFS Security Settings) and the mount "
                   "lands on its own")
        elif merr:
            why = (f"{project}'s sessions run on {name}, which cannot mount the projects share at "
                   f"/workspace: {merr} — its row on the Nodes tab has the mount")
        elif isinstance(up, int) and 0 <= up < BOOT_GRACE_S:
            why = (f"{project}'s sessions run on {name}, which came up {up} seconds ago and has "
                   "not mounted the projects share at /workspace yet — a network mount lands a "
                   "moment after boot, and the button is back when it does")
            passing = True
        else:
            why = (f"{project}'s sessions run on {name}, which does not mount the projects "
                   "share at /workspace — add the mount on its row on the Nodes tab")
        _ask_hello(nid)
    elif se.get("writable") is False:
        # Read-only was the right way to mount the share for a Docker-only
        # sandbox and is the wrong way for one that runs sessions: nothing
        # could be saved, and the transcripts link cannot be made there.
        why = (f"{project}'s sessions run on {name}, which mounts the projects share "
               "read-only — a session there could not save a file. Untick read-only on "
               "the /workspace mount on its row on the Nodes tab and apply, or `sudo "
               "bb-sandbox readonly /workspace off` on the machine")
        _ask_hello(nid)
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
            "why": why + ("." if passing else
                          ". Sessions run on a node and nowhere else — this container "
                          "carries no Claude Code — so the way on is that machine "
                          "coming back, or another node in the project's settings.")}

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
    """Which Anthropic account each BuilderBot account is signed in as, and
    whether two of them share one.

    From the RECORD, not from a credential: no login lives on this container
    (R47), and what it keeps instead is which Anthropic account each of its
    accounts is bound to, as the node that signed in reported it.

    Anthropic's consumer terms allow one person per Claude account, so two
    BuilderBot accounts on one login is the thing the per-account homes exist
    to avoid — said on the row rather than left for somebody to work out.
    """
    out = []
    for u in rows:
        home = home_for(u.get("uid", "")) or os.environ.get("BUILDER_HOME", str(Path.home()))
        out.append(u | {"claude": claudegrant.state(home)["email"]})
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


def sessions_anywhere():
    """Every Claude session's page name, here and on the nodes: what the
    notebook's Send to Claude has to choose from. Since sessions moved onto
    nodes (roadmap #24) the local half is the harness's and the node half
    is everybody's, and a list of only the first told every project it had
    no session while its own row showed one."""
    return [s["name"] for s in tmux_sessions()] + [s["name"] for s in node_tmux_sessions()]


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


def last_claude(project_dir):
    """The most recent Claude transcript for a working directory, or None.

    Used to offer "resume" rather than silently starting a fresh conversation
    in a project that already had one — a session's tmux dies with the machine
    it ran on, but the transcript does not: every account's ~/.claude/projects
    is a link onto the projects share (lib/common.sh's claude_projects_link),
    so this reads what a session on a node wrote.
    """
    d = CLAUDE_PROJECTS / str(project_dir).replace("/", "-")
    try:
        files = [f for f in d.glob("*.jsonl") if f.is_file()]
    except OSError:
        return None
    if not files:
        return None
    newest = max(files, key=lambda f: f.stat().st_mtime)
    return {"id": newest.stem, "when": int(newest.stat().st_mtime)}


MODEL_FAMILY = re.compile(r'"model"\s*:\s*"claude-(opus|sonnet|haiku|fable)')


def claude_model_now(project_dir):
    """The model family the newest transcript here last answered on, or "".

    Read from the tail of the file when a project's settings dialog opens,
    so with no model set the dialog can say what Claude's default actually
    is rather than "leave as is". The tail, because a transcript runs to
    megabytes and the answer is in its last line.
    """
    t = last_claude(project_dir)
    if not t:
        return ""
    f = CLAUDE_PROJECTS / str(project_dir).replace("/", "-") / f"{t['id']}.jsonl"
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

    It used to RESPAWN the pane in place — `tmux respawn-pane -k` running the
    launcher again with `--respawn` — which kept the session, and the browser
    tab attached to it, and meant the change landed somewhere nobody was
    looking. The operator's call (12 Sep): end it, and let the button start it
    again. Simpler to say and simpler to trust, and it asks nothing of a
    node's agent that killing a session from the Sessions card has not asked
    for months — so the version gate that came with the respawn op is gone
    with it.

    A session ended is not a conversation lost: the transcript is the
    account's own and the Claude button resumes it. What it costs is the turn
    in flight, which is what the dialog asking about it says.
    """
    session = claude_session(project)
    if session not in {s["name"] for s in tmux_sessions()}:
        # On a node, through its agent, under the name that machine knows it
        # by — the same path the Sessions card's kill takes.
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


def uptime():
    # PID 1 started when the container did, so its elapsed time is the
    # container's — /proc/uptime is the host's under a shared kernel.
    r = run(["ps", "-o", "etime=", "-p", "1"], timeout=10)
    return r["out"].strip() or "?"


# The API surface the companion app is written against (android/). One
# number, moved with the app: android/api-surface.json names every path
# and field the app reads and carries the same number, test/appapi.mjs
# holds the running server to that file, and the app compares this against
# its own TARGET_API to say when it is behind. A change to a path or a
# field listed there bumps all three together — the app, the file, this.
APP_API = 1


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
    return apks[0].name if apks else ""


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


# What gets removed from a pasted code before it is handed to the flow:
# whitespace of every kind (a wrapped copy brings line breaks, a phone
# keyboard adds a trailing space), control characters, and the zero-width
# marks HTML copy buttons smuggle along. Everything printable stays. This is
# deliberately a strip-list and not an allow-list: two rounds of guessing the
# code's alphabet each refused a real code with advice to copy it again, to an
# operator who had copied it. The code is somebody else's credential format;
# judging it is the flow's job, and the flow says why in its own words.
CODE_JUNK = re.compile(r"[^!-~]+")


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
    # The GRANT is the answer, not `claude auth status`. Signing out deletes
    # the credential and moves the generation; asking the binary would still
    # say signed in, because the binary reads a file that is no longer there
    # only once it is next run — and on a controller that carries no Claude
    # there is no binary to ask at all. What the account is signed in AS is
    # what the node that signed in reported, stored beside the grant.
    # The record, and only the record. There is no `claude` here to ask, and
    # asking one would answer about this container rather than about the
    # machines the account's sessions actually run on.
    st = claudegrant.state(home)
    state = {"signed_in": st["signed_in"], "email": st["email"],
             "plan": st["plan"], "nodes": len(st["nodes"])}
    _auth[home] = {"at": time.monotonic(), "state": state}
    return state


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

notify.configure(run=run,
                 # A session on a node: found by the name the page uses,
                 # told through its agent (roadmap #24). Resolved at call
                 # time: the nodes module is imported further down.
                 on_node=lambda s: next((x for x in node_tmux_sessions() if x["name"] == s), None),
                 node_tell=lambda *a: nodes.tell_wait(*a))

# ---- signing in ------------------------------------------------------------
# The flow runs as a job on a NODE — the machine Claude Code is installed on
# (R47) — and the card here carries its link and takes the code back. See
# signin.py for why every part of doing it in a terminal turned out to be
# somewhere it could go wrong.
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
# network. The credential half stays here — agent_keys and the ssh aliases are
# this box's, not any one project's — and is handed over.
import forges                                                    # noqa: E402
forges.configure(run=run, state=STATE, write_json=write_json)

import projects                                                  # noqa: E402

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
# The Settings tab's own store (roadmap R29): what used to be fourteen
# environment variables. The builder home is where the commit identity lands.
settings.configure(write_json=write_json, state=STATE)
# What may be offered: the catalogues gate their unvetted entries on this
# one switch (roadmap R54, step 6), read live so a save takes at once.
forges.unvetted_ok = lambda: bool(settings.get("offer_unvetted"))


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

# What a project has built, from its dist/ directory — the notebook's fifth
# view. The convention is the module's docstring; the scratch dir is where an
# .xpi is unpacked for web-ext, never dist/ itself.
import artifacts                                                 # noqa: E402
import git as gitview                                            # noqa: E402
import workspace                                                 # noqa: E402

artifacts.configure(workspace=WORKSPACE)
gitview.configure(workspace=WORKSPACE,
                  worktrees=os.environ.get("BB_WORKTREES") or str(WORKSPACE / ".worktrees"),
                  tell=notify.tell, tmux_name=tmux_name)
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
memory.configure_log(write_json=write_json, state=STATE, actor=writer_name)

# ---- the shared to-do list -------------------------------------------------
# The one surface both sides write: the operator adds an item, a session adds
# one and ticks it off. bb-tty puts the open items in front of every Claude
# session it starts, which is the whole reason it is worth having.
import todo                                                      # noqa: E402

todo.configure(write_json=write_json, state=STATE, tell=notify.tell,
               tmux_name=tmux_name, settle=notify.settle, actor=writer_name)

# ---- what a session is handed ----------------------------------------------
# The three above, assembled in the order a session reads them. bb-tty used to
# join them itself in shell; it asks for this now, and the Briefing tab draws
# the same string rather than its own idea of it.
import preamble                                                  # noqa: E402
preamble.configure(rules_mod=rules, todo_mod=todo, bugs_mod=bugs)

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

# ---- a node's CI runners ----------------------------------------------------
# The root-only helper that keeps each runner's token and mints from it, and
# the list the Runner card draws: runners.py.
import runners                                                   # noqa: E402

runners.configure(run=run, nodes=None if NODES_OK else nodes)

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
# What Allow on a rebuild request actually starts (the Docker row's `ask`).
# Outside the block above: the ask has nothing to do with the node registry,
# and a controller without one still has projects whose containers run.
phone.rebuilder = devapp.rebuild
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
import claudegrant                                              # noqa: E402
import version                                                   # noqa: E402
import vmtemplate                                                # noqa: E402
vmtemplate.unvetted_ok = forges.unvetted_ok          # the same switch (R54, step 6)

version.configure(workspace=WORKSPACE, state=STATE, write_json=write_json,
                  todo_mod=todo, bugs_mod=bugs, changelog_mod=changelog,
                  tell_fn=notify.tell, tmux_name_fn=tmux_name,
                  )



projects.configure(run=run, workspace=WORKSPACE, agent_keys=agent_keys,
                   gh_authed=gh_authed, ensure_deploy_alias=ensure_deploy_alias,
                   build_claude_md=build_claude_md,
                   project_name=PROJECT_NAME,
                   state=STATE, home=os.environ.get("BUILDER_HOME", str(Path.home())),
                   write_json=write_json,
                   rename_project_data=devapp.rename_project_data)

# ---- a node's git, relayed --------------------------------------------------
# Push, fetch, pull and ls-remote from a session on a node, done in a
# repository of the controller's own rather than in the tree the session can
# write: gitrelay.py (B148).
import gitrelay                                                  # noqa: E402

gitrelay.configure(state=STATE, workspace=WORKSPACE,
                   push_record=lambda p: projects.load_push().get(p),
                   token_helper=projects.token_helper, parse_url=forges.parse,
                   host_of=forges.host_of, git_env=projects._git_env)



# Written by entrypoint.sh once every startup hook has finished. Named here as
# well as in lib/common.sh, which is the cost of the marker crossing the
# bash/python line; the comment there carries the reasoning.
BOOT_READY_FILE = Path(os.environ.get("BOOT_READY_FILE", "/run/builderbot-ready"))
BOOT_WAIT = 180
BOOT_GRACE = 300


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


# ---- bb doctor, cached for the Doctor card: doctor.py ----------------------
import doctor                                                    # noqa: E402

doctor.configure(run=run, wait_for_boot=wait_for_boot)


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


# A store's revisions(), recomputed only when its file moves.
#
# Those five functions each read and parse a whole state file, which was
# affordable on the fifteen-second poll they were written for and is not on
# the one-and-a-half-second one they moved to. The key is the file's mtime in
# nanoseconds, so a second write in the same second is still a miss — and a
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

    `projects` is what the page actually has open — the notebooks, which are
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
        nb_revs = _cached(STATE / "todos.json", todo.revisions)
        bug_revs = _cached(STATE / "bugs.json", bugs.revisions)
        test_revs = _cached(STATE / "tests.json", testreg.revisions)
        rule_revs = _cached(STATE / "rules.json", rules.revisions)
        pend_revs = _cached(STATE / "pending.json", pending.revisions)
    revs = {
        # The container itself. A restart invalidates everything a page holds.
        "boot": boot_id(),
        # One file each, so any write through any path moves the token — the
        # CLI's included, which no in-process counter would catch.
        "findings": _mtime(STATE / "findings-log.json"),
        "reports": findings.reports_mtime(),
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
        # The notebook's six halves. COUNTERS, not mtimes, and that is the
        # whole of why this is not three more stats: each of these panels
        # holds the number it last read, so it can tell somebody else's write
        # from the echo of its own — an mtime cannot, and a redraw a panel did
        # not need detaches the send box or the half-typed row under the
        # finger that opened it. testreg is the sharpest case: describing ONE
        # test deliberately does not move its counter, where writing the file
        # obviously moves its mtime.
        #
        # The memories are the one thing here that is not a file in the state
        # directory: they are files in an ACCOUNT's home, so that stamp is a
        # glob of one directory. Which is what `projects` is for — one open
        # notebook's worth rather than the whole share's, every second and a
        # half. home_for is memoised, so none of this shells out.
        revs[f"todo:{n}"] = (nb_revs.get(n) or {}).get("todo", 0)
        revs[f"bug:{n}"] = bug_revs.get(n, 0)
        revs[f"tests:{n}"] = test_revs.get(n, 0)
        revs[f"rules:{n}"] = rule_revs.get(n, 0)
        revs[f"pending:{n}"] = pend_revs.get(n, 0)
        if who is not None:
            revs[f"mem:{n}"] = memory.census(
                n, home=home_for(users.uid_of(who)))["rev"]
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
        "phone_asks": len(phone.requests_open(users.uid_of(who), users.is_admin(who))),
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
        "node_runners": runners.listing(),
        "reports": findings.REPORTS.is_dir(),
        "reports_mtime": findings.reports_mtime(),
        "findings_counts": findings.counts(ps),
        # ...and, for the row they land on, what those paths actually look
        # like. Order matters: this reads what the call above computed.
        "findings_heads": findings.heads(),
        # ...and whether there is a readable report at all, which is what the
        # Static analysis button and the Analysis tab ghost on.
        "reports_ok": findings.reports_ok(),
        # ...and when each report was written, so one left behind by a failed
        # scanner is visible rather than silently counted as current.
        "reports_ages": findings.reports_ages(),
        "doctor": doctor.payload(),
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
        # ...and whether it administers this controller, so the page can word
        # an empty Projects card for a user with nothing granted rather than
        # telling them the share is not mounted (16 Sep).
        "admin": bool(who) and users.is_admin(who),
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
        # Whether this account has read the getting-started guide, and
        # which image's changelog it acknowledged: the welcome panel opens
        # itself once for each — the guide on a first sign-in, the changelog
        # once per image update — and these are what make it once.
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
    ("prefix", "/api/status", "_get_status"),
    ("prefix", "/api/findings", "_get_findings"),
    ("prefix", "/api/profile", "_profile"),
    ("prefix", "/api/git", "_get_git"),
    ("prefix", "/api/changelog", "_get_changelog"),
    ("prefix", "/api/version", "_get_version"),
    ("prefix", "/api/artifacts", "_get_artifacts"),
    ("prefix", "/api/artifact?", "_get_artifact"),
    ("prefix", "/api/meta", "_get_meta"),
    ("prefix", "/api/welcome", "_get_welcome"),
    ("prefix", "/api/source?", "_get_source"),
    ("prefix", "/logs/download", "_get_logs_download"),
    ("prefix", "/api/phone", "_get_phone"),
    ("prefix", "/api/packages", "_get_packages"),
    ("prefix", "/api/users", "_get_users"),
    ("exact", "/api/v1/claude-login", "_claude_login"),
    ("prefix", "/api/v1/nodes", "_get_nodes"),
    ("prefix", "/api/v1/jobs", "_get_jobs"),
    ("prefix", "/api/docker", "_get_docker"),
    ("prefix", "/api/containers", "_get_containers"),
    ("prefix", "/api/project-job", "_get_project_job"),
    ("prefix", "/api/trash", "_get_trash"),
    ("prefix", "/api/claude-now", "_get_claude_now"),
    ("prefix", "/api/todo", "_get_todo"),
    ("prefix", "/api/rules", "_get_rules"),
    ("prefix", "/api/global-rules", "_get_global_rules"),
    ("prefix", "/api/preamble", "_get_preamble"),
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
    ("prefix", "/api/lock", "_lock"),
    # NOT /api/pin, which is the command pin and has been since long before
    # this: startswith() means a route added above it silently takes every
    # path it prefixes, and both handlers were called _pin, so the later
    # definition quietly replaced the earlier one in the class body too.
    ("prefix", "/api/project-pin", "_project_pin"),
    ("prefix", "/api/project-auth", "_project_auth"),
    ("prefix", "/api/container", "_container"),
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
    ("prefix", "/api/cards", "_cards"),
    ("prefix", "/api/pin", "_pin"),
    ("prefix", "/api/claude-md", "_claude_md"),
    ("exact", "/api/reset", "_reset"),
    ("prefix", "/api/create", "_create"),
    ("prefix", "/api/profile", "_profile"),
    ("prefix", "/api/git", "_git_act"),
    ("prefix", "/api/unlink", "_unlink"),
    ("prefix", "/api/link", "_link"),
    ("prefix", "/api/project-job", "_project_job"),
    ("prefix", "/api/todo", "_todo"),
    ("prefix", "/api/users", "_users"),
    ("prefix", "/api/packages", "_packages"),
    ("prefix", "/api/logs", "_logs"),
    ("prefix", "/api/idle", "_idle"),
    ("prefix", "/api/settings", "_settings_post"),
    ("prefix", "/api/rules", "_rules"),
    ("prefix", "/api/global-rules", "_global_rules"),
    ("prefix", "/api/pending", "_pending"),
    ("prefix", "/api/memory", "_memory"),
    ("prefix", "/api/prefs", "_prefs_post"),
    ("prefix", "/api/devapp", "_devapp"),
    ("prefix", "/api/changelog", "_changelog"),
    ("prefix", "/api/version", "_version"),
    ("prefix", "/api/artifacts", "_artifacts"),
    ("prefix", "/api/nodelog", "_nodelog"),
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
        wrote it — see _who_raw for how the principal itself is proved."""
        u = self._who_raw()
        _writing.who = u
        return u

    def _who_raw(self):
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
        the check is a real one rather than a guess: the node that signed each
        account in reported which Anthropic account it was, and that record is
        what this compares.

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
        # Every Claude session is on a node now (R47), so this container has
        # no tmux socket to ask. What it has is the census: the node reports
        # its session names on every heartbeat, and a name says whose it is.
        # The rule is made from the last thing the node said — a few seconds
        # stale, which two people starting in the same instant could slip
        # through, and the alternative is not making it at all.
        t = session_target(project, claude=True)
        if t["where"] != "node":
            return ""
        mine = claude_auth(home=home_for(uid)).get("email") or ""
        if not mine:
            return ""                     # not signed in: bb-tty says so, better
        if settings.get("claude_shared_login"):
            return ""                     # the Settings tab stood the refusal down
        store = users.load()["users"]
        by_uid = {u.get("uid"): n for n, u in store.items() if u.get("uid")}
        owner = users.owner_name()
        want = claude_session(project)
        here = [s for s in node_tmux_sessions()
                if s.get("node_id") == t["id"] and tmux_base(s["name"]) == want]
        whose = {s["name"]: tmux_owner(s["name"]) or users.uid_of(users.get(owner or ""))
                 for s in here}
        # Our own session, already running: this is a reattach, and a rule
        # about starting a SECOND session has nothing to say about it. Asked
        # first, because the loop below used to meet another account's
        # session before reaching ours and refuse us our own tab (B141).
        if uid in whose.values():
            return ""
        for sess in here:
            other = whose[sess["name"]]
            if not other:
                continue
            if (claude_auth(home=home_for(other)).get("email") or "") == mine:  # noqa: E501
                return (f"{by_uid.get(other, 'another account')} already has a "
                        f"Claude session on {project} signed in to {mine}. Two "
                        "sessions on one Anthropic account share its limits, "
                        "and nothing afterwards can say which of them did "
                        "what, so this one waits for that to end.")
        return ""

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
            return self._term_notice(refused, 403)
        held = self._claude_held(self.path[len("/term"):])
        if held:
            # 409, not 403: nothing is wrong with the credential, the thing
            # asked for is taken. The name is the whole value of the record —
            # "somebody else has it" tells you nothing you can act on.
            return self._term_notice(held, 409)
        # Where this terminal lives (roadmap #24, phase 10b): a project bound
        # to a node whose session half is up is relayed to THAT machine's
        # ttyd — the same two ports, the same bb-tty, with the account and
        # its token stamped into the URL — and everything else stays on the
        # loopback. session_target says why a node cannot take one, and the
        # row's button carries the same sentence.
        rest0 = self.path[len("/term"):]
        # A SHELL is this container's own and always has been: a tree to look
        # at, the linters, git. Only a CLAUDE session needs a node, because
        # only Claude is the thing this container no longer carries — so the
        # question is asked about a claude: argument and about nothing else.
        arg0 = _term_arg(rest0)
        target = session_target(_arg_project(arg0),
                                claude=arg0.startswith("claude:"))
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

    def _static(self, rel, ctype):
        """A file that IS the app — index.html and the tab scripts — served so
        a browser notices when the image changes.

        They went out with no validator and no cache directive at all, which
        leaves it to the browser's own heuristics: a phone could hold the old
        page across a container update and show yesterday's dashboard against
        today's server, with nothing on screen admitting it. `no-cache` is not
        "do not store", it is "ask me first" — so the usual answer stays a 304
        of a few bytes and the new bytes arrive the moment the file changes.
        The tag is the file's own size and mtime, which is what changes when
        an image does, and costs one stat rather than a hash of 700KB.
        """
        try:
            st = (HERE / rel).stat()
            body, zipped = self._gzip((HERE / rel).read_bytes())
        except OSError:
            return self._json({"error": "not found"}, 404)
        tag = f'W/"{st.st_size:x}-{st.st_mtime_ns:x}"'
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
                    "/tab-users.js", "/tab-phone.js", "/tab-profile.js",
                    "/nb-git.js", "/nb-artifacts.js", "/nb-analysis.js", "/nb-rules.js",
                    "/nb-tests.js", "/nb-bugs.js", "/nb-pending.js", "/nb-roadmap.js",
                    "/nb-memory.js", "/nb-history.js"):
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

    def _get_findings(self):
        """GET /api/findings."""
        return self._json(findings.payload(project_list(self._who())))

    def _get_git(self):
        """GET /api/git."""
        # The notebook's Git view (roadmap R36): plumbing reads on the
        # project's tree, for a project this account may see. A sha
        # and a path are checked in git.py against what the repository
        # itself reports; nothing from the query reaches a command line
        # as anything else.
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        what = q.get("what", [""])[0]
        try:
            n = int(q.get("n", ["0"])[0])
        except ValueError:
            n = 0
        r = gitview.payload(name, what, sha=q.get("sha", [""])[0],
                            path=q.get("path", [""])[0], n=n,
                            branch=q.get("branch", [""])[0])
        if what in ("", "all") and not r.get("error"):
            # What the network bar may offer: a remote to talk to, and
            # the project's push rights, granted once in the clone dialog.
            r["remote"] = gitview.has_remote(WORKSPACE / name)
            r["push"] = projects.may_push(name)
            # The host by its name (GitHub, Gitea, or the machine's own),
            # so the view can say "in step with GitHub" and not "origin".
            url = gitview.remote_url(WORKSPACE / name)
            at = forges.parse(url) if url else None
            f = forges.forge_of(at["host"]) if at else None
            r["host"] = {"name": (f["name"] if f and f["id"] != "git" else (at or {}).get("host", "")),
                         "kind": (f or {}).get("kind", "")}
        return self._result(r)

    def _get_changelog(self):
        """GET /api/changelog."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        d = version._sub(name, q.get("component", [""])[0])
        if d is None:
            return self._json({"error": "no such component"}, 400)
        # The text for reading and the same section as structure for
        # editing: one fetch, because the editor shows both and a second
        # round trip would let them disagree about what is in the file.
        return self._json({"text": changelog.read(d),
                           "groups": changelog.groups(d)})

    def _get_version(self):
        """GET /api/version."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(version_payload(name))

    def _get_artifacts(self):
        """GET /api/artifacts."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        # `devapp` is the main instance, which is what the row shows;
        # `devapps` is every instance, which the manager reads. Both, so
        # the row keeps working while the manager grows around it.
        # One read scope for the row and the manager's list: on an
        # agent node each is a probe job, and both ask the same daemon.
        with devapp.read_scope():
            dev = {"devapp": devapp.state(name), "devapps": devapp.states(name)}
        return self._json({"artifacts": artifacts_of(name),
                           # What this project can and cannot do off this
                           # box, said on the tab that lists what it built.
                           "build": build_state(name)} | dev
                          | phone.summary(prefs.get(name)["node"], users.uid_of(self._who()),
                                          nodes.node(prefs.get(name)["node"])
                                          if prefs.get(name)["node"] and not NODES_OK else None))

    def _get_artifact(self):
        """GET /api/artifact."""
        # The download. Resolved and prefix-checked in artifacts.resolve:
        # a symlink inside dist/ must not turn this into a file server for
        # the whole box.
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        rel = q.get("path", [""])[0]
        if self._not_project(name):
            return
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

    def _get_meta(self):
        """GET /api/meta."""
        # What the companion app asks first: the surface number this
        # dashboard serves, the image it is, and where a newer app is.
        return self._json({"api": APP_API, "version": image_stamp().get("version") or "",
                           "image": image_stamp().get("rev") or "",
                           "built": image_stamp().get("built") or "", "apk": app_apk()})

    def _get_welcome(self):
        """GET /api/welcome."""
        # BuilderBot's own changelog, for the welcome panel: the file
        # beside this checkout (CHANGELOG.md two levels up, which is
        # /opt/builderbot/CHANGELOG.md in the image and the repository's
        # under bb dashboard dev), and where this account last looked
        # (the image commit it acknowledged), so the panel can draw a
        # line under what is new since.
        text = changelog.read(Path(__file__).resolve().parents[2])
        seen = str(users.prefs(self._who()).get("image_seen") or "")
        # Trimmed to what is unreleased plus the newest minor's releases:
        # this panel answers "what changed in the build in front of me",
        # and the file behind it grows for the life of the project. What
        # it left out is counted, not hidden.
        kept, held, series = changelog.since_minor(
            changelog.sections(text) if text else [])
        return self._json({"sections": kept, "held": held, "series": series,
                           "present": text is not None, "seen": seen})

    def _get_source(self):
        """GET /api/source."""
        # The code base as a zip, from the Artifacts tab: what git
        # tracks and would track, never .git, dist/ or what .gitignore
        # hides. A person's download, so a session's token is refused:
        # a session has the tree already.
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if (self._who() or {}).get("session"):
            return self._json({"error": "a session has the tree already"}, 403)
        if self._not_project(name):
            return
        try:
            got = artifacts.source_zip(name)
        except (OSError, subprocess.SubprocessError) as e:
            return self._json({"error": str(e)}, 500)
        if got is None:
            return self._json({"error": "no such project"}, 404)
        if isinstance(got, dict):
            return self._json(got, 413)
        fname, data = got
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return None

    def _get_logs_download(self):
        """GET /logs/download."""
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

    def _get_packages(self):
        """GET /api/packages."""
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

    def _get_users(self):
        """GET /api/users."""
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

    def _get_nodes(self):
        """GET /api/v1/nodes."""
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

    def _get_jobs(self):
        """GET /api/v1/jobs."""
        # One job with its log so far (?id=), or the recent ones,
        # narrowed by ?node=, ?project=, ?type=, ?active=1, at most ?n=.
        # The Jobs tab's whole read surface, and a test's.
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        jid = q.get("id", [""])[0]
        # A job and its log are the project's: an account reads the ones
        # on projects it may see, and a job with no project (a node's
        # own: an update, a store move) is an administrator's. Same
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

    def _get_docker(self):
        """GET /api/docker."""
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
        # The branches each listed project could be built from. Here
        # rather than per row: they come from one `for-each-ref` per
        # project, and the picker needs them before anybody presses.
        got["refs"] = {p: devapp.refs_of(p)
                       for p in {i["project"] for i in got.get("instances") or []}
                       if not devapp.is_file_source(p)}
        # An instance of a project this account was not given is one of
        # the projects hidden from it, wearing a different hat; and a
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
        return self._json({"model": claude_model_now(WORKSPACE / name)})

    def _get_todo(self):
        """GET /api/todo."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        live = sessions_anywhere()
        return self._json({"project": name} | self._todo_state(name, live))

    def _get_rules(self):
        """GET /api/rules."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(rules.payload(name))

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
        return self._json(preamble.payload(name))

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
        for how, route, name in POST_ROUTES:
            if (path == route) if how == "exact" else path.startswith(route):
                return getattr(self, name)(req)
        self._json({"error": "not found"}, 404)

    def _reset(self, req):
        """POST /api/reset."""
        # Start over at onboarding: the controller's own state moved
        # aside (accounts, nodes, project settings, git tokens, the
        # notebook, memories, logs), project files untouched, and the
        # dashboard re-executes itself so the next page is Create the
        # owner. The confirm word is the whole of the safety: this is
        # an administrator typing "reset" into a red box.
        if self._refused("admin"):
            return None
        if str(req.get("confirm") or "") != "reset":
            return self._json({"error": "type reset to confirm; nothing was changed"}, 400)
        try:
            moved = settings.reset_state(STATE)
        except OSError as e:
            return self._json({"error": f"could not move the state aside: {e}"}, 500)
        # The runner tokens are root's, behind the helper: forgotten
        # there, since the nodes they were for are being forgotten here.
        forgot = runners.reset()
        kept = [k for k in moved["kept"] if not (k == "runner-tokens" and forgot)]
        print(f"dashboard: {self._principal()} reset this controller; the old state is in "
              f"{moved['dest']}" + (f"; kept: {', '.join(kept)}" if kept else ""), flush=True)
        threading.Timer(1.0, lambda: os.execv(sys.executable, [sys.executable, *sys.argv])).start()
        return self._json({"ok": True, "moved_to": str(moved["dest"]), "kept": kept})

    def _settings_post(self, req):
        """POST /api/settings."""
        # The Settings tab's fields (R29): an administrator's, validated
        # and applied by the store; the answer is the tab's next drawing.
        if self._refused("admin"):
            return
        r = settings.set_many(req.get("set") or {})
        if r.get("error"):
            return self._json(r, 400)
        return self._json(r | settings.payload())

    def _prefs_post(self, req):
        """POST /api/prefs: a project's settings dialog."""
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
        # reaches every other project there.
        if "node" in req and self._refused("node", name):
            return
        r = prefs.set_prefs(name, model=req.get("model"),
                            effort=req.get("effort"),
                            node=req.get("node"),
                            build=req.get("build"),
                            test=req.get("test"), outputs=req.get("outputs"),
                            gate=req.get("gate"), gitpol=req.get("gitpol"),
                            devbuild=req.get("devbuild"),
                            devtest=req.get("devtest"),
                            color=req.get("color"),
                            workspace=WORKSPACE)
        # The restart is asked for by the dialog, which is where the
        # operator was told what it costs, and never inferred here from the
        # change alone, because the same write happens when nothing is
        # running and there is nothing to interrupt.
        if not r.get("error") and req.get("restart"):
            r |= end_claude(name)
        return self._result(r)

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
        if act == "vm-xml":
            # What a new sandbox VM is made from, for whichever hypervisor is
            # picked. No node exists yet and nothing is written: a render of
            # a shipped machine with an identity of its own, which the
            # operator pastes into their manager or runs on its host.
            return self._json(vmtemplate.render(
                name=field(req, "name"), cores=req.get("cores"),
                memory_gb=req.get("memory_gb"), iso=field(req, "iso"),
                uid=field(req, "uuid"), hw=field(req, "mac"),
                hv=field(req, "hv"), disk_gb=req.get("disk_gb"),
                vmid=req.get("vmid")) | {"catalog": vmtemplate.catalog()})
        if act == "add":
            r = nodes.node_add(self._principal(), field(req, "name"),
                               field(req, "addr"),
                               req.get("capabilities"),
                               field(req, "pool") or "default")
        elif act == "update":
            r = nodes.node_update(self._principal(), nid, req.get("fields") or {})
        elif act == "uninstall":
            r = nodes.node_uninstall(self._principal(), nid)
        elif act in ("drain", "online", "retire"):
            r = nodes.node_state(self._principal(), nid,
                                 {"drain": "draining", "online": "online",
                                  "retire": "retired"}[act])
        elif act in ("lock", "unlock"):
            # System changes locked to the node's own console: Apply
            # storage, Apply network and a root command refused while on.
            r = nodes.node_lock(self._principal(), nid, act == "lock")
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
        elif act == "log-grant":
            # Which nodes' machine logs a session on this node may read. An
            # administrator's, like the rest of this handler — a session that
            # could grant itself the journal is not a boundary.
            r = nodes.node_log_grant(self._principal(), nid,
                                     req.get("from") if isinstance(req.get("from"), list) else [])
        elif act == "apply":
            r = nodes.node_apply(self._principal(), nid, field(req, "what"))
        elif act == "runner":
            # One of the node's runners (phase 7, one per git host): a system
            # job, minting from the token stored for that runner. The URL is
            # the record's, written when the token was, so the token and the
            # address it was made for cannot come apart.
            slot = re.sub(r"[^a-z0-9.-]", "", field(req, "slot"))[:60]
            r = nodes.node_runner(self._principal(), nid, slot, bool(req.get("want", True)),
                                  req.get("labels"),
                                  token=slot in runners.tokens().get(nid, set()))
        elif act == "runner-token":
            # The node's runner token: forge and URL onto the record, the
            # token itself into the root-only store through the helper.
            # Not forges.parse: that wants owner/repo, and a runner's address
            # is as often an organization, one segment deep.
            url = field(req, "url").strip()
            # http as well as https: a Gitea on the LAN, the docker-compose
            # shape, serves plain http, and the enrollment already makes the
            # same trade with a note. GitHub is https whatever is typed.
            at = re.fullmatch(r"https?://([A-Za-z0-9.-]+(?::[0-9]{1,5})?)/[A-Za-z0-9._/-]+", url)
            if not at:
                r = {"error": "the URL is the https address of the repository or "
                              "organization the runner registers with (http is "
                              "accepted for a forge on your own network)"}
            elif not nodes.node(nid):
                r = {"error": "no such node"}
            else:
                # The forge from the picker when it says, else from the host:
                # a private Gitea nobody has linked a project to yet is
                # "another git host" to the catalog, and the picker is how
                # the operator says otherwise.
                forge = field(req, "forge")
                if forge not in ("github", "gitea"):
                    forge = forges.forge_of(at.group(1)).get("kind") or "git"
                slot = nodes.runner_slot(url)
                r = runners.store(nid, slot, url, forge, str(req.get("token") or "").strip())
                if not r.get("error"):
                    r = nodes.node_runner_url(self._principal(), nid, slot, url, forge,
                                              req.get("labels") if isinstance(req.get("labels"), list) else None)
                    r["slot"] = slot
        elif act == "runner-forget":
            slot = re.sub(r"[^a-z0-9.-]", "", field(req, "slot"))[:60]
            r = runners.forget(nid, slot)
            if not r.get("error"):
                r = nodes.node_runner_forget(self._principal(), nid, slot)
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
        return self._result(r)

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
        return self._result(r)

    def _claude_login(self, req=None):
        """This account's Claude identity, both directions (R47) — and no
        credential in either.

        GET is a node asking who this BuilderBot account is bound to and
        what the generation is; POST is a node saying what it signed in as.
        The grant itself never moves: each machine signs in for itself and
        refreshes the one it holds, because a refresh ROTATES the refresh
        token and two copies of one grant sign each other out (bug #64,
        B100). claudegrant.py's header is the long version.

        Only a session token minted FOR an account speaks here — the one the
        terminal proxy stamps into a node-bound terminal's URL — and only for
        that account: the account is in the token, signed, not in a
        parameter.
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
        # No credential leaves here, because none is kept here: a machine
        # signs in for itself and keeps the grant it alone refreshes. What a
        # node gets is the account's IDENTITY and the generation to compare
        # its own against — behind means sign yourself out.
        st = claudegrant.state(home)
        return self._json({"email": st["email"], "plan": st["plan"],
                           "gen": st["gen"], "signed_in": st["signed_in"],
                           "nodes": len(st["nodes"])})

    def _claude_login_put(self, req, home):
        """A node reporting what it is signed in AS — never the grant itself.

        Which node is reporting is not taken from the request: it is the node
        of the session's own project, which the token proves. A machine that
        could name itself could bind the account to whatever it liked.
        """
        proj = (self._who() or {}).get("session") or ""
        # A sign-in job's own token names the node it was queued on rather
        # than a project: the controller minted it, signed, for that job.
        if proj.startswith("node:"):
            nid = proj[5:] if nodes.node(proj[5:]) else ""
        else:
            nid = (prefs.get(proj) or {}).get("node") or "" if proj else ""
        if not nid:
            return self._json({"error": "a sign-in is reported by a session on the "
                                        "node it happened on"}, 400)
        r = claudegrant.report(home, nid, req.get("email") or "",
                               req.get("plan") or "",
                               signed_in=bool(req.get("signed_in", True)))
        _auth.clear()
        return self._result(r)

    def _hook(self, req):
        """What a session's hooks have to say, from a NODE (roadmap #24).

        bb-work-note and bb-prompt-relay write this container's /config
        when they run here — the overlap notes, the project's chat feed. On
        a node there is no /config, so they post the same four things to
        this endpoint with the session's token, and the same modules write
        them: `note` (a file the session is about to edit, with a guess at
        the symbol; answers who else has it open), `asked` (what the person
        typed, into the project feed), `started` (the session began — the
        only place that is announced from, since every session is on a
        node), and `seen` (what the notebook has done since
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
        # Push, fetch and pull write with git, and git wants an author; a
        # policy read and an ls-remote do not (B128).
        if argv and argv[0] == "git" and argv[1:2] not in (["policy"], ["ls-remote"]) \
                and users.uid_of(me) and not users.git_ready(me):
            return self._json({"error": "no name and email for commits yet — set them on "
                                        "your Profile (the gear in the dashboard's header) first"}, 403)
        if not argv or argv[0] not in RELAY_VERBS:
            return self._json({"error": f"bb {argv[0] if argv else ''} is not relayed — "
                               "it answers for the machine the session is on"}, 400)
        # A rule's check is a command, and a session may write its own rule's
        # check, so it runs on the machine the session is on and never here
        # (B152). A node's bb keeps it local; this refuses one sent anyway.
        if argv[:2] == ["rules", "check"]:
            return self._json({"error": "bb rules check runs on the machine the session is on, "
                                        "not on the controller: run it there"}, 400)
        project = field(req, "project") or me.get("session") or ""
        if me.get("session") and project != me["session"]:
            return self._json({"error": "this session's token is for another project"}, 403)
        if not project or (WORKSPACE / project).name != project \
                or not (WORKSPACE / project).is_dir():
            return self._json({"error": "not a project"}, 400)
        if self._refused("bb", project):
            return None
        # Push rights first, for everybody: a project cloned without them
        # does not push, whatever its tree says. The refusing pre-push hook
        # in a read-only clone is a file a session can change, so this is
        # the check that holds (B149), the same one the Git view makes.
        if argv[:1] == ["git"] and argv[1:2] and argv[1] in gitrelay.VERBS and gitrelay.bad_args(argv[2:]):
            return self._json({"error": gitrelay.bad_args(argv[2:])}, 400)
        if argv[:2] == ["git", "push"] and not projects.may_push(project):
            return self._json({"error": "this project has no push rights: they are granted "
                                        "in the clone dialog, once"}, 403)
        # ...and under the project's git policy (the Git view, roadmap R36):
        # a session may push its own branch unless told not to, and may not
        # push to main unless told it may. Judged here because here is
        # where the push runs; a local commit or merge is not this door's.
        if argv and argv[0] == "git" and argv[1:2] == ["push"] and me.get("session"):
            pol = prefs.get(project)["gitpol"]
            if pol.get("push") == "deny":
                return self._json({"error": "this project's git policy does not let a session "
                                            "push — the operator pushes from the Git view"}, 403)
            if pol.get("main") == "deny":
                # Read out of the tree's files, never by running git in it
                # (B148): the branch HEAD names and which of main or master
                # exists.
                repo = WORKSPACE / project
                try:
                    head = gitrelay.head(repo / ".git").removeprefix("refs/heads/")
                    have = gitrelay.refs(repo / ".git")
                except gitrelay.Refused as e:
                    return self._json({"error": str(e)}, 400)
                main = next((b for b in ("main", "master") if f"refs/heads/{b}" in have), "main")
                spec = [a for a in argv[2:] if not a.startswith("-")]
                to_main = any(a == main or a.endswith(":" + main) or a.startswith(main + ":") for a in spec) \
                    or (not spec and head == main) or (len(spec) == 1 and head == main)
                if to_main:
                    return self._json({"error": f"this project's git policy does not let a session "
                                                f"push to {main} — push your branch and say so, "
                                                "and the operator merges from the Git view"}, 403)
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
        # git's network half never runs in the tree a session can write
        # (B148): the controller does it in a repository of its own and
        # hands the tree's half back to the node's bb as `apply`.
        if argv[0] == "git" and argv[1:2] and argv[1] in gitrelay.VERBS:
            r = gitrelay.run(project, str(cwd), argv[1], argv[2:])
            if "error" in r:
                return self._json(r, 400)
            return self._json({"code": r["code"], "out": r["out"][-200000:], "err": r["err"][-20000:],
                               **({"apply": r["apply"]} if r.get("apply") else {})})
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
        # Never from a session (R35). A session is on its project's node and
        # runs these verbs where it is, inside its view; a job runs as the
        # node's enrolled account, outside every view and in the docker
        # group, so a session token that could queue one would read every
        # project on the machine and be root on it. Measured on
        # bb-dev-sandbox, 16 Sep, before this refusal.
        if (self._who() or {}).get("session"):
            return {"error": "a session runs bb run, build, test and emu where it is, on its "
                             "project's node; a job would run outside the session's view, "
                             "so a session cannot queue one"}, 403
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
            return self._result(r)
        if verb == "download":
            # The file itself. Any token gets it — the provisioner fetches
            # it with the enroll token before there is a node — and so does
            # the operator's own login, for reading it in a browser.
            if auth.get("error") and not self._authed():
                return self._json({"error": auth["error"]}, 401)
            what = q.get("what", [""])[0]
            if what in ("provisioner", "provisioner-macos"):
                # The provisioner too, from the copy this image carries: the
                # Enroll dialog's command names it, and a machine with an
                # enroll token is what has to get it (B133), a Mac's as well
                # as a Linux machine's (B150).
                p = workspace.REPO / "nodes" / ("provision-macos.sh" if what == "provisioner-macos"
                                                else "provision-linux.sh")
                body = p.read_bytes() if p.is_file() else b""
                if not body:
                    return self._json({"error": "this controller ships no provisioner"}, 404)
                self.send_response(200)
                self.send_header("Content-Type", "text/x-shellscript; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return None
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
            return self._result(r)
        if auth["kind"] != "node":
            return self._json({"error": "an enrollment token enrolls, and "
                                        "nothing else"}, 403)
        nid = auth["node"]
        if verb == "runner-token":
            # A registration or removal token for the node's runner, minted
            # now from the root-only stash and never stored: the PAT stays
            # here, the hour-long token goes to the node that asked.
            kind = "remove" if field(req, "kind") == "remove" else "registration"
            # An agent that predates slots names none: the node's one runner.
            slot = re.sub(r"[^a-z0-9.-]", "", field(req, "slot"))[:60]
            if not slot:
                only = list(nodes.runners_of(nodes.node(nid) or {}))
                slot = only[0] if len(only) == 1 else ""
            r = runners.mint(kind, nid, slot, field(req, "runner_id"))
            nodes.audit(auth["principal"], "runner-token", nid, {"kind": kind, "ok": not r.get("error")})
            return self._result(r)
        if verb == "hello":
            r = nodes.hello(nid, req.get("census"), addr,
                            field(req, "version"), field(req, "digest"),
                            req.get("running"))
        elif verb == "work":
            # The heartbeat and the long-poll in one: the sample is recorded
            # first, so a node that is only ever waiting still reads as
            # alive and its numbers still move; then the request is held.
            nodes.heartbeat(nid, req.get("sample"), addr, req.get("running"))
            self._node_logins(nid, (req.get("sample") or {}).get("logins")
                              if isinstance(req.get("sample"), dict) else None)
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
        return self._result(r)

    def _signin(self, req):
        """Start a sign-in, or stop the one that is running."""
        _auth.clear()               # every home: the flow may have changed any
        if field(req, "action") == "cancel":
            return self._json(signin.cancel() | {"signin": signin.state()})
        # WHERE it runs. Claude Code is installed where sessions are, which
        # is a node — so the flow goes there, on the node the operator picked
        # or the one node there is. There is no other answer: this container
        # carries no Claude Code, so with no node the refusal below is it.
        uid = users.uid_of(self._who())
        want = field(req, "node")
        # A node that runs SESSIONS, which is the same test session_target
        # makes: Claude Code is installed for the session account, the
        # credential lands in that account's home, and a node with no session
        # half has neither. Not merely "online" — a build node that runs no
        # sessions has nowhere for a login to live.
        live = [] if NODES_OK else [
            n for n in nodes.node_list()
            if n["kind"] == "agent" and n["state"] == "online"
            and n.get("live") is not False
            and ((n.get("reported") or {}).get("session") or {}).get("up")]
        pick = next((n for n in live if want in (n["id"], n["name"])), None) \
            if want else (live[0] if len(live) == 1 else None)
        if pick:
            tok = users.mint_session(f"node:{pick['id']}", ttl=1800, uid=uid)
            return self._json(signin.start_on_node(nodes, pick["id"], uid, pick["name"], token=tok)
                              | {"signin": signin.state()})
        if live:
            return self._json({"error": "which node should the sign-in run on? "
                                        + ", ".join(n["name"] for n in live),
                               "nodes": [n["name"] for n in live]}, 400)
        # And nowhere else. Claude Code is installed for the account that runs
        # sessions, which is a node's; this container carries none, so there
        # is no flow here to fall back to and saying so is the whole answer.
        return self._json({"error": "no node is running sessions, and a Claude "
                                    "sign-in runs on the machine Claude is "
                                    "installed on. Enroll one on the Nodes tab, or "
                                    "wait for one to come back"}, 400)

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
        code = re.split(r"https?://", code, maxsplit=1)[0]
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
        return self._result(r | {"signin": signin.state()})

    def _signout(self, req):
        """Sign this account out of Claude, on every machine it is on.

        There is nothing here to delete — the credentials are the nodes' —
        so what this does is move the generation and clear the record. Each
        node compares generations on its next check and signs ITSELF out
        when its own is behind, which is what reaches one that is not
        listening: being signed out has no date, and a counter does.
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
        # the bare one is the owner's. Every node's sessions as well as this
        # container's — a conversation runs on a node now, and it is exactly
        # the one the sign-out would pull the credential out from under.
        busy = sorted(n for n in (x["name"] for x in
                                  tmux_sessions() + node_tmux_sessions())
                      if tmux_base(n).startswith("claude-")
                      and (tmux_owner(n) or users.uid_of(
                          users.get(users.owner_name() or ""))) == me)
        if busy:
            # Said as projects, not tmux names: "u_3deb3420~claude-hello"
            # named nothing a person recognises, and every one listed is
            # the asker's own.
            projs = sorted({tmux_base(n)[len("claude-"):] for n in busy})
            return self._json({"error": "end your Claude session"
                               + ("s" if len(projs) > 1 else "") + " on "
                               + ", ".join(projs) + " first (Sessions, or the tab's Close)"}, 409)
        # In the asking account's home, like the sign-in: signing out is
        # signing THIS account out, and the credential is in their ~/.claude.
        #
        # The credential goes and the generation moves. That second half is
        # what makes this reach the NODES: each compares generations on its
        # next sync — every connection, every prompt — and adopts what the
        # controller has, which is now nothing. A node that is offline does it
        # when it comes back, because the node is the one that asks; there is
        # no queue to drain and nothing to deliver.
        home = home_for(users.uid_of(self._who()))
        r = claudegrant.sign_out(home)
        _auth.clear()
        if r.get("error"):
            return self._json(r, 500)
        return self._json({"ok": True, "gen": r["gen"],
                           # What it reaches, said rather than assumed: a node
                           # that is not dialing in signs itself out when it
                           # comes back, and the sentence should not pretend
                           # they all go at once.
                           "nodes": [(nodes.node(i) or {}).get("name") or i
                                     for i in r["nodes"]] if not NODES_OK else [],
                           "auth": claude_auth(home=home)})

    def _todo(self, req):
        """Add, send, edit or drop one item on a project's list.

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
        if (bad := locked_out(name)):
            return self._json(bad, 409)
        live = sessions_anywhere()
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
        elif act == "restore":
            r = todo.restore(name, req.get("id"), at=req.get("at"), who=who)
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
        session = todo.claude_session(name)
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
        out = phone.payload(users.uid_of(self._who()), node=node, probe=probe,
                            admin=users.is_admin(self._who()),
                            project=(self._who() or {}).get("session") or "")
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
            return self._result(r)
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
        # Shown under a project's notebook as well as here, when asked:
        # only a project this account can see, or nothing.
        under = field(req, "for")
        if under and self._not_project(under):
            return
        r = devapp.create_container(name, req.get("compose") or "",
                                    req.get("env") or "", field(req, "node"), under)
        return self._result(r)

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
            return self._result(r)
        if act == "clear":
            return self._json(logs.clear())
        return self._json({"error": f"unknown action: {act}"}, 400)

    def _idle(self, req):
        """The idle rule for Claude sessions (idle.py): minutes, 0 for never.
        Operator-only, like the log policy beside it."""
        if self._refused("admin"):
            return
        r = idle.set_minutes(req.get("minutes"))
        return self._result(r)

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
        if act not in ("starter", "state", "rebuild", "abort", "test") \
                and self._refused("docker-write"):
            return None
        # A SESSION is a further question, and the answer is a per-project
        # dial with the notebook's own three words. Rebuild runs the project's
        # own Dockerfile and brings the container up on the node's daemon: for
        # a project whose loop is "change it, rebuild it, look at it" that is
        # exactly what you want a session doing; `ask` puts the reason in
        # front of a person first; `deny`, the default, keeps the button the
        # operator's. The read verbs are nobody's secret.
        #
        # It governs rebuild and abort and NOTHING else, because nothing else
        # ever reaches here from a session: new, remove, env and route are
        # docker-write above, which a session's principal never has. So the
        # dial is about running the code, never about creating a container.
        # A test run is not on the rebuild dial: it runs the project's own
        # test command inside a container that is already up, which a
        # session could run on the node anyway (roadmap R48).
        if act not in ("starter", "state", "test") and (self._who() or {}).get("session"):
            mode = prefs.get(name)["devbuild"]
            if mode == "deny":
                return self._json({"error": "rebuilding this project's dev instance is the "
                                            "operator's — its row on the Docker tab has "
                                            "the dial that hands it over"}, 403)
            if mode == "ask" and act == "rebuild":
                # Aborting is not asked about: it stops a build this session
                # was already allowed to start, and a running build nobody
                # can stop is worse than one nobody approved.
                acct = users.account_of(self._who()) or {}
                want = field(req, "instance") or devapp.MAIN
                r = phone.ask_rebuild(
                    field(req, "why"), name, want, devapp.pname(name, want),
                    asker_uid=str(acct.get("uid") or ""),
                    asker_name=str(acct.get("name") or ""),
                    asker_admin=users.is_admin(acct))
                return self._result(r)
        if act not in ("starter", "state") and name in {p["name"] for p
                                                        in project_list(self._who())} \
                and self._readonly(name):
            return None
        # Which instance of that project. Absent means the one every project
        # has always had, so a caller that predates instances still works and
        # a request that names a strange one is answered rather than obeyed:
        # the name decides a compose project and a data directory, and those
        # are not places to let an arbitrary string reach.
        # A request naming no instance means the project's only one, when
        # it has exactly one: BuilderBot's own is called builderbot-dev, and
        # bb devapp from a session was answering for a `main` that did not
        # exist (15 Sep). With several, `main` as before; bb takes
        # --instance for that.
        inst = field(req, "instance") or devapp.only_instance(name)
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
            under = field(req, "for")
            if under and self._not_project(under):
                return
            r = devapp.create_instance(name, inst, field(req, "node"),
                                       "" if under == name else under)
            if not r.get("error") and field(req, "ref"):
                # Pinned before the build the dialog starts, or the first one
                # comes from the project's checkout and the row says otherwise.
                p = devapp.set_ref(name, r["instance"], field(req, "ref"))
                if p.get("error"):
                    return self._json(p, 400)
            if not r.get("error") and isinstance(req.get("text"), str) \
                    and req["text"].strip():
                # Written before the build that follows, so the first one has
                # the env it needs instead of stopping at the gate and asking
                # for it afterwards.
                devapp.write_env(name, req["text"], r["instance"])
            return self._result(r)
        if inst not in devapp.instances(name):
            return self._json({"error": f"no instance {inst} of {name}"}, 400)
        if act == "remove":
            r = devapp.remove_instance(name, inst)
            return self._result(r)
        if act == "ref":
            # Which branch this instance builds from. `docker-write` above
            # has already had its say, so this is an administrator's like
            # every other thing that changes what a container IS.
            r = devapp.set_ref(name, inst, field(req, "ref"))
            return self._result(r)
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
        elif act == "test":
            # The command is the project's own, from its settings, with the
            # same fallback bb test uses when nothing is set.
            cmd = prefs.get(name)["test"] or prefs.test_default(name, WORKSPACE)
            r = devapp.test(name, inst, cmd, [str(a) for a in (req.get("args") or [])][:32])
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
        if self._not_project(name):
            return
        act = field(req, "action")
        if act == "bump":
            r = version.bump(name, field(req, "part"), by="operator", env=users.git_env(self._who()),
                             comp=field(req, "component") or "")
            if r.get("error"):
                return self._json(r, 400)
            return self._json(version_payload(name) | {"bumped": r})
        if act == "release":
            # The other half of a release, and the outward-facing one: the
            # bump decided the number, this says it happened and pushes the
            # tag. The operator's alone — a policy governs moving the
            # number, and publishing a marker other people fetch is not
            # the same decision.
            r = version.release(name, comp=field(req, "component") or "",
                                env={**projects._git_env(), **users.git_env(self._who())},
                                may_push=projects.may_push(name))
            if r.get("error"):
                return self._json(r, 400)
            if not NODES_OK:
                nodes.audit(self._principal(), "version-release", name,
                            {"tag": r.get("tag"), "pushed": bool(r.get("pushed"))})
            return self._json(version_payload(name) | {"released": r})
        if act == "init":
            r = version.init(name, field(req, "value"), by="operator", env=users.git_env(self._who()),
                             comp=field(req, "component") or "")
            if r.get("error"):
                return self._json(r, 400)
            return self._json(version_payload(name) | {"created": r})
        if act == "unbump":
            r = version.unbump(name, by="operator", env=users.git_env(self._who()),
                               comp=field(req, "component") or "")
            if r.get("error"):
                return self._json(r, 400)
            return self._json(version_payload(name) | {"unbumped": r})
        if act == "ask":
            # Put to the project's own session rather than answered here: it
            # can read the code and be argued with, and neither is true of a
            # function counting commits.
            live = sessions_anywhere()
            r = version.ask(name, live, comp=field(req, "component") or "")
            return self._result(r)
        if act == "policy":
            r = version.set_policy(name, field(req, "policy"))
            if r.get("error"):
                return self._json(r, 400)
            return self._json(version_payload(name))
        return self._json({"error": f"unknown action: {act}"}, 400)

    def _artifacts(self, req):
        """Push an .xpi from a project's dist/ to the paired phone, or stop
        one. The path is resolved against dist/ and unpacked before anything
        runs — push_dir never sees a caller-supplied path."""
        name = field(req, "project")
        if self._not_project(name):
            return
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
        # the control on those is that a person sees the reason and decides,
        # one command at a time. Pairing, connecting, disconnecting and
        # deciding are a PERSON's — any account, not only an administrator:
        # a phone is its owner's, and phone.py holds the ownership (only the
        # account that connected one can disconnect it or answer for it,
        # and root on a shared sandbox is an administrator's whoever asks).
        # A session's token may reach none of them.
        if field(req, "action") not in ("ask", "outcome") and (self._who() or {}).get("session"):
            return self._json({"error": "a session asks; a person answers"}, 403)
        # The outcome of a request is the asking session's to read (scoped
        # to its project below) and an administrator's; not any account's
        # by id, since the output of a root command on a shared machine is
        # not a user's to browse.
        if field(req, "action") == "outcome" and not (self._who() or {}).get("session") \
                and not users.is_admin(self._who()):
            return self._json({"error": "an outcome is read by the session that asked, or an administrator"}, 403)
        act = field(req, "action")
        who = self._who() or {}
        uid, me = users.uid_of(who), who.get("name") or "somebody"
        nid = field(req, "node")
        if act in ("pair", "connect", "disconnect", "forget"):
            if NODES_OK or not nid or not nodes.node(nid):
                return self._json({"error": "pick a node — a phone is driven from "
                                            "a node that has adb"}, 400)
            if act != "forget" and not nodes.node(nid).get("live"):
                return self._json({"error": f"{nodes.node(nid)['name']} is not dialing "
                                            "in — nothing reaches its adb right now"}, 400)
        if act == "pair":
            r = phone.pair(nid, field(req, "ip"), field(req, "port"), field(req, "code"), uid, me)
        elif act == "connect":
            r = phone.connect(nid, field(req, "ip"), field(req, "port") or None, uid, me)
        elif act == "disconnect":
            r = phone.disconnect(nid, uid, me)
        elif act == "forget":
            r = phone.forget(nid, field(req, "ip"))
        elif act == "ask":
            # A session asking to reach the phone on its project's node —
            # or, with kind "root", for one command as root there (roadmap
            # R38). It runs nothing itself; the account that connected that
            # phone, or an administrator, is asked, and on Allow the node
            # runs it. The project is the session's own; a person asking
            # through the API names one they may see.
            proj = who.get("session") or field(req, "project")
            if proj and not who.get("session") and not users.may_see(who, proj):
                proj = ""
            pnid = prefs.get(proj)["node"] if proj else ""
            pn = nodes.node(pnid) if pnid and not NODES_OK else None
            # Whose session asks: the account behind the token (a session on
            # a node is minted for one), or the person calling the API. The
            # answer is routed to them where it can be — their own phone,
            # or root when they are an administrator.
            acct = users.account_of(who) or {}
            asker_uid = str(acct.get("uid") or "")
            asker_name = str(acct.get("name") or "")
            if field(req, "kind") == "root":
                r = phone.ask_root(field(req, "why"), req.get("cmd"), pnid if pn else "",
                                   pn["name"] if pn else "", proj,
                                   bool(((pn or {}).get("reported") or {}).get("sandbox")),
                                   asker_uid=asker_uid, asker_name=asker_name,
                                   asker_admin=users.is_admin(acct),
                                   locked=nodes.node_locked(pn) if pn else "")
            else:
                r = phone.ask(field(req, "why"), req.get("cmd"), pnid if pn else "",
                              pn["name"] if pn else "", proj, asker=asker_name)
        elif act == "allow" or act == "deny":
            r = phone.decide(req.get("id"), act == "allow", uid, me, admin=users.is_admin(who))
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
        if self._not_project(name):
            return
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

    def _global_rules(self, req):
        """The rules that apply to EVERY project (R63). An administrator's.

        Per-project rules are the operator's for that project; a global one
        reaches projects the person saving it may not even work on, so this
        asks for admin where /api/rules asks only for the project. A session
        is refused the same way and for the same reason: its own token would
        otherwise be the way around the arrangement.

        A shipped rule is read-only and is turned off rather than edited, so
        the only thing this writes for one is whether it is on.
        """
        if self._refused("admin"):
            return None
        act = field(req, "action")
        if act == "save":
            r = rules.replace(rules.GLOBAL, req.get("rules") or [])
        elif act in ("enable", "disable"):
            r = rules.set_disabled(field(req, "name"), act == "enable")
        else:
            return self._json({"error": "unknown action"}, 400)
        if r.get("error"):
            return self._json(r, 400)
        return self._json({"rules": rules.globals_now()})

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
        if self._not_project(name):
            return
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
        if self._not_project(name):
            return
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
        if self._not_project(name):
            return
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
            r = bugs.send(name, req.get("id"), sessions_anywhere(),
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
        # The node it was made for, when the dialog offered one: the same
        # write the settings dialog makes, so a project is born able to
        # build and start a session rather than needing a second dialog
        # first (16 Sep). Refused the way the settings dialog refuses it.
        nid = str(req.get("node") or "").strip()
        if code == 200 and body.get("name") and nid and not users.may(self._who(), "node", body["name"]):
            r = prefs.set_prefs(body["name"], node=nid, workspace=WORKSPACE)
            if r.get("error"):
                body["note"] = f"{body.get('note') or 'ready'}; node not set: {r['error']}"
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
            return self._result(r)
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

    def _git_act(self, req):
        """The Git view's actions (roadmap R36 step 2): fixed git commands on
        the project's tree on the controller, under the acting account's
        author and the project's own credentials. An account's, never a
        session's — a session has bb git — on a project it may see and has
        taken on, and not while the project is locked. Switching the tree's
        branch is refused while the owner's Claude session runs in the
        project directory, because that session is standing in it."""
        me = self._who()
        if not me or not users.uid_of(me) or me.get("session"):
            return self._json({"error": "an account's, not a session's — a session uses bb git"}, 403)
        name = field(req, "project")
        if name not in {p["name"] for p in project_list(me)}:
            return self._json({"error": "not a project"}, 400)
        if self._readonly(name):
            return None
        if name in set(load_locks()):
            return self._json({"error": "locked — the padlock on its row unlocks it"}, 403)
        action = field(req, "action")
        # Both of these rewrite the working tree. A merge is not a switch, but
        # it lands other people's files in a directory a session is reading
        # and editing right now, which is the same surprise for the same
        # reason, so it waits for the same moment.
        # A merge INTO ANOTHER branch (into: main, from wherever the tree
        # stands) happens in a temporary worktree and moves nothing here, so
        # the session is no reason to refuse it: that is the merge the
        # operator makes to accept a session's work while it keeps working.
        args_ = req.get("args") or {}
        lands_here = action == "switch" or (
            action == "merge" and str(args_.get("into") or "")
            in ("", gitview.status(WORKSPACE / name).get("branch") or ""))
        if lands_here:
            mine = claude_session(name)
            if any(tmux_base(s["name"]) == mine and not tmux_owner(s["name"])
                   for s in tmux_sessions() + node_tmux_sessions()):
                return self._json({"error": "the owner's Claude session is running in this "
                                            f"directory — end it before "
                                            f"{'switching the branch' if action == 'switch' else 'merging'} "
                                            "under it"}, 409)
        if action == "ask":
            live = sessions_anywhere()
            r = gitview.ask(WORKSPACE / name, name, field(req, "kind"), req.get("args") or {}, live)
            return self._result(r)
        env = {**projects._git_env(), **users.git_env(me)}
        env.pop("DASHBOARD_AUTH", None)
        r = gitview.act(WORKSPACE / name, action, req.get("args") or {}, env=env,
                        may_push=projects.may_push(name))
        if r.get("ok") and not NODES_OK:
            nodes.audit(self._principal(), "git-" + action, name,
                        {k: v for k, v in (req.get("args") or {}).items()
                         if k in ("name", "sha", "path", "at")})
        return self._result(r)

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
        return self._result(r)

    def _link(self, req):
        """Link an existing local repo to an empty repo on a host. projects.py.

        The create gate, because this is the create dialog's third mode and
        one of the places a git token is written — the same reason that gate
        covers the other two. It went ungated from the day it was added: the
        dialog is only drawn for an administrator, so nothing offered it, and
        nothing refused a request that arrived anyway.
        """
        if self._refused("create"):
            return None
        body, code = projects.link(req)
        return self._json(body, code)

    def _unlink(self, req):
        """Take the remote off a project, with the credential and the push
        grant that came with it. See projects.unlink — local, instant, and it
        touches no commit."""
        if self._refused("create"):
            return None
        body, code = projects.unlink(req)
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
            # The welcome panel's two marks: the getting-started guide has
            # been read, and which image's changelog was acknowledged.
            if isinstance(want.get("welcome_seen"), bool):
                keep["welcome_seen"] = want["welcome_seen"]
            if isinstance(want.get("image_seen"), str) and re.fullmatch(r"[0-9a-f]{0,40}", want["image_seen"]):
                keep["image_seen"] = want["image_seen"]
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
        return self._result(r)

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
            if action not in ("install", "remove", "sysdeps"):
                return self._json({"error": "a node takes install, remove or sysdeps"}, 400)
            node = nodes.node(nid)
            if not node:
                return self._json({"error": "no such node"}, 400)
            known = {p["name"] for p in packages.PACKAGES}
            if action == "sysdeps":
                # The system packages the held recipes need, installed
                # without the recipes (roadmap R51): named ones, or every
                # held one when none are named.
                names = [n for n in (req.get("names") or []) if n in known][:8]
                r = packages.node_job(self._principal(), nid, action, names)
                return self._result(r)
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
            return self._result(r)
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
        if action == "update" and req.get("all"):
            return self._claude_md_all()
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
        # The DIRECTORY, not a file: bb resolves which of the two carries the
        # block, and after an update that is CLAUDE.local.md rather than the
        # name this used to hand it.
        md = md_file(WORKSPACE / name)
        if action == "init" and md.is_file():
            return self._json({"error": f"{name} already has an environment block"}, 400)
        if action == "update" and not md.is_file():
            return self._json({"error": f"{name} has no environment block"}, 400)
        r = run(["bb", "claude-md", f"--{action}", str(WORKSPACE / name)], timeout=60)
        if r["code"] != 0:
            return self._json({"error": r["out"].strip() or f"{action} failed"}, 500)
        return self._json({"state": md_state(md), "out": r["out"].strip()})

    def _node_logins(self, nid, rows):
        """What a node's agent says each account on it is signed in to Claude
        as (B104). Absent from most heartbeats, and then nothing happens.

        This is the ONLY report that does not come from a session's own token,
        and it is worth being clear about what that means: a node could name
        an account and an email that are not so. It could also read every
        session's token and run as those accounts, because it runs them — so
        the weakening is small, and what it buys is a card that is true when
        nothing is running, and a way back from a sign-out that does not need
        the session the sign-out just stopped.

        Written only when it says something new, because a heartbeat must not
        cost a write per node per poll, and _auth is cleared only then.
        """
        if not isinstance(rows, list):
            return
        moved = False
        for r in rows[:64]:
            if not isinstance(r, dict):
                continue
            uid = str(r.get("uid") or "")
            if not re.fullmatch(r"u_[0-9a-f]{8}", uid):
                continue
            home = home_for(uid)
            if not home:
                continue
            email = " ".join(str(r.get("email") or "").split())[:120]
            was = claudegrant.state(home)
            on = (was["nodes"] or {}).get(nid) or {}
            if email:
                if on.get("email") == email:
                    continue                       # already what we have
                claudegrant.report(home, nid, email, str(r.get("plan") or ""))
            else:
                if not on:
                    continue                       # never was on this node
                claudegrant.report(home, nid, "", signed_in=False)
            moved = True
        if moved:
            _auth.clear()

    def _claude_md_all(self, req=None):
        """Refresh every project's CLAUDE.md block that is behind, in one press.

        A window move holds every project at once (see window_cost), and the
        only way back was the update link on each project's own row — six
        presses to undo one bump, and each link only appears once the poll has
        noticed (B93). The set is the same one the rows offer: a project whose
        block differs from the template this controller ships. Nothing else is
        touched, so a project with no CLAUDE.md is left alone — creating one is
        a person's decision, per project, and this is not that.

        Locked projects are skipped and named rather than failed: a lock
        refuses exactly this kind of write, and one locked project must not
        stop the other five.
        """
        done, failed, locked = [], [], []
        for p in project_list(self._who()):
            if not any(i.get("action") == "claude-md-update" for i in p.get("issues") or []):
                continue
            if locked_out(p["name"]):
                locked.append(p["name"])
                continue
            r = run(["bb", "claude-md", "--update", str(WORKSPACE / p["name"])], timeout=60)
            if r["code"] == 0:
                done.append(p["name"])
            else:
                failed.append({"project": p["name"],
                               "error": (r["out"] or "").strip()[-200:] or "update failed"})
        return self._json({"updated": done, "failed": failed, "locked": locked})

    def _changelog(self, req):
        """Write back the Unreleased section a person rearranged.

        The WHOLE section at once, which is what the editor holds: somebody
        moving three lines and renaming a category is not making five edits,
        and applying it as a sequence would let a refusal halfway leave a
        shape nobody asked for.

        A session does not get this. The CLI verbs it has — add, edit, merge,
        split, rm — each say what they are doing to one entry; handing it the
        whole section would make "the changelog is the operator's arrangement"
        a convention rather than a rule. The refusal names the verbs.
        """
        if (self._who() or {}).get("session"):
            return self._json({"error": "the changelog's arrangement is the "
                                        "operator's — a session writes entries with "
                                        "`bb changelog add`, and corrects one with "
                                        "`edit`, `merge`, `split` or `rm`"}, 403)
        name = req.get("project", "")
        if self._not_project(name):
            return
        if (bad := locked_out(name)):
            return self._json(bad, 409)
        d = version._sub(name, str(req.get("component") or ""))
        if d is None:
            return self._json({"error": "no such component"}, 400)
        if req.get("action") == "first":
            # The first line, from the page: the editor was dead until a
            # session's `bb changelog add` made the file, and the operator
            # is as entitled to the first entry as to every arrangement
            # after it (16 Sep). Only the first: a file that exists is
            # edited through the editor, whole.
            if changelog.read(d) is not None:
                return self._json({"error": "there is a changelog here already; edit it below"}, 409)
            r = changelog.add(d, str(req.get("text") or ""))
            if r.get("error"):
                return self._json(r, 400)
            return self._json(r | {"text": changelog.read(d),
                                   "groups": changelog.groups(d)})
        gs = req.get("groups")
        if not isinstance(gs, list):
            return self._json({"error": "groups is a list of {name, entries}"}, 400)
        r = changelog.put(d, gs)
        if r.get("error"):
            return self._json(r, 400)
        return self._json(r | {"text": changelog.read(d),
                               "groups": changelog.groups(d)})

    def _nodelog(self, req):
        """A machine's own log, for a session that has been granted it.

        Which node is ASKING is not taken from the request and never from the
        session's environment: a node session's BB_NODE is a variable it can
        set. It is the node of the session's own project, which the token
        proves — the same derivation the phone's ask uses, for the same
        reason.
        """
        if NODES_OK:
            return self._json({"error": "the node store did not open: " + NODES_OK}, 500)
        who = self._who() or {}
        proj = who.get("session") or field(req, "project")
        if proj and not who.get("session") and not users.may_see(who, proj):
            return self._json({"error": "not a project"}, 400)
        asking = prefs.get(proj)["node"] if proj else ""
        want = field(req, "node")
        tgt = nodes.node(want) or next(
            (n for n in nodes.node_list() if n["name"] == want), None)
        r = nodes.node_log_read(self._principal(), asking,
                                (tgt or {}).get("id") or want,
                                field(req, "stream") or "agent",
                                req.get("lines") or 200,
                                debug_on=bool(settings.get("debug_mode")))
        return self._result(r, 403)

    def _doctor(self, req):
        """Re-run bb doctor now and answer with the fresh verdict.

        Synchronous on purpose: the caller pressed a button asking for an
        answer, and the threading server keeps everything else responsive
        while this one connection waits the half-minute a bad network takes.
        """
        if not doctor.refresh():
            return self._json({"error": "doctor is already running"}, 409)
        return self._json(doctor.payload())

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
        sess = claude_session(name)
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
                      if tmux_base(s) == claude_session(name)
                      or tmux_base(s).startswith(tmux_name(f"shell-{name}") + "-"))
        if held:
            return self._json({"error": "close its terminals first — "
                                        + ", ".join(held[:3])
                                        + (" …" if len(held) > 3 else "")}, 409)
        # No daemon, or no compose file: nothing to protect, said by the
        # suppress rather than by a bare pass.
        with contextlib.suppress(Exception):
            if devapp.state(name).get("exists"):
                return self._json({"error": "its dev instance still has "
                                            "containers — press Down on the "
                                            "Artifacts tab first"}, 409)
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
                      if tmux_base(s) == claude_session(name)
                      or tmux_base(s).startswith(tmux_name(f"shell-{name}") + "-"))
        if held:
            return self._json({"error": "close its terminals first — "
                                        + ", ".join(held[:3])
                                        + (" …" if len(held) > 3 else "")}, 409)
        with contextlib.suppress(Exception):    # no daemon, or no compose file
            if devapp.state(name).get("exists"):
                return self._json({"error": "its dev instance still has "
                                            "containers — press Down on the "
                                            "Artifacts tab first"}, 409)
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
            return self._result(r)
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
            return self._result(r)
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
                        if users.tmux_prefix(me) + claude_session(p['name'])
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
            return self._result(r)
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
            return self._result(r | {"sent": lines[0] if len(lines) == 1
                                     else f"{len(lines)} commands"})
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
    doctor.start()
    idle.start()
    threading.Thread(target=_compat_loop, name="compat", daemon=True).start()
    if packages.AUTOCHECK:
        threading.Thread(target=packages.versions_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
