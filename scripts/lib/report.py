"""Behind `bb report` (cmd_report in bb): a problem with BuilderBot itself, from a
session on any project, sent to the controller's reports rather than the
project's tracker, and what became of one read back.

Arguments: the words of the report and its --area and --repro, or for `file`
and `close` the report's number and what follows it. BB_R_SUB is the
subcommand bb chose (add, mine, file, close), BB_R_AUTH the auth header,
BB_R_PROJECT the project, and BB_R_SELF is bb itself, which `file` runs for
the bug add.
"""
import os
import re
import subprocess
import sys
import time

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
    words, got = flags(("area", "repro"))
    d = post({"action": "add", "project": proj, "text": " ".join(words),
              "area": got.get("area", ""), "repro": got.get("repro", "")})
    fail(d)
    print(f"[builderbot] reported #{d['id']}: it is BuilderBot's to look at now, not this project's; "
          "bb report says what became of it")
elif sub == "mine":
    d = post({"action": "mine", "project": proj})
    fail(d)
    rows = d.get("reports") or []
    gone = d.get("cleared") or {}
    if gone.get("n"):
        when = time.strftime("%d %b %H:%M", time.localtime(int(gone.get("at") or 0)))
        print(f"{gone['n']} earlier report{'' if gone['n'] == 1 else 's'} from {proj or 'this project'} "
              f"{'was' if gone['n'] == 1 else 'were'} cleared by the operator on {when} (Controller settings): "
              "what became of each is in BuilderBot's own tracker, which a project that reads BuilderBot "
              "opens with bb -p BuilderBot bug")
    if not rows and not gone.get("n"):
        print(f"no reports from {proj or 'this project'} about BuilderBot")
    for r in rows:
        when = time.strftime("%d %b %H:%M", time.localtime(r.get("at") or 0))
        state = ("filed in BuilderBot's tracker" if r.get("state") == "filed"
                 else f"closed: {r.get('why') or ''}" if r.get("state") == "closed" else "open")
        print(f"  #{r['id']}  {when}  {state}")
        print(f"      {r.get('text')}")
elif sub == "close":
    if len(args) < 2:
        sys.exit('usage: bb report close N "why"')
    fail(post({"action": "close", "id": args[0], "why": " ".join(args[1:])}))
    print(f"[builderbot] report #{args[0]} closed")
else:
    words, got = flags(("sev", "as"))
    if not words:
        sys.exit("usage: bb report file N [--sev S] [--as BUG]")
    rid = words[0]
    r = post({"action": "get", "id": rid})
    fail(r)
    bug = got.get("as", "")
    if not bug:
        # Through the ordinary path, relayed on a node and held for the
        # operator where this project's settings say so, so a report filed
        # is exactly a bug somebody added.
        when = time.strftime("%d %b %Y", time.localtime(r.get("at") or 0))
        # A person's about no project (the header's Report a bug) has none.
        on = r.get("project") or ""
        where = (f"{r['by']}" + (f", on {on}" if on else ", about no project in particular") if r.get("by")
                 else f"a session on {on or 'no project'}")
        repro = " ".join(x for x in [
            r.get("repro") or "",
            f"Reported by {where}" + (f" ({r['node']})" if r.get("node") else "")
            + f", {when}" + (f", on {r['build']}" if r.get("build") else "")
            + f", as report #{r['id']}."] if x)
        # --here: filing BuilderBot's report into this tracker is the point,
        # so bug add is not to ask whether it belongs in bb report.
        p = subprocess.run([os.environ["BB_R_SELF"], "bug", "add", r.get("text") or "", "--here",
                            "--sev", got.get("sev", "medium"),
                            "--area", r.get("area") or (f"reported from {on}" if on else "reported from the dashboard"),
                            "--repro", repro], capture_output=True, text=True)
        out = (p.stdout or "") + (p.stderr or "")
        sys.stdout.write(out)
        # ...or held for approval as one, where the tracker's gate asks.
        m = re.search(r"\b(?:filed|held for approval as) (B\d+)", out)
        if p.returncode != 0 or not m:
            sys.exit(f"[builderbot] report #{rid} stays open: no bug number came back. Once the bug "
                     f"has one, bb report file {rid} --as BUG marks it")
        bug = m.group(1)
    fail(post({"action": "filed", "id": rid, "bug": bug}))
    print(f"[builderbot] report #{rid} is {bug} now; the session that reported it reads that with bb report")
