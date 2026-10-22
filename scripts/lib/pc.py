"""Behind `bb pc` (cmd_pc in bb): a person's Windows PC lent to this project
by the Windows companion (R270 step 6). A fixed table of verbs, each run on
the PC as its person set it up there, under the project's Agents may: Use a
lent PC; never a command string.

    bb pc                         the PCs lending this project, and what each lends
    bb pc VERB [--why "..."]      run one and wait for what it did
    bb pc editor-call METHOD PATH [--body JSON] [--why "..."]
                                  one request to the editor's local interface

BB_PC_AUTH is the auth header bb chose.
"""
import os
import sys
import time

import bbapi

auth, args = os.environ["BB_PC_AUTH"], sys.argv[1:]
post = lambda b, t=60: bbapi.call("/api/pc", b, auth=auth, timeout=t)  # noqa: E731


def fail(d):
    if d.get("error"):
        sys.exit(f"[builderbot] ERROR: {d['error']}")


def take(name):
    if name in args:
        i = args.index(name)
        if i + 1 >= len(args):
            sys.exit(f"[builderbot] ERROR: {name} needs a value after it")
        v = args[i + 1]
        del args[i:i + 2]
        return v
    return ""


if not args or args[0] in ("ls", "list"):
    d = post({"action": "lent"})
    fail(d)
    print(f"Use a lent PC: {d.get('mode')}")
    if not d.get("pcs"):
        print("no PC lends anything to this project now: its person sets it up in the Windows companion, "
              "which lends it while it runs")
    for p in d.get("pcs") or []:
        print(f"{p['name']} ({p['account']}): {', '.join(p['verbs'])}")
    sys.exit(0)

why, body = take("--why"), take("--body")
verb = args.pop(0)
call = {}
if verb == "editor-call":
    if len(args) < 2:
        sys.exit("usage: bb pc editor-call METHOD PATH [--body JSON] [--why \"...\"]")
    call = {"method": args[0], "path": args[1], "body": body}
d = post({"action": "run", "verb": verb, "args": call, "why": why})
fail(d)
print(f"[builderbot] asked {d['pc']} to {verb}" + (": its person is asked first" if d.get("mode") == "ask" else ""),
      flush=True)
end = time.time() + 900
while time.time() < end:
    r = post({"action": "result", "id": d["id"], "wait": 25}, 40)
    fail(r)
    if r["state"] in ("done", "refused", "lapsed"):
        res = r.get("result") or {}
        if r["state"] == "lapsed":
            sys.exit(f"[builderbot] ERROR: {d['pc']} did not take it up; is the companion running there?")
        if res.get("refused"):
            sys.exit(f"[builderbot] ERROR: {d['pc']}'s person said no" + (f": {res['text']}" if res.get("text") else ""))
        if res.get("text"):
            sys.stdout.write(res["text"] if res["text"].endswith("\n") else res["text"] + "\n")
        if res.get("picture"):
            print(f"[builderbot] the picture is {res['picture']} in the project")
        sys.exit(0 if res.get("ok") else 1)
sys.exit(f"[builderbot] ERROR: {d['pc']} took longer than 15 minutes; bb pc result is not kept past that")
