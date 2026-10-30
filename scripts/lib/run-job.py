"""Behind `bb run`, and so `bb build` and `bb test`, when the command travels
(cmd_run in bb): this tree snapshotted, the command run on the project's node
as a job, its log streamed here, and what --out names brought back into
dist/.

Arguments: the auth header, the project, the role (build or test), the node
or "", the timeout in seconds, then the command. BB_RUN_OUTS is the output
globs, one per line.
"""
import os
import sys

import bbapi
import waits


auth, proj, role, node, timeout, *argv = sys.argv[1:]
auth = auth or os.environ.get("BB_AUTH_HEADER", "")
outs = [o for o in os.environ.get("BB_RUN_OUTS", "").split("\n") if o]
call = lambda path, body=None: bbapi.call(path, body, auth=auth)   # noqa: E731
nid = node
if node:
    # A node by name is what a person types; the API takes the id.
    got = call("/api/v1/nodes").get("nodes") or []
    hit = [n for n in got if n["id"] == node or n["name"] == node]
    if not hit:
        sys.exit(f"[builderbot] ERROR: no node called {node}"
                 + (" that this session may use: a session sees only the nodes its project builds on"
                    if os.environ.get("CLAUDECODE") or os.environ.get("BB_AGENT") else " (bb nodes lists them)"))
    nid = hit[0]["id"]
r = call("/api/v1/jobs", {"action": "run", "project": proj, "role": role, "node": nid,
                          "argv": argv, "outputs": outs, "timeout": int(timeout),
                          "from": "session" if os.environ.get("CLAUDECODE") or os.environ.get("BB_AGENT") else "operator"})
if r.get("error"):
    sys.exit(f"[builderbot] ERROR: {r['error']}")
names = {n["id"]: n["name"] for n in (call("/api/v1/nodes").get("nodes") or [])}
# Its place on that node (R151 step 5): one job at a time runs there, so a
# run behind another says how many are ahead rather than looking stuck.
ahead = [j for j in (call("/api/v1/jobs?active=1").get("jobs") or [])
         if j.get("node") == r["node"] and j.get("id") != r["job"] and j.get("state") in ("queued", "assigned", "running")]
print(f"[builderbot] {r['job']} queued on {names.get(r['node'], r['node'])}: "
      f"snapshot {r['snapshot'][7:19]}, {r['files']} files"
      + (f"; {len(ahead)} job{'s' if len(ahead) != 1 else ''} ahead of it there ({', '.join(str(j.get('type')) for j in ahead)})" if ahead else ""), flush=True)
j, state = waits.follow(auth, r["job"])
arts = [o for o in (j.get("outputs") or []) if o.get("kind") == "artifact"]
kept = [o for o in (j.get("outputs") or []) if o.get("kind") == "workspace"]
line = f"[builderbot] {r['job']} {state}"
if j.get("error"):
    line += f": {j['error']}"
if arts:
    line += ", into dist/: " + ", ".join(a["path"][5:] for a in arts)
if kept:
    line += f", workspace kept on the node at {kept[0]['path']}"
print(line, flush=True)
sys.exit(0 if state == "succeeded" else (j.get("exit_code") or 1))
