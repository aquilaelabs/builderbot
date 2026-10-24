"""State 4 to 5: Archive is out of sight only, and a lock says whose it is
(R119, the operator, 23 Oct).

  * locked-projects.json was the Archive button's list: a project on it was
    folded away AND locked. Every name on it moves to archived-projects.json,
    which is what pressing Archive meant, and the project is no longer
    locked: it works again for everybody on it.
  * locked-projects.json becomes {name: {by, admin}}, a lock its owner or an
    administrator sets from now on; it starts empty.

Idempotent: a list already moved is a dictionary, and is left as it is.
Never edited once shipped (stateversion.py).
"""
import json
from pathlib import Path


def run(ctx):
    state = Path(ctx["state"])
    locks = state / "locked-projects.json"
    try:
        was = json.loads(locks.read_text())
    except (OSError, ValueError):
        return
    if not isinstance(was, list):
        return
    names = {x for x in was if isinstance(x, str)}
    archived = state / "archived-projects.json"
    try:
        have = json.loads(archived.read_text())
        have = {x for x in have if isinstance(x, str)} if isinstance(have, list) else set()
    except (OSError, ValueError):
        have = set()
    archived.write_text(json.dumps(sorted(names | have)) + "\n")
    locks.write_text("{}\n")
    if names:
        print(f"dashboard: {len(names)} archived project(s) kept out of sight and unlocked (R119)", flush=True)
