"""A synced node's Claude conversations and memories, kept in step with the
controller's (B613).

Every account's ~/.claude/projects is a link to
/workspace/.claude/<uid>/projects (lib/common.sh's claude_projects_link).
On the controller that is the original. A node holds its projects as a
synced copy (R162, R163) with no share, so this keeps that directory on
the node itself, owned by the
session account, and mirrors it with the controller's (claudesync.py
there), for the folders of the projects the node holds:

- A file written here goes up: a transcript as its new tail, checked
  against the last bytes the controller has, anything else whole.
- A file the controller has and this node has never had comes down when
  it is small (a memory, a short conversation). A large conversation comes
  down when somebody resumes it here: bb-tty fetches it (bb transcripts
  fetch), since copying every long conversation to every node is
  gigabytes nobody asked for.
- A memory removed on one side is removed on the other. A conversation is
  never removed across: the controller's copy is the record, and one
  Claude Code cleaned up here is not fetched again.

The last state both sides agreed on is kept per file, so a file that
differs is known to have changed here or there.
"""
import contextlib
import json
import os
import re
import threading
import time
import urllib.parse
from .base import log

TICK = 5.0
LIST_EVERY = 30.0
PULL_MAX = 1024 * 1024           # what comes down without being asked for
MAX_FILE = 2 * 1024 * 1024 * 1024
TAIL = 4096
UID = re.compile(r"u_[0-9a-f]{8}")
TMP = ".bbsync-"
BBIGNORE = ("BuilderBot: each account's Claude transcripts and memories, kept in step "
            "with the controller's. Not a project.\n")


def slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def project_of(entry, ws, projects):
    """The project a transcripts folder belongs to, or "" (the
    controller's claudesync.project_of)."""
    for p in projects:
        if entry == slug(f"{ws}/{p}") or re.fullmatch(
                re.escape(slug(f"{ws}/.worktrees/{p}") + "-") + r"u-[0-9a-f]{8}", entry):
            return p
    return ""


def is_memory(rel):
    """A memory file, which follows a removal; anything else in a folder is
    a conversation's, which does not."""
    parts = rel.split("/")
    return len(parts) >= 3 and parts[1] == "memory"


def stamp(p):
    """[size, mtime in ms] of a regular file, or None."""
    try:
        s = os.lstat(p)
    except OSError:
        return None
    if not os.path.isfile(p) or os.path.islink(p):
        return None
    return [s.st_size, s.st_mtime_ns // 1_000_000]


def same(a, b):
    return a is not None and b is not None and a[0] == b[0] and abs(a[1] - b[1]) < 2000


def tail_sha(path, end):
    import hashlib
    start = max(0, end - TAIL)
    with open(path, "rb") as f:
        f.seek(start)
        return hashlib.sha256(f.read(end - start)).hexdigest()


def plan(local, ctl, rec, fresh):
    """What to do with each file: [(action, key)], action one of push, pull,
    drop-here, drop-there, agree, forget. `local` and `ctl` map
    "uid/rel" to [size, mtime]; `rec` to the last agreed stamp, or None for
    a conversation this side let go of. Decisions that rest on what the
    controller has are taken only on a fresh listing."""
    out = []
    for key in sorted(set(local) | set(ctl) | set(rec)):
        here, there = local.get(key), ctl.get(key)
        known = key in rec
        was = rec.get(key)
        rel = key.split("/", 1)[1]
        if here is not None and same(here, there):
            if not same(here, was):
                out.append(("agree", key))
            continue
        if here is not None and not same(here, was):
            out.append(("push", key))              # changed here, or new here
            continue
        if not fresh:
            continue
        if here is not None and there is None:
            # Unchanged here since the two agreed, and gone there.
            out.append(("drop-here" if is_memory(rel) else "forget", key))
        elif here is None and there is not None:
            if not known:
                if there[0] <= PULL_MAX:
                    out.append(("pull", key))
            elif was is not None:
                out.append(("drop-there" if is_memory(rel) else "forget", key))
            # (known and was None: let go of here, and not fetched again)
        elif here is not None and there is not None:
            # Unchanged here, changed there.
            if there[0] <= PULL_MAX:
                out.append(("pull", key))
        elif here is None and there is None and known:
            out.append(("gone", key))
    return out


class ClaudeMirror:
    def __init__(self, agent, wssync):
        self.agent, self.wssync = agent, wssync
        self.ctl = {}
        self.listed_at = 0.0
        self.rec = None
        self.thread = None
        self.left = 0             # files here not yet agreed with the controller, for the drain (R164)

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.run, name="claudesync", daemon=True)
            self.thread.start()

    def run(self):
        while True:
            try:
                self.step()
            except Exception as e:                       # noqa: BLE001 (the loop must live)
                log(f"claudesync: {type(e).__name__}: {e}")
            time.sleep(TICK)

    # -- where --------------------------------------------------------------------------
    def top(self):
        return os.path.join(self.wssync.root, ".claude")

    def rec_path(self):
        return os.path.join(self.wssync.record_dir(), "claude.json")

    def load(self):
        if self.rec is None:
            try:
                with open(self.rec_path()) as f:
                    self.rec = dict(json.load(f))
            except (OSError, ValueError):
                self.rec = {}
        return self.rec

    def save(self):
        tmp = self.rec_path() + ".new"
        with open(tmp, "w") as f:
            json.dump(self.rec, f)
        os.replace(tmp, self.rec_path())

    def own(self, path):
        o = self.wssync.owner()
        if o:
            with contextlib.suppress(OSError):
                os.lchown(path, *o)

    def ready_top(self):
        """/workspace/.claude, the session account's, so claude_projects_link
        can make an account's folder in it as that account."""
        top = self.top()
        if not os.path.isdir(top):
            os.makedirs(top, exist_ok=True)
            os.chmod(top, 0o755)
            self.own(top)
        ign = os.path.join(top, ".bbignore")
        if not os.path.exists(ign):
            with open(ign, "w") as f:
                f.write(BBIGNORE)
            self.own(ign)

    def mkdirs(self, uid, rel_dir):
        cur = os.path.join(self.top(), uid)
        if not os.path.isdir(cur):
            os.mkdir(cur, 0o700)
            self.own(cur)
        for part in ["projects", *[x for x in rel_dir.split("/") if x]]:
            cur = os.path.join(cur, part)
            if not os.path.isdir(cur):
                os.mkdir(cur)
                self.own(cur)

    def walk(self, held):
        out = {}
        ws = self.wssync.root
        try:
            uids = [d for d in os.listdir(self.top()) if UID.fullmatch(d)]
        except OSError:
            return out
        for uid in uids:
            base = os.path.join(self.top(), uid, "projects")
            if os.path.islink(base):
                continue
            try:
                entries = os.listdir(base)
            except OSError:
                continue
            for entry in entries:
                if not project_of(entry, ws, held):
                    continue
                for d, dirs, files in os.walk(os.path.join(base, entry)):
                    dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(d, x))]
                    for n in files:
                        if n.startswith(TMP):
                            continue
                        p = os.path.join(d, n)
                        s = stamp(p)
                        if s is not None:
                            out[f"{uid}/{os.path.relpath(p, base)}"] = s
        return out

    # -- the loop -------------------------------------------------------------------------
    def step(self):
        ws = self.wssync
        if (getattr(self.agent, "state", None) or {}).get("host_only"):
            return                       # a hosting-only node holds no project
        if ws.mode != "sync" or os.path.ismount(ws.root) or not os.path.isdir(ws.root):
            return
        self.ready_top()
        with ws.lock:
            held = [n for n, p in ws.projects.items() if not p.ro]
        if not held:
            self.left = 0
            return
        fresh = False
        now = time.monotonic()
        if now - self.listed_at > LIST_EVERY:
            st, r = self.agent.ctl.call("claude", {}, timeout=60)
            if st != 200 or not isinstance(r.get("accounts"), dict):
                return
            self.ctl = {f"{uid}/{rel}": v for uid, files in r["accounts"].items()
                        if UID.fullmatch(str(uid)) and isinstance(files, dict)
                        for rel, v in files.items() if isinstance(v, list) and len(v) == 2}
            self.listed_at, fresh = now, True
        rec = self.load()
        before = json.dumps(rec, sort_keys=True)
        local = self.walk(held)
        for act, key in plan(local, self.ctl, rec, fresh):
            try:
                getattr(self, "do_" + act.replace("-", "_"))(key, local.get(key), self.ctl.get(key))
            except OSError as e:
                log(f"claudesync: {act} {key}: {e}")
        if json.dumps(rec, sort_keys=True) != before:
            self.save()
        self.left = sum(1 for k, v in self.walk(held).items() if not same(v, rec.get(k)))

    # -- the actions ------------------------------------------------------------------------
    def path(self, key):
        uid, rel = key.split("/", 1)
        return uid, rel, os.path.join(self.top(), uid, "projects", rel)

    def do_agree(self, key, here, there):
        self.rec[key] = here

    def do_forget(self, key, here, there):
        # Agreed as it stands: a conversation kept here and gone there is
        # not sent again unless it changes, and one gone here is not
        # fetched again unless it is resumed.
        self.rec[key] = here

    def do_gone(self, key, here, there):
        self.rec.pop(key, None)

    def do_push(self, key, here, there, whole=False):
        uid, rel, p = self.path(key)
        if here[0] > MAX_FILE:
            return
        q = {"uid": uid, "path": rel, "mtime": here[1]}
        if not whole and there is not None and rel.endswith(".jsonl") and 0 < there[0] < here[0]:
            q.update(mode="append", offset=there[0], tail=tail_sha(p, there[0]))
            code, r = self.agent.ctl.upload("claude-put?" + urllib.parse.urlencode(q), p,
                                            timeout=600, offset=there[0], length=here[0] - there[0])
        else:
            q.update(mode="whole")
            code, r = self.agent.ctl.upload("claude-put?" + urllib.parse.urlencode(q), p,
                                            timeout=600, length=here[0])
        if code == 409:
            # Not the bytes the controller has. Its length moved since the
            # listing: the next tick appends from where it is now. The same
            # length with other bytes in it (the conversation carried on
            # elsewhere too): this copy goes whole, as the newest.
            size = int(r.get("size") or 0)
            if size and size != q.get("offset"):
                self.ctl[key] = [size, 0]
                return
            return self.do_push(key, here, None, whole=True)
        if code != 200:
            raise OSError(f"the controller answered {code}: {r.get('error') or ''}")
        self.ctl[key] = here
        self.rec[key] = here

    def do_pull(self, key, here, there):
        uid, rel, p = self.path(key)
        d, _, name = rel.rpartition("/")
        self.mkdirs(uid, d)
        tmp = os.path.join(os.path.dirname(p), TMP + name)
        q = urllib.parse.urlencode({"uid": uid, "path": rel})
        code, _ = self.agent.ctl.fetch(f"claude-file?{q}", tmp, timeout=600)
        if code != 200:
            with contextlib.suppress(OSError):
                os.remove(tmp)
            raise OSError(f"the controller answered {code}")
        os.chmod(tmp, 0o600)
        self.own(tmp)
        os.utime(tmp, ns=(there[1] * 1_000_000, there[1] * 1_000_000))
        os.replace(tmp, p)
        self.rec[key] = stamp(p)

    def do_drop_here(self, key, here, there):
        _, _, p = self.path(key)
        with contextlib.suppress(FileNotFoundError):
            os.remove(p)
        self.rec.pop(key, None)

    def do_drop_there(self, key, here, there):
        uid, rel, _ = self.path(key)
        q = urllib.parse.urlencode({"uid": uid, "path": rel, "mode": "gone"})
        code, r = self.agent.ctl.call(f"claude-put?{q}", None, timeout=60)
        if code != 200:
            raise OSError(f"the controller answered {code}: {r.get('error') or ''}")
        self.ctl.pop(key, None)
        self.rec.pop(key, None)
