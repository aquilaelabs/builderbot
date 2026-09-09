#!/usr/bin/env python3
"""The node data plane: the database seam, the migrations, the node registry,
the audit trail — and, from phase 3, the agent channel: enrollment tokens,
node credentials, the heartbeat with its census, and the job rows an `exec`
job rides in on (docs/nodes.md §4, §9).

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
stops answering loses its jobs rather than holding them forever. The one-way
doors this module owns were paid in phase 1 so that could land without
reshaping anything (docs/nodes.md §15):

  * ids are minted, never addresses, never reused (door 1);
  * every mutation is attributed and audited from the first day there is a
    table to write it in (door 2);
  * the SQL runs on two engines behind numbered migrations from 0001 —
    parameters go through _q(), JSON is TEXT, ids and times are app-side
    (door 6);
  * nothing in the schema assumes one operator: pools, token kinds and
    principals are data, not booleans (door 8).

Storage is /config/builderbot.db unless DATABASE_URL says otherwise. SQLite
is the homelab default; a postgres:// URL is the enterprise seam (E1) and is
refused loudly until that phase is built, which beats accepting it and
half-working. The notebook's JSON files are NOT this module's business —
they are small, human-edited and read whole, and they stay where they are.
"""
import contextlib
import hashlib
import json
import os
import platform
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIGRATIONS = HERE / "migrations"

# The controller's own node id. Well-known rather than minted, from the brief:
# a single-container deployment must work with zero remote hosts, and `local`
# is the one id that may exist before any enrollment has ever happened.
LOCAL = "local"

STATE = None
_db = None
# One connection, one lock. sqlite3 serializes on its own, but a lock makes
# read-modify-write sequences whole — and it is the shape the postgres
# implementation will keep, so callers never learn a difference.
_lock = threading.RLock()


def configure(*, state):
    globals()["STATE"] = Path(state)
    _open()
    migrate()
    _seed_local()


def open_readonly(state):
    """Open the store to read it — no migration, no seeding, no writes.

    For `bb nodes` and anything else that looks without being the boot: a
    read-only caller mutating the store on its way in would make "look at
    the list" a write, and two processes racing the seed.
    """
    globals()["STATE"] = Path(state)
    _open()


# ---------------------------------------------------------------------------
# the engine seam

def _url():
    return (os.environ.get("DATABASE_URL") or "").strip()


def _open():
    global _db
    url = _url()
    if url and not url.startswith("sqlite:"):
        # The seam exists so this becomes a config change (docs/nodes.md §5);
        # accepting the URL before the engine is built would half-work, which
        # is worse than refusing with the phase that fixes it named.
        raise RuntimeError(
            f"DATABASE_URL={url.split('://')[0]}://… is not supported yet — "
            "SQLite is the built engine; Postgres is enterprise track E1")
    path = url[len("sqlite:"):].lstrip("/") if url else ""
    dbfile = Path("/" + path) if path else STATE / "builderbot.db"
    dbfile.parent.mkdir(parents=True, exist_ok=True)
    _db = sqlite3.connect(dbfile, check_same_thread=False)
    _db.row_factory = sqlite3.Row
    # WAL so the poll's reads never block a write; NORMAL is durable enough
    # for state that can be re-derived, and it is what keeps the fsync cost
    # off the request path.
    _db.execute("PRAGMA journal_mode=WAL")
    _db.execute("PRAGMA synchronous=NORMAL")


def _q(sql):
    """The paramstyle seam: written as `?`, translated per engine.

    SQLite wants qmark and postgres wants format. Trivial today and the whole
    point is that it stays trivial — every statement in this module goes
    through here, so the day E1 lands, this function and _open() are the diff
    rather than a hunt.
    """
    return sql


def _exec(sql, args=()):
    with _lock:
        cur = _db.execute(_q(sql), args)
        _db.commit()
        return cur


def _rows(sql, args=()):
    with _lock:
        return [dict(r) for r in _db.execute(_q(sql), args).fetchall()]


# ---------------------------------------------------------------------------
# migrations

def migrate():
    """Apply every migrations/NNNN_*.sql not yet applied, in order.

    Numbered files, run inside one transaction each, recorded in a table of
    their own — the same shape at both tiers, and the discipline door 6 hangs
    on. A migration that half-applied would leave the version unrecorded and
    the transaction rolled back, so boot either has a version or an error,
    never something in between.
    """
    with _lock:
        _db.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY, name TEXT NOT NULL,
            applied INTEGER NOT NULL)""")
        done = {r[0] for r in _db.execute(
            "SELECT version FROM schema_migrations").fetchall()}
        for f in sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            version = int(f.name[:4])
            if version in done:
                continue
            try:
                for stmt in _statements(f.read_text(encoding="utf-8")):
                    _db.execute(stmt)
                _db.execute(
                    "INSERT INTO schema_migrations (version, name, applied) "
                    "VALUES (?, ?, ?)", (version, f.name, int(time.time())))
                _db.commit()
            except sqlite3.Error:
                _db.rollback()
                raise


def _statements(text):
    """Split a migration into statements on blank-line boundaries, comments
    stripped — declared in 0001's header, so a migration that forgets reads
    its own contract at the top of the file it copied."""
    out, cur = [], []
    for line in text.splitlines():
        if line.strip().startswith("--"):
            continue
        if not line.strip():
            if cur:
                out.append("\n".join(cur))
                cur = []
            continue
        cur.append(line)
    if cur:
        out.append("\n".join(cur))
    return [s for s in out if s.strip()]


# ---------------------------------------------------------------------------
# ids

def mint(prefix):
    """n_9f2c41d7 — short, prefixed, unguessable enough to never collide in a
    table this size, and never derived from anything (door 1: an id that
    encodes a fact goes stale when the fact does)."""
    return f"{prefix}_{secrets.token_hex(4)}"


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
    """The nodes, JSON columns inflated. Retired rows are history — kept in
    the table (door 1: ids are never reused, and an old record must stay
    explicable) and left out of every list unless asked for. Each row also
    names the system job in flight on it, so the tab can say "applying"
    without a second fetch."""
    rows = [_live(_inflate(r)) for r in _rows(
        "SELECT * FROM nodes ORDER BY kind = 'local' DESC, created")]
    busy, inflight = {}, {}
    # Every job that has not finished, not only the system ones. A button
    # whose job type was not tracked here came back live on the repaint that
    # followed the press — pressing() greys it for the round trip, and then
    # the render put a fresh, enabled one in its place. Update agent did
    # exactly that, which is what the operator kept seeing.
    for j in _rows("SELECT id, node, type, spec FROM jobs WHERE "
                   "state IN ('queued', 'assigned', 'running')"):
        inflight.setdefault(j["node"], []).append({"id": j["id"], "type": j["type"]})
        if j["type"] != "system":
            continue
        try:
            busy[j["node"]] = {"id": j["id"], "what": json.loads(j["spec"]).get("apply", "")}
        except (ValueError, AttributeError):
            busy[j["node"]] = {"id": j["id"], "what": ""}
    # ...and the last system job that FINISHED on each, which is the only
    # account of an apply that did not work. Without it the operator pressed
    # Apply storage, the job ran, failed, and the section went straight back
    # to "4 changes to apply" — no sign an attempt had happened at all,
    # which reads as a button that does nothing. Bounded: the newest rows
    # are the only ones that could be anybody's last.
    done = {}
    for j in _rows("SELECT id, node, spec, state, error, ended FROM jobs "
                   "WHERE type = 'system' AND state IN ('succeeded', 'failed', "
                   "'canceled') ORDER BY ended DESC LIMIT 200"):
        if j["node"] in done:
            continue
        try:
            spec = json.loads(j["spec"])
        except (ValueError, TypeError):
            spec = {}
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
    return rows if all else [r for r in rows if r["state"] != "retired"]


def node(node_id):
    got = _rows("SELECT * FROM nodes WHERE id = ?", (node_id,))
    return _live(_inflate(got[0])) if got else None


# How long an agent may go unheard before its row says offline: three polls,
# so one slow answer or a controller restart is not an outage on the screen.
LIVE_S = 3 * 25


def _live(rec):
    """Liveness is derived, never stored. The `state` column is the
    OPERATOR's intent — online, draining, retired, pending — and whether an
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
    # and append-only — dropping one is a one-way door across two engines for
    # a cosmetic gain — so it is written rather than special-cased away.
    cols = ("id", "name", "kind", "pool", "created", "state", "concurrency",
            "ssh_addr", "os", "arch", *_JSON_COLS)
    vals = [json.dumps(rec.get(c, {})) if c in _JSON_COLS
            else rec.get(c, "") if c in ("os", "arch") else rec.get(c)
            for c in cols]
    _exec(f"INSERT INTO nodes ({', '.join(cols)}) VALUES "
          f"({', '.join('?' * len(cols))})", vals)


STORE_ID_FILE = ".bb-store-id"

# Where this container keeps its toolchains. `bb sdk root` is the authority
# and packages.py asks it, but nodes.py is imported at boot before any of
# that and must not shell out on the seed path — so the same two answers bb
# itself resolves between, in the same order.
def sdk_root_of_controller():
    r = (os.environ.get("SDK_ROOT") or "").strip()
    if r:
        return r
    return "/sdk" if os.path.isdir("/sdk") else ""


def store_id(path, make=True):
    """A stable id for the store at `path`, from a marker inside it.

    Two machines mounting one share have no way to recognize each other by
    path: this container reaches the package store through Unraid's FUSE layer
    (fstype fuse.shfs, source "shfs") while a node reaches the same bytes
    over NFS (192.168.1.10:/mnt/user/development/SDK). Neither string can be
    derived from the other without knowing it is Unraid, so pairing on the
    mount was never going to work here — measured on this box, 3 Sep.

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
        # believe they created it — the loser reads the winner's.
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
    10c): the image carries no JDK and no Android SDK, so package-build —
    which this box used to demonstrably do — is a node's; docker-host was
    never here (the local node is not a sandbox, docs/nodes.md §12). The row
    stays so the controller is recognized as sharing a store with a node,
    and so a selector job can still be placed here on purpose.
    """
    reported = {
        "cpu": os.cpu_count() or 0,
        "mem_mb": _mem_mb(),
        "os": f"{platform.system().lower()} {platform.machine()}",
    }
    # This container's own packages store, reported like any node's — without
    # it the controller could not be recognized as sharing a store with a
    # node, so the "one install at a time across all of them" arbitration
    # never engaged for the pair that most obviously needs it: the package store,
    # mounted here and on the sandbox at once.
    root = sdk_root_of_controller()
    if root:
        st = {"path": root, "id": store_id(root)}
        with contextlib.suppress(OSError):
            u = os.statvfs(root)
            st["free_mb"] = int(u.f_bavail * u.f_frsize / 1048576)
            st["total_mb"] = int(u.f_blocks * u.f_frsize / 1048576)
        reported["stores"] = {"packages": st}
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
    """What this container's paths are called on the node's machine — the
    daemon resolves bind sources over there. {} when nothing is set."""
    n = node(node_id) if node_id else None
    p = (n.get("config") or {}).get("paths") if n else None
    return dict(p) if isinstance(p, dict) else {}


def node_paths_set(principal, node_id, text):
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] == "local":
        return {"error": "local's paths are its own — there is nothing to map"}
    paths, why = parse_paths(text)
    if why:
        return {"error": why}
    cfg = dict(n.get("config") or {})
    cfg["paths"] = paths
    _exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(cfg), node_id))
    _touch(node_id, principal, "node-paths", {"n": len(paths)})
    return {"ok": True, "paths": paths}


def node_for(capability=None):
    """The default node for work nobody bound to one — the newest enrolled,
    else local. `capability` is ignored and kept for the call sites that
    still name one: a node does everything now, so there is nothing to
    narrow by (2 Sep). What a project can do on its node is what is
    installed there, and the project names the node."""
    try:
        # The newest node with a REACHABLE daemon — docker_nodes() already
        # drops the ones there is no way into. "Newest online" was not
        # enough: an agent node that has never dialed in has no address, so
        # it can hold a project's containers only in principle, and picking
        # it left the manager talking to nothing.
        got = [n for n in docker_nodes() if n["kind"] != "local"]
        if got:
            return sorted(got, key=lambda n: n["created"])[-1]["id"]
    except sqlite3.Error:
        pass                     # a broken store falls back to the answer
    return LOCAL                 # that was always true before it existed


# ---------------------------------------------------------------------------
# mutations — phase 2: the Nodes tab's verbs. Every one writes an audit row
# with the principal the server hands it, because these ARE the mutations the
# audit table was built ahead of.

# What the tab may toggle. An unknown capability is refused rather than
# stored: the scheduler will one day place work on these strings, and a typo
# that sits in the table until then is a job that never places.
# What a node may be asked to do. NOT a setting any more (2 Sep): every node
# gets all of it at enrollment, because a project names one node and that node
# does everything for it — what the project can actually do there is what is
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
    QUIET writes nothing — the count of live nodes is folded in so that its
    row goes grey without anyone touching the store."""
    return f"{_rev[0]}.{sum(1 for n in node_list() if n.get('live'))}"


def _bump():
    _rev[0] += 1


def _touch(node_id, principal, action, fields):
    audit(principal, action, node_id, fields)
    _bump()


def node_add(principal, name, ssh_addr, capabilities=None, pool="default"):
    """Gone (roadmap #18): a node is enrolled with a token, and only with a
    token. It stayed until compose could run on the agent, because until
    then a node still needed an ssh key on top of its token for docker —
    which meant two enrollments for one machine, and a token-only node (the
    cloud case) could take every job EXCEPT docker. Compose is an agent job
    now and proved on a real VM, so the key buys nothing and the second
    enrollment can go.

    Kept as a refusal rather than deleted so the endpoint answers with the
    way in rather than a 404.
    """
    return {"error": "ssh nodes are gone — enroll the machine with a token "
                     "instead: Enroll node mints one, and provision.sh "
                     "--controller URL --token bbe_… on the machine does the "
                     "rest. It needs no key from this container, and it then "
                     "takes every kind of job, docker included."}


def node_update(principal, node_id, fields):
    """Rename, re-pool, relabel, set concurrency, and (for a deliberately
    restricted node, which nothing in the UI makes) capabilities —
    the editable half of a row. Never the id, the kind or the address: an
    address is an identity question, and the answer to "this node moved"
    is a new node (door 1), not an edit that makes old records lie."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    sets, args = [], []
    if "name" in fields:
        sets.append("name = ?"); args.append(str(fields["name"]).strip()[:60])
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
    if not sets:
        return {"error": "nothing to change"}
    args.append(node_id)
    _exec(f"UPDATE nodes SET {', '.join(sets)} WHERE id = ?", args)
    _touch(node_id, principal, "node-update", fields)
    return {"ok": True}


def node_state(principal, node_id, state):
    """Drain and undrain — and retire, which is what Remove means: rows
    are history and an id is never reused, so a removed node keeps its row
    and leaves every list (door 1)."""
    if state not in ("online", "draining", "retired"):
        return {"error": "state is online, draining or retired"}
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] == "local" and state == "retired":
        return {"error": "the local node is this container — it cannot be "
                         "removed, only left with nothing to do"}
    if state == "online" and n["state"] == "pending":
        return {"error": "a pending node comes online by enrolling"}
    _exec("UPDATE nodes SET state = ? WHERE id = ?", (state, node_id))
    if state == "retired":
        # A retired node's agent keeps dialing in until somebody stops the
        # unit; its credential failing closed is what tells it — and the
        # operator — that "removed" meant it (docs/nodes.md §4, rotation
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
        return (f"system changes on {n['name']} are locked to its own console — "
                "its mounts, address and root are managed at the OS level; Unlock "
                "under Advanced on the Nodes tab to change that")
    return ""


def node_revoke(principal, node_id):
    """Cut an agent node's credential without retiring it. The row stays,
    the agent's next call fails closed with 'credential revoked', and the
    way back is a fresh enrollment token — which is to say, a new row: a
    node whose secret was compromised is a node whose identity was, and
    the id is not reissued."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "only an agent node holds a credential to revoke"}
    revoke_tokens(node_id)
    ag = n.get("agent") or {}
    ag["revoked"] = int(time.time())
    _exec("UPDATE nodes SET agent = ? WHERE id = ?", (json.dumps(ag), node_id))
    _touch(node_id, principal, "node-revoke", {})
    return {"ok": True}


def docker_nodes():
    """The docker-host nodes, for every picker — active ones with somewhere
    to send docker to. An agent node that has never dialed in has no known
    address yet, so it is not offered: the picker's job is to name daemons
    the manager can reach, and a row with no way in would be a row that
    only ever says 'no answer'."""
    # Every node with a way in. Not narrowed by capability any more — a node
    # does everything — so the two exclusions left are the honest ones: a
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

    It is no longer how a compose action reaches the node — that is a job
    on the agent — but a row still shows where the node answered from.
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
# tokens — phase 3. Two kinds, one table (door 8: the kind is data).
#
# An ENROLL token is minted by the operator, bound to a node row created
# pending for it, and burned by the one enrollment it admits. A NODE token is
# what enrollment hands back: the bearer credential every later call carries.
# Only the sha256 of a secret is stored, so the table is worthless to read;
# the secret itself is shown exactly once, at mint, and never again.
#
# Secrets are self-describing — bbe_… enrolls, bbn_… is a node — so the
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

def enroll_mint(principal, name, capabilities=None, user="bb"):
    """Add node, agent kind: a pending row and the one token that fills it.

    The row exists BEFORE the machine does, which is the operator's view of
    "waiting for enrollment" — a line on the tab with the command to paste —
    and it is where the token's scope lives: the capabilities the controller
    intended are on the row, so enrollment adds nothing the operator did not
    ask for. The id is minted now and kept; a token that expires unused
    leaves a pending row the tab offers to remove, never a reused id.
    """
    name = (name or "").strip()[:60] or "node"
    caps = [c for c in (capabilities or CAPABILITIES) if c in CAPABILITIES]
    user = re.sub(r"[^a-z0-9_-]", "", (user or "bb").lower())[:32] or "bb"
    nid = mint("n")
    _insert_node({
        "id": nid, "name": name, "kind": "agent",
        "pool": "default", "created": int(time.time()), "state": "pending",
        "concurrency": 1, "ssh_addr": "",
        "capabilities": caps, "services": {},
        "labels": {"disposable": "true"},
        "agent": {}, "reported": {}, "routing": {},
        "config": {"user": user},
    })
    tid, secret = _token_mint("enroll", nid, ENROLL_TTL)
    _touch(nid, principal, "node-enroll-mint", {"token": tid, "caps": caps})
    return {"ok": True, "id": nid, "token": secret,
            "expires": int(time.time()) + ENROLL_TTL}


def enroll(auth, census, addr, version="", digest="", user=""):
    """The one call an enroll token admits: burn it, issue the node token,
    bring the row online. `auth` is authenticate()'s answer for the token."""
    nid = auth["node"]
    n = node(nid)
    if not n or n["state"] != "pending":
        return {"error": "this node is not waiting for enrollment"}
    revoke_tokens(nid, ("enroll",))
    _exec("UPDATE tokens SET uses = uses + 1 WHERE id = ?", (auth["token"],))
    tid, secret = _token_mint("node", nid)
    cfg = n.get("config") or {}
    if user:
        cfg["user"] = re.sub(r"[^a-z0-9_-]", "", user.lower())[:32] or "bb"
    rep = _census(census)
    _exec("UPDATE nodes SET state = 'online', agent = ?, reported = ?, "
          "config = ?, os = ?, arch = ? WHERE id = ?",
          (json.dumps({"token_id": tid, "version": str(version)[:40],
                       "digest": str(digest)[:80], "addr": addr,
                       "last_seen": int(time.time()), "protocol": PROTOCOL}),
           json.dumps(rep), json.dumps(cfg), rep["system"], rep["arch"], nid))
    _touch(nid, auth["principal"], "node-enroll", {"addr": addr})
    return {"ok": True, "node_id": nid, "token": secret,
            "name": n["name"], "capabilities": n["capabilities"],
            "user": cfg.get("user", "bb"), "protocol": PROTOCOL, "poll": POLL_S}


# ---------------------------------------------------------------------------
# the channel: hello, and the long-poll that carries the heartbeat
#
# Protocol 1, long-poll only (docs/nodes.md §4): the agent POSTs `work` with
# its current sample and the request is held until there is a job for it or
# the poll window closes — so one request per node per POLL_S is the whole
# cost of liveness, metrics and job pickup together. The design wrote the
# poll as a GET; a heartbeat is a body, and a GET with a body is not a thing,
# so the verb is POST and the doc was corrected to say so.

# Superseded by the agent's version window (its WINDOW.BUILD constant, and
# agent_window() below): this number was declared 1 on both sides and never
# compared by either, which is why compatibility now rides on a number that
# means something. Still sent, because removing a field the other side may
# read is itself the kind of break the window exists to schedule — it goes at
# 0.5.0.
PROTOCOL = 1


def agent_window(version):
    """The compatibility window a version string promises — "0.4" of "0.4.27".

    Empty for anything that is not WINDOW.BUILD, which includes every agent
    built before the window existed. Empty means "cannot say", and every
    caller reads it that way rather than guessing: an old agent is stale for
    the ordinary reason (a different digest) and does not need a second,
    louder claim made up about it.
    """
    m = re.match(r"^(\d+\.\d+)\.", str(version or ""))
    return m.group(1) if m else ""
# Held below the 30s most proxies allow. Settable only so the suite can stop
# waiting on it: an agent does its housekeeping — restarting a ttyd that died,
# reporting a session that appeared — once per turn of this loop, so a test
# that watches for any of it waits a poll window per thing it watches, and
# three of them were the slowest intervals in the suite. Nothing else sets it.
POLL_S = int(os.environ.get("BB_NODE_POLL") or 25)
_wake = threading.Condition(_lock)
# The last minute of samples per node, for a sparkline (docs/nodes.md §9):
# memory only, and lost on restart, which is the honest scope — the row keeps
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
    except (TypeError, ValueError):
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
    for k in ("os", "docker", "gpu", "hostname"):
        if c.get(k):
            out[k] = str(c[k])[:120]
    # The two placement dimensions (door 9), as fields. An older agent sends
    # only the `os` string, whose first two words are the same two facts.
    words = (out.get("os") or "").split()
    out["system"] = re.sub(r"[^a-z0-9]", "", str(c.get("system") or
                           (words[0] if words else "")).lower())[:20]
    out["arch"] = re.sub(r"[^a-zA-Z0-9_]", "", str(c.get("arch") or
                         (words[1] if len(words) > 1 else "")))[:20]
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
                # is how the pair stays invisible — the same way store_dirs
                # was lost before it was whitelisted.
                "id": str(s.get("id") or "")[:64],
                "free_mb": _mb(s.get("free_mb")),
                "total_mb": _mb(s.get("total_mb")),
                # What the store holds, from the census's du (phase 6): the
                # cache's number beside Clear cache. None when not measured.
                "used_mb": _mb(s.get("used_mb")),
                # The node's own directory in the store — linux-x86_64,
                # darwin-arm64 (roadmap R19); "" from an agent before it.
                "scope": re.sub(r"[^A-Za-z0-9_-]", "", str(s.get("scope") or ""))[:40]}
    # {name: version} from `bb sdk versions` on the node — the controller's
    # own generator, run there. Whitelisted like store_dirs, and for the same
    # reason: a value the agent reports and this drops is a value that does
    # not exist.
    pv = c.get("packages_versions") if isinstance(c.get("packages_versions"), dict) else {}
    out["packages_versions"] = {str(k)[:40]: str(v)[:40] for k, v in list(pv.items())[:40]}
    sd = c.get("store_dirs") if isinstance(c.get("store_dirs"), dict) else {}
    out["store_dirs"] = {k: [str(x)[:60] for x in (sd.get(k) or [])[:64]]
                         for k in ("top", "android", "incomplete")}
    # The android system images in the packages store, and the AVDs built on
    # each (roadmap #20). Whitelisted like store_dirs and packages_versions,
    # and for the same reason: a field the agent reports and this drops is a
    # field that does not exist. Absent rather than empty when the agent did
    # not send it at all: an agent too old to report images is not a node with
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
    # the node was provisioned as a sandbox (bb-sandbox is there — the stamp
    # system jobs are gated on), what it mounts as bb-sandbox reads it, and
    # the address it is on. Facts about the machine, drawn against the
    # operator's desired config on the row; never treated as the config.
    out["sandbox"] = bool(c.get("sandbox"))
    out["mounts"] = []
    for m in (c.get("mounts") if isinstance(c.get("mounts"), list) else [])[:32]:
        if isinstance(m, dict) and str(m.get("path") or "").startswith("/"):
            out["mounts"].append({
                "path": str(m["path"])[:200], "source": str(m.get("source") or "")[:200],
                "type": str(m.get("type") or "")[:16], "ro": bool(m.get("ro")),
                "mounted": bool(m.get("mounted")), "real": str(m.get("real") or "")[:200]})
    sv = c.get("services") if isinstance(c.get("services"), dict) else {}
    ar = sv.get("actions-runner") if isinstance(sv.get("actions-runner"), dict) else {}
    out["services"] = {"actions-runner": {
        "installed": bool(ar.get("installed")), "active": bool(ar.get("active")),
        "busy": bool(ar.get("busy")), "name": str(ar.get("name") or "")[:80],
        "url": str(ar.get("url") or "")[:200],
        "labels": [re.sub(r"[^A-Za-z0-9._-]", "", str(x))[:40]
                   for x in (ar.get("labels") or [])[:16] if str(x)]}}
    ts = sv.get("tailscale") if isinstance(sv.get("tailscale"), dict) else {}
    fun = ts.get("funnel") if isinstance(ts.get("funnel"), dict) else {}
    out["services"]["tailscale"] = {
        "installed": bool(ts.get("installed")),
        "dns": re.sub(r"[^A-Za-z0-9.-]", "", str(ts.get("dns") or ""))[:200],
        # https port -> the local port it forwards to, as the node reports it
        "funnel": {str(k)[:6]: _mb(v) for k, v in list(fun.items())[:8]}}
    # The session half (roadmap #24): whether this node runs sessions, on
    # which ports, as which account, and whether the projects share is
    # mounted where they expect it. Absent — not empty — from an agent too
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
            # Absent from an agent that predates the probe; the proxy reads
            # None as "not known", not as read-only.
            "writable": None if "writable" not in se else bool(se.get("writable")),
            "claude": str(se.get("claude") or "")[:40],
            "bundle": str(se.get("bundle") or "")[:80],
            # The agent's own sentence for a half that is down — no session
            # account, no ttyd, a port taken — which the row's dead button
            # repeats. Dropped once, and the button said only "runs none yet".
            "why": str(se.get("why") or "")[:120],
            # The node's own boot id, which a terminal's URL has to carry for
            # a session THERE (bb-tty compares against the machine it runs
            # on); the row hands it to the page per project.
            "boot": re.sub(r"[^0-9.]", "", str(se.get("boot") or ""))[:40]}
    net = c.get("network") if isinstance(c.get("network"), dict) else {}
    out["network"] = {
        "interface": str(net.get("interface") or "")[:32],
        "addresses": [str(a)[:64] for a in (net.get("addresses") or [])[:8]],
        "gateway": str(net.get("gateway") or "")[:64],
        "dns": [str(a)[:64] for a in (net.get("dns") or [])[:8]]}
    # The machine's own tools, as the agent detected them: its package
    # manager and the service that owns its network. A system job's spec is
    # the same for every node; this says what the agent there would turn it
    # into, so the row can say so — and absent from an agent that predates
    # the detection, which the row reads as "not reported", not as none.
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
# agent runs as root — audited like any mutation, offered only to nodes that
# enrolled as a sandbox, refused on the node without the stamp as well.
# bb-sandbox at the console reads and writes the same on-node state, so the
# GUI and a rescue shell cannot disagree about what the node is meant to be.

MOUNT_TYPES = ("nfs", "virtiofs")
STORE_ROLES = ("data", "packages", "cache", "artifacts")
# The same refusal the agent makes of a store path, made here so the tab says
# no before anybody presses. Deliberately in both places: a store is a
# directory this system creates, fills and — for the cache — empties, so one
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
        return (f"{p} is a system directory (or the root of the mounts) — a store "
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
    page — the agent writes what arrives into fstab and into whichever
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
            # Only a default — /workspace has to stay /workspace for path
            # parity with the controller, so anything that matters is typed.
            tail = src.rsplit("/", 1)[-1] if kind == "nfs" else src
            tail = re.sub(r"[^A-Za-z0-9._-]", "", tail).strip(".")
            if not tail:
                return None, f"nothing to name a mountpoint after in {src!r} — type one"
            path = "/mnt/" + tail
        if not path.startswith("/") or " " in path or ":" in path:
            return None, f"a mountpoint must be an absolute path without spaces: {path!r}"
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
            return None, f"a static address is written with its prefix, like 10.0.0.12/24 — not {addr!r}"
        if gw and not _IP.match(gw):
            return None, f"the gateway is an address, not {gw!r}"
        dns = [d.strip() for d in (net.get("dns") if isinstance(net.get("dns"), list)
                                   else str(net.get("dns") or "").split(",")) if d.strip()]
        for d in dns:
            if not _IP.match(d):
                return None, f"a resolver is an address, not {d!r}"
        n.update(address=addr, gateway=gw, dns=dns[:4])
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
        return {"error": "only an agent node has a configuration plane — "
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


DEFAULT_RUNNER_LABELS = ("builderbot", "self-hosted", "linux")


def runner_labels_for(n, labels=None):
    """The labels a node's runner carries: the defaults, its architecture,
    and its own name — the per-node label that lets a workflow's runs-on
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


def node_runner(principal, node_id, want, labels=None, url=""):
    """Install or remove the Actions runner on a node, as a system job
    (phase 7). The desired state — wanted or not, with which labels — lives
    in the node's services column; the census reports what is there."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "the runner is installed by the agent — an ssh node has none"}
    # No sandbox stamp needed (roadmap #23): a runner is a tarball and a
    # token, not a change to the machine, so a container node or a guest
    # gets one too. Storage and network keep the stamp — node_apply.
    if n["state"] != "online":
        return {"error": f"the node is {n['state']} — system jobs go to an online node"}
    if system_job_for(node_id):
        return {"error": "a system job is already in flight on this node — one at a time"}
    if want and not str(url or "").startswith("https://github.com/"):
        return {"error": "the runner registers with a GitHub org or repo URL — set GITHUB_URL "
                         "on the controller, or type one"}
    labs = runner_labels_for(n, labels) if want else []
    services = dict(n.get("services") or {})
    services["actions-runner"] = {"want": bool(want), "labels": labs, "url": str(url or "")[:200]}
    _exec("UPDATE nodes SET services = ? WHERE id = ?", (json.dumps(services), node_id))
    _touch(node_id, principal, "node-runner", {"want": bool(want), "labels": labs})
    cfg = {"want": bool(want), "labels": labs, "url": str(url or ""), "name": n["name"]}
    return job_add(principal, {"node": node_id}, "system",
                   {"apply": "runner", "config": cfg, "timeout": 1800})


def route_host(node_id):
    """The host a published port on this node is reached at from the LAN:
    the address the node last dialed in from. '' for local and the unknown."""
    n = node(node_id)
    if not n or n["kind"] == "local":
        return ""
    a = (n.get("agent") or {}).get("addr") or ""
    a = re.sub(r"^[a-z][a-z0-9+.-]*://", "", a)
    a = a.split("@")[-1].split("/")[0].split(":")[0]
    return a


def node_funnel(principal, node_id, port, on=True):
    """Tailscale Funnel on a node (docs/nodes.md §7, mode `funnel`): a
    public HTTPS URL for one published port, with no DNS, certificate or
    firewall change — as a system job the agent applies with tailscale's
    own CLI. One funnel per node, on 443: the node's MagicDNS name is the
    URL, and a second instance asking replaces the first, said plainly."""
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "a funnel needs the agent — this node runs none"}
    # Like the runner, no sandbox stamp: tailscale's own CLI does the work.
    ts = ((n.get("reported") or {}).get("services") or {}).get("tailscale") or {}
    if not ts.get("installed"):
        return {"error": f"{n['name']} has no tailscale — install and log it in on the node first"}
    if n["state"] != "online":
        return {"error": f"the node is {n['state']} — system jobs go to an online node"}
    if system_job_for(node_id):
        return {"error": "a system job is already in flight on this node — one at a time"}
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

    A controller is always newer than or equal to its nodes — it is where
    the agent file comes from — so a mismatch means the node may not
    understand a job this version would send it. Job types and spec fields
    have been added on nearly every phase (system, package, cache-clear,
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
        return (f"{n['name']} runs agent {mine} and this controller ships {ours['version']} — "
                f"a different compatibility window ({agent_window(mine)} against "
                f"{agent_window(ours['version'])}), so nothing sent to it is promised to work. "
                "Update it from the Nodes tab before relying on this node.")
    return (f"{n['name']} runs agent {mine} and this controller ships {ours['version']} — "
            "press Update agent on its row first. A job this version sends could name "
            "something that agent does not know.")


def agent_gap(n):
    """True when this node's agent is from ANOTHER compatibility window than
    the one this controller ships — 0.3 against 0.4. Inside a window any
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
        # that reason first, and Update agent could not reach it anyway — an
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
    """Queue the self-update for a node's agent — the file this controller
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
    version only — the body is the download verb's."""
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
    node's census does not report — an unknown build script is not refused,
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
    """The label that pins a workflow's runs-on to THIS node's runner — its
    own name, cleaned the way runner_labels_for cleans it.

    "" when the node has no runner installed or asked for: advising a
    runs-on that nothing answers is the "Waiting for a runner" strand this
    exists to prevent, and an empty answer is how the caller knows to say
    nothing rather than to say something wrong.
    """
    n = node(node_id)
    if not n:
        return ""
    rep = ((n.get("reported") or {}).get("services") or {}).get("actions-runner") or {}
    want = (n.get("services") or {}).get("actions-runner") or {}
    if not (rep.get("installed") or want.get("want")):
        return ""
    return re.sub(r"[^A-Za-z0-9._-]", "-", n["name"])[:40]


def runner_labels_known():
    """Every label a runner in the registry carries, reported or wanted, for
    the lint that checks a workflow's runs-on against what exists."""
    out = set()
    for n in node_list():
        rep = ((n.get("reported") or {}).get("services") or {}).get("actions-runner") or {}
        out.update(rep.get("labels") or [])
        want = (n.get("services") or {}).get("actions-runner") or {}
        if want.get("want"):
            out.update(want.get("labels") or [])
    return sorted(out)


def system_job_for(node_id):
    """The system job in flight for a node, if any: one at a time, because
    two applies racing on one fstab is not a state anybody wants."""
    for j in jobs_for(node_id=node_id, type="system", active=True, n=5):
        return j
    return None


def apply_cfg(desired, what):
    """The half of a desired config an apply of `what` carries. Its own
    function because node_list compares a finished job's spec against it to
    decide whether that job is still about the record as it stands — and a
    second copy of this shape would make a stale failure look current, or
    the other way about, whenever either moved."""
    desired = desired or {}
    if what == "storage":
        return {"mounts": desired.get("mounts") or [], "stores": desired.get("stores") or {}}
    if what == "network":
        return {"network": desired.get("network") or {}}
    return None


def node_apply(principal, node_id, what):
    """Queue the system job that makes the node match its desired config —
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
        return {"error": f"the node is {n['state']} — system jobs go to an online node"}
    if (n.get("agent") or {}).get("revoked"):
        return {"error": "this node's credential was revoked"}
    if node_locked(n):
        return {"error": node_locked(n)}
    desired = (n.get("config") or {}).get("desired") or {}
    if not desired:
        return {"error": "nothing to apply — save a configuration first"}
    if system_job_for(node_id):
        return {"error": "a system job is already in flight on this node — one at a time"}
    cfg = apply_cfg(desired, what)
    # A storage apply that repoints a store copies what is in it first, and a
    # packages store is tens of gigabytes: fifteen minutes is the right ceiling
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


# Set by server.py at boot, because packages.py imports this one and the
# catalog is its business, not the registry's. Absent (an older controller,
# or a store that did not open) simply means the node keeps its built-in
# answer.
layout_of = lambda: []
bundle_digest = lambda: ""
idle_minutes = lambda: 0            # noqa: E731 — idle.minutes, injected by server.py


def hello(nid, census, addr, version="", digest="", running=None):
    """The agent on connect: refresh the census, record the version it is
    running, and answer with what the controller expects of it — protocol,
    transports, the poll window, the node's own capabilities (so it can
    refuse outside them, door 7) and the controller's agent file digest
    (so self-update is a comparison, door 4).

    `running` is the jobs the agent has going right now. An agent that
    restarted has none, and the rows this side still had as running there
    are then failed as lost — a subprocess does not survive its parent, so
    a row saying otherwise would say it forever."""
    n = node(nid)
    if not n:
        return {"error": "no such node"}
    if isinstance(running, list):
        jobs_reconcile(nid, [str(j) for j in running])
    ag = n.get("agent") or {}
    ag.update({"version": str(version)[:40], "digest": str(digest)[:80],
               "addr": addr, "last_seen": int(time.time()),
               "protocol": PROTOCOL})
    rep = n.get("reported") or {}
    sample = rep.get("sample")
    # When this census was taken. The heartbeat is every 25 seconds but the
    # census only rides hello, every ten minutes, so "when did the node last
    # dial in" is not the same question as "how old is this answer" — and it
    # is the second one a refusal is reasoning from.
    census_at = int(time.time())
    rep = _census(census)
    rep["at"] = census_at
    if sample:
        rep["sample"] = sample
    _exec("UPDATE nodes SET agent = ?, reported = ?, os = ?, arch = ? "
          "WHERE id = ?", (json.dumps(ag), json.dumps(rep), rep["system"],
                           rep["arch"], nid))
    _bump()
    ours = agent_file()
    return {"ok": True, "protocol": PROTOCOL, "transports": ["longpoll"],
            "poll": POLL_S, "node": {"id": nid, "name": n["name"],
                                     "state": n["state"],
                                     "capabilities": n["capabilities"],
                                     "concurrency": n["concurrency"]},
            "agent": {"digest": ours["digest"], "version": ours["version"]},
            # Where every package lands, from the catalog — the node has no
            # catalog of its own, and this is what stops it keeping a second
            # copy of the answer that drifts from ours.
            "layout": layout_of() or None,
            # The bb bundle's digest (roadmap #24): a node keeps an unpacked
            # copy for the sessions it runs, and refreshes it when this moves.
            "bundle": bundle_digest() or "",
            # The idle rule for Claude sessions (idle.py): the node enforces
            # it itself, so it holds while this controller is down.
            "session_idle_minutes": idle_minutes()}


def heartbeat(nid, sample, addr, running=0):
    """One sample per poll: the numbers the operator actually wants to see,
    riding the channel that exists anyway. Written to the row (current
    value) and to the ring (the last minute); last_seen is what liveness
    reads. The address is refreshed too — see _addr."""
    n = node(nid)
    if not n:
        return
    s = sample if isinstance(sample, dict) else {}
    clean = {"at": int(time.time())}
    for k in ("cpu_pct", "load1", "mem_used_mb", "mem_mb"):
        with contextlib.suppress(TypeError, ValueError):
            clean[k] = round(float(s.get(k) or 0), 1)
    clean["running"] = int(running or 0)
    stores = s.get("stores") if isinstance(s.get("stores"), dict) else {}
    clean["stores"] = {str(r)[:20]: _mb((v or {}).get("free_mb"))
                       for r, v in list(stores.items())[:8]}
    ag = n.get("agent") or {}
    ag["last_seen"] = clean["at"]
    if addr:
        ag["addr"] = addr
    rep = n.get("reported") or {}
    rep["sample"] = clean
    # The node's tmux sessions (roadmap #24), for the Sessions card: name,
    # whether a client is attached, the active pane's directory and title
    # (a Claude session reports its state through the title). Whitelisted
    # like everything a node says; absent when the agent did not send it.
    if isinstance(s.get("sessions"), list):
        rep["sessions"] = []
        for row in s["sessions"][:64]:
            if not isinstance(row, dict):
                continue
            name = re.sub(r"[^A-Za-z0-9_~.:-]", "", str(row.get("name") or ""))[:120]
            if not name:
                continue
            rep["sessions"].append({
                "name": name, "attached": bool(row.get("attached")),
                "cwd": str(row.get("cwd") or "")[:300],
                "title": str(row.get("title") or "")[:200]})
    for role, free in clean["stores"].items():
        if role in rep.get("stores", {}):
            rep["stores"][role]["free_mb"] = free
    _exec("UPDATE nodes SET agent = ?, reported = ? WHERE id = ?",
          (json.dumps(ag), json.dumps(rep), nid))
    ring = _samples.setdefault(nid, [])
    ring.append(clean)
    del ring[:-SAMPLES_KEEP]
    # Every sample moves the numbers on the row, and the row is the only
    # place they are shown: one repaint per node per poll is the cost.
    _bump()


def samples(nid):
    return list(_samples.get(nid, []))


# ---------------------------------------------------------------------------
# jobs — the queue (docs/nodes.md §2, phase 4)
#
# The queue is a list and placement is a function. A job names a node or a
# selector; a node with a free slot takes the oldest queued job it fits, and
# from then on the row says where it ran, not where it might have. There are
# two kinds of runner: an AGENT takes its jobs over the channel (exec and
# self-update), and the CONTROLLER runs the rest itself — compose actions
# against a node's daemon, and exec on the nodes that have no agent (local,
# ssh). Both ask the same question of the same table through job_next(), and
# concurrency is counted here from the rows rather than trusted from either.

# exec runs argv; compose is the controller's docker; self-update, system
# (phase 5), package (a toolchain install against the node's packages store)
# and cache-clear (drop the node's build caches) are the agent's own.
JOB_TYPES = ("exec", "self-update", "compose", "system", "package", "cache-clear")
JOB_END = ("succeeded", "failed", "canceled")
JOB_ACTIVE = ("queued", "assigned", "running")
# What a selector may name (door 9: os and arch are placement dimensions).
SELECT_KEYS = ("capability", "labels", "pool", "os", "arch")
_jrev = [0]
# type -> what to run on the controller when a job of that type ends,
# registered by the module that queues them (devapp for compose).
ON_DONE = {}


def on_done(job_type, fn):
    ON_DONE[job_type] = fn


def jobs_rev():
    """Bumped on every job mutation and every log chunk; /api/revs carries
    it so the Jobs tab and the rows that watch a job refetch on change."""
    return _jrev[0]


def _jbump():
    _jrev[0] += 1


def runner_of(job_type, kind):
    """Who executes a job of this type on a node of this kind.

    An agent runs everything for itself, compose included: the node's own
    docker, on the node, so the token it enrolled with is the only way in and
    the controller needs no ssh key. Only `local` is left here, and only
    because it IS here — the ssh kind, which used to leave compose on the
    controller over an ssh key, is gone (roadmap #24).
    """
    return "controller" if kind == "local" else "node"


def fits(job, n):
    """Placement, in one place: may this node take this job. An explicit
    node is exact; a selector is every key it names, all of which must hold.
    Nothing here about load — first free slot wins, which is the whole
    scheduling policy a single operator needs (docs/nodes.md §2)."""
    if n["state"] != "online" or (n.get("agent") or {}).get("revoked"):
        return False
    # An agent that is behind takes nothing but its own update. Here as well
    # as in job_add, because job_add only sees the explicitly-placed case —
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
    """Queue a job. With an explicit node the node is checked now — it must
    exist, be online, and hold a credential if it is an agent. With a
    selector, at least one node must fit right now: a job nothing could ever
    take would sit queued forever, and "no node has X" at the button is the
    honest answer (docs/nodes.md §18 — the dashboard says which project has
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
            return {"error": f"node is {n['state']} — it takes no new work"}
        if (n.get("agent") or {}).get("revoked"):
            return {"error": "this node's credential was revoked — enroll it "
                             "again to give it work"}
        if n["kind"] == "agent" and type != "compose" and not n.get("live"):
            return {"error": "the agent on this node is not dialing in — the "
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
    _exec("INSERT INTO jobs (id, type, project, requested_by, placement, "
          "source, spec, outputs, state, node, exit_code, queued, started, "
          "ended, step, error, cancel) VALUES (?, ?, ?, ?, ?, ?, ?, ?, "
          "'queued', ?, NULL, ?, NULL, NULL, '', '', 0)",
          (jid, type, str(project or "")[:120], str(principal),
           json.dumps(pl), json.dumps(source if isinstance(source, dict) else {}),
           json.dumps(spec if isinstance(spec, dict) else {}),
           json.dumps([]), pl.get("node") or "", int(time.time())))
    audit(principal, "job-add", jid, {"placement": pl, "type": type})
    _jbump()
    with _wake:
        _wake.notify_all()
    return {"ok": True, "job": jid}


def run_wait(principal, node_id, argv, env=None, timeout=30, files=None,
             sizes=None, project=""):
    """One command on a node, waited for: queued as an exec job, picked up
    by the agent's next poll (which is held open, so at once), and its log
    and exit code handed back — the Nodes tab's Test, generalised. For the
    phone: adb on the node that holds the handset, where the controller has
    no adb and no phone. {"code", "out"} or {"error"}."""
    spec = {"argv": [str(a) for a in argv], "timeout": int(timeout)}
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
            return {"code": j.get("exit_code") if j["state"] == "succeeded" or j.get("exit_code") is not None else 1,
                    "out": j.get("log") or "", "job": r["job"], "state": j["state"]}
        time.sleep(0.25)
    # Taken back, not left in the queue: a probe nobody is waiting for any
    # more would otherwise run whenever the node's slot freed — an `adb
    # install` an hour after the operator read it as failed.
    job_cancel(principal, r["job"])
    return {"error": f"the agent took the job ({r['job']}) but did not report back within {timeout}s"}


def root_wait(principal, node_id, argv, why="", timeout=600):
    """One approved command as root on a node (roadmap R38): a system job
    with `apply: root`, waited for like run_wait. The gate is node_apply's —
    an online agent node that enrolled as a sandbox, one system job at a
    time — because root on somebody's own machine is theirs, and the agent
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
        return {"error": f"the node is {n['state']} — a root command goes to an online node"}
    if node_locked(n):
        return {"error": node_locked(n)}
    if system_job_for(node_id):
        return {"error": "a system job is already in flight on this node — one at a time"}
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
    job_cancel(principal, r["job"])
    return {"error": f"the agent took the job ({r['job']}) but did not report back within {timeout}s"}


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
    """How many jobs this node has going, from the rows — the count the
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


def session_kill(node_id, name):
    """End a tmux session on a node: queued for the agent's held poll, and
    the poll woken so it goes now. The name is the node's own (the session
    account's prefix included) — the page's name for it is translated back
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


# tmux commands for a node's sessions — keys, a console's line, a macro —
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


def job_next(node_id, wait, runner="node", alive=None):
    """The oldest queued job this node may take, for this runner, else wait
    up to `wait` seconds for one — or for a cancel request, which comes back
    as {"cancel": [ids]} so the agent's held poll hears it at once.

    `alive` says whether the poll's client is still connected, and is asked
    before anything is handed over. A held poll outlives the agent that
    made it — an agent that restarted (its self-update, a kill) leaves its
    last poll on this side for up to a poll length — and a job queued in
    that window was assigned to the dead poll, written to a closed socket,
    and marked lost by the new agent's first hello, which never had it. The
    same poll would have swallowed a cancel, a session kill or a hello
    request. So a poll nobody is listening to takes nothing.

    Drain is honored here: a draining node's agent keeps polling (that is
    how the operator sees it is alive) and is simply never handed work. So
    is concurrency, counted from the rows. The job's node is written at this
    moment and never again — placement frozen at assignment."""
    deadline = time.time() + max(0, float(wait))
    with _wake:
        while True:
            if alive is not None and not alive():
                return None
            n = node(node_id)
            if n and n["state"] == "online" and job_running(node_id) < n["concurrency"]:
                for j in _rows("SELECT * FROM jobs WHERE state = 'queued' AND "
                               "(node = ? OR node = '') ORDER BY queued, id",
                               (node_id,)):
                    j = _job_out(j)
                    if runner_of(j["type"], n["kind"]) != runner or not fits(j, n):
                        continue
                    # An agent's job is `assigned` until its first log post
                    # says it started — the poll reply can be lost on the
                    # wire. The controller's own runner starts it on the
                    # thread that asked, so it is running from here.
                    st = "running" if runner == "controller" else "assigned"
                    _exec("UPDATE jobs SET state = ?, node = ?, "
                          "started = ? WHERE id = ?",
                          (st, node_id, int(time.time()), j["id"]))
                    _jbump()
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
            left = deadline - time.time()
            if left <= 0:
                return None
            _wake.wait(min(left, 5))


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


def job_tail(job_id, n=4000):
    """The end of a job's log, for a row that shows where it got to."""
    text = "".join(r["chunk"] for r in _rows(
        "SELECT chunk FROM job_logs WHERE job_id = ? ORDER BY seq DESC "
        "LIMIT 40", (job_id,))[::-1])
    return text[-n:]


def job_set(job_id, **fields):
    """The runner's progress: step, error. Nothing else is settable this
    way — state moves through job_next / job_result / job_cancel only."""
    sets = {k: str(v)[:500] for k, v in fields.items() if k in ("step", "error")}
    if sets:
        _exec("UPDATE jobs SET " + ", ".join(f"{k} = ?" for k in sets)
              + " WHERE id = ?", (*sets.values(), job_id))
        _jbump()


def job_log(node_id, job_id, chunks, step=None):
    """Append log chunks. Each carries the agent's sequence number, and a
    chunk already stored is dropped, so an agent that lost the answer to a
    post and sends the batch again (door 5: it buffers what it could not
    report) never doubles a line. The answer carries the cancel flag: a
    runner posts output every half second, so this is how one that is busy
    hears it should stop."""
    got = _rows("SELECT node, state, cancel FROM jobs WHERE id = ?", (job_id,))
    if not got or got[0]["node"] != node_id:
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
    if n or step is not None:
        _jbump()
    return {"ok": True, "stored": n, "cancel": bool(got[0]["cancel"])}


def job_result(node_id, job_id, state, exit_code=None, error="", outputs=None):
    """Terminal. Idempotent by design — the agent retries until it is
    acknowledged, so the second arrival of the same result is a no-op with
    the same answer, not a second audit row."""
    got = _rows("SELECT node, state, type FROM jobs WHERE id = ?", (job_id,))
    if not got or got[0]["node"] != node_id:
        return {"error": "not this node's job"}
    if got[0]["state"] in JOB_END:
        return {"ok": True, "already": True}
    if state not in JOB_END:
        return {"error": "a result is succeeded, failed or canceled"}
    code = None
    with contextlib.suppress(TypeError, ValueError):
        code = int(exit_code) if exit_code is not None else None
    _exec("UPDATE jobs SET state = ?, exit_code = ?, ended = ?, step = '', "
          "error = ? WHERE id = ?",
          (state, code, int(time.time()), str(error or "")[:500], job_id))
    # What the job left behind: the artifacts it uploaded and, for a failed
    # one, the workspace the node kept for inspection (docs/nodes.md §6).
    if isinstance(outputs, list):
        keep = [o for o in outputs[:64] if isinstance(o, dict)]
        _exec("UPDATE jobs SET outputs = ? WHERE id = ?", (json.dumps(keep), job_id))
    audit(f"node:{node_id}", "job-result", job_id, {"state": state, "exit": code})
    # The module that queued this kind of job gets to finish it. A compose
    # action run by the agent still has records to write here — what was
    # built, from which commit, on which daemon — and this is where they
    # land, once, whichever runner served it.
    fn = ON_DONE.get(got[0]["type"] if "type" in got[0].keys() else "")
    if fn:
        with contextlib.suppress(Exception):     # noqa: BLE001 — a hook must not lose a result
            # A hook may also REWORD the failure. All a node can honestly say
            # is "exit 1" — it ran an argv somebody else composed — while the
            # module that wrote the plan knows the step was "starting" and
            # what that means. The row used to carry that sentence because
            # the controller ran compose itself; this is how it keeps it now
            # the node does (roadmap #24).
            better = fn(job(job_id, with_log=False), state)
            if state != "succeeded" and isinstance(better, str) and better.strip():
                _exec("UPDATE jobs SET error = ? WHERE id = ?",
                      (better.strip()[:500], job_id))
    _jbump()
    with _wake:
        _wake.notify_all()      # the slot is free: a held poll may take the next
    return {"ok": True}


def job_cancel(principal, job_id):
    """Stop a job. Queued: it simply ends, canceled. Assigned or running:
    the flag is set and the runner is woken — the agent hears it on its
    next log post or held poll, the controller's own runner reads it and
    kills the process group — and the row stays running until the runner
    reports the end, because that is when it actually ended."""
    got = _rows("SELECT state, cancel FROM jobs WHERE id = ?", (job_id,))
    if not got:
        return {"error": "no such job"}
    if got[0]["state"] in JOB_END:
        return {"ok": True, "already": True}
    if got[0]["state"] == "queued":
        _exec("UPDATE jobs SET state = 'canceled', ended = ?, error = 'canceled "
              "before it started' WHERE id = ?", (int(time.time()), job_id))
    elif not got[0]["cancel"]:
        _exec("UPDATE jobs SET cancel = 1 WHERE id = ?", (job_id,))
    audit(principal, "job-cancel", job_id, {})
    _jbump()
    with _wake:
        _wake.notify_all()
    return {"ok": True}


def jobs_for(node_id=None, n=50, project=None, type=None, active=False):
    q, args = "SELECT * FROM jobs", []
    where = []
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
    # second used to come back in either order — the row then showed an
    # older job as the latest, or none at all.
    q += " ORDER BY queued DESC, rowid DESC LIMIT ?"
    return [_job_out(r) for r in _rows(q, (*args, int(n)))]


# How long past liveness a job's node may be silent before the job is lost:
# LIVE_S already allows three missed polls, and a job mid-build does not
# need the row hedging for another few minutes on top.
LOST_S = LIVE_S + 30


def jobs_lost():
    """Fail every job assigned to an agent that has gone quiet — "node lost"
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
        seen = (nd.get("agent") or {}).get("last_seen") or 0
        if now - seen > LOST_S:
            _exec("UPDATE jobs SET state = 'failed', ended = ?, step = '', "
                  "error = 'node lost — the agent stopped answering' WHERE "
                  "id = ?", (now, j["id"]))
            audit("system", "job-lost", j["id"], {"node": j["node"]})
            n += 1
    if n:
        _jbump()
    return n


def jobs_reconcile(node_id, running):
    """At hello: the jobs this side has as running on the node that the
    node does not — an agent that restarted, whose children died with it."""
    have = {r["id"] for r in _rows(
        "SELECT id FROM jobs WHERE node = ? AND state IN ('assigned', "
        "'running')", (node_id,))}
    gone = have - set(running)
    for jid in gone:
        # A compose job on an agent node is the controller's, and the agent
        # never had it — only what the agent RUNS is reconciled against it.
        j = job(jid, with_log=False)
        if runner_of(j["type"], "agent") != "node":
            continue
        _exec("UPDATE jobs SET state = 'failed', ended = ?, step = '', error "
              "= 'lost — the agent restarted without it' WHERE id = ?",
              (int(time.time()), jid))
        audit("system", "job-lost", jid, {"node": node_id, "why": "restart"})
    if gone:
        _jbump()


def jobs_restart_sweep():
    """At start: a job the controller itself was running when the process
    died is failed as lost — the subprocess died with it, and a row still
    saying running would say it forever. An agent's own jobs are left to
    the agent's hello, which reconciles against what it actually has."""
    now = int(time.time())
    n = 0
    for j in _rows("SELECT j.id, j.type, k.kind FROM jobs j LEFT JOIN nodes "
                   "k ON k.id = j.node WHERE j.state IN ('assigned', 'running')"):
        if runner_of(j["type"], j["kind"] or "local") != "controller":
            continue
        _exec("UPDATE jobs SET state = 'failed', ended = ?, step = '', error "
              "= 'lost — BuilderBot restarted while it was running' WHERE "
              "id = ?", (now, j["id"]))
        audit("system", "job-lost", j["id"], {"why": "controller restart"})
        n += 1
    if n:
        _jbump()
    return n


def job_counts():
    """Jobs by state, nodes by state and liveness — the numbers /healthz
    and /metrics are made of."""
    out = {"jobs": {s: 0 for s in JOB_ACTIVE + JOB_END}, "nodes": {}}
    for r in _rows("SELECT state, COUNT(*) AS n FROM jobs GROUP BY state"):
        out["jobs"][r["state"]] = r["n"]
    for n in node_list():
        k = n["state"] + ("/live" if n.get("live") else "")
        out["nodes"][k] = out["nodes"].get(k, 0) + 1
    return out


# ---------------------------------------------------------------------------
# the agent file — served to nodes, and the digest hello compares against

AGENT_PY = HERE.parent / "agent" / "builderbot-agent.py"
_agent_cache = {}


def agent_file():
    """The agent this controller ships: bytes, sha256, version string.
    Read once per mtime, so the digest hello answers with is the file on
    disk right now — which is what makes 'is my agent current' a byte
    comparison on the node rather than a version number anyone typed."""
    try:
        st = AGENT_PY.stat()
    except OSError:
        return {"body": b"", "digest": "", "version": ""}
    if _agent_cache.get("mtime") != st.st_mtime:
        body = AGENT_PY.read_bytes()
        m = re.search(rb'^AGENT_VERSION\s*=\s*"([^"]+)"', body, re.MULTILINE)
        _agent_cache.update({
            "mtime": st.st_mtime, "body": body,
            "digest": "sha256:" + hashlib.sha256(body).hexdigest(),
            "version": m.group(1).decode() if m else "?"})
    return dict(_agent_cache)


# ---------------------------------------------------------------------------
# audit

def audit(principal, action, target, params):
    """One row per mutation: when, who, what, on what, and a digest of the
    parameters — never the parameters themselves, which may carry tokens and
    env text. History that was never written cannot be backfilled (door 2),
    which is why this lands with the schema and not with the first screen
    that displays it."""
    blob = json.dumps(params, sort_keys=True, default=str) if params else ""
    digest = (f"sha256:{hashlib.sha256(blob.encode()).hexdigest()[:12]}"
              f"·{len(blob)}b" if blob else "")
    try:
        _exec("INSERT INTO audit (id, at, principal, action, target, params) "
              "VALUES (?, ?, ?, ?, ?, ?)",
              (mint("a"), int(time.time()), str(principal), str(action)[:200],
               str(target)[:200], digest))
    except sqlite3.Error as e:
        # Bookkeeping must never break the mutation it records — a full disk
        # mid-flight costs the row and says so, not the operator's action.
        print(f"[nodes] audit write failed: {e}", flush=True)


def audit_tail(n=50):
    """The newest rows, for tests and a future view — not an endpoint yet."""
    return _rows("SELECT * FROM audit ORDER BY at DESC, id DESC LIMIT ?",
                 (int(n),))
