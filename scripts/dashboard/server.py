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
import json
import os
import re
import selectors
import shlex
import shutil
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
PORT = int(os.environ.get("DASHBOARD_PORT", "8080"))
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

CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}")
REPORTS = Path(os.environ.get("FINDINGS_DIR", "/reports"))

# Excluded projects live on the /config volume so the list survives the image
# updates this container is built to expect. bb-tty reads the same file — a
# rule only the dashboard honored would be advice, since the terminal URL is
# reachable on its own.
EXCLUDES_FILE = STATE / "excluded-projects.json"   # STATE is set up top

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
CARD_KEYS = ["doctor", "runner", "projects", "tools", "findings", "sessions",
             "linux", "commands", "git", "custom"]


# Every state file is written the same way: to a temp file in the same
# directory, then renamed over the real one, so a reader — including bb-tty,
# which parses the exclusion list on every session launch — never sees half
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
TAB_KINDS = {"term", "findings"}


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


def load_excludes():
    try:
        v = json.loads(EXCLUDES_FILE.read_text())
        return sorted({x for x in v if isinstance(x, str)}) if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def save_excludes(names):
    write_json(EXCLUDES_FILE, sorted(set(names)))


def _project_of(uri, known):
    """Which mounted project a scanner-recorded path belongs to.

    The scanner records where *it* saw the code, which is never where this
    container mounts it, so the only reliable anchor is a path component that
    matches a directory in the workspace.
    """
    parts = [p for p in uri.replace("\\", "/").split("/") if p]
    for i, part in enumerate(parts):
        if part in known:
            return part, "/".join(parts[i + 1:]) or part
    return None, "/".join(parts)


def _parse_run(runinfo, known):
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
        proj, rel = _project_of(uri, known)
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


def parse_sarif(path, known):
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
            name, got = _parse_run(runinfo, known)
        except (AttributeError, TypeError, IndexError, KeyError):
            continue
        if name and name not in tools:
            tools.append(name)
        rows.extend(got)
    # A file can hold runs from several tools; naming it after the last one seen
    # was arbitrary.
    return {"file": path.name, "tool": " + ".join(tools) or "?", "findings": rows}


def _valid_projects(ps):
    """The projects whose findings are worth surfacing: not excluded, and no
    error-level issue. A repo that is broken or deliberately shut out gets
    triaged in the Projects card first — its findings would only pad the
    numbers for code nobody can currently work on."""
    return {p["name"] for p in ps
            if not p["excluded"]
            and not any(i["level"] == "error" for i in p["issues"])}


def findings_payload():
    ps = projects()
    known = {p["name"] for p in ps}
    if not REPORTS.is_dir():
        return {"available": False, "reports": [], "projects": sorted(known)}
    files = sorted(f for f in REPORTS.glob("*.sarif")) + \
            sorted(f for f in REPORTS.glob("*.sarif.json"))
    # Attribution still uses every directory name — filtering the *names*
    # would misfile an excluded project's findings as unattributed. The rows
    # are dropped after attribution, and counted: a report that quietly
    # shrinks reads as "covered everything" when it did not.
    valid = _valid_projects(ps)
    reports, hidden = [], 0
    for f in files:
        rep = parse_sarif(f, known)
        keep = [r for r in rep["findings"]
                if r["project"] is None or r["project"] in valid]
        hidden += len(rep["findings"]) - len(keep)
        rep["findings"] = keep
        reports.append(rep)
    return {"available": True, "projects": sorted(known),
            "hidden": hidden, "reports": reports}


def run(cmd, cwd=None, timeout=120, env=None, split_err=False):
    # split_err=True keeps stdout in `out` and stderr in `err`, for the one
    # caller class that must not mistake a warning for real output (the
    # ls-remote emptiness check: ssh's first-contact "Permanently added ..."
    # note lands on stderr and made an empty repo look non-empty). The
    # default stays combined, which is what every log-oriented caller wants.
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env=env)
        out, err = p.stdout or "", p.stderr or ""
        if not split_err:
            out, err = out + err, ""
        return {"cmd": shlex.join(cmd), "code": p.returncode,
                "out": out, "err": err}
    except subprocess.TimeoutExpired:
        return {"cmd": shlex.join(cmd), "code": 124,
                "out": f"timed out after {timeout}s", "err": ""}
    except FileNotFoundError as e:
        return {"cmd": shlex.join(cmd), "code": 127, "out": str(e), "err": ""}


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

# One creation at a time. Not _state_lock: a clone can take minutes, and
# holding the state lock that long would stall every layout save behind it.
_create_lock = threading.Lock()


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


def _readme_intro(dest):
    """The first prose paragraph of the repo's README, or None.

    Headings, badges and raw HTML are skipped — the first thing most READMEs
    hold is a wall of shields, and a CLAUDE.md that opens with badge markup
    describes the README, not the project."""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = dest / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            return None
        out = []
        for para in text.split("\n\n"):
            # Filtered line by line, not paragraph by paragraph: the most
            # common README opens "# Title\nprose" with no blank line
            # between, and skipping that whole block threw away the prose
            # with the heading.
            lines = [l for l in para.splitlines()
                     if l.strip() and not l.lstrip().startswith(
                         ("#", "<", "![", "[![", "---", "=", "|", "```", ">"))]
            if not lines:
                continue
            out.append(re.sub(r"\s+", " ", " ".join(lines)).strip())
            if sum(map(len, out)) > 400:
                break
        return " ".join(out)[:600] or None
    return None


def _build_hints(dest):
    """Build/test commands read off the tree's own marker files.

    Heuristics, deliberately shallow: the point is a first draft that names
    the toolchain, not a build system parser. Wrong guesses are cheap here —
    the section carries a note saying to verify it."""
    hints = []
    try:
        scripts = (json.loads((dest / "package.json").read_text())
                   .get("scripts") or {})
        hints += [f"- **{k}:** `npm run {k}`"
                  for k in ("build", "test", "lint", "dev") if k in scripts]
    except (OSError, ValueError):
        pass
    if (dest / "gradlew").is_file():
        hints += ["- **Build:** `./gradlew build`"
                  + (" — `./gradlew assembleDebug` for an APK"
                     if (dest / "app").is_dir() else ""),
                  "- **Test:** `./gradlew test`"]
    if (dest / "Cargo.toml").is_file():
        hints += ["- **Build:** `cargo build`", "- **Test:** `cargo test`"]
    if (dest / "go.mod").is_file():
        hints += ["- **Build:** `go build ./...`", "- **Test:** `go test ./...`"]
    if (dest / "pyproject.toml").is_file():
        hints.append("- **Python:** `pyproject.toml` present — `uv pip install -e .`"
                     + ("; `pytest`" if (dest / "tests").is_dir() else ""))
    if (dest / "Makefile").is_file():
        hints.append("- **Make:** a `Makefile` is present — see its targets")
    return hints


def describe_repo(dest):
    """A drafted project section for a repo that arrived without a CLAUDE.md:
    the README's own first paragraph, plus whatever the marker files say about
    building it. None when the tree says nothing — the template's placeholder
    section is more honest than an empty guess."""
    parts = [p for p in (_readme_intro(dest),) if p]
    hints = _build_hints(dest)
    if hints:
        parts.append("What the tree suggests:\n\n" + "\n".join(hints))
    if not parts:
        return None
    parts.append("<!-- Drafted automatically at clone time from the repository's "
                 "own files. Have a session verify this against the code and "
                 "flesh it out. -->")
    return "\n\n".join(parts)


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


def projects():
    out = []
    uid, gid = os.getuid(), os.getgid()
    try:
        if not WORKSPACE.is_dir():
            return out
    except OSError:
        pass                    # unreadable: reported by the listing below
    excluded = set(load_excludes())
    stopped = last_stop()
    try:
        here = sorted(WORKSPACE.iterdir())
    except OSError:
        # A workspace this user cannot list is a mount to fix, not a reason for
        # the runner card and the terminal to stop working too.
        return [{"name": str(WORKSPACE), "git": None, "excluded": False,
                 "last_claude": None,
                 "issues": [{"level": "error",
                             "text": f"cannot list this directory as uid {uid}:{gid}"
                                     " — chown it to PUID:PGID on the host"}]}]
    for d in here:
        # `_work` is the runner's checkout area, not a project. Hidden
        # directories are not projects either: the whole projects folder is
        # mounted now, so this list would otherwise open with the share's own
        # furniture (.Recycle.Bin and friends) presented as things to fix.
        #
        # .bbignore is the general form of the same idea, and the one thing
        # here an operator can drive: a directory holding that file is not a
        # project and is not listed. The container drops it into any path of
        # its own that lands inside the projects share — the SDK share, when
        # someone maps it under /mnt/user/development — and anyone can create
        # one by hand for a directory they would rather not see. It hides;
        # excluding a project is the thing that *blocks*, and that is a
        # different control with a different guarantee.
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
        if d.name in excluded:
            issues.append({"level": "excluded",
                           "text": "excluded — no Claude session can start here"})
        out.append({"name": d.name, "git": branch, "git_ok": git_ok,
                    "linked": linked, "github": github,
                    "claude_md": has_md, "excluded": d.name in excluded,
                    "last_claude": None if d.name in excluded else last_claude(d, d.name, stopped),
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


def doctor_payload():
    with _doctor_lock:
        return {k: _doctor[k] for k in ("when", "checks", "failed", "running")}


# ---- additional packages ---------------------------------------------------
# The toolchains `bb sdk` can put on the SDK share, as the Tools card offers
# them. The names on the left are the contract with bb: each is exactly what
# `bb sdk install <name>` takes, and the recipes live there — this table is
# only how they are described and where their installed copy is looked for.
#
# `probe` is relative to ANDROID_HOME for android packages (whose directories
# are symlinks into the share) and to the SDK root for everything else.
PACKAGES = [
    {"name": "playwright", "label": "Playwright browsers", "size": "~1.3 GB",
     "probe": "playwright",
     "about": "Chromium, Firefox and WebKit. The image carries Playwright "
              "itself and the system libraries; these are the browser bundles "
              "bb shot and the dashboard's own tests drive."},
    {"name": "flutter", "label": "Flutter", "size": "~1.3 GB", "probe": "flutter",
     "about": "Flutter with the bundled Dart SDK. Builds Android APKs here; "
              "the iOS half of a Flutter app still needs a Mac."},
    {"name": "dotnet", "label": ".NET + MAUI", "size": "~4 GB", "probe": "dotnet",
     "about": "The .NET SDK plus the maui-android workload — Android apps from C#."},
    {"name": "swift", "label": "Swift", "size": "~3 GB", "probe": "swift",
     "about": "The Swift toolchain for Linux: shared logic, server-side Swift, "
              "and compiling packages. Not an iOS SDK."},
    {"name": "android:emulator", "label": "Android emulator", "size": "~800 MB",
     "probe": "android:emulator",
     "about": "The emulator binary. System images are per API level and come "
              "from ANDROID_SYSTEM_IMAGES."},
    {"name": "android:ndk", "label": "Android NDK", "size": "~3 GB",
     "probe": "android:ndk",
     "about": "Native development kit, for C and C++ inside an Android app."},
    {"name": "android:cmake", "label": "Android CMake", "size": "~200 MB",
     "probe": "android:cmake",
     "about": "The CMake the NDK's build system uses."},
    {"name": "go", "label": "Go", "size": "~250 MB", "probe": "go",
     "about": "Cross-compiles from here to Windows, macOS, Linux and ARM with "
              "GOOS and GOARCH — no extra toolchain, no target to install."},
    {"name": "rust", "label": "Rust", "size": "~700 MB", "probe": "rust",
     "about": "rustup, cargo and the stable toolchain, kept in one directory. "
              "A Windows target needs a linker as well: gcc-mingw-w64 via "
              "EXTRA_APT_PACKAGES, or zig plus cargo-zigbuild."},
    {"name": "zig", "label": "Zig", "size": "~300 MB", "probe": "zig",
     "about": "A C and C++ cross-compiler as much as a language: `zig cc "
              "-target x86_64-windows-gnu` turns this box into a Windows "
              "toolchain, and it links for Rust too."},
    {"name": "android:playstore", "label": "Android image: Play Store",
     "size": "~2 GB", "probe": "android-image:google_apis_playstore",
     "about": "A system image with the Play Store, for testing anything that "
              "depends on Google Play services. Pixel-style — Samsung, Oppo "
              "and the rest ship no emulator images at all."},
    {"name": "android:tv", "label": "Android image: TV", "size": "~2 GB",
     "probe": "android-image:android-tv",
     "about": "Android TV, for a leanback-layout build."},
    {"name": "android:wear", "label": "Android image: Wear OS", "size": "~1.5 GB",
     "probe": "android-image:android-wear",
     "about": "Wear OS, which is what modern Galaxy and Pixel watches run."},
]

# One install at a time, in a worker thread, because these are minutes long
# and megabytes wide: a request that waited for them would time out, and two
# at once would fight over the same sdkmanager lock.
_pkg_lock = threading.Lock()
# What `bb sdk check` last reported: {name: {installed, latest, status}}.
# Filled only when asked — every probe in it reaches the network, so doing it
# on the fifteen-second poll would be a background service nobody requested.
_pkg_versions = {}
_pkg_job = {"running": False, "queue": [], "current": "", "action": "",
            "log": [], "done": [], "failed": []}
_sdk_root_cache = []


# The bb that ships with this server.py: /opt/builderbot/scripts/bb in the
# image, the checkout's copy under `bb dashboard dev`. Same relative position
# either way, and it keeps the pair in step — a page offering a subcommand
# the bb beside it does not have would be a button that cannot work.
# BB_BIN exists for the test harness, which points it at a stub: the suite
# must be able to drive install and remove without downloading gigabytes.
BB = os.environ.get("BB_BIN") or str(HERE.parent / "bb")


def sdk_root_path():
    """Where bb decided the SDK root is — asked once, since it cannot change
    without a container restart."""
    if not _sdk_root_cache:
        r = run([BB, "sdk", "root"], timeout=15)
        _sdk_root_cache.append(r["out"].strip() if r["code"] == 0 else "")
    return _sdk_root_cache[0]


def _pkg_cands(probe):
    """Where a package could be, in the order worth looking."""
    if probe.startswith("android-image:"):
        # A system-image flavour, not a package directory: they all live under
        # system-images/android-NN/<kind>/, so "is a TV image installed" is a
        # question about the kind, not about the tree existing. Sharing one
        # probe made every flavour claim to be installed the moment any image
        # was — the reassuring wrong answer again.
        kind = probe.split(":", 1)[1]
        base = Path(os.environ.get("ANDROID_HOME", "/opt/android-sdk")) / "system-images"
        cands = []
        try:
            cands = sorted(d / kind for d in base.iterdir() if d.is_dir())
        except OSError:
            pass
    elif probe.startswith("android:"):
        cands = [Path(os.environ.get("ANDROID_HOME", "/opt/android-sdk")) / probe.split(":", 1)[1]]
    else:
        root = sdk_root_path()
        # The share first, then the home volume — anything installed before a
        # share was mapped lives there, and calling it uninstalled while 8GB
        # of it sits on disk is how this went wrong once already.
        home = Path(os.environ.get("BUILDER_HOME", str(Path.home()))) / ".sdk"
        cands = [Path(root) / probe] if root else []
        if str(home) != root:
            cands.append(home / probe)
    return cands


def _pkg_paths(probe):
    """Every directory a package actually occupies.

    Resolved rather than assumed: the android directories are symlinks into
    the share, and the whole point of the card is showing where a thing
    actually landed.

    Usually one. A system-image flavour is the exception — it can be installed
    at several API levels at once, all of them real directories and all of
    them its footprint — which is why this returns a list and the size adds
    them up."""
    out = []
    for p in _pkg_cands(probe):
        try:
            if p.is_dir() and any(p.iterdir()):
                out.append(str(p.resolve()))
        except OSError:
            continue
        # The share and the home volume are two places to look for one
        # installation, not two installations to add together.
        if out and not probe.startswith("android-image:"):
            break
    return out


def _pkg_path(probe):
    """The directory a package occupies, or "" when it is not installed."""
    paths = _pkg_paths(probe)
    return paths[0] if paths else ""


# The installed versions, cached against the set of installed paths: reading
# them costs a couple of seconds across every toolchain (dotnet and swift are
# slow to say their own name), and they cannot change while nothing is being
# installed. Re-read when that set does.
_pkg_local = {"key": None, "versions": {}}


def local_versions():
    key = tuple(sorted((p["name"], _pkg_path(p["probe"])) for p in PACKAGES))
    if _pkg_local["key"] == key:
        return _pkg_local["versions"]
    out = {}
    r = run([BB, "sdk", "versions"], timeout=180)
    for ln in r["out"].splitlines():
        f = ln.rstrip().split("\t")
        if len(f) == 4 and f[1] not in ("", "-"):
            out[f[0]] = f[1]
    _pkg_local.update(key=key, versions=out)
    return out


# Measured sizes in KB, {name: kb}. The catalog's "~3 GB" is a download
# estimate written by hand; once something is on disk there is a real number,
# and it is not the estimate — a toolchain grows after installation (a pub
# cache, a .NET workload, an NDK unpacked bigger than it shipped).
#
# du walks the tree to get it, which is instant on a warm share and seconds on
# a cold one (a system-image tree here is 30GB), so it never runs on a request
# thread: the payload serves the last measurement and says whether one is in
# flight, and the page asks again shortly when it is. Re-measured on a TTL
# rather than cached forever, because "it grew" is exactly what this is for.
PKG_SIZE_TTL = 120
_pkg_sizes = {}
_pkg_sized_at = [0.0]
_pkg_sizing = [False]


def _measure_sizes():
    out = {}
    for p in PACKAGES:
        total, answered = 0, False
        for path in _pkg_paths(p["probe"]):
            r = run(["du", "-sk", path], timeout=300)
            head = r["out"].split("\t")[0].strip() if r["code"] == 0 else ""
            if head.isdigit():
                total += int(head)
                answered = True
        # `answered`, not a non-zero total: du rounds a nearly-empty tree to
        # 0 KB on some filesystems, and "0 KB" is a measurement while a du
        # that failed is not one. Falling back to the estimate on a zero would
        # quietly show the catalog's guess for something that is on the disk.
        if answered:
            out[p["name"]] = total
    _pkg_sizes.clear()
    _pkg_sizes.update(out)
    _pkg_sized_at[0] = time.monotonic()
    _pkg_sizing[0] = False


def _size_refresh():
    """Kick a measurement if what we have is older than the TTL. One at a
    time: du on thirteen trees twice over would fight itself for the disk."""
    if _pkg_sizing[0] or time.monotonic() - _pkg_sized_at[0] < PKG_SIZE_TTL:
        return
    _pkg_sizing[0] = True
    threading.Thread(target=_measure_sizes, daemon=True).start()


def human_kb(kb):
    if kb >= 1024 * 1024:
        return f"{kb / 1048576:.1f} GB"
    if kb >= 1024:
        return f"{kb / 1024:.0f} MB"
    return f"{kb} KB"


def packages_payload():
    items = []
    local = local_versions()
    _size_refresh()
    for p in PACKAGES:
        path = _pkg_path(p["probe"])
        v = _pkg_versions.get(p["name"], {})
        kb = _pkg_sizes.get(p["name"]) if path else None
        items.append({**{k: p[k] for k in ("name", "label", "about")},
                      "installed": bool(path), "path": path,
                      # The estimate until there is a measurement, and the
                      # measurement from then on — flagged, because "~4 GB"
                      # and "4.1 GB" mean quite different things.
                      "size": human_kb(kb) if kb is not None else p["size"],
                      "measured": kb is not None,
                      # The version is local knowledge and always shown; the
                      # state, and what it would move to, are only ever what a
                      # check said.
                      "version": v.get("installed") or local.get(p["name"], ""),
                      "latest": v.get("latest", ""),
                      "state": v.get("status", "")})
    with _pkg_lock:
        job = {k: (list(v) if isinstance(v, list) else v)
               for k, v in _pkg_job.items()}
    return {"root": sdk_root_path(),
            "shared": is_mount(sdk_root_path()),
            "sizing": _pkg_sizing[0],
            "items": items, "job": job}


def is_mount(path):
    """Whether the SDK root is a mapped share rather than a directory on the
    home volume — the difference between "kept outside the image" and "kept
    alongside everything else"."""
    if not path:
        return False
    try:
        with open("/proc/self/mountinfo") as f:
            return any(line.split()[4] == path for line in f)
    except OSError:
        return False


def _pkg_worker():
    """Run the queued work one item at a time, keeping a tail of the output.

    Everything it can do is `bb sdk <verb> <name>` for a name that came out of
    PACKAGES — the page posts an index into the table, never a command, which
    is the same rule the macro buttons follow. The verb is decided here rather
    than by the page: "install" on something already present means update it,
    and one button that does the obvious thing beats two that need explaining.
    """
    while True:
        with _pkg_lock:
            if not _pkg_job["queue"]:
                _pkg_job["running"] = False
                _pkg_job["current"] = ""
                return
            name = _pkg_job["queue"].pop(0)
            action = _pkg_job["action"]
            _pkg_job["current"] = name
        verb = action
        if action == "install":
            probe = next((p["probe"] for p in PACKAGES if p["name"] == name), name)
            verb = "update" if _pkg_path(probe) else "install"
        with _pkg_lock:
            _pkg_job["log"].append(f"$ bb sdk {verb} {name}")
        r = run([BB, "sdk", verb, name], timeout=3600)
        with _pkg_lock:
            if action == "check":
                # TSV out: name, installed, latest, status.
                for ln in r["out"].splitlines():
                    f = ln.rstrip().split("\t")
                    if len(f) == 4 and f[3] != "local":
                        _pkg_versions[f[0]] = {"installed": f[1], "latest": f[2],
                                               "status": f[3]}
                _pkg_job["log"].append(f"{name}: {_pkg_versions.get(name, {}).get('status', '?')}")
            else:
                tail = [ln for ln in r["out"].splitlines() if ln.strip()][-12:]
                _pkg_job["log"].extend(tail)
            _pkg_job["log"] = _pkg_job["log"][-60:]
            (_pkg_job["done"] if r["code"] == 0 else _pkg_job["failed"]).append(name)
        if action in ("install", "remove", "update"):
            _pkg_local["key"] = None      # whatever just happened moved a version
            _pkg_sized_at[0] = 0.0        # ...and changed what is on the disk


def _doctor_loop():
    while True:
        run_doctor()
        time.sleep(DOCTOR_EVERY)


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
_findings_counts = {"mtime": -1, "projects": {}}


def findings_counts(ps):
    """{project: {level: count}} across every report, valid projects only —
    same rule as findings_payload. An unattributed path (the scanner saw a
    directory this workspace does not mount) counts under "", which the
    client labels rather than hiding — a finding with a bad path is still a
    finding. The cache holds the unfiltered counts: validity can change
    (an exclusion toggled, a permission fixed) without any report changing,
    so the filter runs per call and only the parse is cached."""
    # Keyed on the project names too: attribution matches path components
    # against them, so a directory that appears between scans would otherwise
    # keep counting as unattributed here while the report tab, which parses
    # fresh, files it correctly.
    known = {p["name"] for p in ps}
    files = []
    if REPORTS.is_dir():
        files = sorted(REPORTS.glob("*.sarif")) + \
            sorted(REPORTS.glob("*.sarif.json"))
    # Nanosecond mtime plus size, per file: a report parsed mid-write and
    # finished within the same second must not stay cached as "no findings"
    # until the next scan.
    try:
        stamp = tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in files)
    except OSError:
        stamp = ()
    key = (stamp, tuple(sorted(known)))
    if _findings_counts["mtime"] != key:
        per, broken = {}, False
        for f in files:
            rep = parse_sarif(f, known)
            broken = broken or bool(rep.get("error"))
            for row in rep["findings"]:
                lv = per.setdefault(row["project"] or "", {})
                lv[row["level"]] = lv.get(row["level"], 0) + 1
        # A report that failed to parse is not cached: half-written is the
        # usual reason, and the next poll should read it whole.
        _findings_counts.update(mtime=None if broken else key, projects=per)
    valid = _valid_projects(ps)
    return {p: lv for p, lv in _findings_counts["projects"].items()
            if not p or p in valid}


def snapshot():
    ps = projects()
    sessions = tmux_sessions()
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
        "projects": ps,
        "sessions": sessions,
        "runner": runner(),
        "reports": REPORTS.is_dir(),
        "reports_mtime": reports_mtime(),
        "findings_counts": findings_counts(ps),
        "doctor": doctor_payload(),
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
        if self.path.startswith("/api/status"):
            return self._json(snapshot())
        if self.path.startswith("/api/findings"):
            return self._json(findings_payload())
        if self.path.startswith("/api/packages"):
            return self._json(packages_payload())
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
        if path.startswith("/api/exclude"):
            return self._exclude(req)
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
        if path.startswith("/api/packages"):
            return self._packages(req)
        if path.startswith("/api/custom"):
            return self._custom(req)
        if path.startswith("/api/doctor"):
            return self._doctor(req)
        self._json({"error": "not found"}, 404)

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
        """Create a project under /workspace: a fresh local repo, or a clone
        of a GitHub repository the container's credentials can already reach.

        The name is validated before it becomes a path and the URL before it
        becomes an argument — see PROJECT_NAME and GITHUB_URL for why both are
        allow-lists. The clone runs with prompts disabled so missing access
        fails with git's own message instead of hanging a request forever on a
        username prompt nobody can answer.

        mkdir is the claim: it is atomic, so two requests racing on one name
        get one directory and one clean "already exists". On failure the
        directory this request just made is removed — never one that was
        already there, which is the FileExistsError branch returning first.
        """
        mode = req.get("mode")
        if mode not in ("init", "clone"):
            return self._json({"error": "unknown mode"}, 400)
        url = (req.get("url") or "").strip()
        if mode == "clone":
            if not GITHUB_URL.fullmatch(url):
                return self._json({"error": "not a GitHub repository address — "
                                   "use https://github.com/owner/repo or "
                                   "git@github.com:owner/repo.git"}, 400)
            # The repository already knows its name; asking again would just
            # invite a second spelling of the same thing. Notes are not asked
            # for either — they are drafted from the code after the clone.
            name = re.split(r"[/:]", url.rstrip("/"))[-1]
            name = name[:-4] if name.endswith(".git") else name
            about = ""
            # An optional deploy key, by name. The name is only ever matched
            # against what the agent actually holds — nothing from the request
            # is written into a file or a config line; the matched key's own
            # public line is. When one is chosen the clone goes through a
            # per-repo alias (see ensure_deploy_alias for why), which also
            # leaves the remote pointing at that alias, so pushes keep using
            # the right key without anyone re-doing this by hand.
            keyname = (req.get("key") or "").strip()
            if keyname:
                match = next((k for k in agent_keys()
                              if k["name"] == keyname), None)
                if match is None:
                    return self._json({"error": f"the agent holds no key "
                                                f"named {keyname}"}, 400)
                alias = ensure_deploy_alias(match["name"], match["pub"])
                url = f"git@{alias}:{repo_path(url)}.git"
        else:
            name = (req.get("name") or "").strip()
            about = (req.get("about") or "").strip()
        if not PROJECT_NAME.fullmatch(name):
            return self._json({"error": "a project name is one path segment: "
                               "letters, digits, dots, dashes, underscores, "
                               "starting with a letter or digit"}, 400)
        dest = WORKSPACE / name
        with _create_lock:
            try:
                dest.mkdir()
            except FileExistsError:
                return self._json({"error": f"{name} already exists in the "
                                            "workspace"}, 400)
            except OSError as e:
                return self._json({"error": f"cannot create {name}: {e}"}, 500)
            if mode == "clone":
                # BatchMode so a key the agent does not hold fails instead of
                # prompting; accept-new because the first contact with github.com
                # on a fresh home volume is expected, not an attack to refuse.
                env = dict(os.environ, GIT_TERMINAL_PROMPT="0",
                           GIT_SSH_COMMAND="ssh -o BatchMode=yes "
                                           "-o StrictHostKeyChecking=accept-new")
                r = run(["git", "clone", "--", url, str(dest)],
                        timeout=600, env=env)
            else:
                r = run(["git", "init", "-b", "main", str(dest)], timeout=30)
            if r["code"] != 0:
                shutil.rmtree(dest, ignore_errors=True)   # made a moment ago
                return self._json({"error": r["out"].strip()[-2000:]
                                            or f"git {mode} failed"}, 500)

            # The CLAUDE.md. A cloned repo that already carries one keeps it;
            # one that does not gets a draft read out of its own files — the
            # README's opening and whatever the marker files say about
            # building it. A fresh local repo gets the operator's notes.
            md = dest / "CLAUDE.md"
            if md.is_file():
                note = "kept the repository's own CLAUDE.md"
            else:
                if mode == "clone":
                    about = describe_repo(dest) or ""
                body = build_claude_md(about)
                if body is None:
                    note = "no CLAUDE.md template in this image; none written"
                else:
                    try:
                        md.write_text(body)
                        note = (("CLAUDE.md drafted from the repository's own files"
                                 if mode == "clone" else
                                 "CLAUDE.md created from your notes") if about
                                else "CLAUDE.md created from the template")
                    except OSError as e:
                        note = f"could not write CLAUDE.md: {e}"
        return self._json({"ok": True, "name": name, "note": note})

    def _link(self, req):
        """Point an existing local repo at an *empty* GitHub repository and
        push what it has.

        Empty-only is the safety property: `git ls-remote` must come back
        with no refs before anything is pushed, so this can never write over
        a repository that already holds work. The one thing it will create is
        a repo that does not exist at all — PAT path only, always private —
        because "not found" from GitHub is the one answer that proves there
        is nothing there to harm.

        Auth mirrors the clone: a picked deploy key means an ssh alias, no
        key means the PAT answers for https — and with neither, this refuses
        up front instead of letting the push discover it.

        There is no lock around check-then-add: two racing links resolve at
        `git remote add`, which refuses a duplicate origin, and the loser's
        error says exactly that.
        """
        name = (req.get("name") or "").strip()
        url = (req.get("url") or "").strip()
        keyname = (req.get("key") or "").strip()
        try:
            here = {d.name for d in WORKSPACE.iterdir() if d.is_dir()}
        except OSError:
            here = set()
        if name not in here:
            return self._json({"error": f"unknown project: {name}"}, 400)
        dest = str(WORKSPACE / name)
        if run(["git", "-C", dest, "rev-parse", "--is-inside-work-tree"],
               timeout=10)["out"].strip() != "true":
            return self._json({"error": f"{name} is not a git repository"}, 400)
        if run(["git", "-C", dest, "remote"], timeout=10)["out"].strip():
            return self._json({"error": f"{name} already has a remote"}, 400)
        if not GITHUB_URL.fullmatch(url):
            return self._json({"error": "not a GitHub repository address — use "
                               "https://github.com/owner/repo or "
                               "git@github.com:owner/repo.git"}, 400)
        path = repo_path(url)
        pat = gh_authed()
        if keyname:
            match = next((k for k in agent_keys() if k["name"] == keyname), None)
            if match is None:
                return self._json({"error": f"the agent holds no key named "
                                            f"{keyname}"}, 400)
            remote = f"git@{ensure_deploy_alias(match['name'], match['pub'])}:{path}.git"
        elif pat:
            # Plain https: gh's credential helper (wired at startup) answers
            # for it, so nothing secret lands in .git/config.
            remote = f"https://github.com/{path}.git"
        else:
            return self._json({"error": "no PAT is configured and no deploy key "
                               "was picked — a push needs one of the two"}, 400)

        env = dict(os.environ, GIT_TERMINAL_PROMPT="0",
                   GIT_SSH_COMMAND="ssh -o BatchMode=yes "
                                   "-o StrictHostKeyChecking=accept-new")
        created = ""
        # split_err: emptiness is judged on stdout alone. ssh's first-contact
        # "Permanently added github.com ..." note arrives on stderr with exit
        # 0, and combined it made a genuinely empty repository look occupied.
        r = run(["git", "ls-remote", "--", remote], timeout=60, env=env,
                split_err=True)
        if r["code"] != 0:
            blame = (r["err"] + r["out"]).strip()
            if "not found" in blame.lower() and keyname:
                # Creating it here would not help: a brand-new repo has no
                # deploy keys, so the push over this alias still fails — and
                # a retry would then trip over the half-done state. Say what
                # the fix actually is instead.
                return self._json({"error": "GitHub reports the repository as "
                                   "not found over ssh. Create it (empty) on "
                                   "GitHub and add this deploy key to it first"
                                   + (", or leave the key on none to use the "
                                      "PAT" if pat else "") + "."}, 400)
            if "not found" in blame.lower() and pat:
                c = run(["gh", "repo", "create", path, "--private"], timeout=60)
                if c["code"] != 0:
                    return self._json({"error": c["out"].strip()[-2000:]
                                                or "gh repo create failed"}, 500)
                created = f"created {path} on GitHub (private); "
            else:
                return self._json({"error": blame[-2000:]
                                            or "cannot reach that repository"}, 500)
        elif r["out"].strip():
            return self._json({"error": "that repository is not empty — linking "
                               "only targets empty repositories, so nothing can "
                               "be overwritten"}, 400)

        a = run(["git", "-C", dest, "remote", "add", "origin", remote], timeout=10)
        if a["code"] != 0:
            return self._json({"error": a["out"].strip() or "remote add failed"}, 500)
        if run(["git", "-C", dest, "rev-parse", "-q", "--verify", "HEAD"],
               timeout=10)["code"] != 0:
            return self._json({"ok": True, "name": name,
                               "note": created + "remote set — nothing committed "
                                                 "yet, so nothing was pushed"})
        p = run(["git", "-C", dest, "push", "-u", "origin", "HEAD"],
                timeout=300, env=env)
        if p["code"] != 0:
            # The remote stays: it is correct configuration, and the push is
            # the retryable part — from here or from any shell.
            return self._json({"error": created + "the remote was set, but the "
                               "push failed:\n" + p["out"].strip()[-2000:]}, 500)
        branch = run(["git", "-C", dest, "symbolic-ref", "--short", "-q", "HEAD"],
                     timeout=10)["out"].strip() or "HEAD"
        return self._json({"ok": True, "name": name,
                           "note": f"{created}pushed {branch}"})

    def _packages(self, req):
        """Queue installs or removals of the packages the Tools card offers.

        Names are checked against PACKAGES rather than passed through: what
        reaches a command line is a string this server chose, which is the
        rule every other executing endpoint here follows.
        """
        action = req.get("action")
        if action not in ("install", "remove", "update", "check"):
            return self._json({"error": "unknown action"}, 400)
        known = {p["name"] for p in PACKAGES}
        names = [n for n in (req.get("names") or []) if n in known]
        # Checking is about everything, not a selection: the question it
        # answers is "is any of this out of date, and what would the rest of
        # it install". The uninstalled rows are half the reason to press it —
        # a version you can read before spending the gigabytes.
        if action == "check" and not names:
            names = [p["name"] for p in PACKAGES]
        if not names:
            return self._json({"error": "nothing selected"}, 400)
        with _pkg_lock:
            if _pkg_job["running"]:
                return self._json({"error": "an install is already running"}, 409)
            _pkg_job.update(running=True, queue=list(names), action=action,
                            current="", log=[], done=[], failed=[])
        threading.Thread(target=_pkg_worker, daemon=True).start()
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

    def _exclude(self, req):
        """Add or remove a project from the exclusion list.

        Names are checked against the directories that actually exist, so this
        cannot be used to write arbitrary strings into a file another script
        reads — and excluding something that has since been unmounted is a
        no-op rather than a permanent stale entry.
        """
        name, on = req.get("name", ""), bool(req.get("excluded"))
        try:
            here = {d.name for d in WORKSPACE.iterdir() if d.is_dir()}
        except OSError:
            here = set()
        if name not in here:
            return self._json({"error": f"unknown project: {name}"}, 400)
        with _state_lock:
            names = set(load_excludes())
            names.add(name) if on else names.discard(name)
            try:
                save_excludes(names)
            except OSError as e:
                return self._json({"error": f"could not save: {e}"}, 500)

        # An excluded project must not keep a live session running — leaving one
        # attached would mean the exclusion takes effect only next time, which
        # is not what a button labeled "exclude" implies.
        killed = None
        sess = tmux_name(f"claude-{name}")
        if on and sess in {s["name"] for s in tmux_sessions()}:
            run(["tmux", "kill-session", "-t", sess], timeout=10)
            killed = sess
        return self._json({"excluded": sorted(names), "killed": killed})

    def _session(self, req):
        """Kill a session. Closing a tab that owns a Claude conversation should
        end it, or detached sessions accumulate invisibly behind a tidy UI."""
        session = req.get("session", "")
        if req.get("action") != "kill":
            return self._json({"error": "unknown action"}, 400)
        if session not in {s["name"] for s in tmux_sessions()}:
            return self._json({"error": f"no such session: {session}"}, 400)
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
    # Daemon: the doctor loop must die with the server, not hold it open.
    threading.Thread(target=_doctor_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
