"""A node's projects as a synced copy instead of a mounted share (R162).

The controller's copy is the original (its wssync.py says how it judges);
this keeps the node's copy under /workspace in step with it, over the
agent API alone, so a node behind a one-way tunnel needs nothing else.

Each project has a record, kept in the data store so it outlives a restart:
the revision this node last caught up to, and every file as it was when the
two last agreed (hash, size, mtime, mode, a symlink's target). A file whose
size, time or mode differs from its record was changed here; once it has
held still for a tick it goes up as a put naming the hash it was changed
FROM. What the controller has that is newer than the record's revision
comes down: when the held work request says the project moved, and every
PULL_EVERY seconds besides. A change made while the controller could not be
reached waits in the difference between the tree and the record, and goes
up when it can.

When the controller had already taken another version of a file, it keeps
that one and keeps ours beside it as a conflict copy; the version it kept
is fetched here, so the two copies agree again and both versions exist.
"""
import contextlib
import ctypes
import ctypes.util
import errno
import hashlib
import json
import os
import stat as st
import struct
import tarfile
import threading
import time
import urllib.parse
from .base import SHARE, log

# What is not synced, the same set as the controller's (wssync.SKIP_DIRS
# there; the unit tier holds the two equal).
SKIP_DIRS = {"node_modules", ".gradle", "__pycache__", ".venv", "venv", ".next", ".cache", ".bb-map",
             ".pytest_cache", ".mypy_cache", ".ruff_cache"}
TMP = ".bbsync-"
MAX_FILE = 512 * 1024 * 1024
TICK = 1.0
PULL_EVERY = 10.0
ASK_EVERY = 30.0
WALK_EVERY = 60.0        # a whole walk even with the watcher, for what it cannot see


def skipped(rel):
    parts = rel.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]) or parts[-1] in SKIP_DIRS:
        return True
    if parts[-1].startswith(TMP):
        return True
    return ".git" in parts and parts[-1].endswith(".lock")


def entry(p):
    """(size, mtime_ns, mode, link), or None for what is not synced."""
    try:
        s = os.lstat(p)
    except OSError:
        return None
    if st.S_ISLNK(s.st_mode):
        t = os.readlink(p)
        return None if os.path.isabs(t) else (0, s.st_mtime_ns, 0o777, t)
    if not st.S_ISREG(s.st_mode) or s.st_size > MAX_FILE:
        return None
    return (s.st_size, s.st_mtime_ns, st.S_IMODE(s.st_mode), "")


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def link_sha(target):
    return hashlib.sha256(b"link:" + target.encode()).hexdigest()


def walk(root):
    """{rel: entry} for everything synced under root."""
    out = {}
    for d, dirs, files in os.walk(root):
        rd = os.path.relpath(d, root)
        rd = "" if rd == "." else rd + "/"
        keep = []
        for x in dirs:
            if os.path.islink(os.path.join(d, x)):
                files.append(x)
            elif not skipped(rd + x + "/_"):
                keep.append(x)
        dirs[:] = keep
        for f in files:
            rel = rd + f
            if skipped(rel):
                continue
            e = entry(os.path.join(d, f))
            if e is not None:
                out[rel] = e
    return out


# inotify, through libc: the kernel says which files changed, so a tick reads
# those rather than walking the tree. Linux only; anything else (or a node
# out of watches) walks every tick as before.
_IN = dict(MODIFY=0x2, ATTRIB=0x4, CLOSE_WRITE=0x8, MOVED_FROM=0x40, MOVED_TO=0x80, CREATE=0x100,
           DELETE=0x200, DELETE_SELF=0x400, MOVE_SELF=0x800, Q_OVERFLOW=0x4000, IGNORED=0x8000,
           ONLYDIR=0x1000000, DONT_FOLLOW=0x2000000, ISDIR=0x40000000)
_MASK = (_IN["ATTRIB"] | _IN["CLOSE_WRITE"] | _IN["MOVED_FROM"] | _IN["MOVED_TO"] | _IN["CREATE"]
         | _IN["DELETE"] | _IN["DELETE_SELF"] | _IN["MOVE_SELF"])
_libc = None


def _inotify():
    global _libc
    if _libc is None:
        name = ctypes.util.find_library("c")
        lib = ctypes.CDLL(name, use_errno=True) if name else None
        _libc = lib if lib is not None and hasattr(lib, "inotify_init1") else False
    return _libc or None


class Watcher:
    """Which paths under a project changed since the last ask. `full` says
    a walk is needed: a directory came, went or moved, or the kernel's queue
    overflowed, and those are cheaper to walk than to follow."""

    def __init__(self, top):
        lib = _inotify()
        if lib is None:
            raise OSError("no inotify here")
        self.lib, self.top = lib, top
        self.fd = lib.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        self.wds, self.dirty, self.full = {}, set(), False
        self.add_tree("")

    def close(self):
        with contextlib.suppress(OSError):
            os.close(self.fd)

    def add(self, rel):
        wd = self.lib.inotify_add_watch(self.fd, os.path.join(self.top, rel).encode(),
                                        _MASK | _IN["ONLYDIR"] | _IN["DONT_FOLLOW"])
        if wd < 0:
            e = ctypes.get_errno()
            if e == errno.ENOSPC:
                raise OSError(e, "out of inotify watches")
            return
        self.wds[wd] = rel

    def add_tree(self, rel):
        base = os.path.join(self.top, rel)
        for d, dirs, _files in os.walk(base):
            r = os.path.relpath(d, self.top)
            r = "" if r == "." else r
            self.add(r)
            dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(d, x))
                       and not skipped((r + "/" if r else "") + x + "/_")]

    def changes(self):
        """(full, {rel}) since the last call."""
        while True:
            try:
                buf = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            if not buf:
                break
            i = 0
            while i + 16 <= len(buf):
                wd, mask, _cookie, n = struct.unpack_from("iIII", buf, i)
                name = buf[i + 16:i + 16 + n].split(b"\0", 1)[0].decode("utf-8", "surrogateescape")
                i += 16 + n
                if mask & _IN["Q_OVERFLOW"]:
                    self.full = True
                    continue
                base = self.wds.get(wd)
                if mask & _IN["IGNORED"]:
                    self.wds.pop(wd, None)
                    continue
                if base is None:
                    continue
                rel = (base + "/" if base else "") + name if name else base
                if mask & _IN["ISDIR"] or mask & (_IN["DELETE_SELF"] | _IN["MOVE_SELF"]):
                    self.full = True
                    if mask & (_IN["CREATE"] | _IN["MOVED_TO"]) and name and not skipped(rel + "/_"):
                        self.add_tree(rel)
                elif name and not skipped(rel):
                    self.dirty.add(rel)
        full, dirty = self.full, self.dirty
        self.full, self.dirty = False, set()
        return full, dirty


class Project:
    """One synced project's record and its state on this node."""

    def __init__(self, name, path):
        self.name, self.path = name, path
        self.rev, self.files, self.ready = 0, {}, False
        self.moving = {}         # rel -> entry seen last tick, waiting to hold still
        self.pulled_at = 0.0
        self.hinted = False
        self.copying = 0
        self.error = ""
        self.watch = None         # its Watcher, once there is a tree to watch
        self.walked_at = 0.0
        try:
            with open(path) as f:
                d = json.load(f)
            self.rev, self.files = int(d.get("rev") or 0), dict(d.get("files") or {})
            self.ready = bool(d.get("ready"))
        except (OSError, ValueError):
            pass

    def save(self):
        tmp = self.path + ".new"
        with open(tmp, "w") as f:
            json.dump({"rev": self.rev, "ready": self.ready, "files": self.files}, f)
        os.replace(tmp, self.path)


class WorkspaceSync:
    def __init__(self, agent, root=None):
        self.agent = agent
        self.root = root or SHARE
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.projects = {}       # name -> Project
        self.mode = ""
        self.asked_at = 0.0
        self.thread = None

    # -- what the rest of the agent sees ------------------------------------------
    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.run, name="wssync", daemon=True)
            self.thread.start()

    def nudge(self, moved):
        """The held work request said these projects moved."""
        with self.lock:
            for name in moved or {}:
                p = self.projects.get(str(name))
                if p:
                    p.hinted = True
            if any(str(n) not in self.projects for n in moved or {}):
                self.asked_at = 0.0
        self.wake.set()

    def status(self):
        """For the heartbeat: each project's state here."""
        with self.lock:
            return {n: {"ready": p.ready, "rev": p.rev, "copying": p.copying,
                        "pending": len(p.moving), "error": p.error}
                    for n, p in self.projects.items()} if self.mode == "sync" else None

    # -- the loop -------------------------------------------------------------------
    def run(self):
        while True:
            try:
                self.step()
            except Exception as e:                       # noqa: BLE001 (the loop must live)
                log(f"sync: {type(e).__name__}: {e}")
                time.sleep(5)
            self.wake.wait(TICK)
            self.wake.clear()

    def record_dir(self):
        data = ((self.agent.state.get("stores") or {}).get("data")) or "/var/lib/builderbot/data"
        d = os.path.join(data, "sync")
        os.makedirs(d, exist_ok=True)
        return d

    def step(self):
        now = time.monotonic()
        if now - self.asked_at > ASK_EVERY:
            st_, r = self.agent.ctl.call("sync", {"action": "projects"}, timeout=30)
            if st_ != 200:
                return
            self.asked_at = now
            mode = str(r.get("mode") or "mount")
            if mode != self.agent.state.get("workspace_mode"):
                # The census says whether /workspace is there, and in sync
                # mode it is a directory, not a mount: said again now.
                self.agent.state["workspace_mode"] = mode
                self.agent.hello_at = 0
            self.mode = mode
            want = r.get("projects") if isinstance(r.get("projects"), dict) else {}
            with self.lock:
                for name in want:
                    if name not in self.projects:
                        self.projects[name] = Project(name, os.path.join(self.record_dir(), name + ".json"))
                        log(f"sync: {name} is held here as a synced copy")
                for name in list(self.projects):
                    if name not in want:
                        # Unbound: left as it is on disk, no longer kept in step.
                        if self.projects[name].watch:
                            self.projects[name].watch.close()
                        del self.projects[name]
                for name, rev in want.items():
                    p = self.projects[name]
                    if int(rev or 0) != p.rev:
                        p.hinted = True
        if self.mode != "sync":
            return
        if not os.path.isdir(self.root):
            # Nothing mounts here: /workspace is this node's own directory.
            os.makedirs(self.root, exist_ok=True)
        for p in list(self.projects.values()):
            self.one(p)

    def one(self, p):
        top = os.path.join(self.root, p.name)
        if not p.ready:
            self.first_copy(p, top)
            if not p.ready:
                return
        self.push(p, top)
        if p.hinted or time.monotonic() - p.pulled_at > PULL_EVERY:
            self.pull(p, top)

    # -- the session account owns what is written ----------------------------------------
    def owner(self):
        user = self.agent.session_account() if hasattr(self.agent, "session_account") else ""
        if os.geteuid() != 0 or not user:
            return None
        import pwd
        try:
            pw = pwd.getpwnam(user)
        except KeyError:
            return None
        return pw.pw_uid, pw.pw_gid

    def mkdirs(self, top, rel_dir):
        own = self.owner()
        cur = top
        if not os.path.isdir(cur):
            os.makedirs(cur, exist_ok=True)
            if own:
                os.lchown(cur, *own)
        for part in [x for x in rel_dir.split("/") if x]:
            cur = os.path.join(cur, part)
            if not os.path.isdir(cur):
                os.mkdir(cur)
                if own:
                    os.lchown(cur, *own)

    # -- down ---------------------------------------------------------------------------
    def fetch(self, p, top, rel, sha, mode):
        """One file from the controller into place. Its hash as it arrived."""
        d, _, name = rel.rpartition("/")
        self.mkdirs(top, d)
        tmp = os.path.join(top, d, f"{TMP}{name}")
        q = urllib.parse.urlencode({"project": p.name, "path": rel})
        code, _ = self.agent.ctl.fetch(f"sync-file?{q}", tmp, timeout=600)
        if code != 200:
            with contextlib.suppress(OSError):
                os.remove(tmp)
            raise OSError(f"{rel}: the controller answered {code}")
        got = sha_file(tmp)
        os.chmod(tmp, mode or 0o644)
        own = self.owner()
        if own:
            os.lchown(tmp, *own)
        dest = os.path.join(top, rel)
        if os.path.isdir(dest) and not os.path.islink(dest):
            os.remove(tmp)
            raise OSError(f"{rel} is a directory here")
        os.replace(tmp, dest)
        return got

    def place_link(self, top, rel, target):
        d, _, _ = rel.rpartition("/")
        self.mkdirs(top, d)
        dest = os.path.join(top, rel)
        with contextlib.suppress(FileNotFoundError):
            os.remove(dest)
        os.symlink(target, dest)
        own = self.owner()
        if own:
            os.lchown(dest, *own)

    def agree(self, p, top, rel, sha):
        e = entry(os.path.join(top, rel))
        if e is None:
            p.files.pop(rel, None)
        else:
            p.files[rel] = [sha, *e]

    def first_copy(self, p, top):
        """The whole project as the controller has it. A file here already
        the same is kept; one missing is fetched; one that differs is left
        for push to send as a change from nothing, which the controller
        keeps as a conflict copy, so nothing that was here is lost."""
        st_, r = self.agent.ctl.call("sync", {"action": "state", "project": p.name}, timeout=300)
        if st_ != 200:
            p.error = str(r.get("error") or f"the controller answered {st_}")
            return
        rows = r.get("files") or []
        p.copying = len(rows)
        here = walk(top) if os.path.isdir(top) else {}
        p.files = {}
        if not here and rows:
            # Nothing here yet: the project in one download rather than a
            # request a file (R163). Whatever it did not bring is fetched
            # file by file below, as a tree that was here would be.
            try:
                self.unpack(p, top)
            except (OSError, tarfile.TarError) as ex:
                log(f"sync: {p.name}: the whole-project download failed ({ex}); fetching file by file")
            here = walk(top) if os.path.isdir(top) else {}
            for rel, e in here.items():
                try:
                    p.files[rel] = [link_sha(e[3]) if e[3] else sha_file(os.path.join(top, rel)), *e]
                except OSError:
                    continue
        for rel, sha, _size, mode, link, _gone in rows:
            if skipped(rel):
                p.copying -= 1
                continue
            e = here.get(rel)
            if rel in p.files:
                p.copying -= 1             # came in the download
                continue
            try:
                if link:
                    if e is None:
                        self.place_link(top, rel, link)
                        self.agree(p, top, rel, sha)
                    elif e[3] == link:
                        p.files[rel] = [sha, *e]
                elif e is None:
                    got = self.fetch(p, top, rel, sha, mode)
                    self.agree(p, top, rel, got)
                elif not e[3] and sha_file(os.path.join(top, rel)) == sha:
                    p.files[rel] = [sha, *e]
            except OSError as ex:
                p.error = str(ex)[:200]
                return
            p.copying -= 1
        p.rev, p.ready, p.error, p.copying = int(r.get("rev") or 0), True, "", 0
        p.pulled_at = time.monotonic()
        p.save()
        log(f"sync: {p.name} copied ({len(rows)} files at revision {p.rev})")

    def unpack(self, p, top):
        """The controller's tar of the project, into an empty tree here,
        owned by the session account. Paths that would leave the tree, and
        anything but files, directories and links inside it, are refused."""
        tmp = os.path.join(self.record_dir(), f".{p.name}.tar")
        q = urllib.parse.urlencode({"project": p.name})
        try:
            code, _ = self.agent.ctl.fetch(f"sync-tar?{q}", tmp, timeout=3600)
            if code != 200:
                raise OSError(f"the controller answered {code}")
            self.mkdirs(top, "")
            own = self.owner()
            with tarfile.open(tmp) as tar:
                for m in tar:
                    name = m.name
                    if name.startswith("/") or ".." in name.split("/") or skipped(name):
                        continue
                    if not (m.isfile() or m.isdir() or m.issym()):
                        continue
                    if m.issym() and os.path.isabs(m.linkname):
                        continue
                    d = name.rpartition("/")[0]
                    self.mkdirs(top, d)
                    dest = os.path.join(top, name)
                    if m.isdir():
                        continue
                    if m.issym():
                        with contextlib.suppress(FileNotFoundError):
                            os.remove(dest)
                        os.symlink(m.linkname, dest)
                    else:
                        src = tar.extractfile(m)
                        part = os.path.join(top, d, f"{TMP}{os.path.basename(name)}")
                        with open(part, "wb") as f:
                            while True:
                                chunk = src.read(1 << 20)
                                if not chunk:
                                    break
                                f.write(chunk)
                        os.chmod(part, m.mode & 0o7777 or 0o644)
                        os.replace(part, dest)
                    if own:
                        os.lchown(dest, *own)
        finally:
            with contextlib.suppress(OSError):
                os.remove(tmp)

    def pull(self, p, top):
        p.hinted = False
        st_, r = self.agent.ctl.call("sync", {"action": "since", "project": p.name, "rev": p.rev}, timeout=60)
        if st_ != 200:
            p.error = str(r.get("error") or f"the controller answered {st_}")
            return
        p.pulled_at = time.monotonic()
        if r.get("reset"):
            p.ready = False
            p.save()
            return
        held, moved = [], False
        for rel, sha, _size, mode, link, gone in r.get("changes") or []:
            if skipped(rel):
                continue
            path = os.path.join(top, rel)
            e = entry(path)
            rec = p.files.get(rel)
            clean = (e is None and rec is None) or (rec is not None and e is not None and tuple(rec[1:]) == e)
            if not clean:
                # Changed here too and not sent yet: push sends it with the
                # base it had, and the controller judges. Not past this
                # revision until then.
                held.append(rel)
                continue
            if not gone and rec and rec[0] == sha and e is not None:
                continue                          # our own change, come back
            moved = True
            try:
                if gone:
                    if e is not None:
                        os.remove(path)
                    p.files.pop(rel, None)
                elif link:
                    self.place_link(top, rel, link)
                    self.agree(p, top, rel, sha)
                else:
                    got = self.fetch(p, top, rel, sha, mode)
                    self.agree(p, top, rel, got)
            except OSError as ex:
                p.error = str(ex)[:200]
                held.append(rel)
        if not held:
            moved |= p.rev != int(r.get("rev") or p.rev)
            p.rev = int(r.get("rev") or p.rev)
            p.error = ""
        else:
            p.hinted = True
        if moved:
            p.save()

    # -- up -----------------------------------------------------------------------------
    def looked(self, p, top):
        """{rel: entry or None} for every path that may have moved: the
        watcher's paths and what was still moving last tick, or the whole
        tree when the watcher cannot say (none here, a directory moved, a
        minute since the last whole walk)."""
        if p.watch is None and os.path.isdir(top) and _inotify() is not None:
            try:
                p.watch = Watcher(top)
                p.walked_at = 0.0
            except OSError as e:
                log(f"sync: {p.name}: walking the tree every tick, without inotify ({e})")
                p.watch = False
        full, dirty = (True, set()) if not p.watch else p.watch.changes()
        if full or time.monotonic() - p.walked_at > WALK_EVERY:
            p.walked_at = time.monotonic()
            now = walk(top) if os.path.isdir(top) else {}
            return {**{rel: None for rel in p.files if rel not in now}, **now}
        out = {}
        for rel in dirty | set(p.moving):
            out[rel] = entry(os.path.join(top, rel))
        return out

    def push(self, p, top):
        moved = {}
        for rel, e in self.looked(p, top).items():
            rec = p.files.get(rel)
            if e is None:
                if rec is not None:
                    moved[rel] = None
            elif rec is None or tuple(rec[1:]) != e:
                moved[rel] = e
        # A file still being written goes on the next tick: what was seen
        # moving last time must be seen the same now.
        ready = {k: v for k, v in moved.items() if k in p.moving and p.moving[k] == v}
        p.moving = {k: v for k, v in moved.items() if k not in ready}
        changed = False
        for rel, e in sorted(ready.items()):
            rec = p.files.get(rel)
            base = rec[0] if rec else ""
            path = os.path.join(top, rel)
            try:
                if e is None:
                    sha = ""
                elif e[3]:
                    sha = link_sha(e[3])
                else:
                    sha = sha_file(path)
            except OSError:
                continue
            if rec and e is not None and sha == rec[0] and e[2] == rec[3]:
                p.files[rel] = [sha, *e]          # touched, not changed
                changed = True
                continue
            if self.put(p, top, rel, e, base, sha):
                changed = True
        if changed:
            p.save()

    def put(self, p, top, rel, e, base, sha):
        q = {"project": p.name, "path": rel, "base": base}
        path = os.path.join(top, rel)
        if e is None:
            q["gone"] = "1"
        elif e[3]:
            q["link"] = e[3]
        else:
            q["mode"] = str(e[2])
        url = "sync-put?" + urllib.parse.urlencode(q)
        if e is None or e[3]:
            empty = os.path.join(self.record_dir(), ".empty")
            open(empty, "wb").close()
            code, r = self.agent.ctl.upload(url, empty, timeout=60)
        else:
            code, r = self.agent.ctl.upload(url, path, timeout=600)
        if code != 200:
            p.error = f"{rel}: {r.get('error') or code}"[:200]
            return False
        if r.get("conflict"):
            # The controller kept another version; ours is beside it as
            # kept_as. Take the one it kept, so the two copies agree.
            log(f"sync: {p.name}/{rel} was changed on both sides; ours is kept as {r.get('kept_as') or '(deleted here)'}")
            cur = str(r.get("sha") or "")
            try:
                if not cur:
                    if os.path.lexists(path):
                        os.remove(path)
                    p.files.pop(rel, None)
                elif r.get("link"):
                    self.place_link(top, rel, str(r["link"]))
                    self.agree(p, top, rel, cur)
                else:
                    got = self.fetch(p, top, rel, cur, e[2] if e else 0o644)
                    self.agree(p, top, rel, got)
            except OSError as ex:
                p.error = str(ex)[:200]
            p.hinted = True
            return True
        if e is None:
            p.files.pop(rel, None)
        else:
            p.files[rel] = [sha, *e]
        p.error = ""
        return True
