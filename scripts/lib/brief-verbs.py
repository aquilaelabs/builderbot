"""Behind `bb brief` (cmd_brief in bb): a new project's brief, through the
controller's API as the caller (brief.py on the dashboard's side).

The first argument is the verb: show prints the brief waiting in the tree,
or the one kept after it left; take is bb-tty's, starting a new session,
and prints the brief this account staged with Build it, which leaves the
tree as it is taken, or nothing. A take never fails a session's start: any
error prints nothing. BB_BRIEF_AUTH is the auth header and BB_BRIEF_PROJECT
the project.
"""
import os
import sys
import time
import urllib.parse

import bbapi

verb = sys.argv[1] if len(sys.argv) > 1 else "show"
auth = os.environ["BB_BRIEF_AUTH"]
proj = os.environ["BB_BRIEF_PROJECT"]

if verb == "take":
    r = bbapi.call("/api/brief", {"action": "take", "project": proj}, auth=auth)
    text = r.get("text") if isinstance(r, dict) else ""
    if text:
        sys.stdout.write(str(text) + "\n")
    raise SystemExit(0)

d = bbapi.call("/api/brief?project=" + urllib.parse.quote(proj), auth=auth)
if not isinstance(d, dict):
    sys.exit("[builderbot] ERROR: the controller answered something that is not a brief")
if d.get("error"):
    sys.exit(f"[builderbot] ERROR: {d['error']}")
if d.get("pending"):
    print(f"{proj}'s brief, waiting for its first Claude session:\n")
    print(d.get("text") or "")
    raise SystemExit(0)
kept = d.get("kept")
if not isinstance(kept, dict) or not kept:
    print(f"{proj} was not started from a brief")
    raise SystemExit(0)
when = time.strftime("%d %b %Y", time.localtime(kept.get("at") or 0))
how = "sent to the first session" if kept.get("sent") else "set aside when the first session started without it"
print(f"{proj} was started from this brief, {how} on {when}"
      + (f" by {kept['by']}" if kept.get("by") else "") + ":\n")
print(kept.get("text") or "")
