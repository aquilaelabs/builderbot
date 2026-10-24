"""Behind `bb report` (cmd_report in bb): a problem with BuilderBot itself, from a
session on any project, sent to the controller's reports rather than the
project's tracker, where whoever looks after this install's BuilderBot reads
it in the diagnostics. Nothing comes back: there is no answer to follow up.

Arguments: the words of the report and its --area, --repro and --reproduces, or for
`conversation` the report's number. BB_R_SUB is the subcommand bb chose (add,
conversation), BB_R_AUTH the auth header, BB_R_PROJECT the project.
"""
import os
import sys

import bbapi


auth, proj, sub, args = os.environ["BB_R_AUTH"], os.environ.get("BB_R_PROJECT", ""), os.environ["BB_R_SUB"], sys.argv[1:]
post = lambda b: bbapi.call("/api/reports", b, auth=auth, timeout=60)  # noqa: E731


def flags(names):
    """Words and --name VALUE pairs, in any order."""
    words, got, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if a.startswith("--") and a[2:] in names:
            if i + 1 >= len(args):
                sys.exit(f"[builderbot] ERROR: {a} needs a value after it")
            got[a[2:]] = args[i + 1]
            i += 2
            continue
        if a.startswith("--"):
            sys.exit(f"[builderbot] ERROR: bb report: no such option {a}")
        words.append(a)
        i += 1
    return words, got


def fail(d):
    if d.get("error"):
        sys.exit(f"[builderbot] ERROR: {d['error']}")


if sub == "add":
    words, got = flags(("area", "repro", "reproduces"))
    # Steps given say how often they showed it (R124): a repro reads as a
    # sure thing whether or not it is one.
    if got.get("repro") and not got.get("reproduces"):
        sys.exit("[builderbot] ERROR: say whether those steps reproduce it: --reproduces always, "
                 "sometimes, once (seen the one time) or untried")
    d = post({"action": "add", "project": proj, "text": " ".join(words),
              "area": got.get("area", ""), "repro": got.get("repro", ""),
              "reproduces": got.get("reproduces", "")})
    fail(d)
    print(f"[builderbot] reported #{d['id']}: it is in BuilderBot's diagnostics now, not this "
          "project's tracker, and nothing more is needed from this session")
else:
    if not args:
        sys.exit("usage: bb report conversation N")
    d = post({"action": "conversation", "id": args[0]})
    fail(d)
    sys.stdout.write(d.get("text") or "")
