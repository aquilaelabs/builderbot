"""Behind `bb preamble` (cmd_preamble in bb): what a session started on this
project is handed, the house rules, the open roadmap and the open bugs,
in the order it reads them, assembled once by dashboard/preamble.py so
the Briefing tab cannot drift from what a session actually gets.

Arguments: the dashboard directory, the project, and --json for the
payload rather than the text, --topic SLUG for one topic of the briefing
(what `bb help TOPIC` prints), --topics for the list. DASHBOARD_STATE
says where the notebook's files are.
"""
import json
import os
import sys

d, proj, op = sys.argv[1], sys.argv[2], sys.argv[3]
arg = sys.argv[4] if len(sys.argv) > 4 else ""
sys.path.insert(0, d)
import statefile, rules, roadmap, bugs, preamble, prefs, design, registry
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
# The name each project is shown under (B1): without it a session was told
# only directories, while the person names projects as the dashboard does.
registry.configure(state=state, workspace=os.environ.get("WORKSPACE", "/workspace"),
                   write_json=statefile.write_json)
preamble.label_of = registry.label
preamble.id_of = registry.pid


def _packs():
    """The tool packs added here (R77), from the controller's own file."""
    try:
        with open(os.path.join(state, "toolpacks.json")) as f:
            packs = json.load(f).get("packs") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    return {n: {"label": (r.get("manifest") or {}).get("label") or n, "guidance": r.get("guidance") or ""}
            for n, r in packs.items() if isinstance(r, dict)}


preamble.packs_of = _packs


def node_gpu(project):
    """Whether the project's node reports an NVIDIA card (R102), read from
    the node store as it stands, read-only: what decides the briefing's GPU
    section. No store, no node or no answer is no card."""
    nid = (prefs.get(project) or {}).get("node") or ""
    if not nid:
        return False
    try:
        import nodes
        nodes.db.open_readonly(state)
        n = nodes.node(nid)
    except Exception:
        return False
    return bool(n and (n.get("reported") or {}).get("gpu_card"))


preamble.node_gpu = node_gpu
# The account the session is for (bb-tty hands it over as BB_UID): its own
# reply style on the project rides the block.
mine = prefs.all_for_user(os.environ.get("BB_UID", "")).get(proj) or {}
if op == "--topic":
    t = preamble.topic(proj, arg.strip().lower())
    if t is None:
        names = ", ".join(s for s, _, _ in preamble.topics(proj))
        sys.exit(f"[builderbot] ERROR: no topic called {arg!r} in the briefing; the topics: {names}")
    print(t)
    sys.exit(0)
if op == "--topics":
    for slug, gist, _ in preamble.topics(proj):
        print(f"  {slug:<11}{gist}")
    sys.exit(0)
p = preamble.payload(proj, reply=mine.get("reply") or "", asks=mine.get("asks") or "")
if op == "--json":
    print(json.dumps(p))
else:
    # No trailing newline added: this is handed to `claude` as one argument,
    # and the caller tests it with [ -z ].
    sys.stdout.write(p["text"])
    # Said on stderr so it cannot join the block itself: what a part left
    # out to keep to its share, which the block says to the session too.
    for note in p["notes"]:
        print(note, file=sys.stderr)
