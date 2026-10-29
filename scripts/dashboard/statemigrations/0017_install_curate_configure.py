"""State 16 to 17: the Toolchains area is three (R174, the operator, 28 Oct).

  * every role kept in roles.json that holds Toolchains holds Install at
    the same level, node by node where it named nodes;
  * Configure (a service's and a pack's settings on a node, which needed
    an administrator or the right to write containers) is given at Write,
    on the same nodes, to a role that held Toolchains and also wrote
    containers everywhere; nobody gains a press they had no way to make;
  * Curate (the catalog's own entries, an administrator's) is given to no
    role of one's own: the built-in Administrator and Owner hold it;
  * the Toolchains key is taken out. A 0.8 build reads the roles back as
    holding nothing on nodes it does not know, so the number moves.

Idempotent: a role already holding Install is left as it is. Never edited
once shipped (stateversion.py).
"""
import json
from pathlib import Path


def run(ctx):
    f = Path(ctx["state"]) / "roles.json"
    try:
        d = json.loads(f.read_text())
    except (OSError, ValueError):
        return
    roles = d.get("roles") if isinstance(d, dict) else None
    if not isinstance(roles, dict):
        return
    changed = False
    for r in roles.values():
        if not isinstance(r, dict):
            continue
        perms = r.get("perms") if isinstance(r.get("perms"), dict) else {}
        only = r.get("only") if isinstance(r.get("only"), dict) else {}
        if "toolchains" not in perms and "toolchains" not in only:
            continue
        lvl = perms.pop("toolchains", None)
        if lvl and "install" not in perms:
            perms["install"] = lvl
        m = only.pop("toolchains", None)
        if isinstance(m, dict) and "install" not in only:
            only["install"] = m
        if lvl == "write" and perms.get("containers") == "write" and r.get("scope") == "global" and "configure" not in perms:
            perms["configure"] = "write"
            if isinstance(m, dict):
                only["configure"] = {k: "write" for k, v in m.items() if v == "write"}
        r["perms"], r["only"] = perms, only
        changed = True
    if changed:
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2))
        tmp.replace(f)
