"""BuilderBot OS on this machine (R160 step 4): what the image says of
itself for the census, and the update that writes the next image into the
slot not in use. The disk is image/partitions.sh's: two root slots found by
fixed partition UUIDs, each slot's kernel and initrd under /builderbot/SLOT
on the ESP, and GRUB booting the slot its environment names (the slot
tool). An update fetches the release's ISO, checks it against the sha256
the release carries and against its build attestation where gh is here,
takes the slot, its kernel, its initrd and its release stamp out of the
ISO's live/ folder, writes the other slot, puts its kernel beside it, names
it for the next boot, and asks for a restart; nothing running changes until
then, and the slot that runs now is the one to fall back to.
"""
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.request

RELEASE_FILE = "/usr/lib/builderbot-os/release"
SLOT_TOOL = "/usr/lib/builderbot-os/slot"
POOL_TOOL = "/usr/lib/builderbot-os/system-pool"
ESP = "/boot/efi"
# image/partitions.sh's, held to it by test_osimage.py.
SLOT_DEV = {"a": "/dev/disk/by-partuuid/6a5c2f3e-0b7d-4b2a-9c1e-b0b1de5b0e0a",
            "b": "/dev/disk/by-partuuid/6a5c2f3e-0b7d-4b2a-9c1e-b0b1de5b0e0b"}
SLOT_MIB = 4096
RELEASE_URL = "https://github.com/aquilaelabs/builderbot/releases/download"
REPO = "aquilaelabs/builderbot"
# Each piece of a slot, and where image/build.sh puts it on the ISO.
PIECES = {"root.squashfs": "live/filesystem.squashfs", "vmlinuz": "live/vmlinuz",
          "initrd": "live/initrd", "release": "live/release"}
VER_RE = re.compile(r"v?(\d+\.\d+\.\d+)")


def _env(name, default):
    return os.environ.get(name) or default


def os_release():
    """{version, snapshot, built, slot, next} on a BuilderBot OS disk, {}
    anywhere else: the release file the image carries, and the slot tool's
    reading of this boot and the next."""
    path = _env("BB_OS_RELEASE", RELEASE_FILE)
    if not os.path.isfile(path):
        return {}
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k == "BUILDERBOT_OS_VERSION":
                    out["version"] = v[:40]
                elif k == "DEBIAN_SNAPSHOT":
                    out["snapshot"] = v[:20]
                elif k == "BUILT":
                    out["built"] = v[:24]
    except OSError:
        return {}
    tool = _env("BB_OS_SLOT", SLOT_TOOL)
    for key, verb in (("slot", "current"), ("next", "next")):
        try:
            r = subprocess.run(["bash", tool, verb], capture_output=True, text=True, timeout=10, check=False)
            got = r.stdout.strip()
            out[key] = got if got in ("a", "b") else ""
        except (OSError, subprocess.SubprocessError):
            out[key] = ""
    # On trial (R161 step 2): the slot an update wrote, booted and not yet
    # marked good; and a fallback the health check recorded, said until the
    # next update.
    try:
        st = subprocess.run(["bash", tool, "status"], capture_output=True, text=True, timeout=10, check=False).stdout
        out["trial"] = "\ntrial:" in "\n" + st
    except (OSError, subprocess.SubprocessError):
        out["trial"] = False
    fb = os.path.join(_env("BB_OS_WORK", "/var/lib/builderbot-os"), "fell-back")
    try:
        with open(fb, encoding="utf-8", errors="replace") as f:
            out["fell_back"] = f.read().strip()[:200]
    except OSError:
        out["fell_back"] = ""
    return out


def keep_state_before(say, running):
    """The controller's configuration as it is before an update (R160 step
    4, R161 step 2): a copy beside the old slot, so going back to that slot
    boots the configuration it had, and the two newest copies kept."""
    src = _env("BB_OS_STATE", "/var/lib/builderbot-controller/config")
    if not os.path.isdir(src):
        say("no controller configuration here to copy before the update\n")
        return
    keep = os.path.join(_env("BB_OS_WORK", "/var/lib/builderbot-os"), "before")
    os.makedirs(keep, mode=0o700, exist_ok=True)
    dest = os.path.join(keep, f"{running or 'unknown'}.tar.gz")
    r = subprocess.run(["tar", "-czf", dest + ".new", "-C", os.path.dirname(src), "--exclude=logs", "--exclude=jobs",
                        os.path.basename(src)], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        say(f"the configuration's copy before the update did not take: {r.stderr.strip()[-300:]}\n")
        return
    os.replace(dest + ".new", dest)
    say(f"the configuration as it is, kept at {dest}\n")
    olds = sorted((os.path.join(keep, f) for f in os.listdir(keep) if f.endswith(".tar.gz")), key=os.path.getmtime)
    for old in olds[:-2]:
        os.unlink(old)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# What an update holds at once on the data partition, against the ISO's
# size: the ISO, the root taken out of it, its kernel and initrd (R191
# step 4: a fetch that filled /var took the controller's database with it).
ROOM = 2.2


def _room(where, size):
    """Why `size` bytes of ISO do not fit beside the update's working files
    in `where`, or ""."""
    try:
        st = os.statvfs(where)
    except OSError:
        return ""
    free, need = st.f_bavail * st.f_frsize, int(size * ROOM)
    if size and free < need:
        return (f"the data partition has {free >> 20} MB free and the update needs about {need >> 20} MB "
                f"for the image and what it takes out of it: free some, or grow the disk")
    return ""


def _fetch(url, dest, say):
    """One file by URL (https, or file:// for the tests) into dest, by
    chunks, saying each tenth of a large one; refused before a byte is
    written when it would not fit with what the update takes out of it."""
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 (the release's address, or a test's file://)  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        total = int(r.headers.get("Content-Length") or 0)
        if dest.endswith(".iso") and (why := _room(os.path.dirname(dest), total)):
            raise OSError(why)
        with open(dest, "wb") as f:
            _copy_from(r, f, dest, total, say)


def _copy_from(r, f, dest, total, say):
    """r into f by chunks, saying each tenth of a large one."""
    got, said = 0, 0
    while True:
        chunk = r.read(1 << 20)
        if not chunk:
            break
        f.write(chunk)
        got += len(chunk)
        if total > (64 << 20) and got * 10 // total > said:
            said = got * 10 // total
            say(f"{os.path.basename(dest)}: {said * 10}% of {total >> 20} MB\n")


def stick_status():
    """A stick boot's state (R161 step 10, the system-pool tool's status):
    {stick, pool, ready, on_stick, written_kb, boot_written_kb}, or {} where
    the tool is not here (no BuilderBot OS)."""
    tool = _env("BB_OS_POOL", POOL_TOOL)
    if not os.path.isfile(tool):
        return {}
    try:
        r = subprocess.run(["bash", tool, "status"], capture_output=True, text=True, timeout=15, check=False)
        d = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    if not isinstance(d, dict) or not d.get("stick"):
        return {"stick": False}
    return {"stick": True, "pool": str(d.get("pool") or "")[:200], "ready": d.get("ready") is True,
            "on_stick": [str(x)[:20] for x in (d.get("on_stick") or [])][:8],
            "written_kb": d.get("written_kb") if isinstance(d.get("written_kb"), int) else None,
            "boot_written_kb": d.get("boot_written_kb") if isinstance(d.get("boot_written_kb"), int) else None}


class OsImageMixin:
    """Agent's BuilderBot OS update: one of the parts class Agent (agent.py)
    is made of."""

    def _iso_pieces(self, job, iso, work):
        """The slot's pieces copied out of the ISO's live/ folder into
        `work`, the ISO mounted read-only for it: {piece: path}, or {} with
        what went wrong said."""
        mnt = os.path.join(work, "iso")
        os.makedirs(mnt, exist_ok=True)
        if self._sh(job, ["mount", "-o", "loop,ro,nodev,nosuid,noexec", iso, mnt], timeout=60) != 0:
            job.say("the image would not open (mount -o loop): nothing written\n")
            return {}
        files = {}
        try:
            for piece, inside in PIECES.items():
                dest = os.path.join(work, piece)
                at = os.path.join(mnt, inside)
                # A piece is a plain file on the ISO itself, never a link
                # out of it (B470: one to /dev/zero filled the disk).
                if os.path.islink(at) or not os.path.isfile(at):
                    job.say(f"the image has no {inside} as a plain file: nothing written\n")
                    return {}
                try:
                    shutil.copyfile(at, dest, follow_symlinks=False)
                except OSError as e:
                    job.say(f"the image has no {inside}: {e}; nothing written\n")
                    return {}
                files[piece] = dest
        finally:
            if self._sh(job, ["umount", mnt], timeout=60) != 0:
                job.say(f"the image stayed mounted at {mnt}: umount it before the next update\n")
        return files

    def _apply_system_pool(self, job, cfg):
        """A stick's system pool named (R161 step 10): the tool stops docker,
        containerd and libvirt, moves what the stick holds of theirs, of the
        toolchains and of the projects to the pool, keeps the name and binds
        them there at every boot; then a hello says where things are."""
        tool = _env("BB_OS_POOL", POOL_TOOL)
        path = str(cfg.get("path") or "")
        if not os.path.isfile(tool):
            job.say("refused: this machine does not run BuilderBot OS, so it has no stick\n")
            return "failed", 77
        if not path.startswith("/") or ".." in path.split("/"):
            job.say("refused: a pool is named by its mount point\n")
            return "failed", 64
        rc = self._sh(job, ["bash", tool, "set", path], timeout=6 * 3600)
        self.hello_again("the system pool was set")
        return ("succeeded", 0) if rc == 0 else ("failed", rc)

    def _apply_os_update(self, job, cfg):
        """Write the next image into the slot not in use. `cfg` names a
        release by its tag, or a folder on this machine that holds the
        release's files (an offline machine, the files brought on a stick or
        over a share); the sha256 files beside them are read either way.
        What it fetched and took out of the ISO is gone again however it
        ends: a failed update left gigabytes on the data partition (B470)."""
        work = os.path.join(_env("BB_OS_WORK", "/var/lib/builderbot-os"), "update")
        try:
            return self._os_update(job, cfg, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _os_update(self, job, cfg, work):
        say = job.say
        rel = os_release()
        tool = _env("BB_OS_SLOT", SLOT_TOOL)
        if not rel or not os.path.isfile(tool):
            say("refused: this machine does not run BuilderBot OS (no image release here), so there is no slot to write\n")
            return "failed", 77
        cur, other = rel.get("slot") or "", ""
        if cur in ("a", "b"):
            other = "b" if cur == "a" else "a"
        if not other:
            say("refused: this boot named no slot, so the one to write cannot be told from the one running\n")
            return "failed", 78
        # The slot running now on trial is not proven: the other slot is the
        # only good one, and writing it would leave nothing to go back to
        # (B470).
        if rel.get("trial") and rel.get("next") == cur:
            say(f"refused: slot {cur} runs on trial and is not marked good yet, and slot {other} is the one to fall "
                "back to: wait for the health check (a few minutes after the dashboard is up), then update\n")
            return "failed", 79
        tag = str(cfg.get("release") or "").strip()
        src = str(cfg.get("from") or "").strip()
        if not tag and not src:
            say("refused: an update names a release (vX.Y.Z) or a folder with its files\n")
            return "failed", 64
        if tag and not VER_RE.fullmatch(tag):
            say("refused: a release is named by its tag, vX.Y.Z\n")
            return "failed", 64
        if src and not (os.path.isabs(src) and os.path.isdir(src)):
            say(f"refused: {src or 'the folder'} is not a folder on this machine\n")
            return "failed", 64
        ver = VER_RE.fullmatch(tag).group(1) if tag else ""
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work, mode=0o700)
        name = f"builderbot-os-{ver}" if ver else ""
        if src:
            # The folder's ISO names the version.
            found = sorted(f for f in os.listdir(src) if f.startswith("builderbot-os-") and f.endswith(".iso"))
            if len(found) != 1:
                say(f"refused: {src} holds {len(found)} images (builderbot-os-VERSION.iso); one, please\n")
                return "failed", 65
            name = found[0][:-len(".iso")]
            ver = name[len("builderbot-os-"):]
        say(f"os update: {name}, into slot {other} (slot {cur} runs now)\n")
        fn = f"{name}.iso"
        iso = os.path.join(work, fn)
        try:
            if src:
                if why := _room(work, os.path.getsize(os.path.join(src, fn))):
                    raise OSError(why)
                shutil.copyfile(os.path.join(src, fn), iso)
                shutil.copyfile(os.path.join(src, fn + ".sha256"), iso + ".sha256")
            else:
                base = _env("BB_OS_RELEASE_URL", RELEASE_URL)
                job.step(f"fetching {fn}")
                _fetch(f"{base}/{tag if tag.startswith('v') else 'v' + tag}/{fn}", iso, say)
                _fetch(f"{base}/{tag if tag.startswith('v') else 'v' + tag}/{fn}.sha256", iso + ".sha256", say)
        except OSError as e:
            say(f"{fn}: not got: {e}\n")
            return "failed", 66
        with open(iso + ".sha256", encoding="utf-8", errors="replace") as f:
            want = (f.read().split() or [""])[0].lower()
        have = _sha256(iso)
        if not re.fullmatch(r"[0-9a-f]{64}", want) or want != have:
            say(f"{fn}: its sha256 does not match the one the release carries ({have[:12]} against {want[:12] or 'none'}): nothing written\n")
            return "failed", 67
        say(f"{fn} matches its sha256\n")
        # The build attestation (R160 step 4): keyless, from the workflow
        # that built the image, checked where gh is here to ask GitHub.
        # The image carries gh, so one without it is not taken on the
        # sha256 alone, which comes from the same place as the image (B470).
        gh = shutil.which("gh")
        if not src:
            if not gh:
                say("refused: no gh here to verify the image's build attestation with, and a sha256 from the same "
                    "release proves nothing about who built it: nothing written\n")
                return "failed", 68
            rc = self._sh(job, [gh, "attestation", "verify", iso, "--repo", _env("BB_OS_REPO", REPO)], timeout=120)
            if rc != 0:
                say("the image's build attestation did not verify: nothing written\n")
                return "failed", 68
        else:
            say("from a folder: checked against its sha256 alone, so it is only as trustworthy as the folder\n")
        job.step("reading the image")
        files = self._iso_pieces(job, iso, work)
        if not files:
            return "failed", 66
        os.unlink(iso)
        size = os.path.getsize(files["root.squashfs"])
        if size > SLOT_MIB * 1048576:
            say(f"the root image is {size >> 20} MB and a slot holds {SLOT_MIB}: nothing written\n")
            return "failed", 69
        dev = _env(f"BB_OS_DEV_{other.upper()}", SLOT_DEV[other])
        if not os.path.exists(dev):
            say(f"slot {other}'s partition is not here ({dev}): nothing written\n")
            return "failed", 70
        # Every BuilderBot disk shares its partitions' UUIDs, so with a second
        # one in the machine (a stick) the name could be either (B470).
        if not _env(f"BB_OS_DEV_{other.upper()}", ""):
            uuid = os.path.basename(SLOT_DEV[other])
            r = subprocess.run(["blkid", "-t", f"PARTUUID={uuid}", "-o", "device"], capture_output=True, text=True,
                               timeout=30, check=False)
            if len(r.stdout.split()) > 1:
                say(f"refused: {len(r.stdout.split())} disks here carry slot {other} ({', '.join(r.stdout.split())}): "
                    "take out the other BuilderBot disk or stick, then update\n")
                return "failed", 70
        # GRUB pointed back at this slot, trial off, before the other is
        # touched: a slot left half written by a lost power or a failed
        # write is never the next boot (B470).
        if self._sh(job, ["bash", tool, "hold"], timeout=30) != 0:
            say("GRUB's environment could not be set back to this slot: nothing written\n")
            return "failed", 73
        job.step(f"writing slot {other}")
        try:
            with open(files["root.squashfs"], "rb") as f, open(dev, "r+b") as d:
                shutil.copyfileobj(f, d, 1 << 22)
                d.flush()
                os.fsync(d.fileno())
        except OSError as e:
            say(f"slot {other} did not take the image: {e}\n")
            return "failed", 71
        esp = _env("BB_OS_ESP", ESP)
        where = os.path.join(esp, "builderbot", other)
        try:
            os.makedirs(where, exist_ok=True)
            for piece, target in (("vmlinuz", "vmlinuz"), ("initrd", "initrd"), ("release", "release")):
                shutil.copyfile(files[piece], os.path.join(where, target + ".new"))
                # On the ESP before GRUB is told: a kernel still in the
                # page cache when power goes is a slot that will not load.
                with open(os.path.join(where, target + ".new"), "rb+") as f:
                    os.fsync(f.fileno())
                os.replace(os.path.join(where, target + ".new"), os.path.join(where, target))
            os.sync()
        except OSError as e:
            say(f"the ESP did not take slot {other}'s kernel: {e}\n")
            return "failed", 72
        keep_state_before(say, rel.get("version") or "")
        # Named for the next boot and put on trial (R161 step 2) in one
        # write: two boots without the health check's word go back to the
        # slot running now. Not set, it is said, and the next boot stays here
        # (B470: a next without its trial booted the new slot with no way
        # back, and was reported a success).
        if self._sh(job, ["bash", tool, "switch", other, cur, ver], timeout=30) != 0:
            self._sh(job, ["bash", tool, "hold"], timeout=30)
            say(f"GRUB was not told to boot slot {other} on trial: the slot is written and the next boot stays on slot {cur}\n")
            return "failed", 73
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(_env("BB_OS_WORK", "/var/lib/builderbot-os"), "fell-back"))
        say(f"slot {other} holds BuilderBot OS {ver}, and the next boot starts it: restart this machine to finish (Reboot under This machine's Advanced). "
            f"Slot {cur} keeps {rel.get('version') or 'the image running now'} to fall back to.\n")
        self.hello_again(f"BuilderBot OS {ver} written to slot {other}")
        return "succeeded", 0
