"""Behind `bb jobs` (cmd_jobs in bb): the queue, read-only: the recent jobs
and what became of them, or one job's log, from the controller's API as
the caller, which narrows it the way the Jobs tab is narrowed: a session
to its own project's jobs, an account to its projects', an administrator
to all. It read the node store directly before, which on a machine that
holds the controller's state showed a session every project's jobs by
name (B317).

Arguments: how many jobs to list, and a job's id for its log. BB_JOBS_AUTH
is the auth header.
"""
import os
import sys
import time

import bbapi

auth = os.environ["BB_JOBS_AUTH"]
jid = sys.argv[2] if len(sys.argv) > 2 else ""
d = bbapi.call(f"/api/v1/jobs?id={jid}" if jid else f"/api/v1/jobs?n={int(sys.argv[1])}", auth=auth)
if jid:
    # One job answers as itself; the API's "no such job" is the same answer
    # for one that is another project's, on purpose.
    if d.get("error") and "state" not in d:
        print(f"no such job: {jid}")
        raise SystemExit(1)
    rows, names = [d], {}
else:
    if d.get("error"):
        sys.exit(f"[builderbot] ERROR: {d['error']}")
    rows, names = d.get("jobs") or [], d.get("nodes") or {}
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
    state = j["state"] + (" (stopping)" if j.get("cancel") and j["state"] == "running" else "")
    if j["state"] == "running" and j.get("step"):
        state += f' · {j["step"]}'
    when = time.strftime("%d %b %H:%M", time.localtime(j.get("queued") or 0))
    took = (f' · {max(1, int(j["ended"]) - int(j["started"]))}s'
            if j.get("started") and j.get("ended") else "")
    err = f': {j["error"]}' if j.get("error") else ""
    print(f'{j["id"]:>12}  {when}  {state:<22} {names.get(j.get("node"), j.get("node") or "any"):<12} '
          f'{what}{took}{err}')
    if jid:
        # The log, which is why an id was given. A build's can be megabytes,
        # so the tail is what prints unless the whole thing is small.
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
