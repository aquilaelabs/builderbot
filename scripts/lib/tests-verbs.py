"""Behind `bb tests` (cmd_tests in bb): the test registry, read and written
through dashboard/testreg.py, the module the notebook's Tests tab uses.

Arguments: testreg.py's path, the project, then the words of the verb
(list, show, ingest, describe, flagged, accept, ...). BB_TESTS_FILE is the
run log an ingest reads, as a path; DASHBOARD_STATE says where the
notebook's files are.
"""
import os
import sys

import dash

reg = dash.load("testreg", dash.beside(sys.argv[1]))
statefile = dash.statefile(dash.beside(sys.argv[1]))
reg.configure(write_json=statefile.write_json,
              state=os.environ.get("DASHBOARD_STATE", "/config"))

proj, argv = sys.argv[2], sys.argv[3:]
op = argv[0] if argv else "list"
rest = argv[1:]


def secs(ms):
    return "-" if ms is None else f"{ms / 1000:.1f}s"


def bail(r):
    if r.get("error"):
        print(f"[builderbot] ERROR: {r['error']}", file=sys.stderr)
        sys.exit(1)


if op in ("list", "ls"):
    p = reg.payload(proj)
    if not p["n"]:
        print(f"nothing on {proj}'s test registry; "
              "`bb tests ingest RUNLOG` after a run puts the timings in")
        sys.exit(0)
    print(f"{p['n']} tests · {p['total_ms'] / 1000:.0f}s measured"
          + (f" · last run {p['last_wall_ms'] / 1000:.0f}s of wall"
             if p["last_wall_ms"] else "")
          + (f" · {p['suspect']} flagged ({p['recover_ms'] // 1000}s waiting)"
             if p["suspect"] else "")
          + (f" · {p['undocumented']} undescribed" if p["undocumented"] else ""))
    print("\n  by suite:")
    for s in p["suites"]:
        print(f"   {secs(s['ms']):>8}  {s['suite']:<16} {s['n']:>4} tests"
              + (f"  {s['suspect']} flagged" if s["suspect"] else ""))
    # The slowest, which is what this is opened for. Not the whole roster: a
    # couple of thousand lines is not a thing anybody reads in a terminal.
    n = 20
    if rest and rest[0].lstrip("-").isdigit():
        n = int(rest[0].lstrip("-"))
    print(f"\n  slowest {n}:")
    for t in p["tests"][:n]:
        mark = f"  [{t['suspect']}s wait?]" if t["suspect"] else ""
        print(f"   {secs(t['ms']):>8}  {t['key']:<20} {t['name'][:60]}{mark}")
        if t.get("after"):
            print(f"             follows: {t['after'][:60]}")
elif op == "projection":
    # When a run will finish, from what the last one took, so nobody has
    # to guess, and a run well past it is read as stuck rather than slow.
    # `--secs` is the bare number, for `bb tests run` to hold up against
    # the clock when the run ends.
    p = reg.payload(proj)
    want = [a for a in rest if a != "--secs"]
    if want:
        # A NARROWED run: the projection is the sum of the suites named, not
        # what the whole thing took. Matched on the stem, because that is how
        # a runner is asked for one (`cards`, not `cards.mjs`).
        stems = {w.split("/")[-1].split(".")[0] for w in want}
        picked = [s_ for s_ in p["suites"] if s_["suite"].split(".")[0] in stems]
        wall = sum(s_["ms"] for s_ in picked) / 1000
        n = sum(s_["n"] for s_ in picked)
        took = f"what those {n} tests last measured, in {len(picked)} of {len(p['suites'])} suites"
    else:
        # ...and a whole run is projected from the last WHOLE run. A narrowed
        # one is minutes shorter by design, and taking its wall time as the
        # projection would report the next full run as stuck at the point it
        # was only getting started.
        full = [r for r in p["runs"] if (r.get("suites") or 0) >= len(p["suites"])]
        wall = (full[-1]["wall"] if full else 0) or (
            p["last_wall_ms"] / 1000 if p["last_wall_ms"] else p["total_ms"] / 1000)
        took = (f"what the last whole run took over {p['n']} tests in "
                f"{len(p['suites'])} suites")
    if rest[:1] == ["--secs"] or "--secs" in rest:
        print(f"{wall:.0f}")
    elif not wall:
        print("no projection yet; nothing measured on this project, and this run records the first")
    else:
        print(f"projected {wall:.0f}s, {took}; "
              f"one past {2 * wall:.0f}s is stuck, not slow")

elif op == "show":
    if not rest:
        print("usage: bb tests show <key>", file=sys.stderr); sys.exit(1)
    p = reg.payload(proj)
    t = next((x for x in p["tests"] if x["key"] == rest[0]), None)
    if t is None:
        print(f"[builderbot] ERROR: no test called {rest[0]} here", file=sys.stderr)
        sys.exit(1)
    print(f"  {t['key']}  {secs(t['ms'])}  [{t['status'] or '?'}]")
    print(f"  {t['name']}")
    if t.get("after"):
        print(f"  follows: {t['after']}")
    if len(t.get("history") or []) > 1:
        print("  history: " + ", ".join(f"{h / 1000:.1f}s" for h in t["history"]))
    if t["suspect"]:
        print(f"  FLAGGED: lands on a {t['suspect']}s boundary, a fixed sleep or a "
              "polling timeout rather than work")
    elif t.get("accepted"):
        print(f"  accepted: sits on {t['sits_on']}s, and that is the work: {t['accepted']}")
    print(f"  protects: {t['protects'] or '(nothing written yet)'}")
    print(f"  exercises: {t['notes'] or '(nothing written yet)'}")
elif op == "describe" and rest[:1] == ["--from"]:
    # A bulk fill, from a file of {key: {protects, notes}}: one load and one
    # save. Written for the first fill of a registry that already had two
    # thousand tests in it, where the per-test verb would have been two
    # thousand rewrites of the store.
    import json as _json
    with open(os.environ.get("BB_TESTS_FILE", ""), encoding="utf-8") as fh:
        rows = _json.load(fh)
    r = reg.describe_many(proj, rows)
    bail(r)
    print(f"described {r['wrote']} tests")
    if r["unknown_n"]:
        print(f"  {r['unknown_n']} keys named no test here; the registry and the "
              "file have drifted:")
        for k in r["unknown"][:10]:
            print(f"    {k}")
elif op in ("note", "describe"):
    # `bb tests note KEY "what it protects" [--how "what it exercises"]`
    if len(rest) < 2:
        print('usage: bb tests note <key> "what it protects" [--how "fixtures, stubs"]',
              file=sys.stderr)
        sys.exit(1)
    words, how, i = [], None, 1
    while i < len(rest):
        if rest[i] == "--how" and i + 1 < len(rest):
            how = rest[i + 1]; i += 2
        else:
            words.append(rest[i]); i += 1
    r = reg.describe(proj, rest[0], protects=" ".join(words),
                     **({"notes": how} if how is not None else {}))
    bail(r)
    print(f"described {rest[0]}")
elif op == "ingest":
    src = os.environ.get("BB_TESTS_FILE", "")
    with open(src, encoding="utf-8", errors="replace") as fh:
        r = reg.ingest(proj, fh.read(), by="claude")
    bail(r)
    print(f"ingested {r['n']} results from {len(r['suites'])} suite"
          f"{'' if len(r['suites']) == 1 else 's'}")
    for kind, rows in (("new", r["added"]), ("gone", r["gone"]),
                       ("renamed", r["renamed"])):
        if not rows:
            continue
        print(f"  {kind}: {len(rows)}")
        for x in rows[:10]:
            print("    " + (f"{x['was'][:40]} -> {x['now'][:40]}"
                            if kind == "renamed" else x["name"][:70]))
        if len(rows) > 10:
            print(f"    ...and {len(rows) - 10} more")
    if not (r["added"] or r["gone"] or r["renamed"]):
        print("  the registry and the runner agree")
elif op == "drift":
    p = reg.payload(proj)
    d = p.get("drift") or {}
    if not d.get("at"):
        print("nothing ingested yet")
        sys.exit(0)
    # The stored counts, not the lengths of the lists under them: the lists
    # are capped and a first ingest is every test in the project, so counting
    # rows would report where the list stops rather than what drifted.
    shown = n = 0
    for k in ("added", "gone", "renamed"):
        shown += len(d.get(k) or [])
        n += d.get("n_" + k, len(d.get(k) or []))
    print(f"as of the last ingest: {n} difference{'' if n == 1 else 's'}")
    for x in d.get("added") or []:
        print(f"  new     {x['key']:<20} {x['name'][:60]}")
    for x in d.get("gone") or []:
        print(f"  gone    {x['key']:<20} {x['name'][:60]}")
    for x in d.get("renamed") or []:
        print(f"  renamed {x['key']:<20} {x['was'][:30]} -> {x['now'][:30]}")
    if n > shown:
        print(f"  ...and {n - shown} more")
    if p["undocumented"]:
        print(f"\n{p['undocumented']} of {p['n']} tests have no line saying what "
              "they protect; `bb tests list` shows the slowest first")
elif op == "flagged":
    p = reg.payload(proj)
    print(f"{p['suspect']} tests land on a round timeout: "
          f"{p['recover_ms'] // 1000}s of the suite is waiting, not working"
          + (f" · {p['accepted']} accepted as the work, not listed" if p["accepted"] else ""))
    for t in p["tests"]:
        if t["suspect"]:
            print(f"   {secs(t['ms']):>8}  {t['key']:<20} {t['name'][:56]}"
                  f"  [{t['suspect']}s]")
elif op == "accept":
    # `bb tests accept KEY "why"`: the wait is the work (a real boot, a
    # timeout being proved) so it stops being flagged, with the reason kept
    # beside it. `--no` takes the mark off.
    if len(rest) < 2 or (rest[1] != "--no" and not rest[1].strip()):
        print("usage: bb tests accept <key> \"why the time is the work\"  |  bb tests accept <key> --no",
              file=sys.stderr); sys.exit(1)
    r = reg.accept(proj, rest[0], "" if rest[1] == "--no" else " ".join(rest[1:]))
    bail(r)
    print(f"{rest[0]}: " + ("no longer accepted; flagged again if it sits on a round number"
                            if rest[1] == "--no" else "accepted; it will not be flagged"))
else:
    print(f"[builderbot] ERROR: unknown: bb tests {op}", file=sys.stderr)
    sys.exit(1)
