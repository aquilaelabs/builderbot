-- 0006: a person's devices (R272 step 1): an app a person signed in with on
-- their own machine (the Windows companion, the phone, an editor), each with
-- a token of its own that acts as that person for the app's calls alone.
--
-- Only the token's sha256 is kept, as for a node's. `uid` is the account's
-- stable id, so a rename keeps the person's devices; `seen` is when the app
-- last called, written at most once a minute.

CREATE TABLE IF NOT EXISTS devices (
    id          TEXT PRIMARY KEY,
    uid         TEXT NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    secret_hash TEXT NOT NULL UNIQUE,
    created     INTEGER NOT NULL,
    seen        INTEGER,
    revoked     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS devices_uid ON devices (uid);
