"""The NVIDIA card: its sample, who holds its memory, and the driver and container toolkit."""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from .base import AGENT_IDS, GPU_DISPLAY_STATE, SYS_ROOT, TOOLKIT, _run


def _gpu_card():
    """The NVIDIA card by its PCI id, before any driver is on it: what the
    Nodes page offers Set up GPU display on (R20). A VM's virtual adapter is
    not one, and neither is a card of another make, which the verb would
    refuse."""
    for line in (_run(["lspci", "-nn"], timeout=10) if SYS_ROOT == "/sys" else "").splitlines():
        low = line.lower()
        if "nvidia" in low and ("vga compatible" in low or "3d controller" in low):
            return line.split(": ", 1)[-1].strip()[:120]
    # No pciutils (a minimal Rocky): sysfs says the same without the name,
    # a display-class device (0x03) of NVIDIA's vendor id (0x10de).
    try:
        for dev in sorted(os.listdir(f"{SYS_ROOT}/bus/pci/devices")):
            base = f"{SYS_ROOT}/bus/pci/devices/{dev}"
            with open(f"{base}/vendor") as f, open(f"{base}/class") as g, open(f"{base}/device") as h:
                vendor, cls, did = f.read().strip(), g.read().strip(), h.read().strip()
            if vendor == "0x10de" and cls.startswith("0x03"):
                return f"NVIDIA device [10de:{did[2:]}] at {dev}"
    except OSError:
        pass
    return ""


def _gpu_name():
    """The card's name as its driver gives it, or "". Only an answer that
    exited 0 is a name: nvidia-smi says why it failed on stdout, and with
    the driver installed but not yet loaded (nouveau holding the card until
    a reboot) that sentence was reported as the GPU and drawn on the node's
    row as its name (B391)."""
    if not shutil.which("nvidia-smi"):
        return ""
    try:
        p = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def _gpu_sample():
    """What the card is doing now, for the node's meters: {gpu_pct,
    gpu_mem_used_mb, gpu_mem_mb}, or {} when there is no driver answering.
    Two cards are one gauge: their memory added and their load averaged.
    Read on every heartbeat, so it gives up after a few seconds rather than
    hold the poll on a driver that has stopped answering."""
    if not shutil.which("nvidia-smi"):
        return {}
    try:
        p = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return {}
    if p.returncode != 0:
        return {}
    rows = []
    for line in p.stdout.splitlines():
        try:
            rows.append([float(c) for c in line.split(",")])
        except ValueError:
            continue
    rows = [r for r in rows if len(r) == 3]
    if not rows:
        return {}
    return {"gpu_pct": round(sum(r[0] for r in rows) / len(rows), 1),
            "gpu_mem_used_mb": round(sum(r[1] for r in rows)),
            "gpu_mem_mb": round(sum(r[2] for r in rows))}


# What is running on this machine by KIND, for a session judging whether it
# is too busy to time anything on (R108). A session sees only its own
# processes, so this is the one place the rest is visible; counted, never
# named, so no other project's work is told to a session that is not on it.
def _is_agent(ag, comm, args):
    """Whether a process is coding agent `ag`'s: its name, or the base of its
    command's first word, is the agent's own or one of its helpers'."""
    first = (args.split(" ", 1)[0] if args else "").rsplit("/", 1)[-1]
    return any(n == ag or n.startswith(ag + "-") for n in (comm, first))


PROC_KINDS = (
    ("emulator", lambda c, a: c.startswith("qemu-system")),
    ("gradle", lambda c, a: c == "java" and ("GradleDaemon" in a or "gradle" in a.lower())),
    ("java", lambda c, a: c == "java"),
    ("compile", lambda c, a: c in ("cc1", "cc1plus", "rustc", "clang", "ld", "kotlinc", "javac", "go")),
    ("browser", lambda c, a: c in ("chrome", "chromium", "headless_shell", "firefox")),
    ("media", lambda c, a: c in ("ffmpeg", "ffprobe")),
    ("docker build", lambda c, a: c in ("buildkitd", "buildctl") or (c == "docker" and " build" in a)),
    # Each coding agent by its own command, which the controller leaves out
    # of what a busy machine is running: a session is not load (busy.py).
    # By the name or the command's first word, and a helper of its own
    # (codex-code-mode-host): Copilot's process is named MainThread, and
    # ChatGPT's work runs in its helper, so the name alone counted neither.
    *((ag, lambda c, a, ag=ag: _is_agent(ag, c, a)) for ag in AGENT_IDS),
    ("python", lambda c, a: c.startswith("python")),
    ("display", lambda c, a: c in ("Xorg", "X", "Xvfb", "gnome-shell")),
)


def _proc_kinds(proc_root="/proc"):
    """{kind: count} of what runs here, read from /proc: one pass, the
    command name and the first part of its arguments, the first kind that
    matches. A Gradle daemon is a java process, counted once as gradle."""
    out = {}
    try:
        pids = [p for p in os.listdir(proc_root) if p.isdigit()]
    except OSError:
        return out
    for pid in pids:
        try:
            with open(os.path.join(proc_root, pid, "comm"), encoding="utf-8", errors="replace") as f:
                comm = f.read().strip()
            with open(os.path.join(proc_root, pid, "cmdline"), "rb") as f:
                args = f.read(4096).replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        for kind, test in PROC_KINDS:
            if test(comm, args):
                out[kind] = out.get(kind, 0) + 1
                break
    return out


def _gpu_mem_kinds(proc_root="/proc", smi=None):
    """{kind: MB} of the card's memory in use, by what holds it, read from
    nvidia-smi's process table, which lists a graphics user (an emulator
    drawing on the card) as well as a computing one. By kind, like
    _proc_kinds, never by name or project. An Android 37 phone filled the
    card while it booted and a session could not tell what had (B532)."""
    if smi is None:
        if not shutil.which("nvidia-smi"):
            return {}
        try:
            smi = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=3, check=False).stdout or ""
        except (OSError, subprocess.SubprocessError):
            return {}
    out = {}
    for m in re.finditer(r"\s(\d+)\s+(?:C|G|C\+G)\s+\S.*?\s(\d+)MiB\s*\|", smi):
        pid, mb = m.group(1), int(m.group(2))
        kind = "other"
        try:
            with open(os.path.join(proc_root, pid, "comm"), encoding="utf-8", errors="replace") as f:
                comm = f.read().strip()
            with open(os.path.join(proc_root, pid, "cmdline"), "rb") as f:
                args = f.read(4096).replace(b"\0", b" ").decode("utf-8", "replace")
            kind = next((k for k, test in PROC_KINDS if test(comm, args)), "other")
        except OSError:
            pass
        out[kind] = out.get(kind, 0) + mb
    return out


# The card read on a thread of its own and kept (B841): nvidia-smi takes a
# second or so to start, and the heartbeat asked it three times before every
# work poll, so on a node with the driver installed a job queued after another
# waited three seconds to be handed over, and every Containers read with it.
# Read every GPU_EVERY_S while a card answers; a driver with no card (exit 9,
# a card taken out of a VM) or one not loaded yet is asked again in
# GPU_GONE_S, not every few seconds for good.
GPU_EVERY_S = 10
GPU_GONE_S = 300
_gpu = {"val": {}, "thread": None}
_gpu_lock = threading.Lock()


def gpu_cached():
    """The card's latest reading for the heartbeat ({gpu_pct, gpu_mem_used_mb,
    gpu_mem_mb, gpu_procs, gpu_mem_kinds}), or {}: never waits on nvidia-smi.
    The first call starts the thread that reads it."""
    if not shutil.which("nvidia-smi"):
        return {}
    with _gpu_lock:
        if _gpu["thread"] is None:
            _gpu["thread"] = threading.Thread(target=_gpu_loop, name="gpu-sample", daemon=True)
            _gpu["thread"].start()
        return dict(_gpu["val"])


def gpu_read():
    """One reading: the card's numbers, then its process table once for both
    the count computing on it and its memory by kind. {} when no card answers."""
    s = _gpu_sample()
    if not s:
        return {}
    try:
        smi = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=3, check=False).stdout or ""
    except (OSError, subprocess.SubprocessError):
        smi = ""
    procs = len(re.findall(r"\s\d+\s+(?:C|C\+G)\s+\S.*?\s\d+MiB\s*\|", smi))
    return s | {"gpu_procs": procs, "gpu_mem_kinds": _gpu_mem_kinds(smi=smi)}


def _gpu_loop():
    while True:
        val = gpu_read()
        with _gpu_lock:
            _gpu["val"] = val
        time.sleep(GPU_EVERY_S if val else GPU_GONE_S)


def _kernel_key(name):
    """A kernel directory's name as numbers, for which is newest:
    7.0.0-38-generic after 7.0.0-34-generic, and 6.10 after 6.9."""
    return [int(x) for x in re.findall(r"\d+", name)]


def _gpu_driver(sys_root=None, modinfo=None, modules_root="/lib/modules", running=None):
    """Where the NVIDIA driver stands on this machine, for the Toolchains
    tab's driver row (R102): the version installed for this kernel (the
    module modinfo finds), the version loaded now, and which driver has the
    card. {} with no NVIDIA card, unless the driver is installed for one
    that has gone, which is said (nocard) so it can still be removed (B168).
    Read from the files, never from
    nvidia-smi, which only answers once the driver has the card, and the
    row has to tell "not installed" from "installed, waiting for a reboot"
    and from "removed, still loaded until one"."""
    sys_root = sys_root or SYS_ROOT
    bound = ""
    card = False
    try:
        base = os.path.join(sys_root, "bus", "pci", "devices")
        for dev in sorted(os.listdir(base)):
            d = os.path.join(base, dev)
            try:
                with open(os.path.join(d, "vendor")) as f, open(os.path.join(d, "class")) as g:
                    if f.read().strip() != "0x10de" or not g.read().strip().startswith("0x03"):
                        continue
            except OSError:
                continue
            card = True
            link = os.path.join(d, "driver")
            if os.path.islink(link):
                bound = os.path.basename(os.readlink(link))
            break
    except OSError:
        pass
    loaded = ""
    try:
        with open(os.path.join(sys_root, "module", "nvidia", "version")) as f:
            loaded = f.read().strip()[:40]
    except OSError:
        pass
    installed = ""
    tool = modinfo or next((m for m in ("modinfo", "/sbin/modinfo", "/usr/sbin/modinfo")
                            if shutil.which(m) or os.path.isfile(m)), "")
    if tool:
        try:
            p = subprocess.run([tool, "-F", "version", "nvidia"], capture_output=True,
                               text=True, timeout=10, check=False)
            if p.returncode == 0:
                installed = (p.stdout.strip().splitlines() or [""])[0][:40]
        except (OSError, subprocess.SubprocessError):
            pass
    if tool and not installed:
        # None for the running kernel can be a driver update waiting for the
        # newest one: Ubuntu builds a new driver's module for the newest
        # kernel alone, and apt takes the old version's off the running one,
        # so the row read "removed" and the install failed while 595.99.02
        # sat ready for the restart (bb-sandbox, 8 Oct). The newest kernel
        # is the one a restart boots.
        running = running if running is not None else os.uname().release
        try:
            kernels = sorted((k for k in os.listdir(modules_root)
                              if k != running and _kernel_key(k)), key=_kernel_key)
        except OSError:
            kernels = []
        if kernels and _kernel_key(kernels[-1]) > _kernel_key(running):
            try:
                p = subprocess.run([tool, "-k", kernels[-1], "-F", "version", "nvidia"], capture_output=True,
                                   text=True, timeout=10, check=False)
                if p.returncode == 0:
                    installed = (p.stdout.strip().splitlines() or [""])[0][:40]
            except (OSError, subprocess.SubprocessError):
                pass
    if not card:
        return {"installed": installed, "loaded": "", "bound": "", "nocard": True,
                **_gpu_driver_apt()} if installed else {}
    return {"installed": installed, "loaded": loaded, "bound": bound[:20], **_gpu_driver_apt()}


# A driver package apt may be asked for: the distribution's metapackage, by
# branch, with its open-kernel variant. Nothing else reaches a command line.
DRIVER_PKG = re.compile(r"nvidia-driver(-\d{3})?(-open)?")


def _gpu_driver_apt():
    """What apt says about the driver, for the row's pulldown and its
    update line: the metapackage installed and its version, the version apt
    would move it to, the branches on offer (newest first, transitional
    packages and the server branches left out), and the one the
    distribution recommends for this card. {} where apt is not the
    machine's package manager. Asked of apt's own lists, so as current as
    the last apt-get update, which Check for updates runs."""
    if not shutil.which("apt-cache") or not shutil.which("dpkg-query"):
        return {}

    def out(argv, timeout=20):
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
            return p.stdout if p.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""
    names = []
    for line in out(["apt-cache", "search", "--names-only", "^nvidia-driver(-[0-9]+)?(-open)?$"]).splitlines():
        name, _, about = line.partition(" - ")
        name = name.strip()
        if DRIVER_PKG.fullmatch(name) and "transitional" not in about.lower():
            names.append(name)
    cand, cur = {}, ""
    if names:
        for line in out(["apt-cache", "policy", *names[:40]]).splitlines():
            if line and not line.startswith(" "):
                cur = line.rstrip(":").strip()
            elif "Candidate:" in line and cur:
                v = line.split("Candidate:", 1)[1].strip()
                if v and v != "(none)":
                    cand[cur] = v
    package = pkg_version = ""
    for line in out(["dpkg-query", "-W", "-f", "${Package} ${Version} ${db:Status-Abbrev}\n", "nvidia-driver*"]).splitlines():
        f = line.split()
        if len(f) >= 3 and f[2].startswith("ii") and f[0] in cand and f[0] > package:
            package, pkg_version = f[0], f[1]
    rec = ""
    if shutil.which("ubuntu-drivers"):
        for line in out(["ubuntu-drivers", "devices"], timeout=30).splitlines():
            m = re.search(r"driver\s*:\s*(nvidia-driver\S*)\s.*recommended", line)
            if m and DRIVER_PKG.fullmatch(m.group(1)):
                rec = m.group(1)

    def key(n):
        m = re.search(r"-(\d{3})", n)
        return (-int(m.group(1)) if m else 0, n.endswith("-open"))
    options = [{"pkg": n, "version": cand[n].split("-", 1)[0][:30], "open": n.endswith("-open")}
               for n in sorted(cand, key=key)][:16]
    return {"package": package, "pkg_version": pkg_version[:60],
            "candidate": cand.get(package, "")[:60] if package else "",
            "recommended": rec, "options": options}


def _gpu_container(card=None):
    """Where the NVIDIA container toolkit stands on this machine, for its
    row on the Installed page (R102): the version installed, the version apt
    would move it to (known only while NVIDIA's package source is on the
    machine, which the row's install adds), and whether Docker lists the
    nvidia runtime, which is what a container reserving the card needs. {}
    with no Docker, or with no NVIDIA card and no toolkit: there is nothing
    to hand to a container, and the row is not drawn. A toolkit left for a
    card that has gone is said (nocard), since its refresh unit restarts
    every second without one (B168)."""
    if not shutil.which("docker"):
        return {}
    has_card = bool(card if card is not None else _gpu_card())

    def out(argv, timeout=15):
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
            return p.stdout if p.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""
    installed = candidate = ""
    if shutil.which("dpkg-query"):
        f = out(["dpkg-query", "-W", "-f", "${Version} ${db:Status-Abbrev}\n", TOOLKIT]).split()
        if len(f) >= 2 and f[1].startswith("ii"):
            installed = f[0]
    if not installed and shutil.which("nvidia-ctk"):
        # Installed some other way (a family apt does not manage, or by
        # hand): its own tool says the version.
        m = re.search(r"version\s+(\S+)", out(["nvidia-ctk", "--version"]))
        installed = m.group(1) if m else ""
    if shutil.which("apt-cache"):
        for line in out(["apt-cache", "policy", TOOLKIT]).splitlines():
            if "Candidate:" in line:
                v = line.split("Candidate:", 1)[1].strip()
                candidate = "" if v == "(none)" else v
    # Read as the JSON it is: each runtime's entry carries runc's whole
    # feature list, thousands of characters a word search would be reading.
    try:
        runtimes = json.loads(out(["docker", "info", "--format", "{{json .Runtimes}}"]) or "{}")
    except ValueError:
        runtimes = {}
    if isinstance(runtimes, dict) and isinstance(runtimes.get("Runtimes"), dict):
        runtimes = runtimes["Runtimes"]
    if not has_card and not installed:
        return {}
    return {"installed": installed[:60], "candidate": candidate[:60],
            "runtime": isinstance(runtimes, dict) and "nvidia" in runtimes,
            **({} if has_card else {"nocard": True})}


def _gpu_display():
    try:
        with open(GPU_DISPLAY_STATE, encoding="utf-8", errors="replace") as f:
            return f.readline().strip()[:200]
    except OSError:
        return ""
