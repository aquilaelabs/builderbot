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

# What verb() and take_code() need from the server, set by server.py: the
# node registry a flow runs on, a session token minted for the account the
# flow signs in, and the cached answer to who each home is signed in as,
# cleared whenever a flow may have changed it.
nodes = None
mint = None
forget_auth = None

# What gets removed from a pasted code before it is handed to the flow:
# whitespace of every kind (a wrapped copy brings line breaks, a phone
# keyboard adds a trailing space), control characters, and the zero-width
# marks HTML copy buttons smuggle along. Everything printable stays. This is
# deliberately a strip-list and not an allow-list: two rounds of guessing the
# code's alphabet each refused a real code with advice to copy it again, to an
# operator who had copied it. The code is somebody else's credential format;
# judging it is the flow's job, and the flow says why in its own words.
CODE_JUNK = re.compile(r"[^!-~]+")


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


# ---- the card's verbs, one call each from the dashboard ------------------------

def verb(action, want, uid):
    """Start a sign-in for account `uid`, on the node named or the one node
    there is, or stop the one that is running, once server.py has said this
    person may. (payload, status)."""
    forget_auth()               # every home: the flow may have changed any
    if action == "cancel":
        return cancel() | {"signin": state()}, 200
    # WHERE it runs. Claude Code is installed where sessions are, which
    # is a node, so the flow goes there, on the node the operator picked
    # or the one node there is. There is no other answer: this container
    # carries no Claude Code, so with no node the refusal below is it.
    # A node that runs SESSIONS, which is the same test session_target
    # makes: Claude Code is installed for the session account, the
    # credential lands in that account's home, and a node with no session
    # half has neither. Not merely "online": a build node that runs no
    # sessions has nowhere for a login to live.
    live = [] if nodes is None else [
        n for n in nodes.node_list()
        if n["kind"] == "agent" and n["state"] == "online"
        and n.get("live") is not False
        and ((n.get("reported") or {}).get("session") or {}).get("up")]
    pick = next((n for n in live if want in (n["id"], n["name"])), None) \
        if want else (live[0] if len(live) == 1 else None)
    if pick:
        tok = mint(f"node:{pick['id']}", ttl=1800, uid=uid)
        return start_on_node(nodes, pick["id"], uid, pick["name"], token=tok) | {"signin": state()}, 200
    if live:
        return {"error": "which node should the sign-in run on? "
                         + ", ".join(n["name"] for n in live),
                "nodes": [n["name"] for n in live]}, 400
    # And nowhere else. Claude Code is installed for the account that runs
    # sessions, which is a node's; this container carries none, so there
    # is no flow here to fall back to and saying so is the whole answer.
    return {"error": "no node is running sessions, and a Claude "
                     "sign-in runs on the machine Claude is "
                     "installed on. Enroll one on the Nodes tab, or "
                     "wait for one to come back"}, 400


def take_code(code):
    """Hand the code from the browser to the sign-in flow.

    Transport, not judgment. The only property this end owes the pty is
    that a paste is one line of printable text, so the junk a copy brings
    along is stripped rather than refused, and whether what remains is a
    valid code is decided by the flow, whose refusal the card repeats in
    the flow's own words. Two shape checks in a row each turned out to
    refuse a real code (an allow-listed alphabet without base64's `+/=`,
    then the page's own authorize URL glued to the code by its Copy
    button); the only refusals left are the ones that cannot be wrong:
    nothing left to send, or far too much to be a code. (payload,
    status)."""
    # Anything from a URL onward was never part of the code. The page that
    # hands it out sets the authorize URL flush against it, so Copy takes
    # both. A code is base64url and a `#`, with no colon and no slash, so the
    # cut cannot land inside a real one.
    code = re.split(r"https?://", code, maxsplit=1)[0]
    code = CODE_JUNK.sub("", code)
    if not code:
        return {"error": "no code in that paste: copy the "
                         "code itself, not the page's link"}, 400
    if len(code) > 2048:
        return {"error": "that is far too long to be a code; "
                         "copy just the code"}, 400
    r = submit(code)
    # Whatever the cache is holding is about to be wrong either way.
    forget_auth()
    r = r | {"signin": state()}
    return r, (400 if r.get("error") else 200)
