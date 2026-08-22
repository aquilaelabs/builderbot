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
            d.setdefault("unsaved", {})
            return _migrate(d)
    except (OSError, ValueError):
        pass
    return {"projects": {}, "unsaved": {}, "ordered": True}


def _migrate(d):
    """Two one-shot reorderings, each with its own flag so neither runs twice.

    `ordered`: stored order became display order; it used to be newest-last
    and sorted on the way out.

    `oldest_first`: items used to be added at the top, so the number a session
    quotes — the id, which is what `bb todo done` takes — counted *up* the
    screen and #1 sat at the bottom. Adding at the end instead makes the
    numbers run down the page, which is the only arrangement where "#3" can be
    found by looking. Lists built by the old prepend are turned round once;
    a list that is not in strict id-descending order was arranged by hand and
    is left exactly as its operator left it.
    """
    dirty = False
    if not d.get("ordered"):
        for name, rows in d["projects"].items():
            d["projects"][name] = list(reversed(rows))
        d["ordered"] = dirty = True
    if not d.get("oldest_first"):
        for name, rows in d["projects"].items():
            ids = [int(r.get("id", 0)) for r in rows]
            if ids == sorted(ids, reverse=True):
                d["projects"][name] = list(reversed(rows))
        d["oldest_first"] = dirty = True
    if dirty:
        try:
            save(d)
        except Exception:  # noqa: BLE001 - a read must not fail on a failed write
            pass
    return d


def save(d):
    write_json(FILE, d)


# The two things in the panel that can move. Tracked apart so that the line
# spent telling a session can say which of them did — "something changed" is a
# sentence that makes somebody go and look at both.
KINDS = ("todo", "memory")


def unsaved(project):
    """What has moved here since a session was last told, by kind.

    Edits are written the moment they are made — a phone that dies half way
    through tidying a list must not lose it — but telling the session is a
    separate act, because every telling costs a line in a conversation. So the
    two are tracked apart: the file is always current, and this says whether
    anybody has been told, and about what.
    """
    with _lock:
        got = load().get("unsaved", {}).get(project)
    return _kinds(got)


def _kinds(got):
    """Normalize a stored flag. It used to be one boolean for the whole
    project, from before the message said which half had moved."""
    if isinstance(got, dict):
        return {k: bool(got.get(k)) for k in KINDS}
    return {"todo": bool(got), "memory": False}


def _touch(d, project, kind="todo", on=True):
    cur = _kinds(d.setdefault("unsaved", {}).get(project))
    if kind is None:
        cur = dict.fromkeys(KINDS, bool(on))
    else:
        cur[kind] = bool(on)
    d["unsaved"][project] = cur


def _prune(rows):
    """Drop ticked items once they have been ticked long enough."""
    cut = time.time() - KEEP_DONE_DAYS * 86400
    return [r for r in rows if not (r.get("done") and r.get("done_at", 0) < cut)]


def items(project):
    """The list, in the order it is stored — which is the order it is shown.

    Nothing is sorted here any more. A list that reshuffles itself is one you
    cannot keep a plan in: an item ticked off would jump to the bottom, taking
    its steps with it, and the order the operator arranged would be a
    suggestion the list overruled. Done items fade where they are, the same
    way sent steps stay struck through where they are.
    """
    with _lock:
        return _prune(load()["projects"].get(project) or [])


def counts():
    """{project: how much is still to do} for the project rows.

    The same number the panel shows, which is what makes the badge worth
    glancing at: an item with nothing left to hand over does not count, and
    neither does one a session marked finished. Counting "not done" instead
    meant crossing a whole list off changed nothing on the row — because
    nothing in the panel sets done; it sets sent.
    """
    with _lock:
        d = load()
    return {p: sum(1 for r in _prune(rows)
                   if not r.get("done") and next_step(r) is not None)
            for p, rows in d["projects"].items()}


def _int(v):
    """A whole number out of whatever JSON carried, or None.

    Everything that names an item or a step arrives from a request body, so
    `int(v)` is a crash waiting for a field that is a list, a dict, or the
    word "x". One reader, and every caller answers "not an item" instead of
    dying.
    """
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


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
        # The end, so the ids run down the page. The alternative is a list
        # where every addition renumbers what a session was looking at, and
        # the number is the whole way to say which item is meant.
        rows.append(row)
        d["projects"][project] = rows
        _touch(d, project)
        save(d)
    return {"ok": True, "item": row}


def _find(rows, item_id):
    return next((r for r in rows if _int(r.get("id")) == item_id), None)


def _edit(project, item_id, change):
    item_id = _int(item_id)
    if item_id is None:
        return {"error": "not an item"}
    with _lock:
        d = load()
        rows = _prune(d["projects"].get(project) or [])
        row = _find(rows, item_id)
        if row is None:
            return {"error": "no such item"}
        out = change(row, rows)
        d["projects"][project] = rows
        _touch(d, project)
        save(d)
    return out


def set_done(project, item_id, done):
    def change(row, rows):
        row["done"] = bool(done)
        row["done_at"] = int(time.time()) if done else 0
        return {"ok": True, "item": row}
    return _edit(project, item_id, change)


def edit(project, item_id, text, step=None):
    """Reword an item, or one step of it."""
    text = " ".join((text or "").split())
    if not text:
        return {"error": "nothing to say"}
    if len(text) > MAX_TEXT:
        return {"error": f"too long — {MAX_TEXT} characters is the limit"}
    if step is not None and _int(step) is None:
        return {"error": "not a step"}

    def change(row, rows):
        i = _int(step)
        if i is None or i < 0:
            row["text"] = text
            return {"ok": True, "item": row}
        steps = row.get("steps") or []
        if not 0 <= i < len(steps):
            return {"error": "no such step"}
        steps[i]["text"] = text
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
        i = _int(step)
        if i is None:
            return {"error": "not a step"}
        if not 0 <= i < len(steps):
            return {"error": "no such step"}
        steps.pop(i)
        return {"ok": True}
    return _edit(project, item_id, change)


def move(project, item_id, step=None, dir=0):
    """Shuffle an item among the items, or a step within its group.

    Steps that have gone do not move, and nothing moves above them: crossed
    steps are a prefix, and every rule about what can be sent reads them that
    way. So the past of a plan is fixed and its future can be rearranged,
    which is the half anyone actually wants to change.
    """
    dir = _int(dir)
    if dir not in (-1, 1):
        return {"error": "not a direction"}
    item_id = _int(item_id)
    if item_id is None:
        return {"error": "not an item"}

    def swap(seq, i):
        j = i + dir
        if not 0 <= j < len(seq):
            return {"error": "it is already at the end"}
        seq[i], seq[j] = seq[j], seq[i]
        return {"ok": True}

    if step is None:
        with _lock:
            d = load()
            rows = _prune(d["projects"].get(project) or [])
            i = next((n for n, r in enumerate(rows)
                      if _int(r.get("id")) == item_id), None)
            if i is None:
                return {"error": "no such item"}
            out = swap(rows, i)
            if out.get("ok"):
                d["projects"][project] = rows
                _touch(d, project)
                save(d)
        return out

    def change(row, rows):
        steps = row.get("steps") or []
        i = _int(step)
        if i is None:
            return {"error": "not a step"}
        if not 0 <= i < len(steps):
            return {"error": "no such step"}
        first = sum(1 for st in steps if st.get("sent"))
        if i < first or i + dir < first:
            return {"error": "a step that has gone stays where it is"}
        return swap(steps, i)
    return _edit(project, item_id, change)


def add_step(project, item_id, text):
    """Give an item a step — which is how a plain one becomes a plan."""
    text = " ".join((text or "").split())
    if not text:
        return {"error": "nothing to add"}
    if len(text) > MAX_TEXT:
        return {"error": f"too long — {MAX_TEXT} characters is the limit"}

    def change(row, rows):
        steps = row.setdefault("steps", [])
        if len(steps) >= MAX_STEPS:
            return {"error": f"{MAX_STEPS} steps is the limit for one item"}
        steps.append({"text": text, "sent": 0})
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
    if step is not None and _int(step) is None:
        return {"error": "not a step"}

    def change(row, rows):
        target = row
        i = _int(step)
        if i is not None and i >= 0:
            steps = row.get("steps") or []
            if not 0 <= i < len(steps):
                return {"error": "no such step"}
            target = steps[i]
        target["sent"] = int(time.time()) if on else 0
        target["by_hand"] = bool(on)
        return {"ok": True}
    return _edit(project, item_id, change)


def clear_done(project):
    with _lock:
        d = load()
        rows = [r for r in (d["projects"].get(project) or []) if not r.get("done")]
        d["projects"][project] = rows
        _touch(d, project)
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


def send(project, item_id, step=None, sessions=(), also_told=False):
    """Hand one step to the running Claude session and mark it sent.

    Marked only when it actually went: a line left sitting in the input box
    because a dialog had the keyboard has not been given to anybody, and
    crossing it out would be a lie the operator would find out about later.
    """
    if tell is None or tmux_name is None:
        return {"error": "no way to reach a session from here"}
    item_id = _int(item_id)
    if item_id is None:
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
    step = _int(step)
    if step is None:
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
        # A step arrives on its own otherwise, and "then re-measure it" means
        # nothing without the plan it belongs to. So the line carries all
        # three: that it is one step of several, what the whole thing is for,
        # and which step this is.
        text = (f"This is step {step + 1} of {len(steps)} in a plan. "
                f"The plan: {row['text']}. "
                f"Step {step + 1}: {steps[step]['text']}")
    else:
        text = row["text"]
    # One message, not two. Saving the list and sending a step both want to
    # say something, and two lines racing into the same input box is how the
    # second one ends up appended to the first. So the note rides along.
    extra = changed_line(also_told) if isinstance(also_told, dict) else ""
    line = text + (f"  (Also: {extra[0].lower()}{extra[1:]})" if extra else "")
    r = tell(tmux_name("claude-" + project), line, sessions)
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


# What a session is told when something underneath it moved, and which half.
# Naming the half is the point: "something changed" sends somebody to look at
# both, and one of the two is a directory of files.
#
# Deliberately not an instruction either way. The operator edits these while a
# session is mid-task all the time, and a session that downed tools to go and
# read them every time would be worse than one that never read them at all.
LOOK = {
    "todo": "the shared to-do list for this project (`bb todo`)",
    "memory": ("my notes about how you work here "
               "(`cat ~/.claude/projects/$(pwd | tr / -)/memory/*.md`)"),
}


def changed_line(kinds):
    """One sentence naming what moved, or empty when nothing did.

    Built rather than picked from three: the verb belongs once at the end, and
    "X changed and Y changed" is what a template that cannot count reads like.
    """
    which = [k for k in KINDS if kinds.get(k)]
    if not which:
        return ""
    if len(which) == 1:
        subject = LOOK[which[0]][0].upper() + LOOK[which[0]][1:]
        them = "it"
    else:
        subject = "Both " + " and ".join(LOOK[k] for k in which)
        them = "them"
    return (f"{subject} just changed — keep {them} in mind, but carry on with "
            "what you are doing unless I ask for one of those.")


def mark_unsaved(project, kind="todo"):
    """Something in the panel moved. The Save buttons cover all of it, and the
    kind is what lets the message name which half."""
    with _lock:
        d = load()
        _touch(d, project, kind, True)
        save(d)
    return {"ok": True}


def mark_told(project):
    with _lock:
        d = load()
        _touch(d, project, None, False)
        save(d)
    return {"ok": True}


def announce(project, kinds, sessions=()):
    """Tell a running session what moved underneath it.

    Best effort and quiet about it: a session that is not running simply reads
    the new list the next time it starts, which is the ordinary path.
    """
    line = changed_line(kinds if isinstance(kinds, dict) else {kinds: True})
    if not line or tell is None or tmux_name is None:
        return {"ok": True, "sent": False}
    session = tmux_name("claude-" + project)
    if session not in set(sessions):
        return {"ok": True, "sent": False}
    return tell(session, line, sessions)


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
        # Numbered, because a session that wants to talk about one of these
        # has to be able to name it — and the name has to be the one the
        # operator sees on the row and the one `bb todo done` takes.
        lines.append(f"- #{r['id']}  {r['text']}"
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
            "when it is plainly part of what was asked. The number is the "
            "item's own and does not change — it is what the operator sees on "
            "the row, so refer to one as #4 rather than by counting down the "
            "list. Tick one off with "
            "`bb todo done <n>` when you finish it, and add one with "
            "`bb todo add \"...\"` when you notice something worth doing and "
            "it is out of scope for what you are on. Do not restate the list "
            "back to the operator — they can see it.")
