#!/usr/bin/env python3
"""The BuilderBot USB stick maker (R161 step 5): one tool for Windows, a Mac
and Linux, nothing but Python's own library, that writes a release's stick
image onto a USB stick and checks it.

    builderbot-stick.py list                      the removable disks here
    builderbot-stick.py write DISK [--image FILE | --release vX.Y.Z | --latest] [--set KEY=VALUE ...] [--config FILE] [--yes]
    builderbot-stick.py verify DISK --image FILE  the stick read back against the image

DISK is /dev/sdX on Linux, /dev/diskN on a Mac, \\\\.\\PhysicalDriveN or its
number on Windows. The image is builderbot-os-VERSION.stick.raw.xz from a
release (its sha256 beside it is fetched and checked), the newest one when
nothing else is named, or a file you have. --set KEY=VALUE, as often as
needed, writes a line into the stick's builderbot.env, which each boot reads:
TZ (the machine's time zone, Europe/Berlin) and BB_RELEASE_LINE (the release
line updates follow, 0.9) are the ones it takes.
Everything on the stick is lost; the tool says so and takes --yes or a typed
yes. It runs as root (sudo) on Linux and a Mac, and as an administrator on
Windows, since a disk is written whole. A stick made this way boots the
appliance with the slot loaded into memory and keeps its configuration on
the stick's data partition; the dashboard's first page then makes the owner
or restores a saved configuration (docs/image.md).
"""
import argparse
import ctypes
import hashlib
import json
import lzma
import os
import platform
import re
import subprocess
import sys
import urllib.request

RELEASES = "https://github.com/aquilaelabs/builderbot/releases"
API = "https://api.github.com/repos/aquilaelabs/builderbot/releases"
CHUNK = 4 << 20
GB = 1e9
# The stick's builderbot.env (image/lay-disk): 4 KiB behind this line.
ENV_MARK = b"# builderbot.env BB-STICK-ENV-1"
ENV_SIZE = 4096
# ...and its builderbot/firstboot.json, a prepared configuration: 64 KiB.
BOOT_MARK = b"BB-FIRSTBOOT-1\n"
BOOT_SIZE = 65536


def say(s):
    print(s, flush=True)


def die(s):
    print(f"builderbot-stick: {s}", file=sys.stderr, flush=True)
    sys.exit(1)


# ---- the disks here --------------------------------------------------------
def disks():
    """[{id, size, model, removable, system}] for this machine."""
    sysname = platform.system()
    if sysname == "Linux":
        out = subprocess.run(["lsblk", "-J", "-b", "-d", "-o", "NAME,SIZE,MODEL,RM,TRAN,TYPE,MOUNTPOINTS"], capture_output=True, text=True, check=False).stdout
        rows = []
        for d in (json.loads(out or "{}").get("blockdevices") or []):
            if d.get("type") != "disk" or str(d.get("name", "")).startswith(("loop", "zram", "ram")):
                continue
            mnts = [m for m in (d.get("mountpoints") or []) if m]
            rows.append({"id": "/dev/" + d["name"], "size": int(d.get("size") or 0), "model": (d.get("model") or "").strip(),
                         "removable": bool(d.get("rm")) or d.get("tran") == "usb", "system": "/" in mnts or "/boot/efi" in mnts})
        return rows
    if sysname == "Darwin":
        out = subprocess.run(["diskutil", "list", "-plist", "external", "physical"], capture_output=True, text=True, check=False).stdout
        import plistlib
        rows = []
        for name in (plistlib.loads(out.encode()).get("WholeDisks") or []) if out else []:
            info = subprocess.run(["diskutil", "info", "-plist", name], capture_output=True, text=True, check=False).stdout
            i = plistlib.loads(info.encode()) if info else {}
            rows.append({"id": "/dev/" + name, "size": int(i.get("TotalSize") or 0), "model": str(i.get("MediaName") or ""),
                         "removable": bool(i.get("RemovableMediaOrExternalDevice", True)), "system": False})
        return rows
    if sysname == "Windows":
        ps = ("Get-Disk | Select-Object Number,Size,FriendlyName,BusType,IsSystem,IsBoot | ConvertTo-Json -Compress")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, check=False).stdout
        data = json.loads(out or "[]")
        rows = []
        for d in (data if isinstance(data, list) else [data]):
            rows.append({"id": f"\\\\.\\PhysicalDrive{d.get('Number')}", "size": int(d.get("Size") or 0), "model": str(d.get("FriendlyName") or ""),
                         "removable": str(d.get("BusType") or "") in ("USB", "SD", "MMC"), "system": bool(d.get("IsSystem") or d.get("IsBoot"))})
        return rows
    die(f"{sysname} is not a system this tool knows (Windows, a Mac, Linux)")


def cmd_list(_):
    rows = disks()
    if not rows:
        say("no disk found")
        return
    for d in rows:
        say(f"{d['id']:<24} {d['size'] / GB:7.1f} GB  {d['model'] or 'unnamed':<30} {'removable' if d['removable'] else 'fixed'}{'  (the system disk: never)' if d['system'] else ''}")


# ---- the image ----------------------------------------------------------------
def fetch(url, dest, say_progress=True):
    req = urllib.request.Request(url, headers={"User-Agent": "builderbot-stick"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:  # noqa: S310 (the release's address)
        total = int(r.headers.get("Content-Length") or 0)
        got, said = 0, -1
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if say_progress and total and got * 20 // total > said:
                said = got * 20 // total
                say(f"  {os.path.basename(dest)}: {said * 5}%")


TAG = r"v\d+\.\d+\.\d+(?:-dev\.\d+)?"


def release_image(tag, channel="normal"):
    """The stick image of a release, fetched beside the tool with its sha256
    checked; the newest release when tag is 'latest', or on the dev channel
    the newest pre-release a dev build's tag made (R179)."""
    if tag == "latest":
        req = urllib.request.Request(API, headers={"Accept": "application/json", "User-Agent": "builderbot-stick"})
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            rows = json.loads(r.read())
        dev = channel == "dev"
        live = [x for x in rows if not x.get("draft") and bool(x.get("prerelease")) == dev
                and re.fullmatch(TAG if dev else r"v\d+\.\d+\.\d+", str(x.get("tag_name") or ""))]
        if not live:
            die("no published release" + (" on that channel" if dev else ""))
        tag = live[0]["tag_name"]
    if not re.fullmatch(TAG, tag):
        die("a release is named by its tag, vX.Y.Z")
    name = f"builderbot-os-{tag[1:]}.stick.raw.xz"
    base = f"{RELEASES}/download/{tag}/{name}"
    say(f"fetching {name} from the {tag} release")
    fetch(base, name)
    fetch(base + ".sha256", name + ".sha256", say_progress=False)
    check_sha(name, name + ".sha256")
    return name


def check_sha(path, sha_file):
    want = (open(sha_file, encoding="utf-8").read().split() or [""])[0].lower()
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    if h.hexdigest() != want:
        die(f"{path} does not match its sha256 ({h.hexdigest()[:12]} against {want[:12] or 'none'}): not written")
    say(f"{os.path.basename(path)}: sha256 matches")


# ---- the stick's builderbot.env --------------------------------------------------
KEY = re.compile(r"[A-Z][A-Z0-9_]{0,40}")
VALUE = re.compile(r"[A-Za-z0-9_./:+-]{0,200}")


def env_block(sets):
    """The 4 KiB the stick's builderbot.env is, with these KEY=VALUE lines:
    the marker line first, so another write finds it again, and blank
    padding, which the boot's reader passes over."""
    lines = []
    for s in sets:
        k, sep, v = s.partition("=")
        if not sep or not KEY.fullmatch(k) or not VALUE.fullmatch(v):
            die(f"--set {s}: a KEY=VALUE, the key in capitals, the value letters, digits and _ . / : + -")
        lines.append(f"{k}={v}")
    body = ENV_MARK + b": KEY=VALUE lines the boot reads (TZ, BB_RELEASE_LINE)\n" + "".join(x + "\n" for x in lines).encode()
    if len(body) > ENV_SIZE - 1:
        die(f"--set: {len(body)} bytes of lines, and builderbot.env holds {ENV_SIZE}")
    return body + b" " * (ENV_SIZE - 1 - len(body)) + b"\n"


def boot_block(path):
    """The 64 KiB firstboot.json is, holding the prepared configuration in
    the JSON file at path (format 1, docs/image.md): the marker line, the
    JSON on one line, blank padding."""
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        die(f"--config {path}: {e}")
    if not isinstance(cfg, dict) or cfg.get("format") != 1:
        die(f"--config {path}: a prepared configuration is a JSON object with \"format\": 1")
    body = BOOT_MARK + json.dumps(cfg, separators=(",", ":")).encode() + b"\n"
    if len(body) > BOOT_SIZE - 1:
        die(f"--config {path}: {len(body)} bytes, and firstboot.json holds {BOOT_SIZE}")
    return body + b" " * (BOOT_SIZE - 1 - len(body)) + b"\n"


def patched(src, block, boot=None):
    """The image's bytes in CHUNKs, builderbot.env's 4 KiB and firstboot.json's
    64 KiB put in place where their markers are. A chunk is held until the
    next is read, so a file across the line between two is found and written
    whole. A block of None passes its file as it is; a block with no marker
    in the image stops the write before the end (an image older than the
    file)."""
    want = [(m, n, b) for m, n, b in ((ENV_MARK, ENV_SIZE, block), (BOOT_MARK, BOOT_SIZE, boot)) if b is not None]
    hold = max((n + len(m) for m, n, _ in want), default=0)
    held = b""
    for chunk in iter(lambda: src.read(CHUNK), b""):
        buf = held + chunk
        for w in list(want):
            mark, size, blk = w
            at = buf.find(mark)
            if at >= 0 and at + size <= len(buf):
                buf = buf[:at] + blk + buf[at + size:]
                want.remove(w)
        keep = min(len(buf), hold) if want else 0
        out, held = (buf[:len(buf) - keep], buf[len(buf) - keep:]) if keep else (buf, b"")
        if out:
            yield out
    if want:
        what = " and ".join("builderbot.env to write --set into" if m == ENV_MARK else "firstboot.json to write --config into" for m, _, _ in want)
        die(f"this image has no {what} (made before 0.9.0): nothing past the start of the stick is right, so write it again without them or with a newer image")
    if held:
        yield held


# ---- the write ----------------------------------------------------------------
def open_disk(dev):
    """The disk opened for writing whole: on Windows every volume on it is
    locked and dismounted first, so the write is not undone by the system
    behind it."""
    if platform.system() == "Windows":
        m = re.search(r"(\d+)$", dev)
        if not m:
            die(f"{dev} is not a disk (\\\\.\\PhysicalDriveN, or N)")
        n = int(m.group(1))
        ps = f"Get-Partition -DiskNumber {n} -ErrorAction SilentlyContinue | Where-Object DriveLetter | Select-Object -ExpandProperty DriveLetter"
        letters = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, check=False).stdout.split()
        k32 = ctypes.windll.kernel32
        GENERIC_RW, SHARE_RW, OPEN_EXISTING = 0xC0000000, 0x3, 3
        FSCTL_LOCK_VOLUME, FSCTL_DISMOUNT_VOLUME = 0x00090018, 0x00090020
        handles = []
        for letter in letters:
            h = k32.CreateFileW(f"\\\\.\\{letter}:", GENERIC_RW, SHARE_RW, None, OPEN_EXISTING, 0, None)
            if h in (0, -1):
                continue
            out = ctypes.c_ulong(0)
            k32.DeviceIoControl(h, FSCTL_LOCK_VOLUME, None, 0, None, 0, ctypes.byref(out), None)
            k32.DeviceIoControl(h, FSCTL_DISMOUNT_VOLUME, None, 0, None, 0, ctypes.byref(out), None)
            handles.append(h)
        f = open(f"\\\\.\\PhysicalDrive{n}", "r+b", buffering=0)
        f.bb_handles = handles  # kept open until the write ends, so the lock holds
        return f
    if platform.system() == "Darwin":
        subprocess.run(["diskutil", "unmountDisk", dev], capture_output=True, check=False)
        rdev = dev.replace("/dev/disk", "/dev/rdisk")
        return open(rdev, "r+b", buffering=0)
    out = subprocess.run(["lsblk", "-nro", "MOUNTPOINTS", dev], capture_output=True, text=True, check=False).stdout.split()
    for m in out:
        subprocess.run(["umount", m], capture_output=True, check=False)
    return open(dev, "r+b", buffering=0)


def write_image(image, dev, verify_after=True, sets=(), config=None):
    size_xz = os.path.getsize(image)
    say(f"writing {os.path.basename(image)} ({size_xz / GB:.1f} GB compressed) to {dev}")
    block = env_block(sets) if sets else None
    boot = boot_block(config) if config else None
    h = hashlib.sha256()
    written = 0
    with lzma.open(image, "rb") as src, open_disk(dev) as dst:
        for chunk in patched(src, block, boot):
            dst.write(chunk)
            h.update(chunk)
            written += len(chunk)
            if written % (512 << 20) < CHUNK:
                say(f"  {written / GB:.1f} GB written")
        dst.flush()
        try:
            os.fsync(dst.fileno())
        except OSError:
            pass
    say(f"written: {written / GB:.1f} GB")
    if verify_after:
        verify(dev, written, h.hexdigest())


def verify(dev, length, want):
    say("reading the stick back")
    h = hashlib.sha256()
    left = length
    rdev = dev.replace("/dev/disk", "/dev/rdisk") if platform.system() == "Darwin" else dev
    if platform.system() == "Windows" and re.fullmatch(r"\d+", dev):
        rdev = f"\\\\.\\PhysicalDrive{dev}"
    with open(rdev, "rb", buffering=0) as f:
        while left > 0:
            chunk = f.read(min(CHUNK, left))
            if not chunk:
                break
            h.update(chunk)
            left -= len(chunk)
    if h.hexdigest() != want:
        die("the stick does not read back as what was written: try another stick, or another port")
    say("the stick reads back as written")


def pick(dev):
    rows = disks()
    norm = dev if not re.fullmatch(r"\d+", dev) else f"\\\\.\\PhysicalDrive{dev}"
    d = next((r for r in rows if r["id"].lower() == norm.lower()), None)
    if not d:
        die(f"{dev} is not a disk here (list says which are)")
    if d["system"]:
        die(f"{d['id']} is the system disk: never")
    if not d["removable"]:
        die(f"{d['id']} is not a removable disk (a stick, a card): the tool writes only those")
    return d


def cmd_write(a):
    d = pick(a.disk)
    image = a.image
    if not image:
        image = release_image(a.release or "latest", a.channel)
    elif not os.path.isfile(image):
        die(f"no such image: {image}")
    if not image.endswith(".xz"):
        die("the image is the release's builderbot-os-VERSION.stick.raw.xz (or .raw.xz)")
    say(f"{d['id']}: {d['model'] or 'unnamed'}, {d['size'] / GB:.1f} GB. Everything on it is lost.")
    if not a.yes:
        if input("Type yes to write it: ").strip().lower() != "yes":
            die("nothing written")
    write_image(image, d["id"], verify_after=not a.no_verify, sets=a.set or (), config=a.config)
    say("Done. Boot the machine from the stick: it comes up as its own controller, and the dashboard's first page, at http://ITS-ADDRESS:7680 on the LAN, makes the owner or restores a saved configuration.")


def cmd_verify(a):
    d = pick(a.disk)
    h = hashlib.sha256()
    n = 0
    with lzma.open(a.image, "rb") as src:
        for chunk in patched(src, env_block(a.set) if a.set else None, boot_block(a.config) if a.config else None):
            h.update(chunk)
            n += len(chunk)
    verify(d["id"], n, h.hexdigest())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="builderbot-stick", description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="the removable disks here").set_defaults(fn=cmd_list)
    w = sub.add_parser("write", help="write a stick image to a disk")
    w.add_argument("disk")
    w.add_argument("--image", help="builderbot-os-VERSION.stick.raw.xz, a file you have")
    w.add_argument("--release", help="the release's tag to fetch the image from (vX.Y.Z)")
    w.add_argument("--latest", action="store_true", help="fetch the newest release's image (what it does when nothing else is named)")
    w.add_argument("--set", action="append", metavar="KEY=VALUE", help="a line for the stick's builderbot.env: TZ=Region/City, BB_RELEASE_LINE=X.Y")
    w.add_argument("--config", metavar="FILE", help="a prepared configuration (JSON, docs/image.md) the stick's first boot applies, skipping the first-run page where it says so")
    w.add_argument("--channel", choices=["normal", "dev"], default="normal", help=argparse.SUPPRESS)
    w.add_argument("--yes", action="store_true", help="do not ask")
    w.add_argument("--no-verify", action="store_true", help="skip reading the stick back")
    w.set_defaults(fn=cmd_write)
    v = sub.add_parser("verify", help="read a stick back against an image")
    v.add_argument("disk")
    v.add_argument("--image", required=True)
    v.add_argument("--set", action="append", metavar="KEY=VALUE", help="the lines the stick was written with")
    v.add_argument("--config", metavar="FILE", help="the prepared configuration it was written with")
    v.set_defaults(fn=cmd_verify)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
