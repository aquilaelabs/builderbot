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
    def start(self):
        master, slave = pty.openpty()
        # A pty, not a pipe: the flow writes its prompt without a newline and
        # a pipe would have it sitting in a buffer nobody ever sees.
        self._proc = subprocess.Popen(
            ["claude", "auth", "login"], stdin=slave, stdout=slave,
            stderr=slave, start_new_session=True, close_fds=True)
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


def start():
    """Begin a flow, replacing any that is there. Pressing Sign in is the one
    thing that means start over, so it always does.

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
    f.start()
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
