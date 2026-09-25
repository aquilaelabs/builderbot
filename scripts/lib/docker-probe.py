#!/usr/bin/env python3
"""Which docker daemon this container talks to, and whether it answers.

One line on stdout, as `ok|FAIL|skip <sentence>`, for whoever wants to render
it: `bb doctor` as a check row, the startup hook as a boot line.

Shared rather than written twice, for the reason source() itself exists: two
readers each deriving it had already disagreed in public, and a sentence that
contradicts itself is worse than no sentence. The way to not have two is to
not have two.

The probe is devapp.available(), the same call the Artifacts tab makes on its
own poll, so nothing here can drift into disagreeing with the tab about
whether the thing is up.
"""
import importlib.util
from pathlib import Path
import os
import sys


def load(path):
    spec = importlib.util.spec_from_file_location("devapp", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    _wire_nodes(m, path)
    return m


def _wire_nodes(m, path):
    """Give the module the node store, read-only, the way the dashboard
    does at boot. Without it there is no default node and every deploy
    read "no node with a daemon" on the Doctor while the Docker tab was
    building on one: the daemon is a node's, and the probe has to know
    which node the manager would open on."""
    state = os.environ.get("DASHBOARD_STATE") or "/config"
    npath = os.path.join(os.path.dirname(path), "nodes.py")
    if not os.path.isfile(npath) or not os.path.isdir(state):
        return
    try:
        spec = importlib.util.spec_from_file_location("nodes", npath)
        nodes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(nodes)
        nodes.db.open_readonly(state)
    except Exception:                             # noqa: BLE001 - the probe still answers
        return
    m.queue = nodes
    m.node_for = nodes.node_for
    m.node_addr = nodes.ssh_addr_of
    m.node_paths = getattr(nodes, "node_paths", None)
    # The store paths configure() would set, without configure(): that one
    # registers the compose job runner too, and this is a look, not the boot.
    # A verified daemon is adopted on the answer, which is a write of the
    # instance records; the dashboard does it on its own poll, so here the
    # writer is a no-op and the answer is the same.
    m.WORKSPACE = Path(os.environ.get("WORKSPACE") or "/workspace")
    m.STATE = Path(state)
    m.FILE = Path(state) / "devapps.json"
    m.ENVDIR = Path(state) / "devenv"
    m.write_json = lambda *a, **k: None


def verdicts(m):
    """[(state, sentence)], one per node with a daemon. state is ok, FAIL or skip."""
    # The daemon is a node's (DOCKER_HOST is gone: the sandbox VM is a node
    # record, docs/nodes.md §11), and there is no primary among them (the
    # operator, 25 Sep): each node's daemon gets its own line, named, so a
    # box with two nodes does not read one machine's silence as "the docker
    # daemon" being down. No node with one is not a fault to report red on
    # every run of a box that never wanted dev instances (noise is how a
    # check stops being read), so that is a skip.
    q = getattr(m, "queue", None)
    have = [n for n in (q.docker_nodes() if q else []) if n.get("kind") != "local"]
    if not have:
        return [("skip", "no node with a daemon: dev instances run on a node's docker (Nodes tab)")]
    out = []
    for n in sorted(have, key=lambda n: n.get("name") or ""):
        with m.on_node(n["id"]):
            a = m.available_cached()
        why = " ".join((a.get("why") or "").split())      # one line, whatever it said
        if a.get("on"):
            # An agent node's daemon is reached through its agent, never over
            # the address the record carries, so name the node rather than an
            # ssh:// nothing dials.
            out.append(("ok", f"docker on {n['name']}: answering"
                              + ("" if n.get("kind") == "agent" else f" at {a.get('where')}")))
        else:
            out.append(("FAIL", f"docker on {n['name']}: {why}"))
    return out


def mapping_faults(m):
    """Complaints about the node's path mapping (its row's node_paths, once
    DOCKER_HOST_PATHS), or an empty list.

    Worth a boot line of its own because it is the failure nothing else
    catches: a pair whose two sides have drifted apart means a bind mount
    resolving to a directory the daemon does not have, and docker answers that
    by creating an empty one rather than by failing.
    """
    try:
        bad = list(m.host_map()[1])
        return bad + [f"{p} is mapped but this container does not have it"
                      for p in m.stray_map_entries(m.host_map()[0])]
    except Exception:                             # noqa: BLE001 - never fatal
        return []


def main(argv):
    path = argv[0] if argv else os.environ.get("BB_DEVAPP", "")
    if not path or not os.path.isfile(path):
        print("skip docker daemon: devapp.py was not found beside this")
        return 0
    try:
        m = load(path)
    except Exception as e:                        # noqa: BLE001
        print(f"skip docker daemon: could not be probed ({e})")
        return 0
    lines = verdicts(m)
    for state, line in lines:
        print(f"{state} {line}")
    if any(state != "skip" for state, _ in lines):
        for fault in mapping_faults(m):
            print(f"warn host path mapping: {fault}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
