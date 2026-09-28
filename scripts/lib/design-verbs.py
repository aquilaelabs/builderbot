"""Behind `bb design` (cmd_design in bb): a project's design language and
its pages, read from the controller as the caller (design.py on the
dashboard's side), which is where the words are made.

The first argument is the verb: nothing or `list` prints the language in a
line and the pages; `show` prints the prompt for the language, or for one
page named by its id or its name; `file` prints docs/design-language.md as
the notebook would write it, for `bb design file > docs/design-language.md`.
BB_DESIGN_AUTH is the auth header and BB_DESIGN_PROJECT the project.
"""
import os
import sys
import urllib.parse

import bbapi

argv = sys.argv[1:]
verb = argv[0] if argv else "list"
auth = os.environ["BB_DESIGN_AUTH"]
proj = os.environ["BB_DESIGN_PROJECT"]

if verb == "show":
    which = " ".join(argv[1:]).strip() or "language"
elif verb in ("list", "file"):
    which = verb
else:
    sys.exit("usage: bb design [list | show [ID|NAME] | file]")

r = bbapi.call("/api/design?project=" + urllib.parse.quote(proj) + "&show=" + urllib.parse.quote(which), auth=auth)
if not isinstance(r, dict):
    sys.exit("[builderbot] ERROR: the controller answered something that is not a design")
if r.get("error"):
    sys.exit(f"[builderbot] ERROR: {r['error']}")
sys.stdout.write(str(r.get("text") or "") + ("" if str(r.get("text") or "").endswith("\n") else "\n"))
