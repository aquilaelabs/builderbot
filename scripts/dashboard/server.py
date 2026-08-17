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
MACROS = {
    "status":        ["bb", "status"],
    "doctor":        ["bb", "doctor"],
    "projects":      ["bb", "projects"],
    "runner-status": ["bb", "runner", "status"],
    "runner-stop":   ["bb", "runner", "stop"],
    "runner-start":  ["bb", "runner", "start"],
    "runner-restart":["bb", "runner", "restart"],
    "emu-list":      ["bb", "emu", "list"],
    "emu-start":     ["bb", "emu", "start"],
    "emu-stop":      ["bb", "emu", "stop"],
    "emu-status":    ["bb", "emu", "status"],
    "logs":          ["bb", "logs", "200"],
    "update":        ["bb", "update"],
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


# Macros that take a project as their working directory rather than an argument.
PROJECT_MACROS = {
    "findings":  ["bb", "findings"],
    "claude-md": ["bb", "claude-md"],
}


# Every request body here is a handful of short JSON fields. Anything larger is
# a mistake or a probe, and reading it into memory unbounded helps neither.
MAX_BODY = 64 * 1024

CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}")
REPORTS = Path(os.environ.get("FINDINGS_DIR", "/reports"))


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
    for d in sorted(WORKSPACE.iterdir()):
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
        out.append({"name": d.name, "git": branch, "git_ok": git_ok,
                    "claude_md": has_md, "issues": issues})
    return out


def tmux_sessions():
    r = run(["tmux", "list-sessions", "-F", "#{session_name}\t#{session_attached}"],
            timeout=10)
    if r["code"] != 0:
        return []          # no server running yet is the normal empty case
    rows = []
    for line in r["out"].splitlines():
        if "\t" in line:
            name, attached = line.split("\t", 1)
            rows.append({"name": name, "attached": attached.strip() not in ("", "0")})
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


def _pidfile_alive(p):
    """Is the process named by this pidfile still there? A stale file is a no."""
    try:
        pid = int(p.read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


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
        pid = w["out"].split()[0] if w["out"].split() else None
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
        if path.startswith("/api/session"):
            return self._session(req)
        if path.startswith("/api/keys"):
            return self._keys(req)
        if path.startswith("/api/run"):
            return self._run(req)
        self._json({"error": "not found"}, 404)

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

    def _run(self, req):
        name, proj = req.get("macro", ""), req.get("project")
        if name in MACROS:
            return self._json(run(MACROS[name]))
        if name in PROJECT_MACROS:
            names = {p["name"] for p in projects()}
            if proj not in names:
                return self._json({"error": f"unknown project: {proj}"}, 400)
            return self._json(run(PROJECT_MACROS[name], cwd=str(WORKSPACE / proj)))
        self._json({"error": f"unknown macro: {name}"}, 400)


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
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
