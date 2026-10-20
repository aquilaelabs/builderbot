"""Behind `bb nodes` and `bb ci-labels` (cmd_nodes and cmd_ci_labels in bb):
the enrolled machines, and the runner labels the registry knows, read from
the node store the way the Nodes page reads it (dashboard/nodes.py), and
read-only.

The first argument is the verb, `list`, `show` or `labels`, then nodes.py's
path, then for `show` the node's name or id.
DASHBOARD_STATE says where the store is.
"""
import contextlib
import os
import sys

import dash

verb, py = sys.argv[1], sys.argv[2]
arg = sys.argv[3] if len(sys.argv) > 3 else ""
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
              f'{n["name"]} · {where}{nums}{_agent(n)}')


def _agent(n):
    """The agent a node runs beside the row (B9): its version, and
    "update due" when it is not the one this controller ships, which is
    what Update agent on the Nodes page fixes."""
    if n["kind"] != "agent":
        return ""
    mine = (n.get("agent") or {}).get("version") or ""
    if not mine:
        return ""
    return f" · agent {mine}" + (" · update due" if nodes.agent_stale(n) else "")


def show(name):
    """One node in full, by its name or id: `bb nodes show NAME`."""
    try:
        nodes.db.open_readonly(os.environ["DASHBOARD_STATE"])
        rows = [n for n in nodes.node_list() if n["kind"] != "local"]
    except Exception as e:
        print(f"no node store yet; the dashboard creates it on boot ({e})")
        raise SystemExit(0) from None
    n = next((r for r in rows if name in (r["name"], r["id"])), None)
    if not n:
        raise SystemExit(f"[builderbot] ERROR: no node called {name}; bb nodes lists them: "
                         + ", ".join(r["name"] for r in rows))
    ag = n.get("agent") or {}
    rows_out = [("node", f'{n["name"]} ({n["id"]})'), ("state", n["state"] + (", dialing in" if n.get("live") else "")),
                ("kind", n["kind"]), ("address", ag.get("addr") or "-"),
                ("does", ",".join(n["capabilities"]) or "-"), ("labels", ",".join(n.get("labels") or []) or "-")]
    if n["kind"] == "agent":
        ours = nodes.agent_file()["version"] or "?"
        rows_out.append(("agent", f'{ag.get("version") or "?"} (this controller ships {ours})'))
        stale = nodes.agent_stale(n)
        if stale:
            rows_out.append(("update", stale))
    for k, v in rows_out:
        print(f"  {k:<8} {v}")


def labels():
    with contextlib.suppress(Exception):
        nodes.db.open_readonly(os.environ["DASHBOARD_STATE"])
        print("\n".join(nodes.runner_labels_known()))


def enroll_token():
    """A node's enrollment token for a setup scripted from a shell (R84):
    the row and the token Enroll node's Just a token makes, printed once.
    Its run user is --user's, bb by default."""
    rest = sys.argv[3:]
    if not rest or rest[0].startswith("-"):
        sys.exit("[builderbot] ERROR: bb nodes enroll-token NAME [--user U]: which name?")
    name, user = rest[0], "bb"
    if "--user" in rest:
        i = rest.index("--user")
        if i + 1 >= len(rest):
            sys.exit("[builderbot] ERROR: --user needs the account the node's jobs run as")
        user = rest[i + 1]
    nodes.configure(state=os.environ["DASHBOARD_STATE"])
    r = nodes.enroll_mint("user:shell", name, user=user)
    if r.get("error"):
        sys.exit(f"[builderbot] ERROR: {r['error']}")
    print(r["token"])
    print(f"{name} ({r['id']}) waits for it, until {__import__('time').strftime('%d %b %H:%M', __import__('time').localtime(r['expires']))}",
          file=sys.stderr)


if verb == "show":
    show(arg)
elif verb == "enroll-token":
    enroll_token()
else:
    {"list": list_, "labels": labels}[verb]()
