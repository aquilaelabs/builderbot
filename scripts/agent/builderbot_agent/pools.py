"""ZFS pools on the controller's own machine (R162 step 1): each pool as
zpool says it (size, what is used, health, its members by layout, the last
scrub) for the census, and the storage-pool job: a pool made, grown,
scrubbed, a member replaced, the pool exported or destroyed, each argument
held to its shape and each disk to the census's list before zpool runs.
Disks are named to zpool by their /dev/disk/by-id links, so a pool follows
its disks across ports and reboots; a disk that holds anything is refused
unless the job says to wipe it, and nothing is ever made on the system disk.
Snapshots (R162 step 5): each pool's bb-KIND-DATE-TIME snapshots counted by
kind for the census, and the storage-snapshot job: one taken of the pool's
every dataset (the oldest of its kind pruned past what is kept), a dataset
rolled back to one, or one destroyed.
"""
import os
import re
import shutil
import subprocess
import time

from .base import log
from .disks import disks_now

POOL_RE = re.compile(r"[a-z][a-z0-9_-]{0,30}")
LAYOUTS = {"single": 1, "mirror": 2, "raidz1": 3, "raidz2": 4}
ACTIONS = ("create", "add", "scrub", "replace", "export", "destroy")
MOUNT_ROOT = "/mnt"
SNAP_KINDS = ("hourly", "daily", "weekly", "manual")
SNAP_RE = re.compile(r"bb-(hourly|daily|weekly|manual)-(\d{8})-(\d{4})")
DATASET_RE = re.compile(r"[a-z][a-z0-9_-]{0,30}(/[A-Za-z0-9_.-]{1,64}){0,8}")


def _out(argv, timeout=60):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def by_id(name):
    """The /dev/disk/by-id link for a disk's kernel name (sda, nvme0n1):
    the model-and-serial one before the wwn one, and the kernel name when
    the machine has no links (a VM's virtio disk)."""
    root = "/dev/disk/by-id"
    best = ""
    try:
        for link in sorted(os.listdir(root)):
            if link.endswith(("-part1", "-part2")) or "-part" in link:
                continue
            path = os.path.join(root, link)
            try:
                if os.path.basename(os.path.realpath(path)) != name:
                    continue
            except OSError:
                continue
            if not link.startswith("wwn-") or not best:
                best = path
            if not link.startswith("wwn-"):
                break
    except OSError:
        pass
    return best or f"/dev/{name}"


def pools_now():
    """[{name, size_mb, alloc_mb, free_mb, health, mount, vdevs: [{type, disks}],
    scrub, errors}] from zpool list and zpool status; [] without zpool."""
    zpool = shutil.which("zpool")
    if not zpool:
        return []
    out = []
    for line in _out([zpool, "list", "-Hp", "-o", "name,size,allocated,free,health,altroot"]).splitlines():
        f = line.split("\t")
        if len(f) < 5 or not POOL_RE.fullmatch(f[0]):
            continue
        row = {"name": f[0], "size_mb": int(f[1]) // 1048576 if f[1].isdigit() else 0,
               "alloc_mb": int(f[2]) // 1048576 if f[2].isdigit() else 0, "free_mb": int(f[3]) // 1048576 if f[3].isdigit() else 0,
               "health": f[4][:16].lower(), "mount": "", "vdevs": [], "scrub": "", "errors": "", "encrypted": False, "locked": False}
        props = _out([shutil.which("zfs") or "zfs", "get", "-H", "-o", "value", "mountpoint,encryption,keystatus", f[0]]).split("\n")
        mp = (props[0] if props else "").strip()
        row["mount"] = mp[:120] if mp.startswith("/") else ""
        # Native encryption (R162 step 3): whether the root dataset is
        # encrypted, and whether its key is loaded; locked means nothing
        # under it is mounted until a key comes.
        row["encrypted"] = len(props) > 1 and props[1].strip() not in ("", "off", "-")
        row["locked"] = row["encrypted"] and len(props) > 2 and props[2].strip() == "unavailable"
        st = _out([zpool, "status", f[0]])
        m = re.search(r"^\s*scan:\s*(.+)$", st, re.M)
        if m:
            row["scrub"] = m.group(1).strip()[:160]
        m = re.search(r"^errors:\s*(.+)$", st, re.M)
        if m:
            row["errors"] = m.group(1).strip()[:120]
        # The config block: the pool's line, then each vdev (mirror-0,
        # raidz2-0) with its disks under it, or disks straight under the pool.
        cfg = st.split("config:", 1)[1] if "config:" in st else ""
        cfg = cfg.split("\nerrors:", 1)[0]
        cur = None
        for ln in cfg.splitlines():
            tok = ln.split()
            if len(tok) < 2 or tok[0] in ("NAME", f[0]) or tok[0].lower() in ("spares", "logs", "cache", "special"):
                continue
            indent = len(ln) - len(ln.lstrip())
            if re.fullmatch(r"(mirror|raidz[123]?|draid[123]?)-\d+", tok[0]):
                cur = {"type": tok[0].split("-")[0], "disks": [], "state": tok[1].lower()[:12]}
                row["vdevs"].append(cur)
            elif indent >= 4 and cur is not None and indent > 4:
                cur["disks"].append({"id": tok[0][:120], "state": tok[1].lower()[:12]})
            else:
                cur = None
                row["vdevs"].append({"type": "single", "disks": [{"id": tok[0][:120], "state": tok[1].lower()[:12]}], "state": tok[1].lower()[:12]})
        out.append(row)
        if len(out) >= 32:
            break
    return out


def _snapshots():
    """[(dataset, name, kind, at, used_bytes)] for every bb- snapshot zfs
    lists, oldest first; [] without zfs."""
    zfs = shutil.which("zfs")
    if not zfs:
        return []
    out = []
    for line in _out([zfs, "list", "-H", "-p", "-t", "snapshot", "-o", "name,creation,used", "-s", "creation"]).splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or "@" not in parts[0]:
            continue
        dataset, name = parts[0].split("@", 1)
        m = SNAP_RE.fullmatch(name)
        if not m:
            continue
        try:
            out.append((dataset, name, m.group(1), int(parts[1]), int(parts[2])))
        except ValueError:
            continue
    return out


def snapshots_now():
    """{pool: {count, used_mb, kinds: {kind: n}, newest: [{name, at}]}} for
    the census, the pool's datasets folded together (one snapshot name
    counted once across them); {} without zfs."""
    out = {}
    for dataset, name, kind, at, used in _snapshots():
        pool = dataset.split("/", 1)[0]
        v = out.setdefault(pool, {"count": 0, "used_mb": 0, "kinds": {k: 0 for k in SNAP_KINDS}, "_names": {}})
        v["used_mb"] += used // (1024 * 1024)
        if name not in v["_names"]:
            v["count"] += 1
            v["kinds"][kind] += 1
        v["_names"][name] = max(at, v["_names"].get(name, 0))
    for v in out.values():
        names = v.pop("_names")
        v["newest"] = [{"name": n, "at": names[n]} for n in sorted(names, key=lambda n: names[n], reverse=True)[:10]]
    return out


def safe_mode():
    """Safe mode on BuilderBot OS (R161 step 2): bbsafe=1 on the kernel's
    command line; every encrypted pool stays locked in it."""
    try:
        with open(os.environ.get("BB_CMDLINE") or "/proc/cmdline", encoding="utf-8", errors="replace") as f:
            return "bbsafe=1" in f.read().split()
    except OSError:
        return False


class PoolsMixin:
    """Agent's pool jobs: one of the parts class Agent (agent.py) is made of."""
    _pool_keys = ()

    def pool_keys_want(self, rows):
        """The passphrases the hello hands over (R162 step 3): kept in this
        process's memory only (never node.json, never a file), and every
        locked pool among them unlocked and mounted now; nothing in Safe
        mode. A pool made later finds its passphrase here (create)."""
        keys = [{"pool": str(r.get("pool") or ""), "passphrase": str(r.get("passphrase") or "")} for r in rows
                if isinstance(r, dict) and POOL_RE.fullmatch(str(r.get("pool") or "")) and r.get("passphrase")]
        self._pool_keys = keys                              # on the object, never in node.json
        if not keys or os.geteuid() != 0 or safe_mode():
            return
        zfs = shutil.which("zfs")
        if not zfs:
            return
        for p in pools_now():
            if not p.get("locked"):
                continue
            key = next((k["passphrase"] for k in keys if k["pool"] == p["name"]), "")
            if not key:
                continue
            r = subprocess.run([zfs, "load-key", "-L", "prompt", p["name"]], input=key + "\n", capture_output=True, text=True, timeout=60, check=False)
            if r.returncode != 0:
                log(f"pools: {p['name']} did not unlock: {(r.stderr or r.stdout or '').strip()[:160]}")
                continue
            subprocess.run([zfs, "mount", "-a"], capture_output=True, timeout=120, check=False)
            log(f"pools: {p['name']} unlocked")
            self.hello_again(f"the pool {p['name']} unlocked")

    def _apply_storage_snapshot(self, job, cfg):
        say = job.say
        zfs = shutil.which("zfs")
        if not zfs or os.geteuid() != 0:
            say("refused: snapshots are taken by zfs as root, and this agent has no zfs or is not root (the storage feature installs it)\n")
            return "failed", 77
        action = str(cfg.get("snapshot") or "")
        pool = str(cfg.get("pool") or "").strip()
        if action not in ("take", "rollback", "destroy"):
            say(f"refused: {action or 'no action'} is not a snapshot action (take, rollback or destroy)\n")
            return "failed", 64
        if not POOL_RE.fullmatch(pool) or pool not in {p["name"] for p in pools_now()}:
            say(f"refused: {pool or 'nothing'} is not a pool here\n")
            return "failed", 66
        have = _snapshots()
        if action == "take":
            kind = str(cfg.get("kind") or "manual")
            keep = cfg.get("keep") if isinstance(cfg.get("keep"), int) and not isinstance(cfg.get("keep"), bool) else 10
            if kind not in SNAP_KINDS or not 1 <= keep <= 200:
                say(f"refused: a snapshot's kind is one of {', '.join(SNAP_KINDS)} and 1 to 200 are kept\n")
                return "failed", 64
            name = time.strftime(f"bb-{kind}-%Y%m%d-%H%M")
            if any(n == name and d.split("/", 1)[0] == pool for d, n, _k, _a, _u in have):
                say(f"a {kind} snapshot of {pool} was taken this minute already: {name}\n")
                return "succeeded", 0
            say(f"snapshot {pool}@{name}: every dataset of the pool\n")
            rc = self._sh(job, [zfs, "snapshot", "-r", f"{pool}@{name}"], timeout=120)
            if rc == 0:
                # The oldest of this kind past what is kept, on each dataset.
                mine = {}
                for d, n, k, at, _u in have:
                    if k == kind and d.split("/", 1)[0] == pool:
                        mine.setdefault(n, at)
                old = sorted(mine, key=lambda n: mine[n])
                for n in old[:max(0, len(old) + 1 - keep)]:
                    say(f"pruned {pool}@{n}: past the {keep} {kind} kept\n")
                    self._sh(job, [zfs, "destroy", "-r", f"{pool}@{n}"], timeout=120)
        else:
            name = str(cfg.get("name") or "")
            dataset = str(cfg.get("dataset") or pool)
            if not SNAP_RE.fullmatch(name) or not DATASET_RE.fullmatch(dataset) or dataset.split("/", 1)[0] != pool:
                say("refused: a snapshot is named bb-KIND-DATE-TIME on a dataset of the pool\n")
                return "failed", 64
            if not any(d == dataset and n == name for d, n, _k, _a, _u in have):
                say(f"refused: no snapshot {dataset}@{name} here\n")
                return "failed", 66
            if action == "rollback":
                if str(cfg.get("confirm") or "") != name:
                    say("refused: rolling back takes the snapshot's name again as the confirmation\n")
                    return "failed", 64
                say(f"rollback {dataset} to {name}: everything written to it since is gone\n")
                rc = self._sh(job, [zfs, "rollback", "-r", f"{dataset}@{name}"], timeout=600)
            else:
                say(f"destroy {dataset}@{name}\n")
                rc = self._sh(job, [zfs, "destroy", f"{dataset}@{name}"], timeout=120)
        self.hello_again(f"the pool {pool}: snapshot {action}")
        return ("succeeded", 0) if rc == 0 else ("failed", rc)

    def _apply_storage_pool(self, job, cfg):
        say = job.say
        zpool = shutil.which("zpool")
        if not zpool or os.geteuid() != 0:
            say("refused: pools are made by zpool as root, and this agent has no zpool or is not root (the storage feature installs it)\n")
            return "failed", 77
        action = str(cfg.get("pool") or "")
        name = str(cfg.get("name") or "").strip()
        if action not in ACTIONS:
            say(f"refused: {action or 'no action'} is not a pool action (one of {', '.join(ACTIONS)})\n")
            return "failed", 64
        if not POOL_RE.fullmatch(name):
            say(f"refused: {name or 'no name'} is not a pool name (a letter, then letters, digits, hyphens and underscores, 31 at most)\n")
            return "failed", 64
        have = {p["name"]: p for p in pools_now()}
        disks = {d["name"]: d for d in disks_now(smart=False)}
        want = [str(x) for x in (cfg.get("disks") or []) if isinstance(x, str)]
        layout = str(cfg.get("layout") or "single")
        wipe = cfg.get("wipe") is True

        def disk_ok(n, for_what="a pool"):
            d = disks.get(n)
            if not d:
                say(f"refused: {n} is not a disk this machine lists\n")
                return False
            if d.get("system"):
                say(f"refused: {n} is the system disk, which never goes into {for_what}\n")
                return False
            held = [p for p in d.get("parts") or [] if p.get("holds") not in ("nothing", "")] or ([d] if d.get("holds") not in ("nothing", "") else [])
            if held and not wipe:
                say(f"refused: {n} holds {held[0].get('holds')}; the job must say to wipe it\n")
                return False
            return True

        if action in ("create", "add"):
            if layout not in LAYOUTS:
                say(f"refused: {layout} is not a layout (one of {', '.join(LAYOUTS)})\n")
                return "failed", 64
            if len(want) < LAYOUTS[layout] or len(set(want)) != len(want):
                say(f"refused: a {layout} takes {LAYOUTS[layout]} disk(s) at least, each once; {len(want)} named\n")
                return "failed", 64
            if not all(disk_ok(n) for n in want):
                return "failed", 65
            if action == "create" and name in have:
                say(f"refused: a pool called {name} is here already\n")
                return "failed", 66
            if action == "add" and name not in have:
                say(f"refused: no pool called {name} here\n")
                return "failed", 66
            ids = [by_id(n) for n in want]
            vdev = ([] if layout == "single" else [layout]) + ids
            if action == "create":
                argv = [zpool, "create"] + (["-f"] if wipe else []) + ["-o", "ashift=12", "-O", "compression=lz4", "-O", "atime=off",
                                                                      "-O", "xattr=sa", "-O", "acltype=posixacl", "-m", f"{MOUNT_ROOT}/{name}", name] + vdev
            else:
                argv = [zpool, "add"] + (["-f"] if wipe else []) + [name] + vdev
            say(f"pool {action} {name}: {layout} of {', '.join(want)} ({', '.join(ids)})\n")
            if action == "create" and cfg.get("encrypt") is True:
                # Native encryption (R162 step 3): the passphrase never rides
                # the job; it came with the hello (pool_keys_want) and goes to
                # zpool on its stdin, nowhere else.
                key = next((k["passphrase"] for k in getattr(self, "_pool_keys", []) if k.get("pool") == name), "")
                if not key:
                    say("refused: no passphrase for the pool has reached this machine yet; the next hello brings it, press again\n")
                    return "failed", 65
                argv = argv[:2] + ["-O", "encryption=aes-256-gcm", "-O", "keyformat=passphrase", "-O", "keylocation=prompt"] + argv[2:]
                say("$ " + " ".join(argv) + "  (encrypted; the passphrase on stdin)\n")
                p = subprocess.run(argv, input=key + "\n" + key + "\n", capture_output=True, text=True, timeout=600, check=False)
                say((p.stdout or "") + (p.stderr or ""))
                rc = p.returncode
            else:
                rc = self._sh(job, argv, timeout=600)
        elif action == "scrub":
            if name not in have:
                say(f"refused: no pool called {name} here\n")
                return "failed", 66
            say(f"pool scrub {name}\n")
            rc = self._sh(job, [zpool, "scrub", name], timeout=60)
        elif action == "replace":
            old, new = str(cfg.get("old") or ""), str(cfg.get("new") or "")
            members = {d["id"] for p in have.values() if p["name"] == name for v in p["vdevs"] for d in v["disks"]}
            if name not in have or not old or old not in members and os.path.basename(old) not in {os.path.basename(m) for m in members}:
                say(f"refused: {old or 'no member'} is not a member of {name}\n")
                return "failed", 66
            if not disk_ok(new, name):
                return "failed", 65
            say(f"pool replace {name}: {old} with {new} ({by_id(new)})\n")
            rc = self._sh(job, [zpool, "replace"] + (["-f"] if wipe else []) + [name, old, by_id(new)], timeout=600)
        elif action == "export":
            if name not in have:
                say(f"refused: no pool called {name} here\n")
                return "failed", 66
            say(f"pool export {name}: its datasets unmounted, the disks left as they are\n")
            rc = self._sh(job, [zpool, "export", name], timeout=600)
        else:
            if name not in have:
                say(f"refused: no pool called {name} here\n")
                return "failed", 66
            if str(cfg.get("confirm") or "") != name:
                say("refused: destroying a pool takes its name again as the confirmation\n")
                return "failed", 64
            say(f"pool destroy {name}: everything on it is gone\n")
            rc = self._sh(job, [zpool, "destroy", "-f", name], timeout=600)
        self.hello_again(f"the pool {name}: {action}")
        return ("succeeded", 0) if rc == 0 else ("failed", rc)
