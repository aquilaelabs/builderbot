"""Behind `bb ci-log` for a project whose workflows run on GitHub's own
runners (R115): the runs and a run's failed jobs, read by the controller
with its credential (cilogs.py on the dashboard's side), since the session
holds none and GitHub hands out a log only to a token.

    bb ci-log --list      the newest runs: id, when, workflow, branch, result
    bb ci-log [RUN]       a run's jobs, and the end of each failed job's log
                          (the newest finished run when none is named)

BB_CI_AUTH is the auth header and BB_CI_PROJECT the project.
"""
import os
import sys
import urllib.parse

import bbapi

auth = os.environ["BB_CI_AUTH"]
proj = os.environ["BB_CI_PROJECT"]
args = sys.argv[1:]


def fail(msg):
    sys.exit(f"[builderbot] ERROR: {msg}")


def get(query):
    r = bbapi.call("/api/ci-runs?project=" + urllib.parse.quote(proj) + query, auth=auth, timeout=120)
    if not isinstance(r, dict):
        fail("the controller answered something that is not a run")
    if r.get("error"):
        fail(r["error"])
    return r


if "--list" in args:
    r = get("")
    print(f"runs of {r.get('repo')} on GitHub, newest first:")
    for x in r.get("runs") or []:
        res = x.get("conclusion") or x.get("status") or ""
        print(f"  {x['id']:<13} {x.get('at', '')[:16].replace('T', ' ')}  {x.get('name', '')[:24]:<24} "
              f"{x.get('branch', '')[:28]:<28} {res}")
    print("  ('bb ci-log RUN' for one: its jobs and the end of each failed one's log)")
    sys.exit(0)

run = next((a for a in args if not a.startswith("-")), "")
run = run.split("-")[0]
if run and not run.isdigit():
    fail("bb ci-log RUN: a run is named by its number, as bb ci-log --list prints it")
r = get("&run=" + (run or "0"))
m = r.get("run") or {}
print(f"{r.get('repo')} run {m.get('id')}: {m.get('name')} on {m.get('branch')}, "
      f"{m.get('conclusion')} ({str(m.get('at', ''))[:16].replace('T', ' ')})")
if m.get("url"):
    print(f"  {m['url']}")
for j in r.get("jobs") or []:
    why = f", at the step '{j['failed_step']}'" if j.get("failed_step") else ""
    print(f"\n== {j.get('name')}: {j.get('conclusion')}{why} ==")
    if j.get("earlier"):
        print(f"  (the lines above the end that name a failure, {j['earlier'].count(chr(10)) + 1} of them)")
        print(j["earlier"])
        print("  ...")
    if "log" in j:
        if j.get("lines", 0) > j["log"].count("\n") + 1:
            print(f"  (the last {j['log'].count(chr(10)) + 1} of its {j['lines']} lines)")
        print(j["log"])
