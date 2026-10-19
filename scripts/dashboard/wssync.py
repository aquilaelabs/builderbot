"""A node's projects as a synced copy (R162), the one way a node holds them:
no node mounts the controller's disk (R163).

The controller's copy stays the original. A node holds each project bound
to it as a local copy under /workspace, and its
agent keeps the two in step over the agent API, the one connection a node
behind a one-way tunnel may open:

    state   every file of a project as the controller has it, and the revision
    since   what changed after a revision the node already has
    get     one file's bytes (channel.fetch, the verb sync-file)
    put     one file the node changed, with the hash it changed it FROM

Changes reach a node without the controller connecting to it: a put, a
write from VS Code (files.py) or a change a scan finds bumps the project's
revision and leaves a hint for each synced node of the project, which its
held work request takes at once (nodes.sync_hint), and the agent asks
`since` on its own every few seconds besides.

A put whose base is not what the controller has now is a CONFLICT: whichever
reached the controller first stays, and the node's version is kept beside it
as NAME.conflict-NODE-TIME.EXT (inside .git, under .git/bbsync-conflicts/,
where a stray file would not be a file in the project), which syncs to
everyone like any file, and is listed in the bell until it is deleted.

The index is a table (migrations/0005): one row per file with its hash,
size, mtime, mode, a symlink's target and the revision it last changed at;
a deletion stays as a row with gone set. It is the controller's record of
the share, refreshed by a scan of sizes and times at most every SCAN_EVERY
seconds per project when a node asks, and file by file before a put is
judged, so a change made on the share some other way is found.
"""
import contextlib
import hashlib
import os
import re
import stat as st
import subprocess
import tarfile
import threading
import time
from pathlib import Path

import db

WORKSPACE = None
nodes = None              # nodes.py: sync_hint, node
bound = None              # (project) -> [node ids in sync mode the project is bound to]
on_change = None          # (project) -> None: files.py's own scan, for VS Code
audit = None

# Not synced: what a node rebuilds for itself, and the map's own index.
# Everything else is, .git and dist/ included: a session commits on the
# node, and a build there lands its artifacts in dist/ for the Artifacts tab.
SKIP_DIRS = {"node_modules", ".gradle", "__pycache__", ".venv", "venv", ".next", ".cache", ".bb-map",
             ".pytest_cache", ".mypy_cache", ".ruff_cache"}
# ...and what is out by where it is: Claude Code's worktrees for its own
# agents, each a checkout whose .git file the controller refuses, so syncing
# them held the project behind and bb git push with it (B68).
SKIP_UNDER = (".claude/worktrees",)
TMP = ".bbsync-"
MAX_FILE = 512 * 1024 * 1024
SCAN_EVERY = 2.0
CONFLICTS_KEPT = 200

_locks = {}               # project -> RLock: one writer of a project's index at a time
_locks_lock = threading.Lock()
_index = {}               # project -> {path: row}, loaded once, written through
_scanned = {}             # project -> monotonic time of the last scan
_conflicts = []           # [{project, path, kept_as, node, at}], newest last
_moved = threading.Condition()   # notified on every change: a device's long poll waits on it

# A person's device (R270, R272): its id is "dev:" and the device's id, in
# the place a node's id goes. The device route has already checked that its
# person may edit the project (the editor's door, ftp.access_for), so the
# node scope does not apply; .git is never served to one or taken from one,
# as the editor serves none, and a conflict copy is named for the device.
DEV = "dev:"
device_name = lambda did: did   # noqa: E731 (set by configure_devices: (device id) -> its name)


def configure_devices(*, name_of):
    global device_name
    device_name = name_of


def _is_dev(nid):
    return str(nid or "").startswith(DEV)


def _hidden(nid, rel, link=""):
    """What a device is never sent and never takes: .git, since the working
    copy is a person's and the history the controller's, and a symbolic
    link, which Windows makes only with a privilege it seldom grants (one
    the app could not make would read to it as deleted and go up as such)."""
    return _is_dev(nid) and (".git" in str(rel).split("/") or bool(link))


def _who(nid):
    if _is_dev(nid):
        return device_name(nid[len(DEV):]) or nid
    return (nodes.node(nid) or {}).get("name") or nid


def configure(*, workspace, nodes_module, bound_nodes, changed=None, audit_fn=None):
    globals().update(WORKSPACE=Path(workspace), nodes=nodes_module, bound=bound_nodes,
                     on_change=changed, audit=audit_fn)


def _lock(project):
    with _locks_lock:
        return _locks.setdefault(project, threading.RLock())


# ---- paths ----------------------------------------------------------------------

def skipped(rel):
    """Whether a path inside a project is left out of sync."""
    parts = rel.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]) or parts[-1] in SKIP_DIRS:
        return True
    if any(rel == u or rel.startswith(u + "/") for u in SKIP_UNDER):
        return True
    if parts[-1].startswith(TMP):
        return True
    # git's own locks: a moment's file, and the wrong thing to hand another
    # machine's git.
    return ".git" in parts and parts[-1].endswith(".lock")


# A second account's worktree of a project (session_dir in lib/common.sh):
# its own sync unit beside the project, named for where it lives under the
# projects root, so it reaches every node holding the project and comes back
# from the one it was made on (B615). A dot directory, so no project scan
# meets it.
WT_UNIT = re.compile(r"\.worktrees/([A-Za-z0-9][A-Za-z0-9._-]*)/(u_[0-9a-f]{8})")


def _worktrees():
    return Path(os.environ.get("BB_WORKTREES") or str(WORKSPACE / ".worktrees"))


def worktree_of(unit):
    """(project, uid) for a worktree's unit name, else None."""
    m = WT_UNIT.fullmatch(unit or "")
    return (m.group(1), m.group(2)) if m else None


def worktrees_of(project):
    """The unit names of a project's worktrees here."""
    d = _worktrees() / project
    try:
        return sorted(f".worktrees/{project}/{u.name}" for u in d.iterdir()
                      if u.is_dir() and not u.is_symlink() and re.fullmatch(r"u_[0-9a-f]{8}", u.name))
    except OSError:
        return []


def worktree_unit(project, uid):
    """The unit of this account's worktree of the project, when the
    controller holds one: the session gate waits for it on a node."""
    unit = f".worktrees/{project}/{uid}"
    return unit if worktree_of(unit) and (_worktrees() / project / uid).is_dir() else ""


def _root(project, make=False):
    wt = worktree_of(project)
    if wt:
        # A worktree a node made first is made here as it arrives, with the
        # .git line git itself writes (a node never sends that file:
        # git_guard), so git on the controller finds it as the worktree it is.
        if not _there(wt[0]):
            raise ValueError("no such project")
        r = _worktrees() / wt[0] / wt[1]
        if not r.is_dir():
            if not make or not (WORKSPACE / wt[0] / ".git" / "worktrees" / wt[1]).is_dir():
                raise ValueError("no such worktree")
            r.mkdir(parents=True, exist_ok=True)
        dot = r / ".git"
        if make and not dot.exists():
            dot.write_text(f"gitdir: {WORKSPACE / wt[0] / '.git' / 'worktrees' / wt[1]}\n")
        return r
    if not re.fullmatch(r"[A-Za-z0-9._-]+", project or "") or project.startswith("."):
        raise ValueError("no such project")
    r = WORKSPACE / project
    if not r.is_dir():
        raise ValueError("no such project")
    return r


def _rel_ok(rel):
    rel = str(rel or "")
    parts = rel.split("/")
    return bool(rel) and not rel.startswith("/") and all(p not in ("", ".", "..") for p in parts) \
        and "\0" not in rel and len(rel) < 4096


def _entry(p):
    """(size, mtime_ns, mode, link) of a file or a symlink, None for what is
    not synced: a directory, a device, a link that leaves the project (a
    Gradle build directory pointed at the node's own disk)."""
    try:
        s = p.lstat()
    except OSError:
        return None
    if st.S_ISLNK(s.st_mode):
        t = os.readlink(p)
        if os.path.isabs(t):
            return None
        return (0, s.st_mtime_ns, 0o777, t)
    if not st.S_ISREG(s.st_mode) or s.st_size > MAX_FILE:
        return None
    return (s.st_size, s.st_mtime_ns, st.S_IMODE(s.st_mode), "")


def _sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def link_sha(target):
    return hashlib.sha256(b"link:" + target.encode()).hexdigest()


def _walk(root):
    """Every file and symlink under root not skipped, as relative paths."""
    for d, dirs, files in os.walk(root):
        rd = os.path.relpath(d, root)
        rd = "" if rd == "." else rd + "/"
        keep = []
        for x in dirs:
            if os.path.islink(os.path.join(d, x)):
                files.append(x)                # a link to a directory is a link
            elif not skipped(rd + x + "/_"):
                keep.append(x)
        dirs[:] = keep
        for f in files:
            rel = rd + f
            if not skipped(rel):
                yield rel


# ---- the index ------------------------------------------------------------------

def _load(project):
    if project not in _index:
        _index[project] = {r["path"]: r for r in db._rows(
            "SELECT path, sha, size, mtime_ns, mode, link, rev, gone FROM sync_files WHERE project = ?",
            (project,))}
    return _index[project]


def rev_of(project):
    r = db._rows("SELECT rev FROM sync_projects WHERE project = ?", (project,))
    return int(r[0]["rev"]) if r else 0


def _bump(project):
    cur = rev_of(project) + 1
    db._exec("INSERT INTO sync_projects (project, rev, scanned) VALUES (?, ?, ?) "
             "ON CONFLICT(project) DO UPDATE SET rev = excluded.rev", (project, cur, int(time.time())))
    return cur


def _record(project, rel, sha, ent, gone=False):
    """One file's new row, at a new revision. The caller holds the lock."""
    rev = _bump(project)
    size, mtime, mode, link = ent if ent else (0, 0, 0, "")
    row = {"path": rel, "sha": sha, "size": size, "mtime_ns": mtime, "mode": mode, "link": link,
           "rev": rev, "gone": 1 if gone else 0}
    db._exec("INSERT INTO sync_files (project, path, sha, size, mtime_ns, mode, link, rev, gone) "
             "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(project, path) DO UPDATE SET "
             "sha = excluded.sha, size = excluded.size, mtime_ns = excluded.mtime_ns, mode = excluded.mode, "
             "link = excluded.link, rev = excluded.rev, gone = excluded.gone",
             (project, rel, sha, size, mtime, mode, link, rev, row["gone"]))
    _load(project)[rel] = row
    return rev


def _same(row, ent):
    return row and not row["gone"] and (row["size"], row["mtime_ns"], row["mode"], row["link"]) == ent


def _look(project, root, rel):
    """Bring one path's row up to what is on disk. True when it moved."""
    idx = _load(project)
    row = idx.get(rel)
    ent = _entry(root / rel)
    if ent is None:
        if row and not row["gone"]:
            _record(project, rel, "", None, gone=True)
            return True
        return False
    if _same(row, ent):
        return False
    try:
        sha = link_sha(ent[3]) if ent[3] else _sha_file(root / rel)
    except OSError:
        return False
    if row and not row["gone"] and row["sha"] == sha and row["mode"] == ent[2] and row["link"] == ent[3]:
        # Touched, not changed: the new time, no new revision.
        row.update(size=ent[0], mtime_ns=ent[1])
        db._exec("UPDATE sync_files SET size = ?, mtime_ns = ? WHERE project = ? AND path = ?",
                 (ent[0], ent[1], project, rel))
        return False
    _record(project, rel, sha, ent)
    return True


def scan(project, force=False):
    """Bring the project's index up to the share, at most every SCAN_EVERY
    seconds unless forced. Wakes the synced nodes when anything moved."""
    root = _root(project)
    with _lock(project):
        if not force and time.monotonic() - _scanned.get(project, 0) < SCAN_EVERY:
            return False
        idx = _load(project)
        seen, moved = set(), False
        for rel in _walk(root):
            seen.add(rel)
            moved |= _look(project, root, rel)
        for rel, row in list(idx.items()):
            if not row["gone"] and rel not in seen:
                _record(project, rel, "", None, gone=True)
                moved = True
        _scanned[project] = time.monotonic()
    if moved:
        _wake(project)
    return moved


def _wake(project, but=""):
    rev = rev_of(project)
    for nid in _watchers(project):
        if nid != but:
            nodes.sync_hint(nid, project, rev)
    with _moved:
        _moved.notify_all()


def wait_moved(project, rev, timeout):
    """Hold until the project's revision passes `rev` or `timeout` seconds
    go by: a device's long poll, as a node's held work request is its."""
    end = time.monotonic() + timeout
    while True:
        # A change made here some other way (a write through the editor's
        # door, a session on the controller) is only seen by a scan: one
        # every few seconds while it waits, held to SCAN_EVERY by scan().
        with contextlib.suppress(ValueError):
            scan(project)
        left = end - time.monotonic()
        with _moved:
            if rev_of(project) > rev:
                return True
            if left <= 0:
                return False
            _moved.wait(min(left, 3.0))


def held_changed():
    """A project's nodes or what it reads changed (the settings dialog): every
    synced node is told to ask again which projects it holds now, so a
    project bound to a node starts its first copy at once rather than at
    the node's next look of its own (ASK_EVERY there), and one unbound or
    no longer read stops being kept in step. The hint names no project: the
    agent asks again whenever a hint names one it does not hold."""
    for nid in nodes.sync_node_ids() if nodes else ():
        nodes.sync_hint(nid, "", -1)


def changed(project):
    """A write made here some other way (VS Code, files.py): seen now."""
    with contextlib.suppress(ValueError):
        scan(project, force=True)


# ---- what a node asks ------------------------------------------------------------

def _row_out(r):
    return [r["path"], r["sha"], r["size"], r["mode"], r["link"], r["gone"]]


def may(nid, project, write=False):
    """Why this node may not sync the project, or "". A project a bound
    project reads comes down to the node read-only (R163): it may be read,
    never written. A worktree is its project's: read and written by the
    nodes the project is bound to, and no other."""
    wt = worktree_of(project)
    if _is_dev(nid):
        return f"{project} is a worktree: a device syncs a project" if wt else ""
    if wt:
        return "" if wt[0] in (bound_projects(nid) if nodes else []) \
            else f"{wt[0]} is not a project this node holds as a synced copy"
    if project in (bound_projects(nid) if nodes else []):
        return ""
    if not write and project in read_projects(nid):
        return ""
    if project in read_projects(nid):
        return f"{project} is read-only on this node: a project bound here reads it"
    return f"{project} is not a project this node holds as a synced copy"


_reads_of = lambda project: []   # noqa: E731 (set by configure_reads: (project) -> [projects it reads])


def configure_reads(fn):
    globals()["_reads_of"] = fn


def read_projects(nid):
    """The projects this node's bound projects read, less the bound ones:
    a session there sees them read-only at /workspace/NAME, as it does on
    the share."""
    own = set(bound_projects(nid))
    out = set()
    for p in own:
        out |= set(_reads_of(p) or [])
    return sorted(p for p in out - own if _there(p))


def _watchers(project):
    """The nodes that hold this project, bound to it or reading it."""
    wt = worktree_of(project)
    if wt:
        return list(bound(wt[0]) if bound else [])
    out = list(bound(project) if bound else [])
    for q in _all_projects():
        if project in (_reads_of(q) or []):
            out += [n for n in (bound(q) if bound else []) if n not in out]
    return out


def bound_projects(nid):
    return [p for p in _all_projects() if nid in (bound(p) if bound else [])]


_names = list             # set by configure_projects: () -> [project names]


def _there(p):
    """A project on the controller's disk: a name the settings still carry
    for a project since deleted is none, or a node holding it is told of one
    that answers "no such project" forever (walkme on the dev controller,
    9 Oct)."""
    return bool(re.fullmatch(r"[A-Za-z0-9._-]+", p or "")) and not p.startswith(".") \
        and (WORKSPACE / p).is_dir()


def _all_projects():
    return [p for p in _names() if _there(p)]


# The controller's own look at the copies the nodes hold (B643, 11 Oct): a
# change made straight in a project here, not through a verb that scans, is
# found by this every LOOK_EVERY seconds and announced to the nodes holding
# it in their held work request. Before, each node asked `since` for every
# project every ten seconds and that ask was what scanned: 87 posts a
# minute at 0.44s each with two synced nodes, most of the server's time.
LOOK_EVERY = float(os.environ.get("BB_SYNC_LOOK_EVERY") or 10)


def held():
    """Every project and worktree some node holds a copy of: the projects
    with settings, and what they read, which may have none of its own (a
    read-only project was never looked at, so a change made here never
    came down: wssync.mjs, 11 Oct)."""
    names = list(_all_projects())
    for q in list(names):
        names += [r for r in (_reads_of(q) or []) if r not in names and _there(r)]
    out = []
    for p in names:
        for unit in [p, *worktrees_of(p)]:
            if _watchers(unit):
                out.append(unit)
    return out


def look_loop():
    """Scan what the nodes hold, on a timer; scan() wakes them when it moved."""
    while True:
        time.sleep(LOOK_EVERY)
        try:
            units = held()
        except Exception as e:   # noqa: BLE001 (the loop outlives one bad pass)
            print(f"[wssync] look: {type(e).__name__}: {e}", flush=True)
            continue
        for unit in units:
            try:
                scan(unit)
            except Exception as e:   # noqa: BLE001 (one project's trouble is not the loop's)
                print(f"[wssync] {unit}: {type(e).__name__}: {e}", flush=True)


def configure_projects(fn):
    globals()["_names"] = fn


def projects(nid):
    """The projects this node holds as a synced copy, and each one's
    revision, for the agent to compare with its own."""
    conf = (nodes.node(nid) or {}).get("config") or {}
    mode = conf.get("workspace") or "sync"
    if mode != "sync":
        # Off its synced copy (R164): nothing held, and the clean-up the
        # page asked for, by its token, until the node answers it.
        return {"mode": "off", "projects": {}, "reads": {}, "clean": str(conf.get("clean") or "")}
    own = bound_projects(nid)
    return {"mode": mode, "projects": {p: rev_of(p) for p in own}
            | {u: rev_of(u) for p in own for u in worktrees_of(p)},
            "reads": {p: rev_of(p) for p in read_projects(nid)},
            # Leaving (R164): kept in step as ever, so what is waiting goes up.
            "leaving": bool(conf.get("leaving"))}


def state(nid, project):
    if (why := may(nid, project)):
        return {"error": why}, 403
    try:
        scan(project, force=True)
    except ValueError as e:
        return {"error": str(e)}, 404
    with _lock(project):
        rows = [_row_out(r) for r in _load(project).values() if not r["gone"] and not _hidden(nid, r["path"], r["link"])]
        return {"rev": rev_of(project), "files": rows}, 200


def since(nid, project, rev):
    if (why := may(nid, project)):
        return {"error": why}, 403
    try:
        scan(project)
    except ValueError as e:
        return {"error": str(e)}, 404
    try:
        rev = int(rev)
    except (TypeError, ValueError):
        rev = 0
    with _lock(project):
        cur = rev_of(project)
        if rev > cur:
            # The node knows a revision this index never reached: the index
            # was rebuilt. Start over from the whole state.
            return {"rev": cur, "reset": True, "changes": []}, 200
        rows = [_row_out(r) for r in _load(project).values() if r["rev"] > rev and not _hidden(nid, r["path"], r["link"])]
        rows.sort(key=lambda x: x[0])
        return {"rev": cur, "changes": rows}, 200


def file_path(nid, project, rel):
    """The file a node asked for, or a refusal."""
    if (why := may(nid, project)):
        return None, ({"error": why}, 403)
    if not _rel_ok(rel) or skipped(rel) or _hidden(nid, rel):
        return None, ({"error": "not a synced path"}, 400)
    try:
        p = _root(project) / rel
    except ValueError as e:
        return None, ({"error": str(e)}, 404)
    e = _entry(p)
    if e is None or e[3]:
        return None, ({"error": "no such file"}, 404)
    return p, None


def tar_writer(nid, project):
    """The whole project in one download, for a node's first copy: a
    function that writes it as a tar stream, or a refusal. Each file as it is
    at that moment; the node hashes what it unpacks and then asks what
    changed since the revision state() gave it, so a file that moves while
    this runs comes down again."""
    if (why := may(nid, project)):
        return None, ({"error": why}, 403)
    try:
        root = _root(project)
    except ValueError as e:
        return None, ({"error": str(e)}, 404)

    def write(out):
        with tarfile.open(fileobj=out, mode="w|", format=tarfile.PAX_FORMAT) as tar:
            for rel in sorted(_walk(root)):
                p = root / rel
                if _hidden(nid, rel, p.is_symlink()):
                    continue
                if _entry(p) is None:
                    continue
                with contextlib.suppress(OSError):
                    tar.add(p, arcname=rel, recursive=False)
    return write, None


def _conflict_name(rel, who):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    who = re.sub(r"[^A-Za-z0-9_-]", "-", who or "node")[:30]
    parts = rel.split("/")
    if ".git" in parts:
        return f".git/bbsync-conflicts/{who}-{stamp}/" + "/".join(parts[parts.index(".git") + 1:])
    d, _, name = rel.rpartition("/")
    stem, dot, ext = name.rpartition(".")
    base = f"{stem}.conflict-{who}-{stamp}.{ext}" if dot and stem else f"{name}.conflict-{who}-{stamp}"
    return (d + "/" if d else "") + base


# What a node may not write into git's own directory (B618): the controller
# runs git in every project tree (the status poll, the Git view, a relayed
# bb version), and git runs what its config and hooks name. A key here is
# one whose value is a program, or that points git somewhere else. Matched
# against the lowercased key; alias only when its value runs a shell.
GIT_EXEC = re.compile(
    r"(core\.(fsmonitor|hookspath|sshcommand|pager|editor|askpass|gitproxy|alternaterefscommand|worktree)"
    r"|sequence\.editor|diff\.external|diff\..+\.(textconv|command)|merge\..+\.driver"
    r"|filter\..+\.(clean|smudge|process)|credential(\..+)?\.helper|gpg(\..+)?\.program"
    r"|include\.path|includeif\..+\.path|pager\..+|web\.browser|browser\..+\.(cmd|path)"
    r"|man\..+\.(cmd|path)|remote\..+\.(uploadpack|receivepack|vcs)|uploadpack\.packobjectshook"
    r"|ssh\.variant|receive\.procreceiverefs)")


def git_config_danger(path, have=None):
    """The first key in a git config file that would run something, or
    pointed git elsewhere, as "key", or "" when there is none. Read by git
    itself, which runs nothing to read a file; one it cannot read is
    refused, since a config git cannot parse is not one to hand it.
    `have` is the config already here (B732): a key and value git already
    runs from this tree, the project's own credential helper the controller
    wrote, is not planted by a node sending it back, so only what the file
    adds to that counts."""
    had = set(git_config_runs(have)) if have else set()
    try:
        r = subprocess.run(["git", "config", "--file", str(path), "--no-includes", "--list", "-z"],
                           capture_output=True, timeout=10,
                           env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent",
                                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"})
    except (OSError, subprocess.SubprocessError) as e:
        return f"unreadable ({type(e).__name__})"
    if r.returncode != 0:
        return "unreadable: " + r.stderr.decode("utf-8", "replace").strip()[:120]
    for item in r.stdout.split(b"\0"):
        key, _, value = item.decode("utf-8", "replace").partition("\n")
        key = key.strip().lower()
        if not key:
            continue
        if (GIT_EXEC.fullmatch(key) or (key.startswith("alias.") and value.lstrip().startswith("!"))) \
                and (key, value) not in had:
            return key
    return ""


def git_config_runs(path):
    """The (key, value) pairs of a git config file that name a program, or
    nothing for one git cannot read: what the tree already runs."""
    try:
        r = subprocess.run(["git", "config", "--file", str(path), "--no-includes", "--list", "-z"],
                           capture_output=True, timeout=10,
                           env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent",
                                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"})
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    out = []
    for item in r.stdout.split(b"\0"):
        key, _, value = item.decode("utf-8", "replace").partition("\n")
        key = key.strip().lower()
        if key and (GIT_EXEC.fullmatch(key) or (key.startswith("alias.") and value.lstrip().startswith("!"))):
            out.append((key, value))
    return out


def _refused(nid, project, rel, why):
    """A refused write is audited: it is either a mistake or an attack."""
    if audit:
        audit(f"device:{nid[len(DEV):]}" if _is_dev(nid) else f"node:{nid}", "sync-refused", f"{project}:{rel}"[:200], {"why": why[:200]})


def git_guard(rel, link):
    """Why a node's write to `rel` (a symlink to `link`, or a file) is refused
    before it is read, or "" (B618). Nothing in .git/hooks, no .git file at
    a tree's top (it names another directory as the repository), no link
    inside .git, and no link anywhere that climbs out of the project."""
    parts = rel.split("/")
    if link:
        up = os.path.normpath(os.path.join(os.path.dirname(rel), link))
        if up == ".." or up.startswith("../"):
            return "a link out of the project is not synced"
    if ".git" not in parts:
        return ""
    i = parts.index(".git")
    inside = parts[i + 1:]
    if not inside:
        return "a .git file names another directory as the repository; not synced from a node"
    if "hooks" in inside:
        return "git hooks run on the controller; a node does not write them"
    if link:
        return "a link inside .git is not synced from a node"
    return ""


def put(nid, project, q, stream, length):
    """One file the node changed: its bytes in the body, or a deletion, or a
    symlink, with `base` the hash the node had before it changed it ("" for
    a file the node did not have). Applied when the base is what the
    controller has now; otherwise the node's version is kept as a conflict
    copy. ({"ok", "rev", "sha"} | {"conflict", "kept_as", ...}, status)."""
    if (why := may(nid, project, write=True)):
        return {"error": why}, 403
    rel = q.get("path", [""])[0]
    if not _rel_ok(rel) or skipped(rel) or _hidden(nid, rel, q.get("link", [""])[0]):
        return {"error": "not a synced path"}, 400
    try:
        root = _root(project, make=True)
    except ValueError as e:
        return {"error": str(e)}, 404
    base = q.get("base", [""])[0]
    gone = q.get("gone", [""])[0] == "1"
    link = q.get("link", [""])[0]
    try:
        mode = int(q.get("mode", ["420"])[0]) & 0o7777
    except ValueError:
        mode = 0o644
    if _is_dev(nid) and "mode" not in q:
        # A device on a system without POSIX modes sends none: the file
        # keeps its own (a script stays executable), a new one is 644.
        with contextlib.suppress(OSError):
            mode = (root / rel).stat().st_mode & 0o7777
    if link and os.path.isabs(link):
        return {"error": "a link out of the project is not synced"}, 400
    if (why := git_guard(rel, link)):
        _refused(nid, project, rel, why)
        return {"error": why}, 403
    if not gone and not link and (length < 0 or length > MAX_FILE):
        return {"error": f"over {MAX_FILE >> 20} MB: not synced"}, 413
    target = root / rel
    who = _who(nid)
    tmp = None
    try:
        sha = ""
        if not gone and not link:
            # Into a temporary beside it first, hashed as it arrives, so the
            # judgment below is made on what actually came.
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.parent / f"{TMP}{os.getpid()}-{threading.get_ident()}"
            h = hashlib.sha256()
            left = length
            with open(tmp, "wb") as f:
                while left > 0:
                    chunk = stream.read(min(1 << 20, left))
                    if not chunk:
                        break
                    h.update(chunk)
                    f.write(chunk)
                    left -= len(chunk)
            if left:
                return {"error": "the body ended early"}, 400
            sha = h.hexdigest()
            # A git config file is read before it can land (B618): one that
            # sets a key naming a program is refused, the rest go through.
            # Unless it is the one already here (B732): the controller writes
            # the project's own credential helper into its config and the
            # sync carries that down, so the node sending the same bytes back
            # is handing git nothing it did not have, and refusing it left
            # the file pending on every tick and every push from the node
            # refused as behind.
            if ".git" in rel.split("/") and rel.rsplit("/", 1)[-1] in ("config", "config.worktree"):
                with _lock(project):
                    _look(project, root, rel)
                    row = _load(project).get(rel)
                    if row and not row["gone"] and row["sha"] == sha:
                        return {"ok": True, "rev": rev_of(project), "sha": sha}, 200
                bad = git_config_danger(tmp, target if target.is_file() else None)
                if bad:
                    why = (f"{rel} sets {bad}, which git would run on the controller"
                           if not bad.startswith("unreadable") else f"{rel} is {bad}")
                    _refused(nid, project, rel, why)
                    return {"error": why + "; not synced from a node"}, 403
        elif link:
            sha = link_sha(link)
        with _lock(project):
            _look(project, root, rel)
            row = _load(project).get(rel)
            cur = row["sha"] if row and not row["gone"] else ""
            if cur == sha:
                # Already so: the same change made on both sides, or a
                # retry of one that landed.
                return {"ok": True, "rev": rev_of(project), "sha": sha}, 200
            # git's index is a cache of the tree it was written beside, and
            # the node's tree is where the work is: its index wins a
            # disagreement, since one kept here instead put the node's index
            # back to before its own commit (B617), and a conflict copy of an
            # index is no use to anybody.
            if base != cur and rel.split("/")[-2:] != [".git", "index"] \
                    and not (rel.startswith(".git/worktrees/") and rel.endswith("/index")):
                if gone:
                    # Deleted there, changed here: the change stays, and
                    # comes back down to the node.
                    return {"conflict": True, "kept_as": "", "rev": rev_of(project), "sha": cur}, 200
                kept = _conflict_name(rel, who)
                kp = root / kept
                kp.parent.mkdir(parents=True, exist_ok=True)
                if link:
                    os.symlink(link, kp)
                else:
                    os.chmod(tmp, mode)
                    os.replace(tmp, kp)
                    tmp = None
                _look(project, root, kept)
                _conflicts.append({"project": project, "path": rel, "kept_as": kept, "node": who,
                                   "at": int(time.time())})
                del _conflicts[:-CONFLICTS_KEPT]
                if audit:
                    audit(f"device:{nid[len(DEV):]}" if _is_dev(nid) else f"node:{nid}", "sync-conflict", f"{project}:{rel}"[:200], {"kept_as": kept})
                out = {"conflict": True, "kept_as": kept, "rev": rev_of(project), "sha": cur,
                       "link": row["link"] if row and not row["gone"] else ""}
                nid_told = ""             # the conflict copy goes to this node too
            else:
                if gone:
                    with contextlib.suppress(FileNotFoundError):
                        target.unlink()
                elif link:
                    with contextlib.suppress(FileNotFoundError):
                        if target.is_dir() and not target.is_symlink():
                            raise IsADirectoryError(rel)
                        target.unlink()
                    os.symlink(link, target)
                else:
                    if target.is_dir() and not target.is_symlink():
                        return {"error": f"{rel} is a directory here"}, 409
                    os.chmod(tmp, mode)
                    os.replace(tmp, target)
                    tmp = None
                _look(project, root, rel)
                out = {"ok": True, "rev": rev_of(project), "sha": sha}
                nid_told = nid            # it has this one already
        _wake(project, but=nid_told)
        if on_change:
            on_change(project)
        return out, 200
    except OSError as e:
        return {"error": f"{type(e).__name__}: {e}"}, 500
    finally:
        if tmp is not None:
            with contextlib.suppress(OSError):
                tmp.unlink()


def conflicts(visible):
    """The conflict copies still on the share, for the bell: a row stays
    until its copy is deleted. `visible(project)` says whether the asker
    sees the project."""
    out = []
    for c in reversed(_conflicts):
        if not visible(c["project"]):
            continue
        with contextlib.suppress(ValueError):
            if os.path.lexists(_root(c["project"]) / c["kept_as"]):
                out.append(dict(c))
    return out[:20]
