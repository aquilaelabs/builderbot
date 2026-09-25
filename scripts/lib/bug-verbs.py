"""Behind `bb bug` (cmd_bug in bb): the bug tracker's CLI half, the side a
session drives, read and written through dashboard/bugs.py, the module
the dashboard writes it with.

Arguments: bugs.py's path, the project, then the words of the verb
(list, show N, add TEXT, note, fix, close, reopen, rm, begin, commit,
revert, pending, history, ...). DASHBOARD_STATE says where the notebook's
files are, BB_WORKSPACE where the projects are, and BB_ACCOUNT_UID which
seat this session sits in.
"""
import os
import sys
import time

import dash

_here = dash.beside(sys.argv[1])
bugs = dash.load("bugs", _here)
write_json = dash.statefile(_here).write_json
_state = os.environ.get("DASHBOARD_STATE", "/config")
bugs.configure(write_json=write_json, state=_state)

# The roadmap's half of a notebook batch, and the coordinator over the two.
# `bb bug begin` and `bb roadmap begin` are the same command reached from
# either tab's name: one batch covers the notebook, so it would be a lie for
# the tracker to have a private one.
_roadmap = dash.load("roadmap", _here)
_roadmap.configure(write_json=write_json, state=_state, actor=lambda: dash.account_name(_state))
_nb = dash.load("notebook", _here)
_nb.configure(roadmap_mod=_roadmap, bugs_mod=bugs)

proj, argv = sys.argv[2], sys.argv[3:]
op = argv[0] if argv else "list"
rest = argv[1:]

import ids  # noqa: E402 (bugs.py put its directory on sys.path)
import pending  # noqa: E402 (the approval queue, roadmap #27)


def B(n):
    return ids.label("bugs", n) if n is not None else ""


def behind(n, verb, args, summary):
    """A verb aimed at a report that is still waiting for approval: a note
    or a field edit rides behind it, anything else is refused. See the
    roadmap's twin. True when dealt with here."""
    rec = pending.held(proj, "bugs", n)
    if rec is None:
        return False
    if verb is None:
        print(f"[builderbot] ERROR: {B(n)} is still waiting for the operator's "
              "approval; there is nothing to close or drop yet. `bb bug pending`",
              file=sys.stderr)
        sys.exit(1)
    r = pending.hold(proj, "bugs", verb, args, summary, number=n, after=rec["id"])
    bail(r)
    print(f"held behind {B(n)}: it lands with that report when the operator "
          "approves it, and goes if they deny it")
    return True


def ident(word):
    """The bug a verb names, with the letter checked first: `bb bug fix R12`
    stops here saying R12 is a roadmap item. See cmd_roadmap's twin."""
    n, err = ids.parse("bugs", word)
    if err:
        print(f"[builderbot] ERROR: {err}", file=sys.stderr)
        sys.exit(1)
    if n is None:
        print(f"[builderbot] ERROR: not a bug number: {word!r}; they are "
              "B1, B2, ...", file=sys.stderr)
        sys.exit(1)
    return n


def bail(r):
    if r.get("error"):
        print(f"[builderbot] ERROR: {r['error']}", file=sys.stderr)
        sys.exit(1)


def line(b):
    mark = " " if b.get("status") == "open" else "x"
    extra = "" if b.get("status") == "open" else f"  [{b['status']}]"
    return (f"  [{mark}] {B(b['id']):>4}  ({b.get('severity', 'medium')})  "
            f"{b['title']}{extra}")


def show(b):
    print(line(b))
    for k in ("area", "repro", "expected", "actual", "notes"):
        if b.get(k):
            body = b[k].replace("\n", "\n" + " " * 12)
            print(f"  {k:>8}: {body}")
    when = time.strftime("%d %b %H:%M", time.localtime(b.get("at", 0)))
    print(f"  {'by':>8}: {b.get('by', '?')} · {when}"
          + (f" · {b['status']}: {b.get('status_note', '')}"
             if b.get("status") != "open" else ""))
    # The versions (roadmap #6): blank where the report predates the stamp
    # or the tree had nothing honest to say, never a guess.
    if b.get("seen_in") or b.get("seen_on"):
        print(f"  {'seen in':>8}: {b.get('seen_in') or '?'}"
              + (f" · on image {b['seen_on']}" if b.get("seen_on") else ""))
    if b.get("fixed_in"):
        print(f"  {'closed in':>8}: {b['fixed_in']}")


def rows():
    return bugs.payload(proj)["bugs"]


def pull_flags(args):
    """--sev/--area/--repro/--expected/--actual/--notes out of an argv,
    leaving the words that make the title."""
    words, out, i = [], {}, 0
    names = {"--sev": "severity", "--severity": "severity", "--area": "area",
             "--repro": "repro", "--expected": "expected",
             "--actual": "actual", "--notes": "notes"}
    while i < len(args):
        if args[i] in names:
            if i + 1 >= len(args):
                print(f"[builderbot] ERROR: {args[i]} needs a value after it",
                      file=sys.stderr)
                sys.exit(1)
            out[names[args[i]]] = args[i + 1]; i += 2
        else:
            words.append(args[i]); i += 1
    return " ".join(words).strip(), out


if op in ("list", "ls"):
    # Same banner the roadmap's listing carries, for the same batch. A session
    # that opened one on the roadmap and then came here to file something
    # should not have to remember that its notes are unrecorded.
    _b = _nb.state(proj)
    if _b:
        print(f"  [batch open: {_b['changes']} change"
              f"{'' if _b['changes'] == 1 else 's'} unrecorded across this "
              "notebook; bb bug commit, or revert]")
    open_rows = [b for b in rows() if b.get("status") == "open"]
    if not open_rows:
        print(f"no open bugs on {proj}; `bb bug all` includes the closed ones")
    for b in open_rows:
        print(line(b))
elif op == "all":
    if not rows():
        print(f"nothing in {proj}'s bug tracker")
    for b in rows():
        print(line(b))
elif op in ("begin", "commit", "revert"):
    # The same batch `bb roadmap begin` opens: one over the whole notebook,
    # reached from whichever tab's name you happened to be thinking in.
    if op == "begin":
        bail(_nb.begin(proj))
        print(f"batch open on {proj}'s notebook: the bug tracker and the "
              "roadmap both. Commit or revert it")
    elif op == "commit":
        r = _nb.commit(proj); bail(r)
        print(f"committed: {r['written']} entr{'y' if r['written'] == 1 else 'ies'}"
              + (f", {r['folded']} folded into them" if r["folded"] else ""))
    else:
        r = _nb.revert(proj); bail(r)
        print(f"reverted: the tracker and the roadmap are back as they were, "
              f"{r['dropped']} change{'' if r['dropped'] == 1 else 's'} dropped")
elif op in ("find", "search"):
    # Over the bugs themselves, not over the log. `history --find` searches
    # what happened; this searches what is *on file*: the area and the repro
    # above all, which is how you find out whether the thing you just tripped
    # over is already known.
    if not rest:
        print("usage: bb bug find <text>", file=sys.stderr); sys.exit(1)
    needle = " ".join(rest).lower()
    hits = [b for b in rows()
            if any(needle in str(b.get(k, "")).lower()
                   for k in ("title", "area", "repro", "expected", "actual",
                             "notes", "status_note"))]
    if not hits:
        print(f"nothing in {proj}'s tracker mentions that")
    for b in hits:
        print(line(b))
elif op == "show":
    if not rest:
        print("usage: bb bug show <n>", file=sys.stderr); sys.exit(1)
    n = ident(rest[0])
    b = next((x for x in rows() if x.get("id") == n), None)
    if b is None:
        print(f"[builderbot] ERROR: no bug {B(n)} here", file=sys.stderr)
        sys.exit(1)
    show(b)
elif op == "add":
    here = "--here" in rest
    title, flags = pull_flags([a for a in rest if a != "--here"])
    said = " ".join([title] + [str(v) for k, v in flags.items() if k != "severity"])
    # A bug that names BuilderBot, filed in another project's tracker, is
    # usually BuilderBot's, which is what bb report is for. Asked before it is
    # filed rather than said after: said after, a session filed BuilderBot's
    # bug in its own tracker anyway and the operator had to tell it (24 Sep).
    # --here is the answer "it is this project's own". Not where the project
    # has reporting BuilderBot bugs off, BuilderBot's own among them, whose
    # tracker it is.
    import re
    import prefs
    if not here and prefs.get(proj).get("report") != "deny" \
            and re.search(r"\bbuilder ?bot\b|\bbb\b", said, re.I):
        print(f"[builderbot] not filed: this names BuilderBot. A problem with BuilderBot "
              "itself goes to bb report \"what happened\" [--area A] [--repro \"...\"], "
              f"not {proj}'s tracker; if it is {proj}'s own bug, add --here to file it here",
              file=sys.stderr)
        sys.exit(1)
    r = bugs.add(proj, title, by="claude",
                 severity=flags.pop("severity", "medium"), **flags)
    bail(r)
    if r.get("held"):
        h = r["held"]
        print(f"held for approval as {B(h['number'])}: it lands in the tracker "
              "when the operator approves it on the notebook. `bb bug pending` "
              "lists what is waiting; you are told on a later turn what they decided")
        sys.exit(0)
    print(f"filed {B(r['bug']['id'])}: {r['bug']['title']}")
elif op == "note":
    # The everyday update: what a session learned about a bug it did not fix.
    # Appended rather than replacing, because the last analysis is not made
    # wrong by the next one; it is how the next one starts.
    if len(rest) < 2:
        print("usage: bb bug note <n> \"what you learned\"", file=sys.stderr)
        sys.exit(1)
    n = ident(rest[0])
    b = next((x for x in rows() if x.get("id") == n), None)
    stamp = time.strftime("%d %b", time.localtime())
    if b is None:
        # A note on a report that is itself waiting: held behind it, with
        # the note stamped now, because that is when it was learned.
        held_notes = (pending.held(proj, "bugs", n) or {}).get("args", {}).get("notes", "")
        body = (held_notes + f"\n\n[{stamp}] " + " ".join(rest[1:])).strip()
        if behind(n, "edit", {"bug_id": n, "act": "noted", "notes": body},
                  f"note on {B(n)}: {' '.join(rest[1:])}"):
            sys.exit(0)
        print(f"[builderbot] ERROR: no bug {B(n)} here", file=sys.stderr)
        sys.exit(1)
    body = (b.get("notes", "") + f"\n\n[{stamp}] " + " ".join(rest[1:])).strip()
    r = bugs.edit(proj, n, by="claude", act="noted", notes=body); bail(r)
    print(f"noted on {B(n)}")
elif op == "edit":
    if len(rest) < 3 or rest[1] not in ("title", "sev", "severity", "area",
                                        "repro", "expected", "actual", "notes"):
        print("usage: bb bug edit <n> title|sev|area|repro|expected|actual|notes"
              " \"...\"", file=sys.stderr)
        sys.exit(1)
    k = "severity" if rest[1] in ("sev", "severity") else rest[1]
    n = ident(rest[0])
    if behind(n, "edit", {"bug_id": n, k: " ".join(rest[2:])},
              f"{k} on {B(n)}: {' '.join(rest[2:])}"):
        sys.exit(0)
    r = bugs.edit(proj, n, by="claude", **{k: " ".join(rest[2:])})
    bail(r)
    print(f"updated {k} on {B(n)}")
elif op in ("rm", "remove"):
    # For a report that should not exist: mis-filed, a duplicate, the wrong
    # project. A bug that was real and is dealt with gets `fix` or `wontfix`,
    # which keeps it; this does not, and says why in the log.
    if not rest:
        print("usage: bb bug rm <n> [\"why it should not have been filed\"]",
              file=sys.stderr)
        sys.exit(1)
    n = ident(rest[0]); behind(n, None, None, None)
    r = bugs.remove(proj, n, why=" ".join(rest[1:]), by="claude"); bail(r)
    print(f"removed {B(n)}; closing keeps a bug, this does not")
elif op in ("fix", "wontfix", "na", "reopen"):
    if not rest:
        print(f"usage: bb bug {op} <n> [\"note\"]", file=sys.stderr); sys.exit(1)
    status = {"fix": "fixed", "wontfix": "wontfix", "na": "na",
              "reopen": "open"}[op]
    n = ident(rest[0]); behind(n, None, None, None)
    r = bugs.set_status(proj, n, status,
                        note=" ".join(rest[1:]), by="claude")
    bail(r)
    print(f"{B(n)} {status}")
elif op == "pending":
    # The tracker's half of what is waiting for the operator (roadmap #27).
    rs = pending.listing(proj, "bugs")
    if not rs:
        print(f"nothing from the tracker is waiting for approval on {proj}")
    for r in rs:
        when = time.strftime("%d %b %H:%M", time.localtime(r.get("at", 0)))
        tag = B(r["number"]) if r.get("number") is not None else ""
        lead = "  ↳ " if r.get("after") is not None else "  "
        print(f"{lead}{when}  {tag:<5} {r.get('summary', '')}")
    print(f"  (this project's setting for new bug reports from a session: "
          f"{pending.mode(proj, 'bugs')})")
elif op in ("history", "log"):
    # The same filters `bb roadmap history` takes, because whoever learned one
    # should not have to learn the other. `bb history` merges all four.
    limit, since, find, i = 20, None, None, 0
    while i < len(rest):
        a = rest[i]
        if a in ("-n", "--last") and i + 1 < len(rest):
            limit = int(rest[i + 1]); i += 2
        elif a == "--all":
            limit = None; i += 1
        elif a == "--since" and i + 1 < len(rest):
            v = rest[i + 1]
            if v.rstrip("d").isdigit():
                since = int(time.time()) - int(v.rstrip("d")) * 86400
            else:
                try:
                    since = int(time.mktime(time.strptime(v, "%Y-%m-%d")))
                except ValueError:
                    print(f"[builderbot] ERROR: not a date or a day count: {v}",
                          file=sys.stderr)
                    sys.exit(1)
            i += 2
        elif a in ("--find", "-f") and i + 1 < len(rest):
            find = rest[i + 1]; i += 2
        else:
            print("usage: bb bug history [-n N|--all] [--since 7d|YYYY-MM-DD] "
                  "[--find TEXT]", file=sys.stderr)
            sys.exit(1)
    h = bugs.history(proj, limit=limit, since=since, find=find)
    if not h:
        print(f"nothing in {proj}'s tracker matches that")
    for e in h:
        when = time.strftime("%d %b %H:%M", time.localtime(e.get("at", 0)))
        print(f"  {when}  {dash.wrote(e):>6}  {e.get('act', ''):<9}"
              f"  {B(e.get('id'))}  {e.get('text', '')}")
        if e.get("note"):
            print(f"{'':>30}note: {e['note']}")
        if e.get("approved"):
            print(f"{'':>30}approved by the operator")
elif op == "--prompt":
    sys.stdout.write(bugs.prompt(proj))
else:
    print("usage: bb bug [list|all|show N|find TEXT|begin|commit|revert|add TITLE [--sev S] [--area ..] [--here] "
          "[--repro ..]|note N TEXT|edit N FIELD TEXT|fix N [NOTE]|"
          "wontfix N [WHY]|na N [WHY]|reopen N|rm N [WHY]|pending|"
          "history [-n N] [--since D] [--find TEXT]]", file=sys.stderr)
    sys.exit(1)
