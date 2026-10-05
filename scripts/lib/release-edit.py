"""Behind `bb version release --edit` (R139): the published release's notes
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
why, tag, notes, attach = "", "", None, []
root = os.path.realpath(os.path.join(os.environ.get("BB_WORKSPACE", "/workspace"), proj))
while rest:
    flag = rest.pop(0)
    if flag not in ("--why", "--tag", "--notes", "--attach") or not rest:
        fail(f"bb version release --edit takes --why, --tag, --notes FILE and --attach FILE, "
             f"each with its value, not {flag}" + ("" if rest else " alone"))
    val = rest.pop(0)
    if flag == "--why":
        why = val
    elif flag == "--tag":
        tag = val
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
r = bbapi.call("/api/version", {"action": "release-edit", "project": proj, "component": comp, "why": why,
                                "tag": tag, "notes": notes, "attach": attach}, auth=auth, timeout=600)
if r.get("error"):
    fail(f"[builderbot] ERROR: {r['error']}")
if r.get("id") and not r.get("edited"):
    print(f"[builderbot] asked {r.get('to') or 'the project owner'} (#{r['id']}) to edit the release, "
          "waiting up to 15 minutes for Approve in their bell", file=sys.stderr)
    o = waits.outcome(auth, r["id"], "the edit was not allowed")
    if o.get("code"):
        fail(f"[builderbot] ERROR: {o.get('out') or 'the release was not edited'}")
    print(o.get("out") or "edited")
    raise SystemExit(0)
print(r.get("said") or "edited")
