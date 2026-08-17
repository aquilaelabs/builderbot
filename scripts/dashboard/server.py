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
    for d in sorted(WORKSPACE.iterdir()):
        if not d.is_dir() or d.name == "_work":
            continue
        branch = None
        if (d / ".git").exists():
            r = run(["git", "-C", str(d), "symbolic-ref", "--short", "-q", "HEAD"], timeout=10)
            branch = r["out"].strip() or "(detached)"
        out.append({"name": d.name, "git": branch,
                    "claude_md": (d / "CLAUDE.md").is_file()})
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


def runner():
    d = Path(os.environ.get("RUNNER_DIR", "/opt/actions-runner"))
    info = {"registered": False, "listening": False, "name": None, "url": None}
    cfg = d / ".runner"
    if cfg.is_file():
        info["registered"] = True
        try:
            j = json.loads(cfg.read_text())
            info["name"] = j.get("agentName")
            info["url"] = j.get("gitHubUrl")
        except (ValueError, OSError):
            pass
    info["listening"] = run(["pgrep", "-f", "Runner.Listener"], timeout=10)["code"] == 0
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
        "reports": Path("/reports").is_dir(),
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

    def do_GET(self):
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
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._authed():
            return self._deny()
        # Read the body once, here, rather than in each handler: doing it after
        # dispatch is how the request stream ends up consumed twice or not at all.
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, TypeError):
            return self._json({"error": "bad request"}, 400)

        path = self.path.split("?")[0]
        if path.startswith("/api/keys"):
            return self._keys(req)
        if path.startswith("/api/run"):
            return self._run(req)
        self._json({"error": "not found"}, 404)

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
        self._json({"error": f"unknown macro: {name}"})

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
