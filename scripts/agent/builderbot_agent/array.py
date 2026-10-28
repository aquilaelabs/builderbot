"""An Unraid-style array on the controller's own machine (R162 step 2):
disks of mixed sizes, each its own XFS or btrfs filesystem, pooled into one
tree by mergerfs with parity on one or two disks kept by SnapRAID, which
is periodic rather than real time: a file written since the last sync is
unprotected until the next, and the page says so. BuilderBot's own record
(/etc/builderbot/array.json, written whole by the storage-array job) is
what snapraid.conf and the array's fstab lines are rendered from; the
census reads the record, each disk's room and the state file the last
sync, scrub or check left. Disks are named to the record by their
/dev/disk/by-id links and mounted by filesystem UUID, so the array follows
its disks across ports and reboots. A disk that holds anything is refused
unless the job says to wipe it, and nothing is ever made on the system
disk; destroying the array unmounts it and forgets it, every data disk's
files left as they are, readable on any Linux.
"""
import json
import os
import re
import shutil
import subprocess
import time

from .disks import disks_now
from .pools import by_id, _out

RECORD = "/etc/builderbot/array.json"
STATE = "/var/lib/builderbot/array-state.json"
SNAPRAID_CONF = "/etc/snapraid.conf"
FSTAB = "/etc/fstab"
MARK = "# builderbot-array"
MOUNT = "/mnt/array"
DISKS = "/mnt/disks"
PARITY = "/mnt/parity"
CONTENT = "/var/lib/builderbot/snapraid.content"
FS = ("xfs", "btrfs")
# mergerfs's create policies as the page offers them.
POLICIES = {"mfs": "most free space", "lfs": "fill up (least free space)", "epmfs": "existing path, then most free space", "ff": "first disk with room"}
ACTIONS = ("create", "add", "replace", "sync", "scrub", "check", "destroy")
MAX_DATA, MAX_PARITY = 24, 2
NAME_RE = re.compile(r"[a-z][a-z0-9]{0,31}")
SLOT_RE = re.compile(r"(d|p)([1-9][0-9]?)")


def _env(k, d):
    return os.environ.get(k) or d


def read_record():
    try:
        with open(_env("BB_ARRAY_RECORD", RECORD), encoding="utf-8") as f:
            r = json.load(f)
        return r if isinstance(r, dict) and isinstance(r.get("data"), list) else {}
    except (OSError, ValueError):
        return {}


def write_record(rec):
    path = _env("BB_ARRAY_RECORD", RECORD)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, sort_keys=True)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def _state():
    try:
        with open(_env("BB_ARRAY_STATE", STATE), encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def _state_set(**kw):
    s = _state()
    s.update(kw)
    path = _env("BB_ARRAY_STATE", STATE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".new", "w", encoding="utf-8") as f:
        json.dump(s, f)
    os.replace(path + ".new", path)


def mount_of(kind, slot):
    return f"{DISKS}/d{slot}" if kind == "d" else f"{PARITY}/p{slot}"


def render_snapraid(rec):
    """snapraid.conf from the record: the parity files on the parity disks,
    a content file on the system and on every data disk, each data disk by
    its slot."""
    out = ["# Written by BuilderBot (the Storage page): the array's SnapRAID layout. Do not edit; the page writes it whole.\n"]
    for p in rec.get("parity") or []:
        n = int(p["slot"])
        out.append(f"{'' if n == 1 else f'{n}-'}parity {mount_of('p', n)}/snapraid.{'' if n == 1 else f'{n}-'}parity\n")
    out.append(f"content {CONTENT}\n")
    for d in rec.get("data") or []:
        out.append(f"content {mount_of('d', int(d['slot']))}/.snapraid.content\n")
    for d in rec.get("data") or []:
        out.append(f"data d{int(d['slot'])} {mount_of('d', int(d['slot']))}/\n")
    out.append("exclude *.unrecoverable\nexclude /lost+found/\nexclude .snapraid.content\nexclude /.Trash*/\nexclude .DS_Store\n"
               "blocksize 256\nhashsize 16\nautosave 500\n")
    return "".join(out)


def render_fstab(rec):
    """The array's fstab lines: each disk by UUID at its slot's mount
    (nofail, so a missing disk never holds the boot), and the merged tree
    over the data disks, with the record's create policy and 20 GB kept
    free on each before the next is picked."""
    lines = []
    for d in rec.get("data") or []:
        lines.append(f"UUID={d['uuid']} {mount_of('d', int(d['slot']))} {d.get('fs', 'xfs')} defaults,nofail,noatime 0 0 {MARK}\n")
    for p in rec.get("parity") or []:
        lines.append(f"UUID={p['uuid']} {mount_of('p', int(p['slot']))} {p.get('fs', 'xfs')} defaults,nofail,noatime 0 0 {MARK}\n")
    if rec.get("data"):
        policy = rec.get("policy") if rec.get("policy") in POLICIES else "mfs"
        req = ",".join(f"x-systemd.requires-mounts-for={mount_of('d', int(d['slot']))}" for d in rec["data"])
        lines.append(f"{DISKS}/d* {MOUNT} fuse.mergerfs defaults,nofail,allow_other,use_ino,cache.files=off,dropcacheonclose=true,"
                     f"category.create={policy},moveonenospc=true,minfreespace=20G,fsname=bbarray,{req} 0 0 {MARK}\n")
    return "".join(lines)


def write_fstab(rec):
    path = _env("BB_ARRAY_FSTAB", FSTAB)
    try:
        with open(path, encoding="utf-8") as f:
            kept = [ln for ln in f.read().splitlines(True) if not ln.rstrip().endswith(MARK)]
    except OSError:
        kept = []
    text = "".join(kept)
    if text and not text.endswith("\n"):
        text += "\n"
    with open(path + ".new", "w", encoding="utf-8") as f:
        f.write(text + render_fstab(rec))
    os.chmod(path + ".new", 0o644)
    os.replace(path + ".new", path)


def _df(path):
    try:
        st = os.statvfs(path)
        return st.f_frsize * st.f_blocks // 1048576, st.f_frsize * (st.f_blocks - st.f_bavail) // 1048576
    except OSError:
        return 0, 0


def array_now():
    """{policy, mount, data: [{slot, id, fs, size_mb, used_mb, mounted}],
    parity: [...], last_sync, last_scrub, last_check, status, running} for
    the census; {} where no array is recorded."""
    rec = read_record()
    if not rec:
        return {}
    st = _state()

    def row(kind, x):
        m = mount_of(kind, int(x["slot"]))
        mounted = os.path.ismount(m)
        size, used = _df(m) if mounted else (0, 0)
        return {"slot": int(x["slot"]), "id": str(x.get("id") or "")[:120], "fs": str(x.get("fs") or "")[:8],
                "size_mb": size, "used_mb": used, "mounted": mounted}
    return {"policy": str(rec.get("policy") or "mfs"), "mount": MOUNT, "mounted": os.path.ismount(MOUNT),
            "data": [row("d", d) for d in rec.get("data") or []][:MAX_DATA],
            "parity": [row("p", p) for p in rec.get("parity") or []][:MAX_PARITY],
            "last_sync": int(st.get("last_sync") or 0), "last_scrub": int(st.get("last_scrub") or 0),
            "last_check": int(st.get("last_check") or 0), "status": str(st.get("status") or "")[:400],
            "running": str(st.get("running") or "")[:16]}


class ArrayMixin:
    """Agent's array jobs: one of the parts class Agent (agent.py) is made of."""

    def array_pass(self):
        """Once a minute: a recorded array whose mounts are missing (a disk
        back after a reboot without it) mounted again from fstab."""
        rec = read_record()
        if not rec or os.geteuid() != 0:
            return
        for kind, key in (("d", "data"), ("p", "parity")):
            for x in rec.get(key) or []:
                m = mount_of(kind, int(x["slot"]))
                if not os.path.ismount(m) and os.path.isdir(m):
                    subprocess.run(["mount", m], capture_output=True, timeout=60, check=False)
        if rec.get("data") and not os.path.ismount(MOUNT) and os.path.isdir(MOUNT):
            subprocess.run(["mount", MOUNT], capture_output=True, timeout=60, check=False)

    def _apply_storage_array(self, job, cfg):
        say = job.say
        mergerfs, snapraid = shutil.which("mergerfs"), shutil.which("snapraid")
        if not mergerfs or not snapraid or os.geteuid() != 0:
            say("refused: an array is made by mergerfs and SnapRAID as root, and this agent lacks one of them or is not root (the storage feature installs them)\n")
            return "failed", 77
        action = str(cfg.get("array") or "")
        if action not in ACTIONS:
            say(f"refused: {action or 'no action'} is not an array action (one of {', '.join(ACTIONS)})\n")
            return "failed", 64
        rec = read_record()
        disks = {d["name"]: d for d in disks_now(smart=False)}
        wipe = cfg.get("wipe") is True

        def disk_ok(n):
            d = disks.get(n)
            if not d:
                say(f"refused: {n} is not a disk this machine lists\n")
                return False
            if d.get("system"):
                say(f"refused: {n} is the system disk, which never goes into the array\n")
                return False
            held = [p for p in d.get("parts") or [] if p.get("holds") not in ("nothing", "")] or ([d] if d.get("holds") not in ("nothing", "") else [])
            if held and not wipe:
                say(f"refused: {n} holds {held[0].get('holds')}; the job must say to wipe it\n")
                return False
            return True

        def make_fs(n, fs, label):
            """The whole disk one filesystem, labeled; its UUID back."""
            if wipe:
                self._sh(job, ["wipefs", "-a", f"/dev/{n}"], timeout=120)
            argv = ["mkfs.xfs", "-f", "-L", label, f"/dev/{n}"] if fs == "xfs" else ["mkfs.btrfs", "-f", "-L", label, f"/dev/{n}"]
            if self._sh(job, argv, timeout=600) != 0:
                return ""
            return _out(["blkid", "-s", "UUID", "-o", "value", f"/dev/{n}"]).strip()

        def mount_all():
            for kind, key in (("d", "data"), ("p", "parity")):
                for x in rec.get(key) or []:
                    m = mount_of(kind, int(x["slot"]))
                    os.makedirs(m, exist_ok=True)
                    if not os.path.ismount(m) and self._sh(job, ["mount", m], timeout=60) != 0:
                        return False
            os.makedirs(MOUNT, exist_ok=True)
            if os.path.ismount(MOUNT):
                # mergerfs reads its branches' glob at mount: the tree is
                # remounted so a disk added or replaced is in it (a file
                # open through it at that moment sees an error once).
                self._sh(job, ["umount", "-l", MOUNT], timeout=60)
            return self._sh(job, ["mount", MOUNT], timeout=60) == 0

        def settle():
            write_fstab(rec)
            with open(_env("BB_SNAPRAID_CONF", SNAPRAID_CONF) + ".new", "w", encoding="utf-8") as f:
                f.write(render_snapraid(rec))
            os.replace(_env("BB_SNAPRAID_CONF", SNAPRAID_CONF) + ".new", _env("BB_SNAPRAID_CONF", SNAPRAID_CONF))
            os.makedirs(os.path.dirname(CONTENT), exist_ok=True)
            write_record(rec)

        def run_snapraid(what, *extra, key=None, timeout=86400):
            _state_set(running=what)
            try:
                rc = self._sh(job, [snapraid, what, *extra], timeout=timeout)
            finally:
                _state_set(running="")
            if rc == 0 and key:
                _state_set(**{key: int(time.time())})
            return rc

        fs = str(cfg.get("fs") or "xfs")
        if action == "create":
            data = [str(x) for x in (cfg.get("data") or []) if isinstance(x, str)]
            parity = [str(x) for x in (cfg.get("parity") or []) if isinstance(x, str)]
            policy = str(cfg.get("policy") or "mfs")
            if rec:
                say("refused: an array is here already; add to it, or destroy it first\n")
                return "failed", 66
            if fs not in FS or policy not in POLICIES:
                say(f"refused: a filesystem is one of {', '.join(FS)} and a policy one of {', '.join(POLICIES)}\n")
                return "failed", 64
            if not 1 <= len(data) <= MAX_DATA or not 1 <= len(parity) <= MAX_PARITY or len(set(data + parity)) != len(data) + len(parity):
                say(f"refused: an array takes 1 to {MAX_DATA} data disks and 1 or {MAX_PARITY} parity disks, each once; {len(data)} and {len(parity)} named\n")
                return "failed", 64
            if not all(disk_ok(n) for n in data + parity):
                return "failed", 65
            biggest = max(disks[n]["size_mb"] for n in data)
            small = [n for n in parity if disks[n]["size_mb"] < biggest]
            if small:
                say(f"refused: a parity disk is at least as large as the largest data disk; {', '.join(small)} is smaller\n")
                return "failed", 64
            rec = {"policy": policy, "data": [], "parity": [], "made": int(time.time())}
            say(f"array create: {len(data)} data disk(s) as {fs}, {len(parity)} parity, {POLICIES[policy]}\n")
            for i, n in enumerate(data, 1):
                uuid = make_fs(n, fs, f"bb-d{i}")
                if not uuid:
                    return "failed", 1
                rec["data"].append({"slot": i, "id": by_id(n), "uuid": uuid, "fs": fs})
            for i, n in enumerate(parity, 1):
                uuid = make_fs(n, fs, f"bb-p{i}")
                if not uuid:
                    return "failed", 1
                rec["parity"].append({"slot": i, "id": by_id(n), "uuid": uuid, "fs": fs})
            settle()
            if not mount_all():
                return "failed", 1
            rc = run_snapraid("sync", key="last_sync", timeout=3600)
        elif action == "add":
            n = str(cfg.get("disk") or "")
            if not rec:
                say("refused: no array here yet\n")
                return "failed", 66
            if len(rec["data"]) >= MAX_DATA or not disk_ok(n):
                return "failed", 65
            fs = rec["data"][0].get("fs", "xfs") if rec["data"] else fs
            biggest = max(disks[n]["size_mb"], *(_df(mount_of("d", int(d["slot"])))[0] for d in rec["data"]))
            small = [p for p in rec["parity"] if _df(mount_of("p", int(p["slot"])))[0] < biggest]
            if small:
                say(f"refused: {n} is larger than the parity disk p{small[0]['slot']}; parity is at least as large as every data disk\n")
                return "failed", 64
            slot = max((int(d["slot"]) for d in rec["data"]), default=0) + 1
            say(f"array add: {n} as d{slot}, {fs}\n")
            uuid = make_fs(n, fs, f"bb-d{slot}")
            if not uuid:
                return "failed", 1
            rec["data"].append({"slot": slot, "id": by_id(n), "uuid": uuid, "fs": fs})
            settle()
            if not mount_all():
                return "failed", 1
            rc = run_snapraid("sync", key="last_sync")
        elif action == "replace":
            which, n = str(cfg.get("which") or ""), str(cfg.get("new") or "")
            m = SLOT_RE.fullmatch(which)
            if not rec or not m:
                say(f"refused: replace takes the slot to replace (d2, p1) and the new disk; {which or 'nothing'} named\n")
                return "failed", 64
            kind, slot = m.group(1), int(m.group(2))
            rows = rec["data"] if kind == "d" else rec["parity"]
            old = next((x for x in rows if int(x["slot"]) == slot), None)
            if not old:
                say(f"refused: the array has no {which}\n")
                return "failed", 66
            if not disk_ok(n):
                return "failed", 65
            if kind == "d":
                biggest = max(disks[n]["size_mb"], *(_df(mount_of("d", int(d["slot"])))[0] for d in rec["data"] if int(d["slot"]) != slot))
                if any(_df(mount_of("p", int(p["slot"])))[0] < biggest for p in rec["parity"]):
                    say(f"refused: {n} is larger than a parity disk; parity is at least as large as every data disk\n")
                    return "failed", 64
            else:
                biggest = max((_df(mount_of("d", int(d["slot"])))[0] for d in rec["data"]), default=0)
                if disks[n]["size_mb"] < biggest:
                    say(f"refused: {n} is smaller than the largest data disk, which a parity disk may not be\n")
                    return "failed", 64
            mnt = mount_of(kind, slot)
            if os.path.ismount(mnt):
                self._sh(job, ["umount", "-l", mnt], timeout=60)
            say(f"array replace {which}: {old.get('id')} with {n} ({by_id(n)})\n")
            uuid = make_fs(n, old.get("fs", fs), f"bb-{which}")
            if not uuid:
                return "failed", 1
            old.update(id=by_id(n), uuid=uuid)
            settle()
            if not mount_all():
                return "failed", 1
            if kind == "d":
                say(f"rebuilding d{slot} from parity: the array is readable meanwhile, slower\n")
                rc = run_snapraid("fix", "-d", f"d{slot}")
                if rc == 0:
                    rc = run_snapraid("sync", key="last_sync")
            else:
                say(f"rebuilding parity on p{slot}: the array is unprotected until this ends\n")
                rc = run_snapraid("sync", "-F", key="last_sync")
        elif action in ("sync", "scrub", "check"):
            if not rec:
                say("refused: no array here yet\n")
                return "failed", 66
            if _state().get("running"):
                say(f"refused: a {_state()['running']} is running on the array already; one at a time\n")
                return "failed", 75
            if action == "check":
                rc = run_snapraid("status", key="last_check", timeout=3600)
                _state_set(status=" ".join(job.text().splitlines()[-3:])[:400] if hasattr(job, "text") else "")
            elif action == "sync":
                rc = run_snapraid("sync", key="last_sync")
            else:
                rc = run_snapraid("scrub", key="last_scrub")
        else:
            if not rec:
                say("refused: no array here yet\n")
                return "failed", 66
            if str(cfg.get("confirm") or "") != "array":
                say("refused: destroying the array takes the word array again as the confirmation\n")
                return "failed", 64
            say("array destroy: unmounted and forgotten; every data disk keeps its files, readable on any Linux\n")
            if os.path.ismount(MOUNT):
                self._sh(job, ["umount", "-l", MOUNT], timeout=60)
            for kind, key in (("d", "data"), ("p", "parity")):
                for x in rec.get(key) or []:
                    m = mount_of(kind, int(x["slot"]))
                    if os.path.ismount(m):
                        self._sh(job, ["umount", "-l", m], timeout=60)
            rec = {}
            write_fstab(rec)
            for path in (_env("BB_ARRAY_RECORD", RECORD), _env("BB_SNAPRAID_CONF", SNAPRAID_CONF), _env("BB_ARRAY_STATE", STATE)):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            rc = 0
        self.hello_again(f"the array: {action}")
        return ("succeeded", 0) if rc == 0 else ("failed", rc)

