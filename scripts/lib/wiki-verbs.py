"""Behind `bb wiki` (cmd_wiki in bb): the project's wiki, through the
controller's API as the caller (wiki.py on the dashboard's side).

    bb wiki                       the pages: name, size, who changed it last
    bb wiki show NAME             one page's Markdown, as it is kept
    bb wiki save NAME FILE|-      write a page whole (new or a rewrite)
    bb wiki rm NAME               take a page out
    bb wiki mv OLD NEW            rename one
    bb wiki history               the last changes, newest first

A save or a removal is the project's dial, Claude may: Write the wiki:
auto lands it, ask holds it for the operator, deny refuses it. A rewrite is
checked against the page as it was when the save began, so a person's edit
in between is refused rather than overwritten; --base REV checks against
the one `bb wiki show --rev` printed instead. BB_WIKI_AUTH is the auth
header and BB_WIKI_PROJECT the project.
"""
import os
import sys
import time
import urllib.parse

import bbapi

argv = sys.argv[1:]
verb = argv[0] if argv else "list"
auth = os.environ["BB_WIKI_AUTH"]
proj = os.environ["BB_WIKI_PROJECT"]
USAGE = ("usage: bb wiki [list | show NAME [--rev] | save NAME FILE|- [--why \"...\"] [--base REV] | "
         "rm NAME [--why \"...\"] | mv OLD NEW | history]")


def fail(msg):
    sys.exit(f"[builderbot] ERROR: {msg}")


def opt(name):
    if name in argv:
        i = argv.index(name)
        if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
            fail(f"{name} takes a value")
        v = argv[i + 1]
        del argv[i:i + 2]
        return v
    return None


def get(page=""):
    q = "/api/wiki?project=" + urllib.parse.quote(proj) + ("&page=" + urllib.parse.quote(page) if page else "")
    r = bbapi.call(q, auth=auth)
    if not isinstance(r, dict):
        fail("the controller answered something that is not a wiki")
    return r


def post(body):
    r = bbapi.call("/api/wiki", dict(body, project=proj), auth=auth, timeout=60)
    if not isinstance(r, dict):
        fail("the controller answered something that is not a wiki")
    if r.get("error"):
        fail(r["error"])
    return r


def when(t):
    return time.strftime("%d %b %H:%M", time.localtime(t)) if t else ""


why = opt("--why") or ""
base = opt("--base")
if verb in ("-h", "--help"):
    print(__doc__.split("\n\n")[1])
    raise SystemExit(0)
if verb == "list":
    r = get()
    if r.get("error"):
        fail(r["error"])
    rem = r.get("remote") or {}
    print(f"{proj}'s wiki: {len(r.get('pages') or [])} page(s)"
          + (f", on {rem['label']}" if rem.get("label") else ", no remote: the view exports it as a zip")
          + f"; Claude may: Write the wiki is {r.get('gate') or 'auto'}")
    for p in r.get("pages") or []:
        print(f"  {p['name']:<32} {p['size']:>7} B  {p.get('by') or '':<16} {when(p.get('at'))}")
elif verb == "show" and len(argv) >= 2:
    r = get(argv[1])
    if r.get("error"):
        fail(r["error"])
    if "--rev" in argv:
        print(r["rev"])
    else:
        sys.stdout.write(r["text"])
elif verb == "save" and len(argv) >= 3:
    name, src = argv[1], argv[2]
    try:
        text = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
    except OSError as e:
        fail(f"could not read {src}: {e}")
    if base is None:
        cur = get(name)
        base = "" if cur.get("error") else cur.get("rev", "")
    r = post({"action": "save", "name": name, "text": text, "base": base, "why": why})
    if r.get("held"):
        print(f"held for the operator's approval on {proj}'s notebook (Claude may: Write the wiki is ask): "
              f"{r['held'].get('summary', '')}")
    elif r.get("unchanged"):
        print(f"{r['name']}: unchanged")
    else:
        print(f"saved {r['name']} in {proj}'s wiki")
elif verb == "rm" and len(argv) >= 2:
    r = post({"action": "remove", "name": argv[1], "why": why})
    print(f"held for the operator's approval: {r['held'].get('summary', '')}" if r.get("held")
          else f"removed {argv[1]} from {proj}'s wiki")
elif verb == "mv" and len(argv) >= 3:
    r = post({"action": "rename", "name": argv[1], "to": argv[2]})
    print(f"renamed {argv[1]} to {r.get('name')}")
elif verb == "history":
    r = get()
    if r.get("error"):
        fail(r["error"])
    for h in r.get("history") or []:
        print(f"  {h['commit']}  {when(h['at'])}  {h['by']:<16} {h['what']}")
else:
    fail(USAGE)
