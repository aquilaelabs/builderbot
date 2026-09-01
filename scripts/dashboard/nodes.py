#!/usr/bin/env python3
"""The node data plane: the database seam, the migrations, the node registry,
and the audit trail. Phase 1 of docs/nodes.md — the seam, with nothing
visibly changing.

What this module is for now is small: seed a `local` node for the container
itself, mirror DOCKER_HOST into an `ssh` node so the sandbox VM has a record,
answer a read-only list, stamp which node a piece of work ran on, and write
an audit row for every mutation the server takes. What it is shaped for is
the rest of the design, which is why the four one-way doors it owns are paid
here rather than later (docs/nodes.md §15):

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


def node_list():
    """Every node, JSON columns inflated — the read-only list phase 1 ships."""
    return [_inflate(r) for r in _rows(
        "SELECT * FROM nodes ORDER BY kind = 'local' DESC, created")]


def node(node_id):
    got = _rows("SELECT * FROM nodes WHERE id = ?", (node_id,))
    return _inflate(got[0]) if got else None


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
    _exec("UPDATE nodes SET state = 'retired' WHERE kind = 'ssh' "
          "AND state != 'retired'")
    nid = mint("n")
    _insert_node({
        "id": nid, "name": "sandbox", "kind": "ssh",
        "pool": "default", "created": int(time.time()), "state": "online",
        "concurrency": 1, "ssh_addr": addr,
        "capabilities": ["docker-host"],
        "services": {}, "labels": {"disposable": "true"},
        "agent": {}, "reported": {}, "routing": {}, "config": {},
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
