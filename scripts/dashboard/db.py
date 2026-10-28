#!/usr/bin/env python3
"""The controller's store: the one SQLite connection, the numbered migrations
that shape it, the ids minted for its rows and the audit trail every mutation
writes. Nothing here is about nodes; the node registry, the jobs, artifacts
and tokens are tables other modules read and write through _exec() and
_rows(), and nodes.py was merely the first of them.

The one-way doors this module owns were paid when the store first landed
(docs/nodes.md §15):

  * ids are minted, never addresses, never reused (door 1);
  * every mutation is attributed and audited from the first day there is a
    table to write it in (door 2);
  * the SQL runs on two engines behind numbered migrations from 0001:
    parameters go through _q(), JSON is TEXT, ids and times are app-side
    (door 6);
  * nothing in the schema assumes one operator: pools, token kinds and
    principals are data, not booleans (door 8).

Storage is /config/builderbot.db unless DATABASE_URL says otherwise. SQLite
is the homelab default; a postgres:// URL is the enterprise seam (E1) and is
refused loudly until that phase is built, which beats accepting it and
half-working. The notebook's JSON files are NOT this module's business: they
are small, human-edited and read whole, and they stay where they are.
"""

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIGRATIONS = HERE / "migrations"


STATE = None
_db = None
# One connection, one lock. sqlite3 serializes on its own, but a lock makes
# read-modify-write sequences whole, and it is the shape the postgres
# implementation will keep, so callers never learn a difference.
_lock = threading.RLock()


def configure(*, state):
    """Open the store and bring its schema up to date: the boot's half."""
    globals()["STATE"] = Path(state)
    _open()
    migrate()


def open_readonly(state):
    """Open the store to read it: no migration and no writes.

    For `bb nodes` and anything else that looks without being the boot: a
    read-only caller mutating the store on its way in would make "look at
    the list" a write, and two processes racing the boot's.
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
            f"DATABASE_URL={url.split('://')[0]}://… is not supported yet: "
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

    SQLite wants qmark and postgres wants format. Trivial today, and the whole
    point is that it stays trivial: every statement goes through here, so the
    day E1 lands, this function and _open() are the diff rather than a hunt.
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
    their own: the same shape at both tiers, and the discipline door 6 hangs
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
    stripped. That contract is declared in 0001's header, so a migration that
    forgets it reads it at the top of the file it copied."""
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
    """n_9f2c41d7: short, prefixed, unguessable enough to never collide in a
    table this size, and never derived from anything (door 1: an id that
    encodes a fact goes stale when the fact does)."""
    return f"{prefix}_{secrets.token_hex(4)}"




# ---------------------------------------------------------------------------
# audit

def audit(principal, action, target, params):
    """One row per mutation: when, who, what, on what, and a digest of the
    parameters (never the parameters themselves, which may carry tokens and
    env text). History that was never written cannot be backfilled (door 2),
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
        # Bookkeeping must never break the mutation it records: a full disk
        # mid-flight costs the row and says so, not the operator's action.
        print(f"[db] audit write failed: {e}", flush=True)


# The audit trail is a record, not a log, so the logs' days do not reach it;
# it is still not kept for ever: a year, and never more than this many rows.
AUDIT_DAYS = 365
AUDIT_MAX_ROWS = 200_000


def prune_audit():
    """Drop audit rows older than AUDIT_DAYS, then the oldest past
    AUDIT_MAX_ROWS. How many went."""
    try:
        before = _rows("SELECT COUNT(*) AS n FROM audit")[0]["n"]
        _exec("DELETE FROM audit WHERE at < ?", (int(time.time()) - AUDIT_DAYS * 86400,))
        _exec("DELETE FROM audit WHERE id IN (SELECT id FROM audit ORDER BY at DESC LIMIT -1 OFFSET ?)",
              (AUDIT_MAX_ROWS,))
        return before - _rows("SELECT COUNT(*) AS n FROM audit")[0]["n"]
    except sqlite3.Error as e:
        print(f"[db] audit sweep skipped: {e}", flush=True)
        return 0


def audit_page(n=100, before=0, principal="", target=""):
    """A page of the audit for the Audit page (R158 step 8), newest first:
    the rows before `before` (a unix time, 0 for now), by one principal
    and one target where asked, with how many match in all."""
    where, args = [], []
    if before:
        where.append("at < ?")
        args.append(int(before))
    if principal:
        where.append("principal = ?")
        args.append(str(principal))
    if target:
        where.append("target = ?")
        args.append(str(target))
    w = (" WHERE " + " AND ".join(where)) if where else ""
    rows = _rows(f"SELECT * FROM audit{w} ORDER BY at DESC, id DESC LIMIT ?", (*args, int(n)))
    total = _rows(f"SELECT COUNT(*) AS n FROM audit{w}", tuple(args))
    return rows, int(total[0]["n"]) if total else 0


def audit_tail(n=50):
    """The newest rows, for tests and a future view; not an endpoint yet."""
    return _rows("SELECT * FROM audit ORDER BY at DESC, id DESC LIMIT ?",
                 (int(n),))
