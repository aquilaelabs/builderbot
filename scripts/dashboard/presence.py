"""Who else has this project's notebook open, right now.

Roadmap #26's second half. The first half made a collision safe: a write over
somebody else's words is refused, both versions are shown, and one of two
buttons decides it. This is the half that stops most of them happening at
all: the panel says who else is in here before the typing starts, rather
than after it.

The question is the one overlap.py already answers for source files ("who
else has this open"), and the answer wants the same shape. It does not want
the same storage: overlap's notes are a record of what a session did, which
outlives the session and is worth keeping. This is a claim about right now,
and a claim about right now that survived a restart would be a claim about
somebody who is not there, the exact wrong answer for the only question it
is asked. So it lives in memory and nowhere else. A restart drops every
browser's poll anyway, and every one of them says so again within a poll.

A seat is (project, account, client): the client is one browser tab, minted
per page load, which is what lets "your other window" be told from "you".
"""
import threading
import time

# Three polls. The panel heartbeats on its fifteen-second status poll, so one
# missed request must not make somebody vanish and come back: a line that
# flickers is worse than no line, because it reads as two people arriving.
TTL = 50

# A ceiling on what one process will hold. This is a dict of live browser
# tabs, so it is small by construction; the cap is here because it is fed by
# a request body and anything fed by a request body wants one.
MAX = 500

_lock = threading.Lock()
_seats = {}                  # (project, uid, client) -> {"where", "at"}


def mark(project, uid, client, where=""):
    """Record that this browser tab is in this project's notebook.

    Returns the OTHERS (everyone else still in it) because the panel asks
    this question by answering it, and a second round trip to read back what
    it just wrote would be a request for nothing.
    """
    if not project or not uid or not client:
        return []
    now = int(time.time())
    with _lock:
        _prune(now)
        if len(_seats) < MAX or (project, uid, client) in _seats:
            _seats[(project, uid, client)] = {"where": str(where)[:32], "at": now}
        return [{"uid": u, "client": c, **v}
                for (p, u, c), v in _seats.items()
                if p == project and c != client]


def here(project):
    """Everyone in this project's notebook, without marking anybody."""
    with _lock:
        _prune(int(time.time()))
        return [{"uid": u, "client": c, **v}
                for (p, u, c), v in _seats.items() if p == project]


def gone(project, uid, client):
    """A tab that has closed the notebook, or the page. Not required (a seat
    times out on its own), but a line saying somebody is here when they have
    just left is the one this can cheaply avoid."""
    with _lock:
        _seats.pop((project, uid, client), None)


def _prune(now):
    for k in [k for k, v in _seats.items() if now - v["at"] > TTL]:
        del _seats[k]
