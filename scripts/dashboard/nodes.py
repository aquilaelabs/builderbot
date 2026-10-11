#!/usr/bin/env python3
"""The node data plane: the node registry and, from phase 3, the agent
channel (enrollment tokens, node credentials, the heartbeat with its census,
and the job rows an `exec` job rides in on; docs/nodes.md §4, §9).

Phase 1 seeded a `local` node for the container itself, answered a read-only
list, stamped which node a piece of work ran on, and wrote an audit row for
every mutation the server takes. It also mirrored DOCKER_HOST into an `ssh`
node so the sandbox VM had a record; that kind is retired (roadmap #24) and
`local` and `agent` are the two that remain. Phase 2 made the registry
editable. Phase 3 is the
first time something OTHER than this container writes here: an agent on a
node dials in with a bearer token, says what it is, asks for work, and
reports what happened. Phase 4 made the job rows the queue: placement is a
function (pick), a job may name a selector instead of a node and is frozen to
the node that takes it, cancel is a flag the runner reads, and a node that
stops answering loses its jobs rather than holding them forever. The store
under all of it (the connection, the migrations, ids and the audit trail) is
db.py's, and so are the one-way doors it was built to keep.
"""
import contextlib
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import secrets
import sqlite3
import threading
import time
import urllib.parse
from pathlib import Path
import sys
# Beside this file, whichever way it was loaded: bb's own Python and the
# doctor's probe load this module by path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names   # noqa: E402
from fields import field   # noqa: E402
import db   # noqa: E402
import turns   # noqa: E402
import enrollscript   # noqa: E402
from db import _exec, _lock, _rows, audit, mint   # noqa: E402

HERE = Path(__file__).resolve().parent

# The controller's own node id. Well-known rather than minted, from the brief:
# a single-container deployment must work with zero remote hosts, and `local`
# is the one id that may exist before any enrollment has ever happened.
LOCAL = "local"



def configure(*, state):
    """Open the store (db.py) and make sure the controller's own node is in
    it: the one row the registry holds before any enrollment."""
    db.configure(state=state)
    _seed_local()


# ---------------------------------------------------------------------------
# nodes

_JSON_COLS = ("capabilities", "services", "labels", "agent", "reported",
              "routing", "config")


def _inflate(row):
    for k in _JSON_COLS:
        with contextlib.suppress(ValueError, TypeError):
            row[k] = json.loads(row[k])
    return row


def node_list(all=False):
    """The nodes, JSON columns inflated. Retired rows are history: kept in
    the table (door 1: ids are never reused, and an old record must stay
    explicable) and left out of every list unless asked for. Each row also
    names the system job in flight on it, so the tab can say "applying"
    without a second fetch."""
    rows = [_live(_inflate(r)) for r in _rows(
        "SELECT * FROM nodes ORDER BY kind = 'local' DESC, created")]
    busy, inflight = {}, {}
    # Every job that has not finished, not only the system ones. A button
    # whose job type was not tracked here came back live on the repaint that
    # followed the press: pressing() grays it for the round trip, and then
    # the render put a fresh, enabled one in its place. Update agent did
    # exactly that, which is what the operator kept seeing.
    for j in _rows("SELECT id, node, type, spec, state FROM jobs WHERE "
                   "state IN ('queued', 'assigned', 'running')"):
        entry = {"id": j["id"], "type": j["type"], "state": j["state"]}
        inflight.setdefault(j["node"], []).append(entry)
        if j["type"] != "system":
            continue
        try:
            sp = json.loads(j["spec"])
            # The apply's name beside the type: a system job is one type
            # for six things, and the Uninstall button was reading "is an
            # uninstall in flight" off the type alone and never graying.
            entry["apply"] = sp.get("apply", "")
            busy[j["node"]] = {"id": j["id"], "what": sp.get("apply", ""),
                               "slot": str((sp.get("config") or {}).get("slot") or "")}
        except (ValueError, AttributeError):
            busy[j["node"]] = {"id": j["id"], "what": ""}
    # ...and the last system job that FINISHED on each, which is the only
    # account of an apply that did not work. Without it the operator pressed
    # Apply storage, the job ran, failed, and the section went straight back
    # to "4 changes to apply", with no sign an attempt had happened at all,
    # which reads as a button that does nothing. Bounded: the newest rows
    # are the only ones that could be anybody's last.
    done, runner = {}, {}
    for j in _rows("SELECT id, node, spec, state, error, ended FROM jobs "
                   "WHERE type = 'system' AND state IN ('succeeded', 'failed', "
                   "'canceled') ORDER BY ended DESC, rowid DESC LIMIT 200"):
        if j["node"] in done and j["node"] in runner:
            continue
        try:
            spec = json.loads(j["spec"])
        except (ValueError, TypeError):
            spec = {}
        # The last RUNNER apply too, which the last apply of any kind hides
        # as soon as anything else runs there: one root ask after a failed
        # install, and that failure was nobody's last.
        if spec.get("apply") == "runner" and j["node"] not in runner:
            runner[j["node"]] = {"id": j["id"], "state": j["state"], "ended": j["ended"],
                                 "want": (spec.get("config") or {}).get("want", True),
                                 "slot": str((spec.get("config") or {}).get("slot") or "")}
        if j["node"] in done:
            continue
        done[j["node"]] = {"id": j["id"], "what": spec.get("apply", ""),
                           "state": j["state"], "error": (j["error"] or "")[:200],
                           "ended": j["ended"], "cfg": spec.get("config")}
    for r in rows:
        r["applying"] = busy.get(r["id"])
        r["jobs"] = inflight.get(r["id"], [])
        la = done.get(r["id"])
        if la:
            # Whether it is still about the record as it stands. Compared by
            # the config the job CARRIED rather than by when it ran: a save
            # and an apply land in the same second often enough that a clock
            # cannot tell them apart, and this can. A failure the operator
            # has since saved past is about a record that no longer exists.
            la = dict(la)
            la["current"] = la.pop("cfg", None) == apply_cfg(
                (r.get("config") or {}).get("desired"), la["what"])
        r["last_apply"] = la
        r["runner_failed"] = _runner_failed(r, runner.get(r["id"]), r["applying"])
    return rows if all else [r for r in rows if r["state"] != "retired"]



def runner_slot(url):
    """The slot a runner's address maps to: its host and path, lowercase,
    letters, digits, dots and dashes, so it can name a directory on the
    node, a token file on the controller and a row on the tab. One runner
    per slot per node, since a runner's name on its host is the node's.
    The same function lives in scripts/agent/builderbot-agent.py; the two must agree."""
    rest = re.sub(r"^[a-z]+://", "", str(url or "").strip().lower()).rstrip("/")
    rest = re.sub(r"\.git$", "", rest)
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9.]+", "-", rest)).strip("-.")[:60]


def runners_of(row):
    """The runners a node's record asks for, by slot: {slot: {url, forge,
    want, labels}}."""
    r = (row.get("services") or {}).get("runners")
    return r if isinstance(r, dict) else {}


def runners_reported(row):
    """The runners a node's census reports, as a list."""
    r = ((row.get("reported") or {}).get("services") or {}).get("runners")
    return r if isinstance(r, list) else []


def _runner_failed(row, last, applying):
    """The runner install that failed on a node: {id, slot, ended, why}, or
    None.

    Only while it is still the answer: the record asks for that runner and
    no runner apply is in flight that could be the retry. A runner the census
    reports as installed can carry one too: a reinstall that failed left it
    standing, and the row says both. The census knows only what is
    installed, so without this a failed install read as "asked for; not
    reported yet" for as long as nobody pressed Install again."""
    if not last or last["state"] != "failed" or not last["want"]:
        return None
    if (applying or {}).get("what") == "runner":
        return None
    slot = last.get("slot") or ""
    want = runners_of(row).get(slot) or {}
    if not want.get("want"):
        return None
    return {"id": last["id"], "slot": slot, "ended": last["ended"], "why": _failed_why(last["id"])}


_WHY = {}


def _failed_why(job_id):
    """What a failed job's log says about why, for one line on a row.

    A job that ran a command failed on it, so it is that command's output,
    the last two lines of it because a tool's advice tends to follow its
    reason (config.sh names the missing libicu, then says to run a script).
    A job that failed before running one ends on the agent's own sentence,
    so it is the last line. A finished job's log never changes: read once."""
    if job_id not in _WHY:
        lines = [x.strip() for x in job_tail(job_id).splitlines() if x.strip()]
        cmd = max((i for i, x in enumerate(lines) if x.startswith("$ ")), default=-1)
        said = lines[cmd + 1:] if 0 <= cmd < len(lines) - 1 else lines[-1:]
        # Long enough for the helper's 403 line, whose second half says which
        # permission the token lacks: the part that is worth reading.
        _WHY[job_id] = " · ".join(x[:400] for x in said[-2:])[:700]
    return _WHY[job_id]


def node(node_id):
    got = _rows("SELECT * FROM nodes WHERE id = ?", (node_id,))
    return _live(_inflate(got[0])) if got else None


# How long an agent may go unheard before its row says offline: three polls,
# so one slow answer or a controller restart is not an outage on the screen.
LIVE_S = 3 * 25


def _live(rec):
    """Liveness is derived, never stored. The `state` column is the
    OPERATOR's intent (online, draining, retired, pending), and whether an
    agent is actually talking to us is a different fact with a different
    owner, so it rides beside it: `live` is True while the last heartbeat is
    recent, False once it is not, and None for a node kind that has no
    heartbeat to be late with, which since roadmap #24 is only local: us."""
    if rec.get("kind") == "agent":
        seen = (rec.get("agent") or {}).get("last_seen") or 0
        rec["live"] = (time.time() - seen) < LIVE_S
    else:
        rec["live"] = None
    return rec


def _insert_node(rec):
    # ssh_addr is written empty and read by nothing: the kind that used it is
    # retired (roadmap #24). The column stays because migrations are numbered
    # and append-only (dropping one is a one-way door across two engines for
    # a cosmetic gain), so it is written rather than special-cased away.
    cols = ("id", "name", "kind", "pool", "created", "state", "concurrency",
            "ssh_addr", "os", "arch", *_JSON_COLS)
    vals = [json.dumps(rec.get(c, {})) if c in _JSON_COLS
            else rec.get(c, "") if c in ("os", "arch") else rec.get(c)
            for c in cols]
    _exec(f"INSERT INTO nodes ({', '.join(cols)}) VALUES "
          f"({', '.join('?' * len(cols))})", vals)


STORE_ID_FILE = ".bb-store-id"

# Where this container keeps its toolchains. `bb toolchains root` is the authority
# and toolchains.py asks it, but nodes.py is imported at boot before any of
# that and must not shell out on the seed path, so the same two answers bb
# itself resolves between, in the same order.
def sdk_root_of_controller():
    r = (os.environ.get("SDK_ROOT") or "").strip()
    if r:
        return r
    return "/sdk" if os.path.isdir("/sdk") else ""


def store_id(path, make=True):
    """A stable id for the store at `path`, from a marker inside it.

    Two machines mounting one share have no way to recognize each other by
    path: this container reaches the toolchain store through Unraid's FUSE layer
    (fstype fuse.shfs, source "shfs") while a node reaches the same bytes
    over NFS (192.168.1.10:/mnt/user/development/SDK). Neither string can be
    derived from the other without knowing it is Unraid, so pairing on the
    mount was never going to work here. Measured on this box, 3 Sep.

    A file in the store answers exactly, whatever the transport, and it is
    store-specific rather than machine-specific, so it is the one kind of
    thing that belongs in a shared store.
    """
    if not path:
        return ""
    f = os.path.join(path, STORE_ID_FILE)
    try:
        with open(f) as fh:
            got = fh.read().strip()[:64]
        if got:
            return got
    except OSError:
        pass
    if not make:
        return ""
    made = "s_" + secrets.token_hex(8)
    try:
        # Exclusive, so two machines racing the first mount cannot each
        # believe they created it: the loser reads the winner's.
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "w") as fh:
            fh.write(made + "\n")
        return made
    except FileExistsError:
        return store_id(path, make=False)
    except OSError:
        return ""


def _seed_local():
    """The controller as a node, present from the first boot.

    Re-seeded shallowly on every boot: the row survives, but the reported
    census is refreshed because it describes this container, and this boot is
    the authority on this container. No capabilities at all (roadmap #24,
    10c): the image carries no JDK and no Android SDK, so package-build is a
    node's; docker-host was never here (the local node is not a sandbox,
    docs/nodes.md §12). The row
    stays so the controller is recognized as sharing a store with a node,
    and so a selector job can still be placed here on purpose.
    """
    reported = {
        "cpu": os.cpu_count() or 0,
        "mem_mb": _mem_mb(),
        "os": f"{platform.system().lower()} {platform.machine()}",
    }
    # This container's own toolchain store, reported like any node's. Without
    # it the controller could not be recognized as sharing a store with a
    # node, so the "one install at a time across all of them" arbitration
    # never engaged for the pair that most obviously needs it: the toolchain store,
    # mounted here and on the sandbox at once.
    root = sdk_root_of_controller()
    if root:
        st = {"path": root, "id": store_id(root)}
        with contextlib.suppress(OSError):
            u = os.statvfs(root)
            st["free_mb"] = int(u.f_bavail * u.f_frsize / 1048576)
            st["total_mb"] = int(u.f_blocks * u.f_frsize / 1048576)
        reported["stores"] = {"toolchains": st}
    system, arch = platform.system().lower(), platform.machine()
    if node(LOCAL):
        _exec("UPDATE nodes SET reported = ?, os = ?, arch = ? WHERE id = ?",
              (json.dumps(reported), system, arch, LOCAL))
        return
    _insert_node({
        "id": LOCAL, "name": "controller", "kind": "local",
        "pool": "default", "created": int(time.time()), "state": "online",
        "concurrency": 1, "ssh_addr": "", "os": system, "arch": arch,
        "capabilities": [],
        "services": {},                    # no runner here: CI is a node's
        "labels": {"arch": platform.machine()},
        "agent": {}, "reported": reported, "routing": {}, "config": {},
    })
    audit("system", "node-seed", LOCAL, {})


def _mem_mb():
    try:
        with open("/proc/meminfo") as f:
            m = re.search(r"MemTotal:\s+(\d+) kB", f.read())
        return int(m.group(1)) // 1024 if m else 0
    except OSError:
        return 0


def parse_paths(text):
    """"/here:/there, /a:/b" -> ({here: there}, "") or ({}, why)."""
    out = {}
    for pair in str(text or "").replace("\n", ",").split(","):
        pair = pair.strip()
        if not pair:
            continue
        here, _, there = pair.partition(":")
        here, there = here.strip().rstrip("/"), there.strip().rstrip("/")
        if not here.startswith("/") or not there.startswith("/") or " " in here + there:
            return {}, f"{pair} is not a /container:/host pair"
        out[here[:200]] = there[:200]
    return out, ""


def node_paths(node_id):
    """What this container's paths are called on the node's machine: the
    daemon resolves bind sources over there. {} when nothing is set."""
    n = node(node_id) if node_id else None
    p = (n.get("config") or {}).get("paths") if n else None
    return dict(p) if isinstance(p, dict) else {}


def node_paths_set(principal, node_id, text):
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] == "local":
        return {"error": "local's paths are its own; there is nothing to map"}
    paths, why = parse_paths(text)
    if why:
        return {"error": why}
    cfg = dict(n.get("config") or {})
    cfg["paths"] = paths
    _exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(cfg), node_id))
    _touch(node_id, principal, "node-paths", {"n": len(paths)})
    return {"ok": True, "paths": paths}


# The bindings the Docker tab's first pick is derived from: {project: node
# id}, set by the server from the projects' settings.
project_nodes = None


def first_up(nids):
    """(node id, fell_over_from): the first of a project's node set that is
    online and live, the primary first (R82 step 6). The primary when it is
    up, or when none is, so a refusal still names the node the project is
    set to; else the first that is, with the primary it stood in for."""
    nids = [n for n in (nids or []) if n]
    if not nids:
        return "", ""
    for nid in nids:
        n = node(nid)
        if n and n.get("state") == "online" and (n.get("live") or n.get("kind") != "agent"):
            return nid, ("" if nid == nids[0] else nids[0])
    return nids[0], ""


def node_for():
    """The node the Docker tab opens on when nobody has picked one, and
    nothing more: not a default that work falls to. A project's containers
    go to the project's node, and a project with no node has nowhere to
    send, since there is no primary docker manager (the operator, 25 Sep,
    after every new project landed on the newest enrolled node).

    Derived from the projects: the node most of them are bound to, so the
    tab opens where the work is. With nothing bound anywhere, the newest
    enrolled node that runs docker, else the newest enrolled, else local:
    the first pick on a box with no projects yet."""
    try:
        bound = {}
        for nid in (project_nodes() if project_nodes else {}).values():
            if nid:
                bound[nid] = bound.get(nid, 0) + 1
        if bound:
            have = {n["id"]: n for n in docker_nodes() if n["kind"] != "local"}
            live = [nid for nid in bound if nid in have]
            if live:
                return sorted(live, key=lambda nid: (-bound[nid], have[nid]["created"]))[0]
        # The newest node whose census says docker runs there, else the newest
        # the manager has somewhere to send to (B113). An address is not a
        # daemon: a Mac enrolled as a guest, with ssh and no docker, would
        # otherwise be the host of every instance nobody bound to a node. The
        # census is what the node last said about itself, so nothing is asked
        # on the status poll's path, and the choice holds still while a
        # machine is off instead of following its uptime around.
        #
        # Still better than "newest online", which is what it replaced: an
        # agent node that has never dialed in has no address at all, so it
        # could hold a project's containers only in principle, and picking it
        # left the manager talking to nothing.
        got = [n for n in docker_nodes() if n["kind"] != "local"]
        runs = [n for n in got if (n.get("reported") or {}).get("docker")]
        if runs or got:
            return sorted(runs or got, key=lambda n: n["created"])[-1]["id"]
    except sqlite3.Error:
        pass                     # a broken store falls back to the answer
    return LOCAL                 # that was always true before it existed


# ---------------------------------------------------------------------------
# mutations, phase 2: the Nodes tab's verbs. Every one writes an audit row
# with the principal the server hands it, because these ARE the mutations the
# audit table was built ahead of.

# What the tab may toggle. An unknown capability is refused rather than
# stored: the scheduler will one day place work on these strings, and a typo
# that sits in the table until then is a job that never places.
# What a node may be asked to do. NOT a setting any more (2 Sep): every node
# gets all of it at enrollment, because a project names one node and that node
# does everything for it. What the project can actually do there is what is
# INSTALLED on it, which the census reports as toolchains. This stays as the
# vocabulary of the node-side refusal (§15 door 7: an agent refuses a job
# outside what it enrolled with), so a restricted node remains expressible
# without anybody having to configure one to get ordinary work done.
CAPABILITIES = ("docker-host", "package-build", "deploy-target")
_rev = [0]


def rev():
    """Bumped on every node mutation and every heartbeat; /api/revs carries
    it so open views refetch instead of the list riding the status poll
    (docs/nodes.md §13). Liveness is derived, not written, so a node going
    QUIET writes nothing; the count of live nodes is folded in so that its
    row goes gray without anyone touching the store."""
    return f"{_rev[0]}.{sum(1 for n in node_list() if n.get('live'))}"


def _bump():
    _rev[0] += 1


def _touch(node_id, principal, action, fields):
    audit(principal, action, node_id, fields)
    _bump()


def node_add(principal, name, ssh_addr, capabilities=None, pool="default"):
    """Gone (roadmap #18): a node is enrolled with a token, and only with a
    token. It stayed until compose could run on the agent, because until
    then a node still needed an ssh key on top of its token for docker,
    which meant two enrollments for one machine, and a token-only node (the
    cloud case) could take every job EXCEPT docker. Compose is an agent job
    now and proved on a real VM, so the key buys nothing and the second
    enrollment can go.

    Kept as a refusal rather than deleted so the endpoint answers with the
    way in rather than a 404.
    """
    return {"error": "ssh nodes are gone; enroll the machine with a token "
                     "instead: Enroll node mints one, and provision-linux.sh "
                     "--controller URL --token bbe_… on the machine does the "
                     "rest. It needs no key from this container, and it then "
                     "takes every kind of job, docker included."}


def node_update(principal, node_id, fields):
    """Rename, re-pool, relabel, set concurrency, and (for a deliberately
    restricted node, which nothing in the UI makes) capabilities:
    the editable half of a row. Never the id, the kind or the address: an
    address is an identity question, and the answer to "this node moved"
    is a new node (door 1), not an edit that makes old records lie."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    sets, args = [], []
    if "name" in fields:
        # The name is what a node is called everywhere here: the pickers,
        # the project rows, and the label a runner registers with. One
        # word, the charset a label and a hostname both take, and not one
        # another live node already wears. The controller's own row is not
        # a node anybody names.
        name = str(fields["name"]).strip()[:60]
        if n["kind"] == "local":
            return {"error": "this container is not a node to rename"}
        if not names.PROJECT_NAME.fullmatch(name):
            return {"error": "a node name is letters, digits, dots, dashes and underscores, "
                             "starting with a letter or digit"}
        if any(o["id"] != node_id and o["state"] != "retired"
               and o["name"].lower() == name.lower() for o in node_list()):
            return {"error": f"another node is already called {name}"}
        sets.append("name = ?"); args.append(name)
    if "pool" in fields:
        sets.append("pool = ?")
        args.append(str(fields["pool"]).strip()[:60] or "default")
    if "concurrency" in fields:
        try:
            c = max(1, min(64, int(fields["concurrency"])))
        except (TypeError, ValueError):
            return {"error": "concurrency is a small whole number"}
        sets.append("concurrency = ?"); args.append(c)
    if "capabilities" in fields:
        caps = [c for c in fields["capabilities"] if c in CAPABILITIES]
        if n["kind"] == "local" and "docker-host" in caps:
            # The local node is not a sandbox (docs/nodes.md §12): jobs here
            # run beside /config and the dashboard credential, and a docker
            # socket is not something this container mounts by default.
            return {"error": "the local node cannot be a docker host"}
        sets.append("capabilities = ?"); args.append(json.dumps(caps))
    if "labels" in fields and isinstance(fields["labels"], dict):
        clean = {str(k)[:40]: str(v)[:120]
                 for k, v in list(fields["labels"].items())[:24]}
        sets.append("labels = ?"); args.append(json.dumps(clean))
    if "host_only" in fields:
        on = fields["host_only"] is True
        if on:
            import wssync
            held = wssync.bound_projects(node_id)
            if held:
                return {"error": f"{', '.join(held)} {'lists' if len(held) == 1 else 'list'} this node "
                                 "among its nodes: take it out of their settings first, so no code "
                                 "or session is left on a node that is to host containers only"}
        cfg = dict(n.get("config") or {}, host_only=True)
        if not on:
            cfg.pop("host_only", None)
        sets.append("config = ?"); args.append(json.dumps(cfg))
        _synced["at"] = 0.0
    if not sets:
        return {"error": "nothing to change"}
    args.append(node_id)
    _exec(f"UPDATE nodes SET {', '.join(sets)} WHERE id = ?", args)
    _touch(node_id, principal, "node-update", fields)
    return {"ok": True}


def node_state(principal, node_id, state):
    """Drain and undrain, plus retire, which is what Remove means: rows
    are history and an id is never reused, so a removed node keeps its row
    and leaves every list (door 1)."""
    if state not in ("online", "draining", "retired"):
        return {"error": "state is online, draining or retired"}
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] == "local" and state == "retired":
        return {"error": "the local node is this container; it cannot be "
                         "removed, only left with nothing to do"}
    if state == "online" and n["state"] == "pending":
        return {"error": "a pending node comes online by enrolling"}
    _exec("UPDATE nodes SET state = ? WHERE id = ?", (state, node_id))
    if state == "retired":
        # A retired node's agent keeps dialing in until somebody stops the
        # unit; its credential failing closed is what tells it (and the
        # operator) that "removed" meant it (docs/nodes.md §4, rotation
        # and revocation are rows).
        revoke_tokens(node_id)
    _touch(node_id, principal, "node-" + state, {})
    return {"ok": True}


def node_lock(principal, node_id, lock):
    """Lock a node's system changes to its own console: with the lock on,
    Apply storage, Apply network and a root command are refused here, and
    the machine's mounts, address and root are its administrator's at the
    OS level only. For a node somebody manages by hand, or one whose fstab
    and netplan are not the dashboard's to rewrite. The desired config is
    kept and still shown beside what the node reports; only applying it
    stops. The runner and a funnel are BuilderBot's own footprint and are
    not covered."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "only an agent node has a configuration plane to lock"}
    conf = dict(n.get("config") or {})
    if bool(conf.get("lock")) == bool(lock):
        return {"ok": True, "lock": bool(lock)}
    conf["lock"] = bool(lock)
    _exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(conf), node_id))
    _touch(node_id, principal, "node-lock" if lock else "node-unlock", {})
    return {"ok": True, "lock": bool(lock)}


def node_locked(n):
    """The sentence a locked node refuses with, or "" when it is not."""
    if n and (n.get("config") or {}).get("lock"):
        return (f"system changes on {n['name']} are locked to its own console: "
                "its mounts, address and root are managed at the OS level; Unlock "
                "under Advanced on the Nodes tab to change that")
    return ""


def docker_nodes():
    """The docker-host nodes, for every picker: active ones with somewhere
    to send docker to. An agent node that has never dialed in has no known
    address yet, so it is not offered: a row with no way in would be a row
    that only ever says 'no answer'. Somewhere to send to, note, and not a
    daemon that answers: nothing here asks, and the tab is where a node that
    does not answer says so."""
    # Every node with a way in. Not narrowed by capability any more (a node
    # does everything), so the two exclusions left are the honest ones: a
    # node the manager cannot reach would be a row that only ever says "no
    # answer", and `local` is the controller, whose daemon is whatever socket
    # somebody deliberately mounted (docs/nodes.md §12: containers there run
    # beside /config and the dashboard credential), so it appears only when
    # that was done, which is what docker-host on local means.
    return [n for n in node_list()
            if n["state"] not in ("retired", "pending")
            and (_addr(n) if n["kind"] != "local"
                 else "docker-host" in n["capabilities"])]


def _addr(n):
    """Where docker on this node answers, for whichever kind it is.

    An agent node's address is informational and refreshed by the node
    itself on every dial-in (docs/nodes.md §2: the id is the identity, the
    address is data), so it changes without anything on this side being
    edited.

    A compose action reaches the node as a job on the agent, not through
    this; a row still shows where the node answered from.
    """
    if n["kind"] == "agent":
        addr = (n.get("agent") or {}).get("addr") or ""
        user = (n.get("config") or {}).get("user") or ""
        if addr and user and (n.get("reported") or {}).get("sshd"):
            return f"ssh://{user}@{addr}"
    return ""


def ssh_addr_of(node_id):
    """The address a node's daemon answers on; '' for local/unknown."""
    n = node(node_id)
    return _addr(n) if n else ""


# ---------------------------------------------------------------------------
# tokens, phase 3. Two kinds, one table (door 8: the kind is data).
#
# An ENROLL token is minted by the operator, bound to a node row created
# pending for it, and burned by the one enrollment it admits. A NODE token is
# what enrollment hands back: the bearer credential every later call carries.
# Only the sha256 of a secret is stored, so the table is worthless to read;
# the secret itself is shown exactly once, at mint, and never again.
#
# Secrets are self-describing (bbe_… enrolls, bbn_… is a node), so the
# server can route a bearer to the right lookup without a second header, and
# a token pasted in the wrong place fails with the right sentence.

TOKEN_PREFIX = {"enroll": "bbe_", "node": "bbn_"}
ENROLL_TTL = 24 * 3600           # a token the operator minted and forgot
                                 # should not admit a machine next month


def _hash(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def _token_mint(kind, node_id, ttl=None):
    secret = secrets.token_urlsafe(32)
    tid = mint("t")
    now = int(time.time())
    _exec("INSERT INTO tokens (id, kind, node_id, secret_hash, created, "
          "expires, revoked, uses) VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
          (tid, kind, node_id, _hash(secret), now,
           now + ttl if ttl else None))
    return tid, TOKEN_PREFIX[kind] + secret


def authenticate(bearer):
    """A bearer credential to a principal, or the reason it is not one.

    Returns {"principal": "node:<id>", "node": <id>, "kind": ..} or
    {"error": ..}. Enroll tokens authenticate only the enrollment itself
    (and the agent download that precedes it); a node token authenticates
    the node it was issued to, for as long as neither it nor the node has
    been revoked. Fail-closed on every doubt: a token that cannot be found
    and one that was revoked read the same from outside, on purpose.
    """
    bearer = (bearer or "").strip()
    kind = next((k for k, p in TOKEN_PREFIX.items() if bearer.startswith(p)),
                None)
    if not kind:
        return {"error": "not a BuilderBot token"}
    secret = bearer[len(TOKEN_PREFIX[kind]):]
    rows = _rows("SELECT * FROM tokens WHERE secret_hash = ? AND kind = ?",
                 (_hash(secret), kind))
    if not rows:
        return {"error": "unknown token"}
    t = rows[0]
    if t["revoked"]:
        return {"error": "credential revoked" if kind == "node"
                else "enrollment token already used"}
    if t["expires"] and t["expires"] < time.time():
        return {"error": "token expired"}
    n = node(t["node_id"])
    if not n or n["state"] == "retired":
        return {"error": "credential revoked"}
    return {"principal": f"node:{n['id']}", "node": n["id"], "kind": kind,
            "token": t["id"]}


def revoke_tokens(node_id, kinds=("node", "enroll")):
    _exec("UPDATE tokens SET revoked = 1 WHERE node_id = ? AND revoked = 0 "
          f"AND kind IN ({', '.join('?' * len(kinds))})",
          (node_id, *kinds))


# ---------------------------------------------------------------------------
# enrollment

def enroll_mint(principal, name, capabilities=None, user="bb", tunnel=None, host_only=False, nginx=False, door=None,
                existing=None):
    """Add node, agent kind: a pending row and the one token that fills it.
    With `existing` (R177), no row: a node already here gets a new enroll
    token, its config brought to the answers, and the row's id and state
    kept, so the script can be run again on that same machine (the
    agent's machine fingerprint, which enroll() holds it to).

    The row exists BEFORE the machine does, which is the operator's view of
    "waiting for enrollment" (a line on the tab with the command to paste),
    and it is where the token's scope lives: the capabilities the controller
    intended are on the row, so enrollment adds nothing the operator did not
    ask for. The id is minted now and kept; a token that expires unused
    leaves a pending row the tab offers to remove, never a reused id.
    """
    name = (name or "").strip()[:60] or "node"
    caps = [c for c in (capabilities or CAPABILITIES) if c in CAPABILITIES]
    user = re.sub(r"[^a-z0-9_-]", "", (user or "bb").lower())[:32] or "bb"
    if existing:
        n = node(existing)
        if not n or n.get("kind") != "agent" or n.get("state") == "retired":
            return {"error": "no such node to enroll again"}
        cfg = dict(n.get("config") or {})
        cfg["user"] = user
        for key, val in (("tunnel", tunnel), ("host_only", True if host_only else None),
                         ("nginx", True if nginx else None), ("door", door)):
            if val:
                cfg[key] = val
            else:
                cfg.pop(key, None)
        _exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(cfg), existing))
        revoke_tokens(existing, ("enroll",))
        tid, secret = _token_mint("enroll", existing, ENROLL_TTL)
        _touch(existing, principal, "node-enroll-mint", {"token": tid, "again": True})
        return {"ok": True, "id": existing, "token": secret, "again": True,
                "expires": int(time.time()) + ENROLL_TTL}
    nid = mint("n")
    _insert_node({
        "id": nid, "name": name, "kind": "agent",
        "pool": "default", "created": int(time.time()), "state": "pending",
        "concurrency": 1, "ssh_addr": "",
        "capabilities": caps, "services": {},
        "labels": {"disposable": "true"},
        "agent": {}, "reported": {}, "routing": {},
        # The node's address in a tunnel, from the config the script
        # carries (R161): what the controller refuses all but the agent's
        # own API from, before the node has said anything itself.
        "config": {"user": user, **({"tunnel": tunnel} if tunnel else {}),
                   # Its projects as a synced copy (R162), the one way a node
                   # holds them: no node mounts the controller's disk (R163).
                   "workspace": "sync",
                   # Hosting only from its first hello (a cloud box enrolled
                   # to run containers): no code, sessions or bb, ever.
                   **({"host_only": True} if host_only else {}),
                   # nginx put on it once it has enrolled (R171, ON_ENROLL).
                   **({"nginx": True} if nginx else {}),
                   # The door in for SSH the script sets up (R174): its kind
                   # and name, so the row knows before the machine reports.
                   **({"door": door} if door else {})},
    })
    tid, secret = _token_mint("enroll", nid, ENROLL_TTL)
    _touch(nid, principal, "node-enroll-mint", {"token": tid, "caps": caps})
    return {"ok": True, "id": nid, "token": secret,
            "expires": int(time.time()) + ENROLL_TTL}


def enroll_script(principal, req):
    """Enroll node's questions answered, as one script to download (R161,
    enrollscript.py): checked before anything is minted, so a config that
    cannot be used leaves no pending row; then the row and its token, and
    the provisioner with the answers inside. Nothing of it is kept here."""
    ho = req.get("host_only") is True
    # Again, for a node that is here (R177): the row's answers where the
    # request leaves them out, its secrets never (the node keeps them),
    # and the script bound to the machine the node reported.
    again = node(field(req, "node")) if field(req, "node") else None
    if field(req, "node") and not again:
        return {"error": "no such node to enroll again"}
    ans = enrollscript.check(req | ({"sessions": False} if ho else {}), again=bool(again))
    if ans.get("error"):
        return ans
    prov = AGENT_DIR.parent.parent / "nodes" / "provision-linux.sh"
    if not prov.is_file():
        return {"error": "this controller ships no provisioner"}
    user = re.sub(r"[^a-z0-9_-]", "", (field(req, "user") or "bb").lower())[:32] or "bb"
    tunnel = ({"kind": "wireguard", "addr": ans["tunnel_addr"]} if ans["reach"] == "wireguard"
              else {"kind": "public", "host": ans["tunnel_host"]} if ans["reach"] == "public"
              else None)
    # Through a public hostname the node is hosting only, whatever was
    # ticked (enrollscript.check): the session ports cannot be reached back.
    ho = ho or ans["reach"] == "public"
    if again and ans["reach"] == "wireguard" and not tunnel:
        tunnel = ((again.get("config") or {}).get("tunnel") or None)
    m = enroll_mint(principal, field(req, "name"), req.get("capabilities"), user, tunnel=tunnel, host_only=ho,
                    nginx=req.get("nginx") is True,
                    door={"kind": ans["door"], "host": ans.get("door_host", "")} if ans.get("door") else None,
                    existing=again["id"] if again else None)
    _synced["at"] = 0.0
    if m.get("error"):
        return m
    name = node(m["id"])["name"]
    u = urllib.parse.urlparse(ans["controller"])
    port = u.port or (443 if u.scheme == "https" else 80)
    machine = ((again or {}).get("reported") or {}).get("machine") or ""
    return m | {"script": enrollscript.build(ans, name=name, user=user, token=m["token"],
                                              expires=m["expires"], provisioner=prov.read_bytes(),
                                              again=bool(again), machine=machine),
                "filename": enrollscript.filename(name), "reach": ans["reach"],
                "home": enrollscript.home_rules(ans, port),
                "tunnel_addr": ans.get("tunnel_addr", "")}


# What runs once a node has enrolled, each handed its id (the nginx tab's
# deploy for a node the Enroll dialog ticked it on, R171): filled by the
# server, run after the row is online, each on its own so one's failure
# never costs the enrollment.
ON_ENROLL = []


def enroll(auth, census, addr, version="", digest="", user=""):
    """The one call an enroll token admits: burn it, issue the node token,
    bring the row online. `auth` is authenticate()'s answer for the token."""
    nid = auth["node"]
    n = node(nid)
    if not n or n["state"] == "retired":
        return {"error": "this node is not waiting for enrollment"}
    # A node enrolling again (R177) is held to the machine it enrolled
    # from: the fingerprint its census reports against the one on the row.
    # Said before the token is burned, so the right machine can still use it.
    had = (n.get("reported") or {}).get("machine") or ""
    got = str((census or {}).get("machine") or "") if isinstance(census, dict) else ""
    if n["state"] != "pending" and had and got and had != got:
        return {"error": f"this script was made for {n['name']}, which is another machine: "
                         "make a script for this one on the Nodes tab (Enroll node)"}
    # Burned in one statement, so two enrolments racing on one token (a
    # provisioner's retry) cannot both pass and mint two node tokens.
    cur = _exec("UPDATE tokens SET revoked = 1, uses = uses + 1 WHERE id = ? AND revoked = 0",
                (auth["token"],))
    if cur.rowcount != 1:
        return {"error": "this enrollment token was already used"}
    # Every earlier token goes with the enrollment: the node token the
    # last agent held, so a script run again leaves one agent, not two.
    revoke_tokens(nid, ("enroll", "node"))
    tid, secret = _token_mint("node", nid)
    cfg = n.get("config") or {}
    if user:
        cfg["user"] = re.sub(r"[^a-z0-9_-]", "", user.lower())[:32] or "bb"
    rep = _census(census)
    _exec("UPDATE nodes SET state = 'online', agent = ?, reported = ?, "
          "config = ?, os = ?, arch = ? WHERE id = ?",
          (json.dumps({"token_id": tid, "version": str(version)[:40],
                       "digest": str(digest)[:80], "addr": addr,
                       "last_seen": int(time.time())}),
           json.dumps(rep), json.dumps(cfg), rep["system"], rep["arch"], nid))
    _touch(nid, auth["principal"], "node-enroll", {"addr": addr})
    for fn in ON_ENROLL:
        try:
            fn(nid)
        except Exception as e:  # noqa: BLE001 (said, never the enrollment's failure)
            print(f"[nodes] after enrolling {nid}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    return {"ok": True, "node_id": nid, "token": secret,
            "name": n["name"], "capabilities": n["capabilities"],
            "user": cfg.get("user", "bb"), "poll": POLL_S}


# ---------------------------------------------------------------------------
# the channel: hello, and the long-poll that carries the heartbeat
#
# Long-poll only (docs/nodes.md §4): the agent POSTs `work` with
# its current sample and the request is held until there is a job for it or
# the poll window closes, so one request per node per POLL_S is the whole
# cost of liveness, metrics and job pickup together. The design wrote the
# poll as a GET; a heartbeat is a body, and a GET with a body is not a thing,
# so the verb is POST and the doc was corrected to say so.


def agent_window(version):
    """The compatibility window a version string promises: "0.4" of "0.4.27".

    Empty for anything that is not WINDOW.BUILD, which includes every agent
    built before the window existed. Empty means "cannot say", and every
    caller reads it that way rather than guessing: an old agent is stale for
    the ordinary reason (a different digest) and does not need a second,
    louder claim made up about it.
    """
    m = re.match(r"^(\d+\.\d+)\.", str(version or ""))
    return m.group(1) if m else ""
# Held below the 30s most proxies allow. Settable only so the suite can stop
# waiting on it: an agent does its housekeeping (restarting a ttyd that died,
# reporting a session that appeared) once per turn of this loop, so a test
# that watches for any of it waits a poll window per thing it watches, and
# three of them were the slowest intervals in the suite. Nothing else sets it.
POLL_S = int(os.environ.get("BB_NODE_POLL") or 25)
_wake = threading.Condition(_lock)
# The last minute of samples per node, for a sparkline (docs/nodes.md §9):
# memory only, and lost on restart, which is the honest scope: the row keeps
# the current sample in the DB, and history is /metrics plus whatever the
# operator points at it.
_samples = {}
SAMPLES_KEEP = 60


def _mb(v):
    """A megabyte count from the agent, or None: a store that is not there
    reports null, and null is kept apart from zero all the way to the row."""
    if v is None:
        return None
    try:
        return max(0, int(v))
    except (TypeError, ValueError, OverflowError):
        # OverflowError: json.loads takes Infinity, and int() of it raises
        # (B180). A number no disk has is no number.
        return 0


def _census(c):
    """What a node says about itself, kept to the fields the row shows.
    Whitelisted rather than stored whole: a census is a JSON blob from a
    machine that could be lying, and the row is rendered from it."""
    c = c if isinstance(c, dict) else {}
    out = {}
    for k in ("cpu", "mem_mb"):
        with contextlib.suppress(TypeError, ValueError):
            out[k] = int(c.get(k) or 0)
    for k in ("os", "docker", "docker_id", "gpu", "hostname", "git"):
        if c.get(k):
            out[k] = str(c[k])[:120]
    # The machine's fingerprint (R177): what a re-enrollment is held to.
    if re.fullmatch(r"[0-9a-f]{32}", str(c.get("machine") or "")):
        out["machine"] = str(c["machine"])
    # The two placement dimensions (door 9), as fields the agent reports.
    out["system"] = re.sub(r"[^a-z0-9]", "", str(c.get("system") or "").lower())[:20]
    out["arch"] = re.sub(r"[^a-zA-Z0-9_]", "", str(c.get("arch") or ""))[:20]
    out["sshd"] = bool(c.get("sshd"))
    stores = c.get("stores") if isinstance(c.get("stores"), dict) else {}
    out["stores"] = {}
    for role, s in list(stores.items())[:8]:
        if isinstance(s, dict):
            out["stores"][str(role)[:20]] = {
                "path": str(s.get("path") or "")[:200],
                # The marker inside the store (store_id): what says two
                # machines mounting it at different paths, over different
                # transports, are looking at one directory. Dropping it here
                # is how the pair stays invisible, the same way store_dirs
                # was lost before it was whitelisted.
                "id": str(s.get("id") or "")[:64],
                "free_mb": _mb(s.get("free_mb")),
                "total_mb": _mb(s.get("total_mb")),
                # What the store holds, from the census's du (phase 6): the
                # cache's number beside Clear cache. None when not measured.
                "used_mb": _mb(s.get("used_mb")),
                # The node's own directory in the store: linux-x86_64,
                # darwin-arm64 (roadmap R19).
                "scope": re.sub(r"[^A-Za-z0-9_-]", "", str(s.get("scope") or ""))[:40]}
    # {name: version} from `bb toolchains versions` on the node: the controller's
    # own generator, run there. Whitelisted like store_dirs, and for the same
    # reason: a value the agent reports and this drops is a value that does
    # not exist.
    # The tunnel the node reaches the controller through (R161): its kind,
    # its address there, and whether the interface is up.
    t = c.get("tunnel") if isinstance(c.get("tunnel"), dict) else {}
    if t.get("addr") and re.fullmatch(r"[0-9.]{7,15}", str(t["addr"])):
        out["tunnel"] = {"kind": re.sub(r"[^a-z]", "", str(t.get("kind") or ""))[:20],
                         "addr": str(t["addr"]), "up": bool(t.get("up"))}
    pv = c.get("toolchain_versions") if isinstance(c.get("toolchain_versions"), dict) else {}
    out["toolchain_versions"] = {str(k)[:40]: str(v)[:40] for k, v in list(pv.items())[:40]}
    sd = c.get("store_dirs") if isinstance(c.get("store_dirs"), dict) else {}
    out["store_dirs"] = {k: [str(x)[:60] for x in (sd.get(k) or [])[:64]]
                         for k in ("top", "android", "incomplete")}
    # The android system images in the toolchain store, and the AVDs built on
    # each (roadmap #20). Whitelisted like store_dirs and toolchain_versions,
    # and for the same reason: a field the agent reports and this drops is a
    # field that does not exist. Absent rather than empty when the agent did
    # not send it at all: a node that has not answered is not a node with
    # none, and the tab must not say "nothing installed" on its behalf.
    if isinstance(c.get("images"), list):
        out["images"] = []
        for im in c["images"][:64]:
            if not isinstance(im, dict) \
                    or not str(im.get("id") or "").startswith("system-images;"):
                continue
            out["images"].append({
                "id": re.sub(r"[^A-Za-z0-9;._-]", "", str(im["id"]))[:120],
                "api": str(im.get("api") or "")[:20], "kind": str(im.get("kind") or "")[:40],
                "abi": str(im.get("abi") or "")[:20],
                "avds": [str(a)[:60] for a in (im.get("avds") or [])[:16]]})
    tc = c.get("toolchains") if isinstance(c.get("toolchains"), dict) else {}
    out["toolchains"] = {str(k)[:30]: (str(v)[:40] if v else None)
                         for k, v in list(tc.items())[:16]}
    # The configuration plane's reported half (docs/nodes.md §12): whether
    # the node was provisioned as a sandbox (bb-sandbox is there: the stamp
    # system jobs are gated on), what it mounts as bb-sandbox reads it, and
    # the address it is on. Facts about the machine, drawn against the
    # operator's desired config on the row; never treated as the config.
    out["sandbox"] = bool(c.get("sandbox"))
    # The GPU (R20): the NVIDIA card by its PCI id, before any driver, and
    # what the display's unit last said; absent where there is no card.
    for k in ("gpu_card", "gpu_display"):
        if c.get(k):
            out[k] = str(c[k])[:200]
    # Where the NVIDIA driver stands (R102): installed for this kernel,
    # loaded now, and which driver has the card, for the Toolchains tab's
    # driver row. Absent from an agent too old to say, which the row names.
    gd = c.get("gpu_driver")
    if c.get("gpu_card") and isinstance(gd, dict):
        clean = lambda v, n=60: re.sub(r"[^A-Za-z0-9._~+:-]", "", str(v or ""))[:n]  # noqa: E731
        out["gpu_driver"] = {k: clean(gd.get(k)) for k in
                             ("installed", "loaded", "bound", "package", "pkg_version", "candidate", "recommended")}
        # The branches apt offers there, for the row's pulldown: a package
        # name, its version, and whether it is the open-kernel variant.
        out["gpu_driver"]["options"] = [
            {"pkg": clean(o.get("pkg")), "version": clean(o.get("version"), 30), "open": bool(o.get("open"))}
            for o in (gd.get("options") or [])[:16]
            if isinstance(o, dict) and DRIVER_PKG.fullmatch(str(o.get("pkg") or ""))]
    # ...and the container toolkit (R102): the version installed, what apt
    # would move it to, and whether Docker lists the nvidia runtime.
    gc = c.get("gpu_container")
    if c.get("gpu_card") and isinstance(gc, dict):
        ver = lambda v: re.sub(r"[^A-Za-z0-9._~+:-]", "", str(v or ""))[:60]  # noqa: E731
        out["gpu_container"] = {"installed": ver(gc.get("installed")), "candidate": ver(gc.get("candidate")),
                                "runtime": bool(gc.get("runtime"))}
    # The sound it has (R107): ALSA's cards, real and virtual apart, and the
    # sound server installed. Absent from an agent too old to say.
    snd = c.get("sound")
    if isinstance(snd, dict):
        word = lambda v: re.sub(r"[^A-Za-z0-9 ._()/:+-]", "", str(v or ""))[:80]  # noqa: E731
        out["sound"] = {"cards": [word(x) for x in (snd.get("cards") or [])[:8]],
                        "virtual": [word(x) for x in (snd.get("virtual") or [])[:8]],
                        "server": snd.get("server") if snd.get("server") in ("pipewire", "pulseaudio") else ""}
    # Whether the agent may install system packages there: the stamp and
    # root.
    out["administers"] = bool(c.get("administers"))
    # Whether a session there sees only its own project (R35), in the
    # helper's own answer, and why not. An agent from before it reports
    # nothing, which the row says as unknown rather than as a no.
    iso = c.get("isolation")
    if isinstance(iso, dict):
        out["isolation"] = {"sessions": bool(iso.get("sessions")), "why": str(iso.get("why") or "")[:200]}
    # ...and whether each session there reaches only its own project's
    # containers (R79): whether the node can, why not, whether it is in
    # force, how many sessions have a network of their own, and what went
    # wrong setting it up. Absent from an older agent, and empty before its
    # first look, both of which the row reads as not told.
    sn = c.get("session_net")
    if isinstance(sn, dict) and sn:
        out["session_net"] = {"can": bool(sn.get("can")), "why": str(sn.get("why") or "")[:200],
                              "wanted": bool(sn.get("wanted")), "active": bool(sn.get("active")),
                              "sessions": int(sn.get("sessions") or 0) if str(sn.get("sessions") or 0).isdigit() else 0,
                              "error": str(sn.get("error") or "")[:300]}
    # Which held recipes need system packages the machine lacks (roadmap
    # R51): the family and, per recipe, the package names, both bounded.
    sd = c.get("sysdeps") if isinstance(c.get("sysdeps"), dict) else {}
    unmet = sd.get("unmet") if isinstance(sd.get("unmet"), dict) else {}
    out["sysdeps"] = {
        "family": re.sub(r"[^a-z]", "", str(sd.get("family") or ""))[:12],
        "unmet": {re.sub(r"[^A-Za-z0-9:._-]", "", str(k))[:40]:
                  [re.sub(r"[^A-Za-z0-9:._+/-]", "", str(x))[:60] for x in v if str(x)][:64]
                  for k, v in list(unmet.items())[:32] if isinstance(v, list) and v}}
    out["mounts"] = []
    for m in (c.get("mounts") if isinstance(c.get("mounts"), list) else [])[:32]:
        if isinstance(m, dict) and str(m.get("path") or "").startswith("/"):
            out["mounts"].append({
                "path": str(m["path"])[:200], "source": str(m.get("source") or "")[:200],
                "type": str(m.get("type") or "")[:16], "ro": bool(m.get("ro")),
                "mounted": bool(m.get("mounted")), "real": str(m.get("real") or "")[:200],
                "stale": bool(m.get("stale")),
                # What mount said when it failed: the server's own reason.
                "error": str(m.get("error") or "")[:200]})
    # The door in for SSH (R174), as the machine has it: its kind, its
    # name, whether the client is there and whether it is up.
    dr = c.get("door") if isinstance(c.get("door"), dict) else {}
    if dr.get("kind") in ("cloudflared", "tailscale"):
        out["door"] = {"kind": dr["kind"], "host": re.sub(r"[^a-z0-9.-]", "", str(dr.get("host") or "").lower())[:253],
                       "installed": bool(dr.get("installed")), "active": bool(dr.get("active"))}
    sv = c.get("services") if isinstance(c.get("services"), dict) else {}

    def one_runner(ar):
        url = str(ar.get("url") or "")[:200]
        return {
            "installed": bool(ar.get("installed")), "active": bool(ar.get("active")),
            "busy": bool(ar.get("busy")), "name": str(ar.get("name") or "")[:80],
            "url": url,
            "slot": re.sub(r"[^a-z0-9.-]", "", str(ar.get("slot") or ""))[:60] or runner_slot(url),
            # Which host's runner it is: GitHub's, or Gitea's act_runner.
            "forge": re.sub(r"[^a-z]", "", str(ar.get("forge") or ""))[:16],
            # The systemd unit its output goes to, when it has one: what the
            # runner log stream journalctls. Empty from a node running it in
            # the foreground, and the stream reads runner.log then.
            "unit": re.sub(r"[^A-Za-z0-9._@-]", "", str(ar.get("unit") or ""))[:120],
            "labels": [re.sub(r"[^A-Za-z0-9._-]", "", str(x))[:40]
                       for x in (ar.get("labels") or [])[:16] if str(x)]}
    # One runner per git host (R53).
    listed = sv.get("runners") if isinstance(sv.get("runners"), list) else []
    runners = [one_runner(x) for x in listed[:16] if isinstance(x, dict)]
    out["services"] = {"runners": runners}
    ts = sv.get("tailscale") if isinstance(sv.get("tailscale"), dict) else {}
    fun = ts.get("funnel") if isinstance(ts.get("funnel"), dict) else {}
    out["services"]["tailscale"] = {
        "installed": bool(ts.get("installed")),
        "dns": re.sub(r"[^A-Za-z0-9.-]", "", str(ts.get("dns") or ""))[:200],
        # https port -> the local port it forwards to, as the node reports it
        "funnel": {str(k)[:6]: _mb(v) for k, v in list(fun.items())[:8]}}
    # The session half (roadmap #24): whether this node runs sessions, on
    # which ports, as which account, and whether /workspace, where its
    # synced copy is, is there. Absent (not empty) from an agent too
    # old to report it, so the row can tell "no sessions here" from "did not
    # say"; the proxy relays a project's session to a node only on the
    # strength of this.
    se = c.get("session")
    if isinstance(se, dict):
        out["session"] = {
            "up": bool(se.get("up")), "port": _mb(se.get("port")) or 0,
            "ro_port": _mb(se.get("ro_port")) or 0,
            "user": re.sub(r"[^A-Za-z0-9._-]", "", str(se.get("user") or ""))[:32],
            "workspace": bool(se.get("workspace")),
            # None is "not probed", read as unknown rather than read-only:
            # a /workspace the agent could not test is not one it found
            # closed. Said in bb diag; no gate reads it since the synced
            # copy is the node's own directory (R163).
            "writable": None if "writable" not in se else bool(se.get("writable")),
            "claude": str(se.get("claude") or "")[:40],
            "bundle": str(se.get("bundle") or "")[:80],
            # The agent's own sentence for a half that is down (no session
            # account, no ttyd, a port taken), which the row's dead button
            # repeats. Dropped once, and the button said only "runs none yet".
            "why": str(se.get("why") or "")[:120],
            # The node's own boot id, which a terminal's URL has to carry for
            # a session THERE (bb-tty compares against the machine it runs
            # on); the row hands it to the page per project.
            "boot": re.sub(r"[^0-9.]", "", str(se.get("boot") or ""))[:40],
            # Seconds since the machine booted, from an agent that reports
            # it. Finite: json.loads takes Infinity and NaN, and int() of either
            # raised, failing the node's whole hello (B180).
            "up_s": max(-1, int(se["up_s"])) if isinstance(se.get("up_s"), (int, float))
                    and math.isfinite(se["up_s"]) else None}
    net = c.get("network") if isinstance(c.get("network"), dict) else {}
    out["network"] = {
        "interface": str(net.get("interface") or "")[:32],
        "addresses": [str(a)[:64] for a in (net.get("addresses") or [])[:8]],
        "gateway": str(net.get("gateway") or "")[:64],
        "dns": [str(a)[:64] for a in (net.get("dns") or [])[:8]],
        # Its static routes beside the default one (absent from an agent
        # before 0.7.143, which reads as none reported).
        "routes": [{"to": str(r.get("to") or "")[:64], "via": str(r.get("via") or "")[:64]}
                   for r in (net.get("routes") or [])[:32] if isinstance(r, dict)]}
    # The machine's own tools, as the agent detected them: its package
    # manager and the service that owns its network. A system job's spec is
    # the same for every node; this says what the agent there would turn it
    # into, so the row can say so, and absent until the agent has looked,
    # which the row reads as "not reported", not as none.
    d = c.get("distro") if isinstance(c.get("distro"), dict) else None
    if d is not None:
        out["distro"] = {k: re.sub(r"[^a-zA-Z0-9 ._()/-]", "", str(d.get(k) or ""))[:80]
                         for k in ("id", "family", "pretty", "pkg", "network")}
    return out


# ---------------------------------------------------------------------------
# the configuration plane (docs/nodes.md §12, phase 5)
#
# The operator's DESIRED storage and network for a node live on its record
# (config.desired); the agent reports what is APPLIED in its census
# (reported.mounts / .stores / .network); and a change is a `system` job the
# agent runs as root: audited like any mutation, offered only to nodes that
# enrolled as a sandbox, refused on the node without the stamp as well.
# bb-sandbox at the console reads and writes the same on-node state, so the
# GUI and a rescue shell cannot disagree about what the node is meant to be.

MOUNT_TYPES = ("nfs", "virtiofs")
STORE_ROLES = ("data", "toolchains", "cache", "artifacts", "appdata")
# The same refusal the agent makes of a store path, made here so the tab says
# no before anybody presses. Deliberately in both places: a store is a
# directory this system creates, fills and (for the cache) empties, so one
# pointed at /etc is a delete waiting to happen, and the node refuses whatever
# it is told regardless (docs/nodes.md §15 door 7, applied to disk).
STORE_DENY_EXACT = {"/", "/bin", "/boot", "/dev", "/etc", "/home", "/lib",
                    "/lib32", "/lib64", "/libx32", "/media", "/mnt", "/opt",
                    "/proc", "/root", "/run", "/sbin", "/srv", "/sys", "/tmp",
                    "/usr", "/var"}
STORE_DENY_UNDER = ("/bin/", "/boot/", "/dev/", "/etc/", "/lib/", "/lib32/",
                    "/lib64/", "/libx32/", "/proc/", "/root/", "/run/",
                    "/sbin/", "/sys/", "/usr/", "/var/log/", "/var/run/",
                    "/var/lock/", "/var/spool/", "/var/cache/")


def store_path_ok(path):
    """"" if this is a safe place for a store, else why not."""
    p = str(path or "").rstrip("/") or "/"
    if not p.startswith("/"):
        return f"{path!r} is not an absolute path"
    if " " in p or ".." in p.split("/"):
        return f"{path!r} must be a plain absolute path, with no spaces or .."
    if p in STORE_DENY_EXACT:
        return (f"{p} is a system directory (or the root of the mounts): a store "
                "is a directory of its own, like /var/lib/builderbot/x or /mnt/<share>/<dir>")
    for bad in STORE_DENY_UNDER:
        if (p + "/").startswith(bad):
            return f"{p} is inside {bad.rstrip('/')}, which the agent will not write to"
    return ""
_IP = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_CIDR = re.compile(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")


def _clean_config(cfg):
    """The desired config, validated to its shape, or an error string. Every
    field is bounded here so a system job's spec is never a blob from the
    page. The agent writes what arrives into fstab and into whichever
    backend owns its network (netplan, NetworkManager); the spec names the
    address, never the tool."""
    cfg = cfg if isinstance(cfg, dict) else {}
    out = {}
    mounts = []
    for m in (cfg.get("mounts") if isinstance(cfg.get("mounts"), list) else [])[:32]:
        if not isinstance(m, dict):
            continue
        path = str(m.get("path") or "").strip()
        src = str(m.get("source") or "").strip()
        kind = str(m.get("type") or "nfs").strip()
        if not path and not src:
            continue                              # an empty editor row
        if not path and src:
            # A mountpoint nobody typed: /mnt/<what the export is called>,
            # which is where a Linux box puts a mount and is what the
            # operator meant. The agent's bb-sandbox mkdir -p's it, so
            # naming a directory that does not exist yet is not a problem.
            # Only a default: anything that matters is typed.
            tail = src.rsplit("/", 1)[-1] if kind == "nfs" else src
            tail = re.sub(r"[^A-Za-z0-9._-]", "", tail).strip(".")
            if not tail:
                return None, f"nothing to name a mountpoint after in {src!r}; type one"
            path = "/mnt/" + tail
        if not path.startswith("/") or " " in path or ":" in path:
            return None, f"a mountpoint must be an absolute path without spaces: {path!r}"
        if path.rstrip("/") == "/workspace" or path.startswith("/workspace/"):
            # The node's own synced copy of its projects is there (R163): a
            # mount would cover it, and no node mounts the controller's disk.
            return None, "/workspace holds this node's synced copy of its projects; nothing is mounted there"
        if kind not in MOUNT_TYPES:
            return None, f"a mount is nfs or virtiofs, not {kind!r}"
        if kind == "nfs" and (":" not in src or src.startswith(":") or src.endswith(":")):
            return None, f"an NFS source is HOST:/export, not {src!r}"
        if kind == "virtiofs" and (not src or ":" in src or "/" in src):
            return None, f"a virtiofs source is the share's tag, not {src!r}"
        if any(x["path"] == path for x in mounts):
            return None, f"{path} is listed twice"
        mounts.append({"path": path[:200], "source": src[:200], "type": kind,
                       "ro": bool(m.get("ro"))})
    out["mounts"] = mounts
    stores = {}
    for role, path in (cfg.get("stores") if isinstance(cfg.get("stores"), dict) else {}).items():
        path = str(path or "").strip()
        if role not in STORE_ROLES or not path:
            continue
        why = store_path_ok(path)
        if why:
            return None, f"the {role} store: {why}"
        stores[role] = path[:200]
    out["stores"] = stores
    net = cfg.get("network") if isinstance(cfg.get("network"), dict) else {}
    mode = "static" if net.get("mode") == "static" else "dhcp"
    n = {"mode": mode, "interface": re.sub(r"[^A-Za-z0-9_.-]", "", str(net.get("interface") or ""))[:32]}
    if mode == "static":
        addr, gw = str(net.get("address") or "").strip(), str(net.get("gateway") or "").strip()
        if not _CIDR.match(addr):
            return None, f"a static address is written with its prefix, like 10.0.0.12/24, not {addr!r}"
        if gw and not _IP.match(gw):
            return None, f"the gateway is an address, not {gw!r}"
        # str(): a hand-made request's [1] raised on .strip() instead of
        # being told a resolver is an address (B181).
        dns = [str(d).strip() for d in (net.get("dns") if isinstance(net.get("dns"), list)
                                        else str(net.get("dns") or "").split(",")) if str(d).strip()]
        for d in dns:
            if not _IP.match(d):
                return None, f"a resolver is an address, not {d!r}"
        n.update(address=addr, gateway=gw, dns=dns[:4])
    # Static routes (the operator, 7 Oct), in either mode: a network beyond
    # this one and the router that reaches it, as {to, via} or "TO via VIA".
    routes = []
    for r in net.get("routes") or []:
        if isinstance(r, dict):
            to, via = str(r.get("to") or "").strip(), str(r.get("via") or "").strip()
        else:
            parts = str(r).replace(" via ", " ").split()
            to, via = (parts + ["", ""])[:2]
        if not to and not via:
            continue
        if not _CIDR.match(to) or to.split("/")[1] in ("0",) or int(to.split("/")[1]) > 32:
            return None, (f"a route's network is written with its prefix, like 10.20.0.0/24, not {to!r}"
                          + (" (the default route is the gateway above)" if to.endswith("/0") else ""))
        if not _IP.match(via):
            return None, f"a route goes via a router's address, not {via!r}"
        if {"to": to, "via": via} not in routes:
            routes.append({"to": to, "via": via})
    if len(routes) > 32:
        return None, f"a node takes 32 static routes at most, not {len(routes)}"
    n["routes"] = routes
    out["network"] = n
    return out, ""


def node_config_set(principal, node_id, cfg):
    """Store what the operator wants this node to be. Nothing is applied
    here: apply is a job, and the row shows desired beside reported until
    one has run."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "only an agent node has a configuration plane; "
                         "an ssh node is configured at its own console"}
    clean, why = _clean_config(cfg)
    if why:
        return {"error": why}
    conf = dict(n.get("config") or {})
    conf["desired"] = clean
    _exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(conf), node_id))
    _touch(node_id, principal, "node-config",
           {"mounts": len(clean["mounts"]), "stores": sorted(clean["stores"]),
            "network": clean["network"]["mode"]})
    return {"ok": True, "desired": clean}


# ---- debug: which machine's logs a node's sessions may read ---------------
# A session on a node reads the logs of its own WORK by default (the CI runs
# for its project, what its test runs left), and nothing of the machine. The
# machine's own logs are root's there: the enrolled account is in neither
# `adm` nor `systemd-journal`, so `journalctl -u builderbot-agent` from a
# session answers "No journal files were opened due to insufficient
# permissions". That is a real boundary and not a convention.
#
# This opens it deliberately, per node, and only while the controller's
# `debug_mode` setting is on. The grant is stored beside `desired` rather
# than in it: nothing applies it to the machine, it is read at the moment a
# log is asked for.
#
# A node is NOT implicitly granted ITSELF. Its own journal is as much system
# level as any other machine's, and "it is only looking at itself" is the
# reasoning that makes a boundary stop meaning anything.
#
# What can be read is a TABLE, the way everything the web UI can execute is:
# a stream name resolves to an argv here, and nothing else is reachable
# through this door however it is asked for.
LOG_STREAMS = {
    "agent": {"what": "the agent's own journal: what it did, and why a job failed",
              "argv": ["journalctl", "-u", "builderbot-agent", "--no-pager",
                       "-n", "{lines}"]},
    # TWO SHAPES, and the node says which it is in. Under systemd the runner
    # is a service and its output is the journal's; with no systemd the agent
    # runs run.sh itself and redirects it into runner.log under the data
    # store. Reading the file unconditionally is what this did, so the answer
    # on every properly installed runner was "No such file or directory".
    # `unit` picks the first; an agent too old to report one falls to the
    # second, which is exactly what it used to do.
    "runner": {"what": "the CI runner's service log", "store": "data",
               "argv": ["tail", "-n", "{lines}", "{data}/runner.log"],
               "unit_argv": ["journalctl", "-u", "{unit}", "--no-pager",
                             "-n", "{lines}"]},
    "terminal": {"what": "the terminal server's log", "store": "data",
                 "argv": ["tail", "-n", "{lines}", "{data}/ttyd.log"]},
}
LOG_LINES_MAX = 2000


def node_turn_limit(principal, node_id, limit):
    """How many Claude sessions on this node may work on a prompt at once
    (turns.py): 0 for no limit. An administrator's, like the rest of the
    config plane; a session that could raise its own node's limit would make
    it a suggestion."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "only an agent node runs sessions"}
    want = turns.limit_of(limit)
    if want is None:
        return {"error": f"a limit is a whole number from 0 (none) to {turns.LIMIT_MAX}"}
    conf = dict(n.get("config") or {})
    conf["turns"] = want
    _exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(conf), node_id))
    _touch(node_id, principal, "node-turn-limit", {"limit": want})
    return {"ok": True, "limit": want}


def node_session_net(principal, node_id, on):
    """Whether each Claude session on this node reaches only its own
    project's containers, the controller and the internet (R79). An
    administrator's, like the rest of the config plane: a session that could
    turn it off for itself would make it a suggestion. The node hears at once,
    by a fresh hello, rather than at the next ten-minute one."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "only an agent node runs sessions"}
    conf = dict(n.get("config") or {})
    conf["session_net"] = bool(on)
    _exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(conf), node_id))
    _touch(node_id, principal, "node-session-net", {"on": bool(on)})
    ask_hello(node_id)
    return {"ok": True, "on": bool(on)}


def node_root_asks(principal, node_id, on):
    """Whether a session on this node may ask for a root command (bb root
    run): on, the ask goes to a person as ever; off, it is refused with the
    sentence root_refused says. An administrator's, like the rest of the
    config plane."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "only an agent node runs sessions"}
    conf = dict(n.get("config") or {})
    if on:
        conf.pop("no_root", None)
    else:
        conf["no_root"] = True
    _exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(conf), node_id))
    _touch(node_id, principal, "node-root-asks", {"on": bool(on)})
    return {"ok": True, "on": bool(on)}


def root_refused(n):
    """The sentence a node whose sessions may not ask for root refuses with,
    or "" when they may."""
    if n and (n.get("config") or {}).get("no_root"):
        return (f"root commands from sessions are off on {n['name']}: the Sessions "
                "section on its row on the Nodes tab turns them back on")
    return ""


def session_net_on(node_id):
    """Whether that is set on a node."""
    return bool(((node(node_id) or {}).get("config") or {}).get("session_net"))


def session_net_nudge():
    """Every node that keeps sessions to their own network says hello again,
    so what the controller says each project owns there reaches it within a
    poll: after a container changes hands, or an instance comes or goes."""
    for n in node_list():
        if n.get("kind") == "agent" and ((n.get("config") or {}).get("session_net")):
            ask_hello(n["id"])


def node_test_workers(principal, node_id, n):
    """How many workers a test run on this node may use (R81): 0 means the
    node's own core count. Handed to every test job there as
    BB_TEST_WORKERS, for the project's test command and BuilderBot's own
    harness to read. An administrator's, like the rest of the config plane;
    the node hears it by a fresh hello."""
    node_ = node(node_id)
    if not node_:
        return {"error": "no such node"}
    if node_["kind"] != "agent":
        return {"error": "only an agent node runs tests"}
    try:
        want = int(n)
    except (TypeError, ValueError):
        return {"error": "test workers is a whole number from 0 (the node's cores) to 256"}
    if not 0 <= want <= 256:
        return {"error": "test workers is a whole number from 0 (the node's cores) to 256"}
    conf = dict(node_.get("config") or {})
    if want:
        conf["test_workers"] = want
    else:
        conf.pop("test_workers", None)
    _exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(conf), node_id))
    _touch(node_id, principal, "node-test-workers", {"workers": want})
    ask_hello(node_id)
    return {"ok": True, "workers": want}


def test_workers(node_id):
    """The setting on a node, 0 when the node's cores are the answer."""
    v = ((node(node_id) or {}).get("config") or {}).get("test_workers")
    return v if isinstance(v, int) and v > 0 else 0


def turn_limit(node_id):
    """The limit set on a node, 0 when none is."""
    n = node(node_id)
    return turns.limit_of(((n or {}).get("config") or {}).get("turns")) or 0


def node_log_read(principal, asking_id, target_id, stream="agent", lines=200,
                  debug_on=False, grants=(), project=""):
    """A machine log off `target_id`, for a session running on `asking_id`.

    The gate, in order, each refusal saying what would change it: the
    controller's debug switch, then the project's grant for that node
    (`grants`, its settings' Debug, per project since 6 Oct). Past
    both it is root_wait: the same job, the same log in the Jobs tab, the
    same refusal on a machine that did not enroll as a sandbox. What stands
    in for the approval is the grant, and the job's log says so.
    """
    if not debug_on:
        return {"error": "debug mode is off, so a machine's logs are not offered "
                         "to any session. Controller settings turns it on, and "
                         "each project is then granted the nodes it may read"}
    if not asking_id:
        return {"error": "this session is not on a node, and the grant is a "
                         "node's; a controller session reads its own log with "
                         "`bb logs`"}
    tgt = node(target_id)
    if not tgt:
        return {"error": "no such node"}
    if target_id not in (grants or ()):
        return {"error": f"{project or 'this project'} has not been granted {tgt['name']}'s "
                         "machine logs: Debug in its settings grants them"}
    spec = LOG_STREAMS.get(stream)
    if not spec:
        return {"error": "no such log: " + ", ".join(sorted(LOG_STREAMS))}
    try:
        n_lines = max(1, min(LOG_LINES_MAX, int(lines)))
    except (TypeError, ValueError):
        n_lines = 200
    fills = {"lines": str(n_lines)}
    # The unit form when the node reported one, and then the data store is not
    # needed at all: a node whose runner is a service may keep no runner.log.
    unit = (runners_reported(tgt) or [{}])[0].get("unit") or ""
    if spec.get("unit_argv") and unit:
        spec = dict(spec, argv=spec["unit_argv"], store=None)
        fills["unit"] = str(unit)
    if spec.get("store"):
        path = ((tgt.get("reported") or {}).get("stores") or {}).get(
            spec["store"], {}).get("path")
        if not path:
            return {"error": f"{tgt['name']} reports no {spec['store']} store, "
                             f"which is where that log is kept"}
        fills["data"] = str(path).rstrip("/")
    argv = [x.format(**fills) for x in spec["argv"]]
    why = (f"{project or asking_id} reads {tgt['name']}'s "
           f"{stream} log, granted in its settings' Debug, not asked for here")
    return root_wait(principal, target_id, argv, why=why, timeout=120)


DEFAULT_RUNNER_LABELS = ("builderbot", "self-hosted", "linux")


def runner_labels_for(n, labels=None):
    """The labels a node's runner carries: the defaults, its architecture,
    and its own name, the per-node label that lets a workflow's runs-on
    pick this machine. Extra ones from the tab are kept, cleaned."""
    want = [re.sub(r"[^A-Za-z0-9._-]", "", str(x))[:40] for x in (labels or [])]
    out = list(DEFAULT_RUNNER_LABELS)
    arch = (n.get("arch") or "").replace("x86_64", "x64").replace("aarch64", "arm64")
    if arch:
        out.append(arch)
    out.append(re.sub(r"[^A-Za-z0-9._-]", "-", n["name"])[:40])
    for x in want:
        if x and x not in out:
            out.append(x)
    return out[:16]


def node_runner_url(principal, node_id, slot, url, forge, labels=None):
    """The address and forge a runner registers with, onto the node's record
    under its slot, beside the ask, and its labels when they are given.
    Written when the token is stored (server), so the record says what the
    root-only store holds a token FOR; the token itself is never here."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    services = dict(n.get("services") or {})
    runners = dict(runners_of(n))
    ar = dict(runners.get(slot) or {})
    ar.update({"url": str(url or "")[:200], "forge": str(forge or "")[:16]})
    if isinstance(labels, list):
        ar["labels"] = runner_labels_for(n, labels)
    runners[slot] = ar
    services["runners"] = runners
    _exec("UPDATE nodes SET services = ? WHERE id = ?", (json.dumps(services), node_id))
    _touch(node_id, principal, "node-runner-url", {"slot": slot, "url": ar["url"], "forge": ar["forge"]})
    return {"ok": True}


def node_runner_forget(principal, node_id, slot):
    """A runner's entry off the node's record, with its token gone from
    the store (server): nothing left to install from."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    services = dict(n.get("services") or {})
    runners = dict(runners_of(n))
    runners.pop(slot, None)
    services["runners"] = runners
    _exec("UPDATE nodes SET services = ? WHERE id = ?", (json.dumps(services), node_id))
    _touch(node_id, principal, "node-runner-forget", {"slot": slot})
    return {"ok": True}


def node_runner(principal, node_id, slot, want, labels=None, token=False):
    """Install or remove one of a node's runners, as a system job (phase
    7). The desired state per runner (wanted or not, with which labels)
    lives in the node's services column under its slot; the census reports
    what is there. `token` is the server's word that a token is stored for
    that runner, which an install cannot do without; the URL and forge are
    the record's, written with it."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "the runner is installed by the agent; an ssh node has none"}
    # No sandbox stamp needed (roadmap #23): a runner is a tarball and a
    # token, not a change to the machine, so a container node or a guest
    # gets one too. Storage and network keep the stamp: node_apply.
    if n["state"] != "online":
        return {"error": f"the node is {n['state']}; system jobs go to an online node"}
    if system_job_for(node_id):
        return {"error": "a system job is already in flight on this node; one at a time"}
    ar = dict(runners_of(n).get(slot) or {})
    if not ar:
        return {"error": "no such runner on this node: add one on the CI runner tab first"}
    url = ar.get("url") or ""
    forge = ar.get("forge") or "github"
    if want and not token:
        return {"error": "no token stored for this runner: add it on the CI runner tab "
                         "first, with the address it registers with"}
    if want and forge not in ("github", "gitea"):
        return {"error": "runners register with GitHub, Gitea or Forgejo: pick one of those "
                         "beside the address"}
    # http as well as https for a Gitea on the LAN (the token store and
    # the helper accept it too); GitHub is https://github.com/ whatever.
    if want and (not url.startswith(("https://", "http://"))
                 or (forge == "github" and not url.startswith("https://github.com/"))):
        return {"error": "the address is the https repository or organization the runner "
                         "registers with (http is accepted for a forge on your own network)"}
    # The runner's own labels unless new ones are typed with this press.
    labs = runner_labels_for(n, labels if isinstance(labels, list) else ar.get("labels")) if want else []
    services = dict(n.get("services") or {})
    runners = dict(runners_of(n))
    runners[slot] = {**ar, "want": bool(want), "labels": labs}
    services["runners"] = runners
    _exec("UPDATE nodes SET services = ? WHERE id = ?", (json.dumps(services), node_id))
    _touch(node_id, principal, "node-runner", {"slot": slot, "want": bool(want), "labels": labs})
    cfg = {"want": bool(want), "labels": labs, "url": str(url or ""), "name": n["name"],
           "forge": forge, "slot": slot}
    return job_add(principal, {"node": node_id}, "system",
                   {"apply": "runner", "config": cfg, "timeout": 1800})


def tunnel_addr(n):
    """A node's address in the tunnel it reaches the controller through,
    '' for one on the LAN: what it reports, else what its enroll script was
    made with (R161)."""
    t = ((n.get("reported") or {}).get("tunnel") or {}).get("addr") \
        or ((n.get("config") or {}).get("tunnel") or {}).get("addr") or ""
    return t if re.fullmatch(r"[0-9.]{7,15}", t) else ""


_tunnels = {"at": 0.0, "addrs": frozenset()}


def tunnel_addrs():
    """Every node's tunnel address, read again at most every five seconds:
    the server asks on every request."""
    now = time.monotonic()
    if now - _tunnels["at"] > 5:
        tunnel_hosts()
    return _tunnels["addrs"]


def tunnel_hosts():
    """Every hostname a node reaches the controller at through a tunnel
    (R170), read again at most every five seconds like tunnel_addrs."""
    now = time.monotonic()
    if now - _tunnels["at"] > 5 or "hosts" not in _tunnels:
        rows = [n for n in node_list() if n.get("state") != "retired"]
        _tunnels.update(at=now, addrs=frozenset(a for a in (tunnel_addr(n) for n in rows) if a),
                        hosts=frozenset(h for h in (tunnel_host(n) for n in rows) if h))
    return _tunnels["hosts"]


def tunnel_host(n):
    """The hostname a node dials the controller at through a tunnel from
    home, '' for any other node: its enroll script's answer."""
    t = (n.get("config") or {}).get("tunnel") or {}
    h = str(t.get("host") or "").lower() if t.get("kind") == "public" else ""
    return h if re.fullmatch(r"[a-z0-9.-]{1,253}", h) else ""


def tunnel_refuses(addr, path, host="", edge=False):
    """Why a request from `addr` for `path` is refused, or "": a node that
    reaches the controller through a tunnel is answered on the agent's own
    API and nothing else (R161), so the tunnel open on a machine somebody
    else may own reaches no login, no page and no other account's API.
    `host` is the request's Host header and `edge` whether it carries a
    tunnel edge's own headers (R170): through a tunnel every request comes
    from the tunnel's local end, so the hostname a node was enrolled at is
    the mark instead. A header can only narrow what its writer gets,
    never widen it, which is why one is read here at all."""
    if path.startswith("/api/v1/agent/"):
        return ""
    if addr in tunnel_addrs():
        return "this address is a node's tunnel, which reaches the agent's API and nothing else"
    h = str(host or "").lower().rsplit(":", 1)[0].strip("[]") if host else ""
    if (h and h in tunnel_hosts()) or edge:
        return "this hostname is a node's tunnel, which reaches the agent's API and nothing else"
    return ""


def route_host(node_id):
    """The host a published port on this node is reached at from the LAN:
    its address in the tunnel it dials through (R161), else the address the
    node last dialed in from. '' for local and the unknown."""
    n = node(node_id)
    if not n or n["kind"] == "local":
        return ""
    t = tunnel_addr(n)
    if t:
        return t
    a = (n.get("agent") or {}).get("addr") or ""
    a = re.sub(r"^[a-z][a-z0-9+.-]*://", "", a)
    a = a.split("@")[-1].split("/")[0].split(":")[0]
    return a


def node_funnel(principal, node_id, port, on=True):
    """Tailscale Funnel on a node (docs/nodes.md §7, mode `funnel`): a
    public HTTPS URL for one published port, with no DNS, certificate or
    firewall change. It is a system job the agent applies with tailscale's
    own CLI. One funnel per node, on 443: the node's MagicDNS name is the
    URL, and a second instance asking replaces the first, said plainly."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "a funnel needs the agent; this node runs none"}
    # Like the runner, no sandbox stamp: tailscale's own CLI does the work.
    ts = ((n.get("reported") or {}).get("services") or {}).get("tailscale") or {}
    if not ts.get("installed"):
        return {"error": f"{n['name']} has no tailscale; install and log it in on the node first"}
    if n["state"] != "online":
        return {"error": f"the node is {n['state']}; system jobs go to an online node"}
    if system_job_for(node_id):
        return {"error": "a system job is already in flight on this node; one at a time"}
    try:
        port = int(port)
    except (TypeError, ValueError):
        return {"error": "a funnel forwards to a port number"}
    if not 1 <= port <= 65535:
        return {"error": "a funnel forwards to a port number"}
    r = job_add(principal, {"node": node_id}, "system",
                {"apply": "funnel", "config": {"port": port, "on": bool(on)}, "timeout": 300})
    if r.get("ok"):
        audit(principal, "node-funnel", node_id, {"port": port, "on": bool(on)})
    return r


def agent_stale(n):
    """"" if this node runs the agent this controller ships, else why that
    matters right now.

    A controller is always newer than or equal to its nodes (it is where
    the agent file comes from), so a mismatch means the node may not
    understand a job this version would send it. Job types and spec fields
    have been added on nearly every phase (system, toolchain, cache-clear,
    compose plans, bb verbs, store listings), and an older agent meets an
    unknown one with a shrug rather than an error. So the rule is: an agent
    that is behind takes nothing but its own update.
    """
    if not n or n["kind"] != "agent":
        return ""
    ours = agent_file()
    theirs = (n.get("agent") or {}).get("digest") or ""
    if not ours["digest"] or not theirs or theirs == ours["digest"]:
        return ""
    mine = (n.get("agent") or {}).get("version") or "?"
    if agent_gap(n):
        return (f"{n['name']} runs agent {mine} and this controller ships {ours['version']}: "
                f"a different compatibility window ({agent_window(mine)} against "
                f"{agent_window(ours['version'])}), so nothing sent to it is promised to work. "
                "Update it from the Nodes tab before relying on this node.")
    if mine == ours["version"]:
        # The same number and a different file: the agent moved without its
        # version constant. Said as such, since "runs 0.6.92 and ships 0.6.92"
        # read as nonsense on a walk (docs/journeys.md, 23 Sep).
        return (f"{n['name']} runs agent {mine} ({theirs.split(':')[-1][:8]}) and this controller "
                f"ships the same number as a newer file ({ours['digest'].split(':')[-1][:8]}): "
                "press Update agent on its row first. A job this version sends could name "
                "something that agent does not know")
    return (f"{n['name']} runs agent {mine} and this controller ships {ours['version']}: "
            "press Update agent on its row first. A job this version sends could name "
            "something that agent does not know")


def agent_gap(n):
    """True when this node's agent is from ANOTHER compatibility window than
    the one this controller ships: 0.3 against 0.4. Inside a window any
    agent works with any controller and being behind is routine; across one
    that promise was never made. Empty windows (an agent from before the
    window existed) are never read as a gap."""
    ours = agent_window(agent_file()["version"])
    theirs = agent_window((n.get("agent") or {}).get("version"))
    return bool(ours and theirs and ours != theirs)


def attention(project_nodes):
    """The pinned alerts about nodes, for the bell: computed from the record
    on every poll, so one leaves the moment it stops being true. An agent
    node whose agent is behind (an update is available) or from another
    window (nothing routed to it is promised to work, and the projects on
    it are named). `project_nodes` is {project: node id}."""
    ours = agent_file()
    out = []
    for n in node_list():
        # Only a node that is dialing in: one that is away takes no job for
        # that reason first, and Update agent could not reach it anyway. An
        # alert nobody can act on would sit in the bell until the node came
        # back, which is the opposite of an alert that leaves when it stops
        # being true.
        if n["kind"] != "agent" or not n.get("live") or not agent_stale(n):
            continue
        out.append({"kind": "agent", "node": n["name"], "id": n["id"],
                    "from": (n.get("agent") or {}).get("version") or "?",
                    "to": ours["version"], "window": agent_gap(n),
                    "projects": sorted(p for p, nid in project_nodes.items() if nid == n["id"])})
    return out


def node_update_agent(principal, node_id):
    """Queue the self-update for a node's agent: the file this controller
    serves, named by digest so the node can never be handed anything else
    (door 4). The agent replaces itself in place and re-execs, so nothing on
    the node restarts and no running job is interrupted; it refuses while
    other jobs run. Nothing drives this on its own: the row says when an
    update is due, and the operator presses."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "only an agent node has an agent to update"}
    ours = agent_file()
    if not ours["digest"]:
        return {"error": "this controller ships no agent"}
    if (n.get("agent") or {}).get("digest") == ours["digest"]:
        return {"ok": True, "current": True, "version": ours["version"]}
    r = job_add(principal, {"node": node_id}, "self-update",
                {"digest": ours["digest"], "version": ours["version"], "timeout": 300})
    if r.get("ok"):
        audit(principal, "node-update-agent", node_id, {"to": ours["digest"]})
    return r


def agent_shipped():
    """What this controller ships, for the row's comparison: digest and
    version only; the body is the download verb's."""
    f = agent_file()
    return {"digest": f["digest"], "version": f["version"]}


# What a build command obviously needs, by the tool it invokes. Only the
# unambiguous ones: a `make` or a `./build.sh` says nothing about its
# toolchain, and guessing at those would refuse builds that would have
# worked. Keys are what the census reports (agent `_toolchains`).
NEEDS = {
    "gradlew": "java", "gradle": "java", "mvn": "java", "javac": "java",
    "flutter": "flutter", "dotnet": "dotnet", "cargo": "rust", "rustc": "rust",
    "go": "go", "swift": "swift", "swiftc": "swift",
    "npm": "node", "npx": "node", "yarn": "node", "pnpm": "node", "node": "node",
    "sdkmanager": "android-sdk", "adb": "android-sdk", "apksigner": "android-sdk",
    "bundletool": "android-sdk", "emulator": "emulator",
}


def toolchain_for(argv):
    """The toolchain a command visibly needs, or "". Reads every word, so
    `sh -c './gradlew assembleDebug'` and a bare `gradle` both answer."""
    for word in argv or []:
        w = str(word).strip().strip("'\"")
        for part in re.split(r"[\s;&|]+", w):
            base = part.rsplit("/", 1)[-1]
            if base in NEEDS:
                return NEEDS[base]
    return ""


def toolchain_gap(node_id, argv):
    """"" if this node can plausibly run this command, else the toolchain
    it is missing. Only ever answers about a tool the command NAMES and the
    node's census does not report: an unknown build script is not refused,
    and a node that has never dialed in is not judged."""
    want = toolchain_for(argv)
    if not want:
        return ""
    n = node(node_id)
    if not n or n["kind"] != "agent":
        return ""
    tc = (n.get("reported") or {}).get("toolchains")
    if not isinstance(tc, dict) or not tc:
        return ""                       # nothing reported yet: not a verdict
    if tc.get(want):
        return ""
    # Refusing on evidence that can be ten minutes old, so the node is asked
    # for a fresh census and the caller is told how old this one was. The
    # alternative is what the operator met: a command refused, the identical
    # retry allowed, and nothing on screen to explain the difference.
    ask_hello(node_id)
    return want


def census_age(node_id):
    """How many seconds old this node's census is, or None when it has never
    sent one. What a refusal quotes, so "it worked a minute ago" has an
    answer other than a shrug."""
    n = node(node_id)
    at = ((n or {}).get("reported") or {}).get("at")
    return int(time.time()) - int(at) if at else None


def node_runner_label(node_id):
    """The label that pins a workflow's runs-on to THIS node's runner: its
    own name, cleaned the way runner_labels_for cleans it.

    "" when the node has no runner installed or asked for: advising a
    runs-on that nothing answers is the "Waiting for a runner" strand this
    exists to prevent, and an empty answer is how the caller knows to say
    nothing rather than to say something wrong.
    """
    n = node(node_id)
    if not n:
        return ""
    if not (any(r.get("installed") for r in runners_reported(n))
            or any(r.get("want") for r in runners_of(n).values())):
        return ""
    return re.sub(r"[^A-Za-z0-9._-]", "-", n["name"])[:40]


def runner_labels_known():
    """Every label a runner in the registry carries, reported or wanted, for
    the lint that checks a workflow's runs-on against what exists."""
    out = set()
    for n in node_list():
        for r in runners_reported(n):
            out.update(r.get("labels") or [])
        for r in runners_of(n).values():
            if r.get("want"):
                out.update(r.get("labels") or [])
    return sorted(out)


def node_uninstall(principal, node_id):
    """Take BuilderBot off a node from its row: a system job the agent
    answers by deregistering its runners and starting bb-sandbox uninstall
    detached, after which nothing of BuilderBot's is left on the machine
    but docker, the packages and the shares' contents. The node is retired
    when the job succeeds (job_result), so the row leaves every list the
    way Remove's does."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n.get("kind") != "agent":
        return {"error": "only an agent node can be uninstalled from here"}
    if not (n.get("reported") or {}).get("sandbox"):
        return {"error": "only a node provisioned as a BuilderBot sandbox can be uninstalled "
                         "from here: on the machine, sudo bb-sandbox uninstall"}
    if system_job_for(node_id):
        return {"error": "a system job is already in flight on this node; one at a time"}
    r = job_add(principal, {"node": node_id}, "system",
                {"apply": "uninstall", "config": {}, "timeout": 900})
    if r.get("ok"):
        audit(principal, "node-uninstall", node_id, {"job": r["job"]})
    return r


def node_door(principal, node_id, on):
    """The door in for SSH on or off (R174): a system job the agent answers
    by starting or stopping the door's client (cloudflared's service, or
    the node on its tailnet). Only a node provisioned with one."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    kind = ((n.get("reported") or {}).get("door") or (n.get("config") or {}).get("door") or {}).get("kind")
    if kind not in ("cloudflared", "tailscale"):
        return {"error": f"{n['name']} was provisioned with no door in: Enroll node's SSH door sets one up"}
    why = node_locked(n)
    if why:
        return {"error": why}
    if not n.get("live"):
        return {"error": f"{n['name']}'s agent is not dialing in, so nothing from here reaches the machine"}
    if system_job_for(node_id):
        return {"error": "a system job is already in flight on this node; one at a time"}
    r = job_add(principal, {"node": node_id}, "system",
                {"apply": "door", "config": {"on": on is not False}, "timeout": 300})
    if r.get("ok"):
        audit(principal, "node-door", node_id, {"job": r["job"], "on": on is not False})
    return r


def node_gpu_display(principal, node_id):
    """Set the GPU display up on a node from its row (R20): a system job
    the agent answers with bb-sandbox gpu, which starts a headless X server
    on the card, on the driver the Toolchains tab installed, and says
    whether a reboot has to follow. The machine's own answer decides: a node with no card gets that
    said, not refused here."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n.get("kind") != "agent":
        return {"error": "only an agent node has a GPU display to set up"}
    if not (n.get("reported") or {}).get("sandbox"):
        return {"error": "only a node provisioned as a BuilderBot sandbox is set up from here: "
                         "on the machine, sudo bb-sandbox gpu"}
    # The display runs on the driver and does not install it (R102): the
    # Toolchains tab's driver row is the one place it is installed.
    gd = (n.get("reported") or {}).get("gpu_driver")
    if isinstance(gd, dict) and not gd.get("installed"):
        return {"error": f"the NVIDIA driver is not installed on {n['name']}: install it on "
                         "that node's Toolchains tab first; the display runs on it"}
    why = node_locked(n)
    if why:
        return {"error": why}
    if not n.get("live"):
        return {"error": f"{n['name']}'s agent is not dialing in, so nothing from here reaches the machine"}
    if system_job_for(node_id):
        return {"error": "a system job is already in flight on this node; one at a time"}
    r = job_add(principal, {"node": node_id}, "system",
                {"apply": "gpu", "config": {}, "timeout": 1800})
    if r.get("ok"):
        audit(principal, "node-gpu-display", node_id, {"job": r["job"]})
    return r


def node_gpu_display_off(principal, node_id):
    """Stop rendering the emulator on the card (R102): a system job the
    agent answers with bb-sandbox gpu-off, which stops the headless X
    server and leaves the driver alone; an emulator there renders in
    software from its next start."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n.get("kind") != "agent" or not (n.get("reported") or {}).get("sandbox"):
        return {"error": "only a node provisioned as a BuilderBot sandbox is changed from here: "
                         "on the machine, sudo bb-sandbox gpu-off"}
    why = node_locked(n)
    if why:
        return {"error": why}
    if not n.get("live"):
        return {"error": f"{n['name']}'s agent is not dialing in, so nothing from here reaches the machine"}
    if system_job_for(node_id):
        return {"error": "a system job is already in flight on this node; one at a time"}
    r = job_add(principal, {"node": node_id}, "system",
                {"apply": "gpu-off", "config": {}, "timeout": 300})
    if r.get("ok"):
        audit(principal, "node-gpu-display-off", node_id, {"job": r["job"]})
    return r


def node_gpu_compute(principal, node_id, on):
    """Whether sessions and jobs on this node may compute on its NVIDIA
    card (R102): on unless switched off. Off, a session started there from
    now on has CUDA told there is no device and the device CUDA needs
    covered in its view; the emulator's rendering is its own switch."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "only an agent node runs sessions"}
    conf = dict(n.get("config") or {})
    if on:
        conf.pop("no_gpu_compute", None)
    else:
        conf["no_gpu_compute"] = True
    _exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(conf), node_id))
    _touch(node_id, principal, "node-gpu-compute", {"on": bool(on)})
    return {"ok": True, "on": bool(on)}


# The jobs a Reboot or a Shut down waits for, and how the refusal names each.
POWER_WAITS = {"toolchain": "a toolchain install or removal", "image": "a system image install",
               "claude-update": "a Claude Code update"}


def node_power(principal, node_id, what):
    """Reboot or shut a node down from its row: a system job the agent
    answers by scheduling the machine's own reboot or power-off a few
    seconds out, so the job's result reaches here before the agent goes
    with it. Refused where nothing from here would reach the machine (its
    agent away), where the machine is this controller's own (rebooted from
    its host, not from the dashboard it runs), and on a locked node."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if what not in ("reboot", "poweroff"):
        return {"error": "power is reboot or poweroff"}
    verb = "reboot" if what == "reboot" else "shut down"
    if n.get("kind") != "agent":
        return {"error": f"{n['name']} is the controller's own machine: {verb} it from its host, "
                         "not from the dashboard running on it"}
    why = node_locked(n)
    if why:
        return {"error": why}
    if not n.get("live"):
        return {"error": f"{n['name']}'s agent is not dialing in, so nothing from here reaches the "
                         f"machine: {verb} it from its console or its hypervisor"}
    if system_job_for(node_id):
        return {"error": "a system job is already in flight on this node; one at a time"}
    # ...nor under an install: a restart in the middle of apt, or of a
    # toolchain being unpacked, leaves it half on the machine (the operator,
    # 30 Sep). The Toolchains tab's Abort stops one first.
    busy = [j["type"] for j in jobs_for(node_id=node_id, active=True, n=20)
            if j.get("type") in POWER_WAITS]
    if busy:
        return {"error": f"{POWER_WAITS[busy[0]]} is running on {n['name']}: {verb} it when that has "
                         "finished, or stop it first"}
    r = job_add(principal, {"node": node_id}, "system",
                {"apply": what, "config": {}, "timeout": 60})
    if r.get("ok"):
        audit(principal, "node-" + what, node_id, {"job": r["job"]})
    return r


def system_job_for(node_id):
    """The system job in flight for a node, if any: one at a time, because
    two applies racing on one fstab is not a state anybody wants."""
    for j in jobs_for(node_id=node_id, type="system", active=True, n=5):
        return j
    return None


def apply_cfg(desired, what):
    """The half of a desired config an apply of `what` carries. Its own
    function because node_list compares a finished job's spec against it to
    decide whether that job is still about the record as it stands, and a
    second copy of this shape would make a stale failure look current, or
    the other way about, whenever either moved."""
    desired = desired or {}
    if what == "storage":
        return {"mounts": desired.get("mounts") or [], "stores": desired.get("stores") or {}}
    if what == "network":
        return {"network": desired.get("network") or {}}
    return None


def node_apply(principal, node_id, what):
    """Queue the system job that makes the node match its desired config:
    storage (mounts and stores) or network, which is its own job because it
    is the one that can cut the cord (the agent reverts it if it cannot dial
    back in). Offered only to a live agent node that enrolled as a sandbox;
    the agent refuses without the stamp as well, whatever this says."""
    if what not in ("storage", "network"):
        return {"error": "apply storage or network"}
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "only an agent node takes system jobs"}
    if not (n.get("reported") or {}).get("sandbox"):
        return {"error": "this node was not provisioned as a BuilderBot sandbox "
                         "(no bb-sandbox on it), so system jobs are not offered to it"}
    if n["state"] != "online":
        return {"error": f"the node is {n['state']}; system jobs go to an online node"}
    if node_locked(n):
        return {"error": node_locked(n)}
    desired = (n.get("config") or {}).get("desired") or {}
    if not desired:
        return {"error": "nothing to apply; save a configuration first"}
    if system_job_for(node_id):
        return {"error": "a system job is already in flight on this node; one at a time"}
    cfg = apply_cfg(desired, what)
    # A storage apply that repoints a store copies what is in it first, and a
    # toolchain store is tens of gigabytes: fifteen minutes is the right ceiling
    # for mounting a share and the wrong one for moving one. `cache` is not
    # copied (the agent says why), so it does not buy the longer clock.
    timeout = 900
    if what == "storage":
        rep = (n.get("reported") or {}).get("stores") or {}
        if any(p and role != "cache" and (rep.get(role) or {}).get("path")
               and str((rep.get(role) or {}).get("path")).rstrip("/") != str(p).rstrip("/")
               for role, p in (desired.get("stores") or {}).items()):
            timeout = 6 * 3600 + 900
    r = job_add(principal, {"node": node_id}, "system",
                {"apply": what, "config": cfg, "timeout": timeout})
    if r.get("ok"):
        audit(principal, "node-apply", node_id, {"what": what, "job": r["job"]})
    return r


def node_to_sync(principal, node_id):
    """Back onto its synced copy from off (R164): the node holds its bound
    projects again, each copied down before a session there starts. The
    one way a node holds them; no node mounts the projects share (R163)."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "only an agent node holds a synced copy"}
    conf = dict(n.get("config") or {})
    if (conf.get("workspace") or "sync") == "sync":
        return {"error": f"{n['name']} already holds its projects as a synced copy"}
    if conf.get("clean") and not sync_cleaned(n):
        return {"error": f"{n['name']} is still removing its last copy; move it once that is done"}
    if node_locked(n):
        return {"error": node_locked(n)}
    conf["workspace"] = "sync"
    conf.pop("clean", None)
    conf.pop("leaving", None)
    _set_conf(node_id, conf)
    _touch(node_id, principal, "node-to-sync", {})
    return {"ok": True}


# ---- leaving a synced copy (R164) ------------------------------------------------------
#
# The way back from node_to_sync, in three presses with the node's word
# between them: Stop syncing ends the sessions and holds new ones while the
# agent sends up what is waiting (files, and conversations: claudesync.py);
# Clean up /workspace, offered once the node says nothing is left, has the
# agent remove its copies; and from there the node stays off, or moves to
# a synced copy again. There is no way back to the projects share: no node
# mounts the controller's disk (the operator, 10 Oct). A copy is never
# removed while anything in it has not reached the controller: it may be
# the only place a change lives.

def _leave_check(node_id):
    n = node(node_id)
    if not n:
        return None, {"error": "no such node"}
    if n["kind"] != "agent":
        return None, {"error": "only an agent node holds a synced copy"}
    if node_locked(n):
        return None, {"error": node_locked(n)}
    return n, None


def _set_conf(node_id, conf):
    _exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(conf), node_id))
    _synced["at"] = 0.0
    # A hint naming no project: the agent asks again now how it holds them.
    sync_hint(node_id, "", 0)


def sync_drained(n):
    """Whether a leaving node has said nothing is left to send, after a
    whole walk of every project and a fresh look at its conversations."""
    d = (n.get("reported") or {}).get("sync_drain") or {}
    return bool(d.get("walked")) and not d.get("files") and not d.get("claude")


def sync_cleaned(n):
    """The node's answer to the clean-up asked of it, or None while it is
    still to come."""
    conf = n.get("config") or {}
    c = (n.get("reported") or {}).get("sync_clean") or {}
    return c if conf.get("clean") and c.get("token") == conf.get("clean") else None


def node_sync_stop(principal, node_id):
    """Stop syncing: the node's sessions ended and new ones held while what
    is waiting there goes up."""
    n, no = _leave_check(node_id)
    if no:
        return no
    conf = dict(n.get("config") or {})
    if (conf.get("workspace") or "sync") != "sync":
        return {"error": f"{n['name']} holds no projects to stop syncing"}
    if conf.get("leaving"):
        return {"error": f"{n['name']} is already leaving its synced copy"}
    ended = []
    for s in (node_sessions().get(node_id) or ("", []))[1]:
        name = str((s or {}).get("name") or "")
        if name and not session_kill(node_id, name).get("error"):
            ended.append(name)
    conf["leaving"] = True
    _set_conf(node_id, conf)
    _touch(node_id, principal, "node-sync-stop", {"ended": len(ended)})
    return {"ok": True, "ended": ended}


def node_sync_resume(principal, node_id):
    """Keep syncing after all: a node still leaving holds sessions again."""
    n, no = _leave_check(node_id)
    if no:
        return no
    conf = dict(n.get("config") or {})
    if (conf.get("workspace") or "sync") != "sync" or not conf.get("leaving"):
        return {"error": f"{n['name']} is not leaving its synced copy"}
    conf.pop("leaving", None)
    _set_conf(node_id, conf)
    _touch(node_id, principal, "node-sync-resume", {})
    return {"ok": True}


def node_sync_clean(principal, node_id):
    """Clean up /workspace: the node off its synced copy, and asked to remove
    the copies, which it does once and answers by the token."""
    n, no = _leave_check(node_id)
    if no:
        return no
    conf = dict(n.get("config") or {})
    syncing = (conf.get("workspace") or "sync") == "sync"
    if syncing and not conf.get("leaving"):
        return {"error": f"press Stop syncing on {n['name']} first, so nothing is lost"}
    if syncing:
        if n["state"] != "online" or n.get("live") is False:
            return {"error": f"{n['name']} is not answering, so it cannot say whether everything there has gone up"}
        if not sync_drained(n):
            d = (n.get("reported") or {}).get("sync_drain") or {}
            left = [f"{d['files']} file change{'s' if d['files'] != 1 else ''}" if d.get("files") else "",
                    f"{d['claude']} conversation file{'s' if d['claude'] != 1 else ''}" if d.get("claude") else ""]
            left = [x for x in left if x]
            return {"error": f"{n['name']} still has " + " and ".join(left) + " to send up; it is removed once they are there"
                    if left else f"{n['name']} has not finished looking at every file yet; try again in a moment"}
    conf["workspace"] = "off"
    conf.pop("leaving", None)
    conf["clean"] = secrets.token_hex(8)
    _set_conf(node_id, conf)
    _touch(node_id, principal, "node-sync-clean", {"token": conf["clean"]})
    return {"ok": True}



# Set by server.py at boot, because toolchains.py imports this one and the
# catalog is its business, not the registry's. Absent (an older controller,
# or a store that did not open) simply means the node keeps its built-in
# answer.
layout_of = lambda: []
bundle_digest = lambda: ""
idle_minutes = lambda: 0            # noqa: E731  (idle.minutes, injected by server.py)
# {"on", "own"} for a node's agent (R79): whether its sessions are kept to
# their own project's network, and what each project owns there
# (devapp.session_net_own, joined by server.py).
session_net_for = lambda nid: None  # noqa: E731
# A project's file access (ftp.for_node, R151): the servers this node runs.
ftp_for = lambda nid: []  # noqa: E731
# server.session_tokens_for: fresh credentials for the Claude sessions alive
# on one node, so a session idle past its token's life is not locked out of
# its own controller (R27). Injected, because minting is users.py's and the
# project list is the server's, and neither is the node store's business.
session_tokens_for = lambda nid, sessions: []   # noqa: E731


def reported_set(nid, key, sub, value):
    """One field of a node's census, set by this side between hellos: what a
    finished job measured (claudecode.update_done, B249). The next hello
    replaces the whole record, which is right: the node's word is the
    census, and this is only how the minutes before it are not wrong."""
    n = node(nid)
    if not n:
        return
    rep = n.get("reported") or {}
    inner = rep.get(key) if isinstance(rep.get(key), dict) else {}
    inner[sub] = value
    rep[key] = inner
    _exec("UPDATE nodes SET reported = ? WHERE id = ?", (json.dumps(rep), nid))
    _bump()


# Called with the node id when an agent dials in after being unheard: the
# doctor's cached lines about nodes are wrong the moment this happens, and
# waited out a half-hour cache after a reboot (the operator, 25 Sep).
came_back = None
# Nodes whose toolchains are checked on the next turn of the weekly loop
# rather than at the week (toolchains.node_checks_due): one that came back
# from offline, or whose agent is a new file, which means it started again
# (the operator, 6 Oct: check for updates at a node's start up).
checks_wanted = set()


def keep_clean(keep):
    """The agent's report on the session tokens it keeps (B419), checked:
    {said: [{at, key, msg}] (the last eight), ok: when one was last kept}."""
    if not isinstance(keep, dict):
        return None
    said = []
    for x in (keep.get("said") if isinstance(keep.get("said"), list) else [])[-8:]:
        if isinstance(x, dict):
            try:
                said.append({"at": int(x.get("at") or 0), "key": str(x.get("key") or "")[:80],
                             "msg": str(x.get("msg") or "")[:300]})
            except (TypeError, ValueError):
                continue
    try:
        ok = int(keep.get("ok") or 0)
    except (TypeError, ValueError):
        ok = 0
    return {"said": said, "ok": ok}


def hello(nid, census, addr, version="", digest="", running=None, keep=None):
    """The agent on connect: refresh the census, record the version it is
    running, and answer with what the controller expects of it: the
    transports, the poll window, the node's own capabilities (so it can
    refuse outside them, door 7) and the controller's agent file digest
    (so self-update is a comparison, door 4).

    `running` is the jobs the agent has going right now. An agent that
    restarted has none, and the rows this side still had as running there
    are then failed as lost: a subprocess does not survive its parent, so
    a row saying otherwise would say it forever."""
    n = node(nid)
    if not n:
        return {"error": "no such node"}
    was_live = bool(n.get("live"))
    if not was_live or str((n.get("agent") or {}).get("digest") or "") != str(digest or "")[:80]:
        checks_wanted.add(nid)
    ag = n.get("agent") or {}
    if isinstance(running, list):
        jobs_reconcile(nid, [str(j) for j in running])
        ag["held"] = jobs_held(nid, [str(j) for j in running])
    ag.update({"version": str(version)[:40], "digest": str(digest)[:80],
               "addr": addr, "last_seen": int(time.time()),
               })
    # Why an idle session's token was not refreshed here, said by the agent
    # that tried (B419); an agent from before says nothing and keeps none.
    kc = keep_clean(keep)
    if kc is not None:
        ag["keep"] = kc
    rep = n.get("reported") or {}
    # The tmux sessions ride the HEARTBEAT, not the census, so the live set is
    # what the last one recorded rather than anything hello was handed. Read
    # before _census replaces the record below (R27).
    live_sessions = rep.get("sessions") or []
    sample = rep.get("sample")
    # When this census was taken. The heartbeat is every 25 seconds but the
    # census only rides hello, every ten minutes, so "when did the node last
    # dial in" is not the same question as "how old is this answer", and it
    # is the second one a refusal is reasoning from.
    census_at = int(time.time())
    # What only the heartbeat carries is kept across the census replacing
    # the record: dropped, a synced project read as not copied (the session
    # gate held it) and the node's sessions as none (Move to a synced copy
    # ended nothing) until the next heartbeat, and hellos come every half
    # minute or so on a busy node.
    beat = {k: rep[k] for k in ("sessions", "published", "sync", "sync_drain", "sync_clean") if k in rep}
    rep = _census(census)
    rep["at"] = census_at
    if sample:
        rep["sample"] = sample
    rep.update(beat)
    _exec("UPDATE nodes SET agent = ?, reported = ?, os = ?, arch = ? "
          "WHERE id = ?", (json.dumps(ag), json.dumps(rep), rep["system"],
                           rep["arch"], nid))
    _bump()
    if not was_live and came_back:
        try:
            came_back(nid)
        except Exception as e:                                       # noqa: BLE001
            print(f"[nodes] came_back hook: {type(e).__name__}: {e}", flush=True)
    ours = agent_file()
    return {"ok": True, "transports": ["longpoll"],
            "poll": POLL_S, "node": {"id": nid, "name": n["name"],
                                     "state": n["state"],
                                     "capabilities": n["capabilities"],
                                     "concurrency": n["concurrency"]},
            "agent": {"digest": ours["digest"], "version": ours["version"]},
            # Where every toolchain lands, from the catalog: the node has no
            # catalog of its own, and this is what stops it keeping a second
            # copy of the answer that drifts from ours.
            "layout": layout_of() or None,
            # The bb bundle's digest (roadmap #24): a node keeps an unpacked
            # copy for the sessions it runs, and refreshes it when this moves.
            "bundle": "" if host_only(nid) else bundle_digest() or "",
            # A hosting-only node is told so, and keeps no session half, no
            # synced copy and no bb of its own (host_only).
            "host_only": host_only(nid),
            # The idle rule for Claude sessions (idle.py): the node enforces
            # it itself, so it holds while this controller is down.
            "session_idle_minutes": idle_minutes(),
            # How many workers a test run here may use (R81): 0 for the
            # node's cores. Into every test job's environment there.
            "test_workers": test_workers(nid),
            # A fresh token for each Claude session alive on this node (R27).
            # A session's token slides forward while it is TALKING, because
            # every answer it gets carries a renewal; one that sits idle past
            # twelve hours has nothing to slide it, and a dead token is never
            # renewed, which is what makes the life mean anything for a leaked
            # one. So the machine the session is on refreshes it instead, on
            # the beat it already has. A token lives as long as its tmux
            # session does, and none is ever accepted past its expiry.
            "session_tokens": [] if host_only(nid) else session_tokens_for(nid, live_sessions),
            # Whether each session here is kept to its own project's network,
            # and what each project owns here (R79). The node keeps it, so it
            # holds while this controller is down.
            "session_net": session_net_for(nid),
            # The FTPS servers this node runs for its projects' file access
            # (R151): one per project, rooted at its tree.
            "ftp": [] if host_only(nid) else ftp_for(nid)}


def store_merge(census, free, totals):
    """The heartbeat's store readings onto the census's rows, the free space
    and, when the agent sent it, the size with it. Free alone against the
    census's size read a grown disk as empty for up to ten minutes: more
    free than the old total, so nothing used (B434)."""
    for role, mb in free.items():
        row = census.get(role)
        if row is None:
            continue
        row["free_mb"] = mb
        if totals.get(role):
            row["total_mb"] = totals[role]
    return census


def beat(nid):
    """The node is there, and nothing else: last_seen stamped in place, so a
    node whose loop is busy taking a census on the spot (a hello asked for
    after a job changed the machine, a minute and more on bb-sandbox) is
    not read as not answering (the operator, 7 Oct). One statement, so it
    cannot lose a hello's census written beside it."""
    _exec("UPDATE nodes SET agent = json_set(agent, '$.last_seen', ?) WHERE id = ? AND kind = 'agent'",
          (int(time.time()), nid))


def heartbeat(nid, sample, addr, running=0):
    """One sample per poll: the numbers the operator actually wants to see,
    riding the channel that exists anyway. Written to the row (current
    value) and to the ring (the last minute); last_seen is what liveness
    reads. The address is refreshed too; see _addr."""
    n = node(nid)
    if not n:
        return
    s = sample if isinstance(sample, dict) else {}
    clean = {"at": int(time.time())}
    for k in ("cpu_pct", "load1", "mem_used_mb", "mem_mb"):
        with contextlib.suppress(TypeError, ValueError):
            clean[k] = round(float(s.get(k) or 0), 1)
    # The card's gauges only when the node has one answering: absent is
    # "no GPU", which a zero would not say (0.7.125 on).
    for k in ("gpu_pct", "gpu_mem_used_mb", "gpu_mem_mb"):
        if k in s:
            with contextlib.suppress(TypeError, ValueError):
                clean[k] = round(float(s.get(k) or 0), 1)
    # What runs there by kind, its cores and who computes on its card, for
    # a session judging whether the machine is quiet enough to time
    # anything on (R108). Only the kinds the agent counts, as numbers.
    with contextlib.suppress(TypeError, ValueError):
        if "cores" in s:
            clean["cores"] = max(0, min(4096, int(s.get("cores") or 0)))
        if "gpu_procs" in s:
            clean["gpu_procs"] = max(0, min(9999, int(s.get("gpu_procs") or 0)))
    if isinstance(s.get("kinds"), dict):
        clean["kinds"] = {k: max(0, min(9999, int(v))) for k, v in list(s["kinds"].items())[:16]
                          if k in PROC_KINDS and isinstance(v, (int, float))}
    # ...and the card's memory by what holds it, in MB, the same kinds and
    # "other" (B532): what filled the card is a kind, never a name.
    if isinstance(s.get("gpu_mem_kinds"), dict):
        clean["gpu_mem_kinds"] = {k: max(0, min(10**7, int(v))) for k, v in list(s["gpu_mem_kinds"].items())[:16]
                                  if (k in PROC_KINDS or k == "other") and isinstance(v, (int, float))}
    clean["running"] = int(running or 0)
    stores = s.get("stores") if isinstance(s.get("stores"), dict) else {}
    clean["stores"] = {str(r)[:20]: _mb((v or {}).get("free_mb"))
                       for r, v in list(stores.items())[:8]}
    totals = {str(r)[:20]: _mb((v or {}).get("total_mb"))
              for r, v in list(stores.items())[:8]}
    ag = n.get("agent") or {}
    ag["last_seen"] = clean["at"]
    if addr:
        ag["addr"] = addr
    rep = n.get("reported") or {}
    rep["sample"] = clean
    # What the node publishes, by compose project (R82): the ports another
    # node's session of the same project may reach. A change re-sends every
    # firewall its allow list, so a container coming up on one node is
    # reachable from the other within a poll.
    moved = False
    if isinstance(s.get("published"), dict):
        pub = {}
        for k, v in list(s["published"].items())[:64]:
            ports = sorted({int(p) for p in (v if isinstance(v, list) else []) if str(p).isdigit()
                            and 0 < int(p) < 65536})[:32]
            if ports:
                pub[str(k)[:100]] = ports
        moved = pub != (rep.get("published") or {})
        rep["published"] = pub
    # The node's tmux sessions (roadmap #24), for the Sessions card: name,
    # whether a client is attached, the active pane's directory and title
    # (a Claude session reports its state through the title). Whitelisted
    # like everything a node says; absent when the agent did not send it.
    if isinstance(s.get("sessions"), list):
        rep["sessions"] = _session_rows(s["sessions"])
    # Each synced project's state on the node (R162): whether its first
    # copy is done, what is waiting to go up, and why not when it cannot.
    if isinstance(s.get("sync"), dict):
        rep["sync"] = {re.sub(r"[^A-Za-z0-9._-]", "", str(k))[:100]: {
            "ready": bool((v or {}).get("ready")), "rev": int((v or {}).get("rev") or 0),
            "pending": max(0, min(10**7, int((v or {}).get("pending") or 0))),
            "copying": max(0, min(10**7, int((v or {}).get("copying") or 0))),
            "error": str((v or {}).get("error") or "")[:200]}
            for k, v in list(s["sync"].items())[:64] if isinstance(v, dict)}
    # ...leaving it (R164): what is still to go up; absent when not leaving.
    if isinstance(s.get("sync_drain"), dict):
        d = s["sync_drain"]
        rep["sync_drain"] = {"files": max(0, min(10**7, int(d.get("files") or 0))),
                             "claude": max(0, min(10**7, int(d.get("claude") or 0))),
                             "walked": d.get("walked") is True}
    else:
        rep.pop("sync_drain", None)
    # ...and the answer to the clean-up asked of it, by the asker's token.
    if isinstance(s.get("sync_clean"), dict):
        c = s["sync_clean"]
        rep["sync_clean"] = {"token": str(c.get("token") or "")[:64],
                             "freed": max(0, int(c.get("freed") or 0)),
                             "error": str(c.get("error") or "")[:300]}
    store_merge(rep.get("stores") or {}, clean["stores"], totals)
    _exec("UPDATE nodes SET agent = ?, reported = ? WHERE id = ?",
          (json.dumps(ag), json.dumps(rep), nid))
    ring = _samples.setdefault(nid, [])
    ring.append(clean)
    del ring[:-SAMPLES_KEEP]
    # Every sample moves the numbers on the row, and the row is the only
    # place they are shown: one repaint per node per poll is the cost.
    _bump()
    if moved:
        session_net_nudge()


def _session_rows(rows):
    """A node's tmux sessions as the row keeps them (roadmap #24): name,
    whether a client is attached, the active pane's directory and title (a
    Claude session reports its state through the title). Whitelisted like
    everything a node says."""
    out = []
    for row in rows[:64]:
        if not isinstance(row, dict):
            continue
        name = re.sub(r"[^A-Za-z0-9_~.:-]", "", str(row.get("name") or ""))[:120]
        if not name:
            continue
        out.append({
            "name": name, "attached": bool(row.get("attached")),
            "cwd": str(row.get("cwd") or "")[:300],
            # When it started, so a toolchain installed since can say it is
            # not on its PATH.
            "created": _mb(row.get("created")) or 0,
            "title": str(row.get("title") or "")[:200]})
    return out


def sessions_report(nid, rows):
    """A node's sessions as they are right now, sent the moment one changes
    (a session starting, ending, or turning from waiting to working) rather
    than on the poll's turn: what the dot beside each name on a project's
    row is drawn from (the operator, 25 Sep). The same rows the heartbeat
    carries, so nothing reads them two ways."""
    if not isinstance(rows, list):
        return {"error": "sessions is a list"}
    n = node(nid)
    if not n:
        return {"error": "no such node"}
    rep = n.get("reported") or {}
    rep["sessions"] = _session_rows(rows)
    _exec("UPDATE nodes SET reported = ? WHERE id = ?", (json.dumps(rep), nid))
    _bump()
    return {"ok": True, "sessions": len(rep["sessions"])}


def samples(nid):
    return list(_samples.get(nid, []))


# ---------------------------------------------------------------------------
# jobs: the queue (docs/nodes.md §2, phase 4)
#
# The queue is a list and placement is a function. A job names a node or a
# selector; a node with a free slot takes the oldest queued job it fits, and
# from then on the row says where it ran, not where it might have. There are
# two kinds of runner: an AGENT takes its jobs over the channel (exec and
# self-update), and the CONTROLLER runs the rest itself: compose actions
# against a node's daemon, and exec on the nodes that have no agent (local,
# ssh). Both ask the same question of the same table through job_next(), and
# concurrency is counted here from the rows rather than trusted from either.

# exec runs argv; compose is the controller's docker; self-update, system
# (phase 5), toolchain (an install against the node's toolchain store)
# and cache-clear (drop the node's build caches) are the agent's own.
JOB_TYPES = ("exec", "self-update", "compose", "system", "toolchain", "cache-clear",
             # An Android system image onto a node's toolchain store, or off
             # it: there without being a toolchain (emulator.py).
             "image",
             # The sign-in flow, on the machine Claude is installed on: a job
             # of its own because it opens a PTY and drops to the SESSION
             # account, not the job one (R47). Both matter: the flow prints a
             # prompt with no newline after it, and the grant has to land in
             # the home a session will read it from.
             "claude-login",
             # ...and its other half: `claude auth logout` there, in one
             # account's home, since the login is that machine's to let go.
             "claude-logout",
             # Claude Code itself, for the session account: the installer run
             # there, then the binary pinned where the account cannot write it
             # (claudecode.py). Queued by an administrator's press and nothing
             # else; the Claude sessions on the node are ended first.
             "claude-update",
             # A line typed into a Claude session on the node, Enter pressed
             # only once the pane echoes it (notify.py's rule, run where the
             # pane is): the roadmap's and the tracker's Send to Claude.
             "tell",
             # A build in dist/ signed with one of the project's keys
             # (signing.py, R106): the key fetched over the channel for this
             # job alone, used as the enrolled account, never a session's.
             "sign")
JOB_END = ("succeeded", "failed", "canceled")

# Probe jobs (run_wait's `forget`): a read the page makes to draw itself,
# such as the Docker manager's `docker ps` on an agent node. They move no
# revision at any point of their life, because a page that refetches on the
# jobs revision would otherwise probe, see the revision move, and refetch
# again without end; they are dropped once read and never listed.
_probe_ids = set()


def _quiet(job_id):
    return job_id in _probe_ids
JOB_ACTIVE = ("queued", "assigned", "running")
# The kinds an agent counts in its heartbeat (builderbot-agent.py PROC_KINDS).
PROC_KINDS = ("emulator", "gradle", "java", "compile", "browser", "media", "docker build", "claude",
              "python", "display")
# A driver package apt may be asked for (the agent holds the same rule).
DRIVER_PKG = re.compile(r"nvidia-driver(-\d{3})?(-open)?")
# What a selector may name (door 9: os and arch are placement dimensions).
SELECT_KEYS = ("capability", "labels", "pool", "os", "arch")
_jrev = [0]
# type -> what to run on the controller when a job of that type ends,
# registered by the module that queues them (devactions for compose).
ON_DONE = {}


def on_done(job_type, fn):
    ON_DONE[job_type] = fn


def jobs_rev():
    """Bumped on every job mutation and every log chunk; /api/revs carries
    it so the Jobs tab and the rows that watch a job refetch on change."""
    return _jrev[0]


def _jbump():
    _jrev[0] += 1


# The jobs rev without the log chunks: a job queued, taken, finished,
# canceled, or a new step word, and nothing for a line of output. What a
# ROW watches. The Docker manager followed the jobs rev and refetched its
# whole listing several times a second through every build, for a tail it
# has since stopped drawing; the Jobs tab, which does draw the log, keeps
# the full rev.
_jsrev = [0]


def jobs_state_rev():
    return _jsrev[0]


def _jstate_bump():
    """A job was queued, taken, finished or canceled: the jobs rev, and the
    nodes rev with it, because a node's row carries what is applying on it,
    its last apply and its last runner failure, all read off the jobs. An
    open Nodes tab refetches on the nodes rev, so this is what lets it say
    "installing now" and then the result without anybody reloading. A log
    chunk moves only the jobs rev: a row does not change for one."""
    _jbump()
    _jsrev[0] += 1
    _bump()


def runner_of(job_type, kind):
    """Who executes a job of this type on a node of this kind.

    An agent runs everything for itself, compose included: the node's own
    docker, on the node, so the token it enrolled with is the only way in and
    the controller needs no ssh key. Only `local` is left here, and only
    because it IS here: the ssh kind, which used to leave compose on the
    controller over an ssh key, is gone (roadmap #24).
    """
    return "controller" if kind == "local" else "node"


def fits(job, n):
    """Placement, in one place: may this node take this job. An explicit
    node is exact; a selector is every key it names, all of which must hold.
    Nothing here about load: first free slot wins, which is the whole
    scheduling policy a single operator needs (docs/nodes.md §2)."""
    if n["state"] != "online":
        return False
    # An agent that is behind takes nothing but its own update. Here as well
    # as in job_add, because job_add only sees the explicitly-placed case:
    # a selector-placed job is matched to a node at take time, and this is
    # where that happens.
    if job.get("type") != "self-update" and runner_of(job.get("type") or "", n["kind"]) == "node" \
            and agent_stale(n):
        return False
    pl = job.get("placement") or {}
    if pl.get("node"):
        return pl["node"] == n["id"]
    sel = pl.get("select") or {}
    if sel.get("capability") and sel["capability"] not in n["capabilities"]:
        return False
    if sel.get("pool") and sel["pool"] != n["pool"]:
        return False
    if sel.get("os") and sel["os"] != n.get("os"):
        return False
    if sel.get("arch") and sel["arch"] != n.get("arch"):
        return False
    for k, v in (sel.get("labels") or {}).items():
        if (n.get("labels") or {}).get(k) != v:
            return False
    return True


def pick(job, candidates):
    """The first node in `candidates` the job fits, or None. The one call
    site that decides where work goes; fair-share or quotas would be this
    function swapped, not four places edited."""
    for n in candidates:
        if fits(job, n):
            return n
    return None


def _placement(placement):
    """A placement as the caller wrote it, cleaned, or the reason it is
    not one. {"node": id} or {"select": {...SELECT_KEYS}}."""
    pl = placement if isinstance(placement, dict) else {}
    if pl.get("node"):
        return {"node": str(pl["node"])[:40]}, ""
    sel = pl.get("select") if isinstance(pl.get("select"), dict) else {}
    clean = {}
    for k in SELECT_KEYS:
        v = sel.get(k)
        if not v:
            continue
        if k == "labels":
            if isinstance(v, dict):
                clean[k] = {str(a)[:40]: str(b)[:80] for a, b in list(v.items())[:8]}
        else:
            clean[k] = str(v)[:40]
    if not clean:
        return None, "a job names a node or a selector (capability, labels, pool, os, arch)"
    return {"select": clean}, ""


def job_add(principal, placement, type, spec, project="", source=None):
    """Queue a job. With an explicit node the node is checked now: it must
    exist, be online, and hold a credential if it is an agent. With a
    selector, at least one node must fit right now: a job nothing could ever
    take would sit queued forever, and "no node has X" at the button is the
    honest answer (docs/nodes.md §18: the dashboard says which project has
    no node). Assignment itself happens when a node asks, in job_next."""
    if type not in JOB_TYPES:
        return {"error": f"job type is one of {', '.join(JOB_TYPES)}"}
    pl, why = _placement(placement)
    if why:
        return {"error": why}
    probe = {"placement": pl, "type": type}
    if pl.get("node"):
        n = node(pl["node"])
        if not n:
            return {"error": "no such node"}
        if n["state"] != "online":
            return {"error": f"node is {n['state']}; it takes no new work"}
        if host_only(n) and type not in HOST_JOBS:
            return {"error": f"{n['name']} hosts containers only, and a {type} job is not one of those"}
        if n["kind"] == "agent" and type != "compose" and not n.get("live"):
            return {"error": "the agent on this node is not dialing in; the "
                             "job would wait until it does"}
        # Everything the AGENT runs waits for the agent to be current; its
        # own update is the way out and is never blocked.
        if type != "self-update" and runner_of(type, n["kind"]) == "node":
            why = agent_stale(n)
            if why:
                return {"error": why}
    elif pick(probe, node_list()) is None:
        want = ", ".join(f"{k}={v}" for k, v in pl["select"].items())
        return {"error": f"no node fits {want}"}
    jid = mint("j")
    probe = bool(isinstance(spec, dict) and spec.get("probe"))
    if probe:
        _probe_ids.add(jid)
    _exec("INSERT INTO jobs (id, type, project, requested_by, placement, "
          "source, spec, outputs, state, node, exit_code, queued, started, "
          "ended, step, error, cancel) VALUES (?, ?, ?, ?, ?, ?, ?, ?, "
          "'queued', ?, NULL, ?, NULL, NULL, '', '', 0)",
          (jid, type, str(project or "")[:120], str(principal),
           json.dumps(pl), json.dumps(source if isinstance(source, dict) else {}),
           json.dumps(spec if isinstance(spec, dict) else {}),
           json.dumps([]), pl.get("node") or "", int(time.time())))
    if not probe:
        audit(principal, "job-add", jid, {"placement": pl, "type": type})
        _jstate_bump()
    with _wake:
        _wake.notify_all()
    return {"ok": True, "job": jid}


def run_wait(principal, node_id, argv, env=None, timeout=30, files=None,
             sizes=None, project="", forget=False, outputs=None, title="", cwd=""):
    """One command on a node, waited for: queued as an exec job, picked up
    by the agent's next poll (which is held open, so at once), and its log
    and exit code handed back: the Nodes tab's Test, generalised. For the
    phone: adb on the node that holds the handset, where the controller has
    no adb and no phone. {"code", "out"} or {"error"}.

    `forget` is for a READ nobody asked to see: the Docker manager's
    `docker ps` on an agent node runs this way each time a listing is
    drawn, and a row per draw on the Jobs tab would bury the jobs somebody
    queued on purpose. The record is dropped once its answer is in hand;
    the audit line from job_add stays.

    `outputs` are globs, in the job's directory, of files the agent uploads
    into the project's dist/ when the command succeeds: a file that would
    otherwise ride the log as text (a phone's screenshot, report #53)."""
    spec = {"argv": [str(a) for a in argv], "timeout": int(timeout)}
    if title:
        spec["title"] = str(title)[:120]      # what the Jobs tab calls it
    if cwd:
        spec["cwd"] = str(cwd)                 # where it runs on the node, else the data store
    if outputs:
        spec["outputs"] = [str(o) for o in outputs][:4]
        spec["project"] = project
    if forget:
        spec["probe"] = True
    if env:
        spec["env"] = {str(k): str(v) for k, v in env.items()}
    if files:
        spec["files"] = list(files)
        spec["sizes"] = dict(sizes or {})
        spec["project"] = project
    r = job_add(principal, {"node": node_id}, "exec", spec, project)
    if r.get("error"):
        return {"error": r["error"]}
    deadline = time.time() + timeout + 10
    while time.time() < deadline:
        j = job(r["job"])
        if j and j["state"] in JOB_END:
            if forget:
                job_forget(r["job"])
            return {"code": j.get("exit_code") if j["state"] == "succeeded" or j.get("exit_code") is not None else 1,
                    "out": j.get("log") or "", "job": r["job"], "state": j["state"]}
        time.sleep(0.25)
    # Taken back, not left in the queue: a probe nobody is waiting for any
    # more would otherwise run whenever the node's slot freed: an `adb
    # install` an hour after the operator read it as failed.
    why = _no_answer(r["job"], node_id, timeout)
    job_cancel(principal, r["job"])
    return {"error": why}


def _no_answer(job_id, node_id, timeout):
    """Why a waited-on job did not come back, in the words that are true.

    It used to say "the agent took the job but did not report back" whatever
    had happened, and mostly that was false (B200): a node runs `concurrency`
    jobs at once, usually one, so a one-second `uname` queued behind a
    fifteen-minute build never STARTED, the agent was healthy and heartbeating
    throughout, and the person reading it concluded the machine had hung.
    Which of the two it was is on the job's own record.
    """
    j = job(job_id, with_log=False) or {}
    n = node(node_id) or {}
    name = n.get("name") or node_id
    if j.get("state") == "running":
        return (f"{name} started the job ({job_id}) and it did not finish within {timeout}s; "
                "it has been canceled")
    busy = [x for x in jobs_for(node_id=node_id, active=True, n=5)
            if x.get("id") != job_id and x.get("state") == "running"]
    if busy:
        b = busy[0]
        what = " ".join(str(x) for x in [b.get("type"), b.get("project") or ""] if x)
        return (f"{name} is busy with {what} ({b['id']}) and runs "
                f"{n.get('concurrency') or 1} job at a time: this waited {timeout}s for a "
                "slot and was taken back. The machine is fine; try again when that finishes")
    # Handed out and never started: the lane it holds is why this one waited
    # (B245). Named with its age, and with when the agent last dialed in, so
    # the reader can tell a lost poll from a machine that is off.
    held = [x for x in jobs_for(node_id=node_id, active=True, n=10)
            if x.get("id") != job_id and x.get("state") == "assigned"]
    seen = int((n.get("agent") or {}).get("last_seen") or 0)
    ago = f"{int(time.time()) - seen}s ago" if seen else "never"
    if held:
        h = held[0]
        age = int(time.time()) - int(h.get("started") or time.time())
        what = " ".join(str(x) for x in [h.get("type"), h.get("project") or ""] if x)
        return (f"{name} was handed {what} ({h['id']}) {age}s ago and has not started it, "
                f"and this one waited {timeout}s behind it; the node is {n.get('state')}, "
                f"its agent last dialed in {ago}")
    return (f"{name} did not pick the job ({job_id}) up within {timeout}s: "
            f"the node is {n.get('state') or 'unknown'} and its agent last dialed in {ago}")


def tell_wait(node_id, session, text, timeout=20):
    """One line into a Claude session on a node, waited for: a `tell` job
    the agent runs as notify.tell runs here (type, look for the echo, Enter
    only if it appeared), answered in the same shape. {"sent": True} when
    it went, {"typed": True} when it was left unsent in the box, or
    {"error"}."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    r = job_add("dashboard", {"node": node_id}, "tell",
                {"session": str(session), "text": str(text), "timeout": int(timeout)})
    if r.get("error"):
        return {"error": r["error"]}
    deadline = time.time() + timeout + 10
    while time.time() < deadline:
        j = job(r["job"])
        if j and j["state"] in JOB_END:
            code = j.get("exit_code")
            if j["state"] == "succeeded" and code == 0:
                return {"ok": True, "sent": True, "text": text, "job": r["job"]}
            if code == 3:
                return {"ok": True, "sent": False, "typed": True, "text": text, "job": r["job"]}
            last = [x for x in (j.get("log") or "").splitlines() if x.strip()]
            return {"error": last[-1] if last else f"the send failed on {n['name']} (exit {code})"}
        time.sleep(0.25)
    job_cancel("dashboard", r["job"])
    return {"error": f"the agent on {n['name']} took the send but did not report back within {timeout}s"}


def root_wait(principal, node_id, argv, why="", timeout=600):
    """One approved command as root on a node (roadmap R38): a system job
    with `apply: root`, waited for like run_wait. The gate is node_apply's
    (an online agent node that enrolled as a sandbox, one system job at a
    time), because root on somebody's own machine is theirs, and the agent
    refuses it there too whatever this says. The reason and the approver
    ride in the spec so the job's log, which the Jobs tab keeps, says who
    allowed what and why."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "only an agent node takes system jobs"}
    if not (n.get("reported") or {}).get("sandbox"):
        return {"error": "this node was not provisioned as a BuilderBot sandbox, so root "
                         "there is its owner's"}
    if n["state"] != "online":
        return {"error": f"the node is {n['state']}; a root command goes to an online node"}
    if node_locked(n):
        return {"error": node_locked(n)}
    if system_job_for(node_id):
        return {"error": "a system job is already in flight on this node; one at a time"}
    spec = {"apply": "root", "timeout": int(timeout),
            "config": {"argv": [str(a) for a in argv], "why": str(why)[:300],
                       # The person, for the log's first line; the audit row
                       # keeps the principal as it is.
                       "by": str(principal).removeprefix("user:"), "timeout": int(timeout)}}
    r = job_add(principal, {"node": node_id}, "system", spec)
    if r.get("error"):
        return {"error": r["error"]}
    audit(principal, "root-run", node_id, {"argv": argv, "why": why, "job": r["job"]})
    deadline = time.time() + timeout + 10
    while time.time() < deadline:
        j = job(r["job"])
        if j and j["state"] in JOB_END:
            return {"code": j.get("exit_code") if j["state"] == "succeeded" or j.get("exit_code") is not None else 1,
                    "out": j.get("log") or "", "job": r["job"], "state": j["state"]}
        time.sleep(0.25)
    why = _no_answer(r["job"], node_id, timeout)
    job_cancel(principal, r["job"])
    return {"error": why}


def phone_nodes():
    """The nodes a phone can be driven from: agent nodes whose census
    reports adb, with whether they are dialing in. The Phone tab's picker."""
    out = []
    for n in node_list():
        if n["kind"] != "agent" or n["state"] in ("retired", "pending"):
            continue
        tc = (n.get("reported") or {}).get("toolchains") or {}
        if not isinstance(tc, dict) or not (tc.get("adb") or tc.get("android-sdk")):
            continue
        out.append({"id": n["id"], "name": n["name"], "live": bool(n.get("live")),
                    "stores": (n.get("reported") or {}).get("stores") or {}})
    return out


def job_running(node_id):
    """How many jobs this node has going, from the rows: the count the
    slot check uses. Not the agent's own number: that rides a request as a
    snapshot, and a poll held with a stale one made the next job wait out
    the whole window after the last one ended."""
    return _rows("SELECT COUNT(*) AS n FROM jobs WHERE node = ? AND state IN "
                 "('assigned', 'running')", (node_id,))[0]["n"]


# Nodes whose census a refusal has just called into question. Set by the
# gate, cleared when the agent is told; in memory because it is a nudge, not
# a fact worth surviving a restart.
_hello_wanted = {}


def ask_hello(node_id):
    if node_id:
        _hello_wanted[node_id] = True
        # A Condition over the store lock, not an Event: the held poll is
        # waiting on it, and notifying is how it hears without waiting out
        # its five seconds.
        with _wake:
            _wake.notify_all()


# Sessions to end on a node, by node id, until its agent's next poll takes
# them. In memory like the hello requests: a kill nobody delivered within a
# poll is one the operator will press again, and a restart should forget it.
_kills = {}


# node id -> {project: revision}: synced projects that moved since the
# node's agent last heard (R162), taken by its held work request.
_sync_hints = {}


def sync_hint(node_id, project, rev):
    with _wake:
        _sync_hints.setdefault(node_id, {})[project] = rev
        _wake.notify_all()


_synced = {"at": 0.0, "ids": frozenset()}


def sync_node_ids():
    """The nodes that hold their projects as a synced copy (R162), which is
    every agent node not taken off it (R163, R164: config workspace "off").
    Read again at most every two seconds: it is asked per project."""
    now = time.monotonic()
    if now - _synced["at"] > 2:
        _synced.update(at=now, ids=frozenset(
            n["id"] for n in node_list()
            if n.get("kind") == "agent" and n.get("state") != "retired"
            and ((n.get("config") or {}).get("workspace") or "sync") == "sync"))
    return _synced["ids"]


# ---- a hosting-only node (the operator, 10 Oct) ---------------------------------
# A node that holds no project's code and runs no sessions, only containers
# sent to it (a web-facing box): nothing of it comes back to the controller
# but what running those containers needs. Its agent may say hello, beat,
# take work, report a job's log and result, update itself, fetch an image
# shipped to it and carry a container's data in a copy or a move; nothing
# else. No project may list it, no session runs there, and only container,
# storage and network, self-update and cache-clearing jobs go to it.
HOST_VERBS = frozenset(("hello", "beat", "work", "log", "result", "download",
                        "devimage", "devdata", "devdata-put"))
HOST_JOBS = frozenset(("compose", "system", "self-update", "cache-clear"))


def host_only(n):
    """Whether a node (its row or its id) hosts containers and nothing else."""
    n = node(n) if isinstance(n, str) else n
    return bool(((n or {}).get("config") or {}).get("host_only"))


def host_refuses(nid, verb, what=""):
    """Why this node's agent may not use `verb`, or "": only a hosting-only
    node's are narrowed. `what` is a download's: the agent itself may come,
    the bb bundle may not."""
    if not host_only(nid):
        return ""
    if verb in HOST_VERBS and not (verb == "download" and what):
        return ""
    return (f"this node hosts containers only: {verb}"
            + (f" ({what})" if what else "") + " is not something it is given or may send")


def session_kill(node_id, name):
    """End a tmux session on a node: queued for the agent's held poll, and
    the poll woken so it goes now. The name is the node's own (the session
    account's prefix included); the page's name for it is translated back
    by the caller."""
    n = node(node_id)
    if not n or n["kind"] != "agent":
        return {"error": "no such node"}
    with _wake:
        _kills.setdefault(node_id, set()).add(str(name)[:120])
        # Off the list from this moment: the heartbeat that stops carrying
        # it is up to a poll away, and a row that stays after ✕ for twenty
        # seconds reads as a button that did nothing.
        _ended[(node_id, str(name)[:120])] = time.time()
        _wake.notify_all()
    return {"ok": True, "queued": True}


# (node id, session name) -> when the operator ended it, so the row goes
# at once rather than at the next heartbeat; forgotten after a minute, by
# which time the node has either dropped it or it is genuinely back.
_ended = {}


# tmux commands for a node's sessions (keys, a console's line, a macro),
# queued the same way, taken by the same poll. Each is {"session", "argv"}
# with the node's own session name already in argv, or {"session", "page"}
# for the paging decision the agent has to make on the pane it can see.
_tmux_ops = {}


def session_tmux(node_id, ops):
    n = node(node_id)
    if not n or n["kind"] != "agent":
        return {"error": "no such node"}
    with _wake:
        _tmux_ops.setdefault(node_id, []).extend(ops[:16])
        _wake.notify_all()
    return {"ok": True, "queued": True}


def node_sessions():
    """{node id: (name, [session rows])} for every online agent node whose
    heartbeat carried its tmux sessions (roadmap #24)."""
    out = {}
    for n in node_list():
        if n["kind"] != "agent" or n["state"] != "online" or not n.get("live"):
            continue
        rows = (n.get("reported") or {}).get("sessions")
        if isinstance(rows, list):
            now = time.time()
            out[n["id"]] = (n["name"], [
                r for r in rows
                if now - _ended.get((n["id"], str((r or {}).get("name") or "")), 0) > 60])
    return out


# A read that takes a second does not queue behind a build that takes fifteen
# minutes (B200). A node runs `concurrency` jobs at once, usually one, and the
# probes the dashboard draws itself from (uname for Test, `docker ps` for the
# manager, `adb devices` for the phone census, a log tail) waited for that one
# slot like a build would, timed out, and were reported as an agent that "did
# not report back", on a machine that was healthy and busy. They are exec jobs
# with a short timeout of their own, which is what marks them: nothing that
# builds, installs or deploys is asked to finish in half a minute. A couple may
# run beside whatever holds the slot. The agent needs nothing new for this: it
# polls for work whatever is running and leaves placement to these rows.
LIGHT_S = 30
LIGHT_SLOTS = 2


def _light(j):
    try:
        t = int((j.get("spec") or {}).get("timeout") or 0)
    except (TypeError, ValueError):
        return False
    return j.get("type") == "exec" and 0 < t <= LIGHT_S


def _light_running(node_id):
    return sum(1 for r in _rows("SELECT * FROM jobs WHERE node = ? AND "
                                "state IN ('assigned', 'running')", (node_id,))
               if _light(_job_out(r)))


# How long a job may sit `assigned` with no word from the agent before it
# goes back to the queue: a poll's answer can be lost (the agent restarted,
# the socket closed under it), and until now the job held a lane on the node
# until the agent's next hello, up to ten minutes, unnamed (B245). An agent
# that took a job says so within seconds (its first step or the keepalive).
ASSIGN_LOST_S = 2 * POLL_S + 40


def _requeue_unclaimed(node_id):
    cut = int(time.time()) - ASSIGN_LOST_S
    for r in _rows("SELECT id FROM jobs WHERE node = ? AND state = 'assigned' AND "
                   "started < ?", (node_id, cut)):
        _exec("UPDATE jobs SET state = 'queued', started = NULL WHERE id = ? "
              "AND state = 'assigned'", (r["id"],))
        if not _quiet(r["id"]):
            _jstate_bump()


# ...and how long past its own timeout a job may stay `running` with no
# result before it is failed: a job whose end never came back held the
# node's one slot for good. A lent phone's base64 screenshot did (B475's
# job), unseen because probes are not listed, and every sign and rebuild on
# bb-sandbox queued behind it for hours while short execs went on the light
# lane (report #55). A job with no timeout gets the longest the agent gives
# any kind, a build's.
RUN_LOST_S = 300
RUN_DEFAULT_S = 6 * 3600


def _fail_overdue(node_id):
    now = int(time.time())
    for r in _rows("SELECT id, spec, started FROM jobs WHERE node = ? AND state = 'running'", (node_id,)):
        try:
            spec = json.loads(r["spec"] or "{}")
        except (ValueError, TypeError):
            spec = {}
        try:
            limit = int(spec.get("timeout") or RUN_DEFAULT_S) + RUN_LOST_S
        except (ValueError, TypeError):
            limit = RUN_DEFAULT_S + RUN_LOST_S
        if r["started"] and r["started"] < now - limit:
            _exec("UPDATE jobs SET state = 'failed', ended = ?, step = '', error = ? "
                  "WHERE id = ? AND state = 'running'",
                  (now, "lost: ran past its time limit and the node never sent its end", r["id"]))
            if not _quiet(r["id"]):
                _jstate_bump()


def job_next(node_id, wait, runner="node", alive=None):
    """The oldest queued job this node may take, for this runner, else wait
    up to `wait` seconds for one, or for a cancel request, which comes back
    as {"cancel": [ids]} so the agent's held poll hears it at once.

    `alive` says whether the poll's client is still connected, and is asked
    before anything is handed over. A held poll outlives the agent that
    made it: an agent that restarted (its self-update, a kill) leaves its
    last poll on this side for up to a poll length, and a job queued in
    that window was assigned to the dead poll, written to a closed socket,
    and marked lost by the new agent's first hello, which never had it. The
    same poll would have swallowed a cancel, a session kill or a hello
    request. So a poll nobody is listening to takes nothing.

    Drain is honored here: a draining node's agent keeps polling (that is
    how the operator sees it is alive) and is simply never handed work. So
    is concurrency, counted from the rows. The job's node is written at this
    moment and never again: placement frozen at assignment."""
    deadline = time.time() + max(0, float(wait))
    with _wake:
        while True:
            if alive is not None and not alive():
                return None
            n = node(node_id)
            if n and n["state"] == "online":
                _requeue_unclaimed(node_id)
                _fail_overdue(node_id)
                # A slot free, or not: with none, a LIGHT job may still go
                # (see _light). Everything else waits for the slot as before.
                free = job_running(node_id) < n["concurrency"]
                lane = not free and _light_running(node_id) < LIGHT_SLOTS
                # An agent update waits for the node to go quiet (B516): the
                # agent refuses it while another job runs, and a node always
                # doing something (a session building and testing all day)
                # refused every press. So while one is queued the node is
                # handed nothing new, and it is handed the update once what
                # was running has finished; a node not quiet within
                # UPDATE_QUIET_S fails it, saying so, and works again.
                upd = _update_gate(node_id) if runner == "node" else None
                if upd is not None:
                    free = lane = False
                    if upd:
                        _exec("UPDATE jobs SET state = 'assigned', node = ?, started = ? WHERE id = ?",
                              (node_id, int(time.time()), upd["id"]))
                        _jstate_bump()
                        # ...naming what the agent last said it holds that
                        # this side has finished or dropped. An agent from
                        # 0.7.136 passes over only those of them whose work
                        # has ended and that are only posting their end, so a
                        # stuck job no longer blocks its own way out and a
                        # job still working is never left behind (B520).
                        held = (n.get("agent") or {}).get("held") or []
                        spec = (upd.get("spec") or {}) | {"settled": held}
                        return upd | {"state": "assigned", "node": node_id, "spec": spec}
                for j in (_rows("SELECT * FROM jobs WHERE state = 'queued' AND "
                                "(node = ? OR node = '') ORDER BY queued, id",
                                (node_id,)) if (free or lane) else ()):
                    j = _job_out(j)
                    # Queued, but its plan is still being prepared
                    # (devactions._submit): not this poll's.
                    if (j.get("spec") or {}).get("hold"):
                        continue
                    if runner_of(j["type"], n["kind"]) != runner or not fits(j, n):
                        continue
                    if not free and not _light(j):
                        continue
                    # An agent's job is `assigned` until its first log post
                    # says it started: the poll reply can be lost on the
                    # wire. The controller's own runner starts it on the
                    # thread that asked, so it is running from here.
                    st = "running" if runner == "controller" else "assigned"
                    _exec("UPDATE jobs SET state = ?, node = ?, "
                          "started = ? WHERE id = ?",
                          (st, node_id, int(time.time()), j["id"]))
                    if not _quiet(j["id"]):
                        _jstate_bump()
                    return j | {"state": st, "node": node_id}
            if runner == "node":
                asked = [r["id"] for r in _rows(
                    "SELECT id FROM jobs WHERE node = ? AND cancel = 1 AND "
                    "state IN ('assigned', 'running')", (node_id,))]
                if asked:
                    return {"cancel": asked}
                # ...and the sessions the operator has ended from the
                # Sessions card (roadmap #24): a node's tmux is the
                # session account's on that machine, so the agent kills
                # them, and the held poll is how it hears at once.
                kills = _kills.pop(node_id, None)
                if kills:
                    return {"kill_sessions": sorted(kills)}
                ops = _tmux_ops.pop(node_id, None)
                if ops:
                    return {"tmux": ops}
                # ...and a request for a fresh census, when something has
                # been refused on the strength of an old one. The agent says
                # hello every ten minutes, which is fine for a display and
                # too coarse for a gate: a refusal can be reasoning about a
                # node as it was nine minutes ago, and the retry a human
                # makes five seconds later reasons about the same stale
                # answer. This is how the next one does not.
                if _hello_wanted.pop(node_id, None):
                    return {"hello": True}
                # ...and the synced projects that moved (R162, wssync.py):
                # the agent asks what changed, so a save on another node or
                # in VS Code reaches this one in a second, not at its next
                # look of its own.
                moved = _sync_hints.pop(node_id, None)
                if moved:
                    return {"sync": moved}
            left = deadline - time.time()
            if left <= 0:
                return None
            _wake.wait(min(left, 5))


UPDATE_QUIET_S = 600


def _update_gate(node_id):
    """None when no agent update is queued for this node; else the update
    job to hand over now (the node is quiet), or {} while it waits for the
    node's running jobs to finish. One that has waited UPDATE_QUIET_S is
    failed with what kept the node busy, and the node works on."""
    rows = _rows("SELECT * FROM jobs WHERE state = 'queued' AND type = 'self-update' AND node = ? "
                 "ORDER BY queued, id LIMIT 1", (node_id,))
    if not rows:
        return None
    j = _job_out(rows[0])
    busy = _rows("SELECT type, COUNT(*) AS n FROM jobs WHERE node = ? AND state IN ('assigned', 'running') "
                 "GROUP BY type", (node_id,))
    if not busy:
        return j
    if time.time() - int(j.get("queued") or 0) > UPDATE_QUIET_S:
        what = ", ".join(f"{b['n']} {b['type']}" for b in busy)
        _exec("UPDATE jobs SET state = 'failed', ended = ?, step = '', error = ? WHERE id = ?",
              (int(time.time()), f"the node never went quiet for the update in {UPDATE_QUIET_S // 60} "
                                 f"minutes: still running {what}; press Update agent again when they finish",
               j["id"]))
        _jstate_bump()
        return None
    return {}


def _job_out(j):
    j = dict(j)
    for k in ("placement", "source", "spec", "outputs"):
        with contextlib.suppress(ValueError, TypeError):
            j[k] = json.loads(j[k])
    j["cancel"] = bool(j.get("cancel"))
    return j


def job(job_id, with_log=True):
    got = _rows("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not got:
        return None
    j = _job_out(got[0])
    if with_log:
        j["log"] = "".join(r["chunk"] for r in _rows(
            "SELECT chunk FROM job_logs WHERE job_id = ? ORDER BY seq",
            (job_id,)))
    return j


# ---- retention on the job logs (roadmap R17 step 1, R42) --------------------
#
# A job's log is the only copy of what a node's job wrote, and it lives in the
# controller's store: nothing else has it, and until this there was no DELETE
# for one anywhere in the tree. A build's log runs to megabytes, so a busy
# project fills /config/builderbot.db and nothing says so.
#
# The ROW is kept and only the CHUNKS go. The job list, its state, its exit
# code and what it produced are the history and stay; what is dropped is the
# console output, which is the large part and the part nobody reads a month
# later. A list that forgets a build ran is worse than one that cannot show
# you its output.
#
# Hard-coded with a reason rather than a setting, per env-only-what-must: a
# limit is a default with a reason in the code or a field on the Settings tab,
# and that tab holds switches today. These two numbers are the same pair every
# other store here uses, a count and an age, and the count wins where they
# disagree: forty builds on a quiet project can be a year of history, and
# thirty days on a busy one can be a thousand.
JOB_LOG_KEEP = 40          # newest jobs per project whose logs are kept
JOB_LOG_DAYS = 30          # ...and nothing older than this, however few there are


def prune_job_logs(project=None):
    """Drop the log chunks past the policy; how many jobs lost theirs.

    Per project, because one project building all day should not age out
    another's, and a controller serving several people is the case this
    exists for.
    """
    where = "WHERE project = ?" if project else ""
    args = (project,) if project else ()
    gone = 0
    for row in _rows(f"SELECT DISTINCT project FROM jobs {where}", args):
        proj = row["project"]
        # Beyond the newest N, by when they ended (a job still running has no
        # `ended` and sorts first, which is right: it is the one being read).
        old = _rows(
            "SELECT id FROM jobs WHERE project = ? AND state IN "
            "('succeeded', 'failed', 'canceled') "
            "ORDER BY COALESCE(ended, queued) DESC LIMIT -1 OFFSET ?",
            (proj, JOB_LOG_KEEP))
        cutoff = int(time.time()) - JOB_LOG_DAYS * 86400
        aged = _rows(
            "SELECT id FROM jobs WHERE project = ? AND state IN "
            "('succeeded', 'failed', 'canceled') AND COALESCE(ended, queued) < ?",
            (proj, cutoff))
        for jid in {r["id"] for r in old} | {r["id"] for r in aged}:
            if _rows("SELECT 1 FROM job_logs WHERE job_id = ? LIMIT 1", (jid,)):
                _exec("DELETE FROM job_logs WHERE job_id = ?", (jid,))
                gone += 1
    return gone


def job_forget(job_id):
    """Drop a finished job and its log: only for a probe whose answer was
    read by the caller that queued it (run_wait's `forget`). A job somebody
    queued is a record and is never dropped here."""
    _exec("DELETE FROM job_logs WHERE job_id = ?", (job_id,))
    _exec("DELETE FROM jobs WHERE id = ? AND state IN "
          "('succeeded', 'failed', 'canceled')", (job_id,))
    _probe_ids.discard(job_id)


def job_tail(job_id, n=4000):
    """The end of a job's log, for a row that shows where it got to."""
    text = "".join(r["chunk"] for r in _rows(
        "SELECT chunk FROM job_logs WHERE job_id = ? ORDER BY seq DESC "
        "LIMIT 40", (job_id,))[::-1])
    return text[-n:]


def job_set(job_id, **fields):
    """The runner's progress: step, error. Nothing else is settable this
    way: state moves through job_next / job_result / job_cancel only."""
    sets = {k: str(v)[:500] for k, v in fields.items() if k in ("step", "error")}
    if sets:
        _exec("UPDATE jobs SET " + ", ".join(f"{k} = ?" for k in sets)
              + " WHERE id = ?", (*sets.values(), job_id))
        if not _quiet(job_id):
            # A step word or a reason is what a row draws, so the state-only
            # rev moves too: the controller's own runner sets them here.
            _jbump()
            _jsrev[0] += 1


def job_log(node_id, job_id, chunks, step=None):
    """Append log chunks. Each carries the agent's sequence number, and a
    chunk already stored is dropped, so an agent that lost the answer to a
    post and sends the batch again (door 5: it buffers what it could not
    report) never doubles a line. The answer carries the cancel flag: a
    runner posts output every half second, so this is how one that is busy
    hears it should stop."""
    got = _rows("SELECT node, state, cancel FROM jobs WHERE id = ?", (job_id,))
    # A job with no row is one this side dropped while the agent still ran it
    # (a probe forgotten once its row said finished). Refusing the post kept
    # it forever: the agent posts its log before its result and retries a
    # refused log for good, so the job never left the agent's count and every
    # self-update on bb-sandbox failed "busy" (B519). Taken and stored
    # nowhere; the job is NOT told to stop (the operator: nothing is ended
    # unless it is stuck), so it runs to its own end, whose result is then
    # refused and dropped.
    if not got:
        return {"ok": True, "stored": 0, "gone": True}
    if got[0]["node"] != node_id:
        return {"error": "not this node's job"}
    now = int(time.time())
    n = 0
    with _lock:
        for c in chunks if isinstance(chunks, list) else []:
            if not isinstance(c, dict):
                continue
            try:
                seq = int(c.get("seq"))
            except (TypeError, ValueError):
                continue
            if _rows("SELECT 1 FROM job_logs WHERE job_id = ? AND seq = ?",
                     (job_id, seq)):
                continue
            _exec("INSERT INTO job_logs (job_id, seq, at, chunk) VALUES "
                  "(?, ?, ?, ?)", (job_id, seq, now, str(c.get("chunk"))[:32768]))
            n += 1
        if got[0]["state"] == "assigned":
            _exec("UPDATE jobs SET state = 'running' WHERE id = ?", (job_id,))
        # The word the row shows, when the agent sent one with this post.
        if step is not None:
            _exec("UPDATE jobs SET step = ? WHERE id = ?", (str(step)[:60], job_id))
    if (n or step is not None) and not _quiet(job_id):
        _jbump()
        if step is not None:
            _jsrev[0] += 1
    # ...and anything waiting to go DOWN to the job. The agent posts output
    # every half second, so this reply is the only channel the controller has
    # toward a running job: `cancel` has ridden it since the start, and a
    # sign-in's code rides it the same way. Popped, not left: a code is
    # delivered once, and a retried post must not type it twice.
    return {"ok": True, "stored": n, "cancel": bool(got[0]["cancel"]),
            **({"input": _job_input.pop(job_id)} if job_id in _job_input else {})}


# {job id: text waiting to be typed into that job}. In memory, like the
# presence register: a code is good for a minute and a controller restart is
# a sign-in the operator starts again, so there is nothing here worth a row.
_job_input = {}


def job_input(job_id, text):
    """Queue one line for a running job's pty. It leaves on the job's next
    log post, which is at most half a second away."""
    j = job(job_id)
    if not j:
        return {"error": "no such job"}
    if j["state"] in JOB_END:
        return {"error": f"that job is {j['state']}"}
    _job_input[job_id] = str(text)[:4096]
    return {"ok": True}


def job_result(node_id, job_id, state, exit_code=None, error="", outputs=None):
    """Terminal. Idempotent by design: the agent retries until it is
    acknowledged, so the second arrival of the same result is a no-op with
    the same answer, not a second audit row."""
    got = _rows("SELECT node, state, type, project, error FROM jobs WHERE id = ?", (job_id,))
    if not got or got[0]["node"] != node_id:
        return {"error": "not this node's job"}
    # A row this side failed as lost while the agent kept the job (a
    # controller restart, a network gap longer than the grace window) takes
    # the job's real end late rather than dropping it, and says so (B285).
    late = (got[0]["state"] == "failed"
            and str(got[0].get("error") or "").startswith(("node lost", "lost:")))
    if got[0]["state"] in JOB_END and not late:
        return {"ok": True, "already": True}
    if state not in JOB_END:
        return {"error": "a result is succeeded, failed or canceled"}
    # Whether this is a quiet probe, decided BEFORE the state moves. The
    # waiter in run_wait polls for the end, and on seeing it forgets the job,
    # which takes it off the probe list; asked after the housekeeping below,
    # the question found it gone and bumped the revisions. The Docker tab
    # refetches on one of them and its read is a probe, so every read bumped
    # the next: a refresh every second or two for as long as the tab was
    # open (the operator's recording, 24 Sep; measured on the controller,
    # one bump per read).
    quiet = _quiet(job_id)
    code = None
    with contextlib.suppress(TypeError, ValueError):
        code = int(exit_code) if exit_code is not None else None
    # Guarded on the state, so a retry that overlaps the first arrival is the
    # no-op the docstring promises rather than a second audit row and a
    # second run of the hooks (the review of 26 Sep).
    err = str(error or "")[:500]
    # An update refused as busy on a node this side saw go quiet: what the
    # agent holds is jobs this side has finished or dropped, named from its
    # last hello, so the row says which rather than "exit 75" (B519).
    if got[0]["type"] == "self-update" and code == 75:
        held = ((node(node_id) or {}).get("agent") or {}).get("held") or []
        err = ("the agent says other jobs are running" + (
            f" ({', '.join(held)}), which this controller has as finished; "
            "they leave when the agent next posts their end" if held else "") + "; press Update agent again")[:500]
    if late:
        err = ("reported late, after this side called the node lost" + (": " + err if err else ""))[:500]
    cur = _exec("UPDATE jobs SET state = ?, exit_code = ?, ended = ?, step = '', "
                "error = ? WHERE id = ? AND (state NOT IN ('succeeded', 'failed', 'canceled') "
                "OR (state = 'failed' AND (error LIKE 'node lost%' OR error LIKE 'lost:%')))",
                (state, code, int(time.time()), err, job_id))
    if cur.rowcount == 0:
        return {"ok": True, "already": True}
    # What the job left behind: the artifacts it uploaded and, for a failed
    # one, the workspace the node kept for inspection (docs/nodes.md §6).
    if isinstance(outputs, list):
        keep = [o for o in outputs[:64] if isinstance(o, dict)]
        _exec("UPDATE jobs SET outputs = ? WHERE id = ?", (json.dumps(keep), job_id))
    audit(f"node:{node_id}", "job-result", job_id, {"state": state, "exit": code})
    # Swept here rather than on a timer: a job ending is exactly when a
    # project gains a log, so it is when one of its old ones can go, and the
    # work is bounded by that project's own history.
    # Housekeeping never loses a result: whatever goes wrong in the sweep, the
    # job that just finished is already recorded above.
    try:
        prune_job_logs(got[0]["project"] if "project" in got[0].keys() else None)
    except sqlite3.Error as e:
        print(f"dashboard: nodes: job log sweep after {job_id} skipped: {e}",
              file=sys.stderr, flush=True)
    # An uninstall that ran retires the node: the agent is gone with it, so
    # the row leaves every list now rather than after a stale timeout.
    if got[0]["type"] == "system" and state == "succeeded":
        spec = (job(job_id, with_log=False) or {}).get("spec") or {}
        if spec.get("apply") == "uninstall":
            node_state(f"node:{node_id}", node_id, "retired")
    # The module that queued this kind of job gets to finish it. A compose
    # action run by the agent still has records to write here (what was
    # built, from which commit, on which daemon), and this is where they
    # land, once, whichever runner served it.
    fn = ON_DONE.get(got[0]["type"] if "type" in got[0].keys() else "")
    if fn:
        try:
            # A hook may also REWORD the failure. All a node can honestly say
            # is "exit 1" (it ran an argv somebody else composed), while the
            # module that wrote the plan knows the step was "starting" and
            # what that means. The row used to carry that sentence because
            # the controller ran compose itself; this is how it keeps it now
            # the node does (roadmap #24).
            better = fn(job(job_id, with_log=False), state)
            if state != "succeeded" and isinstance(better, str) and better.strip():
                _exec("UPDATE jobs SET error = ? WHERE id = ?",
                      (better.strip()[:500], job_id))
        except Exception as e:                   # noqa: BLE001 (another module's hook must not lose a result already recorded)
            print(f"dashboard: nodes: {got[0]['type']} hook after {job_id} failed: "
                  f"{type(e).__name__}: {e}", file=sys.stderr, flush=True)
    if not quiet:
        _jstate_bump()
    with _wake:
        _wake.notify_all()      # the slot is free: a held poll may take the next
    return {"ok": True}


def job_release(job_id, spec):
    """A queued job that was holding for its plan (spec["hold"], which
    job_next skips) gets the plan and joins the queue. False when the job
    is no longer queued: canceled meanwhile, and the plan is dropped."""
    if not _rows("SELECT 1 FROM jobs WHERE id = ? AND state = 'queued'", (job_id,)):
        return False
    _exec("UPDATE jobs SET spec = ? WHERE id = ?",
          (json.dumps(spec if isinstance(spec, dict) else {}), job_id))
    if not _quiet(job_id):
        _jstate_bump()
    with _wake:
        _wake.notify_all()
    return True


def job_refuse(job_id, why):
    """A queued job its preparation refused: failed with the reason, where
    the row and the Jobs tab show the words (B260). Nothing ran, so no
    completion hook is owed."""
    _exec("UPDATE jobs SET state = 'failed', ended = ?, error = ? WHERE id = ? "
          "AND state = 'queued'", (int(time.time()), str(why)[:500], job_id))
    if not _quiet(job_id):
        _jstate_bump()
    with _wake:
        _wake.notify_all()


def job_cancel(principal, job_id):
    """Stop a job. Queued: it simply ends, canceled. Assigned or running:
    the flag is set and the runner is woken (the agent hears it on its
    next log post or held poll, the controller's own runner reads it and
    kills the process group), and the row stays running until the runner
    reports the end, because that is when it actually ended."""
    got = _rows("SELECT state, cancel FROM jobs WHERE id = ?", (job_id,))
    if not got:
        return {"error": "no such job"}
    if got[0]["state"] in JOB_END:
        return {"ok": True, "already": True}
    # Guarded on the state, since a node can claim the job between the read
    # above and this write: the queued row is ended only if it is still
    # queued, and one that was claimed meanwhile gets the flag instead, so
    # the agent hears the cancel rather than running a job the row calls
    # canceled (the review of 26 Sep).
    if got[0]["state"] == "queued":
        cur = _exec("UPDATE jobs SET state = 'canceled', ended = ?, error = 'canceled "
                    "before it started' WHERE id = ? AND state = 'queued'", (int(time.time()), job_id))
        if cur.rowcount == 0:
            _exec("UPDATE jobs SET cancel = 1 WHERE id = ?", (job_id,))
    elif not got[0]["cancel"]:
        _exec("UPDATE jobs SET cancel = 1 WHERE id = ?", (job_id,))
    if not _quiet(job_id):
        audit(principal, "job-cancel", job_id, {})
        _jstate_bump()
    with _wake:
        _wake.notify_all()
    return {"ok": True}


def jobs_for(node_id=None, n=50, project=None, type=None, active=False):
    q, args = "SELECT * FROM jobs", []
    # Never a probe: they are dropped once read, and one mid-flight is not
    # a row anybody queued.
    where = ["spec NOT LIKE '%\"probe\": true%'"]
    if node_id:
        where.append("node = ?"), args.append(node_id)
    if project:
        where.append("project = ?"), args.append(project)
    if type:
        where.append("type = ?"), args.append(type)
    if active:
        where.append("state IN ('queued', 'assigned', 'running')")
    if where:
        q += " WHERE " + " AND ".join(where)
    # rowid breaks the tie: ids are random, and two jobs queued in the same
    # second used to come back in either order: the row then showed an
    # older job as the latest, or none at all.
    q += " ORDER BY queued DESC, rowid DESC LIMIT ?"
    return [_job_out(r) for r in _rows(q, (*args, int(n)))]


# How long past liveness a job's node may be silent before the job is lost:
# LIVE_S already allows three missed polls, and a job mid-build does not
# need the row hedging for another few minutes on top.
LOST_S = LIVE_S + 30


# When this controller process started: a node's last_seen is from before
# a restart, so a restart longer than the grace window read as every agent
# gone at the first tick, and failed every running job on every node as
# "node lost" while the agents were fine (the review of 26 Sep).
_BOOT = int(time.time())


def jobs_lost():
    """Fail every job assigned to an agent that has gone quiet: "node lost"
    after a grace window (docs/nodes.md §10). The agent is the durable side:
    if it comes back with the job still running it reports late, and the
    row is already terminal, so the late result is dropped as `already`.
    That loses a result in the rarest case and never a row in the common
    one, which is the right way round."""
    now = int(time.time())
    n = 0
    for j in _rows("SELECT j.id, j.node FROM jobs j JOIN nodes k ON k.id = "
                   "j.node WHERE j.state IN ('assigned', 'running') AND "
                   "k.kind = 'agent'"):
        nd = node(j["node"])
        seen = max((nd.get("agent") or {}).get("last_seen") or 0, _BOOT)
        if now - seen > LOST_S:
            _exec("UPDATE jobs SET state = 'failed', ended = ?, step = '', "
                  "error = 'node lost: the agent stopped answering' WHERE "
                  "id = ?", (now, j["id"]))
            audit("system", "job-lost", j["id"], {"node": j["node"]})
            _lost_done(j["id"])
            n += 1
    if n:
        _jstate_bump()
    return n


def _lost_done(jid):
    """The module that queued a job hears that it was lost, as it hears a
    result: a compose rebuild failed as lost left the Docker row saying
    building, since only job_result ran the hook (B287)."""
    j = job(jid, with_log=False)
    fn = ON_DONE.get((j or {}).get("type") or "")
    if not fn or not j:
        return
    try:
        fn(j, "failed")
    except Exception as e:                                                # noqa: BLE001
        print(f"[dashboard] {jid}: the done hook failed after the job was lost: {type(e).__name__}: {e}", flush=True)


def jobs_reconcile(node_id, running):
    """At hello: the jobs this side has as running on the node that the
    node does not: an agent that restarted, whose children died with it."""
    have = {r["id"] for r in _rows(
        "SELECT id FROM jobs WHERE node = ? AND state IN ('assigned', "
        "'running')", (node_id,))}
    gone = have - set(running)
    for jid in gone:
        # A compose job on an agent node is the controller's, and the agent
        # never had it: only what the agent RUNS is reconciled against it.
        j = job(jid, with_log=False)
        if runner_of(j["type"], "agent") != "node":
            continue
        _exec("UPDATE jobs SET state = 'failed', ended = ?, step = '', error "
              "= 'lost: the agent restarted without it' WHERE id = ?",
              (int(time.time()), jid))
        audit("system", "job-lost", jid, {"node": node_id, "why": "restart"})
        _lost_done(jid)
    if gone:
        _jstate_bump()


def jobs_held(node_id, running):
    """The jobs the agent says it is running that this side has as finished
    or has no row for at all: the other half of jobs_reconcile. Each keeps
    the agent's count up, and an agent update is refused while any is held,
    so the refusal names them from here (B519)."""
    live = {r["id"] for r in _rows("SELECT id FROM jobs WHERE node = ? AND state IN "
                                   "('queued', 'assigned', 'running')", (node_id,))}
    return [j for j in running if j not in live][:20]


def jobs_restart_sweep():
    """At start: a job the controller itself was running when the process
    died is failed as lost: the subprocess died with it, and a row still
    saying running would say it forever. An agent's own jobs are left to
    the agent's hello, which reconciles against what it actually has."""
    now = int(time.time())
    n = 0
    for j in _rows("SELECT j.id, j.type, k.kind FROM jobs j LEFT JOIN nodes "
                   "k ON k.id = j.node WHERE j.state IN ('assigned', 'running')"):
        if runner_of(j["type"], j["kind"] or "local") != "controller":
            continue
        _exec("UPDATE jobs SET state = 'failed', ended = ?, step = '', error "
              "= 'lost: BuilderBot restarted while it was running' WHERE "
              "id = ?", (now, j["id"]))
        audit("system", "job-lost", j["id"], {"why": "controller restart"})
        n += 1
    if n:
        _jstate_bump()
    return n


def job_counts():
    """Jobs by state, nodes by state and liveness: the numbers /healthz
    and /metrics are made of."""
    out = {"jobs": {s: 0 for s in JOB_ACTIVE + JOB_END}, "nodes": {}}
    for r in _rows("SELECT state, COUNT(*) AS n FROM jobs GROUP BY state"):
        out["jobs"][r["state"]] = r["n"]
    for n in node_list():
        k = n["state"] + ("/live" if n.get("live") else "")
        out["nodes"][k] = out["nodes"].get(k, 0) + 1
    return out


# ---------------------------------------------------------------------------
# the agent file: served to nodes, and the digest hello compares against

AGENT_DIR = HERE.parent / "agent"
AGENT_VERSION_PY = AGENT_DIR / "builderbot_agent" / "__init__.py"
_agent_cache = {}


def _agent_bundle():
    """builderbot_agent/bundle.py, loaded by path: it makes the zip a node
    runs, and the agent itself makes the same one to know its own digest."""
    if "bundle" not in _agent_cache:
        spec = importlib.util.spec_from_file_location("bb_agent_bundle", AGENT_DIR / "builderbot_agent" / "bundle.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _agent_cache["bundle"] = mod
    return _agent_cache["bundle"]


def agent_file():
    """The agent this controller ships: bytes, sha256, version string. The
    agent is a package now, shipped as one zip (bundle.py) that a node runs
    as it ran the single file. Built once per change of its sources, so the
    digest hello answers with is the sources on disk right now, which is
    what makes 'is my agent current' a byte comparison on the node rather
    than a version number anyone typed."""
    try:
        b = _agent_bundle()
        mtime = b.newest(str(AGENT_DIR))
    except (OSError, ImportError, SyntaxError, ValueError):
        return {"body": b"", "digest": "", "version": ""}
    if _agent_cache.get("mtime") != mtime:
        try:
            body = b.build(str(AGENT_DIR))
            init = AGENT_VERSION_PY.read_bytes()
        except OSError:
            return {"body": b"", "digest": "", "version": ""}
        m = re.search(rb'^AGENT_VERSION\s*=\s*"([^"]+)"', init, re.MULTILINE)
        _agent_cache.update({
            "mtime": mtime, "body": body,
            "digest": "sha256:" + hashlib.sha256(body).hexdigest(),
            "version": m.group(1).decode() if m else "?"})
    return {k: v for k, v in _agent_cache.items() if k != "bundle"}


# ---------------------------------------------------------------------------
# the Nodes tab's verbs, one call from the dashboard's /api/v1/nodes

# What the verbs compose with, handed over by server.py (configure_verbs),
# which configures each of them in its own order. Not imported: bb loads
# this file by path with none of them beside it.
vmtemplate = None        # what a new sandbox VM is made from
forges = None            # the git hosts' catalog, for a runner's forge
devapp = None            # a node's daemon, for the path check and the test
runner_store = None      # runners.py: each runner's token, root-only
workspace = None         # a project's tree snapshotted, a file in its dist/
project_prefs = None     # a project -> its settings (its node and node set)
may_push = None          # a project -> whether it was cloned with push rights
no_node_advice = None    # a project with no node -> what it can still do
turns_of = None          # a node row -> its sessions' turns: working, waiting, the limit
_VERB_PARTS = ("vmtemplate", "forges", "devapp", "runner_store",
               "workspace", "project_prefs", "may_push", "no_node_advice", "turns_of")


def configure_verbs(**parts):
    """Join what verb() composes with. Only those names: a misspelt one
    would otherwise overwrite something of this module's own."""
    unknown = set(parts) - set(_VERB_PARTS)
    if unknown:
        raise TypeError(f"configure_verbs: nothing called {', '.join(sorted(unknown))}")
    globals().update(parts)


def agent_test(principal, n):
    """Test on an agent node: an exec job, waited for. The channel is
    the thing being tested, so the proof is a round trip through it
    (queued here, picked up by the next poll, run there, logged back),
    and a node that is not dialing in says so rather than timing out."""
    if not n.get("live"):
        return {"on": False, "why": ("waiting for enrollment"
                                     if n["state"] == "pending"
                                     else "not connected: the agent has "
                                     "not dialed in lately")}
    r = job_add(principal, {"node": n["id"]}, "exec",
                      {"argv": ["uname", "-srm"], "timeout": 20})
    if r.get("error"):
        return {"on": False, "why": r["error"]}
    deadline = time.time() + 15
    while time.time() < deadline:
        j = job(r["job"])
        if j and j["state"] in JOB_END:
            out = (j.get("log") or "").strip()
            db.audit(principal, "node-test", n["id"],
                     {"on": j["state"] == "succeeded"})
            return {"on": j["state"] == "succeeded",
                    "why": out or f"{j['state']} (exit {j['exit_code']})"}
        time.sleep(0.3)
    return {"on": False, "why": "the agent took the job but did not "
                                "report back within 15s"}


def verb(principal, req):
    """One of the Nodes tab's verbs, asked by an administrator: server.py
    holds that gate and this says what the verb means. The answer is
    (payload, status), a {ok} or {error} with 400 on the error unless the
    verb names its own status."""
    act = field(req, "action")
    nid = field(req, "id")
    # One closure per verb, in the table below; each answers with {ok} or
    # {error}, or with (payload, status) when its status is its own.

    def vm_xml():
        # What a new sandbox VM is made from, for whichever hypervisor is
        # picked. No node exists yet and nothing is written: a render of
        # a shipped machine with an identity of its own, which the
        # operator pastes into their manager or runs on its host.
        return vmtemplate.render(
            name=field(req, "name"), cores=req.get("cores"),
            memory_gb=req.get("memory_gb"), iso=field(req, "iso"),
            uid=field(req, "uuid"), hw=field(req, "mac"),
            hv=field(req, "hv"), disk_gb=req.get("disk_gb"),
            vmid=req.get("vmid")) | {"catalog": vmtemplate.catalog()}, 200

    def add():
        return node_add(principal, field(req, "name"),
                        field(req, "addr"),
                        req.get("capabilities"),
                        field(req, "pool") or "default")

    def update():
        return node_update(principal, nid, req.get("fields") or {})

    def uninstall():
        return node_uninstall(principal, nid)

    def state():
        return node_state(principal, nid,
                          {"drain": "draining", "online": "online",
                           "retire": "retired"}[act])

    def lock():
        # System changes locked to the node's own console: Apply
        # storage, Apply network and a root command refused while on.
        return node_lock(principal, nid, act == "lock")

    def enroll():
        if req.get("script"):
            return enroll_script(principal, req)
        return enroll_mint(principal, field(req, "name"),
                           req.get("capabilities"),
                           field(req, "user") or "bb", host_only=req.get("host_only") is True,
                           nginx=req.get("nginx") is True)

    def power():
        return node_power(principal, nid, act)

    def gpu_display():
        # The emulator on the card, on or off (R102): each a system job.
        if req.get("on") is False:
            return node_gpu_display_off(principal, nid)
        return node_gpu_display(principal, nid)

    def gpu_compute():
        return node_gpu_compute(principal, nid, req.get("on") is True)

    def config():
        # The configuration plane (docs/nodes.md §12): what the operator
        # wants the node to mount and be addressed as. Stored here,
        # applied by the next action as a system job the agent runs.
        return node_config_set(principal, nid, req.get("config"))

    def turns():
        # How many Claude sessions on the node may work at once; 0 for
        # no limit. An administrator's, like the rest of this handler.
        return node_turn_limit(principal, nid, req.get("limit"))

    def test_workers():
        # How many workers a test run on the node may use (R81); 0 for
        # its cores. An administrator's, like the rest.
        return node_test_workers(principal, nid, req.get("workers"))

    def session_net():
        # Whether each session on the node reaches only its own project's
        # containers (R79). An administrator's, like the rest.
        return node_session_net(principal, nid, req.get("on") is True)

    def root_asks():
        # Whether a session on the node may ask for a root command at
        # all. An administrator's, like the rest.
        return node_root_asks(principal, nid, req.get("on") is True)

    def apply():
        return node_apply(principal, nid, field(req, "what"))

    def host_on():
        # Hosting only: containers and nothing of a project or a session.
        # An administrator's, like the rest.
        return node_update(principal, nid, {"host_only": True})

    def host_off():
        return node_update(principal, nid, {"host_only": False})

    def to_sync():
        # Back onto its synced copy from off (R164). An administrator's,
        # like the rest.
        return node_to_sync(principal, nid)

    def sync_stop():
        # ...and off it again (R164): stop, then clean up.
        return node_sync_stop(principal, nid)

    def sync_resume():
        return node_sync_resume(principal, nid)

    def sync_clean():
        return node_sync_clean(principal, nid)

    def runner():
        # One of the node's runners (phase 7, one per git host): a system
        # job, minting from the token stored for that runner. The URL is
        # the record's, written when the token was, so the token and the
        # address it was made for cannot come apart.
        slot = re.sub(r"[^a-z0-9.-]", "", field(req, "slot"))[:60]
        return node_runner(principal, nid, slot, bool(req.get("want", True)),
                           req.get("labels"),
                           token=slot in runner_store.tokens().get(nid, set()))

    def runner_token():
        # The node's runner token: forge and URL onto the record, the
        # token itself into the root-only store through the helper.
        # Not forges.parse: that wants owner/repo, and a runner's address
        # is as often an organization, one segment deep.
        url = field(req, "url").strip()
        # http as well as https: a Gitea on the LAN, the docker-compose
        # shape, serves plain http, and the enrollment already makes the
        # same trade with a note. GitHub is https whatever is typed.
        at = re.fullmatch(r"https?://([A-Za-z0-9.-]+(?::[0-9]{1,5})?)/[A-Za-z0-9._/-]+", url)
        if not at:
            return {"error": "the URL is the https address of the repository or "
                             "organization the runner registers with (http is "
                             "accepted for a forge on your own network)"}
        if not node(nid):
            return {"error": "no such node"}
        # The forge from the picker when it says, else from the host:
        # a private Gitea nobody has linked a project to yet is
        # "another git host" to the catalog, and the picker is how
        # the operator says otherwise.
        forge = field(req, "forge")
        if forge not in ("github", "gitea"):
            forge = forges.forge_of(at.group(1)).get("kind") or "git"
        slot = runner_slot(url)
        r = runner_store.store(nid, slot, url, forge, str(req.get("token") or "").strip())
        if not r.get("error"):
            r = node_runner_url(principal, nid, slot, url, forge,
                                req.get("labels") if isinstance(req.get("labels"), list) else None)
            r["slot"] = slot
        return r

    def runner_forget():
        slot = re.sub(r"[^a-z0-9.-]", "", field(req, "slot"))[:60]
        r = runner_store.forget(nid, slot)
        if not r.get("error"):
            r = node_runner_forget(principal, nid, slot)
        return r

    def paths():
        # What this container's paths are called on the node's machine
        # (docs/nodes.md §11): the mapping that was DOCKER_HOST_PATHS.
        return node_paths_set(principal, nid, field(req, "paths"))

    def check_paths():
        # Whether the two machines mean the same directory by the
        # projects share (roadmap #13): a marker made here, looked for
        # through the node's daemon. Off the poll, on purpose.
        return ({"error": "no such node"} if not node(nid)
                else devapp.check_paths(nid))

    def funnel():
        # Tailscale Funnel for a port on the node, raw: the manager's
        # route picker goes through the instance's record; this is the
        # same job by hand, for a port that is not an instance's.
        return node_funnel(principal, nid, req.get("port"), bool(req.get("on", True)))

    def update_agent():
        return node_update_agent(principal, nid)

    def cache_clear():
        # Drop a node's build caches, one project's or all (docs/nodes.md
        # §6): a job the agent runs, so it is logged and audited like
        # everything else that touches a node's disk.
        n = node(nid)
        if not n or n["kind"] != "agent":
            return {"error": "only an agent node keeps caches to clear"}
        return job_add(principal, {"node": nid}, "cache-clear",
                       {"project": field(req, "project")})

    def exec_():
        # The channel's one job type, from the tab or from curl: run
        # this argv on that node, as the enrolled account, and read the
        # log back from /api/v1/jobs. What the Test button sends, and
        # what a session holding the credential could: the same reach
        # a session already has over ssh to the sandbox, audited now.
        argv = [str(a) for a in (req.get("argv") or []) if str(a)][:64]
        if not argv:
            return {"error": "argv is empty"}
        spec = {"argv": argv, "timeout": 600}
        # What the job needs the node to be enrolled for. The node
        # checks it, not the row (door 7), and this is how that is exercised.
        need = [str(c) for c in (req.get("requires") or []) if str(c)][:8]
        if need:
            spec["requires"] = need
        # Placed on the node named, or (with `select` and no id) on
        # whichever node fits the selector when one asks (phase 4).
        place = ({"select": req["select"]} if not nid
                 and isinstance(req.get("select"), dict) else {"node": nid})
        return job_add(principal, place, "exec", spec, field(req, "project"))

    def test():
        n = node(nid)
        if not n:
            return {"error": "no such node"}
        if n["kind"] == "local":
            return {"on": False, "why": "the local node runs no daemon"}
        if n["kind"] == "agent":
            return agent_test(principal, n)
        # The same verdict the Docker manager gates on, asked of THIS
        # node's daemon right now: drop the memo, probe, answer. The
        # sandbox-stamp check rides along, because a node that answers
        # docker but is not a sandbox is the case worth a button.
        devapp.forget_available()
        with devapp.on_node(nid):
            got = devapp.available_cached()
        db.audit(principal, "node-test", nid, {"on": got.get("on")})
        return {"on": bool(got.get("on")), "why": got.get("why") or ""}

    verbs = {"vm-xml": vm_xml, "add": add, "update": update, "uninstall": uninstall,
             "drain": state, "online": state, "retire": state,
             "lock": lock, "unlock": lock, "enroll": enroll,
             "reboot": power, "poweroff": power, "gpu-display": gpu_display,
             "gpu-compute": gpu_compute,
             "config": config, "turns": turns,
             "test-workers": test_workers, "session-net": session_net,
             "root-asks": root_asks, "apply": apply, "to-sync": to_sync, "sync-stop": sync_stop,
             "host-only": host_on, "host-off": host_off,
             "door": lambda: node_door(principal, nid, req.get("on")),
             "sync-resume": sync_resume, "sync-clean": sync_clean, "runner": runner,
             "runner-token": runner_token, "runner-forget": runner_forget,
             "paths": paths, "check-paths": check_paths, "funnel": funnel,
             "update-agent": update_agent, "cache-clear": cache_clear,
             "exec": exec_, "test": test}
    if act not in verbs:
        return {"error": "unknown action"}, 400
    r = verbs[act]()
    return r if isinstance(r, tuple) else (r, 400 if r.get("error") else 200)

def run_job(name, req, principal):
    """`bb run`, `bb build` and `bb test` from the controller (docs/nodes.md
    §6), once server.py has let an administrator queue one for this
    project: snapshot the project's working tree, dirty edits included, and
    queue an exec on the project's node, or on the node named; `emu` runs a
    bb verb there from the bundle instead. Outputs are globs; what matches
    comes back into dist/. The principal is the session when the request
    says so, which is a label the credential cannot prove (bug #16) but is
    worth writing down. (payload, status)."""
    argv = [str(a) for a in (req.get("argv") or []) if str(a)][:64]
    if not argv:
        return {"error": "argv is empty"}, 400
    # `emu` (docs/nodes.md phase 9): a bb verb the node runs from the
    # bundle with its own toolchain store as the SDK: no snapshot, since
    # the emulator is not the tree's; inputs come from dist/ by name and
    # what it writes comes back the same way.
    emu = field(req, "action") == "emu"
    pf = project_prefs(name)
    # The node named, else the project's primary, else the first of its
    # set that is up (R82 step 6): a primary that is offline is a job
    # that runs elsewhere and says so, not a refusal.
    nid, fell_over = field(req, "node"), ""
    if not nid:
        nid, fell_over = first_up(pf.get("nodes") or ([pf["node"]] if pf["node"] else []))
    if not nid:
        return {"error": f"{name} has no node, so nothing can be compiled for it. "
                         + no_node_advice(name)}, 400
    n = node(nid)
    if not n:
        return {"error": f"no such node: {nid}"}, 400
    if n["kind"] != "agent":
        return {"error": f"{n['name']} runs no agent: a build node is an agent "
                         "node with a workspace of its own (docs/nodes.md §6)"}, 400
    # A node that visibly cannot run this is refused before the job is
    # queued rather than after it fails on "gradlew: not found", and the
    # two ways out are named. Only fires when the command NAMES a
    # toolchain the node's census does not report; an unknown build
    # script is left alone.
    gap = toolchain_gap(nid, argv)
    if gap:
        # How old that answer is, because the census rides hello every
        # ten minutes and a refusal can be reasoning about the node as
        # it was nine of them ago. The node has just been asked for a
        # fresh one, so the sentence says a retry may differ.
        age = census_age(nid)
        when = (f", as of what it reported {age // 60}m ago; it has been "
                "asked for a fresh answer, so a retry shortly may differ"
                if age and age > 90 else "")
        return {"error": f"{n['name']} has no {gap}{when}. Install it from the Toolchains tab "
                         f"with {n['name']} picked, "
                         + ("or push and let CI build it."
                            if may_push(name)
                            else f"or give {name} push rights and let CI build it; "
                                 "it has none, so there is no fallback here.")}, 400
    outputs = [str(g)[:200] for g in (req.get("outputs") or []) if str(g)][:16]
    try:
        timeout = min(4 * 3600, max(30, int(req.get("timeout") or 3600)))
    except (TypeError, ValueError):
        timeout = 3600
    who = f"session:{name}" if field(req, "from") == "session" else principal
    if emu:
        files, sizes = [], {}
        for f in (req.get("files") or [])[:8]:
            p = workspace.file_path(name, str(f))
            if p is None:
                return {"error": f"{f} is not a file in {name}'s dist/"}, 400
            files.append(str(f))
            # So the node can tell its own copy from a new build without
            # fetching it again (docs/nodes.md §6, the artifacts store).
            sizes[str(f)] = p.stat().st_size
        spec = {"bb": argv, "files": files, "sizes": sizes, "timeout": timeout,
                "outputs": outputs, "project": name}
        r = job_add(who, {"node": nid}, "exec", spec, name)
        if r.get("error"):
            return r, 400
        return r | {"node": nid}, 200
    snap = workspace.snapshot(name)
    if snap.get("error"):
        return snap, 400
    spec = {"argv": argv, "timeout": timeout, "outputs": outputs, "project": name}
    # A test run sits below the node's other work: the emulator, a docker
    # build and a session's own work keep the CPU when they want it (the
    # operator, 27 Sep). The agent puts nice in front of the command.
    if field(req, "role") == "test":
        spec["nice"] = 10
    if fell_over:
        spec["fell_over"] = fell_over      # the primary it stood in for (R82 step 6)
    r = job_add(who, {"node": nid}, "exec", spec, name,
                source={"digest": snap["digest"], "project": name,
                        "files": snap["files"], "bytes": snap["bytes"]})
    if r.get("error"):
        return r, 400
    return r | {"node": nid, "snapshot": snap["digest"], "files": snap["files"]}, 200


# The project a job belongs to when it is not the one it names: a container
# written for a project (bb container new --for) carries the container's own
# name as its project, and its owner is the record's. Set by server.py to
# devapp.owner_of; None reads every job as its own project's.
job_owner = None


def _job_mine(j, mine):
    """Whether this account sees a job: its project's, or one of a
    container that belongs to its project (B321)."""
    if j.get("project") in mine:
        return True
    return bool(job_owner) and job_owner(j) in mine


def jobs_view(jid, q, mine, system=None):
    """The Jobs tab's whole read surface, and a test's: one job with its log
    so far, or the recent ones narrowed by the query's node, project, type,
    active and n. `mine` is None for an administrator, or the projects this
    account may see: a job and its log are the project's, or its project's
    container's (B321), and a job with no project (a node's own: an update,
    a store move) is an administrator's, with the same answer as a typo so
    the listing says nothing about what else is queued on the box. With
    `system` (a redactor), the node's own jobs are seen as well, through it:
    the caller may read the controller's diagnostics, which list them. n counts
    what this account sees, not the node's last n before the filter, which
    showed one job of twelve and read as history pruned (B321).
    (payload, status)."""
    def seen(j):
        return _job_mine(j, mine) or (system is not None and not j.get("project"))

    def scrub(v):
        # Every string inside, the shape kept: bb jobs and the Jobs tab read
        # a spec's fields by name.
        if isinstance(v, str):
            return system(v)
        if isinstance(v, list):
            return [scrub(x) for x in v]
        if isinstance(v, dict):
            return {k: scrub(x) for k, x in v.items()}
        return v

    def shown(j):
        if mine is None or system is None or j.get("project") or _job_mine(j, mine):
            return j
        return {k: scrub(v) if k in ("log", "error", "label", "spec") else v for k, v in j.items()}
    if jid:
        j = job(jid)
        if j and mine is not None and not seen(j):
            j = None
        return (shown(j), 200) if j else ({"error": "no such job"}, 404)
    try:
        n = min(500, max(1, int(q.get("n", ["100"])[0])))
    except ValueError:
        n = 100
    rows = jobs_for(
        q.get("node", [""])[0] or None, n=500 if mine is not None else n,
        project=q.get("project", [""])[0] or None,
        type=q.get("type", [""])[0] or None,
        active=q.get("active", [""])[0] == "1")
    if mine is not None:
        rows = [shown(j) for j in rows if seen(j)][:n]
    # The names of the nodes these rows run on, and for an account that
    # is not an administrator no other: the whole registry rode here
    # past the scoping the nodes listing keeps (the probe of 26 Sep).
    names = {x["id"]: x["name"] for x in node_list(all=True)}
    if mine is not None:
        names = {k: v for k, v in names.items() if any(j.get("node") == k for j in rows)}
    return {"jobs": rows, "nodes": names}, 200


def tab_view(rows, admin):
    """The Nodes tab's read: the rows the server has scoped to this account
    (an account that may not change a node sees the ones its own projects
    build on), each agent's with its sessions' turns, and for an
    administrator the agent this controller ships, which rides beside the
    rows once so a row can say when its node's agent is behind, and the
    node the Docker tab opens on and New project offers (node_for). Not a
    default that work falls to: a project with no node has nowhere to send,
    and the dialogs make the person pick."""
    for n in rows:
        if n.get("kind") == "agent":
            n["turns"] = turns_of(n)
    return {"nodes": rows, "agent": agent_shipped() if admin else {},
            "default": node_for() if admin else ""}


def log_read_named(principal, asking_id, want, stream, lines, debug_on, grants=(), project=""):
    """node_log_read with the target named by id or by name, for a session
    the server has placed on `asking_id`, whose project may read `grants`.
    {..} or {error}."""
    tgt = node(want) or next((n for n in node_list() if n["name"] == want), None)
    return node_log_read(principal, asking_id, (tgt or {}).get("id") or want,
                         stream or "agent", lines or 200, debug_on=debug_on,
                         grants=grants, project=project)
