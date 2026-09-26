"""Behind `bb roadmap` (cmd_roadmap in bb): the shared to-do list from a
session's side, read and written through dashboard/roadmap.py, the module
the dashboard writes it with, so a list edited from a phone and a list
edited from a terminal cannot disagree.

Arguments: roadmap.py's path, the project, then the words of the verb
(list, show N, add TEXT, edit, done, rm, restore, shelve, mv, step, info,
begin, commit, revert, pending, history). DASHBOARD_STATE says where the
notebook's files are and BB_ACCOUNT_UID which seat this session sits in.
"""
import os
import sys
import time

import dash

_here = dash.beside(sys.argv[1])
roadmap = dash.load("roadmap", _here)
write_json = dash.statefile(_here).write_json
_state = os.environ.get("DASHBOARD_STATE", "/config")
roadmap.configure(write_json=write_json, state=_state, actor=lambda: dash.account_name(_state))

# The tracker's half of a notebook batch. A batch spans both files, so the
# roadmap's begin/commit/revert have to reach the tracker as well; loaded
# beside roadmap.py rather than imported, for the same reason roadmap.py is: this
_bugs = dash.load("bugs", _here)
_bugs.configure(write_json=write_json, state=_state, actor=lambda: dash.account_name(_state))
_nb = dash.load("notebook", _here)
_nb.configure(roadmap_mod=roadmap, bugs_mod=_bugs)

proj, argv = sys.argv[2], sys.argv[3:]
op = argv[0] if argv else "list"
rest = argv[1:]

# roadmap.py put its own directory on sys.path, so the id module beside it is
# importable here the way it is inside the dashboard, and the approval
# queue (roadmap #27), which roadmap.configure already set up.
import ids  # noqa: E402
import pending  # noqa: E402


def held_line(r, what="it"):
    """What a session is told when its add was held for the operator."""
    h = r["held"]
    tag = R(h["number"]) if h.get("number") is not None else "it"
    return (f"held for approval as {tag}; {what} lands on the roadmap when the "
            "operator approves it on the notebook. `bb roadmap pending` lists "
            "what is waiting; you are told on a later turn what they decided")


def behind(n, verb, args, summary):
    """A follow-up aimed at a number that is still waiting for approval.

    info, step add and edit ride behind the held add and land after it;
    anything else on a held item is refused, because there is nothing to
    tick, drop or move yet. Returns True when the call was dealt with here.
    """
    rec = pending.held(proj, "roadmap", n)
    if rec is None:
        return False
    if verb is None:
        print(f"[builderbot] ERROR: {R(n)} is still waiting for the operator's "
              "approval; there is nothing to change yet. `bb roadmap pending`",
              file=sys.stderr)
        sys.exit(1)
    r = pending.hold(proj, "roadmap", verb, args, summary, number=n, after=rec["id"])
    bail(r)
    print(f"held behind {R(n)}: it lands with that item when the operator "
          "approves it, and goes if they deny it")
    return True


def R(n):
    return ids.label("roadmap", n) if n is not None else ""


def ident(word):
    """The item a verb was given, checked before anything is looked up.

    `bb roadmap done 12` and `bb roadmap done R12` both work; `bb roadmap
    done B12` stops here with a sentence saying B12 is a bug: the letter is
    a check, not decoration (ids.py). The number goes on as an int so every
    module call and every message below prints it the same way.
    """
    n, err = ids.parse("roadmap", word)
    if err:
        print(f"[builderbot] ERROR: {err}", file=sys.stderr)
        sys.exit(1)
    if n is None:
        print(f"[builderbot] ERROR: not a roadmap item: {word!r}; they are "
              "numbered R1, R2, ...", file=sys.stderr)
        sys.exit(1)
    return n


def show():
    rows = roadmap.items(proj)
    # The whole notebook's count, not the roadmap's: one batch covers both,
    # and a banner reporting half of it would read as "nothing much staged"
    # while a dozen tracker changes sat unrecorded.
    b = _nb.state(proj)
    if b:
        print(f"  [batch open: {b['changes']} change"
              f"{'' if b['changes'] == 1 else 's'} unrecorded across this "
              "notebook; bb roadmap commit, or revert]")
    if not rows:
        print(f"nothing on {proj}'s list")
        return
    for r in rows:
        # No done column: everything here is outstanding by construction, and
        # a box that is never ticked is a column of nothing. Shelved is worth
        # a column, because it is the one state that changes whether a line is
        # asking for anything.
        who = " (claude)" if r.get("by") == "claude" else ""
        mark = "~" if r.get("shelved") else " "
        print(f" {mark}{R(r['id']):>4}  {r['text']}{who}"
              + ("  [shelved]" if r.get("shelved") else ""))
        if r.get("info"):
            print("       details: " + r["info"].replace("\n", "\n                "))
        for i, st in enumerate(r.get("steps") or []):
            print(f"          {i + 1}. {st['text']}"
                  + ("  (done)" if st.get("done") else "  (sent)" if st.get("sent") else ""))
            if st.get("info"):
                print("             details: "
                      + st["info"].replace("\n", "\n                      "))


def bail(r):
    if r.get("error"):
        print(f"[builderbot] ERROR: {r['error']}", file=sys.stderr)
        sys.exit(1)


# Which seat this session sits in, for the two questions roadmap #26 and #27
# both need answered: has this list moved since I last looked at it, and was
# it me who moved it. Empty for a bb run from a plain shell, which then does
# no check, because there is nothing to check against.
_who = os.environ.get("BB_ACCOUNT_UID", "")


def fresh():
    """Refuse to write over words this session has not read.

    The exposure is not two writes landing at once; those are per field and
    under a lock. It is that a session read the roadmap when it started, the
    operator reworded an item an hour later, and the session then rewrites
    that item from the copy in its context. Nothing tells either of them.

    So: if the list has moved since this session was last told about it,
    say so and stop. There is no --force, deliberately. Re-reading is one
    command and clears the block, which makes the honest path the short one;
    a flag would make the dishonest path shorter.
    """
    if roadmap.stale(proj, _who):
        print("[builderbot] ERROR: the roadmap has changed since you last read "
              "it; run `bb roadmap` and make this change against what it says "
              "now", file=sys.stderr)
        sys.exit(2)


if op in ("list", "ls"):
    show()
    # Read, so what arrives on the next prompt is what has moved SINCE this,
    # and so the guard above stops holding a session that has just looked.
    roadmap.mark_seen(proj, _who, "roadmap")
elif op == "show":
    # One item in full: its details, its steps and theirs. `list` cannot carry
    # this without becoming unreadable, and a session working item N wants
    # exactly N, the same reason `bb bug show` exists.
    if not rest:
        print("usage: bb roadmap show <n>", file=sys.stderr); sys.exit(1)
    n = ident(rest[0])
    r = next((x for x in roadmap.items(proj) if x.get("id") == n), None)
    if r is None:
        print(f"[builderbot] ERROR: no item {R(n)} here", file=sys.stderr)
        sys.exit(1)
    who = " (claude)" if r.get("by") == "claude" else ""
    print(f"  {R(r['id'])}  {r['text']}{who}"
          + ("  [shelved]" if r.get("shelved") else ""))
    if r.get("info"):
        print("  details: " + r["info"].replace("\n", "\n           "))
    for i, st in enumerate(r.get("steps") or []):
        print(f"    {i + 1}. {st['text']}"
              + ("  (done)" if st.get("done") else "  (sent)" if st.get("sent") else ""))
        if st.get("info"):
            print("       details: " + st["info"].replace("\n", "\n                "))
    roadmap.mark_seen(proj, _who, "roadmap")
elif op == "--prompt":
    sys.stdout.write(roadmap.prompt(proj))
elif op == "add":
    # `bb roadmap add "title" --step "..." --step "..."`: a change that needs
    # things done in an order is one item with steps, not several items that
    # can be handed over backwards.
    words, steps, i = [], [], 0
    while i < len(rest):
        if rest[i] == "--step":
            # A dangling --step used to fall through and become part of the
            # title, so `bb roadmap add "x" --step` quietly made an item called
            # "x --step" instead of saying what was missing.
            if i + 1 >= len(rest):
                print("[builderbot] ERROR: --step needs the step after it",
                      file=sys.stderr)
                sys.exit(1)
            steps.append(rest[i + 1]); i += 2
        else:
            words.append(rest[i]); i += 1
    r = roadmap.add(proj, " ".join(words).strip(), by="claude", steps=steps,
                 who=_who); bail(r)
    if r.get("held"):
        print(held_line(r)); sys.exit(0)
    n = len(r["item"]["steps"])
    print(f"added {R(r['item']['id'])}: {r['item']['text']}"
          + (f" ({n} steps)" if n else ""))
elif op == "done":
    # Off the list and into the log. There is no undoing it: a list is read to
    # find out what is left, so nothing finished stays on it, and the history
    # is where the words live afterwards.
    if not rest:
        print("usage: bb roadmap done <n>", file=sys.stderr); sys.exit(1)
    n = ident(rest[0]); behind(n, None, None, None); fresh()
    r = roadmap.tick(proj, n, by="claude", who=_who); bail(r)
    print(f"done {R(n)}: {r['item']['text']}")
elif op in ("rm", "remove"):
    # For work that is abandoned. A finished plan is ticked, not dropped.
    # The reason rides with the deletion: the row can be put back from the
    # history (`restore`, or the panel's Put back), and a note saying why it
    # went is what stops that happening by mistake.
    if not rest:
        print("usage: bb roadmap rm <n> [\"why it is going\"]", file=sys.stderr); sys.exit(1)
    n = ident(rest[0]); behind(n, None, None, None); fresh()
    r = roadmap.remove(proj, n, by="claude", why=" ".join(rest[1:]),
                    who=_who); bail(r)
    print(f"removed {R(n)}; bb roadmap restore {R(n)} puts it back")
elif op == "restore":
    # The other half of rm: the dropped row comes back from the history as it
    # was, steps and details and all, under its own number.
    if not rest:
        print("usage: bb roadmap restore <n>", file=sys.stderr); sys.exit(1)
    n = ident(rest[0]); fresh()
    r = roadmap.restore(proj, n, by="claude", who=_who); bail(r)
    print(f"put back {R(n)}: {r['item']['text']}")
elif op in ("begin", "commit", "revert"):
    # Working something out is not a series of decisions the operator has to
    # read; it is arriving at one. The work still lands as it happens (hiding
    # it would be worse than a noisy log), but the record is written once, at
    # commit, saying what changed rather than every step of getting there.
    #
    # One batch over the WHOLE notebook: the roadmap and the tracker both.
    # A plan usually moves because of what the tracker now says, and letting
    # one be committed while the other is reverted would leave a roadmap
    # describing work against a tracker that never recorded why.
    if op == "begin":
        bail(_nb.begin(proj))
        print(f"batch open on {proj}'s notebook: the roadmap and the bug "
              "tracker both. Commit or revert it")
    elif op == "commit":
        r = _nb.commit(proj); bail(r)
        print(f"committed: {r['written']} entr{'y' if r['written'] == 1 else 'ies'}"
              + (f", {r['folded']} folded into them" if r["folded"] else ""))
    else:
        r = _nb.revert(proj); bail(r)
        print(f"reverted: the roadmap and the tracker are back as they were, "
              f"{r['dropped']} change{'' if r['dropped'] == 1 else 's'} dropped")
elif op in ("mv", "move"):
    # The list's own order, not a group's. Both halves of restructuring belong
    # to a session: it is the one that knows a plan has to happen before the
    # item under it, and deleting and retyping to express that loses the words
    # and the record both.
    if len(rest) < 2 or rest[1] not in ("up", "down"):
        print("usage: bb roadmap mv <n> up|down", file=sys.stderr); sys.exit(1)
    n = ident(rest[0]); behind(n, None, None, None)
    r = roadmap.move(proj, n, dir=-1 if rest[1] == "up" else 1, by="claude",
                  who=_who)
    bail(r)
    print(f"moved {R(n)} {rest[1]}")
elif op == "shelve":
    # Parked, not dropped: a reason to keep it, no intention of doing it now.
    # One direction only. Putting something on the shelf is a thing a session
    # knows (it is blocked, or it is waiting on somebody) and it is loud:
    # the row goes dark at the bottom and the log says who did it. Taking one
    # *off* is reversing a decision the operator made for reasons the session
    # was not told, so it is theirs, and one tap in the panel.
    if not rest:
        print("usage: bb roadmap shelve <n>", file=sys.stderr); sys.exit(1)
    n = ident(rest[0]); behind(n, None, None, None)
    r = roadmap.shelve(proj, n, True, by="claude", who=_who); bail(r)
    print(f"shelved {R(n)}; say in your reply why. `bb roadmap unshelve {R(n)} WHY` asks for it back")
elif op == "unshelve":
    # The other direction is a request, not a change (R78): taking one off
    # the shelf reverses a decision the operator made for reasons the session
    # was not told, so it is held with the reason for a person on the
    # project, whatever the gate says, and lands when they approve it.
    if not rest:
        print("usage: bb roadmap unshelve <n> [WHY]", file=sys.stderr); sys.exit(1)
    n = ident(rest[0])
    r = roadmap.shelve(proj, n, False, by="claude", who=_who,
                       why=" ".join(rest[1:]).strip()); bail(r)
    if r.get("held"):
        print(f"asked to take {R(n)} off the shelf: held for approval on the notebook, "
              "where a person on the project allows or denies it. Carry on with something "
              "else meanwhile")
    else:
        print(f"{R(n)} is off the shelf")
elif op == "edit":
    # A plan written last week can describe a design that has since moved.
    # Correcting it is better than working around it, and the history keeps
    # what it used to say.
    if len(rest) < 2:
        print("usage: bb roadmap edit <n> \"the new wording\"", file=sys.stderr); sys.exit(1)
    n = ident(rest[0])
    if behind(n, "edit", {"item_id": n, "text": " ".join(rest[1:]), "who": _who},
              f"reword {R(n)}: {' '.join(rest[1:])}"):
        sys.exit(0)
    fresh()
    r = roadmap.edit(proj, n, " ".join(rest[1:]), by="claude", who=_who); bail(r)
    print(f"reworded {R(n)}")
elif op == "info":
    # The technical half, attached where the work is: which files, which
    # functions, the approach. `bb roadmap info N "..."` for an item,
    # `bb roadmap info N M "..."` for step M of it; "" clears.
    if len(rest) < 2:
        print("usage: bb roadmap info <n> [<step>] \"...\"", file=sys.stderr)
        sys.exit(1)
    item = ident(rest[0])
    if len(rest) >= 3 and rest[1].isdigit():
        n = int(rest[1])
        if n < 1:
            print("[builderbot] ERROR: step numbers start at 1", file=sys.stderr)
            sys.exit(1)
        if behind(item, "info", {"item_id": item, "text": " ".join(rest[2:]),
                                 "step": n - 1, "who": _who},
                  f"details on step {n} of {R(item)}: {' '.join(rest[2:])}"):
            sys.exit(0)
        fresh()
        r = roadmap.set_info(proj, item, " ".join(rest[2:]),
                          step=n - 1, by="claude", who=_who); bail(r)
        print(f"details on step {rest[1]} of {R(item)}")
    else:
        if behind(item, "info", {"item_id": item, "text": " ".join(rest[1:]), "who": _who},
                  f"details on {R(item)}: {' '.join(rest[1:])}"):
            sys.exit(0)
        fresh()
        r = roadmap.set_info(proj, item, " ".join(rest[1:]), by="claude",
                          who=_who); bail(r)
        print(f"details on {R(item)}")
elif op == "step":
    sub, srest = (rest[0] if rest else ""), rest[1:]

    def step_index(word):
        """A 1-based step number from the command line, as a 0-based index.

        Its own function because the expression it replaces read
        `_int(x) - 1 if _int(x) else None`, and Python's zero is falsy: step 0
        was not "invalid", it was "no step at all", so `step edit N 0 "..."`
        fell through to editing the item and renamed it. Every step verb had
        its own copy of that.
        """
        n = roadmap._int(word)
        if n is None or n < 1:
            print(f"[builderbot] ERROR: step numbers start at 1 (got {word!r})",
                  file=sys.stderr)
            sys.exit(1)
        return n - 1
    item = ident(srest[0]) if srest else None
    if sub == "add" and len(srest) >= 2:
        if behind(item, "step-add", {"item_id": item, "text": " ".join(srest[1:]), "who": _who},
                  f"a step on {R(item)}: {' '.join(srest[1:])}"):
            sys.exit(0)
        r = roadmap.add_step(proj, item, " ".join(srest[1:]), by="claude",
                          who=_who); bail(r)
        print(f"added a step to {R(item)}")
    elif sub == "edit" and len(srest) >= 3:
        # 1-based on the way in, because that is how the step is numbered
        # everywhere a human reads it.
        behind(item, None, None, None); fresh()
        r = roadmap.edit(proj, item, " ".join(srest[2:]),
                      step=step_index(srest[1]),
                      by="claude", who=_who); bail(r)
        print(f"reworded step {srest[1]} of {R(item)}")
    elif sub in ("rm", "remove") and len(srest) >= 2:
        behind(item, None, None, None); fresh()
        r = roadmap.remove(proj, item,
                        step=step_index(srest[1]),
                        by="claude", why=" ".join(srest[2:]), who=_who); bail(r)
        print(f"removed step {srest[1]} of {R(item)}")
    elif sub == "info" and len(srest) >= 2:
        behind(item, None, None, None); fresh()
        r = roadmap.set_info(proj, item, " ".join(srest[2:]),
                          step=step_index(srest[1]),
                          by="claude", who=_who); bail(r)
        print(f"details on step {srest[1]} of {R(item)}")
    elif sub == "done" and len(srest) >= 2:
        # A session's own mark, distinct from the dashboard's "sent": this
        # step is finished, whether or not anybody sent it. See roadmap.step_done.
        behind(item, None, None, None)
        r = roadmap.step_done(proj, item, step_index(srest[1]),
                           by="claude", note=" ".join(srest[2:]), who=_who); bail(r)
        print(f"step {srest[1]} of {R(item)} done"
              + (f", the last one, so {R(item)} is done and off the list"
                 if r.get("finished") else ""))
    elif sub in ("mv", "move") and len(srest) >= 3 and srest[2] in ("up", "down"):
        # The other half of restructuring a plan. Without it a session that
        # finds two steps in the wrong order can only delete and retype them,
        # which loses both their words and the record of what really changed.
        behind(item, None, None, None)
        r = roadmap.move(proj, item,
                      step=step_index(srest[1]),
                      dir=-1 if srest[2] == "up" else 1, by="claude",
                      who=_who); bail(r)
        print(f"moved step {srest[1]} of {R(item)} {srest[2]}")
    else:
        print("usage: bb roadmap step add <n> \"...\" | step edit <n> <step> \"...\""
              " | step rm <n> <step> [\"why\"] | step mv <n> <step> up|down"
              " | step done <n> <step> [\"note\"]",
              file=sys.stderr)
        sys.exit(1)
elif op == "pending":
    # What this project has waiting for the operator (roadmap #27): the
    # roadmap's half. Read-only: approving is theirs, on the notebook.
    rs = pending.listing(proj, "roadmap")
    if not rs:
        print(f"nothing from the roadmap is waiting for approval on {proj}")
    for r in rs:
        when = time.strftime("%d %b %H:%M", time.localtime(r.get("at", 0)))
        tag = R(r["number"]) if r.get("number") is not None else ""
        lead = "  ↳ " if r.get("after") is not None else "  "
        print(f"{lead}{when}  {tag:<5} {r.get('summary', '')}")
    g = pending.mode(proj, "roadmap")
    print(f"  (this project's setting for new roadmap items from a session: {g})")
elif op in ("history", "log"):
    # Narrowed on the way out, not on the way in: this is read by sessions as
    # often as by people, and a whole log pasted into a conversation costs
    # more context than the one line anybody wanted from it.
    limit, since, find, i = 20, None, None, 0
    while i < len(rest):
        a = rest[i]
        if a in ("-n", "--last") and i + 1 < len(rest):
            limit = roadmap._int(rest[i + 1]); i += 2
        elif a == "--all":
            limit = None; i += 1
        elif a == "--since" and i + 1 < len(rest):
            # A day count, or a date. Both are things somebody types from
            # memory; neither needs a library to read.
            v = rest[i + 1]
            n = roadmap._int(v.rstrip("d")) if v.rstrip("d").isdigit() else None
            if n is not None:
                since = int(time.time()) - n * 86400
            else:
                try:
                    since = int(time.mktime(time.strptime(v, "%Y-%m-%d")))
                except ValueError:
                    print(f"[builderbot] ERROR: not a date or a day count: {v}",
                          file=sys.stderr); sys.exit(1)
            i += 2
        elif a in ("--find", "-f") and i + 1 < len(rest):
            find = rest[i + 1]; i += 2
        else:
            print("usage: bb roadmap history [-n N|--all] [--since 7d|YYYY-MM-DD] "
                  "[--find TEXT]", file=sys.stderr)
            sys.exit(1)
    h = roadmap.history(proj, limit=limit, since=since, find=find)
    if not h:
        print(f"nothing on {proj}'s list matches that")
    for e in h:
        when = time.strftime("%d %b %H:%M", time.localtime(e.get("at", 0)))
        where = f" step {e['step'] + 1} of" if e.get("step") is not None else ""
        print(f"  {when}  {dash.wrote(e):>6}  {e.get('act', ''):<11}"
              f"{where} {R(e.get('id'))}  {e.get('text', '')}")
        if e.get("was"):
            print(f"{'':>32}was: {e['was']}")
        if e.get("why"):
            print(f"{'':>32}why: {e['why']}")
        if e.get("approved"):
            print(f"{'':>32}approved by the operator")
else:
    print("usage: bb roadmap [list|show N|add TEXT [--step ...]|edit N TEXT|"
          "info N [M] TEXT|step add|edit|rm|mv|done|info ...|mv N up|down|done N|"
          "rm N [WHY]|restore N|shelve N|unshelve N [WHY]|begin|commit|revert|pending|"
          "history [-n N] [--since D] [--find TEXT]]",
          file=sys.stderr)
    sys.exit(1)
