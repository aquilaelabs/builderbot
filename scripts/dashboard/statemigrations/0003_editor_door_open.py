"""State 2 to 3: a person's own machine reaches the projects they are on
(R104, the operator, 22 Oct).

  * every project's editor and apps door (ftp.json's `editor`) is opened:
    being on a project, with File access in the account's roles, is now what
    lets the VS Code extension and the Windows companion in, and the
    project's switch is an owner's way to close it rather than a second
    switch to open it.

Idempotent: a door that is open stays open. Never edited once shipped
(stateversion.py).
"""
import json
from pathlib import Path


def run(ctx):
    f = Path(ctx["state"]) / "ftp.json"
    try:
        d = json.loads(f.read_text())
    except (OSError, ValueError):
        return
    if not isinstance(d, dict):
        return
    opened = 0
    for rec in d.values():
        if isinstance(rec, dict) and not rec.get("editor"):
            rec["editor"] = True
            opened += 1
    if opened:
        f.write_text(json.dumps(d, indent=2) + "\n")
        print(f"dashboard: {opened} project(s) open to their people's editors and apps (R104)", flush=True)
