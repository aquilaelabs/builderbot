"""State 15 to 16: the static analysis scan is the Scanners page's (R145,
the operator, 26 Oct).

  * an install's scan schedule (schedules.json's built-in `scan` row: on,
    its timetable) becomes the Scanners page's schedule (scanners.json),
    on with the same timetable where it was on; the row itself stays in
    schedules.json, unlisted, so nothing is lost if a person goes back;
    the node and the three paths it named are not carried: the scanners
    are deployed per node from the page, and read the node's own project
    copies, so the paths mean nothing now;
  * the number moves because an older build would list the scan row as a
    schedule again and run tools/scan.sh, which this image no longer
    carries, on a node that has the Scanners' compose project instead.

Never edited once shipped (stateversion.py).
"""
import json
from pathlib import Path


def run(ctx):
    state = Path(ctx["state"])
    try:
        d = json.loads((state / "schedules.json").read_text())
    except (OSError, ValueError):
        return
    row = ((d.get("schedules") if isinstance(d, dict) else None) or {}).get("scan")
    if not isinstance(row, dict) or not row.get("on"):
        return
    p = state / "scanners.json"
    try:
        sc = json.loads(p.read_text())
        sc = sc if isinstance(sc, dict) else {}
    except (OSError, ValueError):
        sc = {}
    sc.setdefault("schedule", {})
    sc["schedule"]["on"] = True
    sc["schedule"]["cron"] = str(row.get("cron") or "0 4 * * 0")
    sc["schedule"].pop("due", None)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sc, indent=1))
    tmp.replace(p)
