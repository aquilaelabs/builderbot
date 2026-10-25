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

projects.json: {"next": N, "projects": {dir: {"id", "name", "state", "at",
"moved"}}}, state being live, trashed or purged, and moved when it last
changed (the trash's "deleted 2 min ago"). A project (R138, repos.py) is a
record of its own in state `repos`: a key shaped like a directory and counted
as one, so no folder ever takes it, though none is on disk; its id and name
are the project's, and every repository is in one, keeping its own record,
folder and name. A project's name is a title (spaces and punctuation kept,
title()); a repository's is GitHub's (clean_name). Each is unique among its
own kind, so a project and its repository may share one. Only BuilderBot
makes a repository: a folder made by hand on the share is not one. On the
first run every folder already there is recorded, which is the whole
migration.
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
STATES = ("live", "trashed", "purged", "repos")
# The states a name is taken in: a live project's, and a project of
# repositories'.
NAMED = ("live", "repos")
# GitHub's for a repository's name (the operator, 9 Oct): a project is one,
# or becomes one, and a name GitHub would refuse or rewrite is not one to show.
NAME_MAX = 100

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
    """Bring the records in step with the disk. Only BuilderBot makes a
    project (create, clone, an imported archive: claim()); a folder made by
    hand on the share is not one and is not listed (the operator, 8 Oct).
    The one exception is the first run, when every folder already there is
    recorded, which is the whole migration. After that a record follows its
    folder: gone from the workspace it is trashed or purged, and moved back
    by hand from the trash it is live again."""
    live, gone = _on_disk()
    with _lock:
        first = not FILE.exists()
        d = _load()
        ps, changed = d["projects"], first
        if first:
            for name in sorted(live):
                _add(d, name, unique_name(name, but=name))
            for name in sorted(gone - live):
                # A numbered delete from before ids (X-2) was X.
                _add(d, name, re.sub(r"-\d+$", "", name), "trashed")["legacy"] = True
        # A name stored before GitHub's rules held here ("Turing Lens", or a
        # clash numbered "Name (2)") is brought to them once, as it would have
        # been given: numbered if another live project already has it.
        for name, r in ps.items():
            was = str(r.get("name") or "")
            if was and clean_name(was) != was:
                r["name"] = clean_name(was) or name
                if r.get("state") == "live":
                    r["name"] = unique_name(r["name"], but=name)
                changed = True
        for name, r in ps.items():
            st = r.get("state")
            if st == "live" and name not in live:
                r["state"] = "trashed" if name in gone else "purged"
                changed = True
            elif st == "trashed" and name in live and name not in gone:
                # Put back by hand with a mv: the same folder, so the same
                # project. One made by hand while the trashed one is still
                # in the trash is not, and stays unlisted.
                r["name"] = unique_name(str(r.get("name") or name), but=name)
                r["state"] = "live"
                changed = True
            elif st == "trashed" and name not in gone and name not in live:
                r["state"] = "purged"
                changed = True
        if changed:
            _save(d)
        return d


def is_project(dirname):
    """Whether this folder is a project: recorded live, never just present."""
    r = _load()["projects"].get(str(dirname or ""))
    return bool(r) and r.get("state") == "live"


def get(dirname):
    return dict((_load()["projects"].get(str(dirname or "")) or {}))


def label(dirname):
    """The name shown for a project's directory: its own, or the directory."""
    r = _load()["projects"].get(str(dirname or ""))
    return str((r or {}).get("name") or dirname or "")


def pid(dirname):
    """The project's id as it is written, P and its number (P3), or "": the
    registry's number, never handed out twice, so it names one project for
    good where a name can change."""
    n = (_load()["projects"].get(str(dirname or "")) or {}).get("id")
    return f"P{n}" if n else ""


def labels():
    return {k: str(v.get("name") or k) for k, v in _load()["projects"].items()}


def clean_name(raw):
    """A shown name by GitHub's rules for a repository's: ASCII letters,
    digits, - _ and . only, each run of anything else one -, as GitHub turns
    "Turing Lens" into Turing-Lens, at most NAME_MAX, and never . or ..
    (the operator, 9 Oct: a rename to "Turing Lens" kept the space)."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(raw or "").strip()).strip("-")
    s = s[:NAME_MAX].strip("-")
    return "" if s in (".", "..") else s


def title(raw):
    """A project's name (R138, the operator, 25 Oct): what was typed, spaces
    and punctuation kept, each run of whitespace one space, no control
    character, at most NAME_MAX."""
    s = " ".join("".join(ch for ch in str(raw or "") if ch.isprintable()).split())
    return s[:NAME_MAX].strip()


def live_named(name, but=None, kind=None):
    """The live repository's directory, or the project's key, shown under
    `name` (any case), or "". `kind` "live" or "repos" asks one kind alone;
    with neither, a repository first: a project and its repository commonly
    share a name, and what a name is asked for by (a session's bb -p NAME, a
    notebook) is a repository's."""
    want = str(name or "").strip().lower()
    want_live = clean_name(name).lower()
    found = ""
    for k, r in _load()["projects"].items():
        st = r.get("state")
        if k == but or st not in NAMED or (kind and st != kind):
            continue
        shown = str(r.get("name") or k).lower()
        if st == "live" and shown == want_live:
            return k
        if st == "repos" and shown == want:
            found = found or k
    return found


def is_repos(key):
    """Whether this key is a project's (R138), as against a repository's."""
    r = _load()["projects"].get(str(key or ""))
    return bool(r) and r.get("state") == "repos"


def repos_keys():
    """Every project's key."""
    return sorted(k for k, r in _load()["projects"].items() if r.get("state") == "repos")


def claim_repos(name):
    """A new project (R138): its key, a directory nothing has had, made from
    its name, and its record under the name, refused where another project
    has it. The record with its key, or {error}."""
    with _lock:
        d = _load()
        shown = title(name)
        if not shown or not any(ch.isalnum() for ch in shown):
            return {"error": "a project's name needs at least one letter or digit in it"}
        if live_named(shown, kind="repos"):
            return {"error": f"{shown} is already a project's name"}
        key = new_dir(clean_name(shown) or "project")
        r = _add(d, key, shown, "repos")
        _save(d)
        return dict(r, key=key)


def drop_repos(key):
    """A project deleted (R138, only with no repository left in it): purged,
    so its key and id are never handed out again, as a deleted
    repository's are."""
    with _lock:
        d = _load()
        r = d["projects"].get(key)
        if r is not None and r.get("state") == "repos":
            r["state"] = "purged"
            r["moved"] = int(time.time())
            _save(d)


def unique_name(name, but=None):
    """`name`, or `name-2`, `name-3`, as a directory is numbered: never the
    name a live project is shown under, so two clones of one repository read
    apart (the operator, 8 Oct), and a name GitHub would take as it is."""
    name = clean_name(name)
    cand, n = name, 2
    while live_named(cand, but=but, kind="live"):
        sfx = f"-{n}"
        cand = name[:NAME_MAX - len(sfx)] + sfx
        n += 1
    return cand


def taken_dirs():
    """Every directory a new project may not have, lowercased: each record,
    purged ones too (their notebook, settings, containers and transcripts
    are kept under it, and a new project would inherit them), and anything
    on disk. The New project dialog reads it to say before Create when the
    folder will be numbered (B63)."""
    with _lock:
        ps = _load()["projects"]
        live, gone = _on_disk()
        return sorted({k.lower() for k in ps} | {k.lower() for k in live | gone})


def new_dir(base):
    """A directory nothing has ever had: `base`, else base-2, base-3. Every
    record counts, purged ones too, and so does anything on disk."""
    with _lock:
        taken = set(taken_dirs())
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


def forget(dirname):
    """A create that never took (a clone that failed, an archive refused,
    git init failing): its record goes, so its folder is free again and the
    next try with the name lands in it rather than in NAME-2 (B93). Only a
    record whose folder is not there: nothing was ever kept under it."""
    with _lock:
        d = _load()
        if dirname in d["projects"] and not (WORKSPACE / dirname).exists():
            d["projects"].pop(dirname)
            _save(d)
            return True
        return False


def live_dirs():
    """Every live repository's directory."""
    return sorted(k for k, r in _load()["projects"].items() if r.get("state") == "live")


def set_name(dirname, name):
    """A rename: the shown name alone, a repository's by GitHub's rules and a
    project's a title, unique among its own kind. {ok} or {error}."""
    with _lock:
        d = _load()
        r = d["projects"].get(dirname)
        if r is None or r.get("state") not in NAMED:
            return {"error": f"{dirname} is not a project"}
        kind = r.get("state")
        name = title(name) if kind == "repos" else clean_name(name)
        if not name or not any(ch.isalnum() for ch in name):
            return {"error": "a name needs at least one letter or digit in it"}
        other = live_named(name, but=dirname, kind=kind)
        if other:
            return {"error": f"{name} is already a {'project' if kind == 'repos' else 'repository'}'s name"}
        was = str(r.get("name") or dirname)
        r["name"] = name
        _save(d)
        return {"ok": True, "dir": dirname, "name": name, "was": was}


def note_project(dirname, key):
    """The project a repository last belonged to, kept on its record as it
    goes to the trash (R138): what the trash says it belonged to, and where
    a restore puts it back."""
    with _lock:
        d = _load()
        r = d["projects"].get(str(dirname or ""))
        if r is not None:
            r["project"] = str(key or "")
            _save(d)


def last_project(dirname):
    """The project this repository belonged to when it went to the trash."""
    return str((_load()["projects"].get(str(dirname or "")) or {}).get("project") or "")


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
        r["moved"] = int(time.time())
        _save(d)
        return dict(r)


def resolve(word):
    """A live project's directory, or a project of repositories' key (R136),
    from what somebody typed: the directory or key itself, its id (P3), else
    a shown name that is one project's. "" when none of them."""
    word = str(word or "").strip()
    if not word:
        return ""
    ps = _load()["projects"]
    r = ps.get(word)
    if r is not None and r.get("state") in NAMED:
        return word
    # Its id, as the page and a session's name write it (P3).
    if re.fullmatch(r"[Pp]\d+", word):
        n = int(word[1:])
        for k, r in ps.items():
            if r.get("state") in NAMED and r.get("id") == n:
                return k
        return ""
    return live_named(word)
