"""State 1 to 2: the VM manager (R91).

  * every role that holds Containers on a project holds VMs at the same
    level, the nearest trust it already had: a VM is made on a node as a
    container is, and the area did not exist when the role was written;
  * /config/vms.json, the VMs' records, there and empty.

Idempotent: a role that holds VMs already keeps its level, and a vms.json
that is there is left alone. Never edited once shipped (stateversion.py).
"""
import json
from pathlib import Path

import roles


def run(ctx):
    with roles._lock:
        d = roles._load()
        moved = 0
        for r in d.values():
            lvl = (r.get("perms") or {}).get("containers")
            if lvl and "vms" not in r["perms"]:
                r["perms"]["vms"] = lvl
                moved += 1
        if moved:
            roles._save(d)
            print(f"dashboard: {moved} role(s) given VMs at their Containers level (R91)", flush=True)
    f = Path(ctx["state"]) / "vms.json"
    if not f.exists():
        f.write_text(json.dumps({"vms": {}, "nets": {}}, indent=2) + "\n")
