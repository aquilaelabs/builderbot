#!/usr/bin/env python3
"""One batch across the whole notebook, for a session working something out.

`bb roadmap begin`, then edit the roadmap and the tracker as much as you like,
then `bb roadmap commit` — and each log gets one account of what changed
rather than every step of arriving at it. `revert` puts both back.

**Why it spans both.** A session reworking a plan usually files, notes or
closes bugs in the same breath: the plan moved because of what the tracker now
says. Two independent batches would let one be committed and the other
reverted, leaving a roadmap describing work against a tracker that never
recorded why — and nothing afterwards could notice. So it is one transaction
over the notebook, opened and closed here and nowhere else.

**Deliberately not the panel's model.** There, the thing being edited is on
screen and Save is the commit, so nothing touches disk until it is pressed and
each tab holds its own unsaved work separately. Here the file IS the only way
the operator can see what a session is doing, so changes land as they are
made — visible, watchable — and only the *record* waits for commit.

**The memories are not in it.** A session writes those as files with its own
tools rather than through a module here, so there is no write to intercept and
nothing to put back. Worth stating rather than leaving to be discovered:
`revert` will not undo a memory written while a batch was open.

Each half lives in the module that owns its file, so neither reaches across a
lock it does not hold. This only sequences them, and makes "half a batch" a
state that cannot be reached through the front door.
"""

# Injected rather than imported. The CLI already loads these by path — the
# running image serves them from /opt while a checkout may be the one under
# test — and importing them again here would produce a second copy with its
# own configuration and its own idea of where the state lives.
todo = None
bugs = None


def configure(*, todo_mod, bugs_mod):
    globals().update(todo=todo_mod, bugs=bugs_mod)


def _parts():
    return (("roadmap", todo), ("tracker", bugs))


def begin(project, by="claude"):
    """Open one across both, or open neither.

    The roadmap goes first because its batch is what the dashboard's poll
    reads to hold the panel; if the tracker then refuses, that half is put
    straight back rather than left holding the notebook against a batch the
    session does not think it has.
    """
    r = todo.begin(project, by)
    if r.get("error"):
        return r
    r2 = bugs.begin(project, by)
    if r2.get("error"):
        todo.revert(project)
        return r2
    return {"ok": True}


def state(project):
    """The open batch, or None — both halves' unrecorded changes counted as one.

    `half` is set only when the two have somehow come apart, which the front
    door cannot do; it is there so that if it ever happens the panel and the
    CLI say so instead of quietly reporting the half they happened to ask.
    """
    a, b = todo.batch(project), bugs.batch(project)
    if not a and not b:
        return None
    return {"at": min(x["at"] for x in (a, b) if x),
            "by": (a or b).get("by", ""),
            "changes": (a or {}).get("changes", 0) + (b or {}).get("changes", 0),
            "half": None if (a and b) else ("roadmap" if a else "tracker")}


def commit(project):
    """Write both accounts. Whatever is open is closed, even a stray half."""
    if state(project) is None:
        return {"error": "nothing is open here"}
    written = folded = 0
    for _name, mod in _parts():
        if mod.batch(project) is None:
            continue
        r = mod.commit(project)
        if r.get("error"):
            return r
        written += r.get("written", 0)
        folded += r.get("folded", 0)
    return {"ok": True, "written": written, "folded": folded}


def revert(project):
    """Put both back, or neither.

    Both guards are asked before either file is touched. Reverting the roadmap
    and then discovering the tracker refuses would leave the notebook in a
    state nobody asked for and no command can name — worse than the refusal it
    was trying to honor.
    """
    if state(project) is None:
        return {"error": "nothing is open here"}
    for _name, mod in _parts():
        if mod.batch(project) is None:
            continue
        why = mod.revert_blocked(project)
        if why:
            return {"error": why}
    dropped = 0
    for _name, mod in _parts():
        if mod.batch(project) is None:
            continue
        r = mod.revert(project)
        if r.get("error"):
            return r
        dropped += r.get("dropped", 0)
    return {"ok": True, "dropped": dropped}
