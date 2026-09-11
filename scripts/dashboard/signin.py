#!/usr/bin/env python3
"""Signing in to Claude, without a terminal in it.

`claude auth login` is interactive: it prints a URL and waits for the code the
browser gives back. That made it look like a job for a terminal, so it got
one — a tmux session behind ttyd behind a tab. Every part of that turned out
to be a place for it to go wrong. ttyd reconnects a dropped socket, so closing
the flow started another; a phone cannot select a wrapped URL out of a canvas,
and a paste into one silently does not arrive, so the code reaching the prompt
empty read as a rejected code; and the tab itself zooms and reflows under a
thumb while you are trying to work in it.

None of that was the sign-in. The sign-in is two lines of text going in
opposite directions, and a program that wants a terminal only wants a pty.
So the server holds one: it runs the flow, reads the URL off it, and writes
the code into it when the dashboard hands one over. What the operator sees is
a link and a text field, which is what a phone is good at.

The server imports this and hands it `run`; nothing here reaches back.
"""
import contextlib
import os
import pty
import re
import select
import signal
import subprocess
import threading
import time

# The URL the flow prints, and the two things it says when it is over.
AUTH_URL = re.compile(r"https://(?:claude\.com|console\.anthropic\.com|"
                      r"platform\.claude\.com)/\S+")
PROMPT = "Paste code"

# A flow nobody finishes should not hold a process for the life of the
# container. Long enough to walk to a desktop, short enough to be forgotten.
MAX_LIFE = 15 * 60

_lock = threading.Lock()
_flow = None


class Flow:
    """One run of `claude auth login`, and everything the page needs of it."""

    def __init__(self):
        self.out = ""
        self.url = ""
        self.waiting = False        # the prompt is up; a code can be sent
        self.sent = False           # a code has gone in
        self.done = False
        self.ok = False
        self.at = time.time()
        self._master = None
        self._proc = None

    # -- the flow itself ---------------------------------------------------
    def start(self, home=""):
        master, slave = pty.openpty()
        # In the ASKING account's home, not the dashboard's own (roadmap #26).
        # `claude auth login` writes the credential to $HOME/.claude, and
        # accounts have a home each — so run with the dashboard's environment
        # and this card signs the wrong person in, silently and every time.
        # This is the onboarding path for a new account, not an afterthought.
        env = dict(os.environ)
        if home:
            env["HOME"] = home
        # A pty, not a pipe: the flow writes its prompt without a newline and
        # a pipe would have it sitting in a buffer nobody ever sees.
        self._proc = subprocess.Popen(
            ["claude", "auth", "login"], stdin=slave, stdout=slave,
            stderr=slave, start_new_session=True, close_fds=True, env=env)
        os.close(slave)
        self._master = master
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while True:
            if time.time() - self.at > MAX_LIFE:
                self.cancel()
                break
            try:
                r, _, _ = select.select([self._master], [], [], 0.5)
            except (OSError, ValueError):
                break
            if r:
                try:
                    chunk = os.read(self._master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                self.out = (self.out + chunk.decode("utf-8", "replace"))[-8000:]
                m = AUTH_URL.search(self.out)
                if m and not self.url:
                    self.url = m.group(0)
                if PROMPT in self.out:
                    self.waiting = True
            if self._proc.poll() is not None:
                break
        code = self._proc.poll()
        self.ok = code == 0
        self.done = True
        with _lock:
            self._shut()

    def _shut(self):
        if self._master is not None:
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = None

    def submit(self, code):
        if self.done or self._master is None:
            return {"error": "that sign-in is over — start another"}
        if not self.waiting:
            return {"error": "it is not asking for a code yet"}
        try:
            os.write(self._master, (code + "\n").encode())
        except OSError as e:
            return {"error": f"could not hand it over: {e}"}
        self.sent = True
        return {"ok": True}

    def cancel(self):
        if self._proc and self._proc.poll() is None:
            try:
                os.killpg(self._proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        self.done = True
        with _lock:
            self._shut()

    # -- what the page is told --------------------------------------------
    def state(self):
        return {"running": not self.done, "url": self.url,
                "waiting": self.waiting and not self.sent,
                "sent": self.sent and not self.done,
                "done": self.done, "ok": self.ok,
                "error": "" if self.ok or not self.done else self._why()}

    def _why(self):
        """The line that says what went wrong, out of what it printed.

        The last non-empty line that is not the URL and not the prompt: the
        flow ends by saying "Login failed: …", and the two lines before it are
        a hundred characters of query string nobody wants read back to them.
        """
        for line in reversed(self.out.splitlines()):
            line = line.strip()
            if not line or line.startswith("http") or PROMPT in line:
                continue
            return line[-300:]
        return "the sign-in did not finish"


# How long start() waits for the URL before answering. The flow takes about a
# second to print it, and a button that returns before then leaves the card
# saying "starting the sign-in…" until the next poll — which is how a link
# that is ready in a second took fifteen to appear.
URL_WAIT = 6


class NodeFlow:
    """The same flow, run on a NODE (roadmap R47).

    Claude Code is installed where sessions run, and after R47 this container
    carries none — so the flow has to happen over there. It is a job of its
    own on the node, under a pty, as that machine's session account; what it
    prints comes back as the job's log and the code goes down on the reply to
    a log post, the channel `cancel` has always used.

    The same three questions the local Flow answers — what is the URL, is it
    asking, did it work — read off the job's log and state instead of a pty
    this process holds. Everything above this line is what the page sees, so
    the card does not know or care which of the two it is talking to.
    """

    def __init__(self, nodes, node_id, job_id, name=""):
        self._nodes, self.node, self.job = nodes, node_id, job_id
        self.node_name = name
        self.sent = False

    def _log(self):
        j = self._nodes.job(self.job) or {}
        return j, (j.get("log") or "")

    def submit(self, code):
        j, _ = self._log()
        if not j or j.get("state") in ("succeeded", "failed", "canceled"):
            return {"error": "that sign-in is over — start another"}
        r = self._nodes.job_input(self.job, code)
        if r.get("error"):
            return r
        self.sent = True
        return {"ok": True}

    def cancel(self):
        with contextlib.suppress(Exception):
            self._nodes.job_cancel("user:signin", self.job)
        return {"ok": True}

    def state(self):
        j, out = self._log()
        done = (j.get("state") or "") in ("succeeded", "failed", "canceled")
        m = AUTH_URL.search(out)
        why = ""
        if done and j.get("state") != "succeeded":
            for line in reversed(out.splitlines()):
                line = line.strip()
                if line and not line.startswith("http") and PROMPT not in line:
                    why = line[-300:]
                    break
            why = why or "the sign-in did not finish"
        return {"running": not done, "url": m.group(0) if m else "",
                "waiting": bool(PROMPT in out) and not self.sent and not done,
                "sent": self.sent and not done,
                "done": done, "ok": j.get("state") == "succeeded",
                "on": self.node_name, "job": self.job, "error": why}


def start_on_node(nodes, node_id, uid, name=""):
    """Begin a flow on a node. Same contract as start(): it replaces whatever
    was running and waits a moment for the URL, so the button that is already
    waiting gets the link in its own answer."""
    global _flow
    with _lock:
        old = _flow
    if old:
        old.cancel()
    r = nodes.job_add("user:signin", {"node": node_id}, "claude-login",
                      {"uid": str(uid), "timeout": 900})
    if r.get("error"):
        return r
    f = NodeFlow(nodes, node_id, r["job"], name)
    with _lock:
        _flow = f
    t0 = time.time()
    while time.time() - t0 < URL_WAIT and not f.state()["url"] \
            and f.state()["running"]:
        time.sleep(0.1)
    return {"ok": True, "job": r["job"], "on": name}


def start(home=""):
    """Begin a flow, replacing any that is there. Pressing Sign in is the one
    thing that means start over, so it always does.

    `home` is the requesting account's, so the credential lands in their own
    ~/.claude rather than the dashboard's.

    Waits for the URL rather than returning the moment the process exists:
    the answer is worth having in the response that the button is already
    waiting on.
    """
    global _flow
    with _lock:
        old = _flow
    if old:
        old.cancel()
    f = Flow()
    f.start(home)
    with _lock:
        _flow = f
    t0 = time.time()
    while time.time() - t0 < URL_WAIT and not f.url and not f.done:
        time.sleep(0.05)
    return {"ok": True}


def submit(code):
    with _lock:
        f = _flow
    return f.submit(code) if f else {"error": "no sign-in is running"}


def cancel():
    with _lock:
        f = _flow
    if f:
        f.cancel()
    return {"ok": True}


def state():
    with _lock:
        f = _flow
    return f.state() if f else {"running": False}
