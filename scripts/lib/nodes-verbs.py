"""Behind `bb nodes` and `bb ci-labels` (cmd_nodes and cmd_ci_labels in bb):
the enrolled machines, and the runner labels the registry knows, read from
the node store the way the Nodes page reads it (dashboard/nodes.py), and
read-only.

The first argument is the verb, `list` or `labels`, then nodes.py's path.
DASHBOARD_STATE says where the store is.
"""
import contextlib
import os
import sys

import dash

verb, py = sys.argv[1], sys.argv[2]
nodes = dash.load("nodes", dash.beside(py))


def list_():
    try:
        nodes.db.open_readonly(os.environ["DASHBOARD_STATE"])
        rows = nodes.node_list()
    except Exception as e:
        print(f"no node store yet; the dashboard creates it on boot ({e})")
        raise SystemExit(0) from None
    # Enrolled machines only. The controller's own record is registry plumbing
    # (it is how a share it mounts is recognized as a node's store) and never a
    # machine anybody lists: it runs no work and takes no toolchains.
    rows = [n for n in rows if n["kind"] != "local"]
    if not rows:
        print("no node is enrolled; the dashboard's Nodes page mints a token for one")
        print("a project with no node can be read and edited here, and cannot be built")
        raise SystemExit(0)
    for n in rows:
        caps = ",".join(n["capabilities"]) or "-"
        ag = n.get("agent") or {}
        where = ag.get("addr") or "-"
        # An agent node is live or quiet by whether it has dialed in lately:
        # derived, never stored, and the one column the row cannot lie about.
        state = n["state"]
        if n["kind"] == "agent" and state != "pending":
            state += (" ●" if n.get("live") else " ○")
        s = (n.get("reported") or {}).get("sample") or {}
        nums = (f' · cpu {s.get("cpu_pct", 0):.0f}% · {s.get("mem_used_mb", 0) / 1024:.1f}'
                f'/{s.get("mem_mb", 0) / 1024:.0f}GB') if s and n.get("live") else ""
        print(f'{n["id"]:>12}  {state:<10} {n["kind"]:<6} {caps:<24} '
              f'{n["name"]} · {where}{nums}')


def labels():
    with contextlib.suppress(Exception):
        nodes.db.open_readonly(os.environ["DASHBOARD_STATE"])
        print("\n".join(nodes.runner_labels_known()))


{"list": list_, "labels": labels}[verb]()
