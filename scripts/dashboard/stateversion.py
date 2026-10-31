#!/usr/bin/env python3
"""The version of what /config holds, and the one door every upgrade takes.

/config outlives every image: an update replaces the container and keeps
the volume, so a build reads state an older build wrote, and a rollback has
an older build read state a newer one wrote. The SQLite store carries its
schema's version (db.py's schema_migrations); the JSON stores beside it
(the accounts, the settings, the notebook, the tool packs) carried nothing,
and a one-off migrator at start was the only thing between a new build and
an old shape. This is that number, held in code rather than in a rule only
a briefed session reads:

  * /config/state.json is {"state": N, "by": VERSION, "at": TIME}: N is the
    newest numbered migration in statemigrations/ that has run on it, and
    BY the build that ran it. No state.json on a /config that holds records
    is state 0, an install from before the stamp; on one that holds nothing
    it is a fresh install, stamped current with nothing to run.
  * At start, before anything writes, gate() refuses a /config NEWER than
    this build (a downgrade: restore the copy taken before the upgrade) and
    one OLDER than SUPPORTED_FROM (go through the release named for it
    first), each in one sentence, and the controller does not start. The
    entrypoint asks the same question (`stateversion.py check`) before its
    hooks run, so a refused container writes nothing at all.
  * When the state is to move, the copy of /config is taken first
    (backups/before-VERSION, the newest three kept), then migrate() runs
    every numbered migration past the stamp, in order, once all the
    modules are configured, and stamps the last one that ran.

A migration is statemigrations/NNNN_name.py with run(ctx): idempotent, so a
start cut short runs it again safely, and never edited once a release has
shipped it (`bb lint` holds every one present at the newest v* tag
byte-for-byte). Adding one moves CURRENT, since CURRENT is the newest file.
Stdlib only, and importable on its own: the entrypoint runs it as a script.
"""
import contextlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIGRATIONS = HERE / "statemigrations"
FILE = "state.json"
BACKUPS = "backups"
KEEP = 3

# The oldest state this build migrates from: state 2, what 0.6.0 shipped,
# so any 0.6.x, 0.7.x or 0.8.x install upgrades in one step (the operator,
# 28 Oct: 0.9 is a clean break with upgrade paths from 0.6, 0.7 and 0.8).
# The migrations below it are gone from the tree (bb lint allows that for a
# number under this floor alone). A release that drops a state from here
# names the release that still reads it in THROUGH.
SUPPORTED_FROM = 2

# state -> the release line to go through for a state this build no longer
# migrates from: its newest release carries it to one this build reads.
# State 0 is a /config from before the stamp (before 0.5.0), state 1 a 0.5.x.
THROUGH = {0: "0.6", 1: "0.6"}

# What the copy before a migration leaves out: what grows and is not state
# (each kind paths.py lets the Settings page move: logs, the trees jobs ran
# from, each project's daily snapshots, dev-instance images in transit, the
# relay and Git view repositories rebuilt from the projects), the apps fetched
# from a release, the copies themselves, a Reset's moved-aside state, and
# lock and temporary files. The JSON records, the database, the signing keys,
# the git credentials and the wiki are all kept.
# runner-tokens is a Docker volume of its own, root-only by design and kept
# across an update by Docker, which this copy (made as the dashboard's
# account) could not read anyway (B109).
SKIP = {BACKUPS, "logs", "snapshots", "project-snapshots", "images", "gitrelay",
        "gitview", "apps", "ci-logs", "runner-tokens", "state-held"}
SKIP_GLOBS = (".reset-*", "*.lock", "*.tmp")

# Why this start migrates nothing, when the copy before it failed; written
# to /config/state-held too, which bb doctor says in red (B109).
HELD = ""
HELD_FILE = "state-held"


def _held(state, why):
    """Say why the state is held, or clear it once nothing is."""
    f = Path(state) / HELD_FILE
    with contextlib.suppress(OSError):
        if why:
            f.write_text(why + "\n")
        else:
            f.unlink(missing_ok=True)

# A /config holding any of these has been used: one without state.json is
# state 0, not a fresh install.
RECORDS = ("users.json", "builderbot.db", "settings.json", "projects.json",
           "roadmap.json", "bugs.json", "rules.json")


def migrations():
    """[(number, path)] of statemigrations/NNNN_*.py, in order."""
    return sorted((int(p.name[:4]), p) for p in MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.py"))


def current():
    """The state this build writes: its newest migration's number."""
    ms = migrations()
    return ms[-1][0] if ms else 0


def build_version():
    """This build's version: the image's BB_VERSION, else the tree's
    VERSION file (a checkout run by hand), else "unknown"."""
    v = (os.environ.get("BB_VERSION") or "").strip()
    if not v:
        with contextlib.suppress(OSError):
            v = (HERE.parent.parent / "VERSION").read_text().strip()
    return v or "unknown"


def read(state):
    """(state number, the build that wrote it) of `state`, or (None, "") for
    a /config with no stamp. A stamp that cannot be read is refused rather
    than guessed: a guess is how an old build migrates a newer /config."""
    p = Path(state) / FILE
    try:
        d = json.loads(p.read_text())
    except FileNotFoundError:
        return None, ""
    except (OSError, ValueError) as e:
        raise ValueError(f"{p} cannot be read ({e})") from None
    n = d.get("state") if isinstance(d, dict) else None
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise ValueError(f"{p} holds no state number")
    return n, str(d.get("by") or "")


def used(state):
    """Whether `state` holds any record: a fresh /config holds none."""
    return any((Path(state) / r).exists() for r in RECORDS)


def stamp(state, n, version=None):
    """Write the stamp. Atomic, so a reader never meets half of it."""
    import statefile
    statefile.write_json(Path(state) / FILE, {"state": int(n), "by": version or build_version(),
                                              "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})


def refusal(state, version=None):
    """The one sentence that keeps this build off `state`, or "" when it
    may start on it."""
    version = version or build_version()
    try:
        n, by = read(state)
    except ValueError as e:
        return (f"BuilderBot {version} will not start: {e}, so which build wrote this /config is not "
                f"known. Restore {FILE} from a copy under {Path(state) / BACKUPS}, or put back the "
                f"build that wrote it.")
    cur = current()
    if n is None:
        n = 0 if used(state) else cur
    if n > cur:
        back = _newest_backup(state)
        where = (f"restore {back} over {state} with the controller stopped" if back
                 else f"restore {state} from your own backup")
        return (f"BuilderBot {version} will not start: this /config is at state {n}, written by "
                f"BuilderBot {by or 'a newer build'}, and this build reads state {cur} and older. "
                f"Downgrades are not supported: start {by or 'the newer build'} again, or {where}.")
    if n < SUPPORTED_FROM:
        via = THROUGH.get(n, "an older release")
        return (f"BuilderBot {version} will not start: this /config is at state {n}"
                f"{f', written by BuilderBot {by}' if by else ''}, and this build upgrades from state "
                f"{SUPPORTED_FROM} on. Start the newest {via} release on it first, then this one "
                f"(docs/install.md#upgrading).")
    return ""


def gate(state, version=None):
    """At the very start, before anything writes: refuse, or stamp a fresh
    /config, or, where the state is to move, take the copy before the
    migrations do (migrate() runs them once every module is configured).
    Exits the process on a refusal. Returns the state found."""
    why = refusal(state, version)
    if why:
        print(why, file=sys.stderr, flush=True)
        sys.exit(78)              # EX_CONFIG: nothing to retry until /config changes
    n, _ = read(state)
    if n is None and not used(state):
        with contextlib.suppress(OSError):
            stamp(state, current(), version)
        return current()
    n = n or 0
    if n < current():
        try:
            dest = backup(state, version)
        except OSError as e:
            # No copy, no migration: the start goes on, on the state as it
            # is, and the next one tries the copy again.
            globals()["HELD"] = f"the copy of /config before migrating could not be made ({e})"
            print(f"dashboard: /config is at state {n} and stays there: {HELD}", flush=True)
            _held(state, f"/config is at state {n} and was not upgraded: {HELD}")
            return n
        print(f"dashboard: /config is at state {n} and this build at {current()}: "
              f"copied to {dest} before migrating", flush=True)
    _held(state, "")
    return n


def backup(state, version=None):
    """Copy `state` to backups/before-VERSION, leaving out SKIP, and keep the
    newest KEEP copies. A copy already there for this version is kept as it
    is: it is the one from before the first try, and a second start after a
    failed one must not overwrite it with half-migrated state. The database
    is copied with SQLite's own backup, which is consistent where a file
    copy of a live WAL store may not be. The copy's path."""
    state = Path(state)
    name = "before-" + re.sub(r"[^A-Za-z0-9._+-]", "_", version or build_version())
    root = state / BACKUPS
    dest = root / name
    if dest.exists():
        return dest
    tmp = root / f".{name}.partial"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    # What this account cannot read (a root-only file an operator put here)
    # is left out and named, rather than holding the whole upgrade (B109).
    unread = []

    def copy(src, dst, *, follow_symlinks=False):
        try:
            return shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
        except PermissionError:
            unread.append(os.path.relpath(src, state))
            return dst
    for p in sorted(state.iterdir()):
        if _skipped(p.name):
            continue
        try:
            if p.is_file() and p.suffix == ".db":
                _copy_db(p, tmp / p.name)
            elif p.name.endswith((".db-wal", ".db-shm")):
                continue          # folded into the .db's own copy
            elif p.is_dir() and not p.is_symlink():
                shutil.copytree(p, tmp / p.name, symlinks=True, copy_function=copy,
                                ignore=lambda _d, names: [x for x in names if _skipped(x, inner=True)])
            else:
                copy(p, tmp / p.name)
        except (PermissionError, shutil.Error):
            # copytree gathers what it could not copy into one Error.
            unread.append(p.name)
    if unread:
        (tmp / "NOT-COPIED.txt").write_text("Left out of this copy, unreadable to the dashboard's account:\n"
                                           + "".join(f"  {u}\n" for u in unread))
        print(f"dashboard: the copy of /config left out what it could not read: {', '.join(unread[:10])}",
              flush=True)
    os.replace(tmp, dest)
    os.chmod(dest, 0o700)         # it holds the password hashes and the git credentials
    for old in sorted((d for d in root.glob("before-*") if d.is_dir()),
                      key=lambda d: d.stat().st_mtime)[:-KEEP]:
        shutil.rmtree(old, ignore_errors=True)
    return dest


def _skipped(name, inner=False):
    import fnmatch
    if not inner and name in SKIP:
        return True
    return any(fnmatch.fnmatch(name, g) for g in SKIP_GLOBS)


def _copy_db(src, dst):
    a = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    b = sqlite3.connect(dst)
    try:
        a.backup(b)
    finally:
        b.close()
        a.close()


def _newest_backup(state):
    root = Path(state) / BACKUPS
    got = sorted((d for d in root.glob("before-*") if d.is_dir()), key=lambda d: d.stat().st_mtime)
    return got[-1] if got else None


def migrate(state, ctx, version=None):
    """Run every migration past the stamp, in order, and stamp each as it
    lands, so a failure part-way leaves the stamp at the last one that ran
    and the next start begins at the one that failed. A failure is said
    and does not stop the start (a migration never kept the dashboard from
    starting); it is retried at the next. The numbers that ran."""
    if HELD:
        return []
    n, _ = read(state)
    n = n or 0
    ran = []
    for num, path in migrations():
        if num <= n:
            continue
        try:
            _load(path).run(ctx)
        except Exception as e:                                 # noqa: BLE001
            print(f"dashboard: state migration {path.name} failed, and runs again at the next "
                  f"start: {type(e).__name__}: {e}", flush=True)
            break
        stamp(state, num, version)
        ran.append(num)
    if ran:
        print(f"dashboard: /config migrated to state {ran[-1]} ({', '.join(f'{x:04d}' for x in ran)})",
              flush=True)
    return ran


def restore(state, version):
    """Put back the copy a build took before it migrated `state`
    (backups/before-VERSION), for the build before it when a bare-metal
    install's update did not come up (R90 step 5). With the controller
    stopped: what the state holds of what the copy kept is moved aside, into
    backups/rolled-back-TIME, never deleted, and the copy's own is put in its
    place; what the copy leaves out on purpose (SKIP: the logs, the
    snapshots, the backups themselves) stays where it is. The folder the
    rest went to, or a ValueError saying why nothing moved."""
    state = Path(state)
    name = "before-" + re.sub(r"[^A-Za-z0-9._+-]", "_", version or "")
    src = state / BACKUPS / name
    if not version or not src.is_dir():
        raise ValueError(f"there is no copy of {state} from before {version or 'that build'} "
                         f"({src}) to put back")
    aside = state / BACKUPS / time.strftime("rolled-back-%Y%m%d-%H%M%S")
    aside.mkdir(parents=True)
    # Moved, not copied: the copy is used once (below), and a rename within
    # one disk needs no room, where a copy that ran out of it halfway left
    # half a state for the newer build to start on. Every move is undone if
    # one fails, so it is the whole copy or the state as it was.
    done = []
    try:
        for p in sorted(state.iterdir()):
            if _skipped(p.name):
                continue
            os.replace(p, aside / p.name)
            done.append((aside / p.name, p))
        for p in sorted(src.iterdir()):
            if p.name == "NOT-COPIED.txt":
                continue
            os.replace(p, state / p.name)
            done.append((state / p.name, p))
    except OSError:
        for now, was in reversed(done):
            try:
                os.replace(now, was)
            except OSError:
                pass
        raise
    # ...and what the copy could not read is still in what was moved aside:
    # brought back rather than lost (a root-only file, B109), a file inside
    # a folder the copy took the rest of included.
    for rel in _not_copied(src):
        was, now = aside / rel, state / rel
        if (was.exists() or was.is_symlink()) and not (now.exists() or now.is_symlink()):
            now.parent.mkdir(parents=True, exist_ok=True)
            os.replace(was, now)
    # The copy used goes with what it replaced, so the next start of that
    # version takes a fresh one: kept, a retry a week later reused the copy
    # from the first try, and a second rollback put that week-old state back.
    os.replace(src, aside / f"used-{name}")
    return aside


def _not_copied(src):
    """The paths, relative to the state, a copy names as left out."""
    try:
        lines = (Path(src) / "NOT-COPIED.txt").read_text().splitlines()[1:]
    except OSError:
        return []
    return [ln.strip() for ln in lines if ln.strip() and ".." not in ln.strip().split("/")]


def _load(path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"statemigrations.m{path.name[:4]}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv):
    """`stateversion.py check [STATE]`: the gate's question alone, for the
    entrypoint: exit 0 when this build may start, else the sentence and 78.
    `stateversion.py policy`: the state this build writes and the oldest it
    migrates from, as JSON, for the upgrade suite and the snapshot tool.
    `stateversion.py restore STATE VERSION`: the copy VERSION took before it
    migrated, put back (restore())."""
    if argv[:1] == ["policy"]:
        print(json.dumps({"current": current(), "supported_from": SUPPORTED_FROM}))
        return 0
    if argv[:1] == ["restore"] and len(argv) == 3:
        try:
            aside = restore(argv[1], argv[2])
        except (ValueError, OSError) as e:
            print(e, file=sys.stderr)
            return 1
        print(f"{argv[1]} is back to the copy from before {argv[2]}; what it held is in {aside}")
        return 0
    if argv[:1] != ["check"]:
        print("usage: stateversion.py check [STATE] | policy | restore STATE VERSION", file=sys.stderr)
        return 2
    why = refusal(argv[1] if len(argv) > 1 else os.environ.get("DASHBOARD_STATE", "/config"))
    if why:
        print(why, file=sys.stderr)
        return 78
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
