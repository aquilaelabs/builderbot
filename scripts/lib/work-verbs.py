"""Behind `bb work` (cmd_work in bb): who else is changing this project and
where you overlap, from git's view of every working tree and the hook's
notes (dashboard/overlap.py). Read-only.

Arguments: overlap.py's path, the project, the dashboard's state directory
and the workspace.
"""
import contextlib
import json
import sys

import dash

mod, proj, state, ws = sys.argv[1:5]
o = dash.load("overlap", dash.beside(mod))
o.configure(state=state, workspace=ws,
            write_json=lambda p, d: open(p, "w").write(json.dumps(d, indent=2)))
# The account each worktree belongs to, so the answer names people rather than
# ids. Missing users.json is not fatal; the ids are still an answer.
names = {}
with contextlib.suppress(Exception), open(f"{state}/users.json") as f:
    names = {u.get("uid"): n for n, u in (json.load(f).get("users") or {}).items()}
wt = f"{ws}/.worktrees"
trees = o.trees(proj, wt)
if len(trees) < 2:
    print(f"{proj}: one working tree, and nobody else is in it")
else:
    print(f"{proj}: {len(trees)} working trees")
    for label, path in trees.items():
        n = len(o.changed(path))
        print(f"  {names.get(label, label or 'owner'):<20} {n} file(s) uncommitted  {path}")
hits = o.collisions(proj, wt, names)
if hits:
    print("\nthe same file, open in more than one:")
    for h in hits:
        print(f"  {h['file']}  ({', '.join(h['trees'])})")
elif len(trees) > 1:
    print("\nno file is open in two of them")
notes = o.notes(proj)
if notes:
    print("\nwhat each session last touched (a guess at the symbol, from the edit):")
    for sess, rec in sorted(notes.items()):
        for f, syms in sorted((rec.get("files") or {}).items()):
            print(f"  {o.said(sess, names):<20} {f}" + (f"  [{', '.join(syms)}]" if syms else ""))
