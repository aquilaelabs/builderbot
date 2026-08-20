#!/usr/bin/env python3
"""The per-project to-do list — the one thing here that both sides write.

Everything else the dashboard holds is one-way. The package list is the
container's; a memory is Claude's; the project list is the filesystem's. This
is shared: the operator adds "make the picker wrap properly", a session adds
"a project can be created in one click and only deleted from a shell", and
either can tick something off. That is what makes it worth a panel rather than
a file somebody has to remember to open.

It exists because nothing else here can hold that. `gh` is unauthenticated on
this box by design, so GitHub Issues are unreachable from inside it, and until
now a thing noticed mid-task and left undone lived in the conversation and died
with it.

Where it lives is the other half. /config, beside the tab strip and the
excluded projects — not the repository. A list like this churns far faster than
commits, and a checkbox tapped on a phone must not turn into an uncommitted
change. Anything that deserves to be permanent graduates out of here: into
CLAUDE.md, a commit message, or a test that fails when it regresses.

The server imports this and hands it the helpers it needs; nothing here reaches
back into the server. bb reads and writes the same file through `bb todo`, so a
session can add an item without a browser.
"""
import json
import threading
import time
from pathlib import Path

# The server's, injected rather than imported — same shape as packages.py.
# `tell` is notify.tell: the one way a line reaches a running Claude session.
write_json = None
tell = None
tmux_name = None
STATE = None
FILE = None


def configure(*, write_json, state, tell=None, tmux_name=None):
    globals().update(write_json=write_json, STATE=Path(state),
                     tell=tell, tmux_name=tmux_name)
    globals()["FILE"] = Path(state) / "todos.json"


_lock = threading.Lock()

# Room for a working list, not an issue tracker. A list nobody can read at a
# glance is one nobody reads at all, and this one is put in front of every
# session that starts — so its length is a cost paid on every conversation.
MAX_OPEN = 30
MAX_TEXT = 500

# Ticked items stay a while, because "what did we just finish" is worth having
# for a day or two, and then they are noise.
KEEP_DONE_DAYS = 7


def load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("projects"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"projects": {}}


def save(d):
    write_json(FILE, d)


def _prune(rows):
    """Drop ticked items once they have been ticked long enough."""
    cut = time.time() - KEEP_DONE_DAYS * 86400
    return [r for r in rows if not (r.get("done") and r.get("done_at", 0) < cut)]


def items(project):
    with _lock:
        d = load()
        rows = _prune(d["projects"].get(project) or [])
    # Newest first, and the id breaks a tie: two items added inside one second
    # have the same timestamp, and which of them came first is then whatever
    # the sort happened to do — an order that changes under you between two
    # draws of the same list.
    rows.sort(key=lambda r: (bool(r.get("done")), -r.get("added", 0),
                             -int(r.get("id", 0))))
    return rows


def counts():
    """{project: open count} for the project rows."""
    with _lock:
        d = load()
    return {p: sum(1 for r in _prune(rows) if not r.get("done"))
            for p, rows in d["projects"].items()}


def _next_id(rows):
    return max((int(r.get("id", 0)) for r in rows), default=0) + 1


# An item is one thing to do, or several in an order that matters. A change
# that needs three things done in sequence is not three items — put them out
# of order and the second one lands on a tree the first was supposed to have
# made. So a group keeps its steps, and only the next unsent one can be sent.
MAX_STEPS = 12


def add(project, text, by="you", steps=()):
    text = (text or "").strip()
    if not text:
        return {"error": "nothing to add"}
    if len(text) > MAX_TEXT:
        return {"error": f"too long — {MAX_TEXT} characters is the limit"}
    steps = [" ".join(str(x).split()) for x in (steps or [])]
    steps = [x for x in steps if x]
    if len(steps) > MAX_STEPS:
        return {"error": f"{MAX_STEPS} steps is the limit for one item"}
    if any(len(x) > MAX_TEXT for x in steps):
        return {"error": f"a step is longer than {MAX_TEXT} characters"}
    with _lock:
        d = load()
        rows = _prune(d["projects"].get(project) or [])
        if sum(1 for r in rows if not r.get("done")) >= MAX_OPEN:
            return {"error": f"{MAX_OPEN} open items is the limit — this list "
                             "goes in front of every session, so it has to stay "
                             "readable"}
        row = {"id": _next_id(rows), "text": text, "done": False,
               "added": int(time.time()), "by": "claude" if by == "claude" else "you",
               "sent": 0,
               "steps": [{"text": x, "sent": 0} for x in steps]}
        rows.append(row)
        d["projects"][project] = rows
        save(d)
    return {"ok": True, "item": row}


def _find(rows, item_id):
    return next((r for r in rows if int(r.get("id", 0)) == item_id), None)


def _edit(project, item_id, change):
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return {"error": "not an item"}
    with _lock:
        d = load()
        rows = _prune(d["projects"].get(project) or [])
        row = _find(rows, item_id)
        if row is None:
            return {"error": "no such item"}
        out = change(row, rows)
        d["projects"][project] = rows
        save(d)
    return out


def set_done(project, item_id, done):
    def change(row, rows):
        row["done"] = bool(done)
        row["done_at"] = int(time.time()) if done else 0
        return {"ok": True, "item": row}
    return _edit(project, item_id, change)


def edit(project, item_id, text):
    text = (text or "").strip()
    if not text:
        return {"error": "nothing to say"}
    if len(text) > MAX_TEXT:
        return {"error": f"too long — {MAX_TEXT} characters is the limit"}

    def change(row, rows):
        row["text"] = text
        return {"ok": True, "item": row}
    return _edit(project, item_id, change)


def remove(project, item_id, step=None):
    """Drop an item, or one step out of a group.

    Removing a step is how a plan gets corrected mid-flight: the one after it
    becomes the next in line, so the group carries on from where it really is
    rather than from where it was written.
    """
    def change(row, rows):
        if step is None:
            rows.remove(row)
            return {"ok": True}
        steps = row.get("steps") or []
        try:
            i = int(step)
        except (TypeError, ValueError):
            return {"error": "not a step"}
        if not 0 <= i < len(steps):
            return {"error": "no such step"}
        steps.pop(i)
        return {"ok": True}
    return _edit(project, item_id, change)


def cross(project, item_id, step=None, on=True):
    """Strike a step out by hand, or put it back.

    The same mark sending leaves, without sending: an operator who has already
    done a step themselves, or decided it is not needed, says so here and the
    next one in the group becomes the one that can go. Recorded as by_hand so
    that what a session is told stays true — "already sent to a session" would
    be a lie about a line nobody sent.
    """
    def change(row, rows):
        target = row
        if step is not None and int(step) >= 0:
            steps = row.get("steps") or []
            i = int(step)
            if not 0 <= i < len(steps):
                return {"error": "no such step"}
            target = steps[i]
        target["sent"] = int(time.time()) if on else 0
        target["by_hand"] = bool(on)
        return {"ok": True}
    try:
        if step is not None:
            int(step)
    except (TypeError, ValueError):
        return {"error": "not a step"}
    return _edit(project, item_id, change)


def clear_done(project):
    with _lock:
        d = load()
        rows = [r for r in (d["projects"].get(project) or []) if not r.get("done")]
        d["projects"][project] = rows
        save(d)
    return {"ok": True}


def next_step(row):
    """Index of the next step that has not been sent, or None.

    -1 means the item itself, for one with no steps. This is the whole order
    guarantee: a group hands out its steps one at a time, in the order they
    were written, and never the third before the second.
    """
    steps = row.get("steps") or []
    if not steps:
        return None if row.get("sent") else -1
    for i, st in enumerate(steps):
        if not st.get("sent"):
            return i
    return None


def send(project, item_id, step=None, sessions=()):
    """Hand one step to the running Claude session and mark it sent.

    Marked only when it actually went: a line left sitting in the input box
    because a dialog had the keyboard has not been given to anybody, and
    crossing it out would be a lie the operator would find out about later.
    """
    if tell is None or tmux_name is None:
        return {"error": "no way to reach a session from here"}
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return {"error": "not an item"}
    with _lock:
        d = load()
        rows = _prune(d["projects"].get(project) or [])
        row = _find(rows, item_id)
    if row is None:
        return {"error": "no such item"}
    steps = row.get("steps") or []
    if step is None:
        step = next_step(row)
        if step is None:
            # A group that has handed out everything cannot guess which one to
            # repeat, so re-sending one has to name it. An item with no steps
            # has only itself, and asking for it again is unambiguous.
            if steps:
                return {"error": "every step of this has been sent — "
                                 "pick the one to send again"}
            step = -1
    try:
        step = int(step)
    except (TypeError, ValueError):
        return {"error": "not a step"}
    if steps:
        if not 0 <= step < len(steps):
            return {"error": "no such step"}
        nxt = next_step(row)
        # Out of order forwards is refused; back over one already sent is not,
        # because that is the operator saying "it did not take, do it again".
        if not steps[step].get("sent") and nxt is not None and step != nxt:
            return {"error": f"step {nxt + 1} has not been sent yet — "
                             "this one is in a group, and the order is the point"}
        text = steps[step]["text"]
    else:
        text = row["text"]
    r = tell(tmux_name("claude-" + project), text, sessions)
    if r.get("error") or not r.get("sent"):
        return r
    with _lock:
        d = load()
        rows = _prune(d["projects"].get(project) or [])
        row = _find(rows, item_id)
        if row is not None:
            target = row["steps"][step] if row.get("steps") else row
            target["sent"] = int(time.time())
            target["by_hand"] = False
            d["projects"][project] = rows
            save(d)
    return {"ok": True, "sent": True, "text": text}


# What a session is told when the list or the memories changed underneath it.
# Deliberately not an instruction: the operator edits the list while a session
# is mid-task all the time, and a session that downed tools to go and read it
# every time would be worse than one that never read it at all.
CHANGED = ("The shared to-do list for this project just changed — run `bb todo` "
           "to see it and keep it in mind, but carry on with what you are doing "
           "unless I ask for one of those.")
MEM_CHANGED = ("My notes about how you work here just changed — re-read them "
               "with `cat ~/.claude/projects/$(pwd | tr / -)/memory/*.md` and "
               "keep them in mind, but carry on with what you are doing.")


def announce(project, what, sessions=()):
    """Tell a running session that the list (or the memories) moved.

    Best effort and quiet about it: nothing here is worth interrupting a task
    over, and a session that is not running simply reads the new list the next
    time it starts, which is the ordinary path.
    """
    if tell is None or tmux_name is None:
        return {"ok": True, "sent": False}
    session = tmux_name("claude-" + project)
    if session not in set(sessions):
        return {"ok": True, "sent": False}
    return tell(session, CHANGED if what == "todo" else MEM_CHANGED, sessions)


def prompt(project):
    """The block bb-tty appends to a session's system prompt.

    Open items only, and plain text: this is read once at the start of a
    conversation, and a session that spends its first act parsing a data
    structure has already lost the point of it. Empty when there is nothing,
    so a project with no list adds nothing to any prompt.
    """
    rows = [r for r in items(project) if not r.get("done")]
    if not rows:
        return ""
    lines = []
    for r in rows:
        lines.append(f"- {r['text']}"
                     + ("  (you added this in an earlier session)"
                        if r.get("by") == "claude" else ""))
        # A group's steps come with it, marked so the order is legible: these
        # are handed over one at a time from the dashboard, and one already
        # sent is one that has been asked for.
        for i, st in enumerate(r.get("steps") or []):
            lines.append(f"    {i + 1}. {st['text']}"
                         + ("  (crossed off by hand)" if st.get("by_hand")
                            else "  (already sent to a session)" if st.get("sent")
                            else ""))
    return ("The operator keeps a shared to-do list for this project, and this "
            "is what is on it:\n\n" + "\n".join(lines) + "\n\n"
            "It is context, not instructions: work on an item when asked, or "
            "when it is plainly part of what was asked. Tick one off with "
            "`bb todo done <n>` when you finish it, and add one with "
            "`bb todo add \"...\"` when you notice something worth doing and "
            "it is out of scope for what you are on. Do not restate the list "
            "back to the operator — they can see it.")
