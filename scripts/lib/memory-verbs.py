"""Behind `bb memory` (cmd_memory in bb): a repository's memories, the
account's own, through the controller's API as the caller (memory.py on the
dashboard's side, the notebook's Memory view). Every coding agent keeps
them here, in the folder Claude Code reads for that repository, so a
repository moved to another project keeps what was learned about it and a
session of any agent sees them (R152). `list` prints the index; `show NAME`
one memory whole; `add NAME --type T --about "..." BODY` writes one and its
index line; `forget NAME` removes it. `bb -p REPO memory ...` answers for
another repository of the project. BB_MEMORY_AUTH is the auth header and
BB_MEMORY_PROJECT the repository.
"""
import os
import sys
import urllib.parse
from typing import NoReturn

import bbapi

argv = sys.argv[1:]
verb = argv[0] if argv else "list"
auth = os.environ["BB_MEMORY_AUTH"]
proj = os.environ["BB_MEMORY_PROJECT"]
TYPES = ("user", "feedback", "project", "reference")


def fail(msg) -> NoReturn:
    sys.exit(f"[builderbot] ERROR: {msg}")


def read():
    r = bbapi.call(f"/api/memory?project={urllib.parse.quote(proj)}", auth=auth)
    if not isinstance(r, dict) or r.get("error"):
        fail(r.get("error") if isinstance(r, dict) else "the controller answered something that is not a list")
    return r


def post(body):
    r = bbapi.call("/api/memory", body={"project": proj, **body}, auth=auth)
    if not isinstance(r, dict):
        fail("the controller answered something that is not a result")
    if r.get("error"):
        fail(r["error"])
    return r


def named(r, name):
    file = name if name.endswith(".md") else name + ".md"
    return next((m for m in r.get("memories") or [] if m.get("file") == file or m.get("name") == name), None)


if verb == "list":
    r = read()
    ms = r.get("memories") or []
    if not ms:
        print(f"no memories of yours on {proj} yet: bb memory add saves one")
        raise SystemExit(0)
    print(f"your memories on {proj}, newest first:")
    for m in ms:
        print(f"  {m.get('name')}  [{m.get('type') or '?'}]  {m.get('hook') or m.get('description') or ''}")
    for i in r.get("issues") or []:
        print(f"  ! {i.get('text')}")
elif verb == "show":
    if len(argv) < 2:
        fail("bb memory show NAME")
    m = named(read(), argv[1])
    if not m:
        fail(f"no memory called {argv[1]} on {proj}: bb memory list names them")
    print(m.get("text") or "", end="" if (m.get("text") or "").endswith("\n") else "\n")
elif verb == "add":
    args, name, mtype, about, body = argv[1:], "", "", "", []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--type" and i + 1 < len(args):
            mtype, i = args[i + 1], i + 2
        elif a == "--about" and i + 1 < len(args):
            about, i = args[i + 1], i + 2
        elif not name:
            name, i = a, i + 1
        else:
            body.append(a)
            i += 1
    if not name or not body:
        fail('bb memory add NAME --type user|feedback|project|reference --about "one line" "what to remember"')
    if mtype not in TYPES:
        fail(f"--type is one of: {', '.join(TYPES)}")
    if not about:
        fail('--about "one line": what recall matches it against, and its line in the index')
    title = name.replace("-", " ").capitalize()
    r = post({"action": "create", "name": name, "title": title, "hook": about, "type": mtype, "body": " ".join(body)})
    print(f"saved {r.get('file')} on {proj}")
elif verb == "forget":
    if len(argv) < 2:
        fail("bb memory forget NAME")
    m = named(read(), argv[1])
    if not m:
        fail(f"no memory called {argv[1]} on {proj}")
    post({"action": "delete", "file": m["file"]})
    print(f"forgot {m['file']} on {proj}")
else:
    fail("bb memory [list | show NAME | add NAME --type T --about \"...\" BODY | forget NAME]")
