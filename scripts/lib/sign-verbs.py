"""Behind `bb sign` (cmd_sign in bb, R106): ask the controller to sign a
build in the project's dist/ with one of its keys, wait for the project's
owner when its dial is `ask`, then follow the sign job to its verdict. The
session sends a file name and a route and gets a file back in dist/; the
key and its password never come near it.

Arguments: FILE (relative to dist/), ROUTE (play or sideload), WHY.
BB_SIGN_AUTH and BB_SIGN_PROJECT come from bb."""
import os
import sys
import time

import bbapi
import waits

auth = os.environ["BB_SIGN_AUTH"]
project = os.environ.get("BB_SIGN_PROJECT", "")
file, route, why = sys.argv[1], sys.argv[2], sys.argv[3]
if not project:
    sys.exit("[builderbot] ERROR: run bb sign inside a project's tree")

r = bbapi.call("/api/signing", {"action": "sign", "project": project, "file": file,
                                "route": route, "why": why}, auth=auth, timeout=60)
if r.get("error"):
    sys.exit(f"[builderbot] ERROR: {r['error']}")
job = r.get("job") or ""
if not job and r.get("id"):
    print(f"[builderbot] asked {r.get('to') or 'the project owner'} (#{r['id']}), waiting up to "
          "15 minutes for Approve in their bell", file=sys.stderr)
    o = waits.outcome(auth, r["id"], "the signing was not allowed")
    if o.get("code"):
        sys.exit(f"[builderbot] ERROR: {o.get('out') or 'the signing would not start'}")
    job = o.get("out") or ""
if not job:
    sys.exit("[builderbot] ERROR: the controller started no signing and said nothing about why")
print(f"[builderbot] signing {file} for {route} on the project's node ({job})", file=sys.stderr)
for _ in range(600):
    time.sleep(2)
    j = bbapi.call(f"/api/v1/jobs?id={job}", auth=auth)
    if j.get("error") and "state" not in j:
        sys.exit(f"[builderbot] ERROR: {j['error']}")
    if j.get("state") not in ("succeeded", "failed", "canceled"):
        continue
    log = str(j.get("log") or "")
    said = [ln for ln in log.splitlines() if ln.strip()]
    if j["state"] != "succeeded":
        print("\n".join(said[-6:]))
        sys.exit(f"[builderbot] ERROR: the signing {j['state']}: {str(j.get('error') or '')[:200]}")
    print(next((ln for ln in reversed(said) if ln.startswith("signed ")), "signed"))
    sys.exit(0)
sys.exit(f"[builderbot] ERROR: the signing ({job}) had not finished in twenty minutes; bb jobs {job} says where it is")
