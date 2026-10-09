"""A project's files, one request at a time, for a person's own editor (R159).

The VS Code extension opens a project as a folder of its own and reads and
writes it through here, with no share mounted on the person's machine. The
server's handler has already proved the account and asked ftp.access_for
what its settings give it through the editor's door ("r" or "rw"), on this
very request: nothing is cached, so access taken away holds from the next
one. Here every path is held inside the project, a write needs "rw", and
every change goes on the audit trail under the person's name.

What is never served: `.git`, at any depth. Its config can hold a remote's
token in a URL, and the history is the Git view's and the session's.

    verb(action, project, req, access, by) -> (payload, status)

Actions: stat, list, read, write, mkdir, delete, rename (the editor's file
system), search (text across the tree, step 5) and changes (what moved
since a revision, for the editor's open files, step 4).
"""

import base64
import os
import re
import shutil
import stat as st
import threading
import time
from collections import deque
from pathlib import Path

# The API's version, which the extension compares with its own (vscode/lib/client.js).
API = 1
WORKSPACE = None
audit = None              # (principal, action, target, params) -> the audit row

# A file the editor opens whole. Bigger ones are a build output or a dataset,
# which an editor tab is no place for.
MAX_READ = 20 * 1024 * 1024
HIDDEN = {".git"}
# What a change scan and a search walk past: generated, vendored or the
# map's own, and large enough to make every scan slow.
SKIP = {".git", "node_modules", ".gradle", "build", "dist", "__pycache__", ".bb-map",
        ".venv", "venv", ".next", "target", ".cache"}
SCAN_FILES = 50_000       # past this a tree is answered as "reset", not walked further
SCAN_EVERY = 2.0          # seconds between two scans of one project, however many ask
EVENTS_KEPT = 5000
SEARCH_SECONDS = 10
SEARCH_FILE_MAX = 2 * 1024 * 1024
SEARCH_HITS = 2000


def configure(*, workspace, audit):
    globals().update(WORKSPACE=Path(workspace), audit=audit)


class Refused(Exception):
    def __init__(self, status, why):
        super().__init__(why)
        self.status, self.why = status, why


def _root(project):
    root = (WORKSPACE / project).resolve()
    if not root.is_dir():
        raise Refused(404, f"{project} has no tree on this controller")
    return root


def _path(project, rel):
    """(root, the path, its clean relative form), or Refused. Inside the
    project after every symlink is followed, and never through .git."""
    parts = [p for p in str(rel or "").replace("\\", "/").split("/") if p not in ("", ".")]
    if ".." in parts:
        raise Refused(400, "a path inside the project, with no ..")
    if any(p in HIDDEN for p in parts):
        raise Refused(403, ".git is not served: its config can carry a token, and history "
                           "is the Git view's")
    root = _root(project)
    p = root.joinpath(*parts)
    real = p.resolve(strict=False)
    if real != root and root not in real.parents:
        raise Refused(403, "that path leads outside the project")
    if any(x in HIDDEN for x in real.relative_to(root).parts):
        raise Refused(403, ".git is not served")
    return root, p, "/".join(parts)


def _kind(s):
    return "dir" if st.S_ISDIR(s.st_mode) else "file"


def _stat(p):
    try:
        s = p.stat()
    except FileNotFoundError:
        raise Refused(404, "no such file") from None
    return {"type": _kind(s), "size": s.st_size, "mtime": int(s.st_mtime * 1000),
            "ctime": int(s.st_ctime * 1000)}


def _b64(req):
    d = req.get("data")
    if not isinstance(d, str):
        raise Refused(400, "data, as base64")
    try:
        raw = base64.b64decode(d, validate=True)
    except ValueError:
        raise Refused(400, "data is not base64") from None
    if len(raw) > MAX_READ:
        raise Refused(413, f"larger than {MAX_READ // (1024 * 1024)} MB")
    return raw


def _flag(req, k):
    return req.get(k) is True


def _write(p, raw):
    """In place of the file at once: a temporary beside it, then a rename,
    so a session reading it never meets half a file. Its mode is kept."""
    mode = None
    try:
        mode = st.S_IMODE(p.stat().st_mode)
    except FileNotFoundError:
        pass
    tmp = p.with_name(f".{p.name}.bbedit-{os.getpid()}-{threading.get_ident()}")
    try:
        with open(tmp, "wb") as f:
            f.write(raw)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


on_change = None          # (project) -> None: wssync.changed, so a synced node hears at once (R162)


def _changed(project, by, action, rel, **more):
    if audit:
        audit(by, f"files-{action}", f"{project}:{rel}"[:200], more)
    _poke(project)
    if on_change:
        on_change(project)


# ---- the editor's file system ---------------------------------------------------

def _stat_v(project, req, access, by):
    _, p, _ = _path(project, req.get("path"))
    return {**_stat(p), "readonly": access != "rw"}


def _list(project, req, access, by):
    _, p, _ = _path(project, req.get("path"))
    if not p.is_dir():
        raise Refused(404 if not p.exists() else 400, "not a folder")
    out = []
    for e in sorted(os.scandir(p), key=lambda e: e.name):
        if e.name in HIDDEN or e.name.startswith(".bbedit-") or ".bbedit-" in e.name:
            continue
        try:
            out.append([e.name, "dir" if e.is_dir() else "file"])
        except OSError:
            continue
    return {"entries": out}


def _read(project, req, access, by):
    _, p, _ = _path(project, req.get("path"))
    s = _stat(p)
    if s["type"] == "dir":
        raise Refused(400, "a folder, not a file")
    if s["size"] > MAX_READ:
        raise Refused(413, f"larger than {MAX_READ // (1024 * 1024)} MB: not opened in an editor")
    return {"data": base64.b64encode(p.read_bytes()).decode(), **_stat(p)}


def _needs_rw(access):
    if access != "rw":
        raise Refused(403, "your file access to this project is read-only")


def _write_v(project, req, access, by):
    _needs_rw(access)
    _, p, rel = _path(project, req.get("path"))
    raw = _b64(req)
    exists = p.exists()
    if exists and p.is_dir():
        raise Refused(400, "a folder, not a file")
    if exists and not _flag(req, "overwrite"):
        raise Refused(409, "it exists")
    if not exists and not _flag(req, "create"):
        raise Refused(404, "no such file")
    if not p.parent.is_dir():
        raise Refused(404, "its folder does not exist")
    # Changed since the editor read it: Claude's save, most likely. The
    # editor shows its compare rather than one side quietly winning.
    want = req.get("mtime")
    if exists and isinstance(want, int) and _stat(p)["mtime"] != want:
        return {"error": "changed on the controller since you opened it", "conflict": True,
                **_stat(p)}, 409
    _write(p, raw)
    _changed(project, by, "write", rel, bytes=len(raw))
    return {"ok": True, **_stat(p)}


def _mkdir(project, req, access, by):
    _needs_rw(access)
    _, p, rel = _path(project, req.get("path"))
    if p.exists():
        raise Refused(409, "it exists")
    if not p.parent.is_dir():
        raise Refused(404, "its folder does not exist")
    p.mkdir()
    _changed(project, by, "mkdir", rel)
    return {"ok": True}


def _delete(project, req, access, by):
    _needs_rw(access)
    root, p, rel = _path(project, req.get("path"))
    if p == root:
        raise Refused(403, "not the project itself")
    if not p.exists() and not p.is_symlink():
        raise Refused(404, "no such file")
    if p.is_dir() and not p.is_symlink():
        if any(True for _ in p.iterdir()) and not _flag(req, "recursive"):
            raise Refused(409, "the folder is not empty")
        if any(h in d for _, d, _ in os.walk(p) for h in HIDDEN):
            raise Refused(403, "it holds a .git, which is not served, so not deleted from here")
        shutil.rmtree(p)
    else:
        p.unlink()
    _changed(project, by, "delete", rel)
    return {"ok": True}


def _rename(project, req, access, by):
    _needs_rw(access)
    root, a, ra = _path(project, req.get("path"))
    _, b, rb = _path(project, req.get("to"))
    if a == root or b == root:
        raise Refused(403, "not the project itself")
    if not a.exists():
        raise Refused(404, "no such file")
    if b.exists() and not _flag(req, "overwrite"):
        raise Refused(409, "the new name exists")
    if not b.parent.is_dir():
        raise Refused(404, "the new name's folder does not exist")
    os.replace(a, b)
    _changed(project, by, "rename", f"{ra} -> {rb}")
    return {"ok": True}


# ---- search across the tree (step 5) ----------------------------------------------

def _walk(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP)
        for fn in sorted(fns):
            yield Path(dp) / fn


def _search(project, req, access, by):
    q = req.get("query")
    if not isinstance(q, str) or not q:
        raise Refused(400, "what to search for")
    flags = 0 if _flag(req, "case") else re.I
    pat = q if _flag(req, "regex") else re.escape(q)
    if _flag(req, "word"):
        pat = rf"\b{pat}\b"
    try:
        rx = re.compile(pat, flags)
    except re.error as e:
        raise Refused(400, f"not a regular expression: {e}") from None
    root = _root(project)
    try:
        cap = max(1, min(int(req.get("max") or SEARCH_HITS), SEARCH_HITS))
    except (TypeError, ValueError):
        cap = SEARCH_HITS
    hits, done, until = [], True, time.monotonic() + SEARCH_SECONDS
    for p in _walk(root):
        if time.monotonic() > until or len(hits) >= cap:
            done = False
            break
        try:
            if p.is_symlink() or p.stat().st_size > SEARCH_FILE_MAX:
                continue
            raw = p.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:8192]:
            continue
        rel = str(p.relative_to(root))
        for n, line in enumerate(raw.decode("utf-8", "replace").split("\n"), 1):
            m = rx.search(line)
            if m:
                hits.append({"path": rel, "line": n, "col": m.start(), "len": m.end() - m.start(),
                             "text": line[:400]})
                if len(hits) >= cap:
                    break
    return {"matches": hits, "complete": done}


# ---- what changed since a revision (step 4) ----------------------------------------
# A scan of the tree's sizes and times, at most every SCAN_EVERY seconds per
# project however many editors ask, each difference an event with a
# revision. The tree is a share that sessions on other machines write, and
# inotify on it sees none of their writes, so it is looked at, not told.

_scans = {}               # project -> {"at", "rev", "snap": {rel: (mtime_ns, size)}, "events": deque}
_scan_lock = threading.Lock()
_wake = threading.Condition()


def _snapshot(root):
    snap = {}
    for p in _walk(root):
        try:
            s = p.stat()
        except OSError:
            continue
        snap[str(p.relative_to(root))] = (s.st_mtime_ns, s.st_size)
        if len(snap) > SCAN_FILES:
            return None
    return snap


def _scan(project, force=False):
    with _scan_lock:
        rec = _scans.get(project)
        if rec and not force and time.monotonic() - rec["at"] < SCAN_EVERY:
            return rec
        root = _root(project)
        snap = _snapshot(root)
        if rec is None:
            rec = _scans[project] = {"at": 0.0, "rev": 1, "snap": snap or {}, "events": deque(maxlen=EVENTS_KEPT),
                                     "big": snap is None}
        elif snap is None:
            rec["big"] = True
        else:
            old = rec["snap"]
            moved = [(k, "changed" if k in old else "created") for k, v in snap.items() if old.get(k) != v]
            moved += [(k, "deleted") for k in old if k not in snap]
            for k, kind in moved:
                rec["rev"] += 1
                rec["events"].append((rec["rev"], k, kind))
            rec["snap"], rec["big"] = snap, False
        rec["at"] = time.monotonic()
    if rec["events"] and rec["events"][-1][0] == rec["rev"]:
        with _wake:
            _wake.notify_all()
    return rec


def _poke(project):
    """A write from here is seen on the next ask, not after SCAN_EVERY."""
    if project in _scans:
        try:
            _scan(project, force=True)
        except Refused:
            pass


def _changes(project, req, access, by):
    try:
        since = int(req.get("since") or 0)
    except (TypeError, ValueError):
        since = 0
    try:
        wait = max(0.0, min(float(req.get("wait") or 0), 25.0))
    except (TypeError, ValueError):
        wait = 0.0
    until = time.monotonic() + wait
    while True:
        rec = _scan(project)
        if rec.get("big"):
            return {"rev": rec["rev"], "reset": True, "changes": [],
                    "why": f"more than {SCAN_FILES} files: changes are not followed"}
        if since == 0:
            return {"rev": rec["rev"], "changes": []}
        oldest = rec["events"][0][0] if rec["events"] else rec["rev"] + 1
        if since < oldest - 1 and rec["events"]:
            return {"rev": rec["rev"], "reset": True, "changes": []}
        got = [{"path": k, "type": kind} for r, k, kind in rec["events"] if r > since]
        if got or time.monotonic() >= until:
            return {"rev": rec["rev"], "changes": got}
        with _wake:
            _wake.wait(timeout=min(SCAN_EVERY, max(0.05, until - time.monotonic())))


ACTIONS = {"stat": _stat_v, "list": _list, "read": _read, "write": _write_v, "mkdir": _mkdir,
           "delete": _delete, "rename": _rename, "search": _search, "changes": _changes}


def verb(action, project, req, access, by=""):
    """One action on `project`'s files with `access` ("r" or "rw") already
    granted to the account `by`. (payload, status)."""
    fn = ACTIONS.get(action)
    if fn is None:
        return {"error": f"unknown action: {action}; one of {', '.join(ACTIONS)}"}, 400
    try:
        out = fn(project, req, access, by)
    except Refused as e:
        return {"error": e.why}, e.status
    except PermissionError:
        return {"error": "the controller may not touch that file"}, 403
    except OSError as e:
        return {"error": f"{type(e).__name__}: {e.strerror or e}"}, 500
    return out if isinstance(out, tuple) else (out, 200)
