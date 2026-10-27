"""Behind `bb roadmap` (cmd_roadmap in bb): the shared to-do list from a
session's side, read and written through dashboard/roadmap.py, the module
the dashboard writes it with, so a list edited from a phone and a list
edited from a terminal cannot disagree.

Arguments: roadmap.py's path, the project, then the words of the verb
(list, show N, add TEXT, edit, done, rm, restore, shelve, mv, step, info,
target, begin, commit, revert, pending, history). DASHBOARD_STATE says where the
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
# `--format json|yaml|markdown` or `--json` on a list or a show (R167): the
# records whole, from records.py, in place of the text printed here.
fmt, argv = dash.format_flag(argv)
op = argv[0] if argv else "list"
rest = argv[1:]
records = dash.load("records", _here)


def dump_records(rows, as_of=None):
    sys.stdout.write(records.dump(records.document("roadmap", rows, proj, as_of=as_of), fmt))


def as_of_now():
    return (roadmap.revisions().get(proj) or {}).get("roadmap", 0)

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


def show(target=None):
    rows = roadmap.items(proj)
    # `bb roadmap --target 0.6.0`: the items meant for one release, and
    # `--target none` the ones meant for none yet.
    # An item is for a release by its own target or by any step's (R108).
    want = None if target is None else (target.lstrip("vV") if target.lower() != "none" else "")
    if target is not None:
        rows = [r for r in rows if roadmap.for_release(r, want)] if want else [r for r in rows if not r.get("target")]
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
              + (f"  [for {r['target']}]" if r.get("target") else "")
              + ("  [shelved]" if r.get("shelved") else ""))
        if r.get("info"):
            print("       details: " + r["info"].replace("\n", "\n                "))
        for i, st in enumerate(r.get("steps") or []):
            print(f"          {i + 1}. {st['text']}"
                  + (f"  [for {st['target']}]" if st.get("target") else "")
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


if op in ("list", "ls", "--target"):
    if op == "--target" or "--target" in rest:
        at = rest if op == "--target" else rest[rest.index("--target") + 1:]
        if not at:
            print("usage: bb roadmap --target X.Y.Z|none", file=sys.stderr); sys.exit(1)
        if fmt != "text":
            want = at[0].lstrip("vV") if at[0].lower() != "none" else ""
            rows = roadmap.items(proj)
            dump_records([r for r in rows if roadmap.for_release(r, want)] if want else [r for r in rows if not r.get("target")], as_of_now())
        else:
            show(at[0])
    elif fmt != "text":
        dump_records(roadmap.items(proj), as_of_now())
    else:
        show()
    # Read, so what arrives on the next prompt is what has moved SINCE this,
    # and so the guard above stops holding a session that has just looked.
    roadmap.mark_seen(proj, _who, "roadmap")
elif op == "show":
    # One item in full: its details, its steps and theirs. `list` cannot carry
    # this without becoming unreadable, and a session working item N wants
    # exactly N, the same reason `bb bug show` exists.
    if not rest:
        print("usage: bb roadmap show <n>[.<step>] [<step>]", file=sys.stderr); sys.exit(1)
    # One step by the number it was first given (R168): `show R56.9` or
    # `show R56 9` finds it wherever it is now, moved, split away or not.
    head, _, dot = rest[0].partition(".")
    stepno = dot or (rest[1] if len(rest) > 1 and rest[1].isdigit() else "")
    if stepno:
        n = ident(head)
        got = roadmap.resolve(proj, n, int(stepno)); bail(got)
        it, i = got["item"], got["index"]
        where = (f"{R(it['id'])} step {i + 1}" if i >= 0 else R(it["id"])) + (" (finished)" if got["where"] == "finished" else "")
        print(f"  {R(n)} step {stepno} is {where}" + (": moved there" if got["moved"] else "") if int(stepno) or got["moved"]
              else f"  {R(n)} is on the list")
        st = it["steps"][i] if i >= 0 else it
        print(f"    {st['text']}" + (f"  [for {st['target']}]" if st.get("target") else "")
              + ("  (done)" if st.get("done") else "  (sent)" if st.get("sent") else ""))
        if st.get("info"):
            print("       details: " + st["info"].replace("\n", "\n                "))
        sys.exit(0)
    n = ident(rest[0])
    r = next((x for x in roadmap.items(proj) if x.get("id") == n), None)
    # A finished item is shown as the Finished section shows it (B766):
    # finished is how it reads, not a door that shuts on it.
    if r is None:
        r = next((x for x in roadmap.finished(proj) if x.get("id") == n), None)
    if r is None:
        print(f"[builderbot] ERROR: no item {R(n)} here", file=sys.stderr)
        sys.exit(1)
    if fmt != "text":
        dump_records([r], as_of_now())
        roadmap.mark_seen(proj, _who, "roadmap")
        sys.exit(0)
    who = " (claude)" if r.get("by") == "claude" else ""
    when = time.strftime("%d %b", time.localtime(r["done_at"])) if r.get("done_at") else ""
    print(f"  {R(r['id'])}  {r['text']}{who}"
          + (f"  [for {r['target']}]" if r.get("target") else "")
          + ("  [shelved]" if r.get("shelved") else "")
          + (f"  [finished {when}]" if r.get("done_at") else ""))
    if r.get("info"):
        print("  details: " + r["info"].replace("\n", "\n           "))
    for i, st in enumerate(r.get("steps") or []):
        # A step from another item says so (R168): the number it answers
        # to there is its sid's.
        sid = st.get("sid") if isinstance(st.get("sid"), list) and len(st["sid"]) == 2 else None
        came = (f"  (was {R(sid[0])} step {sid[1]})" if sid and sid[1] else f"  (was {R(sid[0])}, folded in)") if sid and sid[0] != r["id"] else ""
        print(f"    {i + 1}. {st['text']}"
              + (f"  [for {st['target']}]" if st.get("target") else "")
              + ("  (done)" if st.get("done") else "  (sent)" if st.get("sent") else "") + came)
        if st.get("info"):
            print("       details: " + st["info"].replace("\n", "\n                "))
    # ...and where each step that left went (R168), with its place now.
    for m in r.get("moved") or []:
        got = roadmap.resolve(proj, m["sid"][0], m["sid"][1]) if isinstance(m.get("sid"), list) else {}
        now = (f"{R(got['item']['id'])} step {got['index'] + 1}" if got.get("item") and got.get("index", -1) >= 0
               else R(m.get("to")))
        own = f"step {m['sid'][1]}" if m["sid"][0] == r["id"] else f"{R(m['sid'][0])} step {m['sid'][1]}, then step {m.get('n')} here"
        print(f"    moved: {own} went to {now}")
    roadmap.mark_seen(proj, _who, "roadmap")
elif op == "--prompt":
    sys.stdout.write(roadmap.prompt(proj))
elif op == "add" and "--from" in rest:
    # Records from a file (R167): `bb roadmap add --from FILE` (or `-` for
    # stdin) adds each as one item with its steps, details and target, in
    # any of the formats bb prints; a record's id is ignored, since a new
    # item takes the next number.
    src = rest[rest.index("--from") + 1] if rest.index("--from") + 1 < len(rest) else ""
    if not src:
        print("[builderbot] ERROR: --from needs the file after it, or - for stdin", file=sys.stderr); sys.exit(1)
    try:
        doc = records.load(sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read())
    except (OSError, ValueError) as e:
        print(f"[builderbot] ERROR: {src}: {e}", file=sys.stderr); sys.exit(1)
    if doc.get("kind") not in (None, "roadmap"):
        print(f"[builderbot] ERROR: {src} holds {doc['kind']} records, not roadmap items", file=sys.stderr); sys.exit(1)
    for rec in doc.get("records") or []:
        steps = [str(st.get("text") or "") for st in (rec.get("steps") or []) if isinstance(st, dict)]
        r = roadmap.add(proj, str(rec.get("text") or ""), by="claude", steps=steps, who=_who,
                        target=str(rec.get("target") or "")); bail(r)
        if r.get("held"):
            print(held_line(r)); continue
        nid = r["item"]["id"]
        if rec.get("info"):
            bail(roadmap.set_info(proj, nid, str(rec["info"]), by="claude", who=_who))
        for i, st in enumerate(rec.get("steps") or []):
            if isinstance(st, dict) and st.get("info"):
                bail(roadmap.set_info(proj, nid, str(st["info"]), step=i, by="claude", who=_who))
            if isinstance(st, dict) and st.get("target"):
                bail(roadmap.set_step_target(proj, nid, i, str(st["target"]), by="claude", who=_who))
        print(f"added {R(nid)}: {r['item']['text']}" + (f" ({len(steps)} steps)" if steps else ""))
elif op == "apply":
    # An edited show back (R167): `bb roadmap show N --format yaml > f`,
    # edit, `bb roadmap apply f`. Each record's words, details and target,
    # and each step's by its id, are written where they differ; a step
    # with no id is added; nothing is removed. Refused when the list moved
    # since the document was printed (its as_of), so an edit never lands
    # on words it did not see.
    if not rest:
        print("usage: bb roadmap apply FILE|-", file=sys.stderr); sys.exit(1)
    try:
        doc = records.load(sys.stdin.read() if rest[0] == "-" else open(rest[0], encoding="utf-8").read())
    except (OSError, ValueError) as e:
        print(f"[builderbot] ERROR: {rest[0]}: {e}", file=sys.stderr); sys.exit(1)
    if doc.get("as_of") is not None and int(doc["as_of"]) != int(as_of_now()):
        print("[builderbot] ERROR: the roadmap has changed since this was printed: print it again "
              "(bb roadmap show N --format ...) and make the edit against what it says now", file=sys.stderr)
        sys.exit(2)
    fresh()
    try:
        changes, adds = records.apply_plan(doc, roadmap.items(proj))
    except ValueError as e:
        print(f"[builderbot] ERROR: {e}", file=sys.stderr); sys.exit(1)
    for rid, k, i, v in changes:
        if k == "text":
            r = roadmap.edit(proj, rid, v, step=i, by="claude", who=_who)
        elif k == "info":
            r = roadmap.set_info(proj, rid, v, step=i, by="claude", who=_who)
        else:
            r = (roadmap.set_step_target(proj, rid, i, v, by="claude", who=_who) if i is not None
                 else roadmap.set_target(proj, rid, v, by="claude", who=_who))
        bail(r)
    for rid, text in adds:
        bail(roadmap.add_step(proj, rid, text, by="claude", who=_who))
    print(f"applied: {len(changes)} field{'' if len(changes) == 1 else 's'} changed, {len(adds)} step{'' if len(adds) == 1 else 's'} added")
elif op == "add":
    # `bb roadmap add "title" --step "..." --step "..."`: a change that needs
    # things done in an order is one item with steps, not several items that
    # can be handed over backwards.
    words, steps, target, i = [], [], "", 0
    while i < len(rest):
        if rest[i] == "--target":
            if i + 1 >= len(rest):
                print("[builderbot] ERROR: --target needs the version after it, as 0.6.0",
                      file=sys.stderr)
                sys.exit(1)
            target = rest[i + 1]; i += 2
        elif rest[i] == "--step":
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
                 who=_who, target=target); bail(r)
    if r.get("held"):
        print(held_line(r)); sys.exit(0)
    n = len(r["item"]["steps"])
    print(f"added {R(r['item']['id'])}: {r['item']['text']}"
          + (f" ({n} steps)" if n else "")
          + (f", for {r['item']['target']}" if r["item"].get("target") else ""))
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
elif op == "reopen":
    # A finished item back on the list, steps and details and all: more work
    # found on it is its own step, not a new item naming the old one.
    if not rest:
        print("usage: bb roadmap reopen <n>", file=sys.stderr); sys.exit(1)
    n = ident(rest[0]); fresh()
    r = roadmap.reopen(proj, n, by="claude", who=_who); bail(r)
    print(f"reopened {R(n)}: {r['item']['text']}")
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
elif op == "target":
    # The release an item is meant to ship in (the operator, 21 Oct):
    # `bb roadmap target N 0.6.0`, and `none` takes it off.
    # One step's (R108): `bb roadmap target N.M X.Y.Z` or `target N M X.Y.Z`,
    # and `none` sends the step back to its item's release.
    usage = "usage: bb roadmap target <n>[.<step>] [<step>] X.Y.Z|none"
    if len(rest) < 2:
        print(usage, file=sys.stderr); sys.exit(1)
    head, _, dot = rest[0].partition(".")
    step = dot or (rest[1] if len(rest) > 2 else "")
    if step:
        if not step.isdigit() or len(rest) < (2 if dot else 3):
            print(usage, file=sys.stderr); sys.exit(1)
        n = ident(head)
        v = "" if rest[-1].lower() == "none" else rest[-1]
        if behind(n, None, None, None):
            sys.exit(0)
        r = roadmap.set_step_target(proj, n, int(step) - 1, v, by="claude", who=_who); bail(r)
        st = r["item"]["steps"][int(step) - 1]
        print(f"step {step} of {R(n)} is for {st['target']}" if st.get("target")
              else f"step {step} of {R(n)} goes with its item" + (f" ({r['item']['target']})" if r["item"].get("target") else ""))
        sys.exit(0)
    n = ident(rest[0])
    v = "" if rest[1].lower() == "none" else rest[1]
    if behind(n, "target", {"item_id": n, "version": v, "who": _who},
              f"{R(n)} for {v}" if v else f"{R(n)} with no target"):
        sys.exit(0)
    r = roadmap.set_target(proj, n, v, by="claude", who=_who); bail(r)
    print(f"{R(n)} is for {r['item']['target']}" if r["item"].get("target") else f"{R(n)} has no target")
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
    # `bb roadmap info N M "..."` for step M of it; "" clears. Attached is
    # added to (B817): the text goes in as a new paragraph under what is
    # there, and --replace sets the details outright; replacing them was
    # how a status note wiped four items' details in one pass.
    replace = "--replace" in rest
    rest = [w for w in rest if w != "--replace"]
    if len(rest) < 2:
        print("usage: bb roadmap info <n> [<step>] \"...\" [--replace]", file=sys.stderr)
        sys.exit(1)
    item = ident(rest[0])

    def kept(text, step=None):
        """The details there now, the new text under them."""
        if replace or not text.strip():
            return text
        row = next((x for x in roadmap.items(proj) + roadmap.finished(proj) if x.get("id") == item), None) or {}
        steps = row.get("steps") or []
        old = (steps[step].get("info") if step is not None and 0 <= step < len(steps) else row.get("info")) or ""
        return text if not old.strip() or text in old else f"{old}\n{text}"
    if len(rest) >= 3 and rest[1].isdigit():
        rest = rest[:2] + [kept(" ".join(rest[2:]), int(rest[1]) - 1)]
    else:
        rest = rest[:1] + [kept(" ".join(rest[1:]))]
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
    # `N.M` names a step by its old number (R168), parsed by the verb that
    # takes it; everything else names the item first.
    item = ident(srest[0]) if srest and not ("." in srest[0] and sub in ("mv", "move")) else None
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
        # The steps after it move up a number, said so (B818): a fold that
        # removed one then named the old numbers in nine reasons.
        left = len(next((x.get("steps") or [] for x in roadmap.items(proj) if x.get("id") == item), []))
        gone = step_index(srest[1]) + 1
        print(f"removed step {srest[1]} of {R(item)}" + (
            f"; steps {gone + 1} to {left + 1} are {gone} to {left} now" if left >= gone + 1
            else f"; step {gone + 1} is {gone} now" if left == gone else ""))
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
    elif sub in ("undone", "undo") and len(srest) >= 2:
        # A done mark taken back (the operator, 17 Oct): the wrong step
        # ticked, or one found not finished. See roadmap.step_undone.
        behind(item, None, None, None)
        r = roadmap.step_undone(proj, item, step_index(srest[1]),
                                by="claude", note=" ".join(srest[2:]), who=_who); bail(r)
        print(f"step {srest[1]} of {R(item)} is to do again")
    elif sub in ("mv", "move") and len(srest) >= 3 and srest[2] not in ("up", "down"):
        # To another item (R168): `step mv N M TO [POSITION]`, or `step mv
        # N.M TO`; the step goes whole, and N says where it went.
        to = ident(srest[2])
        pos = srest[3] if len(srest) > 3 and srest[3].isdigit() else None
        behind(item, None, None, None); behind(to, None, None, None); fresh()
        r = roadmap.step_mv(proj, item, step_index(srest[1]), to, position=pos, by="claude", who=_who); bail(r)
        print(f"moved step {srest[1]} of {R(item)} to {R(to)}, its step {r['step'] + 1}; "
              f"bb roadmap show {R(item)}.{srest[1]} still finds it")
    elif sub in ("mv", "move") and len(srest) >= 2 and "." in srest[0]:
        head, _, dot = srest[0].partition(".")
        item, to = ident(head), ident(srest[1])
        pos = srest[2] if len(srest) > 2 and srest[2].isdigit() else None
        behind(item, None, None, None); behind(to, None, None, None); fresh()
        r = roadmap.step_mv(proj, item, step_index(dot), to, position=pos, by="claude", who=_who); bail(r)
        print(f"moved step {dot} of {R(item)} to {R(to)}, its step {r['step'] + 1}; "
              f"bb roadmap show {R(item)}.{dot} still finds it")
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
              " | step mv <n> <step> <to> [<position>]"
              " | step done <n> <step> [\"note\"] | step undone <n> <step> [\"why\"]",
              file=sys.stderr)
        sys.exit(1)
elif op == "split":
    # An item's steps into new items, one change (R168): `bb roadmap split
    # N --into "TITLE" 3 4 5 --into "TITLE" 7`; each new item carries
    # those steps whole and points back at N's details. Under the roadmap
    # gate as an add is: a session's may be held.
    if not rest:
        print("usage: bb roadmap split <n> --into \"TITLE\" <step>... [--target X.Y.Z] [--into ...]", file=sys.stderr)
        sys.exit(1)
    n = ident(rest[0]); groups, cur, i = [], None, 1
    while i < len(rest):
        if rest[i] == "--into":
            if i + 1 >= len(rest):
                print("[builderbot] ERROR: --into needs the new item's title after it", file=sys.stderr); sys.exit(1)
            cur = {"text": rest[i + 1], "steps": []}; groups.append(cur); i += 2
        elif rest[i] == "--target" and cur is not None:
            if i + 1 >= len(rest):
                print("[builderbot] ERROR: --target needs the version after it", file=sys.stderr); sys.exit(1)
            cur["target"] = rest[i + 1]; i += 2
        elif cur is not None and rest[i].isdigit():
            cur["steps"].append(int(rest[i])); i += 1
        else:
            print(f"[builderbot] ERROR: not a step number or --into: {rest[i]!r}", file=sys.stderr); sys.exit(1)
    behind(n, None, None, None); fresh()
    r = roadmap.split(proj, n, groups, by="claude", who=_who); bail(r)
    if r.get("held"):
        print(held_line(r, "the split")); sys.exit(0)
    for made in r["made"]:
        print(f"added {R(made['id'])}: {made['text']} ({len(made['steps'])} steps)")
    left = len(r["item"].get("steps") or [])
    print(f"{R(n)} keeps {left} step{'' if left == 1 else 's'} and says where each went; "
          f"bb roadmap show {R(n)}.N finds a step by its old number")
elif op == "fold":
    # One item into another (R168): `bb roadmap fold N INTO M` makes N a
    # step of M, its steps following; `fold N INTO M.K` adds N's words to
    # step K's details and puts its steps after it. N leaves the list with
    # where it went, and restore brings it back.
    if len(rest) < 3 or rest[1].upper() != "INTO":
        print("usage: bb roadmap fold <n> INTO <m>[.<step>] [\"why\"]", file=sys.stderr); sys.exit(1)
    n = ident(rest[0]); head, _, dot = rest[2].partition("."); m = ident(head)
    behind(n, None, None, None); behind(m, None, None, None); fresh()
    r = roadmap.fold(proj, n, m, into_step=(int(dot) - 1 if dot.isdigit() and int(dot) >= 1 else None),
                     by="claude", who=_who, why=" ".join(rest[3:])); bail(r)
    print(f"folded {R(n)} into {R(m)} step {r['folded'][1]}; bb roadmap restore {R(n)} undoes it")
elif op == "refs":
    # The list's own words checked (R168): every R number and step they
    # name that no longer finds anything, and a moved one's place now.
    rs = roadmap.refs(proj)
    bad = [x for x in rs if not x.get("moved")]
    for x in rs:
        print(f"  {x['where']:<22} {x['ref']:<14} {x['why']}")
    if not rs:
        print(f"every reference on {proj}'s list finds what it names")
    elif bad:
        print(f"{len(bad)} reference{'' if len(bad) == 1 else 's'} find{'s' if len(bad) == 1 else ''} nothing: reword the lines that carry them", file=sys.stderr)
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
    # `bb bug note` has a twin here under another name; a session reaching
    # for it met the whole usage line (MediaReducer, 7 Oct).
    if op == "note":
        print("[builderbot] ERROR: a roadmap item's notes are its details: "
              "bb roadmap info N [STEP] TEXT", file=sys.stderr)
        sys.exit(1)
    print("usage: bb roadmap [list|show N|add TEXT [--step ...]|edit N TEXT|"
          "info N [M] TEXT|step add|edit|rm|mv|done|undone|info ...|mv N up|down|done N|"
          "rm N [WHY]|restore N|reopen N|shelve N|unshelve N [WHY]|begin|commit|revert|pending|"
          "history [-n N] [--since D] [--find TEXT]]",
          file=sys.stderr)
    sys.exit(1)
