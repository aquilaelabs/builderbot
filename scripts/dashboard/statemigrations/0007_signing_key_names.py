"""State 6 to 7: every project's signing keys under a name.

  * Keys made before a project could hold several (R106, 1 Oct) sat in the
    project's own signing folder as play.ks/json and sideload.ks/json. The
    dashboard moved them into `default` the first time it looked, which left
    a project nobody had opened since with them where they were. Moved here
    once, so the dashboard reads only named keys.

Idempotent: a slot already moved is not there to move again, and one that
would land on a key already in `default` is left where it is.
Never edited once shipped (stateversion.py).
"""
import os
from pathlib import Path


def run(ctx):
    root = Path(ctx["state"]) / "signing"
    if not root.is_dir():
        return
    moved = 0
    for project in sorted(p for p in root.iterdir() if p.is_dir()):
        for route in ("play", "sideload"):
            for ext in ("ks", "json"):
                old = project / f"{route}.{ext}"
                new = project / "default" / f"{route}.{ext}"
                if not old.is_file() or new.exists():
                    continue
                new.parent.mkdir(parents=True, exist_ok=True)
                os.chmod(new.parent, 0o700)
                os.replace(old, new)
                moved += 1
    if moved:
        print(f"dashboard: {moved} signing key file(s) moved under their project's default key", flush=True)
