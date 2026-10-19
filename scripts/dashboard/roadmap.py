#!/usr/bin/env python3
"""The per-project roadmap: the one thing here that both sides write.

Named roadmap.py because that is what the list was called when it was written,
and the file is served from an absolute path by the running image; the
command, the tab and the words everywhere else are "roadmap".

Everything else the dashboard holds is one-way. The toolchain list is the
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
locked projects, not the repository. A list like this churns far faster than
commits, and a checkbox tapped on a phone must not turn into an uncommitted
change. Anything that deserves to be permanent graduates out of here: into
CLAUDE.md, a commit message, or a test that fails when it regresses.

The server imports this and hands it the helpers it needs; nothing here reaches
back into the server. bb reads and writes the same file through `bb roadmap`, so a
session can add an item without a browser.
"""
import os as _os
import sys as _sys
# Beside this file, whichever way it was loaded: bb's own Python loads the
# modules by path, where a plain sibling import finds nothing.
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from names import claude_session   # noqa: E402
import copy
import json
import os
import sys

# `bb` execs this module by path (spec_from_file_location), so its directory
# is not on sys.path the way it is when the dashboard imports it normally, and
# a plain `import statefile` would work in one caller and not the other. Doing
# it through sys.path rather than a second by-path load keeps it ONE module
# object per process, which matters: the in-process half of the lock is a
# dict in there, and two copies of it would not see each other's.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import statefile  # noqa: E402
import ids  # noqa: E402
from fields import field, field_list  # noqa: E402
import pending  # noqa: E402
import re
import time
from pathlib import Path

# The server's, injected rather than imported: the same shape as toolchains.py.
# `tell` is notify.tell: the one way a line reaches a running Claude session.
write_json = None
actor = None
tell = None
# Injected beside tell, from the same module. Optional: the CLI configures
# this without one, and a switch there simply does not wait.
settle = None
tmux_name = None
STATE = None
FILE = None


def configure(*, write_json, state, tell=None, tmux_name=None, settle=None,
              actor=None):
    globals().update(write_json=write_json, STATE=Path(state),
                     tell=tell, tmux_name=tmux_name, settle=settle,
                     # Which PERSON is writing, asked at the moment an event
                     # is logged: "you" says a person rather than a session,
                     # and with two people on a project that is not enough to
                     # answer "who dropped the third one?".
                     actor=actor)
    globals()["FILE"] = Path(state) / "roadmap.json"
    # The approval queue (roadmap #27): the gate in add() reads it, and the
    # replay of an approved record comes back through `replay` below.
    pending.configure(write_json=write_json, state=state)
    pending.applier("roadmap", replay)


# What a held roadmap call replays as. Only what a session can ask for
# through bb is here: add, and the three follow-ups that ride behind a held
# add. Everything else on a held item is refused by bb with "still waiting".
_REPLAY = {"add": "add", "info": "set_info", "step-add": "add_step", "edit": "edit",
           # A session asking for an item back off the shelf (R78): held as a
           # request whatever the gate says, and a person's Approve replays it.
           "unshelve": "shelve"}


def replay(project, verb, args):
    fn = globals().get(_REPLAY.get(verb, ""))
    if fn is None:
        return {"error": f"not a roadmap change that can be replayed: {verb}"}
    return fn(project, by="claude", **args)


# Every read-modify-write below is already wrapped in `with _lock:`. What it
# was NOT is a lock: a threading.Lock guards the threads of one process, and
# the roadmap has two writers: the dashboard, and a `bb` invocation, which is a
# separate process. Both loaded, both mutated their own copy, both wrote, and
# the second landed on top of the first. Measured, four processes making forty
# changes each: 40 of 160 survived.
#
# statefile.locked takes flock on the file itself, so the other process waits
# instead of overwriting. Same sites, same shape. See statefile.py.
_lock = statefile.on(lambda: FILE)

# What is kept and what a session is sent are two things (the operator, 29
# Sep): the list keeps what there is to do, and a session's prompt carries
# a count of it (brief) with the items a prompt names (preamble.mentioned).
# The limit is on the open ones, and is what a list still is rather than
# what a prompt holds.
MAX_OPEN = 5000
# What a title is cut to.
MAX_TEXT = 4000

# A line may be several lines. A step is one thing to hand over, and one thing
# is often three sentences and a blank line, and collapsing that to a single
# paragraph made every plan read like a wall, which pushed sessions into
# splitting one step into three. Steps are the expensive unit here (each one is
# a message the operator sends by hand), so the cheap thing has to be able to
# hold the detail. Bounded so a paste cannot turn a list into a document.
MAX_LINES = 200


def _clean(text, multiline=True, max_lines=None):
    """Trim a line, or a small block of them.

    Trailing space goes, runs of blank lines collapse to one, and the whole
    thing is capped. Interior single newlines survive, which is the point.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not multiline:
        return " ".join(text.split())
    lines = [" ".join(ln.split()) for ln in text.split("\n")]
    out = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out[:max_lines or MAX_LINES])

# Ticked items stay a while, because "what did we just finish" is worth having
# for a day or two, and then they are noise.


def load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("projects"), dict):
            d.setdefault("unsaved", {})
            return d
    except (OSError, ValueError):
        pass
    return {"projects": {}, "unsaved": {}}



def save(d):
    write_json(FILE, d)


# The two things in the panel that can move. Tracked apart so that the line
# spent telling a session can say which of them did: "something changed" is a
# sentence that makes somebody go and look at both.
KINDS = ("roadmap", "memory")


def unsaved(project):
    """What has moved here since a session was last told, by kind.

    Edits are written the moment they are made (a phone that dies half way
    through tidying a list must not lose it), but telling the session is a
    separate act, because every telling costs a line in a conversation. So the
    two are tracked apart: the file is always current, and this says whether
    anybody has been told, and about what.
    """
    with _lock:
        got = load().get("unsaved", {}).get(project)
    return _kinds(got)


def _kinds(got):
    """The stored flags, one per half, shape-checked."""
    got = got if isinstance(got, dict) else {}
    return {k: bool(got.get(k)) for k in KINDS}


def _touch(d, project, kind="roadmap", on=True, who=""):
    # A session's own write (`who` is its seat) leaves the panel's flag as it
    # was (B56): the flag says the operator has something the sessions were
    # not told, and a session needs no telling about what it wrote. Another
    # session hears of it all the same, by the counter below.
    if not (on and who):
        cur = _kinds(d.setdefault("unsaved", {}).get(project))
        if kind is None:
            cur = dict.fromkeys(KINDS, bool(on))
        else:
            cur[kind] = bool(on)
        d["unsaved"][project] = cur
    # ...and a counter per kind that only ever goes up, which is what lets a
    # SESSION be told what it personally has not seen (roadmap #27). The
    # `unsaved` flag above is one per project: it answers "does the panel
    # still have something to say", and a second session clearing it would
    # answer for somebody else. A counter compares instead: each session
    # remembers the number it last saw, so being told is per session and
    # nobody's turn is spent on somebody else's behalf.
    if on:
        b = d.setdefault("bump", {}).setdefault(project, {})
        for k in (KINDS if kind is None else [kind]):
            b[k] = int(b.get(k, 0)) + 1


def _credit(d, project, who, kind="roadmap"):
    """Move one seat's watermark up by the change it just made itself.

    Without this, a session that adds an item is immediately behind the
    counter it moved, and the next prompt tells it the roadmap changed,
    which it did, by its own hand. Crediting the writer keeps "you have not
    seen this" meaning somebody ELSE wrote it.

    By one, not up to the current number: the point is to skip its own write,
    not to mark everything anybody else did as read on the way past.
    """
    if not who:
        return
    seat = (d.get("seen", {}).get(project) or {}).get(who)
    if isinstance(seat, dict):
        seat[kind] = int(seat.get(kind, 0)) + 1


# Every change to a list, kept. The list itself only ever shows its present
# state, and two people write it, so "was that step always worded like that?"
# and "who dropped the third one?" had no answer at all. Capped per project:
# this rides in the same file the list does, and an unbounded log would make
# every read of a short list pay for a year of edits.
MAX_HISTORY = 300


def _trim(h):
    """The log kept to its last MAX_HISTORY events, less the finished items:
    an item's done event IS the finished item (its row rides in it), and one
    trimmed away left the Finished section and bb roadmap show without it
    (B768). Kept whatever their age, as an archive is; the rest goes."""
    if len(h) <= MAX_HISTORY:
        return
    cut = len(h) - MAX_HISTORY
    keep = [e for e in h[:cut] if e.get("act") == "done" and e.get("step") is None]
    h[:cut] = keep


# How long a run of moves of one item is one line in the log (R254 step 5):
# a reorder is a move at a time, and a line per press drowned the rest.
MOVE_FOLD_S = 600


def _moved(d, project, by, row, i, j):
    """An item moved from place i to place j (0-based): logged, and folded
    into the last line when that was the same item moved by the same hand
    a moment ago, so one reorder reads as one line, from where it started
    to where it ended."""
    h = d.setdefault("history", {}).setdefault(project, [])
    last = h[-1] if h else None
    if (last and last.get("act") == "moved" and _int(last.get("id")) == _int(row.get("id"))
            and last.get("by") == by and time.time() - last.get("at", 0) < MOVE_FOLD_S):
        last.update(to=j + 1, at=int(time.time()))
        if last.get("from") == last.get("to"):
            h.pop()
        return
    _log(d, project, by, {"act": "moved", "id": _int(row.get("id")), "text": row.get("text", ""),
                          "from": i + 1, "to": j + 1})


def _log(d, project, by, ev):
    """Record one event, in the history or in an open batch.

    Called inside the lock, before the save that commits the change it
    describes, so the record and the change land together or neither does.

    While a batch is open the event goes into it instead. A session working a
    plan out rewords the same step three times before it is happy, and three
    entries saying so is a log nobody can read to find the one change that
    mattered. The batch is coalesced on commit into what actually happened.
    """
    name = str((actor() if actor else "") or "")[:60]
    ev = {"at": int(time.time()),
          "by": "claude" if by == "claude" else "you",
          # The account behind it, where one is known, including behind a
          # session, whose author is the person it was minted for.
          **({"who": name} if name else {}),
          # A replay of something the operator approved: said on the event,
          # so the log reads "claude, approved" rather than "claude".
          **({"approved": True} if pending.replaying() else {}), **ev}
    b = d.get("batch", {}).get(project)
    if b is not None and ev["by"] == b.get("by", "claude"):
        b.setdefault("events", []).append(ev)
        return
    # Anyone else's change goes straight to the history, which is also what
    # makes revert's guard work: it looks there for the operator's hand.
    h = d.setdefault("history", {}).setdefault(project, [])
    h.append(ev)
    _trim(h)


# ---- batches -------------------------------------------------------------
# A session that is working something out is not making a series of decisions
# the operator needs to read; it is arriving at one. `begin` takes a copy of
# the list, the work happens normally on top of it (visible, so the operator
# can watch it land), and `commit` writes what changed rather than every step
# of getting there. `revert` puts the copy back.
#
# Deliberately not the panel's model. There, the thing being edited is on
# screen and Save is the commit, so nothing should touch the list until it is
# pressed. Here the list is the only way anyone can see what a session is
# doing, and hiding the work until commit would be worse than a noisy log.

def begin(project, by="claude"):
    with _lock:
        d = load()
        if d.get("batch", {}).get(project):
            return {"error": "a batch is already open here; commit or revert it"}
        # How many of the operator's changes the log already held. Counted,
        # not timed: `at` has one-second resolution, so "later than the batch
        # opened" caught anything that happened in the same second as it,
        # which made revert refuse for a change that came *before* the work it
        # was asked to undo.
        h = d.get("history", {}).get(project) or []
        d.setdefault("batch", {})[project] = {
            "at": int(time.time()), "by": by, "events": [],
            "yours": sum(1 for e in h if e.get("by") == "you"),
            "rows": json.loads(json.dumps(d["projects"].get(project) or []))}
        save(d)
    return {"ok": True}


# How long a batch may stay open before it stops holding the notebook. A
# session's batch is minutes of work; one open for half an hour belongs to a
# session that was killed mid-way or a container that restarted under it, and
# it used to disable Save for every person on the project for good, with no
# way out that did not need a shell, which a user account does not have
# (B198). Lifting the HOLD is safe by the batch's own design: a person's
# change made while one is open goes straight to the history, the session's
# commit still folds its own events in, and its revert already refuses to
# roll back over a person's edit.
BATCH_STALE = 30 * 60


def _batch_view(b):
    at = int(b.get("at") or 0)
    return {"at": at, "by": b.get("by", ""), "changes": len(b.get("events") or []),
            "stale": bool(at and time.time() - at > BATCH_STALE)}


def batches():
    """Every project with a batch open, for the status poll.

    One read of the file for all of them: this runs on every poll, and asking
    per project would be a load and a lock each.
    """
    with _lock:
        d = load().get("batch", {})
    return {p: _batch_view(b) for p, b in d.items() if b}


def batch(project):
    """The open batch here, or None. What the panel shows a marker for."""
    with _lock:
        b = load().get("batch", {}).get(project)
    return None if not b else _batch_view(b)


# Two events about the same line are one event about that line. Ordered by
# what the pair means rather than by what each said: written-then-dropped is
# nothing at all, and reworded-twice is one rewording from the first wording
# to the last.
def _coalesce(events):
    out, seen = [], {}
    for e in events:
        key = (e.get("id"), e.get("step"))
        act = e.get("act", "")
        prev = seen.get(key)
        if prev is None:
            seen[key] = e
            out.append(e)
            continue
        pact = prev.get("act", "")
        if act.startswith("remove") and pact.startswith("add"):
            out.remove(prev)                    # written and dropped again
            del seen[key]
            continue
        if act.startswith("remove") or act in ("done",):
            out.remove(prev)
            seen[key] = e
            out.append(e)
            continue
        if act == "unshelved" and pact == "shelved":
            out.remove(prev)
            del seen[key]
            continue
        if pact.startswith("add"):
            prev["text"] = e.get("text", prev.get("text"))   # written, then reworded
            prev["at"] = e["at"]
            continue
        if act.startswith("edit") and pact.startswith("edit"):
            prev["text"] = e.get("text", "")                 # one rewording
            prev["at"] = e["at"]
            continue
        out.remove(prev)
        seen[key] = e
        out.append(e)
    return out


def commit(project):
    with _lock:
        d = load()
        b = d.get("batch", {}).get(project)
        if not b:
            return {"error": "nothing is open here"}
        kept = _coalesce(b.get("events") or [])
        h = d.setdefault("history", {}).setdefault(project, [])
        h.extend(kept)
        _trim(h)
        del d["batch"][project]
        save(d)
    return {"ok": True, "written": len(kept),
            "folded": len(b.get("events") or []) - len(kept)}


def revert_blocked(project):
    """Why a revert would refuse, or None. Asked before anything is undone.

    Only the session's own work goes back. If the operator changed something
    while the batch was open, restoring a copy taken before it would quietly
    undo their change too, so it is refused and said.

    Its own function because a notebook batch spans two files: both guards
    have to answer before either is put back, or a refusal from the second
    would leave the first already reverted.
    """
    with _lock:
        d = load()
        b = d.get("batch", {}).get(project)
        if not b:
            return "nothing is open here"
        h = d.get("history", {}).get(project) or []
        if sum(1 for e in h if e.get("by") == "you") > b.get("yours", 0):
            return ("the operator has changed this list since the batch "
                    "opened; reverting would undo their work too. "
                    "Commit it and correct what is wrong.")
    return None


def revert(project):
    why = revert_blocked(project)
    if why:
        return {"error": why}
    with _lock:
        d = load()
        b = d.get("batch", {}).get(project)
        if not b:
            return {"error": "nothing is open here"}
        d["projects"][project] = b.get("rows") or []
        del d["batch"][project]
        _touch(d, project)
        save(d)
    return {"ok": True, "dropped": len(b.get("events") or [])}


def history(project, limit=None, since=None, find=None):
    """What has happened to this list, newest first, optionally narrowed.

    Narrowed here rather than by whoever is reading, because the reader that
    matters most is a session: a log dumped whole is a log that costs more
    context than the answer in it is worth. `find` reads the words of the
    line, what it used to say, and the reason it was dropped: the three
    places anybody would look.
    """
    with _lock:
        h = load().get("history", {}).get(project) or []
    # Sorted, not merely reversed: a batch's events are written at commit, so
    # the order they sit in the file is not the order they happened in.
    out = sorted(h, key=lambda e: -e.get("at", 0))
    if since is not None:
        cut = _int(since)
        if cut is not None:
            out = [e for e in out if e.get("at", 0) >= cut]
    if find:
        needle = str(find).lower()
        out = [e for e in out
               if any(needle in str(e.get(k, "")).lower()
                      for k in ("text", "was", "why", "of", "act"))]
    n = _int(limit)
    if n is not None and n > 0:
        out = out[:n]
    return out


def items(project):
    """The list, in the order it is stored, which is the order it is shown.

    Nothing is sorted here any more. A list that reshuffles itself is one you
    cannot keep a plan in: an item ticked off would jump to the bottom, taking
    its steps with it, and the order the operator arranged would be a
    suggestion the list overruled. Done items fade where they are, the same
    way sent steps stay struck through where they are.
    """
    with _lock:
        return load()["projects"].get(project) or []


def counts():
    """{project: how much is still to do} for the project rows.

    The same number the panel shows, which is what makes the badge worth
    glancing at: an item with nothing left to hand over does not count.
    Everything on the list is outstanding by construction now (ticking one
    off takes it off), so this is only about how much of it can still be sent.
    """
    with _lock:
        d = load()
    return {p: sum(1 for r in rows
                   if not r.get("shelved") and next_step(r) is not None)
            for p, rows in d["projects"].items()}


def _int(v):
    """A whole number out of whatever JSON carried, or None.

    Everything that names an item or a step arrives from a request body, so
    `int(v)` is a crash waiting for a field that is a list, a dict, or the
    word "x". One reader, and every caller answers "not an item" instead of
    dying.

    "R12" is accepted beside 12, because the printed form of an id is the
    letter and the number (ids.py), and another tab's letter reads as no item
    at all.
    bb checks the letter before it gets here so the refusal can say why; the
    dashboard sends bare ints and never trips it.
    """
    n, _err = ids.parse("roadmap", v)
    return n


def _next_id(rows, d=None, project=None):
    """One above the highest number ever handed out here.

    On the list, held for approval (pending.py), or finished and gone: the
    file keeps the high-water mark under `reserved`, and it never comes
    down. It used to be the highest number still ON the list, so ticking
    the newest items off handed their numbers to the next adds: the
    approval gate was #27 in ten comments and the next item was R27 too
    (bug B72). A number is the item's own, and "a gap means something was
    removed" only holds if nothing is ever numbered twice.
    """
    top = max((int(r.get("id", 0)) for r in rows), default=0)
    if d is not None and project is not None:
        top = max(top, _int((d.get("reserved") or {}).get(project)) or 0)
    return top + 1


def _took(d, project, n):
    """Record that `n` has been handed out, so it never is again."""
    r = d.setdefault("reserved", {})
    r[project] = max(_int(r.get(project)) or 0, int(n))


# The details under a line: the technical half the title should not carry.
# Which files, which functions, the approach, earmarked when the plan is
# written so the session that works the step does not start from a cold grep.
# Longer than a line is allowed to be, because "where in the codebase" is a
# list, not a sentence.
MAX_INFO = 20000
MAX_INFO_LINES = 500


def set_info(project, item_id, text, step=None, by="you", was=None, who=""):
    """Attach details to an item or one step of it, or clear them with "".

    Its own verb rather than a field on edit, because the two change for
    different reasons: the words are *what* is being asked, the details are
    *where and how*, and the history should say which of the two moved.
    """
    text = _clean(text, max_lines=MAX_INFO_LINES + 1)
    if len(text) > MAX_INFO or text.count("\n") >= MAX_INFO_LINES:
        return {"error": f"details are {MAX_INFO} characters over at most "
                         f"{MAX_INFO_LINES} lines. Write the half a session would "
                         f"otherwise grep for (which files, which functions, what "
                         f"was decided) and not the thinking that got there; the "
                         f"whole list is read into every session's prompt."}
    if step is not None and _int(step) is None:
        return {"error": "not a step"}

    def change(row, rows):
        i = _int(step)
        target = row
        ev = {"act": "info", "id": row["id"]}
        if i is not None and i >= 0:
            steps = row.get("steps") or []
            if not 0 <= i < len(steps):
                return {"error": "no such step"}
            target = steps[i]
            ev.update(act="info-step", step=i, of=row["text"])
        old = target.get("info", "")
        if (bad := clash("item's details" if target is row else "step's details",
                         old, was)):
            return bad
        if text:
            target["info"] = text
        else:
            target.pop("info", None)
        ev.update(text=text, **({"was": old} if old else {}))
        return {"ok": True, "item": row, "log": ev}
    return _edit(project, item_id, change, by, who, finished=True)


# An item is one thing to do, or several in an order that matters. A change
# that needs three things done in sequence is not three items: put them out
# of order and the second one lands on a tree the first was supposed to have
# made. So a group keeps its steps, and only the next unsent one can be sent.
MAX_STEPS = 100


def add(project, text, by="you", steps=(), who="", number=None):
    text = _clean(text)
    if not text:
        return {"error": "nothing to add"}
    if len(text) > MAX_TEXT:
        return {"error": f"too long: {MAX_TEXT} characters is the limit. Almost never compress the wording: the technical half belongs in `bb roadmap info`, and a step should say what has to be true before the next one can start."}
    steps = [_clean(str(x)) for x in (steps or [])]
    steps = [x for x in steps if x]
    if len(steps) > MAX_STEPS:
        return {"error": f"{MAX_STEPS} steps is the limit for one item. Past that it is more than one goal, and separate items can be sent in any order, which is the whole reason both shapes exist."}
    if any(len(x) > MAX_TEXT for x in steps):
        return {"error": f"a step is longer than {MAX_TEXT} characters. A step "
                         f"is a point at which the last work must have finished, "
                         f"not a task: put everything that can be done in one go "
                         f"into one, and the detail in `bb roadmap info`."}
    # The gate (roadmap #27): what a SESSION adds may be held for the operator
    # or refused, per project. After the checks above, so a held record is
    # one that would have landed, and the number it is told is reserved
    # here, where the next id is minted, so nothing else takes it meanwhile.
    if by == "claude" and not pending.replaying():
        g = pending.mode(project, "roadmap")
        if g == "deny":
            return {"error": pending.refusal("roadmap")}
        if g == "ask":
            with _lock:
                d = load()
                n = _next_id(d["projects"].get(project) or [], d, project)
                d.setdefault("reserved", {})[project] = n
                save(d)
            return pending.hold(project, "roadmap", "add",
                                {"text": text, "steps": steps, "who": who, "number": n},
                                summary=text, number=n)
    with _lock:
        d = load()
        rows = d["projects"].get(project) or []
        if sum(1 for r in rows if not r.get("shelved")) >= MAX_OPEN:
            return {"error": f"{MAX_OPEN} open items is the limit: finish, "
                             "park or drop some first"}
        nid = _int(number) or _next_id(rows, d, project)
        _took(d, project, nid)
        row = {"id": nid, "text": text,
               "added": int(time.time()), "by": "claude" if by == "claude" else "you",
               "sent": 0,
               "steps": [{"text": x, "sent": 0} for x in steps]}
        # The end, so the ids run down the page. The alternative is a list
        # where every addition renumbers what a session was looking at, and
        # the number is the whole way to say which item is meant.
        # Above the shelf, not at the very end: the shelf is the bottom of the
        # list and something just added is the opposite of parked. The panel
        # puts it in the same place, and a new item landing somewhere other
        # than where it was drawn is the kind of jump that reads as a bug.
        rows.insert(sum(1 for r in rows if not r.get("shelved")), row)
        _log(d, project, by, {"act": "add", "id": row["id"], "text": text,
                              **({"steps": len(steps)} if steps else {})})
        d["projects"][project] = rows
        _touch(d, project, who=who)
        _credit(d, project, who)
        save(d)
    return {"ok": True, "item": row}


def _events(d, project):
    """The history and then the open batch's events (B819): inside a batch
    what this session did waits there until commit, so an item a step had
    just closed was neither on the list nor in the history, and read as
    never there."""
    return [*(d.get("history", {}).get(project) or []),
            *((d.get("batch", {}).get(project) or {}).get("events") or [])]


def _gone(d, project, item_id):
    """Why an item is not on the list, from the loaded file's log, or the
    plain answer: finished (ticked off, or its last step done), dropped, or
    never there (B737: a step done after the last one closed the item said
    only 'no such item'). The open batch's events too (B819): inside one the
    close waits there until commit, and an item a step had just closed read
    as never there."""
    for e in sorted(_events(d, project), key=lambda e: -e.get("at", 0)):
        if _int(e.get("id")) != item_id or e.get("step") is not None:
            continue
        if e.get("act") == "done":
            return {"error": f"R{item_id} is done already: it left the list when it was finished, "
                             "and the notebook's Roadmap view shows it under Finished"}
        if e.get("act") == "remove":
            return {"error": f"R{item_id} was dropped from the list"
                             + (f": {e['why']}" if e.get("why") else "")}
    return {"error": f"no item R{item_id} on this list"}


def _find(rows, item_id):
    return next((r for r in rows if _int(r.get("id")) == item_id), None)


def _moved_by(d, project, item_id):
    """Who last changed this item and when, out of the log, for the refusal
    below, which is worth nothing without a name and a time on it.

    An open batch is searched first: its events are newer than anything in the
    history, and a session working a plan out is the likeliest other writer.
    """
    b = (d.get("batch", {}).get(project) or {}).get("events") or []
    h = d.get("history", {}).get(project) or []
    for e in reversed(list(h) + list(b)):
        if _int(e.get("id")) == item_id:
            return {"by": e.get("by", ""), "at": e.get("at", 0)}
    return {}


def clash(what, stored, was):
    """The refusal, when a write's base is no longer what is stored.

    What a write to this list replaces is one FIELD (an item's words, or a
    step's, or either one's details), so what it carries is not a version
    number for the row but the words it believes it is replacing, and the
    check is that they are still there (roadmap #26).

    Per field rather than per row on purpose, and it was built the other way
    first: a session attaching details while the operator rewords the same
    line is two people doing two things, and a row counter reports that as a
    conflict and then offers a dialog whose two sides are not in conflict
    about anything. Same item is not the same as same words.

    `was is None` means the caller did not say what it was replacing, and is
    unchecked: every caller that predates this, and `bb`, which has its own
    guard for the same danger and a much longer window to guard.
    """
    if was is None or str(was) == str(stored):
        return None
    return {"error": f"this {what} changed while you had it open",
            "conflict": {"current": stored}}


def _oldest_first(events):
    """The log in the order things happened: by time, and in the order they
    were written within one second (a sort on time alone, reversed, read an
    item's steps before the item that made room for them)."""
    return [e for _, e in sorted(enumerate(events), key=lambda p: (p[1].get("at", 0), p[0]))]


def _rebuilt_row(events, item_id, text):
    """A finished item's row put back together from the log, for one kept
    without it (finished by its last step before B767): its steps from their
    add-step events, with their edits, details and done marks applied. A step
    made with the item logged only a count, so it says its words are gone."""
    row = {"id": item_id, "text": text, "steps": []}
    steps = row["steps"]
    for e in events:
        if _int(e.get("id")) != item_id:
            continue
        act, i = e.get("act"), _int(e.get("step"))
        if act == "add":
            row["text"] = e.get("text") or row["text"]
            steps[:] = [{"text": f"step {k + 1} (its words were not kept)", "sent": 0}
                        for k in range(_int(e.get("steps")) or 0)]
        elif act == "add-step" and i is not None:
            while len(steps) < i:
                steps.append({"text": f"step {len(steps) + 1} (its words were not kept)", "sent": 0})
            steps[i:i + 1] = [{"text": e.get("text", ""), "sent": 0}]
        elif i is not None and 0 <= i < len(steps):
            if act == "edit-step":
                steps[i]["text"] = e.get("text", steps[i]["text"])
            elif act == "info-step":
                steps[i]["info"] = e.get("text", "")
            elif act == "done-step":
                steps[i]["done"] = e.get("at", 0)
            elif act == "undone-step":
                steps[i].pop("done", None)
        elif act == "edit" and i is None:
            row["text"] = e.get("text") or row["text"]
        elif act == "info" and i is None:
            row["info"] = e.get("text", "")
    return row


def _finished_row(d, project, item_id):
    """A finished item's row as the Finished section shows it: the snapshot
    in its newest "done" event, made into one for an older event that kept
    only the words. None when it is not a finished item."""
    for e in reversed(_events(d, project)):
        if _int(e.get("id")) != item_id or e.get("step") is not None:
            continue
        # Its words or details put right since: still finished.
        if e.get("act") in ("info", "edit"):
            continue
        if e.get("act") != "done":
            return None
        if not isinstance(e.get("row"), dict) or not e["row"].get("steps"):
            # Kept without its row, or with an empty one a build before the
            # rebuild wrote (15 Oct): the steps the log knows join it, and its
            # own words and details stay.
            got = _rebuilt_row(_oldest_first(_events(d, project)), item_id, e.get("text", ""))
            e["row"] = {**got, **(e["row"] if isinstance(e.get("row"), dict) else {}), "steps": got["steps"]}
        return e["row"]
    return None


def _edit(project, item_id, change, by="you", who="", finished=False):
    """Run one change against one item, under the lock.

    A change hands back its own history entry under "log", which is stripped
    off here rather than by every caller: the entry has to be written inside
    this lock, next to the change it describes, and a closure that returns it
    cannot reach the loaded file to write it itself.

    It may also hand back a `conflict` (see `clash` above), which is filled
    in here with who moved the thing and when, for the same reason: the log
    is inside this lock and the closure cannot reach it.
    """
    item_id = _int(item_id)
    if item_id is None:
        return {"error": "not an item"}
    with _lock:
        d = load()
        rows = d["projects"].get(project) or []
        row = _find(rows, item_id)
        # A finished item stays finished, and its words and details can still
        # be put right (B766): the change lands on the row its "done" event
        # keeps, which is what the Finished section draws. Refused for the
        # verbs about doing the work, which a finished item has none of.
        done = row is None and finished and _finished_row(d, project, item_id)
        if done:
            row = done
        if row is None:
            return _gone(d, project, item_id)
        out = change(row, rows)
        if done and isinstance(out, dict) and isinstance(out.get("log"), dict):
            out["log"]["finished"] = True
        ev = out.pop("log", None) if isinstance(out, dict) else None
        ok = isinstance(out, dict) and not out.get("error")
        if isinstance(out, dict) and out.get("conflict"):
            out["conflict"].update(id=item_id, **_moved_by(d, project, item_id))
            return out
        # One event, or a list of them: the last step of a plan being marked
        # done is two things that happened (the step, and the item it
        # finished), and the log says both.
        for e in ([ev] if isinstance(ev, dict) else (ev or [])):
            if ok:
                _log(d, project, by, e)
        d["projects"][project] = rows
        # Only when something happened. A refused change (no such step, a
        # step that has gone) used to mark the list unsaved all the same,
        # which since #27 means every session on the project is told the
        # roadmap moved when nothing did.
        if ok:
            _touch(d, project, who=who)
            _credit(d, project, who)
        save(d)
    return out


def shelve(project, item_id, on=True, by="you", who="", why=""):
    """Put an item aside without taking it off, or bring it back.

    The state between "do this" and "we are not doing this": a reason to keep
    it, no intention of doing it now. It sinks to the bottom of the list, goes
    dark, and its arrow dies, so what is left above it is what is actually
    live, which is the only thing the list is read for.

    Physically to the bottom, not sorted there on the way out: the stored
    order is the displayed order everywhere else here, and two orders is how
    a rearrangement lands somewhere nobody pointed at.

    A session may shelve, and may ASK for one back (R78): taking an item off
    the shelf reverses a decision it was not told the reason for, so its
    request is held for a person on the project, with its reason, and lands
    when they approve it, whatever the roadmap gate says. That is a
    notification with a decision behind it, not a gate on creation, which
    is why it is held here and not in the add path.
    """
    why = _clean(why or "")
    if by == "claude" and not on and not pending.replaying():
        item = _find(items(project), _int(item_id))
        if item is None:
            return {"error": "no such item"}
        if not item.get("shelved"):
            return {"error": "it is already off the shelf"}
        label = ids.label("roadmap", item["id"])
        return pending.hold(project, "roadmap", "unshelve",
                            {"item_id": item["id"], "on": False, "why": why},
                            f"take {label} off the shelf" + (f": {why}" if why else ""),
                            number=item["id"])

    def change(row, rows):
        if bool(on) == bool(row.get("shelved")):
            return {"error": "it is already " + ("shelved" if on else "off the shelf")}
        row["shelved"] = int(time.time()) if on else 0
        rows.remove(row)
        if on:
            rows.append(row)
        else:
            # Back above the shelf, at the end of the live ones: its old place
            # is not recoverable and guessing at one would be worse than the
            # bottom of the part of the list it belongs to.
            rows.insert(sum(1 for r in rows if not r.get("shelved")), row)
        return {"ok": True, "item": row,
                "log": {"act": "shelved" if on else "unshelved",
                        "id": row["id"], "text": row["text"],
                        **({"why": why} if why else {})}}
    return _edit(project, item_id, change, by, who=who)


def tick(project, item_id, by="you", who=""):
    """Finish an item: off the list, into the log.

    It used to fade in place for a week. That is the same mistake striking a
    line out by hand was: a list is read to find out what is left, and a
    thing that is finished is not left. Both ways of leaving now go the same
    way, and the log is what tells them apart: "ticked off" is a session
    saying it did the work, "dropped" is somebody deciding not to.

    There is no putting one back, because there is nothing to put it back
    *to*. The words are in the history; adding it again is a fresh item, and
    that is honest: it is being asked for a second time.
    """
    def change(row, rows):
        rows.remove(row)
        # The whole row rides in the log, as a dropped one's does: the Roadmap
        # tab shows finished items behind a toggle (R78), with their steps and
        # details, and the words alone would have been a line with no plan.
        return {"ok": True, "item": row,
                "log": {"act": "done", "id": row["id"], "text": row["text"],
                        "row": copy.deepcopy(row),
                        **({"steps": len(row.get("steps") or [])}
                           if row.get("steps") else {})}}
    return _edit(project, item_id, change, by, who=who)


def finished(project, limit=None):
    """The items ticked off, newest first, each as it was when it went:
    the "done" events in the history that carry the row (a tick since 23
    Sep, a last step since B767), or the row put back together from the log
    (an older one). One entry per item, the newest
    tick of it, and the Roadmap tab shows them below the shelved ones,
    hidden until asked for."""
    # One reopened since is on the list again, not under Finished.
    seen, out = {_int(r.get("id")) for r in items(project)}, []
    log = history(project)
    # Whether reopen would take it (R254 step 2): never one a released
    # version shipped, so the page offers Reopen only where it will land.
    rel = last_release(project)
    for e in log:
        if e.get("act") != "done" or e.get("step") is not None:
            continue
        i = _int(e.get("id"))
        if i is None or i in seen:
            continue
        seen.add(i)
        # One kept without its row (finished by its last step before B767) is
        # put back together from the log, oldest first, rather than shown as
        # the words alone.
        row = copy.deepcopy(e["row"]) if isinstance(e.get("row"), dict) else {}
        if not row.get("steps"):
            got = _rebuilt_row(_oldest_first(log), i, e.get("text", ""))
            row = {**got, **row, "steps": got["steps"]}
        row.update(id=i, done_at=e.get("at", 0), done_by=e.get("by", ""),
                   reopenable=not (rel and e.get("at", 0) < rel[1]))
        out.append(row)
    n = _int(limit)
    return out[:n] if n else out


# The project's last release, read off its changelog's newest release heading
# ("## 0.7.0: 2026-09-25"): an item finished on or before that day shipped
# with that version, and reopening it would rewrite a released version's
# record (the operator, 15 Oct). (version, epoch of the day's end) or None.
_RELEASE = re.compile(r"^## (\d+\.\d+\.\d+[^:\s]*): (\d{4}-\d{2}-\d{2})\s*$", re.M)


def releases(project):
    """Every released version in the project's CHANGELOG, newest first, each
    with the end of its day (R254 step 4): a thing done before that end and
    after the one before it shipped in that version, and one done after the
    newest is planned for the next. Derived, never typed."""
    try:
        text = (Path(os.environ.get("WORKSPACE", "/workspace")) / project / "CHANGELOG.md").read_text(errors="replace")
    except OSError:
        return []
    out = []
    for m in _RELEASE.finditer(text):
        try:
            out.append((m.group(1), time.mktime(time.strptime(m.group(2), "%Y-%m-%d")) + 86400))
        except ValueError:
            continue
    return out


_REF = re.compile(r"(?<![\w-])([RB])(\d{1,5})(?![\w-])")
_SECTION = re.compile(r"^## (Unreleased|\d+\.\d+\.\d+[^:\s]*)")


def changelog_refs(project, kind="R"):
    """The changelog entries that name a roadmap item (kind R) or a bug (B),
    by its id: {"R12": [{"in": "0.7.0" or "Unreleased", "text": ...}]},
    newest first, at most ten each (R254 step 4), so an item lists what was
    written about it and the release it went out in."""
    try:
        text = (Path(os.environ.get("WORKSPACE", "/workspace")) / project / "CHANGELOG.md").read_text(errors="replace")
    except OSError:
        return {}
    out, where = {}, ""
    for line in text.splitlines():
        m = _SECTION.match(line)
        if m:
            where = m.group(1)
            continue
        if not where or not line.startswith("- "):
            continue
        for k, n in {(k, n) for k, n in _REF.findall(line) if k == kind}:
            got = out.setdefault(f"{k}{int(n)}", [])
            if len(got) < 10:
                got.append({"in": where, "text": line[2:].strip()[:240]})
    return out


def last_release(project):
    rel = releases(project)
    return rel[0] if rel else None


def reopen(project, item_id, by="you", who=""):
    """Put a finished item back on the list as its row was, its steps and
    details with it, for work that is truly part of the same goal and found
    after it was ticked off; never one a released version shipped. Above the
    shelf, like an item just added."""
    item_id = _int(item_id)
    if item_id is None:
        return {"error": "not an item"}
    with _lock:
        d = load()
        rows = d["projects"].get(project) or []
        if _find(rows, item_id):
            return {"error": f"R{item_id} is on the list"}
        if sum(1 for r in rows if not r.get("shelved")) >= MAX_OPEN:
            return {"error": f"{MAX_OPEN} open items is the limit: finish, park or drop some first"}
        done = _finished_row(d, project, item_id)
        if done is None:
            return _gone(d, project, item_id)
        # Only the same work, and never across a release: an item a released
        # version shipped stays in that version's record, and more work on it
        # is a new item (the operator, 15 Oct).
        rel = last_release(project)
        when = max((e.get("at", 0) for e in d.get("history", {}).get(project) or []
                    if _int(e.get("id")) == item_id and e.get("act") == "done" and e.get("step") is None), default=0)
        if rel and when and when < rel[1]:
            return {"error": f"R{item_id} was finished before {rel[0]} was released and shipped with it: "
                             "it stays closed, and more work on it is a new item (it may name this one)"}
        row = {k: v for k, v in copy.deepcopy(done).items() if k not in ("done_at", "done_by")}
        row.pop("shelved", None)
        rows.insert(sum(1 for r in rows if not r.get("shelved")), row)
        d["projects"][project] = rows
        _log(d, project, by, {"act": "reopen", "id": item_id, "text": row.get("text", "")})
        _touch(d, project, who=who)
        _credit(d, project, who)
        save(d)
    return {"ok": True, "item": row}


def edit(project, item_id, text, step=None, by="you", was=None, who=""):
    """Reword an item, or one step of it."""
    text = _clean(text)
    if not text:
        return {"error": "nothing to say"}
    if len(text) > MAX_TEXT:
        return {"error": f"too long: {MAX_TEXT} characters is the limit. Almost never compress the wording: the technical half belongs in `bb roadmap info`, and a step should say what has to be true before the next one can start."}
    if step is not None and _int(step) is None:
        return {"error": "not a step"}

    def change(row, rows):
        i = _int(step)
        if i is None or i < 0:
            if (bad := clash("item", row["text"], was)):
                return bad
            old, row["text"] = row["text"], text
            return {"ok": True, "item": row,
                    "log": {"act": "edit", "id": row["id"],
                            "text": text, "was": old}}
        steps = row.get("steps") or []
        if not 0 <= i < len(steps):
            return {"error": "no such step"}
        if (bad := clash("step", steps[i]["text"], was)):
            return bad
        old, steps[i]["text"] = steps[i]["text"], text
        return {"ok": True, "item": row,
                "log": {"act": "edit-step", "id": row["id"], "step": i,
                        "text": text, "was": old, "of": row["text"]}}
    return _edit(project, item_id, change, by, who, finished=True)


def remove(project, item_id, step=None, by="you", why="", was=None, who=""):
    """Drop an item, or one step out of a group.

    Removing a step is how a plan gets corrected mid-flight: the one after it
    becomes the next in line, so the group carries on from where it really is
    rather than from where it was written.

    Dropping is for work that is abandoned: a finished plan is ticked, and
    marking its last step done ticks it. So the history keeps the whole row,
    steps and details and all, and `restore` puts it back from there: a line
    dropped by mistake, or a decision reversed, is one press rather than a
    retype.

    And it keeps the reason. "Dropped" and "dropped because the picker this
    described no longer exists" are the same event to the list and different
    events to whoever reads it next, and the second one is what stops
    somebody putting it back.
    """
    why = _clean(why, multiline=False)[:MAX_TEXT]

    def change(row, rows):
        if step is None:
            if (bad := clash("item", row["text"], was)):
                return bad
            rows.remove(row)
            return {"ok": True,
                    "log": {"act": "remove", "id": row["id"], "text": row["text"],
                            "row": copy.deepcopy(row),
                            **({"why": why} if why else {}),
                            **({"steps": len(row.get("steps") or [])}
                               if row.get("steps") else {})}}
        steps = row.get("steps") or []
        i = _int(step)
        if i is None:
            return {"error": "not a step"}
        if not 0 <= i < len(steps):
            return {"error": "no such step"}
        if (bad := clash("step", steps[i].get("text", ""), was)):
            return bad
        gone = steps.pop(i)
        return {"ok": True,
                "log": {"act": "remove-step", "id": row["id"], "step": i,
                        "text": gone.get("text", ""), "of": row["text"],
                        **({"why": why} if why else {})}}
    return _edit(project, item_id, change, by, who)


def move(project, item_id, step=None, dir=0, by="you", who=""):
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
            rows = d["projects"].get(project) or []
            i = next((n for n, r in enumerate(rows)
                      if _int(r.get("id")) == item_id), None)
            if i is None:
                return {"error": "no such item"}
            # Shelved items are a suffix, the way sent steps are a prefix: the
            # shelf is the bottom of the list, and a swap across its edge would
            # leave a dark row sitting among the live ones.
            shelf = sum(1 for r in rows if not r.get("shelved"))
            if (i < shelf) != (i + dir < shelf):
                return {"error": "shelved items stay at the bottom"}
            row = rows[i]
            out = swap(rows, i)
            if out.get("ok"):
                d["projects"][project] = rows
                _touch(d, project, who=who)
                _credit(d, project, who)
                _moved(d, project, by, row, i, i + dir)
                save(d)
        return out

    def change(row, rows):
        steps = row.get("steps") or []
        i = _int(step)
        if i is None:
            return {"error": "not a step"}
        if not 0 <= i < len(steps):
            return {"error": "no such step"}
        # By mark, not by prefix: sent steps are a prefix by construction,
        # but a session may finish step three with one and two still to
        # send, and that one is just as fixed.
        j = i + dir
        if gone(steps[i]) or (0 <= j < len(steps) and gone(steps[j])):
            return {"error": "a step that has gone stays where it is"}
        return swap(steps, i)
    return _edit(project, item_id, change, by, who=who)


def add_step(project, item_id, text, by="you", who=""):
    """Give an item a step, which is how a plain one becomes a plan."""
    text = _clean(text)
    if not text:
        return {"error": "nothing to add"}
    if len(text) > MAX_TEXT:
        return {"error": f"too long: {MAX_TEXT} characters is the limit. Almost never compress the wording: the technical half belongs in `bb roadmap info`, and a step should say what has to be true before the next one can start."}

    def change(row, rows):
        steps = row.setdefault("steps", [])
        if len(steps) >= MAX_STEPS:
            return {"error": f"{MAX_STEPS} steps is the limit for one item. Past that it is more than one goal, and separate items can be sent in any order, which is the whole reason both shapes exist."}
        steps.append({"text": text, "sent": 0})
        return {"ok": True,
                "log": {"act": "add-step", "id": row["id"],
                        "step": len(steps) - 1, "text": text, "of": row["text"]}}
    return _edit(project, item_id, change, by, who=who)


def cross(project, item_id, step=None, on=True, by="you", who=""):
    """Put a sent line back, or mark one as gone.

    This used to be two features. Striking a line out *by hand* ("I did this
    one myself") is gone: a line crossed off without being handed over reads
    exactly like one that was, and a list of things that look dealt with and
    are not is worse than a shorter list. What is left is the undo of a send:
    it did not take, put it back so it can go again. Removing it is the other
    answer, and the history keeps the words either way.
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
        if not on and not target.get("sent"):
            return {"error": "that has not been sent"}
        target["sent"] = int(time.time()) if on else 0
        target.pop("by_hand", None)
        ev = {"act": "sent" if on else "unsent", "id": row["id"],
              "text": target.get("text", "")}
        if i is not None and i >= 0:
            ev.update(step=i, of=row["text"])
        return {"ok": True, "log": ev}
    return _edit(project, item_id, change, by, who=who)


def _flat(text):
    """One line, for the one place that has to be one line.

    A step can be written across several lines because a person reads it in
    the panel. It is delivered by typing it into a terminal, where a newline
    is not whitespace: it is Enter, and it would submit half a prompt and
    leave the rest to arrive as a second message. So the breaks become
    separators on the way out. A paragraph break is a heavier one than a line
    break, which is about as much of the shape as a single line can carry.
    """
    parts = [p.strip() for p in (text or "").split("\n\n")]
    return " / ".join(" ".join(p.split()) for p in parts if p.strip())


def gone(st):
    """A step that needs no sending: handed over, or finished by a session."""
    return bool(st.get("sent") or st.get("done"))


def next_step(row):
    """Index of the next step that has not been sent or finished, or None.

    -1 means the item itself, for one with no steps. This is the whole order
    guarantee: a group hands out its steps one at a time, in the order they
    were written, and never the third before the second. A step a session
    finished without being sent it (told in chat, or carried along with
    the one before) is passed over the same way, so the operator is never
    offered a finished step as the next thing to send.
    """
    steps = row.get("steps") or []
    if not steps:
        return None if gone(row) else -1
    for i, st in enumerate(steps):
        if not gone(st):
            return i
    return None


def step_done(project, item_id, step, by="claude", note="", who=""):
    """A session finished one step of a plan, and says so.

    The step used to have one mark, sent, and sent is the dashboard's: it
    says a line was handed over, not that anything came of it. A session
    told in chat to go ahead with a phase had no way to mark the phase
    finished, so it reworded the step to say LANDED and the panel went on
    offering it to send. This is the second mark. Only a session sets it,
    the same rule as ticking off an item; a session that ticked the wrong
    one, or found it not finished after all, takes it back with
    step_undone (the operator, 17 Oct), as sending it again does.
    """
    if _int(step) is None:
        return {"error": "not a step"}

    def change(row, rows):
        steps = row.get("steps") or []
        i = _int(step)
        if not 0 <= i < len(steps):
            return {"error": "no such step"}
        if steps[i].get("done"):
            return {"error": "that step is already done"}
        steps[i]["done"] = int(time.time())
        ev = {"act": "done-step", "id": row["id"], "step": i,
              "text": steps[i].get("text", ""), "of": row["text"]}
        if note:
            ev["why"] = _clean(note, multiline=False)
        # The last one finishes the plan: off the list and into the log as
        # done, the way `tick` does it, without a second command. A list is
        # read to find out what is left, and a plan with every step done is
        # not left; it used to sit there saying "bb roadmap done takes it
        # off" until somebody typed that.
        if all(st.get("done") for st in steps):
            rows.remove(row)
            # The whole row, as a tick's carries (B767): finished by its last
            # step it showed under Finished as the words alone, its plan gone.
            return {"ok": True, "finished": True, "item": row,
                    "log": [ev, {"act": "done", "id": row["id"], "text": row["text"],
                                 "row": copy.deepcopy(row), "steps": len(steps)}]}
        return {"ok": True, "log": ev}
    return _edit(project, item_id, change, by, who=who)


def step_undone(project, item_id, step, by="claude", note="", who=""):
    """Take back a step's done mark (the operator, 17 Oct: a session that
    ticked the wrong step had no way back but a person's Send). The step is
    left to do again, and the log says so, with why where one is given."""
    if _int(step) is None:
        return {"error": "not a step"}

    def change(row, rows):
        steps = row.get("steps") or []
        i = _int(step)
        if not 0 <= i < len(steps):
            return {"error": "no such step"}
        if not steps[i].get("done"):
            return {"error": "that step is not done"}
        steps[i].pop("done", None)
        ev = {"act": "undone-step", "id": row["id"], "step": i,
              "text": steps[i].get("text", ""), "of": row["text"]}
        if note:
            ev["why"] = _clean(note, multiline=False)
        return {"ok": True, "log": ev}
    return _edit(project, item_id, change, by, who=who)


def restore(project, item_id, at=None, by="you", who=""):
    """Put a dropped item back from the history, as it was when it went.

    The newest "remove" of that item, or the one at `at` when the log
    holds several, carries the row itself (see remove), so what comes back
    is the plan with its steps, marks and details, under its own number. A
    ticked-off item is not restorable: done is a session's word that the
    work happened, and undoing that is adding the work again.
    """
    item_id = _int(item_id)
    if item_id is None:
        return {"error": "not an item"}
    with _lock:
        d = load()
        rows = d["projects"].get(project) or []
        if _find(rows, item_id) is not None:
            return {"error": f"{ids.label("roadmap", item_id)} is on the list"}
        if sum(1 for r in rows if not r.get("shelved")) >= MAX_OPEN:
            return {"error": f"{MAX_OPEN} open items is the limit: finish, "
                             "park or drop some first"}
        want = _int(at)
        evs = [e for e in (d.get("history", {}).get(project) or [])
               if e.get("act") == "remove" and e.get("step") is None
               and _int(e.get("id")) == item_id and isinstance(e.get("row"), dict)
               and (want is None or e.get("at") == want)]
        if not evs:
            return {"error": f"nothing dropped as {ids.label("roadmap", item_id)} "
                             "is in the history to put back"}
        row = copy.deepcopy(max(evs, key=lambda e: e.get("at", 0))["row"])
        row["id"] = item_id
        row.pop("shelved", None)
        rows.insert(sum(1 for r in rows if not r.get("shelved")), row)
        _log(d, project, by, {"act": "restored", "id": item_id, "text": row.get("text", ""),
                              **({"steps": len(row.get("steps") or [])}
                                 if row.get("steps") else {})})
        d["projects"][project] = rows
        _touch(d, project, who=who)
        _credit(d, project, who)
        save(d)
    return {"ok": True, "item": row}


def send(project, item_id, step=None, sessions=(), also_told=False, note="", prefix=""):
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
        rows = d["projects"].get(project) or []
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
                return {"error": "every step of this has been sent; "
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
        if not gone(steps[step]) and nxt is not None and step != nxt:
            return {"error": f"step {nxt + 1} has not been sent yet; "
                             "this one is in a group, and the order is the point"}
        # A step arrives on its own otherwise, and "then re-measure it" means
        # nothing without the plan it belongs to. So the line carries all
        # three: that it is one step of several, what the whole thing is for,
        # and which step this is.
        text = (f"This is step {step + 1} of {len(steps)} in a plan "
                f"({ids.label('roadmap', item_id)} on the roadmap). "
                f"The plan: {_flat(row['text'])}. "
                f"Step {step + 1}: {_flat(steps[step]['text'])}")
        if steps[step].get("info"):
            text += f" Details: {_flat(steps[step]['info'])}"
    else:
        text = f"{_flat(row['text'])}  ({ids.label('roadmap', item_id)} on the roadmap)"
        if row.get("info"):
            text += f"  (Details: {_flat(row['info'])})"
    # One message, not two. Saving the list and sending a step both want to
    # say something, and two lines racing into the same input box is how the
    # second one ends up appended to the first. So the note rides along.
    # The operator's own words for this send, if they wrote any. Ahead of the
    # "and the list moved" rider and behind the step itself: it is about this
    # step, where the rider is about everything else.
    note = _flat(_clean(note or "")) if note else ""
    if note:
        text += f"  (From the operator, with this step: {note})"
    extra = changed_line(also_told) if isinstance(also_told, dict) else ""
    line = text + (f"  (Also: {extra[0].lower()}{extra[1:]})" if extra else "")
    # Nothing is switched here any more. The model and effort a project runs
    # on are its own setting, applied by bb-tty as launch flags, so a session
    # that is up is already on them, and a step is just the step. What used to
    # sit here typed /model ahead of it, which stopped working the day claude
    # put a confirmation behind that command: the step went into the dialog.
    # The CALLER's session, not the project's bare one. Every session a node
    # starts is named with the account's prefix (bb-tty's sess()), and the
    # owner's prefix is the empty string, so the bare name is the owner's
    # conversation and nobody else's. Sent without this, a second person's
    # step was typed into the owner's window, or refused as "no session is
    # running here" while their own sat there running (B194).
    session = prefix + claude_session(project)
    r = tell(session, line, sessions)
    if r.get("error") or not r.get("sent"):
        return r
    with _lock:
        d = load()
        rows = d["projects"].get(project) or []
        row = _find(rows, item_id)
        if row is not None:
            target = row["steps"][step] if row.get("steps") else row
            target["sent"] = int(time.time())
            target.pop("by_hand", None)
            # Sending a step a session called done is the operator saying it
            # was not: the mark comes off, and the log shows the send after
            # the finish, which is the whole story.
            target.pop("done", None)
            ev = {"act": "sent", "id": row["id"], "text": target.get("text", "")}
            if row.get("steps"):
                ev.update(step=step, of=row["text"])
            _log(d, project, "you", ev)
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
    "roadmap": "the shared to-do list for this project (`bb roadmap`)",
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
    return (f"{subject} just changed; keep {them} in mind, but carry on with "
            "what you are doing unless I ask for one of those.")


def mark_unsaved(project, kind="roadmap"):
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


def revisions():
    """{project: {kind: how many times it has moved}} for the status poll.

    So an open notebook can tell that somebody else wrote something without
    re-fetching the list every fifteen seconds to find out. It is the same
    trick the Bugs tab has had since it started polling bug_rev, and the
    reason the Roadmap and Memory views were the two that sat there stale
    (roadmap #26).

    The counter is #27's: it moves on every change to either half, whether or
    not a batch is open, which is what a history length cannot say.
    """
    with _lock:
        b = load().get("bump", {})
    return {p: {k: int((v or {}).get(k, 0)) for k in KINDS} for p, v in b.items()}


def stale(project, who, kind="roadmap"):
    """Has this half moved since this seat last saw it?

    What it is for is a session about to write over words it read a while
    ago. A seat nobody has ever recorded answers False: the list went into
    that session's prompt when it started and there is nothing to compare
    against, so refusing would be a guess dressed as a rule.
    """
    if not project or not who:
        return False
    with _lock:
        d = load()
        seat = (d.get("seen", {}).get(project) or {}).get(who)
        now = int((d.get("bump", {}).get(project) or {}).get(kind, 0))
    return isinstance(seat, dict) and now > int(seat.get(kind, 0))


def mark_seen(project, who, kind=None):
    """This seat has now read what is there, silently, saying nothing.

    `catchup` is the other half of the same pair and reports as well as
    records; this one is for the act of READING the list, where there is
    nothing to report because the thing being marked is on screen.
    """
    if not project or not who:
        return
    with _lock:
        d = load()
        b = d.get("bump", {}).get(project) or {}
        seat = d.setdefault("seen", {}).setdefault(project, {}).setdefault(who, {})
        for k in (KINDS if kind is None else [kind]):
            seat[k] = int(b.get(k, 0))
        # When, kept apart from the counters rather than in the seat beside
        # them: `catchup` compares the whole seat against the current numbers
        # to decide whether to write at all, and a timestamp in there would
        # never match, so every prompt of every session would write the file
        # to record that nothing had changed.
        d.setdefault("read", {}).setdefault(project, {})[who] = int(time.time())
        # Reading is the act; recording it is a courtesy. A checkout's bb on
        # a node runs this against a state dir it cannot write (B228), and a
        # traceback over a list that was printed whole is the wrong answer.
        try:
            save(d)
        except OSError:
            pass


def readers(project):
    """{seat: when it last READ this list}, for the panel (roadmap #26).

    The operator's question after changing something is whether the session
    beside them has taken it in yet, and this is the only thing that answers
    it: being TOLD is #27's channel and lands on the session's next prompt,
    but going and reading is an act, and `bb roadmap` is where it happens.
    """
    with _lock:
        return dict(load().get("read", {}).get(project) or {})


def catchup(project, who):
    """What has moved here since THIS session was last told, as one sentence,
    marking it told in the same breath (roadmap #27).

    Read by the UserPromptSubmit hook, so the answer rides into a turn the
    operator was already spending rather than costing one of its own, which
    is the whole difference between this and `announce` below, and the reason
    the panel need not have a button for the ordinary case.

    A session that has never asked is told NOTHING and starts from here: it
    was handed the whole list in its system prompt a moment ago, and reading
    "the roadmap changed" about changes already in front of it is worse than
    silence. So the first ask only records the watermark.

    Writes only when there is something to record. This runs on every prompt
    of every session, and a file written that often for nothing is a cost
    with no answer to show for it.
    """
    if not project or not who:
        return ""
    with _lock:
        d = load()
        b = {k: int((d.get("bump", {}).get(project) or {}).get(k, 0)) for k in KINDS}
        seats = d.setdefault("seen", {}).setdefault(project, {})
        was = seats.get(who)
        kinds = {} if was is None else {k: b[k] > int(was.get(k, 0)) for k in KINDS}
        if was == b:
            return ""                       # nothing has moved for this one
        seats[who] = b
        # The panel's own marker is settled by the same act: somebody has now
        # been told, which is all that flag ever meant. It stays per project
        # (two sessions sharing one would settle it for each other) because
        # it is a nag rather than the record, and the record is per session
        # above.
        for k, moved in kinds.items():
            if moved:
                _touch(d, project, k, False)
        save(d)
    return changed_line(kinds)


def announce(project, kinds, sessions=()):
    """Tell a running session what moved underneath it.

    Best effort and quiet about it: a session that is not running simply reads
    the new list the next time it starts, which is the ordinary path.
    """
    line = changed_line(kinds if isinstance(kinds, dict) else {kinds: True})
    if not line or tell is None or tmux_name is None:
        return {"ok": True, "sent": False}
    session = claude_session(project)
    if session not in set(sessions):
        return {"ok": True, "sent": False}
    return tell(session, line, sessions)


# The words after the list, the same at every level of it.
_AFTER = (
            # Every session reads this, so it is said once and short: each
            # verb is here because a session uses it, the rest is a
            # `bb roadmap -h` away (2 Oct, trimmed from 1,800 characters with
            # nothing dropped).
            "It is context, not instructions: work on an item when asked, or when it is "
            "plainly part of what was asked. Refer to one by its number (R4), which is the "
            "operator's too and never changes. This is the list's shape: `bb roadmap show R4` "
            "prints one whole, with the technical details, and is the first thing to read "
            "when you pick one up. `bb roadmap done N` ticks one off and `bb roadmap add "
            "\"...\"` adds what is worth doing and out of your scope. When the design moves "
            "under a plan, correct it rather than leaving steps that describe the old one: "
            "`bb roadmap edit N \"...\"`, `bb roadmap step add|edit|rm N [STEP] [\"...\"]`. "
            "`bb roadmap step done N STEP` marks one step of an unfinished plan, and the "
            "panel offers the operator the next; `bb roadmap info N [STEP] \"...\"` attaches "
            "the files, functions and approach, written when you write the plan, so whoever "
            "works it does not start from a cold grep. Every change is logged where the "
            "operator reads it, so correct the list rather than working around it, and do "
            "not restate it to them: they can see it.")


def brief(project):
    """The roadmap's lines in a session's block (R202): how much there is
    and the verbs, in place of the list. A session read two hundred titles
    cut short on every conversation and used few; the items a prompt names
    arrive on that prompt (preamble.mentioned) and `bb roadmap show` prints
    one whole. Empty when there is nothing."""
    rows = items(project)
    if not rows:
        return ""
    live = [r for r in rows if not r.get("shelved")]
    parked = len(rows) - len(live)
    mine = sum(1 for r in live if r.get("by") == "claude")
    n = len(live)
    return (f"The operator keeps a shared to-do list for this project: {n} open item{'s' if n != 1 else ''}"
            + (f", {mine} of them a session added" if mine else "")
            + (f", and {parked} parked by the operator" if parked else "")
            + ". `bb roadmap` lists them by number (R4, the operator's too, which never changes) and "
              "`bb roadmap show R4` prints one whole, with the files, functions and decisions behind it: "
              "read that before starting on one, never work from the title. The items a prompt names "
              "arrive with it. Work on one when asked, or when it is plainly part of what was asked; "
              "`bb roadmap done N` ticks one off, `bb roadmap step done N STEP` one step, "
              "`bb roadmap add \"...\"` adds what is worth doing and out of scope, and "
              "`bb roadmap info N [STEP] \"...\"` attaches the files and approach to a plan you write, so "
              "whoever works it does not start from a cold grep. A parked item is the operator's to "
              "unpark: `bb roadmap unshelve N WHY` asks, and nothing is read for or drafted until they "
              "approve. Every change is logged where the operator reads it, so correct the list rather "
              "than working around it, and do not restate it to them.")


def prompt(project):
    """The roadmap's lines in a session's block: `bb roadmap --prompt`."""
    return brief(project)



# ---------------------------------------------------------------------------
# the Roadmap tab's verbs, one call from the dashboard's /api/roadmap

# The bug list whose open batch a batch-close commits beside this one's.
bugs_mod = None
_VERB_PARTS = ("bugs_mod",)


def configure_verbs(**parts):
    """Join what verb() needs from the server (the bug list). Only that
    name: a misspelt one would otherwise overwrite something of this
    module's own."""
    unknown = set(parts) - set(_VERB_PARTS)
    if unknown:
        raise TypeError(f"configure_verbs: nothing called {', '.join(sorted(unknown))}")
    globals().update(parts)


def panel(name, live, prefix):
    """What the panel needs after any change: the list, whether there is
    anywhere to send, and whether a session has been told about it yet.
    `prefix` is the asking account's session prefix (users.tmux_prefix)."""
    # The session THIS ACCOUNT would be sending into, which is the one the
    # arrows have to answer for: every session a node starts wears the
    # account's prefix, and the owner's prefix is empty (B194). Read with
    # the bare name, a second person's arrows said "no Claude session is
    # running here" with their own session open in the next tab.
    session = prefix + claude_session(name)
    return {"items": items(name),
            # How many are finished, for the toggle's label (R78): the
            # items themselves come when it is pressed.
            "finished_n": len(finished(name)),
            # What a time of doing shipped in, for the rows' facts (R254).
            "releases": releases(name),
            # ...and what the changelog says about each item (R254 step 4).
            "changelog": changelog_refs(name, "R"),
            # What the poll compares against, handed back with every read
            # AND every write, so this panel's own change never reads as
            # somebody else's on the next poll, and a change that lands
            # between opening the tab and the first poll is not missed
            # (roadmap #26).
            "rev": (revisions().get(name) or {}).get("roadmap", 0),
            "session": session if session in set(live) else None,
            "unsaved": unsaved(name),
            # A session part-way through a batch. The panel refuses to save
            # over one: the list on screen is a copy taken before the
            # session started, and replaying edits onto a list that has
            # moved underneath is how two people writing one file lose
            # each other's work.
            "batch": batch(name)}


def verb(name, act, req, me, *, live, prefix):
    """One change to a project's list from the Roadmap tab or `bb roadmap`
    (add, send, edit, move, the details, a step, cross, remove, restore,
    shelve, a stale batch closed, the panel's Save) or one of its reads
    (the finished items, the history), once server.py has let this account
    work on the project. (payload, status); a change answers with panel(),
    so nothing on screen is stale. `live` is every session running, and
    `prefix` the asking account's session prefix."""
    # What the caller believes it is replacing, for the verbs that
    # replace something (roadmap #26). A field's own words rather than a
    # version for the row: a session attaching details while the operator
    # rewords the same line is not a conflict. Absent from a client that
    # has not been taught to send it, which is then unchecked.
    was = req.get("was")
    # And who is writing, but only when a SESSION is: its own change must
    # not come back to it as news on its next prompt (#27's watermark),
    # while the operator's must, which is the whole point of that channel.
    # A browser's cookie names the same account and is deliberately not
    # credited.
    who = me.get("uid", "") if me.get("session") else ""
    if act == "batch-close":
        # A batch its session will never close: killed mid-way, or the
        # container restarted under it (B198). The only way out was a
        # shell running `bb roadmap commit`, which a user account does
        # not have. Committed rather than reverted: what the session
        # wrote is already on the list in front of everybody, and folding
        # its log in loses nothing, where a revert would take work away
        # on the say-so of somebody who did not do it. An
        # administrator's, like the other decisions about other
        # people's work: the server asks that before this.
        closed = 0
        for batch_of, commit_of in ((batch, commit), (bugs_mod.batch, bugs_mod.commit)):
            if batch_of(name) is not None:
                r = commit_of(name)
                if r.get("error"):
                    return r, 400
                closed += 1
        return {"ok": True, "closed": closed} | panel(name, live, prefix), 200
    if act == "save":
        # The panel's one Save: settle the marker, say nothing. A session
        # is told by itself, on the next prompt it is given (roadmap #27),
        # so the panel has one button and this has one action: nothing
        # here types the change into a running session.
        # `announce` is still live: the send path below carries
        # the same line on a message that was going anyway.
        mark_told(name)
        return {"ok": True} | panel(name, live, prefix), 200
    if act == "add":
        r = add(name, field(req, "text"), steps=field_list(req, "steps"), who=who)
    elif act == "send":
        r = send(name, req.get("id"), req.get("step"), live,
                 also_told=unsaved(name) if req.get("tell") else False,
                 note=field(req, "note"), prefix=prefix)
        if r.get("sent") and req.get("tell"):
            mark_told(name)
    elif act == "edit":
        r = edit(name, req.get("id"), field(req, "text"), req.get("step"),
                 was=was, who=who)
    elif act == "move":
        r = move(name, req.get("id"), req.get("step"), req.get("dir"))
    elif act == "info":
        r = set_info(name, req.get("id"), field(req, "text"),
                     step=req.get("step"), was=was, who=who)
    elif act == "add-step":
        r = add_step(name, req.get("id"), field(req, "text"))
    elif act == "cross":
        r = cross(name, req.get("id"), req.get("step"), bool(req.get("on", True)))
    elif act == "remove":
        r = remove(name, req.get("id"), req.get("step"),
                   why=field(req, "why"), was=was, who=who)
    elif act == "restore":
        r = restore(name, req.get("id"), at=req.get("at"), who=who)
    elif act == "reopen":
        r = reopen(name, req.get("id"), who=who)
    elif act == "done":
        # Ticked off from its row by a person (R254 step 2, the operator,
        # 16 Oct): the roadmap is theirs, and work finishes outside a
        # session or stops mattering. Logged as theirs; Reopen undoes it
        # until a release ships it. A session ticks off through bb as before.
        r = tick(name, req.get("id"), by="claude" if me.get("session") else "you", who=who)
    elif act == "shelve":
        # One direction for a session, the way `bb roadmap shelve` is on
        # the command line: parking something is a thing a session knows
        # (it is blocked, it is waiting on somebody, the design moved
        # under it) and it is loud, with the row dark at the foot of the
        # list and the log saying who did it. Taking one OFF reverses a
        # decision the operator made for reasons the session was not told,
        # so it is theirs. The CLI only ever passed on=True; this door
        # took whatever it was handed.
        # A session asking for one back is held for a person on the
        # project (R78): roadmap.shelve holds it with its reason.
        on = bool(req.get("on", True))
        r = shelve(name, req.get("id"), on,
                   by="claude" if me.get("session") else "you", who=who,
                   why=field(req, "why"))
        if r.get("held"):
            return r | panel(name, live, prefix), 200
    elif act == "finished":
        # The ticked-off items, with their plans, for the Roadmap tab's
        # toggle (R78): fetched when it is turned on, never in the poll.
        return {"finished": finished(name, limit=req.get("limit"))}, 200
    elif act == "history":
        # Fetched only when the panel is showing it. It rides in no poll:
        # a log nobody has opened is bytes on every status request for
        # every project, forever. Narrowed server-side for the same
        # reason: the panel asks for a window, not for everything.
        return {"history": history(
            name, limit=req.get("limit"), since=req.get("since"),
            find=field(req, "find"))}, 200
    else:
        return {"error": f"unknown action: {act}"}, 400
    if r.get("error"):
        # A conflict answers 200. Not because it is a success (the write
        # was refused) but because the only client is this page, which
        # branches on `conflict` before `error`, and a 4xx here would put
        # "Failed to load resource" in the browser console for an outcome
        # the page handles. The suite holds every tab to zero console
        # errors, and that rule is worth more than the status code.
        # It answers with the item as it now stands so the panel can show
        # both, and with the fresh list so nothing else on screen is stale.
        if r.get("conflict"):
            return r | panel(name, live, prefix), 200
        return r, 400
    return r | panel(name, live, prefix), 200
