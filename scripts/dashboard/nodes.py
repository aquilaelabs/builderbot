#!/usr/bin/env python3
"""The node data plane: the database seam, the migrations, the node registry,
the audit trail — and, from phase 3, the agent channel: enrollment tokens,
node credentials, the heartbeat with its census, and the job rows an `exec`
job rides in on (docs/nodes.md §4, §9).

Phase 1 seeded a `local` node for the container itself, mirrored DOCKER_HOST
into an `ssh` node so the sandbox VM had a record, answered a read-only list,
stamped which node a piece of work ran on, and wrote an audit row for every
mutation the server takes. Phase 2 made the registry editable. Phase 3 is the
first time something OTHER than this container writes here: an agent on a
node dials in with a bearer token, says what it is, asks for work, and
reports what happened. The four one-way doors this module owns were paid
in phase 1 so that could land without reshaping anything (docs/nodes.md §15):

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
    _adopt_docker_host()


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
    explicable) and left out of every list unless asked for."""
    rows = [_live(_inflate(r)) for r in _rows(
        "SELECT * FROM nodes ORDER BY kind = 'local' DESC, created")]
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
    heartbeat to be late with (ssh nodes are probed, local is us)."""
    if rec.get("kind") == "agent":
        seen = (rec.get("agent") or {}).get("last_seen") or 0
        rec["live"] = (time.time() - seen) < LIVE_S
    else:
        rec["live"] = None
    return rec


def _insert_node(rec):
    cols = ("id", "name", "kind", "pool", "created", "state", "concurrency",
            "ssh_addr", *_JSON_COLS)
    vals = [json.dumps(rec.get(c, {})) if c in _JSON_COLS else rec.get(c)
            for c in cols]
    _exec(f"INSERT INTO nodes ({', '.join(cols)}) VALUES "
          f"({', '.join('?' * len(cols))})", vals)


def _seed_local():
    """The controller as a node, present from the first boot.

    Re-seeded shallowly on every boot: the row survives, but the reported
    census is refreshed because it describes this container, and this boot is
    the authority on this container. Capabilities stay conservative —
    package-build is what this box demonstrably does; docker-host stays off
    (the local node is not a sandbox, docs/nodes.md §12) and joins only if a
    later phase finds a mounted socket and the operator turns it on.
    """
    reported = {
        "cpu": os.cpu_count() or 0,
        "mem_mb": _mem_mb(),
        "os": f"{platform.system().lower()} {platform.machine()}",
    }
    if node(LOCAL):
        _exec("UPDATE nodes SET reported = ? WHERE id = ?",
              (json.dumps(reported), LOCAL))
        return
    _insert_node({
        "id": LOCAL, "name": "controller", "kind": "local",
        "pool": "default", "created": int(time.time()), "state": "online",
        "concurrency": 1, "ssh_addr": "",
        "capabilities": ["package-build"],
        "services": {"actions-runner": {}},
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


def _adopt_docker_host():
    """Mirror DOCKER_HOST into an ssh-kind node record, once.

    The env var keeps working exactly as it does — devapp still reads it, and
    nothing routes through this row yet — but the sandbox VM now has an
    identity that is not its address, which is the migration path §11
    describes: the record exists first, the env var stops being read later.
    Keyed on the address so a changed DOCKER_HOST makes a NEW node rather
    than quietly rewriting what the old record meant; the old one is marked
    retired, not deleted, because rows are history (door 1).
    """
    addr = (os.environ.get("DOCKER_HOST") or "").strip()
    if not addr.startswith("ssh://"):
        return
    have = _rows("SELECT id FROM nodes WHERE kind = 'ssh' AND ssh_addr = ? "
                 "AND state != 'retired'", (addr,))
    if have:
        return
    # Only the row THIS migration made goes when the env var moves — marked
    # so, because with the tab able to add nodes, "retire every other ssh
    # node" would eat the operator's own rows on the next boot.
    _exec("UPDATE nodes SET state = 'retired' WHERE kind = 'ssh' "
          "AND state != 'retired' AND config LIKE ?",
          ('%"from_env": true%',))
    nid = mint("n")
    _insert_node({
        "id": nid, "name": "sandbox", "kind": "ssh",
        "pool": "default", "created": int(time.time()), "state": "online",
        "concurrency": 1, "ssh_addr": addr,
        "capabilities": ["docker-host"],
        "services": {}, "labels": {"disposable": "true"},
        "agent": {}, "reported": {}, "routing": {},
        "config": {"from_env": True},
    })
    audit("system", "node-adopt", nid, {"from": "DOCKER_HOST"})


def node_for(capability=None):
    """Which node work runs on. Phase 1's answer is fixed — docker work is
    the sandbox record, everything else is local — and the point is that
    callers ask at all: the call sites this creates are the seam phase 4's
    placement function slides into without touching them again."""
    try:
        if capability == "docker-host":
            got = _rows("SELECT id FROM nodes WHERE kind = 'ssh' AND "
                        "state != 'retired' ORDER BY created DESC")
            if got:
                return got[0]["id"]
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
    """Register an ssh-kind docker host. Phase 2's only enrollment: the
    agent kind arrives with phase 3 and mints its ids the same way."""
    name = (name or "").strip() or "node"
    addr = (ssh_addr or "").strip()
    if addr and "://" not in addr:
        addr = "ssh://" + addr
    if not addr.startswith("ssh://"):
        return {"error": "an ssh node needs an ssh:// address (or a bare "
                         "host, which gets ssh:// and the bb account)"}
    if "@" not in addr[len("ssh://"):]:
        addr = "ssh://bb@" + addr[len("ssh://"):]
    caps = [c for c in (capabilities or ["docker-host"]) if c in CAPABILITIES]
    if _rows("SELECT id FROM nodes WHERE ssh_addr = ? AND state != 'retired'",
             (addr,)):
        return {"error": f"a node already answers at {addr}"}
    nid = mint("n")
    _insert_node({
        "id": nid, "name": name[:60], "kind": "ssh",
        "pool": str(pool or "default")[:60], "created": int(time.time()),
        "state": "online", "concurrency": 1, "ssh_addr": addr,
        "capabilities": caps, "services": {},
        "labels": {"disposable": "true"},
        "agent": {}, "reported": {}, "routing": {}, "config": {},
    })
    _touch(nid, principal, "node-add", {"addr": addr})
    return {"ok": True, "id": nid}


def node_update(principal, node_id, fields):
    """Rename, re-pool, relabel, set concurrency, toggle capabilities —
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
    return [n for n in node_list()
            if n["state"] not in ("retired", "pending")
            and "docker-host" in n["capabilities"]
            and (n["kind"] == "local" or _addr(n))]


def _addr(n):
    """Where docker on this node answers, for whichever kind it is.

    An ssh node stores its address — that IS the record. An agent node's
    address is informational and refreshed by the node itself on every
    dial-in (docs/nodes.md §2: the id is the identity, the address is data),
    so docker over ssh to an agent node goes to wherever it said it was
    last, with the account the provisioner enrolled. That is what lets a
    VM change address without anything on this side being edited, and it
    is the whole of how 'agent or ssh, and both work' is true in phase 3 —
    docker itself still travels over ssh until compose actions become
    jobs (phase 4).
    """
    if n["kind"] == "ssh":
        return n.get("ssh_addr") or ""
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
    and it is where the token's scope lives: the capabilities the operator
    intended are on the row, so enrollment adds nothing the operator did not
    ask for. The id is minted now and kept; a token that expires unused
    leaves a pending row the tab offers to remove, never a reused id.
    """
    name = (name or "").strip()[:60] or "node"
    caps = [c for c in (capabilities or ["package-build"]) if c in CAPABILITIES]
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
    _exec("UPDATE nodes SET state = 'online', agent = ?, reported = ?, "
          "config = ? WHERE id = ?",
          (json.dumps({"token_id": tid, "version": str(version)[:40],
                       "digest": str(digest)[:80], "addr": addr,
                       "last_seen": int(time.time()), "protocol": PROTOCOL}),
           json.dumps(_census(census)), json.dumps(cfg), nid))
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

PROTOCOL = 1
POLL_S = 25                      # held below the 30s most proxies allow
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
    out["sshd"] = bool(c.get("sshd"))
    stores = c.get("stores") if isinstance(c.get("stores"), dict) else {}
    out["stores"] = {}
    for role, s in list(stores.items())[:8]:
        if isinstance(s, dict):
            out["stores"][str(role)[:20]] = {
                "path": str(s.get("path") or "")[:200],
                "free_mb": _mb(s.get("free_mb")),
                "total_mb": _mb(s.get("total_mb"))}
    tc = c.get("toolchains") if isinstance(c.get("toolchains"), dict) else {}
    out["toolchains"] = {str(k)[:30]: (str(v)[:40] if v else None)
                         for k, v in list(tc.items())[:16]}
    return out


def hello(nid, census, addr, version="", digest=""):
    """The agent on connect: refresh the census, record the version it is
    running, and answer with what the controller expects of it — protocol,
    transports, the poll window, the node's own capabilities (so it can
    refuse outside them, door 7) and the controller's agent file digest
    (so self-update is a comparison, door 4)."""
    n = node(nid)
    if not n:
        return {"error": "no such node"}
    ag = n.get("agent") or {}
    ag.update({"version": str(version)[:40], "digest": str(digest)[:80],
               "addr": addr, "last_seen": int(time.time()),
               "protocol": PROTOCOL})
    rep = n.get("reported") or {}
    sample = rep.get("sample")
    rep = _census(census)
    if sample:
        rep["sample"] = sample
    _exec("UPDATE nodes SET agent = ?, reported = ? WHERE id = ?",
          (json.dumps(ag), json.dumps(rep), nid))
    _bump()
    ours = agent_file()
    return {"ok": True, "protocol": PROTOCOL, "transports": ["longpoll"],
            "poll": POLL_S, "node": {"id": nid, "name": n["name"],
                                     "state": n["state"],
                                     "capabilities": n["capabilities"],
                                     "concurrency": n["concurrency"]},
            "agent": {"digest": ours["digest"], "version": ours["version"]}}


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
# jobs — phase 3 carries exactly one type, exec, over the channel it is
# proving. The rows are the phase-4 model (placement, logs, cancel, node
# lost) written as far as one node and one queue need: a job names its node
# at creation, the node's agent takes the oldest queued one when it has a
# free slot, log chunks accumulate by sequence number, and the result is
# terminal. Nothing here decides WHICH node — that is placement, phase 4.

JOB_TYPES = ("exec", "self-update")
JOB_END = ("succeeded", "failed", "canceled")


def job_add(principal, node_id, type, spec, project=""):
    n = node(node_id)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": "no agent on this node — jobs run where an agent "
                         "dials in, and an ssh node is driven over ssh"}
    if type not in JOB_TYPES:
        return {"error": f"job type is one of {', '.join(JOB_TYPES)}"}
    if n["state"] != "online":
        return {"error": f"node is {n['state']} — it takes no new work"}
    if (n.get("agent") or {}).get("revoked"):
        return {"error": "this node's credential was revoked — enroll it "
                         "again to give it work"}
    jid = mint("j")
    _exec("INSERT INTO jobs (id, type, project, requested_by, placement, "
          "source, spec, outputs, state, node, exit_code, queued, started, "
          "ended) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, NULL, ?, "
          "NULL, NULL)",
          (jid, type, str(project or "")[:120], str(principal),
           json.dumps({"node": node_id}), json.dumps({}),
           json.dumps(spec if isinstance(spec, dict) else {}),
           json.dumps([]), node_id, int(time.time())))
    audit(principal, "job-add", jid, {"node": node_id, "type": type})
    with _wake:
        _wake.notify_all()
    return {"ok": True, "job": jid}


def job_next(node_id, running, wait):
    """The long-poll's other half: the oldest queued job for this node if
    it may take one, else wait up to `wait` seconds for one to be added.
    Drain is honored here — a draining node's agent keeps polling (that is
    how the operator sees it is alive) and is simply never handed work.
    So is concurrency: the agent says how many jobs it has going, and the
    row says how many it may."""
    deadline = time.time() + max(0, float(wait))
    with _wake:
        while True:
            n = node(node_id)
            if n and n["state"] == "online" and int(running or 0) < n["concurrency"]:
                got = _rows("SELECT * FROM jobs WHERE node = ? AND state = "
                            "'queued' ORDER BY queued, id LIMIT 1", (node_id,))
                if got:
                    j = got[0]
                    _exec("UPDATE jobs SET state = 'assigned', started = ? "
                          "WHERE id = ?", (int(time.time()), j["id"]))
                    return _job_out(j) | {"state": "assigned"}
            left = deadline - time.time()
            if left <= 0:
                return None
            _wake.wait(min(left, 5))


def _job_out(j):
    j = dict(j)
    for k in ("placement", "source", "spec", "outputs"):
        with contextlib.suppress(ValueError, TypeError):
            j[k] = json.loads(j[k])
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


def job_log(node_id, job_id, chunks):
    """Append log chunks. Each carries the agent's sequence number, and a
    chunk already stored is dropped, so an agent that lost the answer to a
    post and sends the batch again (door 5: it buffers what it could not
    report) never doubles a line."""
    got = _rows("SELECT node, state FROM jobs WHERE id = ?", (job_id,))
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
    return {"ok": True, "stored": n}


def job_result(node_id, job_id, state, exit_code=None):
    """Terminal. Idempotent by design — the agent retries until it is
    acknowledged, so the second arrival of the same result is a no-op with
    the same answer, not a second audit row."""
    got = _rows("SELECT node, state FROM jobs WHERE id = ?", (job_id,))
    if not got or got[0]["node"] != node_id:
        return {"error": "not this node's job"}
    if got[0]["state"] in JOB_END:
        return {"ok": True, "already": True}
    if state not in ("succeeded", "failed"):
        return {"error": "a result is succeeded or failed"}
    code = None
    with contextlib.suppress(TypeError, ValueError):
        code = int(exit_code) if exit_code is not None else None
    _exec("UPDATE jobs SET state = ?, exit_code = ?, ended = ? WHERE id = ?",
          (state, code, int(time.time()), job_id))
    audit(f"node:{node_id}", "job-result", job_id, {"state": state, "exit": code})
    return {"ok": True}


def jobs_for(node_id=None, n=20):
    q = "SELECT * FROM jobs" + (" WHERE node = ?" if node_id else "")
    q += " ORDER BY queued DESC, id DESC LIMIT ?"
    return [_job_out(r) for r in _rows(q, ((node_id,) if node_id else ())
                                       + (int(n),))]


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
