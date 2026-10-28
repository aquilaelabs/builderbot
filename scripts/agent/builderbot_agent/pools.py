"""ZFS pools on the controller's own machine (R162 step 1): each pool as
zpool says it (size, what is used, health, its members by layout, the last
scrub) for the census, and the storage-pool job: a pool made, grown,
scrubbed, a member replaced, the pool exported or destroyed, each argument
held to its shape and each disk to the census's list before zpool runs.
Disks are named to zpool by their /dev/disk/by-id links, so a pool follows
its disks across ports and reboots; a disk that holds anything is refused
unless the job says to wipe it, and nothing is ever made on the system disk.
"""
import os
import re
import shutil
import subprocess

from .disks import disks_now

POOL_RE = re.compile(r"[a-z][a-z0-9_-]{0,30}")
LAYOUTS = {"single": 1, "mirror": 2, "raidz1": 3, "raidz2": 4}
ACTIONS = ("create", "add", "scrub", "replace", "export", "destroy")
MOUNT_ROOT = "/mnt"


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
               "health": f[4][:16].lower(), "mount": "", "vdevs": [], "scrub": "", "errors": ""}
        mp = _out([shutil.which("zfs") or "zfs", "get", "-H", "-o", "value", "mountpoint", f[0]]).strip()
        row["mount"] = mp[:120] if mp.startswith("/") else ""
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


class PoolsMixin:
    """Agent's pool jobs: one of the parts class Agent (agent.py) is made of."""

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
