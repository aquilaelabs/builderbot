#!/usr/bin/env python3
"""Signing in to Claude, without a terminal in it.

`claude auth login` is interactive: it prints a URL and waits for the code the
browser gives back. That made it look like a job for a terminal, so it got
one: a tmux session behind ttyd behind a tab. Every part of that turned out
to be a place for it to go wrong. ttyd reconnects a dropped socket, so closing
the flow started another; a phone cannot select a wrapped URL out of a canvas,
and a paste into one silently does not arrive, so the code reaching the prompt
empty read as a rejected code; and the tab itself zooms and reflows under a
thumb while you are trying to work in it.

None of that was the sign-in. The sign-in is two lines of text going in
opposite directions, and a program that wants a terminal only wants a pty.

So the pty is held where Claude IS, which is a node: the flow runs there as a
`claude-login` job, its output comes back as that job's log, and the code goes
down on the reply to a log post, the channel `cancel` has always used. What
the operator sees is a link and a text field, which is what a phone is good
at, and it is the same card whichever machine is answering.

The grant the flow makes stays on that machine. Nothing is copied anywhere
(claudegrant.py says why), and this container carries no Claude Code to run a
flow of its own with.
"""
import re
import sqlite3
import sys
import threading
import time

# The URL the flow prints, and the two things it says when it is over.
AUTH_URL = re.compile(r"https://(?:claude\.com|console\.anthropic\.com|"
                      r"platform\.claude\.com)/\S+")
PROMPT = "Paste code"


# How long start_on_node() waits for the URL before answering. The flow takes
# about a second to print it once the node picks the job up, and a button that
# returns before then leaves the card saying "starting the sign-in…" until the
# next poll, which is how a link that is ready in a second took fifteen to
# appear. Longer than the local flow's six, because a job has to be handed out
# by the long-poll first.
URL_WAIT = 10

_lock = threading.Lock()
_flow = None


class NodeFlow:
    """The same flow, run on a NODE (roadmap R47).

    Claude Code is installed where sessions run, and after R47 this container
    carries none, so the flow has to happen over there. It is a job of its
    own on the node, under a pty, as that machine's session account; what it
    prints comes back as the job's log and the code goes down on the reply to
    a log post, the channel `cancel` has always used.

    The same three questions the local Flow answers (what is the URL, is it
    asking, did it work) read off the job's log and state instead of a pty
    this process holds. Everything above this line is what the page sees, so
    the card does not know or care which of the two it is talking to.
    """

    def __init__(self, nodes, node_id, job_id, name="", uid=""):
        self._nodes, self.node, self.job = nodes, node_id, job_id
        self.node_name = name
        self.uid = str(uid or "")          # whose sign-in it is: theirs to type into
        self.sent = False

    def _log(self):
        j = self._nodes.job(self.job) or {}
        return j, (j.get("log") or "")

    def submit(self, code):
        j, _ = self._log()
        if not j or j.get("state") in ("succeeded", "failed", "canceled"):
            return {"error": "that sign-in is over; start another"}
        r = self._nodes.job_input(self.job, code)
        if r.get("error"):
            return r
        self.sent = True
        return {"ok": True}

    def cancel(self):
        try:
            self._nodes.job_cancel("user:signin", self.job)
        except sqlite3.Error as e:
            print(f"dashboard: signin: cancel of {self.job} not recorded: {e}",
                  file=sys.stderr, flush=True)
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


def start_on_node(nodes, node_id, uid, name="", token=""):
    """Begin a flow on a node. Same contract as start(): it replaces whatever
    was running and waits a moment for the URL, so the button that is already
    waiting gets the link in its own answer."""
    global _flow
    with _lock:
        old = _flow
    if old:
        old.cancel()
    # The token is what lets the flow REPORT what it signed in as: minted
    # for the account and scoped to this node, it is the credential
    # bb login --flow speaks to the controller with. Without one the flow
    # ended and nobody was told, and the next check signed the node out
    # again as stale (16 Sep).
    r = nodes.job_add("user:signin", {"node": node_id}, "claude-login",
                      {"uid": str(uid), "timeout": 900, "token": str(token or "")})
    if r.get("error"):
        return r
    f = NodeFlow(nodes, node_id, r["job"], name, uid=uid)
    with _lock:
        _flow = f
    t0 = time.time()
    while time.time() - t0 < URL_WAIT and not f.state()["url"] \
            and f.state()["running"]:
        time.sleep(0.1)
    return {"ok": True, "job": r["job"], "on": name}




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


def owner():
    """The account the running flow was started for, or "" when none is."""
    with _lock:
        f = _flow
    return getattr(f, "uid", "") if f else ""
