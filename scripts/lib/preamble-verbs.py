"""Behind `bb preamble` (cmd_preamble in bb): what a session started on this
project is handed, the house rules, the open roadmap and the open bugs,
in the order it reads them, assembled once by dashboard/preamble.py so
the Briefing tab cannot drift from what a session actually gets.

Arguments: the dashboard directory, the project, and --json for the
payload rather than the text. DASHBOARD_STATE says where the notebook's
files are.
"""
import json
import os
import sys

d, proj, op = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, d)
import statefile, rules, roadmap, bugs, preamble, prefs, design
state = os.environ.get("DASHBOARD_STATE", "/config")
# Reading only: none of the callbacks a write would need are passed, and the
# three stores take them as optional for exactly this case.
rules.configure(write_json=statefile.write_json, state=state)
roadmap.configure(write_json=statefile.write_json, state=state)
bugs.configure(write_json=statefile.write_json, state=state)
prefs.configure(write_json=statefile.write_json, state=state)
# The design too: the briefing says whether the notebook holds one, and
# unconfigured the store read no file, so every session started on a
# designed project was told its Design view was empty (B355).
design.configure(workspace=os.environ.get("WORKSPACE", "/workspace"), state=state,
                 write_json=statefile.write_json)
preamble.configure(rules_mod=rules, roadmap_mod=roadmap, bugs_mod=bugs, prefs_mod=prefs)
# The account the session is for (bb-tty hands it over as BB_UID): its own
# reply style on the project rides the block.
mine = prefs.all_for_user(os.environ.get("BB_UID", "")).get(proj) or {}
p = preamble.payload(proj, reply=mine.get("reply") or "", asks=mine.get("asks") or "")
if op == "--json":
    print(json.dumps(p))
else:
    # No trailing newline added: this is handed to `claude` as one argument,
    # and the caller tests it with [ -z ].
    sys.stdout.write(p["text"])
    # Said on stderr so it cannot join the block itself. The launcher shows
    # this to whoever opened the terminal; a list nobody can afford is a
    # thing to hear about once rather than to discover as a session that has
    # not read half of it.
    if p["capped"]:
        print(f"WARNING: this project's rules, roadmap and bugs are "
              f"{p['bytes']} bytes and only the first {p['max']} are in a "
              f"session's prompt.", file=sys.stderr)
        print("Trim the list with `bb roadmap`, or the rest of it is invisible "
              "to every session started here.", file=sys.stderr)
