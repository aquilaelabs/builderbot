"""Who reads a coding agent's token on this node (R125 step 6).

Where accounts run as their own users, an account's sign-ins are files in its
home that only it and root can open. Root cannot be kept out by a file mode,
so this is the tripwire: fanotify on the folders that hold the three tokens
(Claude Code's, Codex CLI's, Copilot CLI's, Grok Build's), an open by anything but the
account's own user or this agent and its children said in the node's log and
carried to the controller on the next hello, which audits it and puts it on
the bell. Each pass also holds the files at 600, the account's.

Linux only, and only as root: fanotify needs CAP_SYS_ADMIN. Where it cannot
start, the reason is kept and said once, and nothing else changes.
"""
import contextlib
import ctypes
import os
import struct
import threading
import time

from .base import log

# The folder in an account's home, and the file in it that is the sign-in.
TOKENS = {".claude": ".credentials.json", ".codex": "auth.json", ".copilot": "config.json", ".grok": "auth.json"}

FAN_CLOEXEC = 0x1
FAN_CLASS_NOTIF = 0x0
FAN_MARK_ADD = 0x1
FAN_OPEN = 0x20
FAN_EVENT_ON_CHILD = 0x08000000
AT_FDCWD = -100
META = struct.Struct("=IBBHQii")      # event_len, vers, reserved, metadata_len, mask, fd, pid
KEEP = 32                             # reads kept for the hello
SAY_S = 7 * 86400                     # ...for a week


def _proc(pid):
    """(uid, ppid, comm) of a process, or None once it has gone."""
    try:
        with open(f"/proc/{pid}/status") as f:
            st = dict(line.rstrip("\n").split(":\t", 1) for line in f if ":\t" in line)
        return int(st["Uid"].split()[1]), int(st["PPid"]), st.get("Name", "?")
    except (OSError, KeyError, ValueError, IndexError):
        return None


def ours(pid, me):
    """Whether `pid` is this agent or was started by it (a sign-in, the
    login listing): the agent reads the tokens as root by design."""
    seen = 0
    while pid > 1 and seen < 64:
        if pid == me:
            return True
        p = _proc(pid)
        if not p:
            return False
        pid, seen = p[1], seen + 1
    return False


def judge(path, pid, owner, me):
    """A read worth saying, as {path, pid, comm, uid}, or None: the file's
    own user and the agent's own tree are expected."""
    p = _proc(pid)
    if not p:
        return {"path": path, "pid": pid, "comm": "?", "uid": -1}
    uid, _, comm = p
    if uid == owner or ours(pid, me):
        return None
    return {"path": path, "pid": pid, "comm": comm[:32], "uid": uid}


class TokenWatch:
    def __init__(self):
        self.fd = -1
        self.why = ""
        self.marked = set()
        self.reads = []
        self.lock = threading.Lock()
        self.me = os.getpid()

    def start(self):
        if self.fd >= 0 or self.why:
            return self.fd >= 0
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            libc.fanotify_init.argtypes = [ctypes.c_uint, ctypes.c_uint]
            libc.fanotify_mark.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_uint64,
                                           ctypes.c_int, ctypes.c_char_p]
            fd = libc.fanotify_init(FAN_CLOEXEC | FAN_CLASS_NOTIF, os.O_RDONLY | getattr(os, "O_LARGEFILE", 0))
        except (OSError, AttributeError) as e:
            self.why = f"fanotify is not here: {e}"
        else:
            if fd < 0:
                self.why = f"fanotify_init: {os.strerror(ctypes.get_errno())}"
            else:
                self.fd, self.libc = fd, libc
                threading.Thread(target=self.loop, name="tokenwatch", daemon=True).start()
        if self.why:
            log(f"token reads are not watched here: {self.why}")
        return self.fd >= 0

    def watch(self, home, pw):
        """One account's home, its user `pw`: the token files 600 and its
        own, and their folders marked (a folder mark outlives the file being
        replaced, which every agent does when it refreshes a token)."""
        for d, name in TOKENS.items():
            folder = os.path.join(home, d)
            f = os.path.join(folder, name)
            with contextlib.suppress(OSError):
                st = os.lstat(f)
                if not os.path.islink(f) and (st.st_mode & 0o077 or st.st_uid != pw.pw_uid):
                    os.chown(f, pw.pw_uid, pw.pw_gid, follow_symlinks=False)
                    os.chmod(f, 0o600)
            if self.fd < 0 or not os.path.isdir(folder) or os.path.islink(folder):
                continue
            key = os.stat(folder).st_ino, folder
            if key in self.marked:
                continue
            if self.libc.fanotify_mark(self.fd, FAN_MARK_ADD, FAN_OPEN | FAN_EVENT_ON_CHILD,
                                       AT_FDCWD, folder.encode()) == 0:
                self.marked.add(key)

    def loop(self):
        while True:
            try:
                buf = os.read(self.fd, 4096)
            except OSError:
                time.sleep(5)
                continue
            at = 0
            while at + META.size <= len(buf):
                ln, _, _, _, _, efd, pid = META.unpack_from(buf, at)
                at += ln or META.size
                if efd < 0:
                    continue
                try:
                    path = os.readlink(f"/proc/self/fd/{efd}")
                    st = os.fstat(efd)
                except OSError:
                    path, st = "", None
                finally:
                    with contextlib.suppress(OSError):
                        os.close(efd)
                folder, name = os.path.split(path)
                if not st or TOKENS.get(os.path.basename(folder)) != name:
                    continue
                got = judge(path, pid, st.st_uid, self.me)
                if got:
                    self.said(got)

    def said(self, got):
        now = int(time.time())
        with self.lock:
            # One line per process and file: a cat is one open, an editor
            # several, and the bell wants the reader, not the count.
            if any(r["pid"] == got["pid"] and r["path"] == got["path"] and now - r["at"] < 600
                   for r in self.reads):
                return
            self.reads.append({**got, "at": now})
            self.reads = [r for r in self.reads if now - r["at"] < SAY_S][-KEEP:]
        log(f"token read: {got['path']} opened by {got['comm']} (pid {got['pid']}, uid {got['uid']}), "
            "neither its account nor this agent")

    def report(self):
        with self.lock:
            return list(self.reads)
