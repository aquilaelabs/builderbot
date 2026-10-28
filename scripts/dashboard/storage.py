"""The Storage page (R169): what every node's disks hold, and whose.

The agent walks its disks once an hour (its storage.py) and the census
carries the walk; this module turns those into the tab's answer for one
account. A node is listed where the account holds the Storage area on it
(an administrator: every node); each project's folders on the node are
named where the account may see the project, and every other project's
are folded into one line, "other projects", so a shared node says how
much of its disk is somebody else's without saying whose. Measure now is a
job the agent answers at once (nodes.node_storage_measure).
"""
import time

# Where a project's bytes are on a node, in the order the tab shows them.
WHERE = ("workspace", "cache", "artifacts", "appdata", "emulator", "builds")


def node_view(n, may_see):
    """One node's row: the walk as the census carried it, its projects
    split into the ones this account sees and one line for the rest."""
    st = (n.get("reported") or {}).get("storage") or {}
    mine, other = [], {w: 0 for w in WHERE}
    for name, by in sorted((st.get("projects") or {}).items()):
        row = {w: int(by.get(w) or 0) for w in WHERE}
        row["total"] = sum(row.values())
        if may_see(name):
            mine.append({"name": name, **row})
        else:
            for w in WHERE:
                other[w] += row[w]
    mine.sort(key=lambda r: -r["total"])
    hidden = {**other, "total": sum(other.values())} if any(other.values()) else None
    out = {"node": n["id"], "name": n.get("name") or n["id"], "live": n.get("live"),
            "host_only": bool((n.get("config") or {}).get("host_only")),
            # The controller's own machine (R90) and its disks as the census
            # lists them (R162 step 1): the Storage page's Disks section.
            "own": bool((n.get("config") or {}).get("own")),
            "disks": (n.get("reported") or {}).get("disks") or [],
            "shares": (n.get("reported") or {}).get("shares") or [],
            "snapshots": (n.get("reported") or {}).get("snapshots") or {},
            "smb": bool((((n.get("reported") or {}).get("features") or {}).get("shares") or {}).get("smb")),
            "nfs": bool((((n.get("reported") or {}).get("features") or {}).get("shares") or {}).get("nfs")),
            "pools": (n.get("reported") or {}).get("pools") or [],
            "zfs": bool((((n.get("reported") or {}).get("features") or {}).get("storage") or {}).get("zfs")),
            "measured": bool(st.get("at")), "at": int(st.get("at") or 0), "took_s": int(st.get("took_s") or 0),
            "age_s": max(0, int(time.time()) - int(st.get("at") or 0)) if st.get("at") else None,
            "filesystems": st.get("filesystems") or [], "stores": st.get("stores") or {},
            "workspace": st.get("workspace") or {}, "homes": st.get("homes") or {},
            "docker": st.get("docker") or {}, "slow": st.get("slow") or [],
            "projects": mine, "other": hidden,
            # The phones of the projects this account sees (R123), whose
            # Remove the page offers where it may write on the node.
            "phones": [p for p in st.get("phones") or [] if may_see(p.get("project") or "")]}
    # Its memory fence (R110 step 4): [max MB, used MB], null for none, and
    # left out where the agent is too old to say.
    smp = (n.get("reported") or {}).get("sample") or {}
    return out | ({"fence": smp["fence"]} if "fence" in smp else {})


def view(nodes, who, *, is_admin, nodes_for, may_see, level_of):
    """Every node this account may read storage on, each as node_view, and
    whether it may measure one again."""
    allowed = None if is_admin(who) else nodes_for(who, "storage")
    if allowed is not None and not allowed and not level_of(who, "storage"):
        return {"error": "the Storage page is its own area: ask for Read on Storage"}, 403
    out = []
    for n in nodes:
        if n.get("kind") != "agent" or n.get("state") in ("retired", "pending"):
            continue
        if allowed is not None and n["id"] not in allowed:
            continue
        # Whether it may measure this one (R260: Storage held node by node).
        out.append(dict(node_view(n, lambda name: is_admin(who) or may_see(who, name)),
                        may_measure=is_admin(who) or level_of(who, "storage", node=n["id"]) == "write"))
    write = is_admin(who) or level_of(who, "storage") == "write"
    return {"nodes": out, "may_measure": write, "where": list(WHERE)}, 200
