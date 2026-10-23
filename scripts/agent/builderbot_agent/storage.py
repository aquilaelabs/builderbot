"""What this node's disks hold (the Storage page; R146 step 3, disk by
project): each real filesystem with its size and use, each store with what
it holds, Docker's own share, and each project's folders on the node, in
the stores and in the accounts' build caches.

A walk of a big store is minutes, not seconds, so it is never the census's
to wait on: the census carries the last measurement (`last()`), a thread of
its own takes a new one once an hour, and the Storage page's Measure now is
a job that takes one at once (`measure()`). Each walk runs at the lowest
CPU and IO priority, so a full disk being looked at never slows a build.
"""
import contextlib
import glob
import json
import os
import re
import shutil
import subprocess
import threading
import time

from .base import SESSION, SHARE, log

EVERY_S = 3600
# One walk's limit: a store on a slow share that has not answered by then
# is said as not measured rather than holding the next hour's.
WALK_S = 600
# The filesystems a person means by "disk": what holds bytes on a device or
# a share. tmpfs, overlay, proc and their kind are the kernel's or Docker's
# own and say nothing about room.
REAL_FS = frozenset({"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs",
                     "nfs", "nfs4", "cifs", "smb3", "smbfs", "9p", "virtiofs", "ntfs", "ntfs3",
                     "vfat", "exfat", "apfs", "hfs", "fuse.shfs", "fuse.mergerfs", "fuse.sshfs",
                     "ceph", "glusterfs", "fuse.glusterfs"})
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

_last = {}
_lock = threading.Lock()
_busy = threading.Lock()
_started = [False]


def last():
    """The newest measurement, {} before the first has finished."""
    with _lock:
        return dict(_last)


def _nice(argv):
    """argv at the lowest priority this machine offers: nice, and ionice's
    idle class where there is one."""
    pre = ["nice", "-n", "19"] if shutil.which("nice") else []
    if shutil.which("ionice"):
        pre += ["ionice", "-c", "3"]
    return pre + argv


def _du_children(root, timeout=WALK_S):
    """{child name: MB} for each directory directly under root, and root's
    own total under "", from one walk. None when it could not be walked in
    time."""
    if not root or not os.path.isdir(root):
        return {}
    try:
        p = subprocess.run(_nice(["du", "-k", "-x", "--max-depth=1", root]), capture_output=True,
                           text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    out = {}
    base = root.rstrip("/")
    for line in (p.stdout or "").splitlines():
        kb, _, path = line.partition("\t")
        if not kb.isdigit():
            continue
        path = path.rstrip("/")
        name = "" if path == base else os.path.basename(path)
        out[name] = int(kb) // 1024
    return out


def _filesystems():
    """Each real filesystem once, by device: its mount point, source, type
    and room. A device mounted at several places (a bind mount) is listed at
    the shortest path, with the others beside it."""
    seen, out = {}, []
    try:
        with open("/proc/self/mounts") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        src, path, kind = parts[0], parts[1].replace("\\040", " "), parts[2]
        if kind not in REAL_FS or path.startswith(("/proc", "/sys", "/run/credentials")):
            continue
        try:
            st = os.statvfs(path)
            dev = os.stat(path).st_dev
        except OSError:
            continue
        if not st.f_blocks:
            continue
        mb = st.f_frsize / (1024 * 1024)
        row = {"path": path, "source": src[:200], "type": kind, "ro": "ro" in parts[3].split(","),
               "total_mb": int(st.f_blocks * mb), "free_mb": int(st.f_bavail * mb),
               "used_mb": int((st.f_blocks - st.f_bfree) * mb), "also": []}
        if dev in seen:
            first = seen[dev]
            if len(path) < len(first["path"]):
                row["also"] = first["also"] + [first["path"]]
                out[out.index(first)] = row
                seen[dev] = row
            else:
                first["also"].append(path)
            continue
        seen[dev] = row
        out.append(row)
    for r in out:
        r["also"] = r["also"][:8]
    return out[:32]


def fs_of(path, filesystems):
    """The mount point of the listed filesystem a path is on: the one whose
    mount point, or one of the places it is also mounted, is the longest
    prefix of its real path."""
    try:
        real = os.path.realpath(path)
    except OSError:
        real = path
    best, longest = "", -1
    for f in filesystems:
        for at in [f["path"]] + list(f.get("also") or []):
            p = at.rstrip("/") or "/"
            if (real == p or real.startswith(p.rstrip("/") + "/")) and len(p) > longest:
                best, longest = f["path"].rstrip("/") or "/", len(p)
    return best


def _docker():
    """Docker's own use, by kind (images, containers, volumes, build cache),
    as `docker system df` counts it, and the filesystem its root is on."""
    if not shutil.which("docker"):
        return {}
    try:
        p = subprocess.run(["docker", "system", "df", "--format", "{{json .}}"], capture_output=True,
                           text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return {}
    kinds = []
    for line in (p.stdout or "").splitlines():
        with contextlib.suppress(ValueError, TypeError):
            d = json.loads(line)
            kinds.append({"kind": str(d.get("Type") or "")[:40], "count": int(d.get("TotalCount") or 0),
                          "mb": _size_mb(d.get("Size")), "reclaimable_mb": _size_mb(d.get("Reclaimable"))})
    root = ""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        root = subprocess.run(["docker", "info", "--format", "{{.DockerRootDir}}"], capture_output=True,
                              text=True, timeout=15, check=False).stdout.strip()
    return {"kinds": kinds[:8], "root": root[:200]} if kinds else {}


def _size_mb(s):
    """Docker's "1.234GB (40%)" as MB."""
    m = re.match(r"\s*([\d.]+)\s*([kKMGT]?B)", str(s or ""))
    if not m:
        return 0
    mult = {"B": 1 / 1e6, "kB": 1e-3, "KB": 1e-3, "MB": 1, "GB": 1e3, "TB": 1e6}.get(m.group(2), 1)
    return int(float(m.group(1)) * mult)


def _account_builds(home):
    """{project: MB} of every account's per-project build caches under the
    session account's home: the Gradle home and the out-of-tree build each
    session of that project uses (bb-tty), which are where most of a node's
    disk goes. The homes' own total too."""
    if not home or not os.path.isdir(home):
        return {}, None
    out = {}
    roots = glob.glob(os.path.join(home, ".cache", "builderbot", "u", "*", "project")) + \
        glob.glob(os.path.join(home, "users", "*", ".cache", "builderbot", "u", "*", "project"))
    for r in roots[:64]:
        got = _du_children(r) or {}
        for name, mb in got.items():
            if name:
                out[name] = out.get(name, 0) + mb
    whole = _du_children(home, timeout=WALK_S)
    return out, (whole or {}).get("") if whole is not None else None


# A project's virtual phones (R123): each account's AVDs for it, in the
# folder bb emu keeps them in (~/.android/avd-projects/PROJECT, B511), which
# no store holds, so the emulator column read the data store's emu/ and
# missed every one of them (bb-sandbox, 23 Oct: 20 GB of phones, none shown).
AVD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
UID_RE = re.compile(r"^u_[0-9a-f]{8}$")


def avd_homes(home):
    """(uid, folder of that account's projects' AVDs) for the session
    account's home and each account's home under it ("" for the base)."""
    if not home or not os.path.isdir(home):
        return []
    out = [("", os.path.join(home, ".android", "avd-projects"))]
    for u in sorted(glob.glob(os.path.join(home, "users", "u_*")))[:64]:
        if UID_RE.match(os.path.basename(u)):
            out.append((os.path.basename(u), os.path.join(u, ".android", "avd-projects")))
    return [(uid, d) for uid, d in out if os.path.isdir(d)]


def avd_running(avd_dir):
    """Whether the emulator holds this AVD: its multiinstance.lock flocked,
    the test bb emu's emu_held makes."""
    import fcntl
    lock = os.path.join(avd_dir, "multiinstance.lock")
    if not os.path.exists(lock):
        return False
    try:
        with open(lock, "rb") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    except OSError:
        return False


def _phones(home):
    """Every project's phones under the homes: [{project, uid, name, mb,
    running}], one du per project's folder."""
    out = []
    for uid, d in avd_homes(home):
        with contextlib.suppress(OSError):
            for proj in sorted(os.listdir(d))[:300]:
                if not NAME_RE.match(proj):
                    continue
                sizes = _du_children(os.path.join(d, proj))
                for name in sorted(x[:-4] for x in os.listdir(os.path.join(d, proj)) if x.endswith(".avd")):
                    if not AVD_RE.match(name):
                        continue
                    mb = (sizes or {}).get(name + ".avd") if sizes is not None else None
                    out.append({"project": proj, "uid": uid, "name": name, "mb": mb,
                                "running": avd_running(os.path.join(d, proj, name + ".avd"))})
    return out[:200]


def measure(state):
    """One measurement of the whole node: what the tab draws. Several at
    once are one: a second caller waits for the walk already going."""
    with _busy:
        t0 = time.time()
        stores = (state.get("stores") or {}) if isinstance(state.get("stores"), dict) else {}
        fss = _filesystems()
        projects, slow = {}, []

        def add(where, sizes, path):
            if sizes is None:
                slow.append(path)
                return
            for name, mb in sizes.items():
                if name and NAME_RE.match(name):
                    projects.setdefault(name, {})[where] = projects.get(name, {}).get(where, 0) + mb

        store_rows = {}
        for role, path in stores.items():
            if not isinstance(path, str) or not path:
                continue
            sizes = _du_children(path)
            row = {"path": path, "fs": fs_of(path, fss),
                   "used_mb": (sizes or {}).get("") if sizes is not None else None}
            store_rows[role] = row
            # Per project underneath: the cache, the artifacts and a dev
            # instance's data are <store>/<project>; the data store's
            # projects are its emulators', under emu/.
            if role in ("cache", "artifacts", "appdata"):
                add(role, sizes, path)
            elif role == "data":
                add("emulator", _du_children(os.path.join(path, "emu")), path)
            if sizes is None:
                row["slow"] = True
        if os.path.isdir(SHARE):
            add("workspace", _du_children(SHARE), SHARE)
        builds, homes = _account_builds(SESSION.get("home") or "")
        add("builds", builds, "homes")
        phones = _phones(SESSION.get("home") or "")
        for ph in phones:
            if ph["mb"]:
                projects.setdefault(ph["project"], {})["emulator"] = \
                    projects.get(ph["project"], {}).get("emulator", 0) + ph["mb"]
        got = {"at": int(time.time()), "took_s": int(time.time() - t0),
               "filesystems": fss, "stores": store_rows,
               "projects": dict(sorted(projects.items())[:300]),
               "workspace": {"path": SHARE, "fs": fs_of(SHARE, fss)} if os.path.isdir(SHARE) else {},
               "homes": {"path": SESSION.get("home") or "", "mb": homes,
                         "fs": fs_of(SESSION.get("home") or "/", fss)} if SESSION.get("home") else {},
               "docker": _docker(), "phones": phones, "slow": slow[:16]}
        if got["docker"].get("root"):
            got["docker"]["fs"] = fs_of(got["docker"]["root"], fss)
        with _lock:
            _last.clear()
            _last.update(got)
        return got


def start(state_of):
    """The hourly walk, on a thread of its own, started once. `state_of`
    hands it the agent's state as it is at each walk, since a store moved
    from the Nodes page changes where to look."""
    if _started[0]:
        return
    _started[0] = True

    def run():
        # A minute's grace after the agent starts, so a restart is not a
        # walk of every disk at the same moment as the first hello.
        time.sleep(60)
        while True:
            try:
                measure(state_of())
            except Exception as e:                       # noqa: BLE001 (logged, retried next hour)
                log(f"storage: {type(e).__name__}: {e}")
            time.sleep(EVERY_S)
    threading.Thread(target=run, daemon=True, name="storage").start()
