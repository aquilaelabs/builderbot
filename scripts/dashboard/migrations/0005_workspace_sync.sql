-- 0005: a synced project's index (R162).
--
-- A node that holds its projects as a copy rather than mounting the share
-- syncs them through the controller, whose copy on the share is the
-- original. Each row is one file as the controller last saw it: its hash,
-- size, mode, a symlink's target, and the revision it last changed at. A
-- deletion stays as a row with gone = 1, so a node asking what changed
-- since its revision hears about it. Revisions count per project.

CREATE TABLE IF NOT EXISTS sync_files (
    project TEXT NOT NULL,
    path TEXT NOT NULL,
    sha TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    mode INTEGER NOT NULL,
    link TEXT NOT NULL,
    rev INTEGER NOT NULL,
    gone INTEGER NOT NULL,
    PRIMARY KEY (project, path)
)

CREATE INDEX IF NOT EXISTS sync_files_rev ON sync_files (project, rev)

CREATE TABLE IF NOT EXISTS sync_projects (
    project TEXT PRIMARY KEY,
    rev INTEGER NOT NULL,
    scanned INTEGER NOT NULL
)
