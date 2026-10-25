"""Projects and their repositories (R136, R138).

A project is made first, with a name alone, and repositories are added to
it: every repository is in exactly one project, and a project may hold none.
Each repository stays what it was (its folder, its record and name in
registry.py, its notebook, its remote, token and deploy key, forge, CI and
releases, its version and changelog, its signing keys and its dev
instance), and the project over them has a name and an id of its own
(registry.py's `repos` state) and what one session in all of them needs: its
node, its agents, its people, the Agents may dials, and what it grants other
projects (prefs.GROUP_FIELDS). A project that reads it reads every
repository in it, the ones added later too (prefs.reads_trees). A repository
goes to the trash out of its project, which its record remembers
(registry.note_project); a project is deleted only with none left in it.
Nothing on disk moves.

project-repos.json: {"projects": {key: {"members": [dir, ...], "at": t}}},
the first member the one a session starts in. Kept apart from
project-groups.json, which is each person's own grouping of the Projects
page's cards and has nothing to do with this.
"""
import json
import threading
import time
from pathlib import Path

FILE = None
write_json = None
registry = None

_lock = threading.RLock()
_cache = {"mtime": None, "data": None}


def configure(*, state, write_json, registry):
    globals().update(FILE=Path(state) / "project-repos.json", write_json=write_json, registry=registry)
    _cache.update(mtime=None, data=None)


def _load():
    try:
        m = FILE.stat().st_mtime_ns
    except (OSError, AttributeError):
        m = None
    if m is not None and m == _cache["mtime"] and _cache["data"] is not None:
        return _cache["data"]
    try:
        d = json.loads(FILE.read_text())
    except (OSError, ValueError, AttributeError):
        d = {}
    ps = d.get("projects") if isinstance(d, dict) and isinstance(d.get("projects"), dict) else {}
    out = {}
    for k, v in ps.items():
        if not isinstance(v, dict):
            continue
        ms = [str(x) for x in (v.get("members") or []) if isinstance(x, str) and x]
        out[str(k)] = {"members": list(dict.fromkeys(ms)), "at": int(v.get("at") or 0)}
    d = {"projects": out}
    _cache.update(mtime=m, data=d)
    return d


def _save(d):
    write_json(FILE, d)
    try:
        _cache.update(mtime=FILE.stat().st_mtime_ns, data=d)
    except OSError:
        _cache.update(mtime=None, data=None)


def members(key):
    """A project's repositories, in their order: the live ones."""
    rec = _load()["projects"].get(str(key or ""))
    if not rec or not registry.is_repos(key):
        return []
    return [m for m in rec["members"] if registry.is_project(m)]


def project_of(dirname):
    """The project this repository is in, or "": one at most."""
    dirname = str(dirname or "")
    for k, rec in _load()["projects"].items():
        if dirname in rec["members"] and registry.is_repos(k):
            return k
    return ""


def key_of(name):
    """The project a name stands for (R138): a project's own key as itself,
    a repository's its project's, anything else as itself. What every store
    of a project's (its people, roles, owner, marks) is keyed by, so a
    repository is reached through its project."""
    name = str(name or "")
    if registry.is_repos(name):
        return name
    return project_of(name) or name


def expand(names):
    """Project names as the trees they stand for: a project of repositories
    as each of its repositories, at the time of asking, so one added later
    is in it with nothing changed; any other name as itself. In order, once
    each."""
    out = []
    for n in names or []:
        for t in (members(n) if registry.is_repos(n) else [n]):
            if t not in out:
                out.append(t)
    return out


def all_members():
    """{key: [members]} for every project, an empty one with []."""
    return {k: members(k) for k in _load()["projects"] if registry.is_repos(k)}


def create(name):
    """A new project with no repository in it yet (R138). {ok, key, name,
    id} or {error}."""
    with _lock:
        rec = registry.claim_repos(name)
        if rec.get("error"):
            return rec
        d = _load()
        d["projects"][rec["key"]] = {"members": [], "at": int(time.time())}
        _save(d)
        return {"ok": True, "key": rec["key"], "name": rec["name"], "id": f"P{rec['id']}"}


def place():
    """Every live repository in a project (R138): one in none (an imported
    archive, a clone, a folder recorded since migration 0010 ran) gets a
    project of its own, named as it is shown, with its id beside the name
    where that is another project's already. Cheap when there is nothing
    to place, so the status read asks it every time. [(key, dirname)] for
    each it made, for the server to carry the repository's owner and
    settings over (membership.adopt, prefs.adopt)."""
    with _lock:
        inside = {m for ms in all_members().values() for m in ms}
        made = []
        for dirname in registry.live_dirs():
            if dirname in inside:
                continue
            shown = registry.label(dirname)
            if registry.live_named(shown, kind="repos"):
                shown = f"{shown} ({registry.pid(dirname)})"
            got = create(shown)
            if got.get("error"):
                continue
            add(got["key"], dirname)
            made.append((got["key"], dirname))
        return made


def add(key, dirname):
    """A repository put into a project: one in no project yet (a new one, or
    one back from the trash). {ok, key, members} or {error}."""
    key, dirname = str(key or ""), str(dirname or "")
    with _lock:
        if not registry.is_repos(key):
            return {"error": f"{key} is not a project"}
        if not registry.is_project(dirname):
            return {"error": f"{dirname} is not a repository here"}
        other = project_of(dirname)
        if other and other != key:
            return {"error": f"{registry.label(dirname)} is already in {registry.label(other)}"}
        d = _load()
        have = d["projects"].setdefault(key, {"members": [], "at": int(time.time())})["members"]
        if dirname not in have:
            have.append(dirname)
        _save(d)
        return {"ok": True, "key": key, "members": [m for m in have if registry.is_project(m)]}


def move(dirname, to):
    """A repository moved into another project. {ok, was, key, members} or
    {error}; who may, and whether it can (a session on either running), is
    the server's to ask first."""
    dirname, to = str(dirname or ""), str(to or "")
    with _lock:
        was = project_of(dirname)
        if was == to:
            return {"error": f"{registry.label(dirname)} is already in {registry.label(to)}"}
        if not registry.is_repos(to):
            return {"error": f"{to} is not a project"}
        if was:
            d = _load()
            d["projects"][was]["members"] = [m for m in d["projects"][was]["members"] if m != dirname]
            _save(d)
        got = add(to, dirname)
        if got.get("error") and was:
            add(was, dirname)
            return got
        return dict(got, was=was)


def detach(dirname):
    """A repository out of its project, as it goes to the trash: the project
    it was in is kept on its record (registry.note_project), and is
    returned, or ""."""
    dirname = str(dirname or "")
    with _lock:
        was = project_of(dirname)
        if not was:
            return ""
        d = _load()
        d["projects"][was]["members"] = [m for m in d["projects"][was]["members"] if m != dirname]
        _save(d)
        registry.note_project(dirname, was)
        return was


def delete(key):
    """A project deleted, only with no repository left in it (R138, the
    operator, 25 Oct): nothing ever ends up in the trash without a project
    to go back to. {ok} or {error}."""
    key = str(key or "")
    with _lock:
        if not registry.is_repos(key):
            return {"error": f"{key} is not a project"}
        left = members(key)
        if left:
            return {"error": f"{registry.label(key)} still holds {', '.join(registry.label(m) for m in left)}: "
                             "move or delete its repositories first"}
        d = _load()
        d["projects"].pop(key, None)
        _save(d)
        registry.drop_repos(key)
        return {"ok": True, "key": key}
