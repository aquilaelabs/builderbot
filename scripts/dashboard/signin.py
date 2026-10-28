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
flow of its own with. So a sign-in is asked for on one node, from that
node's row, and signing out is asked of the same node: `claude auth logout`
there, as a job.
"""
import re
import sqlite3
import sys
import threading
import time

import agents

# The URL the flow prints, and the two things it says when it is over.
AUTH_URL = re.compile(r"https://(?:claude\.com|console\.anthropic\.com|"
                      r"platform\.claude\.com)/\S+")
PROMPT = "Paste code"

# Each coding agent's flow as its log reads (R95 step 3): the link it
# prints, the one-time code a device flow shows beside it (the person types
# it on the provider's page, and nothing comes back down), and the prompt a
# flow that wants a code pasted back waits at. Claude's asks for a code;
# Codex's device login (`codex login --device-auth`, 0.163.0) and Copilot's
# (`copilot login --device-code`, 1.0.102) show one.
FLOWS = {
    "claude": {"url": AUTH_URL, "code": None, "prompt": PROMPT},
    # The link ends at a space or at the color code Codex prints around it
    # (\x1b[...m): taken with \S+ the reset came along, the link opened a
    # page that said the session had ended.
    "codex": {"url": re.compile(r"https://auth\.openai\.com/[^\s\x1b]+"),
              "code": re.compile(r"one-time code[^\n]*\n\s*(?:\x1b\[[0-9;]*m)*([A-Z0-9]{4,}(?:-[A-Z0-9]{4,})+)"),
              "prompt": None},
    "copilot": {"url": re.compile(r"https://github\.com/login/device[^\s\x1b]*"),
                "code": re.compile(r"enter code\s+([A-Z0-9]{4}-[A-Z0-9]{4})"),
                "prompt": None},
    # Grok Build's device code (`grok login --device-auth`): a link on an
    # x.ai host and a code beside it, matched broadly since its words are
    # documented as "a URL and a code" (25 Oct).
    "grok": {"url": re.compile(r"https://(?:[a-z0-9-]+\.)*(?:x\.ai|grok\.com)/[^\s\x1b]*"),
             "code": re.compile(r"(?<![A-Z0-9-])([A-Z0-9]{4,}-[A-Z0-9]{4,})(?![A-Z0-9-])"),
             "prompt": None},
}


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
# node registry a flow runs on, and a session token minted for the account
# the flow signs in.
nodes = None
mint = None

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

    def __init__(self, nodes, node_id, job_id, name="", uid="", agent="claude"):
        self._nodes, self.node, self.job = nodes, node_id, job_id
        self.node_name = name
        self.uid = str(uid or "")          # whose sign-in it is: theirs to type into
        self.agent = agent if agent in FLOWS else "claude"
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
        flow = FLOWS[self.agent]
        m = flow["url"].search(out)
        c = flow["code"].search(out) if flow["code"] else None
        prompt = flow["prompt"]
        why = ""
        if done and j.get("state") != "succeeded":
            for line in reversed(out.splitlines()):
                line = line.strip()
                if line and not line.startswith("http") and (not prompt or prompt not in line):
                    why = line[-300:]
                    break
            why = why or "the sign-in did not finish"
        return {"running": not done, "url": m.group(0) if m else "",
                # A device flow's code, shown for the person to type on the
                # provider's page; "" for a flow that wants one pasted back.
                "code": c.group(1) if c else "", "agent": self.agent,
                "waiting": bool(prompt and prompt in out) and not self.sent and not done,
                "sent": self.sent and not done,
                "done": done, "ok": j.get("state") == "succeeded",
                # Which node's row draws it: the flow is that machine's.
                "node": self.node,
                "on": self.node_name, "job": self.job, "error": why}


def start_on_node(nodes, node_id, uid, name="", token="", agent="claude"):
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
    a = agents.get(agent) or agents.get("claude")
    r = nodes.job_add("user:signin", {"node": node_id}, a.login_job,
                      {"uid": str(uid), "timeout": 900, "token": str(token or ""), "agent": a.id})
    if r.get("error"):
        return r
    f = NodeFlow(nodes, node_id, r["job"], name, uid=uid, agent=a.id)
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
    """Stop the running flow and forget it. Forgotten at once, not when the
    node reports the job stopped: a node that has gone quiet never does, and
    a flow nobody can finish must not hold the next sign-in back."""
    global _flow
    with _lock:
        f, _flow = _flow, None
    if f:
        f.cancel()
    return {"ok": True}


def state(uid=None):
    """The running flow as its row draws it. With `uid`, only that account's
    own: the link a flow prints signs somebody in, so it is shown to the
    person it was started for and nobody else."""
    with _lock:
        f = _flow
    if not f or (uid is not None and getattr(f, "uid", "") != str(uid or "")):
        return {"running": False}
    return f.state()


def owner():
    """The account the running flow was started for, or "" when none is."""
    with _lock:
        f = _flow
    return getattr(f, "uid", "") if f else ""


# ---- the row's verbs, one call each from the dashboard -------------------------

def cannot(n, agent="claude"):
    """Why a sign-in or a sign-out cannot run on this node now, or "". A
    node that runs SESSIONS, which is the same test session_target makes:
    the agent is installed for the session account and the login lands in
    a home a session reads, and a node with no session half has neither."""
    a = agents.get(agent) or agents.get("claude")
    if not n or n.get("kind") != "agent":
        return f"which node? A {a.name} sign-in is made on one node, from its row on the Installed page"
    if n.get("state") != "online":
        return f"{n['name']} is {n.get('state') or 'not online'} and takes no new work: sign in or out there when it is back online"
    if n.get("live") is False:
        return f"{n['name']} is not answering: sign in or out there when it is back"
    if not ((n.get("reported") or {}).get("session") or {}).get("up"):
        return f"{n['name']} runs no sessions, so there is nowhere for a {a.name} login to live there"
    return ""


def verb(action, node_id, uid, agent="claude"):
    """Start a sign-in for account `uid` to `agent` on the node named, or
    stop the one that is running, once server.py has said this person may
    and that the node is theirs to see. (payload, status)."""
    if action == "cancel":
        return cancel() | {"signin": state(uid)}, 200
    n = nodes.node(node_id) if nodes is not None and node_id else None
    why = cannot(n, agent)
    if why:
        return {"error": why}, 400
    tok = mint(f"node:{n['id']}", ttl=1800, uid=uid)
    return start_on_node(nodes, n["id"], uid, n["name"], token=tok, agent=agent) | {"signin": state(uid)}, 200


def sign_out(node_id, uid, agent="claude"):
    """Sign account `uid` out of a coding agent on one node: `claude auth
    logout` there for Claude, `codex logout` for Codex, in that account's
    home, as a job. The credential is that machine's, so that machine is the
    one that lets go of it, and a node that is not answering is asked when
    it is back. (payload, status)."""
    n = nodes.node(node_id) if nodes is not None and node_id else None
    why = cannot(n, agent)
    if why:
        return {"error": why}, 400
    a = agents.get(agent) or agents.get("claude")
    r = nodes.job_add("user:signin", {"node": n["id"]}, a.logout_job,
                      {"uid": str(uid), "timeout": 120, "agent": a.id})
    if r.get("error"):
        return r, 400
    return {"ok": True, "job": r["job"], "on": n["name"]}, 200


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
    r = r | {"signin": state(owner())}
    return r, (400 if r.get("error") else 200)
