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
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
PORT = int(os.environ.get("DASHBOARD_PORT", "7680"))
AUTH = os.environ.get("DASHBOARD_AUTH", "")
# Loopback only: the browser reaches terminals through this server's own
# /term proxy, so there is no second port for the page to be told about —
# which is what DASHBOARD_TTYD_PUBLIC_PORT used to exist for.
TTYD_PORT = int(os.environ.get("DASHBOARD_TTYD_PORT", "7681"))

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


def make_token():
    exp = str(int(time.time()) + SESSION_DAYS * 86400)
    return exp + "." + hmac.new(SECRET, exp.encode(), hashlib.sha256).hexdigest()


def token_ok(tok):
    exp, _, sig = tok.partition(".")
    if not exp.isdigit() or int(exp) < time.time():
        return False
    want = hmac.new(SECRET, exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, want)


# The landing page. Same palette as the dashboard, one job: turn a credential
# into the cookie. autocomplete names are the standard ones so password
# managers offer to fill and to save — the thing the browser dialog never did
# well on a phone.
LOGIN_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>BuilderBot — sign in</title>
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
</style></head><body>
<form method="post" action="/login">
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
  <!--ERR-->
  <input type="hidden" name="next" value="/">
  <label for="u">Username</label>
  <input id="u" name="username" autocomplete="username" autocapitalize="none" required>
  <label for="p">Password</label>
  <input id="p" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Sign in</button>
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
MACROS = {
    "status":           ["bb", "status"],
    "update":           ["bb", "update"],
    "login":            ["bb", "login"],
    "runner-status":    ["bb", "runner", "status"],
    "runner-stop":      ["bb", "runner", "stop"],
    "runner-start":     ["bb", "runner", "start"],
    "emu-start":        ["bb", "emu", "start"],
    "emu-stop":         ["bb", "emu", "stop"],
    "emu-status":       ["bb", "emu", "status"],
    "emu-list":         ["bb", "emu", "list"],
    "lint":             ["bb", "lint"],
    "logs":             ["bb", "logs"],
    "logs-follow":      ["bb", "logs", "-f"],
}
# Sendable, but not listed in the bb commands card: another card owns them.
CARD_HIDDEN = {"runner-status", "runner-stop", "runner-start"}

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
MAX_TABS = int(os.environ.get("DASHBOARD_MAX_TABS", "12"))

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
CARD_KEYS = ["doctor", "runner", "projects", "tools", "phone", "findings"]


# Every state file is written the same way: to a temp file in the same
# directory, then renamed over the real one, so a reader — including bb-tty,
# which parses the lock list on every session launch — never sees half
# a file. The temp name is unique per call. It used to be a fixed
# "<name>.json.tmp", and this is a threading server: two saves landing
# together (a slow poll and the page's debounced follow-up save were enough)
# each opened the SAME temp file, the second truncating what the first was
# writing, and whichever renamed first published a torn file. A reader in
# that window got a parse error, which load_layout() reports as "no layout
# yet" — and a page that hears that saves its default strip over the real
# one and then, holding the revision it just wrote, ignores the server
# until the next change. Mode 644 because mkstemp gives 600 and the files
# were world-readable before.
def write_json(path, obj):
    STATE.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(obj, indent=2) + "\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


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
TAB_KINDS = {"term", "packages", "todo", "projects", "docker"}


def load_layout():
    try:
        v = json.loads(TABS_FILE.read_text())
    except (OSError, ValueError):
        v = {}
    # Shape-checked field by field, not trusted: this runs inside every status
    # poll and once at startup (prune_claude_tabs), so a file holding
    # `"tabs": 5` — a hand edit, or a client that posted junk before the
    # handler checked — must read as "no layout", not raise and take the
    # whole dashboard down with a 500 per poll and a crash at the next boot.
    if not isinstance(v, dict):
        v = {}
    tabs, ids = [], set()
    stored = v.get("tabs") if isinstance(v.get("tabs"), list) else []
    for t in stored[:MAX_TABS]:
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


def save_layout(v):
    write_json(TABS_FILE, v | {"boot": boot_id()})


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

    Called once at startup. The revision is bumped so a browser left open across
    the restart adopts the pruned strip instead of saving its stale tabs back.
    """
    try:
        stored = json.loads(TABS_FILE.read_text())
    except (OSError, ValueError):
        return
    here = boot_id()
    if not here or stored.get("boot") == here:
        return
    v = load_layout()
    kept = [t for t in v["tabs"] if not t["arg"].startswith("claude:")]
    if len(kept) == len(v["tabs"]):
        save_layout(v)                  # nothing to drop; just stamp this boot
        return
    ids = {t["id"] for t in kept}
    panes = [p if p in ids else None for p in v["panes"]]
    if panes[0] is None:
        panes = [panes[1], None]
    try:
        save_layout({"rev": v["rev"] + 1, "tabs": kept, "panes": panes,
                     "active": 1 if panes[1] else 0})
    except OSError:
        pass                            # a read-only /config is not fatal here


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


def findings_payload():
    ps = project_list()
    known = {p["name"] for p in ps}
    if not REPORTS.is_dir():
        return {"available": False, "reports": [], "projects": sorted(known)}
    files = sorted(f for f in REPORTS.glob("*.sarif")) + \
            sorted(f for f in REPORTS.glob("*.sarif.json"))
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
    true exactly when an https remote will work, whichever of GIT_PAT,
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


def project_list():
    """Every directory under /workspace that is a project, with what is wrong
    with it. Named _list because `projects` is the module beside this one that
    creates them — one name for the reading and one for the writing."""
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
                    # every time the image gains a feature.
                    issues.append({"level": "warning", "action": "claude-md-update",
                                   "text": "CLAUDE.md environment block is out of date — update"})
                elif md == "unmarked":
                    # `bb claude-md --update` refuses this one, so it must not be
                    # offered as a link that would do nothing.
                    issues.append({"level": "warning",
                                   "text": "CLAUDE.md predates the BUILDERBOT:ENV markers"
                                           " — merge the block in by hand once"})

        # Every directory is still reported. The dashboard decides what to show,
        # and SARIF paths are attributed by matching these names — dropping one
        # here would silently orphan its findings.
        if d.name in locked:
            # The one gate there is. It says who runs this directory, not that
            # anything is wrong with it — which is why it is a level of its own
            # and never an error: the row keeps every control the operator uses
            # themselves, and only the ones that act on Claude's behalf go.
            issues.append({"level": "locked",
                           "text": "locked — yours to run; no Claude session, "
                                   "and the notebook is read-only"})
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
                    "last_claude": last_claude(d, d.name, stopped),
                    # What Claude remembers here. On the row because a memory
                    # nobody knows about is the one that goes wrong quietly.
                    "memories": memory.count(d.name),
                    # ...and what is still to do, which is the number on the row
                    # actually worth glancing at.
                    "todo": open_todo.get(d.name, 0),
                    # So the open notebook learns a session has started one
                    # without waiting for the operator to touch something.
                    "todo_batch": todo_batches.get(d.name),
                    # So an open Bugs tab notices a session filing or closing
                    # one without polling the tracker itself.
                    "bug_rev": bug_revs.get(d.name, 0),
                    "issues": issues})
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


def log_path():
    """Where entrypoint.sh sends the container log — same rules as bb_log_dir."""
    d = os.environ.get("BB_LOG_DIR") or ("/logs" if Path("/logs").is_dir()
                                         else "/config/logs")
    return Path(d) / "builderbot.log"


# The runner announces each job on stdout, which lands in the container log:
#     2026-08-17 02:27:17Z: Running job: tests
#     2026-08-17 02:29:04Z: Job tests completed with result: Succeeded
JOB_START = re.compile(r"Running job:\s*(.+?)\s*$")
JOB_END = re.compile(r"Job\s+(.+?)\s+completed with result:")

# ...and its connection state the same way:
#     2026-08-17 02:21:32Z: Listening for Jobs
#     A session for this runner already exists.
#     2026-08-17 02:38:35Z: Runner connect error: Error: Conflict. Retrying
#     2026-08-17 02:39:10Z: Runner reconnected.
LINK_OK = re.compile(r"Listening for Jobs|Runner reconnected")
LINK_BAD = re.compile(r"Runner connect error:\s*(.*?)\s*(?:Retrying until reconnected\.?)?\s*$")
SESSION_TAKEN = re.compile(r"A session for this runner already exists")


def log_tail(limit=65536):
    """Last `limit` bytes of the container log, as lines. Empty if unreadable."""
    try:
        with log_path().open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - limit))       # bounded: this log can be huge
            return fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def current_job(lines):
    """Name of the job the runner is on, from the last of those two lines.

    Cosmetic only — whether a job is running at all is decided by the worker
    process, not by this. A rotated or unreadable log costs the name, nothing
    more.
    """
    for line in reversed(lines):
        if JOB_END.search(line):
            return None                          # finished before it started
        m = JOB_START.search(line)
        if m:
            return m.group(1)
    return None


def link_state(lines):
    """(healthy, detail) for the runner's connection to GitHub.

    A Listener process says the runner is *trying*, not that it succeeded: a
    rejected connection is retried forever without the process exiting, so
    pgrep alone reports a green light through an outage. The last connectivity
    marker in the log is what actually distinguishes the two.
    """
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if LINK_OK.search(line):
            return True, None
        m = LINK_BAD.search(line)
        if m:
            detail = m.group(1).strip(" .") or "connection refused"
            # "Conflict" on its own means nothing to a reader. The runner
            # explains it on the preceding line, so look just behind.
            if any(SESSION_TAKEN.search(x) for x in lines[max(0, i - 5):i]):
                detail = "a session for this runner already exists"
            return False, detail
    return True, None                            # nothing logged either way


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


def _pidfile_alive(p):
    """Is the process named by this pidfile still there? A stale file is a no."""
    try:
        pid = int(p.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True         # it exists, we just may not signal it
    except OSError:
        return False
    return True


def runner():
    d = Path(os.environ.get("RUNNER_DIR", "/opt/actions-runner"))
    info = {"registered": False, "running": False, "listening": False,
            "busy": False, "connected": True, "detail": None,
            "job": None, "elapsed": None, "name": None, "url": None}
    cfg = d / ".runner"
    if cfg.is_file():
        info["registered"] = True
        try:
            j = json.loads(cfg.read_text())
            info["name"] = j.get("agentName")
            info["url"] = j.get("gitHubUrl")
        except (ValueError, OSError):
            pass
    # Path-anchored so the pattern cannot match a command line that merely
    # names the binary — a grep, or the `pgrep -af Runner.Listener` we suggest.
    info["listening"] = run(["pgrep", "-f", "/Runner.Listener"], timeout=10)["code"] == 0
    # The supervisor, which outlives the listener: an ephemeral runner exits
    # after each job and runner.sh re-registers it. Stopped means *this* is
    # gone, so it — not the listener — is what the Stop/Start button reflects.
    # By pidfile, because there is no command-line pattern for runner.sh that
    # does not also match unrelated processes.
    info["running"] = info["listening"] or _pidfile_alive(d / ".runner.pid")
    # The Listener stays up for the whole of a job and spawns a Worker per job,
    # so "listening" alone cannot tell idle from busy — which made the dashboard
    # claim the runner was waiting while it was building.
    w = run(["pgrep", "-f", "/Runner.Worker"], timeout=10)
    info["busy"] = w["code"] == 0
    lines = log_tail() if info["listening"] else []
    if info["listening"]:
        info["connected"], info["detail"] = link_state(lines)
    if info["busy"]:
        info["job"] = current_job(lines)
        # How long the job has been going. There is no progress to report
        # beyond this: a runner long-polls for one job at a time and is never
        # told what else is queued, and what a job *does* — how many tests, how
        # far in — is known only to the tool running inside the step.
        # `out` merges stderr, so take the first token that is actually a pid
        # rather than whatever happened to be printed first.
        pid = next((t for t in w["out"].split() if t.isdigit()), None)
        if pid:
            e = run(["ps", "-o", "etimes=", "-p", pid], timeout=10)
            if e["code"] == 0 and e["out"].strip().isdigit():
                info["elapsed"] = int(e["out"].strip())
    info["enabled"] = os.environ.get("ENABLE_RUNNER", "true").lower() not in ("false", "0", "no")
    return info


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
DOCTOR_EVERY = max(300, int(os.environ.get("DASHBOARD_DOCTOR_INTERVAL", "1800")))

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
_auth = {"at": 0.0, "state": {}}
_auth_lock = threading.Lock()
AUTH_TTL = 20
# While a sign-in is open and this box is still signed out, the answer is about
# to change and is worth re-reading sooner. Not *every* poll, though: one check
# is a full node runtime — measured at 357MB and 0.68s — so bypassing the cache
# meant every status request spawning its own, several at once across a phone,
# a desktop and a preload. The dashboard stopped updating and the container ran
# out of memory, which is what "it freezes until I reload the page" was.
AUTH_TTL_FAST = 5


def claude_auth(fresh=False):
    """{signed_in, email} — or {"unknown": True} on a claude too old to ask.

    The one piece of container health that has an action attached, which is
    why it is a field of its own rather than a line in the doctor verdict: a
    verdict is read, and this is pressed.
    """
    # Signed in already: nothing a running sign-in does changes that answer,
    # so it keeps the long cache however busy the flow looks.
    ttl = AUTH_TTL_FAST if fresh and not _auth["state"].get("signed_in") else AUTH_TTL
    if time.monotonic() - _auth["at"] < ttl and _auth["state"]:
        return _auth["state"]
    # One at a time, and checked again on the way in: without this every
    # request that arrives during the 0.68s answer starts its own copy, which
    # is the difference between one node process and a handful.
    with _auth_lock:
        if time.monotonic() - _auth["at"] < ttl and _auth["state"]:
            return _auth["state"]
        return _read_auth()


def _read_auth():
    r = run(["claude", "auth", "status", "--json"], timeout=20)
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
    _auth.update(at=time.monotonic(), state=state)
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

# ---- the bug tracker --------------------------------------------------------
# The notebook's third view. Same arrangement again: its own file, handed the
# two helpers it needs, nothing reaching back.
import bugs                                                      # noqa: E402

bugs.configure(write_json=write_json, state=STATE, tell=notify.tell,
               tmux_name=tmux_name)

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

artifacts.configure(workspace=WORKSPACE, scratch=STATE / "artifacts-tmp")

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
# A project's compose app, built and run on the host's daemon through the
# socket proxy. The module's docstring carries the security reasoning.
import devapp                                                    # noqa: E402

# project_names: devapp checks that a container's name is not already some
# other project's, and what counts as a project is this module's rule — a
# project with no record still owns its default instance's name.
devapp.configure(workspace=WORKSPACE, state=STATE, write_json=write_json,
                 project_names=lambda: [p["name"] for p in project_list()])

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
                   devdata=devapp.DEVDATA, write_json=write_json,
                   rename_devdata=devapp.rename_dev_data,
                   pname=devapp._pname)

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
_findings_counts = {"mtime": -1, "projects": {}, "heads": []}


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
        per, rows_by, broken = {}, {}, False
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
# start, the Artifacts tab not noticing a phone connect, and the Phone card
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
    # The dev-instance job and its files. In-memory counter plus mtimes — the
    # poll never spawns docker.
    revs["devapp"] = devapp.job_rev()
    return revs


def snapshot():
    ps = project_list()
    sessions = tmux_sessions()
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
        # the Phone card knows when to go and fetch the real thing. Reading it
        # is a length() on a list in memory — no adb, nothing to pay for.
        "phone_asks": len(phone.requests_open()),
        # Whether there is a daemon behind any of the Docker controls, and if
        # not, the sentence saying why. Memoised in devapp, because answering
        # it properly is a subprocess: this rides the poll, and the poll is the
        # page's heartbeat. Every Docker button on the page reads this one
        # answer rather than each finding out by failing.
        "docker": devapp.available_cached(),
        # The namespace compose project names start with, so the naming
        # dialog can preview the name it is about to make rather than
        # hardcoding a prefix the operator may have turned off.
        "dev_prefix": devapp.dev_prefix(),
        # Which run of the container this is. The page stamps it into the URL
        # of every Claude terminal it opens, so bb-tty can tell a request made
        # now from one a browser carried across a restart.
        "boot": boot_id(),
        "image": image_stamp(),
        "projects": ps,
        "sessions": sessions,
        "runner": runner(),
        "reports": REPORTS.is_dir(),
        "reports_mtime": reports_mtime(),
        "findings_counts": findings_counts(ps),
        # ...and, for the row they land on, what those paths actually look
        # like. Order matters: this reads what the call above computed.
        "findings_heads": findings_heads(),
        # ...and when each report was written, so one left behind by a failed
        # scanner is visible rather than silently counted as current.
        "reports_ages": reports_ages(),
        "doctor": doctor_payload(),
        # Asked in this order: whether a sign-in is running decides whether
        # the answer to "signed in?" is worth re-reading rather than serving
        # from the cache.
        "claude_auth": claude_auth(fresh=login["running"]),
        "signin": login,
        # A clone or a first push runs in the background now, so the card can
        # say what it is doing without the dialog being open.
        "project_job": projects.job(),
        "max_tabs": MAX_TABS,
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
        # and every client is already asking for that every 15s.
        "layout": load_layout(),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "builderbot-dashboard"

    def log_message(self, fmt, *args):      # quieter than the default
        pass

    def _authed(self):
        if not AUTH:
            return False                    # startup refuses this case anyway
        hdr = self.headers.get("Authorization", "")
        if hdr.startswith("Basic "):
            try:
                given = base64.b64decode(hdr[6:]).decode("utf-8", "replace")
            except (ValueError, UnicodeDecodeError):
                return False
            # Compare the whole "user:pass" so a correct username with a wrong
            # password is indistinguishable from both being wrong.
            return _constant_eq(given, AUTH)
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "bb_session" and token_ok(v.strip()):
                return True
        return False

    def _deny(self):
        """Not signed in. A person gets the login page, code gets a plain
        401 — never a WWW-Authenticate challenge, which is what summons the
        browser's own dialog. Anything fetching /api/ is the page's JS (or
        curl), and both handle a 401 better than a redirect-to-HTML."""
        if self.path.split("?")[0].startswith("/api/"):
            return self._json({"error": "not signed in"}, 401)
        nxt = urllib.parse.quote(self.path, safe="/?=&")
        self.send_response(302)
        self.send_header("Location", f"/login?next={nxt}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _login_page(self, error=""):
        err = f'<p class="err">{error}</p>' if error else ""
        body = LOGIN_HTML.replace("<!--ERR-->", err).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _login_post(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 <= n <= MAX_BODY:
                return self._json({"error": "body too large"}, 413)
            form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
        except (ValueError, TypeError):
            return self._json({"error": "bad request"}, 400)
        given = (form.get("username", [""])[0] + ":" + form.get("password", [""])[0])
        if not (AUTH and _constant_eq(given, AUTH)):
            # A beat of delay, so guessing costs something; the message does
            # not say which half was wrong for the same reason _authed's
            # comparison does not.
            time.sleep(0.5)
            return self._login_page("Wrong username or password.")
        nxt = form.get("next", ["/"])[0]
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"
        self.send_response(303)
        self.send_header("Location", nxt)
        self.send_header("Set-Cookie",
                         f"bb_session={make_token()}; Path=/; "
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
        rest = self.path[len("/term"):]
        if not rest or rest.startswith("?"):
            # ttyd's client resolves "token" and "ws" against the page URL,
            # so the page must live under a trailing slash.
            self.send_response(302)
            self.send_header("Location", "/term/" + rest)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            up = socket.create_connection(("127.0.0.1", TTYD_PORT), timeout=5)
        except OSError:
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
        lines.append("Authorization: Basic "
                     + base64.b64encode(AUTH.encode()).decode())
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

    def _json(self, obj, code=200):
        body, zipped = self._gzip(json.dumps(obj).encode())
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
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
        if path == "/login":
            return self._login_page()
        if path == "/logout":
            return self._logout()
        if not self._authed():
            return self._deny()
        if path == "/term" or path.startswith("/term/"):
            return self._term_proxy()
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
            return self._json(snapshot())
        if self.path.startswith("/api/findings"):
            return self._json(findings_payload())
        if self.path.startswith("/api/changelog"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            if name not in {p["name"] for p in project_list()}:
                return self._json({"error": "not a project"}, 400)
            d = version._sub(name, q.get("component", [""])[0])
            if d is None:
                return self._json({"error": "no such component"}, 400)
            return self._json({"text": changelog.read(d)})
        if self.path.startswith("/api/version"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            if name not in {p["name"] for p in project_list()}:
                return self._json({"error": "not a project"}, 400)
            return self._json(version.payload(name))
        if self.path.startswith("/api/artifacts"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            if name not in {p["name"] for p in project_list()}:
                return self._json({"error": "not a project"}, 400)
            # `devapp` is the main instance, which is what the row shows;
            # `devapps` is every instance, which the manager reads. Both, so
            # the row keeps working while the manager grows around it.
            return self._json({"artifacts": artifacts.listing(name),
                               "devapp": devapp.state(name),
                               "devapps": devapp.states(name)}
                              | phone.summary())
        if self.path.startswith("/api/artifact?"):
            # The download. Resolved and prefix-checked in artifacts.resolve —
            # a symlink inside dist/ must not turn this into a file server for
            # the whole box.
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            rel = q.get("path", [""])[0]
            if name not in {p["name"] for p in project_list()}:
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
        if self.path.startswith("/api/phone"):
            # Not on the status poll: this walks the projects looking for
            # extension manifests, and a filesystem walk every fifteen seconds
            # for a card nobody has open is a poor trade. The card asks.
            return self._json(self._phone_payload())
        if self.path.startswith("/api/packages"):
            return self._json(packages.payload())
        if self.path.startswith("/api/docker"):
            # Refresh is the retry: drop the memoised availability first, so a
            # daemon wired up thirty seconds ago is noticed by pressing the
            # button rather than by waiting for the memo to lapse.
            devapp.forget_available()
            # The manager's whole page in one answer: every instance, and
            # every container that is not one of them.
            return self._json(devapp.overview())
        if self.path.startswith("/api/containers"):
            # A read, and the only one this dashboard makes of the daemon
            # beyond `docker version` — see the guard in devapp.py, which
            # allows it and still refuses anything that would change something.
            return self._json(devapp.containers())
        if self.path.startswith("/api/project-job"):
            return self._json(projects.job())
        if self.path.startswith("/api/todo"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            if name not in {p["name"] for p in project_list()}:
                return self._json({"error": "not a project"}, 400)
            live = [s["name"] for s in tmux_sessions()]
            return self._json({"project": name} | self._todo_state(name, live))
        if self.path.startswith("/api/memory"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            got = memory.payload(q.get("project", [""])[0],
                                 [s["name"] for s in tmux_sessions()])
            return self._json(got if got is not None
                              else {"error": "not a project"}, 400 if got is None else 200)
        if self.path.startswith("/api/bugs"):
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            name = q.get("project", [""])[0]
            if name not in {p["name"] for p in project_list()}:
                return self._json({"error": f"not a project: {name}"}, 400)
            return self._json(bugs.payload(name))
        if self.path.startswith("/api/pubkeys"):
            # The shielded agent's public halves, for the New project dialog:
            # picking one selects it for the clone, and showing it is how the
            # operator gets it onto GitHub's deploy-key page in the first
            # place. Public keys are the shareable part — nothing here can
            # reach the private material, by construction. `pat` rides along
            # so the dialogs can say whether a deploy key is optional (a PAT
            # covers https) or the only way a push can authenticate.
            return self._json({"keys": agent_keys(), "pat": gh_authed()})
        self._json({"error": "not found"}, 404)

    def _post(self):
        if self.path.split("?")[0] == "/login":
            return self._login_post()
        if not self._authed():
            return self._deny()
        # Read the body once, here, rather than in each handler: doing it after
        # dispatch is how the request stream ends up consumed twice or not at all.
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 <= n <= MAX_BODY:
                return self._json({"error": "body too large"}, 413)
            req = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, TypeError):
            return self._json({"error": "bad request"}, 400)
        if not isinstance(req, dict):
            return self._json({"error": "bad request"}, 400)

        path = self.path.split("?")[0]
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
        if path.startswith("/api/trash"):
            return self._trash(req)
        if path.startswith("/api/session"):
            return self._session(req)
        if path.startswith("/api/keys"):
            return self._keys(req)
        if path.startswith("/api/send"):
            return self._send(req)
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
        if path.startswith("/api/link"):
            return self._link(req)
        if path.startswith("/api/project-job"):
            return self._project_job(req)
        if path.startswith("/api/todo"):
            return self._todo(req)
        if path.startswith("/api/packages"):
            return self._packages(req)
        if path.startswith("/api/memory"):
            return self._memory(req)
        if path.startswith("/api/prefs"):
            name = req.get("project", "")
            r = prefs.set_prefs(name, model=req.get("model"),
                                effort=req.get("effort"))
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

    def _signin(self, req):
        """Start a sign-in, or stop the one that is running."""
        _auth.update(at=0.0, state={})
        if field(req, "action") == "cancel":
            return self._json(signin.cancel() | {"signin": signin.state()})
        return self._json(signin.start() | {"signin": signin.state()})

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
        _auth.update(at=0.0, state={})
        return self._json(r | {"signin": signin.state()},
                          400 if r.get("error") else 200)

    def _signout(self, req):
        """Sign this container out of Claude.

        The other half — signing in — is not here, because it cannot be: the
        flow wants a browser and a code pasted back, so the page opens a
        terminal for it. Signing out is one command with no conversation in
        it, so it is a button.
        """
        # Not while a conversation is running. Signing out pulls the ground
        # from under every session on the box, and a page that has not polled
        # for fifteen seconds can offer a button the answer has moved past —
        # so the refusal is here as well as on the button.
        busy = [s["name"] for s in tmux_sessions() if s["name"].startswith("claude-")]
        if busy:
            return self._json({"error": "end these first: " + ", ".join(busy)}, 409)
        r = run(["claude", "auth", "logout"], timeout=60)
        _auth.update(at=0.0, state={})
        if r["code"] != 0:
            return self._json({"error": r["out"].strip()[-500:] or "logout failed"}, 500)
        return self._json({"ok": True, "auth": claude_auth()})

    def _todo(self, req):
        """Add, send, edit or drop one item on a project's list.

        The project is checked against the real list for the same reason every
        other endpoint here does it: a name that came back off the filesystem
        cannot name something that was never there.
        """
        name = field(req, "project")
        if name not in {p["name"] for p in project_list()}:
            return self._json({"error": f"not a project: {name}"}, 400)
        act = field(req, "action")
        # "send" is a write to the roadmap (it marks a step sent) and starts a
        # session's turn, so it goes with the rest.
        if (bad := locked_out(name)):
            return self._json(bad, 409)
        live = [s["name"] for s in tmux_sessions()]
        if act in ("tell", "save"):
            # Two Saves, one difference: whether a line of the conversation is
            # spent saying so. Both settle the panel — the plain one is "I have
            # seen this, do not nag me", which is the right answer while a
            # session is mid-task or when there is none.
            told = False
            if act == "tell":
                told = bool(todo.announce(name, todo.unsaved(name), live).get("sent"))
            todo.mark_told(name)
            return self._json({"ok": True, "told": told}
                              | self._todo_state(name, live))
        if act == "add":
            r = todo.add(name, field(req, "text"), steps=field_list(req, "steps"))
        elif act == "send":
            r = todo.send(name, req.get("id"), req.get("step"), live,
                          also_told=todo.unsaved(name) if req.get("tell") else False,
                          note=field(req, "note"))
            if r.get("sent") and req.get("tell"):
                todo.mark_told(name)
        elif act == "edit":
            r = todo.edit(name, req.get("id"), field(req, "text"), req.get("step"))
        elif act == "move":
            r = todo.move(name, req.get("id"), req.get("step"), req.get("dir"))
        elif act == "info":
            r = todo.set_info(name, req.get("id"), field(req, "text"),
                              step=req.get("step"))
        elif act == "add-step":
            r = todo.add_step(name, req.get("id"), field(req, "text"))
        elif act == "cross":
            r = todo.cross(name, req.get("id"), req.get("step"),
                           bool(req.get("on", True)))
        elif act == "remove":
            r = todo.remove(name, req.get("id"), req.get("step"),
                            why=field(req, "why"))
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
            return self._json(r, 400)
        return self._json(r | self._todo_state(name, live))

    def _todo_state(self, name, live):
        """What the panel needs after any change: the list, whether there is
        anywhere to send, and whether a session has been told about it yet."""
        session = todo.tmux_name("claude-" + name)
        return {"items": todo.items(name),
                "session": session if session in set(live) else None,
                "unsaved": todo.unsaved(name),
                # A session part-way through a batch. The panel refuses to save
                # over one: the list on screen is a copy taken before the
                # session started, and replaying edits onto a list that has
                # moved underneath is how two people writing one file lose
                # each other's work.
                "batch": todo.batch(name)}

    def _phone_payload(self):
        """The card's data, plus this browser's own address when it is a phone.

        The whole point of the IP field is a number the operator has to go and
        read off the device — and when the dashboard is being viewed ON that
        device, the server already has it: the client address of this very
        request. Docker's bridge does not masquerade it, so what arrives is the
        real LAN address rather than the gateway's.

        Only offered for an Android client. From a desktop the client address
        is the desktop's, which is emphatically not the phone, and filling the
        field with it would be a confident wrong answer — the worst kind.
        """
        out = phone.payload()
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
        clash = next((p["name"] for p in project_list()
                      if devapp._slug(p["name"]) == devapp._slug(name)), "")
        if name and clash:
            return self._json({"error": f"that is the project {clash} — a "
                                        f"container written here needs a name "
                                        f"of its own"}, 400)
        r = devapp.create_container(name, req.get("compose") or "",
                                    req.get("env") or "")
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
        if name not in {p["name"] for p in project_list()} \
                and name not in devapp.overview_names():
            return self._json({"error": f"not a project or container: {name}"}, 400)
        act = field(req, "action")
        # Which instance of that project. Absent means the one every project
        # has always had, so a caller that predates instances still works and
        # a request that names a strange one is answered rather than obeyed:
        # the name decides a compose project and a data directory, and those
        # are not places to let an arbitrary string reach.
        inst = field(req, "instance") or devapp.MAIN
        # `new` is the one action whose instance does not exist yet — that is
        # what it is for. Everything else names one that must exist, because
        # the string decides a compose project and a data directory and is not
        # somewhere an arbitrary one should reach.
        if act == "abort":
            # Before the instance check below: a job can be running against an
            # instance that has since been removed, and stopping it must not
            # depend on the thing it is building still existing.
            return self._json({"ok": True, "stopped": devapp.abort_job()})
        if act == "starter":
            # The project's .env.example, for a container that does not exist
            # yet — the send dialog opens on it so the env is filled in before
            # the first build rather than after it stops at the gate. Reads
            # nothing of the instance, which is the point: there is none.
            return self._json({"text": devapp.starter(name)})
        if act == "new":
            r = devapp.create_instance(name, inst)
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
        else:
            return self._json({"error": f"unknown action: {act}"}, 400)
        if r.get("error"):
            return self._json(r, 400)
        return self._json(r | {"state": devapp.state(name, inst)})

    def _version(self, req):
        """Move a project's version, or change who is allowed to.

        Both are the operator's: this endpoint is only reachable from the
        panel, so `by="operator"` is the honest value rather than a field the
        caller supplies. A session's bump goes through `bb version bump`,
        which asks the same policy and passes `by="claude"`.
        """
        name = field(req, "project")
        if name not in {p["name"] for p in project_list()}:
            return self._json({"error": f"not a project: {name}"}, 400)
        act = field(req, "action")
        if act == "bump":
            r = version.bump(name, field(req, "part"), by="operator",
                             comp=field(req, "component") or "")
            if r.get("error"):
                return self._json(r, 400)
            return self._json(version.payload(name) | {"bumped": r})
        if act == "init":
            r = version.init(name, field(req, "value"), by="operator",
                             comp=field(req, "component") or "")
            if r.get("error"):
                return self._json(r, 400)
            return self._json(version.payload(name) | {"created": r})
        if act == "unbump":
            r = version.unbump(name, by="operator",
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
        if name not in {p["name"] for p in project_list()}:
            return self._json({"error": f"not a project: {name}"}, 400)
        act = field(req, "action")
        if act == "push":
            dev = phone.phone()
            if not dev:
                return self._json({"error": "no phone is connected — pair one "
                                            "on the Phone card first"}, 400)
            rel = field(req, "path")
            # A push is a decision, made each time — nothing auto-pushes on a
            # change. The other half of that bargain: pushing the IDENTICAL
            # build into a session that is still live installs nothing, so it
            # is compared and said instead of done. Stopping the session
            # clears the comparison, because after a stop (or a Firefox
            # restart) the same file is a legitimate thing to push again.
            if phone.push_state()["running"]:
                if artifacts.live_matches(name, rel):
                    return self._json({"error": "that exact build is already "
                                       "live on the phone — rebuild the .xpi, "
                                       "or Stop and push again"}, 400)
                return self._json({"error": "a push is still live — Stop it "
                                            "first"}, 400)
            d, err = artifacts.unpack_xpi(name, rel)
            if err:
                return self._json({"error": err}, 400)
            r = phone.push_dir(d, dev["serial"], field(req, "apk"), label=rel)
            if not r.get("error"):
                artifacts.set_live(name, rel)
        elif act == "install":
            # An APK, installed for real and kept — unlike the extension push,
            # which is a temporary add-on. `adb install -r` replaces an
            # existing copy in place and keeps its data, so this is the update
            # path too and there is no second verb.
            dev = phone.phone()
            if not dev:
                return self._json({"error": "no phone is connected — pair one "
                                            "on the Phone card first"}, 400)
            rel = field(req, "path")
            f = artifacts.resolve(name, rel)
            if f is None or f.suffix.lower() not in (".apk",):
                return self._json({"error": "not an .apk in this project's "
                                            "dist/"}, 400)
            r = phone.install_apk(f, dev["serial"], label=rel)
        elif act == "stop":
            r = phone.stop_push()
            artifacts.clear_live()
        else:
            return self._json({"error": f"unknown action: {act}"}, 400)
        if r.get("error"):
            return self._json(r, 400)
        return self._json(r | {"artifacts": artifacts.listing(name)}
                          | phone.summary())

    def _phone(self, req):
        """Pair, connect, and push an extension. Every argument is checked by
        phone.py against something already known — a discovered extension, an
        attached device, a Firefox that is actually installed — rather than
        taken as given: this is one of the few places the page causes a program
        to run."""
        act = field(req, "action")
        if act == "pair":
            r = phone.pair(field(req, "ip"), field(req, "port"), field(req, "code"))
        elif act == "connect":
            r = phone.connect(field(req, "ip"), field(req, "port") or None)
        elif act == "disconnect":
            r = phone.disconnect(field(req, "serial"))
        elif act == "ask":
            # A session asking to reach the phone. It does not run anything
            # itself; if the operator allows it, this process does.
            r = phone.ask(field(req, "why"), req.get("cmd"))
        elif act == "allow" or act == "deny":
            r = phone.decide(req.get("id"), act == "allow")
        elif act == "outcome":
            r = phone.outcome(req.get("id"))
            if not r.get("error"):
                return self._json(r)
        else:
            return self._json({"error": f"unknown action: {act}"}, 400)
        if r.get("error"):
            return self._json(r, 400)
        return self._json(r | self._phone_payload())

    def _findings_log(self, req):
        """The Analysis view's log. Read-only by nature: the scan runs on the
        host and nothing here can write a finding, so `history` is the only
        action there is — the entries are made by findings_counts noticing the
        report changed."""
        name = field(req, "project")
        if name not in {p["name"] for p in project_list()}:
            return self._json({"error": f"not a project: {name}"}, 400)
        if field(req, "action") != "history":
            return self._json({"error": "the findings log is read-only"}, 400)
        return self._json({"history": findings.history(
            name, limit=req.get("limit"), since=req.get("since"),
            find=field(req, "find"))})

    def _bugs(self, req):
        """Report, edit, or close one bug. The fields go through bugs.py's own
        cleaner; this only picks the action and answers with the fresh list,
        so the tab never has to guess what the write left behind."""
        name = field(req, "project")
        if name not in {p["name"] for p in project_list()}:
            return self._json({"error": f"not a project: {name}"}, 400)
        act = field(req, "action")
        if (bad := locked_out(name)):
            return self._json(bad, 409)
        fields = {k: field(req, k) for k in ("title", "area", "repro",
                                             "expected", "actual", "notes")}
        if act == "add":
            r = bugs.add(name, fields.pop("title"),
                         severity=field(req, "severity", "medium"), **fields)
        elif act == "edit":
            r = bugs.edit(name, req.get("id"),
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
        if act == "save":
            r = memory.save(proj, file, field(req, "text"))
        elif act == "index":
            r = memory.save_index(proj, [e for e in (req.get("lines") or [])
                                         if isinstance(e, dict)])
        elif act == "create":
            r = memory.create(proj, field(req, "name"), field(req, "title"),
                              field(req, "hook"), field(req, "type"),
                              field(req, "body"))
        elif act == "delete":
            r = memory.delete(proj, file)
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
        return self._json(r, 400 if r.get("error") else 200)

    def _custom(self, req):
        """Save or delete one of the operator's own command lists.

        Ids are minted here rather than accepted from the page, so the file
        cannot grow a key that came from a request, and every stored macro is
        addressable by something this server chose.
        """
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

    def _packages(self, req):
        """Queue installs or removals of the packages the Tools card offers.

        Names are checked against PACKAGES rather than passed through: what
        reaches a command line is a string this server chose, which is the
        rule every other executing endpoint here follows.
        """
        action = req.get("action")
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
        with _state_lock:
            cur = load_layout()
            v = {"rev": cur["rev"] + 1,
                 "tabs": req.get("tabs") or [],
                 "panes": req.get("panes") or [None, None],
                 "active": 1 if req.get("active") == 1 else 0}
            try:
                save_layout(v)
            except OSError as e:
                return self._json({"error": f"could not save: {e}"}, 500)
            # Re-read so the caller gets exactly what every other client will
            # see, including anything the validator dropped.
            return self._json(load_layout())

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
        live = {s["name"] for s in tmux_sessions()}
        held = sorted(s for s in live
                      if s == tmux_name(f"claude-{name}")
                      or s.startswith(tmux_name(f"shell-{name}") + "-"))
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
        live = {s["name"] for s in tmux_sessions()}
        held = sorted(s for s in live
                      if s == tmux_name(f"claude-{name}")
                      or s.startswith(tmux_name(f"shell-{name}") + "-"))
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
        if session not in {s["name"] for s in tmux_sessions()}:
            return self._json({"code": 0, "out": "", "err": "", "gone": True})
        return self._json(run(["tmux", "kill-session", "-t", session], timeout=10))

    def _keys(self, req):
        session, key = req.get("session", ""), req.get("key", "")
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
        if session not in {s["name"] for s in tmux_sessions()}:
            return self._json({"error": f"no such session: {session}"}, 400)
        # Never into a Claude session: that would not run the command, it would
        # submit it as a prompt.
        if session.startswith("claude-"):
            return self._json({"error": "refusing to type into a Claude session"}, 400)
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


def _constant_eq(a, b):
    """Compare without leaking length or position through timing."""
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())


def main():
    if not AUTH or not re.match(r"^[^:]+:.+$", AUTH):
        raise SystemExit(
            "DASHBOARD_AUTH must be set as user:password.\n"
            "This serves a terminal into a container holding your ssh agent and\n"
            "source trees; it will not start unauthenticated."
        )
    prune_claude_tabs()
    # Daemons: these loops must die with the server, not hold it open.
    threading.Thread(target=_doctor_loop, daemon=True).start()
    if packages.AUTOCHECK:
        threading.Thread(target=packages.versions_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
