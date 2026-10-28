"""Home (R218 step 5): the overview's numbers across the whole install, in
one read the page makes on open, and a light one when the queue moves (the
design's the-dashboard/home rule). Nothing here polls.

What the status poll already carries the page counts itself (the sessions
open, the updates due, a red CI run). What it does not is here: the nodes
online of enrolled, the containers running of all, the jobs running and
failed today, and the last ten jobs. The containers are each docker node's
own listing, asked once per node in parallel with the reads the Docker
manager makes (devapp.containers: a probe job on an agent node, its last
answer standing in, marked stale, when the node does not answer), so a
node that is slow says "as last seen" rather than holding the page.

The handler in server.py decides who may ask and passes the jobs this
account may see (nodes.jobs_view's scoping), and whether the machines are
this account's to count (the Nodes area): an account that may not read
them is told nothing about them, not a zero.
"""
import concurrent.futures
import datetime
import time

nodes = None               # nodes.py: node_list
devapp = None              # devapp.py: on_node, containers

# How long Home waits for a node's container listing before it counts that
# node as unknown: a whole page of tiles is not held for one machine.
CONTAINER_WAIT_S = 8
# ...and how long once every node has answered before (the operator, 17 Oct:
# Home took seconds to open): a node slower than this is counted from what it
# last said, marked as last seen, while its listing finishes behind the
# answer and is kept for the next open.
KEPT_WAIT_S = 1.5
# Each docker node's last listing that came back whole, by node id.
_kept = {}


backups_summary = None    # storebackups.summary over the own machine's census (R162 step 5)


def configure(*, nodes_mod, devapp_mod):
    globals().update(nodes=nodes_mod, devapp=devapp_mod)


def _machines():
    """The agent nodes, retired ones left out: the enrolled machines."""
    return [n for n in nodes.node_list() if n.get("kind") == "agent" and n.get("state") != "retired"]


def _containers(ns):
    """Running and all containers across the docker nodes, and whether any
    count came from a kept answer (the node's own, or Home's last listing of
    it) or none at all."""
    docker = [n for n in ns if (n.get("reported") or {}).get("docker")]

    def one(nid):
        with devapp.on_node(nid):
            got = devapp.containers()
        if got and not got.get("error"):
            _kept[nid] = got
        return got
    running = total = 0
    stale = unknown = 0
    if not docker:
        return {"running": 0, "all": 0, "nodes": 0, "stale": 0, "unknown": 0}
    # Not `with`: leaving that block waits for every thread, which is the
    # one thing the timeout is here to stop. A late listing finishes on its
    # own and is kept for the next read (devapp's last reads).
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(docker)))
    futs = [ex.submit(one, n["id"]) for n in docker]
    wait = KEPT_WAIT_S if all(n["id"] in _kept for n in docker) else CONTAINER_WAIT_S
    done, _ = concurrent.futures.wait(futs, timeout=wait)
    ex.shutdown(wait=False)
    for n, f in zip(docker, futs, strict=True):
        got = (f.result() or {}) if f in done and f.exception() is None else {"error": "late"}
        if got.get("error") and n["id"] in _kept:
            got = dict(_kept[n["id"]], stale=True)
        if got.get("error"):
            unknown += 1
            continue
        cs = got.get("containers") or []
        running += sum(1 for c in cs if c.get("state") == "running")
        total += len(cs)
        stale += 1 if got.get("stale") else 0
    return {"running": running, "all": total, "nodes": len(docker), "stale": stale, "unknown": unknown}


def _midnight(now=None):
    """Today's start in this container's time zone (TZ), as epoch seconds:
    'failed today' is the operator's day, not UTC's."""
    t = datetime.datetime.fromtimestamp(now or time.time())
    return t.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _jobs(rows, names):
    """Running, failed today, and the last ten, newest first, with the
    fields the page's job row draws from (the Jobs page's own helpers)."""
    since = _midnight()
    keep = ("id", "type", "project", "spec", "state", "step", "cancel", "node", "queued",
            "started", "ended", "exit_code", "error", "requested_by")
    last = sorted(rows, key=lambda j: j.get("queued") or 0, reverse=True)[:10]
    return {"running": sum(1 for j in rows if j.get("state") in ("running", "assigned")),
            "waiting": sum(1 for j in rows if j.get("state") == "queued"),
            "failed_today": sum(1 for j in rows if j.get("state") == "failed"
                                and (j.get("ended") or j.get("queued") or 0) >= since),
            # Where today began, so the Jobs page's Failed today lists the
            # jobs this count counted, by this container's day (B113).
            "today": int(since),
            "last": [{k: j.get(k) for k in keep} for j in last],
            "nodes": {k: v for k, v in (names or {}).items() if any(j.get("node") == k for j in last)}}


def read(jobs_rows, job_names, machines, light=False):
    """The Home payload: (payload, status). `machines` is whether this
    account counts the nodes and the containers on them. `light` is a
    re-read when the queue moved: the containers are not asked again (that
    is a probe job on every docker node), and the page keeps what it had."""
    out = {"jobs": _jobs(jobs_rows or [], job_names or {}), "nodes": None, "containers": None}
    if machines:
        ns = _machines()
        out["nodes"] = {"enrolled": len(ns),
                        "online": sum(1 for n in ns if n.get("state") == "online" and n.get("live") is not False)}
        if not light:
            out["containers"] = _containers(ns)
        # The own machine's backups (R162 step 5): the tile says the last
        # good run, or what failed or went stale.
        own = next((n for n in ns if (n.get("config") or {}).get("own")), None)
        if own and backups_summary:
            sm = backups_summary((own.get("reported") or {}).get("store_backups") or [])
            if sm.get("count"):
                out["backups"] = sm
    return out, 200
