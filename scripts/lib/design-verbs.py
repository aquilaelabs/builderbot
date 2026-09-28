"""Behind `bb design` (cmd_design in bb): a project's design language and
its pages, through the controller's API as the caller (design.py on the
dashboard's side), which is where the words are made.

The first argument is the verb: nothing or `list` prints the language in a
line and the pages; `show` prints the prompt for the language, or for one
page named by its id or its name; `file` prints docs/design-language.md as
the notebook would write it, for `bb design file > docs/design-language.md`;
`json` prints the record (language, pages, and the presets they are drawn
from: every kind, template, scheme and choice by key); `save FILE` (or `-`
for stdin) writes a record of that shape back, whole, which is how a
session asked to put a design language into the notebook does it. A page
without an id is new; one with its id replaces that page; one left out is
removed. BB_DESIGN_AUTH is the auth header and BB_DESIGN_PROJECT the project.
"""
import json
import os
import sys
import urllib.parse

import bbapi

argv = sys.argv[1:]
verb = argv[0] if argv else "list"
auth = os.environ["BB_DESIGN_AUTH"]
proj = os.environ["BB_DESIGN_PROJECT"]
USAGE = "usage: bb design [list | show [ID|NAME] | file | json | save FILE]"


def fail(msg):
    sys.exit(f"[builderbot] ERROR: {msg}")


if verb == "save":
    src = argv[1] if len(argv) > 1 else ""
    if not src:
        fail("bb design save FILE: a JSON file of the shape bb design json prints, or - for stdin")
    try:
        raw = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
        rec = json.loads(raw)
    except (OSError, ValueError) as e:
        fail(f"could not read {src}: {e}")
    if not isinstance(rec, dict):
        fail("the record is an object with language and pages")
    r = bbapi.call("/api/design", {"action": "save", "project": proj,
                                   "language": rec.get("language") or {},
                                   "pages": rec.get("pages") or []}, auth=auth)
    if not isinstance(r, dict):
        fail("the controller answered something that is not a design")
    if r.get("error"):
        fail(r["error"])
    n = len(r.get("pages") or [])
    print(f"saved {proj}'s design: {n} page{'' if n == 1 else 's'}; the notebook's Design view shows it, "
          "and bb design file prints docs/design-language.md from it")
    raise SystemExit(0)

if verb == "show":
    which = " ".join(argv[1:]).strip() or "language"
elif verb in ("list", "file", "json"):
    which = verb
elif verb in ("-h", "--help"):
    print(USAGE)
    raise SystemExit(0)
else:
    fail(USAGE)

r = bbapi.call("/api/design?project=" + urllib.parse.quote(proj) + "&show=" + urllib.parse.quote(which), auth=auth)
if not isinstance(r, dict):
    fail("the controller answered something that is not a design")
if r.get("error"):
    fail(r["error"])
text = str(r.get("text") or "")
sys.stdout.write(text + ("" if text.endswith("\n") else "\n"))
