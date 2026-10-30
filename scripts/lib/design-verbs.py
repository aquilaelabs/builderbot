"""Behind `bb design` (cmd_design in bb): a project's design language and
its pages, through the controller's API as the caller (design.py on the
dashboard's side), which is where the words are made.

The first argument is the verb: nothing or `list` prints the language in a
line and the pages; `show` prints the prompt for the language, or for one
page named by its id or its name; `file` prints docs/design-language.md as
the notebook would write it, for `bb design file > docs/design-language.md`,
and `file --from FILE` the same from a record given (what `json` prints,
edited) rather than the saved one, so a branch writes it from its own design;
`json` prints the record (language, pages, and the presets they are drawn
from: every kind, template, scheme and choice by key); `schema` prints the
record's shape with every limit (B342); `save FILE` (or `-`
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

import dash  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dashboard"))
import records  # noqa: E402

# `--format json|yaml|markdown` on list or show (R167): the record `json`
# prints, in that form; a design is one record of its pages and themes.
fmt, argv = dash.format_flag(sys.argv[1:])
verb = argv[0] if argv else "list"
auth = os.environ["BB_DESIGN_AUTH"]
proj = os.environ["BB_DESIGN_PROJECT"]
USAGE = "usage: bb design [list | show [ID|NAME] | file [--from FILE] | json | schema | save FILE]"


def fail(msg):
    sys.exit(f"[builderbot] ERROR: {msg}")


if verb == "save" and (len(argv) < 2 or argv[1] in ("-h", "--help")):
    # Help, not a file called -h (B342): the shape and every limit.
    r = bbapi.call("/api/design?project=" + urllib.parse.quote(proj) + "&show=schema", auth=auth)
    print("bb design save FILE (or - for stdin): a JSON file of this shape, saved whole")
    print()
    print(r.get("text", "") if isinstance(r, dict) else "")
    raise SystemExit(0 if len(argv) > 1 else 1)
def read_record(src):
    """A record of the shape bb design json prints, from a file or stdin."""
    try:
        rec = json.loads(sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read())
    except (OSError, ValueError) as e:
        fail(f"could not read {src}: {e}")
    if not isinstance(rec, dict):
        fail("the record is an object with language and pages")
    return rec


if verb == "file" and len(argv) > 1:
    # From a record given rather than the saved one (B227): a branch writes
    # the file from its own design, not from what other branches saved.
    if argv[1] != "--from" or len(argv) != 3:
        fail("usage: bb design file [--from FILE]")
    rec = read_record(argv[2])
    r = bbapi.call("/api/design", {"action": "render", "project": proj,
                                   "language": rec.get("language") or {},
                                   "pages": rec.get("pages") or []}, auth=auth)
    if not isinstance(r, dict):
        fail("the controller answered something that is not a design")
    if r.get("error"):
        fail(r["error"])
    text = str(r.get("text") or "")
    sys.stdout.write(text + ("" if text.endswith("\n") else "\n"))
    raise SystemExit(0)

if verb == "save":
    rec = read_record(argv[1])
    r = bbapi.call("/api/design", {"action": "save", "project": proj,
                                   "language": rec.get("language") or {},
                                   "pages": rec.get("pages") or []}, auth=auth)
    if not isinstance(r, dict):
        fail("the controller answered something that is not a design")
    if r.get("error"):
        fail(r["error"])
    if r.get("held"):
        print(f"held for the operator's approval on {proj}'s notebook (Agents may: Add to the design is ask): "
              f"{r['held'].get('summary', '')}")
        raise SystemExit(0)
    n = len(r.get("pages") or [])
    print(f"saved {proj}'s design: {n} page{'' if n == 1 else 's'}; the notebook's Design view shows it, "
          "and bb design file prints docs/design-language.md from it")
    raise SystemExit(0)

if verb == "show":
    which = " ".join(argv[1:]).strip() or "language"
elif verb in ("list", "file", "json", "schema"):
    which = "json" if fmt != "text" and verb in ("list", "json") else verb
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
if fmt not in ("text", "json") and which == "json":
    rec = json.loads(text)
    pages = rec.get("pages") if isinstance(rec, dict) and isinstance(rec.get("pages"), list) else [rec]
    text = records.dump(records.document("design", pages, proj), fmt)
sys.stdout.write(text + ("" if text.endswith("\n") else "\n"))
