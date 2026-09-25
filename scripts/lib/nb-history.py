"""Behind `bb history` (cmd_history in bb): one search over all of the
notebook's logs (the roadmap, the bugs, what the dashboard did to the
memories, the findings and the approval queue), tagged by source and
merged by time.

Arguments: the dashboard directory, the project, then the filters
(-n N, --since D, --find TEXT). DASHBOARD_STATE says where the notebook's
files are.
"""
import os
import sys
import time

import dash

dirname, proj, argv = sys.argv[1], sys.argv[2], sys.argv[3:]
state = os.environ.get("DASHBOARD_STATE", "/config")
# One implementation of the atomic write, from beside the modules it serves.
write_json = dash.statefile(dirname).write_json
roadmap = dash.load("roadmap", dirname)
roadmap.configure(write_json=write_json, state=state, actor=lambda: dash.account_name(state))
import ids  # noqa: E402  (roadmap.py put its directory on sys.path)
bugs = dash.load("bugs", dirname)
bugs.configure(write_json=write_json, state=state, actor=lambda: dash.account_name(state))
memory = dash.load("memory", dirname)
memory.configure_log(write_json=write_json, state=state)
findings = dash.load("findings", dirname)
findings.configure(write_json=write_json, state=state)

limit, since, find, i = 20, None, None, 0
while i < len(argv):
    a = argv[i]
    if a in ("-n", "--last") and i + 1 < len(argv):
        limit = int(argv[i + 1]); i += 2
    elif a == "--all":
        limit = None; i += 1
    elif a == "--since" and i + 1 < len(argv):
        v = argv[i + 1]
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
    elif a in ("--find", "-f") and i + 1 < len(argv):
        find = argv[i + 1]; i += 2
    else:
        print("usage: bb history [-n N|--all] [--since 7d|YYYY-MM-DD] "
              "[--find TEXT]", file=sys.stderr)
        sys.exit(1)

rows = []
# All four views, so "when did anything here mention X" means all of it. The
# findings log is the one nobody wrote: its rows carry no `by`, which reads
# correctly in this column as a blank rather than a name.
# ...and the approval queue's own log (roadmap #27): what was held, and what
# the operator decided: the one place "denied" is written down.
pending = dash.load("pending", dirname)
pending.configure(write_json=write_json, state=state)
for tag, mod in (("roadmap", roadmap), ("bugs", bugs), ("memory", memory),
                 ("scanner", findings), ("waiting", pending)):
    for e in mod.history(proj, since=since, find=find):
        rows.append((tag, e))
rows.sort(key=lambda te: -te[1].get("at", 0))
if limit:
    rows = rows[:limit]
if not rows:
    print(f"nothing in {proj}'s notebook matches that")
for tag, e in rows:
    when = time.strftime("%d %b %H:%M", time.localtime(e.get("at", 0)))
    where = f" step {e['step'] + 1} of" if e.get("step") is not None else ""
    # The tab's own letter on the number (R12, B62), because a merged log is
    # exactly where a bare number could be read against the wrong list.
    kind = tag
    if tag == "waiting":
        # The queue's rows carry which tab and that tab's number.
        k2 = e.get("kind")
        ident = (f" {ids.label(k2, e['number'])}" if e.get("number") is not None
                 and k2 in ids.LETTERS else
                 f" rule {e['number']}" if e.get("number") else "")
    else:
        ident = (f" {ids.label(kind, e['id'])}" if e.get("id") is not None
                 and kind in ids.LETTERS else "")
    print(f"  {when}  {tag:>7}  {dash.wrote(e):>6}  {e.get('act', ''):<11}"
          f"{where}{ident}  {e.get('text', '')}")
    if e.get("was"):
        print(f"{'':>41}was: {e['was']}")
    for k in ("why", "note"):
        if e.get(k):
            print(f"{'':>41}{k}: {e[k]}")
    if e.get("approved"):
        print(f"{'':>41}approved by the operator")
