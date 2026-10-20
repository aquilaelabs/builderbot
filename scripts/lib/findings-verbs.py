"""Behind `bb findings history` and `bb findings sample` (cmd_findings_history
and cmd_findings_sample in bb): the scanner log's history, read through
dashboard/findings.py, and a sample SARIF report written for the Analysis
tab to show when no scanner has run.

The first argument is the verb. `history` takes findings.py's path, the
project, then the filters (-n N, --all, --since D, --find TEXT), with
DASHBOARD_STATE saying where the notebook's files are. `sample` takes the
report's path, with WORKSPACE saying where the projects it names are.
"""
import json
import os
import sys
import time

import dash

verb, args = sys.argv[1], sys.argv[2:]


def history():
    fx = dash.load("findings", dash.beside(args[0]))
    write_json = dash.statefile(dash.beside(args[0])).write_json
    fx.configure(write_json=write_json,
                 state=os.environ.get("DASHBOARD_STATE", "/config"))
    proj, argv = args[1], args[2:]

    # The same three filters the other logs take, parsed the same way: a day
    # count or a date, because both are things somebody types from memory.
    limit, since, find, i = 20, None, None, 0
    while i < len(argv):
        a = argv[i]
        if a in ("-n", "--last") and i + 1 < len(argv):
            limit = fx._int(argv[i + 1]); i += 2
        elif a == "--all":
            limit = None; i += 1
        elif a == "--since" and i + 1 < len(argv):
            v = argv[i + 1]
            n = fx._int(v.rstrip("d")) if v.rstrip("d").isdigit() else None
            if n is not None:
                since = int(time.time()) - n * 86400
            else:
                try:
                    since = int(time.mktime(time.strptime(v, "%Y-%m-%d")))
                except ValueError:
                    print(f"[builderbot] ERROR: not a date or a day count: {v}",
                          file=sys.stderr); sys.exit(1)
            i += 2
        elif a in ("--find", "-f") and i + 1 < len(argv):
            find = argv[i + 1]; i += 2
        else:
            print("usage: bb findings history [-n N|--all] [--since 7d|YYYY-MM-DD] "
                  "[--find TEXT]", file=sys.stderr)
            sys.exit(1)

    h = fx.history(proj, limit=limit, since=since, find=find)
    if not h:
        print(f"nothing in {proj}'s findings log matches that")
        print("the first scan of a project is its starting point rather than an "
              "entry, so this fills in from the second one onwards")
    for e in h:
        when = time.strftime("%d %b %H:%M", time.localtime(e.get("at", 0)))
        print(f"  {when}  {e.get('act', ''):<8}  {e.get('text', '')}")
        if e.get("note"):
            print(f"{'':>24}{e['note']}")


def sample():
    ws = os.environ.get("WORKSPACE", "/workspace")
    try:
        names = sorted(d.name for d in os.scandir(ws)
                       if d.is_dir() and not d.name.startswith("."))
    except OSError:
        names = []
    # Three at most: enough for the tab's per-project rows to mean something,
    # few enough that the list is obviously a sample and not a scan.
    names = names[:3] or ["example"]

    RULES = [
        ("BBSAMPLE001", "error", "sample finding: a shell script runs a command without checking it"),
        ("BBSAMPLE002", "warning", "sample finding: a dependency is pinned to a moving tag"),
        ("BBSAMPLE003", "note", "sample finding: this line is longer than the style allows"),
    ]
    results = []
    for i, project in enumerate(names):
        rule, level, text = RULES[i % len(RULES)]
        results.append({
            "ruleId": rule, "level": level,
            "message": {"text": f"{text} (sample data, no scanner ran)"},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": f"{project}/sample/where-it-would-be.txt"},
                "region": {"startLine": 12 + i}}}]})
    # One the attribution cannot place, so the "unattributed" label on the tab has
    # something to label. This is what a scanner's own container paths look like.
    results.append({
        "ruleId": "BBSAMPLE004", "level": "warning",
        "message": {"text": "sample finding: a path this share does not mount (sample data)"},
        "locations": [{"physicalLocation": {
            "artifactLocation": {"uri": "opt/somewhere-else/thing.py"},
            "region": {"startLine": 1}}}]})

    doc = {"version": "2.1.0",
           "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
           "runs": [{"tool": {"driver": {
               "name": "builderbot-sample",
               "informationUri": "https://github.com/aquilaelabs/builderbot",
               "rules": [{"id": r, "shortDescription": {"text": t}} for r, _, t in RULES]}},
               "results": results}]}
    with open(args[0], "w") as f:
        json.dump(doc, f, indent=1)
    print(f"{len(results)} sample findings, one each in {', '.join(names)} "
          "and one on a path that places nowhere")


{"history": history, "sample": sample}[verb]()
