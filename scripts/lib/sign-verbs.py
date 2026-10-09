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
if not project:
    sys.exit("[builderbot] ERROR: run bb sign inside a project's tree")


def keys_verb(sub, route, why, rest):
    """bb sign keys | key new NAME | map PACKAGE KEY (R106 step 6)."""
    if sub == "--keys":
        d = bbapi.call("/api/signing", {"action": "keys", "project": project}, auth=auth)
        if d.get("error"):
            sys.exit(f"[builderbot] ERROR: {d['error']}")
        for name, slots in (d.get("keys") or {}).items():
            for rt, rec in slots.items():
                print(f"  {name:<14} {rt:<9} " + (f"{rec.get('alias')}  {rec.get('sha256')}" if rec else "-"))
        for pkg, k in (d.get("map") or {}).items():
            print(f"  {pkg} -> {k}")
        if not d.get("keys"):
            print("  no keys yet: an administrator adds one under Signing keys in the project's settings")
        return
    if sub == "--rotate":
        if len(rest) != 2:
            sys.exit("[builderbot] ERROR: bb sign rotate OLD NEW --why \"...\" (two keys, each with a sideload key)")
        body = {"action": "rotate", "from": rest[0], "to": rest[1]}
    elif sub == "--key":
        if len(rest) != 2 or rest[0] != "new" or route not in ("play", "sideload"):
            sys.exit("[builderbot] ERROR: bb sign key new NAME --for play|sideload --why \"...\"")
        body = {"action": "generate", "key": rest[1], "route": route}
    else:
        if len(rest) != 2:
            sys.exit("[builderbot] ERROR: bb sign map PACKAGE KEY --why \"...\" (KEY \"\" unmaps it)")
        body = {"action": "map", "package": rest[0], "key": rest[1]}
    r = bbapi.call("/api/signing", body | {"project": project, "why": why}, auth=auth, timeout=180)
    if r.get("error"):
        sys.exit(f"[builderbot] ERROR: {r['error']}")
    if r.get("id") and not r.get("keys") and not r.get("key"):
        print(f"[builderbot] asked {r.get('to') or 'the project owner'} (#{r['id']}), waiting up to "
              "15 minutes for Approve in their bell", file=sys.stderr)
        o = waits.outcome(auth, r["id"], "the change was not allowed")
        if o.get("code"):
            sys.exit(f"[builderbot] ERROR: {o.get('out') or 'it was not made'}")
    print("[builderbot] done: bb sign keys says what the project has now", file=sys.stderr)


if sys.argv[1].startswith("--"):
    keys_verb(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
    sys.exit(0)
file, route, why = sys.argv[1], sys.argv[2], sys.argv[3]
# The build is read from the controller's copy of dist/: on a synced node it
# goes up first (R163).
import syncwait  # noqa: E402
if not syncwait.up(project, "the controller signs the build in its copy of dist/"):
    sys.exit("[builderbot] ERROR: not asked: the build here has not reached the controller yet; try again in a moment")
r = bbapi.call("/api/signing", {"action": "sign", "project": project, "file": file, "route": route,
                                "key": os.environ.get("BB_SIGN_KEY", ""), "why": why}, auth=auth, timeout=60)
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
