"""BuilderBot OS on this machine (R160 step 4): what the image says of
itself for the census, and the update that writes the next image into the
slot not in use. The disk is image/partitions.sh's: two root slots found by
fixed partition UUIDs, each slot's kernel and initrd under /builderbot/SLOT
on the ESP, and GRUB booting the slot its environment names (the slot
tool). An update fetches the release's four files, checks each against the
sha256 the release carries and the squashfs against its build attestation
where gh is here, writes the other slot, puts its kernel beside it, names it
for the next boot, and asks for a restart; nothing running changes until
then, and the slot that runs now is the one to fall back to.
"""
import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import urllib.request

RELEASE_FILE = "/usr/lib/builderbot-os/release"
SLOT_TOOL = "/usr/lib/builderbot-os/slot"
ESP = "/boot/efi"
# image/partitions.sh's, held to it by test_osimage.py.
SLOT_DEV = {"a": "/dev/disk/by-partuuid/6a5c2f3e-0b7d-4b2a-9c1e-b0b1de5b0e0a",
            "b": "/dev/disk/by-partuuid/6a5c2f3e-0b7d-4b2a-9c1e-b0b1de5b0e0b"}
SLOT_MIB = 4096
RELEASE_URL = "https://github.com/aquilaelabs/builderbot/releases/download"
REPO = "aquilaelabs/builderbot"
PIECES = ("root.squashfs", "vmlinuz", "initrd", "release")
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


def _fetch(url, dest, say):
    """One file by URL (https, or file:// for the tests) into dest, by
    chunks, saying each tenth of a large one."""
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:  # noqa: S310 (the release's address, or a test's file://)  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        total = int(r.headers.get("Content-Length") or 0)
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


class OsImageMixin:
    """Agent's BuilderBot OS update: one of the parts class Agent (agent.py)
    is made of."""

    def _apply_os_update(self, job, cfg):
        """Write the next image into the slot not in use. `cfg` names a
        release by its tag, or a folder on this machine that holds the
        release's files (an offline machine, the files brought on a stick or
        over a share); the sha256 files beside them are read either way."""
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
        work = os.path.join(_env("BB_OS_WORK", "/var/lib/builderbot-os"), "update")
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work, mode=0o700)
        name = f"builderbot-os-{ver}" if ver else ""
        if src:
            # The folder's files name the version.
            found = sorted(f for f in os.listdir(src) if f.startswith("builderbot-os-") and f.endswith(".release"))
            if len(found) != 1:
                say(f"refused: {src} holds {len(found)} release stamps (builderbot-os-VERSION.release); one, please\n")
                return "failed", 65
            name = found[0][:-len(".release")]
            ver = name[len("builderbot-os-"):]
        say(f"os update: {name}, into slot {other} (slot {cur} runs now)\n")
        files = {}
        for piece in PIECES:
            fn = f"{name}.{piece}"
            dest = os.path.join(work, fn)
            try:
                if src:
                    shutil.copyfile(os.path.join(src, fn), dest)
                    shutil.copyfile(os.path.join(src, fn + ".sha256"), dest + ".sha256")
                else:
                    base = _env("BB_OS_RELEASE_URL", RELEASE_URL)
                    job.step(f"fetching {fn}")
                    _fetch(f"{base}/{tag if tag.startswith('v') else 'v' + tag}/{fn}", dest, say)
                    _fetch(f"{base}/{tag if tag.startswith('v') else 'v' + tag}/{fn}.sha256", dest + ".sha256", say)
            except OSError as e:
                say(f"{fn}: not got: {e}\n")
                return "failed", 66
            with open(dest + ".sha256", encoding="utf-8", errors="replace") as f:
                want = (f.read().split() or [""])[0].lower()
            have = _sha256(dest)
            if not re.fullmatch(r"[0-9a-f]{64}", want) or want != have:
                say(f"{fn}: its sha256 does not match the one the release carries ({have[:12]} against {want[:12] or 'none'}): nothing written\n")
                return "failed", 67
            files[piece] = dest
        say("every file matches its sha256\n")
        # The build attestation (R160 step 4): keyless, from the workflow
        # that built the image, checked where gh is here to ask GitHub.
        gh = shutil.which("gh")
        if gh and not src:
            rc = self._sh(job, [gh, "attestation", "verify", files["root.squashfs"], "--repo", _env("BB_OS_REPO", REPO)], timeout=120)
            if rc != 0:
                say("the slot's build attestation did not verify: nothing written\n")
                return "failed", 68
        elif not src:
            say("no gh here to verify the build attestation with: the sha256 is what was checked\n")
        size = os.path.getsize(files["root.squashfs"])
        if size > SLOT_MIB * 1048576:
            say(f"the root image is {size >> 20} MB and a slot holds {SLOT_MIB}: nothing written\n")
            return "failed", 69
        dev = _env(f"BB_OS_DEV_{other.upper()}", SLOT_DEV[other])
        if not os.path.exists(dev):
            say(f"slot {other}'s partition is not here ({dev}): nothing written\n")
            return "failed", 70
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
                os.replace(os.path.join(where, target + ".new"), os.path.join(where, target))
        except OSError as e:
            say(f"the ESP did not take slot {other}'s kernel: {e}\n")
            return "failed", 72
        keep_state_before(say, rel.get("version") or "")
        rc = self._sh(job, ["bash", tool, "next", other], timeout=30)
        if rc != 0:
            say(f"GRUB was not told to boot slot {other}: the slot is written and the next boot stays on slot {cur}\n")
            return "failed", 73
        # On trial (R161 step 2): two boots without the health check's word
        # go back to the slot running now.
        rc = self._sh(job, ["bash", tool, "trial", cur, ver], timeout=30)
        if rc != 0:
            say(f"the trial was not set in GRUB's environment: slot {other} boots next without a fallback count\n")
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(_env("BB_OS_WORK", "/var/lib/builderbot-os"), "fell-back"))
        shutil.rmtree(work, ignore_errors=True)
        say(f"slot {other} holds BuilderBot OS {ver}, and the next boot starts it: restart this machine to finish (Reboot under This machine's Advanced). "
            f"Slot {cur} keeps {rel.get('version') or 'the image running now'} to fall back to.\n")
        self.hello_again(f"BuilderBot OS {ver} written to slot {other}")
        return "succeeded", 0
