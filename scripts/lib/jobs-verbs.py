"""Behind `bb jobs` (cmd_jobs in bb): the queue, read-only: the recent jobs
and what became of them, or one job's log, from the node store the way
the Jobs tab reads it (dashboard/nodes.py).

Arguments: nodes.py's path, how many jobs to list, and a job's id for its
log. DASHBOARD_STATE says where the store is.
"""
import os
import sys
import time

import dash

nodes = dash.load("nodes", dash.beside(sys.argv[1]))
try:
    nodes.db.open_readonly(os.environ["DASHBOARD_STATE"])
    jid = sys.argv[3] if len(sys.argv) > 3 else ""
    rows = ([nodes.job(jid)] if jid else nodes.jobs_for(n=int(sys.argv[2])))
    names = {x["id"]: x["name"] for x in nodes.node_list(all=True)}
except Exception as e:
    print(f"no node store yet; the dashboard creates it on boot ({e})")
    raise SystemExit(0) from None
if jid and not rows[0]:
    print(f"no such job: {jid}")
    raise SystemExit(1)
if not rows:
    print("no jobs yet; a compose action, an exec on a node or an agent update makes one")
    raise SystemExit(0)
for j in rows:
    s = j.get("spec") or {}
    # Named per type, the same names the Jobs tab uses. Anything not named
    # here fell through to `exec` with an empty command, which is what a
    # system job looked like on this list: a blank line and an exit code.
    what = (f'{s.get("action", "compose")} {j["project"]}'
            + (f'/{s["instance"]}' if s.get("instance") not in (None, "", "main") else "")
            if j["type"] == "compose" else
            "agent self-update" if j["type"] == "self-update" else
            f'apply {s.get("apply") or "config"} on the node' if j["type"] == "system" else
            f'{s.get("action") or "install"} {", ".join(s.get("names") or [])}'
            if j["type"] == "toolchain" else
            f'{s.get("action") or "add"} image {s.get("image") or ""}'
            if j["type"] == "image" else
            ("clear " + (f'{s["project"]}\'s caches' if s.get("project") else "every cache"))
            if j["type"] == "cache-clear" else
            "exec " + " ".join(s.get("argv") or [])[:60])
    state = j["state"] + (" (stopping)" if j["cancel"] and j["state"] == "running" else "")
    if j["state"] == "running" and j.get("step"):
        state += f' · {j["step"]}'
    when = time.strftime("%d %b %H:%M", time.localtime(j["queued"]))
    took = (f' · {max(1, j["ended"] - j["started"])}s'
            if j.get("started") and j.get("ended") else "")
    err = f': {j["error"]}' if j.get("error") else ""
    print(f'{j["id"]:>12}  {when}  {state:<22} {names.get(j["node"], j["node"] or "any"):<12} '
          f'{what}{took}{err}')
    if jid:
        # The log, which is why an id was given. `nodes.job` reads it whole;
        # a build's can be megabytes, so the tail is what prints unless the
        # whole thing is small.
        log = (j.get("log") or "")
        if not log.strip():
            print("\n  (this job wrote nothing, and not "
                  + ("still running" if j["state"] in ("queued", "assigned", "running")
                     else "an empty pane waiting to fill") + ")")
        else:
            cut = log[-20000:]
            print(f"\n  ---- log{' (last 20000 characters)' if cut != log else ''} ----")
            for ln in cut.splitlines():
                print("  " + ln)
