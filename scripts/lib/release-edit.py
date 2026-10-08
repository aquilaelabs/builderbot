"""Behind `bb version release --edit` (R139), and --remove, which takes files
off the release as its own ask: the published release's notes
replaced and files attached, made by the controller with the project's own
token under Claude may: Tag and publish a release, every edit its own ask.

Run where it is typed, never relayed: the notes are a file the session
wrote (its scratchpad, or stdin), and a relayed verb ran on the
controller, which sees /workspace and nothing else, so a scratchpad file
was "No such file or directory" and stdin arrived empty (report 60,
Shebang-DevBoard, 5 Oct). Only the API call goes to the controller.

Arguments: the project, then the words after `bb version`: [--for DIR]
release --edit --why "..." [--tag TAG] [--notes FILE|-] [--attach FILE]...
BB_VERSION_AUTH is the session's credential, BB_WORKSPACE where the
projects are.
"""
import os
import sys

import bbapi
import waits


def fail(msg):
    print(msg, file=sys.stderr)
    raise SystemExit(1)


proj, rest = sys.argv[1], list(sys.argv[2:])
comp = ""
if "--for" in rest:
    i = rest.index("--for")
    if i + 1 >= len(rest):
        fail("--for needs a component directory")
    comp = rest[i + 1]
    del rest[i:i + 2]
for word in ("release", "--edit"):
    if word in rest:
        rest.remove(word)
why, tag, notes, attach, remove = "", "", None, [], []
root = os.path.realpath(os.path.join(os.environ.get("BB_WORKSPACE", "/workspace"), proj))
while rest:
    flag = rest.pop(0)
    if flag not in ("--why", "--tag", "--notes", "--attach", "--remove") or not rest:
        fail(f"bb version release --edit takes --why, --tag, --notes FILE and --attach FILE, and --remove "
             f"takes --why, --tag and NAME, each with its value, not {flag}" + ("" if rest else " alone"))
    val = rest.pop(0)
    if flag == "--why":
        why = val
    elif flag == "--tag":
        tag = val
    elif flag == "--remove":
        remove.append(val)
    elif flag == "--notes":
        try:
            notes = sys.stdin.read() if val == "-" else open(val, encoding="utf-8").read()
        except OSError as e:
            fail(f"--notes {val}: {e.strerror}")
        except UnicodeDecodeError:
            fail(f"--notes {val}: not UTF-8 text")
    else:
        p = os.path.realpath(val)
        if not p.startswith(root + os.sep):
            fail(f"--attach {val}: a file in {proj}, a build in dist/ or a committed one")
        attach.append(os.path.relpath(p, root))
auth = os.environ.get("BB_VERSION_AUTH", "")
# Taking files off is its own ask and never part of an edit (the operator,
# 5 Oct): the person reading it sees a removal and nothing else.
if remove and (notes is not None or attach):
    fail("a removal is its own ask: run --remove without --notes and --attach, and the edit after it")
if remove:
    body = {"action": "release-remove", "project": proj, "component": comp, "why": why, "tag": tag, "remove": remove}
else:
    body = {"action": "release-edit", "project": proj, "component": comp, "why": why,
            "tag": tag, "notes": notes, "attach": attach}
r = bbapi.call("/api/version", body, auth=auth, timeout=600)
if r.get("error"):
    fail(f"[builderbot] ERROR: {r['error']}")
what = "take files off the release" if remove else "edit the release"
if r.get("id") and not (r.get("edited") or r.get("removed")):
    print(f"[builderbot] asked {r.get('to') or 'the project owner'} (#{r['id']}) to {what}, "
          "waiting up to 15 minutes for Approve in their bell", file=sys.stderr)
    o = waits.outcome(auth, r["id"], f"it was not allowed to {what}")
    if o.get("code"):
        fail(f"[builderbot] ERROR: {o.get('out') or 'nothing changed'}")
    print(o.get("out") or "done")
    raise SystemExit(0)
print(r.get("said") or "done")
