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
# This is `bb`'s whole command surface, in the order the card lists it. Commands
# that prompt or follow (`login`, `logs -f`) are fine here because a macro is
# typed into the real terminal rather than captured — the operator answers the
# prompt or presses Ctrl-C exactly as if they had typed it. The one command left
# out is `bb shell`, which from a terminal only nests a second shell inside the
# one it was typed into.
MACROS = {
    "status":           ["bb", "status"],
    "doctor":           ["bb", "doctor"],
    "projects":         ["bb", "projects"],
    "logs":             ["bb", "logs", "200"],
    "logs-follow":      ["bb", "logs", "-f"],
    "logs-list":        ["bb", "logs", "--list"],
    "runner-status":    ["bb", "runner", "status"],
    "runner-stop":      ["bb", "runner", "stop"],
    "runner-start":     ["bb", "runner", "start"],
    "runner-restart":   ["bb", "runner", "restart"],
    "emu-list":         ["bb", "emu", "list"],
    "emu-start":        ["bb", "emu", "start"],
    "emu-status":       ["bb", "emu", "status"],
    "emu-stop":         ["bb", "emu", "stop"],
    "claude-md":        ["bb", "claude-md"],
    "claude-md-update": ["bb", "claude-md", "--update"],
    "claude-md-init":   ["bb", "claude-md", "--init"],
    "findings":         ["bb", "findings"],
    "findings-all":     ["bb", "findings", "--all"],
    "update":           ["bb", "update"],
    "login":            ["bb", "login"],
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


def projects():
    out = []
    if not WORKSPACE.is_dir():
        return out
    uid, gid = os.getuid(), os.getgid()
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
        if not d.is_dir() or d.name == "_work":
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
                    issues.append({"level": "warning", "text": "no CLAUDE.md"})

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
    """Session name -> the working directory of its active pane.

    Where a terminal *is* right now, which is not where it was opened: the tab
    is labelled from this, so a `cd` shows up in the strip.
    """
    r = run(["tmux", "list-panes", "-a", "-F",
             "#{session_name}\t#{pane_active}\t#{pane_current_path}"], timeout=10)
    out = {}
    if r["code"] != 0:
        return out
    for line in r["out"].splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[1] == "1":
            out[parts[0]] = parts[2]
    return out


def tmux_sessions():
    r = run(["tmux", "list-sessions", "-F", "#{session_name}\t#{session_attached}"],
            timeout=10)
    if r["code"] != 0:
        return []          # no server running yet is the normal empty case
    cwds = session_cwds()
    rows = []
    for line in r["out"].splitlines():
        if "\t" in line:
            name, attached = line.split("\t", 1)
            rows.append({"name": name, "attached": attached.strip() not in ("", "0"),
                         "cwd": cwds.get(name, "")})
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


def snapshot():
    return {
        "host": os.uname().nodename,
        "uptime": uptime(),
        "projects": projects(),
        "sessions": tmux_sessions(),
        "runner": runner(),
        "ttyd_port": TTYD_PUBLIC_PORT,
        "reports": REPORTS.is_dir(),
        "max_tabs": MAX_TABS,
        # The command list is built from the table above rather than spelled out
        # again in the page, so a command added here appears as a button and one
        # removed cannot leave a button that posts a name the server rejects.
        "macros": [{"name": k, "label": " ".join(v[1:])} for k, v in MACROS.items()],
        "pinned": load_pins(),
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
        self._json({"error": "not found"}, 404)

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

        Still a name from the fixed table, never a command string — the page
        cannot ask for anything not listed above, and what lands in the
        terminal is exactly what the operator would have typed.
        """
        session, name = req.get("session", ""), req.get("macro", "")
        if name not in MACROS:
            return self._json({"error": f"unknown macro: {name}"}, 400)
        if session not in {s["name"] for s in tmux_sessions()}:
            return self._json({"error": f"no such session: {session}"}, 400)
        # Never into a Claude session: that would not run the command, it would
        # submit it as a prompt.
        if session.startswith("claude-"):
            return self._json({"error": "refusing to type into a Claude session"}, 400)
        line = shlex.join(MACROS[name])
        r = run(["tmux", "send-keys", "-t", session, "-l", line], timeout=10)
        if r["code"] != 0:
            return self._json(r)
        return self._json(run(["tmux", "send-keys", "-t", session, "Enter"], timeout=10)
                          | {"sent": line})


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
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
