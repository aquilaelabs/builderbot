#!/usr/bin/env python3
"""Delivering a line to a running Claude session, and knowing whether it landed.

There is no IPC into a Claude session. `--remote-control` is for claude.ai, not
for anything on this box, and no subcommand posts a message to a local one — so
the only door is the terminal it is sitting in, through tmux send-keys.

Which makes pressing Enter the whole problem. A session that is "waiting for
input" is either sitting at its prompt, where Enter is exactly right, or
holding a permission dialog, where Enter answers it — and answering a
permission dialog on the operator's behalf, blind, is the worst thing anything
in this dashboard could do. The pane title cannot tell those apart: both are
waiting.

So this does not try to recognise a dialog, which would mean pattern-matching a
TUI that changes with every release. It uses the one property every text input
has and no dialog does: **it echoes what you type**. Type the line, look at the
pane, and press Enter only if the line is now on the screen. A dialog swallows
stray characters, so nothing appears, so nothing is sent — and the line is
left where the operator can see it and deal with it themselves.

The server imports this and hands it `run`; memory.py and todo.py are handed
this module's `tell`.
"""
import time

run = None


def configure(*, run):
    globals().update(run=run)


# Long enough for the TUI to repaint after send-keys, short enough that the
# request it happens inside does not feel stuck. Two looks, because a first
# frame can land mid-redraw.
SETTLE = 0.25
LOOKS = 2

# How much of the line to look for. A pane is narrow and the text wraps; -J
# rejoins it, but a long line can still be truncated by a narrow terminal at
# the far right, so only the head is used as the fingerprint.
FINGERPRINT = 40


def _capture(session):
    r = run(["tmux", "capture-pane", "-p", "-J", "-t", session], timeout=10)
    return r["out"] if r["code"] == 0 else ""


def live(session, sessions):
    return session in set(sessions)


def send_line(session, text, sessions=()):
    """Type a line into a session we started ourselves, and submit it.

    No echo check, unlike tell(). That check exists because a Claude session
    "waiting for input" might be holding a permission dialog, and Enter would
    answer it. This is for the sign-in session: a terminal this dashboard
    opened, running one command whose only input is a code, with no dialog in
    it to answer. Knowing what is on the other end is the whole difference.
    """
    text = " ".join((text or "").split())
    if not text:
        return {"error": "nothing to send"}
    if session not in set(sessions):
        return {"error": "that terminal is not running"}
    r = run(["tmux", "send-keys", "-t", session, "-l", "--", text], timeout=10)
    if r["code"] != 0:
        return r
    e = run(["tmux", "send-keys", "-t", session, "Enter"], timeout=10)
    if e["code"] != 0:
        return e
    return {"ok": True, "sent": True}


def tell(session, text, sessions=()):
    """Type one line into a session and submit it if it visibly arrived.

    Returns {"sent": True} when the line went in and Enter followed,
    {"typed": True} when it was left in the input box unsent, or an error.
    """
    text = " ".join((text or "").split())
    if not text:
        return {"error": "nothing to say"}
    if session not in set(sessions):
        return {"error": "no session is running here"}
    # Counted before, not merely looked for after. The same line may already be
    # on the screen — it is the second send of a step that did not take, and
    # the first one's echo is still scrolled up there — and "is it visible?"
    # says yes to that. What means the input box took it is that there is now
    # one *more* of it than there was.
    mark = text[:FINGERPRINT]
    was = _capture(session).count(mark)
    r = run(["tmux", "send-keys", "-t", session, "-l", "--", text], timeout=10)
    if r["code"] != 0:
        return r
    for _ in range(LOOKS):
        time.sleep(SETTLE)
        if _capture(session).count(mark) > was:
            e = run(["tmux", "send-keys", "-t", session, "Enter"], timeout=10)
            if e["code"] != 0:
                return e
            return {"ok": True, "sent": True, "text": text}
    # It did not echo, so whatever has the keyboard is not a text box. Leave
    # the line be: on the screen, unsent, for a person to look at.
    return {"ok": True, "sent": False, "typed": True, "text": text}
