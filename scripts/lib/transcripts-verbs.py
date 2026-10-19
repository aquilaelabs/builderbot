"""Behind `bb transcripts` (cmd_transcripts in bb): the account's own
conversations with Claude on a project, through the controller's API as
the caller (transcripts.py on the dashboard's side, the Profile page's
list and download). `list` prints them newest first with the first thing
typed; `show ID [--tz ZONE]` prints one as the Profile's download reads,
stamped in ZONE (the controller's own when none); `fetch ID` copies the
file itself into this machine's folder for it, which is how a synced node
resumes a conversation it does not have (B613). A session reads its
account's conversations on its own project and on one its project reads
(`bb -p NAME transcripts`), and nobody else's: the controller looks under
the account's transcripts and nowhere else. `audit [DAYS]` is `bb rules
audit`: the same conversations counted against the rules that refuse
commands (R200). BB_TRANSCRIPTS_AUTH is the
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

if verb == "audit":
    # `bb rules audit [DAYS]` (R200): the account's conversations here over
    # the last DAYS, counted against the rules that refuse commands.
    days = argv[1] if len(argv) > 1 and argv[1].isdigit() else "7"
    q = urllib.parse.urlencode({"project": proj, "audit": days})
    r = bbapi.call(f"/api/transcripts?{q}", auth=auth, timeout=300)
    if not isinstance(r, dict) or r.get("error"):
        fail(r.get("error") if isinstance(r, dict) else "the controller answered something that is not an audit")
    a = r.get("audit") or {}
    print(f"your conversations on {proj} over the last {a.get('days')} days: "
          f"{a.get('conversations', 0)}, with {a.get('bash', 0)} shell commands"
          + (f" (the newest {48} MB of {a['partial']} long one{'s' if a['partial'] != 1 else ''})" if a.get("partial") else ""))
    g = a.get("guards") or {}
    if g:
        print("commands a rule refuses (refused since the guard, or would have been before it):")
        for name, n in sorted(g.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>5}  {name}")
            for ex in (a.get("examples") or {}).get(name, []):
                print(f"         $ {ex[:120]}")
    else:
        print("no command a rule refuses")
    print(f"refused by the guard: {a.get('refused', 0)}")
    print(f"the code map asked: {a.get('map', 0)}, grep and Grep: {a.get('grep', 0)}")
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

if verb == "fetch":
    # The conversation as Claude Code wrote it, into this machine's folder
    # for it, so a node holding its projects as a synced copy can resume one
    # it does not have (B613): bb-tty runs this before claude --resume. A
    # copy here that is as long is left alone.
    import re
    sid = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else ""
    if not sid or not re.fullmatch(r"[0-9A-Za-z-]+", sid):
        fail("bb transcripts fetch ID [--into DIR]: the id from bb transcripts")
    into = ""
    if "--into" in argv:
        k = argv.index("--into")
        into = argv[k + 1] if k + 1 < len(argv) else ""
    if not into:
        into = os.path.join(os.path.expanduser("~/.claude/projects"), re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()))
    dest = os.path.join(into, sid + ".jsonl")
    have = os.path.getsize(dest) if os.path.isfile(dest) else -1
    q = urllib.parse.urlencode({"project": proj, "id": sid, "as": "raw", "have": have})
    try:
        c, base = bbapi._conn(600)
        c.request("GET", f"{base}/api/transcript?{q}", None, {"Authorization": auth})
        r = c.getresponse()
        if r.status != 200 or r.getheader("Content-Type", "").startswith("application/json"):
            import json
            got = json.loads(r.read() or b"{}")
            c.close()
            if r.status != 200:
                fail(got.get("error") or f"HTTP {r.status}")
            print(f"{sid} is here already")
            raise SystemExit(0)
        os.makedirs(into, exist_ok=True)
        tmp = os.path.join(into, f".bbsync-{sid}.jsonl")
        n = 0
        with open(tmp, "wb") as f:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                f.write(chunk)
                n += len(chunk)
        c.close()
        want = int(r.getheader("Content-Length") or n)
        if n != want:
            os.remove(tmp)
            fail(f"the download stopped at {size(n)} of {size(want)}")
        mt = int(r.getheader("X-Mtime-Ms") or 0)
        if mt:
            # The controller's time, so the node's mirror reads the two as
            # one file and sends nothing back.
            os.utime(tmp, ns=(mt * 1_000_000, mt * 1_000_000))
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    except OSError as e:
        fail(f"could not fetch {sid}: {e}")
    print(f"fetched {sid} ({size(n)}) from the controller")
    raise SystemExit(0)

fail("bb transcripts [list | show ID [--tz ZONE] | fetch ID [--into DIR]]")
