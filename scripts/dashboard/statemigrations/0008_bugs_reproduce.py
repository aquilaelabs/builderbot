"""State 7 to 8: whether each bug and each diagnostics report reproduces.

  * A report says how to reproduce it and now whether that works: always,
    sometimes, once or untried (R124). Every bug in the tracker and every
    report in the diagnostics before the field is untried, which is all
    the record knew of it; nothing is guessed from its repro.

Idempotent: a row that already says is left as it is.
Never edited once shipped (stateversion.py).
"""
import json
import os
from pathlib import Path


def _rewrite(path, fill):
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return 0
    n = fill(d)
    if n:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(d, indent=2) + "\n")
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    return n


def _bugs(d):
    n = 0
    for rows in ((d.get("projects") or {}).values() if isinstance(d, dict) else ()):
        for b in rows if isinstance(rows, list) else ():
            if isinstance(b, dict) and not b.get("reproduces"):
                b["reproduces"] = "untried"
                n += 1
    return n


def _reports(d):
    n = 0
    for r in (d.get("reports") or []) if isinstance(d, dict) else ():
        if isinstance(r, dict) and not r.get("reproduces"):
            r["reproduces"] = "untried"
            n += 1
    return n


def run(ctx):
    state = Path(ctx["state"])
    n = _rewrite(state / "bugs.json", _bugs) + _rewrite(state / "reports.json", _reports)
    if n:
        print(f"dashboard: {n} bug(s) and report(s) marked as not yet tried to reproduce", flush=True)
