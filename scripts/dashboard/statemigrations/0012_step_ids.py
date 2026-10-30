"""State 11 to 12: every roadmap step has an id of its own (R168, the
operator, 27 Oct).

  * each step of each open item in roadmap.json gets `sid`, [item, n], its
    item's number and its place on it as this ran, and the item `nsteps`,
    the count handed out, so a step moved to another item, split away or
    left behind by a drop of one before it is still the one its first
    number named (bb roadmap show R56.9);
  * the number moves because an item carrying `moved` (where a step went)
    and steps from other items are a shape an older build reads as that
    item's own steps, numbered afresh.

Idempotent: a step with a sid keeps it. Never edited once shipped
(stateversion.py).
"""
import json
import os
from pathlib import Path


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def run(ctx):
    f = Path(ctx["state"]) / "roadmap.json"
    try:
        d = json.loads(f.read_text())
    except (OSError, ValueError):
        return
    if not isinstance(d, dict) or not isinstance(d.get("projects"), dict):
        return
    changed = False
    for rows in d["projects"].values():
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            rid, steps = _int(row.get("id")), row.get("steps") or []
            n = _int(row.get("nsteps")) or 0
            for st in steps:
                s = st.get("sid") if isinstance(st, dict) else None
                if isinstance(s, list) and len(s) == 2 and _int(s[0]) == rid and (_int(s[1]) or 0) > n:
                    n = _int(s[1]) or 0
            for st in steps:
                if isinstance(st, dict) and not (isinstance(st.get("sid"), list) and len(st["sid"]) == 2):
                    n += 1
                    st["sid"] = [rid, n]
                    changed = True
            if (steps or n) and row.get("nsteps") != n:
                row["nsteps"] = n
                changed = True
    if changed:
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d))
        os.replace(tmp, f)
