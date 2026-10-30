"""State 17 to 18: a sign-in is held to its browser, not its whole
User-Agent string (B447).

  * each sign-in kept in logins.json held to a digest of the whole string
    is held instead to the browser it recorded in its own words ("Safari on
    iPhone" is Safari), digested as logins.family_digest does;
  * one that recorded no browser is held to nothing, and the first browser
    to present it is the one it is held to, as a sign-in made with no
    User-Agent always was.

A 0.8 build compares the whole string's digest and would sign everybody
out, so the number moves. Idempotent: a binding already of the new form is
left as it is. Never edited once shipped (stateversion.py).
"""
import hashlib
import json
from pathlib import Path


def run(ctx):
    f = Path(ctx["state"]) / "logins.json"
    try:
        d = json.loads(f.read_text())
    except (OSError, ValueError):
        return
    if not isinstance(d, dict):
        return
    changed = False
    for rows in d.values():
        if not isinstance(rows, dict):
            continue
        for r in rows.values():
            if not isinstance(r, dict) or not r.get("ua") or str(r["ua"]).startswith("f:"):
                continue
            fam = str(r.get("agent") or "").split(" on ")[0].strip()
            r["ua"] = "f:" + hashlib.sha256(fam.encode("utf-8", "replace")).hexdigest()[:16] if fam and fam != "a browser" else ""
            changed = True
    if changed:
        tmp = f.with_name(f.name + ".new")
        tmp.write_text(json.dumps(d))
        tmp.chmod(0o600)
        tmp.replace(f)
