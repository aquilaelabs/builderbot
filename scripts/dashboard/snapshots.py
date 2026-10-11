"""A project's tree as it was each day, kept for the days its settings say
(R165), so a node gone wrong, or compromised, cannot destroy the original
through its synced copy.

What is kept is exactly what a node can change: every file the sync
carries (wssync's own walk, .git included), not what a node rebuilds. Each
file's contents are stored once by their hash, read-only, under objects/;
a day is a list of paths and hashes under days/<project>/. An unchanged
file costs nothing from one day to the next, and an unchanged size and
time reuse the last day's hash without reading the file again. The store
is the controller's (paths.py, project-snapshots), where no node API
reaches.

Taken once a day by a thread the server starts, pruned to the project's
days, and the objects no day names any more removed. A restore, the whole
tree as of a day or one file, first snapshots the tree as it is now, so a
restore can be undone, then writes through the same files the sync reads,
and tells the sync, so every node holding the project follows.
"""
import contextlib
import hashlib
import json
import os
import re
import stat as st
import threading
import time
from datetime import datetime
from pathlib import Path

import paths
import wssync

WORKSPACE = Path("/workspace")
days_of = None            # set by server.py: (project) -> days to keep, 0 for none
projects = None           # set by server.py: () -> [project names]
audit = None
CHECK_EVERY = 1800        # seconds between looks for a project with no snapshot today
DAY = re.compile(r"\d{4}-\d{2}-\d{2}(T\d{6}-before-restore)?")
_lock = threading.Lock()


def configure(*, workspace, days, names, audit_fn=None):
    """paths.py and wssync.py are configured by the server already; this
    takes what is the project settings' and the audit's."""
    globals().update(WORKSPACE=Path(workspace), days_of=days, projects=names, audit=audit_fn)


def _store():
    return paths.of("project-snapshots")


def _days_dir(project):
    return _store() / "days" / project


def _obj(sha):
    return _store() / "objects" / sha[:2] / sha


def _root(project):
    return wssync._root(project)


def _manifest(project, day):
    try:
        return json.loads((_days_dir(project) / f"{day}.json").read_text())
    except (OSError, ValueError):
        return None


def days(project):
    """Every day kept for the project, newest first: [{day, at, files, bytes}]."""
    out = []
    with contextlib.suppress(OSError):
        for f in _days_dir(project).glob("*.json"):
            if not DAY.fullmatch(f.stem):
                continue
            m = _manifest(project, f.stem) or {}
            files = m.get("files") or {}
            out.append({"day": f.stem, "at": int(m.get("at") or 0), "files": len(files),
                        "bytes": sum(int(v[1]) for v in files.values()),
                        "why": str(m.get("why") or "")})
    return sorted(out, key=lambda d: (d["at"], d["day"]), reverse=True)


def _put_object(path, size):
    """The file's contents into the store, once: (sha) of what was read."""
    h = hashlib.sha256()
    tmp = _store() / "objects" / f".in.{os.getpid()}.{threading.get_ident()}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "rb") as src, open(tmp, "wb") as out:
        for chunk in iter(lambda: src.read(1 << 20), b""):
            h.update(chunk)
            out.write(chunk)
    sha = h.hexdigest()
    dest = _obj(sha)
    if dest.exists():
        tmp.unlink(missing_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(tmp, 0o444)
        os.replace(tmp, dest)
    return sha


def take(project, why=""):
    """Snapshot the project's tree now. `why` names one that is not the
    day's own (before a restore), kept beside the day's rather than over it."""
    root = _root(project)
    prev = {}
    kept = days(project)
    if kept:
        prev = (_manifest(project, kept[0]["day"]) or {}).get("files") or {}
    files = {}
    for rel in wssync._walk(root):
        p = root / rel
        e = wssync._entry(p)
        if e is None:
            continue
        size, mtime, mode, link = e  # noqa: F841 (size rides the manifest below)
        if link:
            files[rel] = ["", 0, mtime, 0o777, link]
            continue
        was = prev.get(rel)
        if was and was[0] and was[1] == size and was[2] == mtime and _obj(was[0]).exists():
            files[rel] = [was[0], size, mtime, mode, ""]
            continue
        try:
            files[rel] = [_put_object(p, size), size, mtime, mode, ""]
        except OSError:
            continue
    now = time.time()
    name = datetime.fromtimestamp(now).strftime("%Y-%m-%d") \
        + (datetime.fromtimestamp(now).strftime("T%H%M%S") + "-" + why if why else "")
    d = _days_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{name}.json"
    tmp.write_text(json.dumps({"at": int(now), "why": why, "files": files}))
    os.replace(tmp, d / f"{name}.json")
    return {"ok": True, "day": name, "files": len(files)}


def prune(project, keep):
    """Days older than `keep` go; 0 keeps none."""
    cut = time.time() - keep * 86400
    for d in days(project):
        if keep == 0 or d["at"] < cut:
            (_days_dir(project) / f"{d['day']}.json").unlink(missing_ok=True)


def gc():
    """Objects no kept day names, removed."""
    used = set()
    top = _store() / "days"
    with contextlib.suppress(OSError):
        for f in top.glob("*/*.json"):
            with contextlib.suppress(OSError, ValueError):
                used |= {v[0] for v in (json.loads(f.read_text()).get("files") or {}).values() if v[0]}
    gone = 0
    with contextlib.suppress(OSError):
        for f in (_store() / "objects").glob("??/*"):
            if f.name not in used:
                with contextlib.suppress(OSError):
                    os.chmod(f, 0o644)
                    f.unlink()
                    gone += 1
    return gone


def daily():
    """Each project with days to keep and no snapshot today gets one; every
    project is pruned to its days; then the objects nobody names go."""
    today = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        for project in projects() if projects else []:
            try:
                keep = int(days_of(project)) if days_of else 0
            except (TypeError, ValueError, KeyError):
                continue
            try:
                if keep and not (_days_dir(project) / f"{today}.json").exists():
                    take(project)
                prune(project, keep)
            except (OSError, ValueError) as e:
                print(f"[snapshots] {project}: {type(e).__name__}: {e}", flush=True)
        gc()


def start():
    def loop():
        while True:
            try:
                daily()
            except Exception as e:                       # noqa: BLE001 (the loop must live)
                print(f"[snapshots] {type(e).__name__}: {e}", flush=True)
            time.sleep(CHECK_EVERY)
    threading.Thread(target=loop, name="snapshots", daemon=True).start()


def restore(project, day, rel="", who=""):
    """The whole tree as of `day`, or the one file `rel`. The tree as it is
    now is snapshotted first. Files are written whole into place; in a whole
    restore, files the day did not have are removed. Answers what changed."""
    if not DAY.fullmatch(day or ""):
        return {"error": "not a snapshot"}
    m = _manifest(project, day)
    if m is None:
        return {"error": f"no snapshot {day} of {project}"}
    files = m.get("files") or {}
    if rel and rel not in files:
        return {"error": f"{rel} was not in {project} on {day}"}
    with _lock:
        before = take(project, why="before-restore")
        root = _root(project)
        wrote = removed = 0
        for path, v in sorted(files.items()):
            if rel and path != rel:
                continue
            if not wssync._rel_ok(path):
                continue
            sha, _size, _mtime, mode, link = v
            p = root / path
            cur = wssync._entry(p)
            if link:
                if cur and cur[3] == link:
                    continue
                p.parent.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(FileNotFoundError):
                    p.unlink()
                os.symlink(link, p)
                wrote += 1
                continue
            if cur and not cur[3] and wssync._sha_file(p) == sha:
                continue
            src = _obj(sha)
            if not src.exists():
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(f".bbsync-restore-{p.name}")
            with open(src, "rb") as s, open(tmp, "wb") as out:
                for chunk in iter(lambda: s.read(1 << 20), b""):
                    out.write(chunk)
            os.chmod(tmp, st.S_IMODE(mode) or 0o644)
            if p.is_dir() and not p.is_symlink():
                tmp.unlink(missing_ok=True)
                continue
            os.replace(tmp, p)
            wrote += 1
        if not rel:
            for path in list(wssync._walk(root)):
                if path not in files:
                    with contextlib.suppress(OSError):
                        (root / path).unlink()
                        removed += 1
    # The sync sees it at once, and every node holding the project follows.
    with contextlib.suppress(Exception):
        wssync.changed(project)
    if audit:
        audit(who or "operator", "snapshot-restore", project, {"day": day, "path": rel, "wrote": wrote,
                                                              "removed": removed, "undo": before.get("day")})
    return {"ok": True, "wrote": wrote, "removed": removed, "undo": before.get("day")}
