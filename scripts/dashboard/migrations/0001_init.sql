-- 0001: the node-and-job data plane, whole, empty.
--
-- Every table the controller design names is created here even though phase 1
-- only writes three of them (nodes, audit, schema bookkeeping). That is
-- deliberate: the schema is the part that has to run on two engines forever
-- (docs/nodes.md §5, §15 door 6), so it is easier to keep honest as one
-- reviewed piece than as a drip of later alterations, and an empty table
-- costs nothing.
--
-- Portability rules, binding on every migration after this one:
--   * types are TEXT / INTEGER only; JSON is TEXT serialized app-side
--   * ids are TEXT, minted by the application; never AUTOINCREMENT/SERIAL
--   * times are INTEGER epoch seconds
--   * no engine-specific syntax: no WITHOUT ROWID, no JSON1, no partial
--     indexes, no ON CONFLICT clauses in the schema
-- The statements are split on blank-line boundaries by the runner, so keep
-- one statement per paragraph.

CREATE TABLE nodes (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL,
    pool         TEXT NOT NULL,
    created      INTEGER NOT NULL,
    state        TEXT NOT NULL,
    concurrency  INTEGER NOT NULL,
    ssh_addr     TEXT NOT NULL,
    capabilities TEXT NOT NULL,
    services     TEXT NOT NULL,
    labels       TEXT NOT NULL,
    agent        TEXT NOT NULL,
    reported     TEXT NOT NULL,
    routing      TEXT NOT NULL,
    config       TEXT NOT NULL
);

CREATE TABLE jobs (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL,
    project      TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    placement    TEXT NOT NULL,
    source       TEXT NOT NULL,
    spec         TEXT NOT NULL,
    outputs      TEXT NOT NULL,
    state        TEXT NOT NULL,
    node         TEXT NOT NULL,
    exit_code    INTEGER,
    queued       INTEGER NOT NULL,
    started      INTEGER,
    ended        INTEGER
);

CREATE INDEX jobs_state ON jobs (state, queued);

CREATE TABLE job_logs (
    job_id TEXT NOT NULL,
    seq    INTEGER NOT NULL,
    at     INTEGER NOT NULL,
    chunk  TEXT NOT NULL
);

CREATE INDEX job_logs_job ON job_logs (job_id, seq);

CREATE TABLE artifacts (
    id      TEXT PRIMARY KEY,
    job_id  TEXT NOT NULL,
    path    TEXT NOT NULL,
    size    INTEGER NOT NULL,
    digest  TEXT NOT NULL,
    created INTEGER NOT NULL
);

CREATE TABLE tokens (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    node_id     TEXT NOT NULL,
    secret_hash TEXT NOT NULL,
    created     INTEGER NOT NULL,
    expires     INTEGER,
    revoked     INTEGER NOT NULL,
    uses        INTEGER NOT NULL
);

CREATE TABLE audit (
    id        TEXT PRIMARY KEY,
    at        INTEGER NOT NULL,
    principal TEXT NOT NULL,
    action    TEXT NOT NULL,
    target    TEXT NOT NULL,
    params    TEXT NOT NULL
);

CREATE INDEX audit_at ON audit (at);
