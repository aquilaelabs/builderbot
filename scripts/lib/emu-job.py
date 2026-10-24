"""Behind `bb emu` when the emulator is on a node (emu_via_node in bb): one emu
job queued through the controller, its log streamed here, and the exit code
the job's.

Arguments: the auth header, the project, then the bb words to run there
(`emu`, the subcommand, its arguments). BB_EMU_FILES is the file the node
fetches from dist/ first, one per line, for `emu install`.
"""
import os
import sys

import bbapi
import waits


auth, proj, *argv = sys.argv[1:]
auth = auth or os.environ.get("BB_AUTH_HEADER", "")
files = [f for f in os.environ.get("BB_EMU_FILES", "").split("\n") if f]
call = lambda path, body=None: bbapi.call(path, body, auth=auth)   # noqa: E731
r = call("/api/v1/jobs", {"action": "emu", "project": proj, "argv": argv, "files": files,
                          "outputs": ["*.png", "*.txt"],
                          "from": "session" if os.environ.get("CLAUDECODE") or os.environ.get("BB_AGENT") else "operator"})
if r.get("error"):
    sys.exit(f"[builderbot] ERROR: {r['error']}")
names = {n["id"]: n["name"] for n in (call("/api/v1/nodes").get("nodes") or [])}
print(f"[builderbot] {r['job']}: bb {' '.join(argv)} on {names.get(r['node'], r['node'])}", flush=True)
j, state = waits.follow(auth, r["job"])
arts = [o["path"] for o in (j.get("outputs") or []) if o.get("kind") == "artifact"]
print(f"[builderbot] {r['job']} {state}" + (f": {j['error']}" if j.get("error") else "")
      + (", into dist/: " + ", ".join(a[5:] for a in arts) if arts else ""), flush=True)
sys.exit(0 if state == "succeeded" else (j.get("exit_code") or 1))
