"""A project of several repositories (R136, the operator, 24 Oct).

A project today is one repository: its folder under /workspace, its notebook,
its git host link. A project may hold several: each repository stays what it
was (its folder, its record and name in registry.py, its notebook, its
remote, token and deploy key, forge, CI and releases, its version and
changelog, its signing keys and its dev instance), and the project over them
has a name and an id of its own (registry.py's `repos` state) and what one
session in all of them needs: its node, its agents, its people, the Agents
may dials, and what it grants other projects (prefs.GROUP_FIELDS). A
project that reads it reads every repository in it, the ones added later
too, with nothing changed (prefs.reads_trees). Nothing on disk moves.

project-repos.json: {"projects": {key: {"members": [dir, ...], "at": t}}},
the first member the one the project was made from. Kept apart from
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
    """The repositories of a project of them, in their order: the live ones
    (a member in the trash is out of it until it is back)."""
    rec = _load()["projects"].get(str(key or ""))
    if not rec or not registry.is_repos(key):
        return []
    return [m for m in rec["members"] if registry.is_project(m)]


def project_of(dirname):
    """The project of repositories this repository is in, or "": one at most."""
    dirname = str(dirname or "")
    for k, rec in _load()["projects"].items():
        if dirname in rec["members"] and registry.is_repos(k):
            return k
    return ""


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
    """{key: [members]} for every project of repositories."""
    return {k: members(k) for k in _load()["projects"] if registry.is_repos(k)}


def merge(into, dirs, name=""):
    """Repositories added to a project: `into` a project of repositories, or
    a repository on its own, which becomes the first of a new one named
    `name` (its own name when none is given). Refused, saying which, for a
    name that is no repository, one already in a project of repositories,
    or a project of them named as a repository. {ok, key, members, made} or
    {error}. Who may, and whether each repository can join (its lock, its
    archive, its node), is the server's to ask first."""
    into = str(into or "")
    dirs = [str(d) for d in dirs or [] if str(d)]
    if not dirs:
        return {"error": "name a repository to add"}
    with _lock:
        d = _load()
        made = False
        if registry.is_repos(into):
            key = into
        elif registry.is_project(into):
            if project_of(into):
                return {"error": f"{registry.label(into)} is already in {registry.label(project_of(into))}"}
            dirs = [into] + [x for x in dirs if x != into]
            key = ""
        else:
            return {"error": f"{into} is not a project"}
        for x in dirs:
            if registry.is_repos(x):
                return {"error": f"{registry.label(x)} is a project of repositories, not a repository: split its repositories out first"}
            if not registry.is_project(x):
                return {"error": f"{x} is not a repository here"}
            other = project_of(x)
            if other and other != key:
                return {"error": f"{registry.label(x)} is already in {registry.label(other)}"}
        if not key:
            rec = registry.claim_repos(name or registry.label(into), but=dirs)
            if rec.get("error"):
                return rec
            key, made = rec["key"], True
            d["projects"][key] = {"members": [], "at": int(time.time())}
        have = d["projects"].setdefault(key, {"members": [], "at": int(time.time())})["members"]
        added = [x for x in dirs if x not in have]
        have += added
        _save(d)
        return {"ok": True, "key": key, "members": list(have), "added": added, "made": made}


def split(dirname):
    """A repository taken out of its project of repositories, back to a
    project of its own. A project left with one repository is no longer one
    of several: that one is out too and the project's record is dropped.
    {ok, key, out: [the repositories now on their own], dropped} or {error}."""
    dirname = str(dirname or "")
    with _lock:
        key = project_of(dirname)
        if not key:
            return {"error": f"{registry.label(dirname)} is not in a project of repositories"}
        d = _load()
        rec = d["projects"][key]
        rec["members"] = [m for m in rec["members"] if m != dirname]
        out, dropped = [dirname], False
        if len([m for m in rec["members"] if registry.is_project(m)]) < 2:
            out += rec["members"]
            d["projects"].pop(key)
            dropped = True
        _save(d)
        if dropped:
            registry.drop_repos(key)
        return {"ok": True, "key": key, "out": out, "dropped": dropped}


def refusal(dirs, *, locked, archived, people, node):
    """Why these repositories cannot be one project, or "": the server's
    question before a merge, from what it read (the locked and archived
    names, each repository's people as a set of names, each one's own node,
    "" for none). One session works in every repository of a project, so
    each must be open to it, everybody on one must be on all, and they must
    be on one node."""
    lab = registry.label
    for d in dirs:
        if d in locked:
            return f"{lab(d)} is locked: unlock it first"
        if d in archived:
            return f"{lab(d)} is archived: bring it back first"
    first = dirs[0]
    for d in dirs[1:]:
        odd = sorted(people.get(d, set()) ^ people.get(first, set()))
        if odd:
            on, off = (first, d) if odd[0] in people.get(first, set()) else (d, first)
            return (f"{odd[0]} is on {lab(on)} but not on {lab(off)}: a project's session works in every "
                    f"repository in it, so everybody on it is on all of them. Put them on {lab(off)}, or "
                    f"take them off {lab(on)}, first")
    where = [(d, node.get(d) or "") for d in dirs if node.get(d)]
    if len({n for _, n in where}) > 1:
        (a, na), (b, nb) = where[0], next(x for x in where if x[1] != where[0][1])
        return (f"{lab(a)} works on {na} and {lab(b)} on {nb}: a project's repositories share its node, "
                f"so give them one first")
    return ""
