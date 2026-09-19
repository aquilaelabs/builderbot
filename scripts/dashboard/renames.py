"""State this controller wrote under names it no longer uses, moved once.

The notebook's roadmap was called "todo" in its file, its keys and its tab,
and the operator asked for one name everywhere. The code says roadmap now;
what an earlier build already wrote to /config is the operator's roadmap and
their open tabs, and it has to come across rather than be left behind under
a name nothing reads. So at startup, before anything opens these files:

  * todos.json becomes roadmap.json, and inside it the per-project "todo"
    keys of `unsaved`, `bump` and `seen` become "roadmap";
  * a saved tab of kind "todo" (the notebook) becomes kind "notebook".

Each step does nothing when there is nothing to move, so this runs on every
start at the cost of a stat. It exists for the one controller that ran a
build from before the rename, and goes once that controller has started on
this one.
"""
import json
import os
from pathlib import Path

# The tab kinds that were renamed: {old: new}.
TAB_KINDS = {"todo": "notebook"}
# The roadmap's own kind key inside its file.
ROADMAP_KIND = ("todo", "roadmap")


def _read(p):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _write(p, d):
    tmp = p.with_name(p.name + ".renaming")
    tmp.write_text(json.dumps(d, indent=2))
    os.replace(tmp, p)


def _roadmap(state):
    old, new = state / "todos.json", state / "roadmap.json"
    if old.exists() and not new.exists():
        os.replace(old, new)
    d = _read(new)
    if not isinstance(d, dict):
        return False
    was, now = ROADMAP_KIND
    moved = False
    for section in ("unsaved", "bump"):
        for per in (d.get(section) or {}).values():
            if isinstance(per, dict) and was in per:
                per[now] = per.pop(was)
                moved = True
    for seats in (d.get("seen") or {}).values():
        for seat in (seats.values() if isinstance(seats, dict) else []):
            if isinstance(seat, dict) and was in seat:
                seat[now] = seat.pop(was)
                moved = True
    if moved:
        _write(new, d)
    return moved


def _tabs(state):
    p = state / "tabs.json"
    d = _read(p)
    if not isinstance(d, dict):
        return False
    moved = False
    for lay in (d.get("users") or {}).values():
        for t in ((lay or {}).get("tabs") or []) if isinstance(lay, dict) else []:
            if isinstance(t, dict) and t.get("kind") in TAB_KINDS:
                t["kind"] = TAB_KINDS[t["kind"]]
                moved = True
    if moved:
        _write(p, d)
    return moved


def run(state):
    """Move whatever is still under an old name. The names of what moved."""
    state = Path(state)
    done = []
    for name, step in (("roadmap", _roadmap), ("tabs", _tabs)):
        try:
            if step(state):
                done.append(name)
        except OSError:
            pass                     # a read-only or missing /config: nothing to move
    return done
