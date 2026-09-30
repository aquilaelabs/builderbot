"""Behind `bb transcripts` (cmd_transcripts in bb): the account's own
conversations with Claude on a project, through the controller's API as
the caller (transcripts.py on the dashboard's side, the Profile tab's
list and download). `list` prints them newest first with the first thing
typed; `show ID [--tz ZONE]` prints one as the Profile's download reads,
stamped in ZONE (the controller's own when none). A session reads its
account's conversations on its own project and on one its project reads
(`bb -p NAME transcripts`), and nobody else's: the controller looks under
the account's transcripts and nowhere else. BB_TRANSCRIPTS_AUTH is the
auth header and BB_TRANSCRIPTS_PROJECT the project.
"""
import os
import sys
import time
import urllib.parse

import bbapi

argv = sys.argv[1:]
verb = argv[0] if argv else "list"
auth = os.environ["BB_TRANSCRIPTS_AUTH"]
proj = os.environ["BB_TRANSCRIPTS_PROJECT"]


def fail(msg):
    sys.exit(f"[builderbot] ERROR: {msg}")


def size(n):
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(1, n // 1024)} KB"


if verb == "list":
    r = bbapi.call(f"/api/transcripts?project={urllib.parse.quote(proj)}", auth=auth)
    if not isinstance(r, dict) or r.get("error"):
        fail(r.get("error") if isinstance(r, dict) else "the controller answered something that is not a list")
    rows = r.get("rows") or []
    if not rows:
        print(f"no conversations of yours on {proj} yet")
        raise SystemExit(0)
    print(f"your conversations with Claude on {proj}, newest first:")
    for row in rows:
        when = time.strftime("%d %b %H:%M", time.localtime(int(row.get("at") or 0)))
        print(f"  {row['id']}  {when}  {size(int(row.get('bytes') or 0)):>7}  {row.get('first') or ''}")
    print("bb transcripts show ID prints one: what was said, every command Claude ran and what it answered")
    raise SystemExit(0)

if verb == "show":
    sid = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else ""
    if not sid:
        fail("bb transcripts show ID [--tz ZONE]: the id from bb transcripts")
    tz = ""
    if "--tz" in argv:
        k = argv.index("--tz")
        tz = argv[k + 1] if k + 1 < len(argv) else ""
    q = urllib.parse.urlencode({"project": proj, "id": sid, "tz": tz, "as": "json"})
    r = bbapi.call(f"/api/transcript?{q}", auth=auth)
    if not isinstance(r, dict) or r.get("error"):
        fail(r.get("error") if isinstance(r, dict) else "the controller answered something that is not a transcript")
    sys.stdout.write(r.get("text") or "")
    raise SystemExit(0)

fail("bb transcripts [list | show ID [--tz ZONE]]")
