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
import json
import os
import re
import shlex
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
PORT = int(os.environ.get("DASHBOARD_PORT", "8080"))
AUTH = os.environ.get("DASHBOARD_AUTH", "")
TTYD_PORT = int(os.environ.get("DASHBOARD_TTYD_PORT", "7681"))
# What the *browser* should connect to. Identical to TTYD_PORT unless the host
# publishes the terminal on a different port, which nothing inside the
# container can see — Docker port mappings are invisible from in here. Getting
# this wrong is quiet: the page loads and only the terminal fails.
TTYD_PUBLIC_PORT = int(os.environ.get("DASHBOARD_TTYD_PUBLIC_PORT") or TTYD_PORT)

# Every command the UI can run, by name. The UI posts a key from this table and
# nothing else — no argument passthrough, no shell. A dashboard that accepted a
# command string would be a remote shell with extra steps, and there is already
# a real terminal one port over for anything not listed here.
#
# This is `bb`'s command surface, in `bb help`'s own order — the card is the
# same list in the same sequence, so what you learn from one you can find in the
# other. Commands that prompt or follow (`login`, `logs -f`) belong here because
# a macro is typed into the real terminal rather than captured: the operator
# answers the prompt or presses Ctrl-C exactly as if they had typed it.
#
# Two rules about what is NOT here. Nothing but `bb` — anything else belongs in
# the terminal, which is one click away. And nothing that needs an argument to
# mean anything: every entry below is a command that does the right thing typed
# exactly as it stands, so a button is never a half-written command line. That
# leaves out `bb shell`, which from a terminal only nests a second shell inside
# the one it was typed into.
MACROS = {
    "status":           ["bb", "status"],
    "projects":         ["bb", "projects"],
    "update":           ["bb", "update"],
    "login":            ["bb", "login"],
    "runner-status":    ["bb", "runner", "status"],
    "runner-stop":      ["bb", "runner", "stop"],
    "runner-start":     ["bb", "runner", "start"],
    "runner-restart":   ["bb", "runner", "restart"],
    "emu-start":        ["bb", "emu", "start"],
    "emu-stop":         ["bb", "emu", "stop"],
    "emu-status":       ["bb", "emu", "status"],
    "emu-list":         ["bb", "emu", "list"],
    "claude-md":        ["bb", "claude-md"],
    "claude-md-update": ["bb", "claude-md", "--update"],
    "claude-md-init":   ["bb", "claude-md", "--init"],
    "lint":             ["bb", "lint"],
    "findings":         ["bb", "findings"],
    "findings-all":     ["bb", "findings", "--all"],
    "logs":             ["bb", "logs"],
    "logs-follow":      ["bb", "logs", "-f"],
    "logs-prev":        ["bb", "logs", "-p"],
    "logs-list":        ["bb", "logs", "--list"],
    "doctor":           ["bb", "doctor"],
}

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
# rule only the dashboard honoured would be advice, since the terminal URL is
# reachable on its own.
STATE = Path(os.environ.get("DASHBOARD_STATE", "/config"))
EXCLUDES_FILE = STATE / "excluded-projects.json"

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

# What a stored tab may contain. Anything else is dropped rather than trusted:
# this file is written by one browser and handed to every other one, so it is
# the one place where a bad value could travel between devices.
TAB_KINDS = {"term", "findings"}


def load_layout():
    try:
        v = json.loads(TABS_FILE.read_text())
    except (OSError, ValueError):
        v = {}
    tabs, ids = [], set()
    for t in (v.get("tabs") or [])[:MAX_TABS]:
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
    panes = [p if p in ids else None for p in (v.get("panes") or [None, None])[:2]]
    while len(panes) < 2:
        panes.append(None)
    return {"rev": int(v.get("rev") or 0), "tabs": tabs, "panes": panes,
            "active": 1 if v.get("active") == 1 and panes[1] else 0}


def save_layout(v):
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = TABS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(v | {"boot": boot_id()}, indent=2) + "\n")
    tmp.replace(TABS_FILE)


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
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = CUSTOM_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(macros, indent=2) + "\n")
    tmp.replace(CUSTOM_FILE)


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
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = PINS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sorted(set(names)), indent=2) + "\n")
    tmp.replace(PINS_FILE)


def load_excludes():
    try:
        v = json.loads(EXCLUDES_FILE.read_text())
        return sorted({x for x in v if isinstance(x, str)}) if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def save_excludes(names):
    """Write via a temp file in the same directory, then rename.

    bb-tty reads this on every session launch; a half-written file would be a
    parse error at exactly the moment someone is trying to start work.
    """
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = EXCLUDES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sorted(set(names)), indent=2) + "\n")
    tmp.replace(EXCLUDES_FILE)


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


def findings_payload():
    known = {p["name"] for p in projects()}
    if not REPORTS.is_dir():
        return {"available": False, "reports": [], "projects": sorted(known)}
    files = sorted(f for f in REPORTS.glob("*.sarif")) + \
            sorted(f for f in REPORTS.glob("*.sarif.json"))
    return {"available": True, "projects": sorted(known),
            "reports": [parse_sarif(f, known) for f in files]}


def run(cmd, cwd=None, timeout=120):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout)
        return {"cmd": shlex.join(cmd), "code": p.returncode,
                "out": (p.stdout or "") + (p.stderr or "")}
    except subprocess.TimeoutExpired:
        return {"cmd": shlex.join(cmd), "code": 124,
                "out": f"timed out after {timeout}s"}
    except FileNotFoundError as e:
        return {"cmd": shlex.join(cmd), "code": 127, "out": str(e)}


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
        if not d.is_dir() or d.name == "_work" or d.name.startswith("."):
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

        branch, git_ok = None, False
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
                    "claude_md": has_md, "excluded": d.name in excluded,
                    "last_claude": None if d.name in excluded else last_claude(d, d.name, stopped),
                    "issues": issues})
    return out


def session_cwds():
    """Session name -> {cwd, title} of its active pane.

    cwd is where a terminal *is* right now, which is not where it was opened:
    the tab is labelled from this, so a `cd` shows up in the strip. The pane
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


def snapshot():
    return {
        "host": os.uname().nodename,
        "uptime": uptime(),
        "projects": projects(),
        "sessions": tmux_sessions(),
        "runner": runner(),
        "ttyd_port": TTYD_PUBLIC_PORT,
        "reports": REPORTS.is_dir(),
        "reports_mtime": reports_mtime(),
        "doctor": doctor_payload(),
        "max_tabs": MAX_TABS,
        # The command list is built from the table above rather than spelled out
        # again in the page, so a command added here appears as a button and one
        # removed cannot leave a button that posts a name the server rejects.
        "macros": [{"name": k, "label": " ".join(v[1:])} for k, v in MACROS.items()],
        "pinned": load_pins(),
        "custom": load_custom(),
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
        if not hdr.startswith("Basic "):
            return False
        try:
            given = base64.b64decode(hdr[6:]).decode("utf-8", "replace")
        except (ValueError, UnicodeDecodeError):
            return False
        # Compare the whole "user:pass" so a correct username with a wrong
        # password is indistinguishable from both being wrong.
        return _constant_eq(given, AUTH)

    def _deny(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="BuilderBot"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
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

    def _get(self):
        if not self._authed():
            return self._deny()
        if self.path.split("?")[0] in ("/", "/index.html"):
            body = (HERE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if self.path.startswith("/api/status"):
            return self._json(snapshot())
        if self.path.startswith("/api/findings"):
            return self._json(findings_payload())
        self._json({"error": "not found"}, 404)

    def _post(self):
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
        if path.startswith("/api/pin"):
            return self._pin(req)
        if path.startswith("/api/claude-md"):
            return self._claude_md(req)
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

    def _pin(self, req):
        """Pin or unpin a command. Names are keys from MACROS, so this file can
        never grow an entry the card would not know what to do with."""
        name, on = req.get("name", ""), bool(req.get("pinned"))
        if name not in MACROS:
            return self._json({"error": f"unknown macro: {name}"}, 400)
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
        cur = load_layout()
        v = {"rev": cur["rev"] + 1,
             "tabs": req.get("tabs") or [],
             "panes": req.get("panes") or [None, None],
             "active": req.get("active") or 0}
        try:
            save_layout(v)
        except OSError as e:
            return self._json({"error": f"could not save: {e}"}, 500)
        # Re-read so the caller gets exactly what every other client will see,
        # including anything the validator dropped.
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
        names = set(load_excludes())
        names.add(name) if on else names.discard(name)
        try:
            save_excludes(names)
        except OSError as e:
            return self._json({"error": f"could not save: {e}"}, 500)

        # An excluded project must not keep a live session running — leaving one
        # attached would mean the exclusion takes effect only next time, which
        # is not what a button labelled "exclude" implies.
        killed = None
        if on and f"claude-{name}" in {s["name"] for s in tmux_sessions()}:
            run(["tmux", "kill-session", "-t", f"claude-{name}"], timeout=10)
            killed = f"claude-{name}"
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
        if key in TMUX_KEYS:
            return self._json(run(["tmux", "send-keys", "-t", session,
                                   TMUX_KEYS[key]], timeout=10))
        if key in TMUX_LITERALS:
            return self._json(run(["tmux", "send-keys", "-t", session, "-l",
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
            if name not in MACROS:
                return self._json({"error": f"unknown macro: {name}"}, 400)
            lines = [shlex.join(MACROS[name])]
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
        # labelled `bb status` should be able to do.
        run(["tmux", "send-keys", "-t", session, "C-e", "C-u"], timeout=10)
        # Typed one after another without waiting. That is what happens when a
        # person types ahead too — the tty buffers the input and the shell reads
        # each line when it is ready for one.
        for line in lines:
            r = run(["tmux", "send-keys", "-t", session, "-l", line], timeout=10)
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
