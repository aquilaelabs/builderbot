"""Each account's Claude conversations and memories, kept in step between a
synced node and the controller (B613).

Claude Code writes a conversation under ~/.claude/projects/<slug>/, which
every machine links to /workspace/.claude/<uid>/projects (common.sh's
claude_projects_link). On the projects share that was one directory for
all of them. A node holding its projects as a synced copy (R162, R163) has
no share, so it keeps its own directory at the same path and its agent
mirrors it here: the controller's copy stays the one the Profile page, the
Memory tab, bb transcripts and the resume offer read.

Not wssync.py's machinery, on purpose: a transcript only ever grows, and
runs to hundreds of megabytes (the briefing rides on every turn), so a
change is sent as its new tail, checked against the last bytes the
controller already has, rather than the whole file every turn. A file that
is rewritten (a memory) goes whole. Only the folders of projects the node
holds may be written, and only a project it holds is listed to it.
"""
import contextlib
import hashlib
import os
import re
import threading
from pathlib import Path

WORKSPACE = Path("/workspace")
UID = re.compile(r"u_[0-9a-f]{8}")
TAIL = 4096                 # the bytes before an append, compared on both sides
MAX_FILE = 2 * 1024 * 1024 * 1024
_lock = threading.Lock()
_held = lambda nid: []   # noqa: E731 (set by configure: (node id) -> [projects it may write])


def configure(*, workspace, held):
    globals().update(WORKSPACE=Path(workspace), _held=held)


def root():
    return WORKSPACE / ".claude"


def slug(path):
    """A path as Claude Code names its folder: every character that is not
    a letter or a digit becomes a dash (bb-session's _slug)."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def project_of(entry, projects):
    """The project a transcripts folder belongs to, of `projects`, or "":
    the project's own tree, or one of its worktrees (an account's uid on
    the end, an agent's and a slot's after it), so a project whose name
    starts another's never claims it."""
    for p in projects:
        if entry == slug(WORKSPACE / p) or re.fullmatch(
                re.escape(slug(WORKSPACE / ".worktrees" / p) + "-") + r"u-[0-9a-f]{8}(?:-[a-z]+)?(?:-[2-9])?", entry):
            return p
    return ""


def rel_ok(rel):
    parts = str(rel or "").split("/")
    return len(parts) >= 2 and all(p not in ("", ".", "..") for p in parts) \
        and "\0" not in rel and len(rel) < 4096


def tail_sha(path, end):
    """sha256 of the TAIL bytes before `end`."""
    start = max(0, end - TAIL)
    with open(path, "rb") as f:
        f.seek(start)
        return hashlib.sha256(f.read(end - start)).hexdigest()


def _may(nid, uid, rel):
    """The file's path here, or the refusal."""
    if not UID.fullmatch(uid or ""):
        return None, ({"error": "not an account"}, 400)
    if not rel_ok(rel):
        return None, ({"error": "not a transcripts path"}, 400)
    if not project_of(rel.split("/")[0], _held(nid)):
        return None, ({"error": "not a project this node holds"}, 403)
    top = root() / uid / "projects"
    p = top / rel
    # A link anywhere on the way would carry a write out of the folder.
    if not os.path.realpath(p).startswith(os.path.realpath(top) + "/"):
        return None, ({"error": "not a transcripts path"}, 400)
    return p, None


def listing(nid):
    """Every file in the folders of the projects this node holds, of every
    account: {uid: {rel: [size, mtime_ms]}}."""
    held = _held(nid)
    out = {}
    try:
        uids = [d for d in os.listdir(root()) if UID.fullmatch(d)]
    except OSError:
        return {"accounts": out}
    for uid in uids:
        top = root() / uid / "projects"
        try:
            entries = os.listdir(top)
        except OSError:
            continue
        files = {}
        for entry in entries:
            if not project_of(entry, held):
                continue
            for dirpath, dirs, names in os.walk(top / entry):
                dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(dirpath, d))]
                for n in names:
                    p = os.path.join(dirpath, n)
                    try:
                        s = os.lstat(p)
                    except OSError:
                        continue
                    if not os.path.isfile(p) or os.path.islink(p) or n.startswith(".bbsync-"):
                        continue
                    files[os.path.relpath(p, top)] = [s.st_size, s.st_mtime_ns // 1_000_000]
        if files:
            out[uid] = files
    return {"accounts": out}


def file_path(nid, uid, rel):
    p, no = _may(nid, uid, rel)
    if no:
        return None, no
    if not p.is_file():
        return None, ({"error": "no such file"}, 404)
    return p, None


def _mkdirs(uid, p):
    acct = root() / uid
    if not acct.is_dir():
        acct.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(acct, 0o700)
    p.parent.mkdir(parents=True, exist_ok=True)


def put(nid, q, stream, length):
    """One file from the node: `mode` whole (the body is the file), append
    (the body follows `offset` bytes, the last of which hash to `tail`) or
    gone. `mtime` (ms) is set on what is written, so both sides then read
    alike and neither sends it again. An append whose offset or tail is not
    what is here is refused with what is here, and the node sends whole."""
    def arg(k):
        return q.get(k, [""])[0]
    p, no = _may(nid, arg("uid"), arg("path"))
    if no or p is None:
        return no
    mode = arg("mode") or "whole"
    try:
        mtime = int(arg("mtime") or 0)
    except ValueError:
        mtime = 0
    if length < 0 or length > MAX_FILE:
        return {"error": "too large"}, 413
    with _lock:
        if mode == "gone":
            with contextlib.suppress(FileNotFoundError):
                p.unlink()
            return {"ok": True}, 200
        _mkdirs(arg("uid"), p)
        if mode == "append":
            try:
                offset = int(arg("offset"))
            except ValueError:
                return {"error": "offset"}, 400
            have = p.stat().st_size if p.is_file() else 0
            if have != offset or (offset and tail_sha(p, offset) != arg("tail")):
                _drain(stream, length)
                return {"error": "not the bytes here", "size": have}, 409
            with open(p, "ab") as f:
                got = _copy(stream, f, length)
            if got != length:
                with open(p, "r+b") as f:
                    f.truncate(offset)
                return {"error": "short body"}, 400
        elif mode == "whole":
            tmp = p.with_name(f".bbsync-{p.name}")
            with open(tmp, "wb") as f:
                got = _copy(stream, f, length)
            if got != length:
                tmp.unlink(missing_ok=True)
                return {"error": "short body"}, 400
            os.replace(tmp, p)
        else:
            return {"error": f"no such mode: {mode}"}, 400
        if mtime:
            with contextlib.suppress(OSError):
                os.utime(p, ns=(mtime * 1_000_000, mtime * 1_000_000))
        s = p.stat()
        return {"ok": True, "size": s.st_size, "mtime": s.st_mtime_ns // 1_000_000}, 200


def _copy(stream, f, length):
    got = 0
    while got < length:
        chunk = stream.read(min(1 << 20, length - got))
        if not chunk:
            break
        f.write(chunk)
        got += len(chunk)
    return got


def _drain(stream, length):
    while length > 0:
        chunk = stream.read(min(1 << 20, length))
        if not chunk:
            return
        length -= len(chunk)
