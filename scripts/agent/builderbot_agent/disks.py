"""The machine's disks (R162 step 1): each whole disk by name, model, serial,
size, kind (rotational or solid state) and transport, what each of its
partitions holds (a mounted filesystem, a ZFS pool's member, swap, nothing),
and its SMART health, temperature and hours where smartctl is here. Read
off lsblk's JSON and smartctl's, never parsed from the human forms; for
the census, so the Storage page lists the controller's own machine's disks
before anything is written to one.
"""
import json
import os
import re
import shutil
import subprocess

NAME_RE = re.compile(r"[A-Za-z0-9_.:-]{1,32}")


def _json(argv, timeout=20):
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False).stdout
        return json.loads(out) if out.strip().startswith("{") else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def _holds(part):
    """What a partition (or a whole disk with no table) holds, in words."""
    fs = str(part.get("fstype") or "")
    mnt = str(part.get("mountpoint") or "")
    if fs == "zfs_member":
        return f"ZFS pool {part.get('label') or ''}".strip()
    if fs == "swap":
        return "swap"
    if mnt:
        return f"{fs} at {mnt}"
    if fs:
        return f"{fs}, not mounted"
    if part.get("children"):
        kinds = {str(c.get("type") or "") for c in part["children"]}
        if "crypt" in kinds:
            return "encrypted"
        if "lvm" in kinds:
            return "LVM"
        if "raid1" in kinds or any(k.startswith("raid") for k in kinds):
            return "a RAID member"
    return "nothing"


def _smart(name):
    """{health, temp_c, hours} from smartctl -j, or {} without it or where
    the disk does not answer (a virtual one)."""
    tool = shutil.which("smartctl")
    if not tool:
        return {}
    d = _json([tool, "-j", "-H", "-A", "-l", "devstat", f"/dev/{name}"], timeout=30)
    if not d:
        return {}
    out = {}
    st = d.get("smart_status") or {}
    if "passed" in st:
        out["health"] = "ok" if st.get("passed") else "failing"
    t = (d.get("temperature") or {}).get("current")
    if isinstance(t, (int, float)):
        out["temp_c"] = int(t)
    h = (d.get("power_on_time") or {}).get("hours")
    if isinstance(h, (int, float)):
        out["hours"] = int(h)
    return out


def by_id_link(name):
    """The /dev/disk/by-id link's name for a disk (the model-and-serial one
    before the wwn one), "" where the machine has none (a VM's virtio disk);
    what the Storage page names a disk by when it mounts it (R162 step 4)."""
    root = "/dev/disk/by-id"
    best = ""
    try:
        for link in sorted(os.listdir(root)):
            if "-part" in link:
                continue
            try:
                if os.path.basename(os.path.realpath(os.path.join(root, link))) != name:
                    continue
            except OSError:
                continue
            if not link.startswith("wwn-") or not best:
                best = link
    except OSError:
        return ""
    return best


def disks_now(smart=True):
    """Every whole disk of this machine, loop and RAM devices left out, with
    its partitions' holdings and its SMART facts; at most 32."""
    if not shutil.which("lsblk"):
        return []
    d = _json(["lsblk", "-J", "-b", "-o", "NAME,KNAME,TYPE,SIZE,MODEL,SERIAL,ROTA,TRAN,MOUNTPOINT,FSTYPE,LABEL,PKNAME,RM"])
    out = []
    for dev in d.get("blockdevices") or []:
        name = str(dev.get("kname") or dev.get("name") or "")
        if dev.get("type") != "disk" or not NAME_RE.fullmatch(name) or name.startswith(("loop", "ram", "zram", "sr", "fd")):
            continue
        parts = []
        for p in dev.get("children") or []:
            if p.get("type") not in ("part", "md", "crypt"):
                continue
            parts.append({"name": str(p.get("kname") or p.get("name") or "")[:32], "size_mb": int(p.get("size") or 0) // 1048576,
                          "holds": _holds(p)[:80]})
        row = {"name": name, "model": str(dev.get("model") or "").strip()[:64], "serial": str(dev.get("serial") or "").strip()[:64],
               "size_mb": int(dev.get("size") or 0) // 1048576, "ssd": dev.get("rota") is False,
               "tran": str(dev.get("tran") or "")[:16], "removable": dev.get("rm") is True, "by_id": by_id_link(name)[:120],
               "holds": _holds(dev)[:80] if not parts else "", "parts": parts[:16],
               "system": any(str(p.get("mountpoint") or "") in ("/", "/boot/efi") for p in (dev.get("children") or []))
                         or str(dev.get("mountpoint") or "") == "/"}
        if smart:
            row["smart"] = _smart(name)
        out.append(row)
        if len(out) >= 32:
            break
    return out
