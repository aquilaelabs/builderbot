"""Projects by id (R154, the operator, 8 Oct).

A project has three things that used to be one: a permanent number (its id),
the directory it lives in under /workspace, and the name people see. The
directory is still what every store keys a project by (the notebook, the
settings, the containers, the sessions, Claude Code's own paths), so nothing
of those moved; what changed is that a directory is never handed out twice.
A name taken by a live project, one in the trash or one deleted for good gets
the next free directory (Name-2, Name-3), and the name shown stays Name. So
a restore always fits back where it was, a new project never inherits an old
one's notebook or containers, and a rename is the shown name alone.

projects.json: {"next": N, "projects": {dir: {"id", "name", "state", "at"}}},
state being live, trashed or purged. Every directory found on disk without a
record is given one, named for itself, which is the whole migration.
"""
import json
import re
import threading
import time
from pathlib import Path

FILE = None
WORKSPACE = None
write_json = None
TRASH = ".trash"
STATES = ("live", "trashed", "purged")
NAME_MAX = 60

_lock = threading.RLock()
_cache = {"mtime": None, "data": None}


def configure(*, state, workspace, write_json):
    globals().update(FILE=Path(state) / "projects.json", WORKSPACE=Path(workspace),
                     write_json=write_json)
    _cache.update(mtime=None, data=None)


def _load():
    try:
        m = FILE.stat().st_mtime_ns
    except OSError:
        m = None
    if m is not None and m == _cache["mtime"] and _cache["data"] is not None:
        return _cache["data"]
    try:
        d = json.loads(FILE.read_text())
    except (OSError, ValueError, AttributeError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    ps = d.get("projects") if isinstance(d.get("projects"), dict) else {}
    d = {"next": int(d.get("next") or 1), "projects": {
        str(k): v for k, v in ps.items() if isinstance(v, dict)}}
    _cache.update(mtime=m, data=d)
    return d


def _save(d):
    write_json(FILE, d)
    try:
        _cache.update(mtime=FILE.stat().st_mtime_ns, data=d)
    except OSError:
        _cache.update(mtime=None, data=None)


def _add(d, dirname, name, state="live"):
    n = d["next"]
    d["next"] = n + 1
    d["projects"][dirname] = {"id": n, "name": name, "state": state, "at": int(time.time())}
    return d["projects"][dirname]


def _on_disk():
    """(live dirs, trashed dirs) as the workspace holds them now."""
    live, gone = set(), set()
    try:
        for p in WORKSPACE.iterdir():
            if p.is_dir() and not p.name.startswith("."):
                live.add(p.name)
    except OSError:
        pass
    try:
        for p in (WORKSPACE / TRASH).iterdir():
            if p.is_dir() and not p.name.startswith("."):
                gone.add(p.name)
    except OSError:
        pass
    return live, gone


def sync():
    """Give every directory on disk a record, and each record the state its
    directory is in. Cheap enough for the scan: two listdirs and, when
    nothing moved, no write."""
    live, gone = _on_disk()
    with _lock:
        d = _load()
        ps, changed = d["projects"], False
        for name in sorted(live):
            r = ps.get(name)
            if r is None:
                _add(d, name, name)
                changed = True
            elif r.get("state") != "live":
                r["name"] = unique_name(str(r.get("name") or name), but=name)
                r["state"] = "live"
                changed = True
        for name in sorted(gone):
            r = ps.get(name)
            if r is None:
                # From before ids: a second delete was numbered (X-2), and
                # the name it had is the one without the number.
                _add(d, name, re.sub(r"-\d+$", "", name), "trashed")["legacy"] = True
                changed = True
            elif r.get("state") == "live" and name not in live:
                r["state"] = "trashed"
                changed = True
        for name, r in ps.items():
            if r.get("state") in ("live", "trashed") and name not in live and name not in gone:
                r["state"] = "purged"
                changed = True
        if changed:
            _save(d)
        return d


def get(dirname):
    return dict((_load()["projects"].get(str(dirname or "")) or {}))


def label(dirname):
    """The name shown for a project's directory: its own, or the directory."""
    r = _load()["projects"].get(str(dirname or ""))
    return str((r or {}).get("name") or dirname or "")


def labels():
    return {k: str(v.get("name") or k) for k, v in _load()["projects"].items()}


def id_of(dirname):
    r = _load()["projects"].get(str(dirname or ""))
    return int(r["id"]) if r and r.get("id") else 0


def clean_name(raw):
    """A shown name: trimmed, one line, printable, at most NAME_MAX."""
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    s = "".join(ch for ch in s if ch.isprintable())
    return s[:NAME_MAX].strip()


def live_named(name, but=None):
    """The live project's directory shown under `name` (any case), or ""."""
    low = clean_name(name).lower()
    for k, r in _load()["projects"].items():
        if k != but and r.get("state") == "live" and str(r.get("name") or k).lower() == low:
            return k
    return ""


def unique_name(name, but=None):
    """`name`, or `name (2)`, `name (3)`: never the name a live project is
    shown under, so two clones of one repository read apart (the operator,
    8 Oct)."""
    name = clean_name(name)
    cand, n = name, 2
    while live_named(cand, but=but):
        cand = f"{name} ({n})"
        n += 1
    return cand


def new_dir(base):
    """A directory nothing has ever had: `base`, else base-2, base-3. Every
    record counts, purged ones too, and so does anything on disk."""
    with _lock:
        ps = _load()["projects"]
        live, gone = _on_disk()
        taken = {k.lower() for k in ps} | {k.lower() for k in live | gone}
        cand, n = base, 2
        while cand.lower() in taken:
            cand = f"{base}-{n}"
            n += 1
        return cand


def claim(dirname, name):
    """Record a new project's directory under its shown name."""
    with _lock:
        d = _load()
        r = d["projects"].get(dirname)
        shown = unique_name(clean_name(name) or dirname, but=dirname)
        if r is None:
            r = _add(d, dirname, shown)
        else:
            r.update(name=shown, state="live")
        _save(d)
        return dict(r)


def set_name(dirname, name):
    """A rename: the shown name alone. {ok} or {error}."""
    name = clean_name(name)
    if not name:
        return {"error": "a name needs at least one letter or digit in it"}
    with _lock:
        d = _load()
        r = d["projects"].get(dirname)
        if r is None or r.get("state") != "live":
            return {"error": f"{dirname} is not a project"}
        other = live_named(name, but=dirname)
        if other:
            return {"error": f"{name} is already a project's name"}
        was = str(r.get("name") or dirname)
        r["name"] = name
        _save(d)
        return {"ok": True, "dir": dirname, "name": name, "was": was}


def mark(dirname, state):
    """A project's directory moved to the trash, back, or deleted for good.
    Back, its name gets a number when a live project took it meanwhile."""
    with _lock:
        d = _load()
        r = d["projects"].get(dirname)
        if r is None:
            r = _add(d, dirname, dirname, state)
        if state == "live" and r.get("state") != "live":
            r["name"] = unique_name(str(r.get("name") or dirname), but=dirname)
        r["state"] = state
        _save(d)
        return dict(r)


def resolve(word):
    """A live project's directory from what somebody typed: the directory
    itself, else a shown name that is one project's. "" when neither."""
    word = str(word or "").strip()
    if not word:
        return ""
    ps = _load()["projects"]
    r = ps.get(word)
    if r is not None and r.get("state") == "live":
        return word
    return live_named(word)
