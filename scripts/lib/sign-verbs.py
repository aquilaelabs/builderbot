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


def ago(at):
    s = max(0, int(time.time()) - int(at or 0))
    return (f"{s}s" if s < 90 else f"{s // 60} min" if s < 5400 else
            f"{s // 3600} h" if s < 172800 else f"{s // 86400} days") + " ago"


def status_verb(rest):
    """bb sign status [TAG] (R134): whether the project's release APKs can be
    signed, and how the newest went, in the Signing view's and the bell's
    words."""
    tag = rest[0] if rest else ""
    d = bbapi.call("/api/signing", {"action": "release", "project": project}, auth=auth)
    if d.get("error"):
        sys.exit(f"[builderbot] ERROR: {d['error']}")
    r = d.get("release") or {}
    if not r.get("wanted"):
        print(f"  {project}'s workflows hand over no unsigned APK (an artifact named bb-release-apk-TAG), "
              "so BuilderBot signs none of its releases")
        return
    for k in r.get("keys") or []:
        print(f"  {k.get('package') or 'the app'}: releases sign with {k.get('key')}  {k.get('sha256') or ''}")
    if r.get("node"):
        print(f"  signed on {r['node']}")
    print("  ready: a release's APK can be signed" if not r.get("why") else f"  NOT READY: {r['why']}")
    if r.get("looking"):
        print("  looking for unsigned APKs now")
    rows = [("signed", x) for x in r.get("signed") or []] + [("failed", x) for x in r.get("failed") or []]
    rows = [x for x in rows if not tag or x[1].get("tag") == tag]
    for what, x in sorted(rows, key=lambda x: -int(x[1].get("at") or 0)):
        if what == "signed":
            print(f"  {x.get('tag')}: signed {ago(x.get('at'))}, {', '.join(x.get('files') or [])} "
                  f"with {x.get('key')} ({x.get('cert') or '?'}){'  ' + x['url'] if x.get('url') else ''}")
        else:
            print(f"  {x.get('tag')}: FAILED {ago(x.get('at'))}: {x.get('why')}")
    if tag and not rows:
        print(f"  nothing yet for {tag}: its APK is looked for once the release is made, and hourly")
    if any(w == "failed" for w, _ in rows):
        print("  bb sign release --why \"...\" asks for the look again once what stopped it is fixed")


def release_verb(why):
    """bb sign release --why (R134 step 5): the Signing view's Look for
    unsigned APKs now, under the Sign a build dial."""
    # The look before this one, so its end is told by the controller's own
    # clock, never this machine's.
    before = int(((bbapi.call("/api/signing", {"action": "release", "project": project}, auth=auth)
                   .get("release") or {}).get("last") or {}).get("at") or 0)
    r = bbapi.call("/api/signing", {"action": "release-sign", "project": project, "why": why}, auth=auth)
    if r.get("error"):
        sys.exit(f"[builderbot] ERROR: {r['error']}")
    if r.get("id") and not r.get("ok"):
        print(f"[builderbot] asked {r.get('to') or 'the project owner'} (#{r['id']}), waiting up to "
              "15 minutes for Approve in their bell", file=sys.stderr)
        o = waits.outcome(auth, r["id"], "the look was not allowed")
        if o.get("code"):
            sys.exit(f"[builderbot] ERROR: {o.get('out') or 'it was not started'}")
    # The look is waited for and what it found said run by run (R190
    # step 5): "looking" alone left v0.9.0-dev.4501's missing APK
    # unexplained.
    print("[builderbot] looking for unsigned release APKs, waiting for what the look finds", file=sys.stderr)
    t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(5)
        d = bbapi.call("/api/signing", {"action": "release", "project": project}, auth=auth)
        rel = d.get("release") or {}
        last = rel.get("last") or {}
        if not rel.get("looking") and int(last.get("at") or 0) > before:
            break
    else:
        sys.exit("[builderbot] ERROR: the look is still going after fifteen minutes: bb sign status says how it went")
    said_look(last, rel.get("expect") or [])


def said_look(last, expect):
    """What one look found, in a line per run, and why it found nothing."""
    if last.get("error"):
        print(f"  the look could not finish: {last['error']}")
    for x in last.get("runs") or []:
        print(f"  run {x.get('run')} for {x.get('tag')}: {x.get('state')}"
              + (f": {x['why']}" if x.get("why") else "") + (f"  {x['url']}" if x.get("url") else ""))
    if not last.get("runs") and not last.get("error"):
        print(f"  no unsigned APK waiting: {last.get('asked', 0)} recent run(s) that passed were asked and "
              f"none handed one over, {last.get('known_bare', 0)} more are known to hand over none")
        print("  the Android workflow's run for the release may still be going, or it failed: "
              "bb forge run list says which")
    if expect:
        print(f"  still expected: {', '.join(expect)}, looked for every few minutes for twelve hours")


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
            print("  no keys yet: an administrator adds one in the project's Signing view (Ship)")
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


if sys.argv[1] == "--status":
    status_verb(sys.argv[4:])
    sys.exit(0)
if sys.argv[1] == "--release":
    release_verb(sys.argv[3])
    sys.exit(0)
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
