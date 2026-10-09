"""The census and the sample: what the node says about itself on every hello."""
import errno
import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from .base import (
    BREW_BIN,
    CLAUDE_DIR,
    OS_RELEASE,
    SANDBOX_BIN,
    SESSION,
    SHARE,
    TAILSCALE_BIN,
    _mem,
    _probe,
    _probe_died,
    _run,
)
from .stores import _stores, store_dirs
from .backends import _have, net_backend, pkg_backend
from .toolchains import _toolchains, sdk_images, sdk_versions, sysdeps_now
from .gpu import (
    _gpu_card,
    _gpu_container,
    _gpu_display,
    _gpu_driver,
    _gpu_mem_kinds,
    _gpu_name,
    _gpu_procs,
    _gpu_sample,
    _proc_kinds,
)
from .sessnet import SESSNET_STATUS, isolation_now
from .runners import _runner_state, runner_dirs


def _sshd_listening():
    # Port 22 in LISTEN (state 0A) in either table: cheaper and truer than
    # asking systemd, which does not know about a dropbear.
    for tab in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(tab) as f:
                for line in f.readlines()[1:]:
                    cols = line.split()
                    if cols[1].endswith(":0016") and cols[3] == "0A":
                        return True
        except OSError:
            continue
    return False


ASOUND_CARDS = "/proc/asound/cards"
# ALSA's own stand-ins: a card that plays to nothing (snd-dummy) or back to
# itself (snd-aloop) is a virtual device, not a sound card in the machine.
_VIRTUAL_CARDS = ("Dummy", "Loopback")


def _sound():
    """What sound this machine has (R107): the cards ALSA lists, real and
    virtual apart, and which sound server is installed, which is what an
    emulator's audio and a virtual sink would go through. No /proc/asound at
    all is a kernel with no sound loaded, which is a VM's usual state."""
    cards, virtual = [], []
    try:
        with open(ASOUND_CARDS, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"\s*\d+\s+\[(\S+)\s*\]:\s*(.*)", line)
                if not m:
                    continue
                kind = m.group(2).split(" - ")[0].strip()
                name = (m.group(2).split(" - ", 1)[-1].strip() or m.group(1))[:80]
                (virtual if kind in _VIRTUAL_CARDS or m.group(1) in _VIRTUAL_CARDS else cards).append(name)
    except OSError:
        pass
    server = next((s for s in ("pipewire", "pulseaudio") if shutil.which(s)), "")
    return {"cards": cards[:8], "virtual": virtual[:8], "server": server}


def census(state):
    """What this machine is. Asked at hello, every ten minutes, so the
    slow questions (docker, java) are allowed here and not in the sample."""
    tot, _ = _mem()
    tc = _toolchains(state)
    gpu = _gpu_name()
    return {
        "cpu": os.cpu_count() or 0, "mem_mb": tot,
        "os": f"{platform.system().lower()} {platform.machine()} "
              f"{_os_release()}".strip(),
        # The two the placement selector matches on, as fields of their own:
        # a selector should not have to parse the display string above.
        "system": platform.system().lower(), "arch": platform.machine(),
        "hostname": socket.gethostname(),
        "docker": _run(["docker", "version", "--format", "{{.Server.Version}}"])
        if shutil.which("docker") else "",
        # git's, because nothing keeps it in step and nothing should: it is
        # installed once at enrollment from whatever the distribution
        # packages, and on a GUEST node the machine is its owner's, so the
        # controller upgrading it is the one thing R23 says it must not do.
        # What is owed instead is being able to SEE it, and to be told when a
        # node is below the floor the Git view needs (bb doctor names it).
        "git": _run(["git", "--version"]) if shutil.which("git") else "",
        # The daemon's OWN id, which is how the controller tells two VMs that
        # have worn one address apart: a rebuilt sandbox, or a second
        # machine given the old one's IP. It used to read it over ssh with `docker
        # info`, and that reader went when the Docker tab stopped judging an
        # agent node by the controller's ssh (B111); reported here, the same
        # value arrives by the route the work already takes.
        "docker_id": _run(["docker", "info", "--format", "{{.ID}}"], timeout=15)
        if shutil.which("docker") else "",
        "gpu": gpu.splitlines()[0][:80] if gpu else "",
        "gpu_card": _gpu_card(),
        "gpu_driver": _gpu_driver(),
        "gpu_container": _gpu_container(),
        "gpu_display": _gpu_display(),
        "sound": _sound(),
        "sshd": _sshd_listening(),
        "stores": _stores(state.get("stores"), used=True),
        "toolchains": tc,
        "store_dirs": store_dirs(state),
        # Which held recipes need system packages this machine lacks
        # (roadmap R51): read here, so the Tools tab and the row can say so
        # before a build fails on a missing library.
        "sysdeps": sysdeps_now(state),
        # The android system images the store holds, and the AVDs built on
        # them (roadmap #20). Not part of store_dirs: it reaches three levels
        # down and reads the data store's AVD configs as well.
        "images": sdk_images(state),
        # The configuration plane's reported half (docs/nodes.md §12): what
        # is mounted and from where, and the address this machine is on.
        # The row draws the operator's desired config against these.
        "sandbox": os.access(SANDBOX_BIN, os.X_OK),
        # ...and whether this agent may install the machine's own packages
        # here: the stamp AND root, which is what administers() asks. The
        # stamp alone said yes for an agent that could not, and the
        # controller queued system packages it was bound to refuse.
        "administers": os.geteuid() == 0 and os.access(SANDBOX_BIN, os.X_OK),
        # Whether a session here sees only its own project (R35).
        "isolation": isolation_now(),
        # ...and reaches only its own project's containers (R79), as the
        # thread that keeps it last found it; absent before it has looked.
        "session_net": dict(SESSNET_STATUS),
        "mounts": mounts_now(),
        "network": network_now(),
        # Which of the machine's own tools a system job would go through.
        "distro": distro_now(),
        # The same report the controller makes for itself, so one store is
        # not described two ways (roadmap #19).
        "toolchain_versions": sdk_versions(state),
        "services": services_now(),
        # The session half (roadmap #24), as this process is holding it.
        "session": session_now(state),
    }


def session_now(state):
    """Whether this node runs sessions, and what a proxy needs to reach
    them: the ports, the account, whether the projects share is mounted at
    /workspace (a session without it has nothing to work on), and which
    Claude the session account has. Empty until the agent has tried once,
    so an old census never claims a node it has not measured."""
    if not SESSION:
        return {}
    out = dict(SESSION)
    out["workspace"] = os.path.ismount(SHARE)
    # ...and writable: a projects share mounted read-only was the right
    # arrangement for a Docker-only sandbox (nothing there wrote source), and
    # is the wrong one for a machine that runs sessions: Claude could not
    # save a file, and the home's transcripts link cannot be made on it.
    # The kernel answers EROFS for root too, so this is an honest probe.
    out["writable"] = out["workspace"] and os.access(SHARE, os.W_OK)
    home = out.pop("home", "")
    out.pop("bind", None)
    # Claude Code as the session account has it: its own ~/.local/bin (the
    # native installer's home) or ~/.npm-global/bin first, the system after.
    # The pinned copy first (claude_update): it is what a session runs.
    dirs = [CLAUDE_DIR] + ([os.path.join(home, ".local", "bin"), os.path.join(home, ".npm-global", "bin")] if home else [])
    claude = ""
    for d in dirs + ["/usr/local/bin", "/usr/bin"]:
        exe = os.path.join(d, "claude")
        if os.access(exe, os.X_OK):
            # Through the probe, for the same reason the toolchains go through
            # it: a binary that is there and cannot START used to hand its own
            # crash text back as the version, forty characters of it, on the
            # doctor card. A claude that cannot run is a node that cannot hold
            # a session, so it reports as none and says why in the log.
            out_, dead = _probe([exe, "--version"], timeout=15)
            if dead:
                _probe_died("claude", exe, out_, dead)
            else:
                claude = out_.split("\n")[0][:40] or "installed"
            break
    out["claude"] = claude
    # This machine's boot, in the form bb-tty's boot_id() computes: a
    # terminal's URL carries the boot it was opened in, and bb-tty refuses
    # to START a session from a tab older than the machine's current run.
    # On a node that has to be the node's boot, not the controller's. The
    # controller stamps this into a node-bound terminal's URL for the page.
    out["boot"] = boot_id()
    # ...and how long ago that boot was. A network mount lands a moment
    # after the agent starts, so a census taken in that moment says the
    # share is missing; with the uptime beside it the controller can say
    # "just came up, not mounted yet" rather than "add the mount".
    out["up_s"] = uptime_s()
    return out


def uptime_s():
    """Seconds since this machine booted, or -1 when it cannot be read."""
    try:
        if platform.system() == "Darwin":
            m = re.search(r"sec\s*=\s*(\d+)", _run(["sysctl", "-n", "kern.boottime"]))
            return int(time.time() - int(m.group(1))) if m else -1
        with open("/proc/uptime") as f:
            return int(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return -1


def boot_id():
    """PID 1's start time paired with the host's boot time: the same pair,
    in the same shape, as the controller's server.boot_id and bb-tty's."""
    try:
        with open("/proc/1/stat") as f:
            start = f.read().rsplit(")", 1)[1].split()[19]
        with open("/proc/stat") as f:
            btime = next(l for l in f if l.startswith("btime ")).split()[1]
        return f"{btime}.{start}"
    except (OSError, IndexError, StopIteration):
        return ""


def services_now():
    """The managed services on this node and their state. Today that is the
    Actions runner: registered as what, with which labels, and whether its
    listener is up. Read from the runner's own files, so a runner installed
    by hand reports the same way one installed from the tab does."""
    out = {}
    # Every runner on this node, one per git host.
    out["runners"] = [_runner_state(d, rec) for d, rec in runner_dirs()]
    # Tailscale: whether it is here, this node's MagicDNS name (the funnel
    # URL is https://<that>), and which https ports are funnelled to which
    # local ports, read from tailscale's own status, so a funnel set by
    # hand reports the same as one set from the tab.
    ts = {"installed": bool(shutil.which(TAILSCALE_BIN) or os.access(TAILSCALE_BIN, os.X_OK)),
          "dns": "", "funnel": {}}
    if ts["installed"]:
        try:
            st = json.loads(_run([TAILSCALE_BIN, "status", "--json"], timeout=15) or "{}")
            ts["dns"] = str((st.get("Self") or {}).get("DNSName") or "").rstrip(".")
            sv = json.loads(_run([TAILSCALE_BIN, "serve", "status", "--json"], timeout=15) or "{}")
            allow = sv.get("AllowFunnel") or {}
            for hostport, web in (sv.get("Web") or {}).items():
                if not allow.get(hostport):
                    continue
                https = hostport.rsplit(":", 1)[-1]
                for h in (web.get("Handlers") or {}).values():
                    m = re.search(r":(\d+)/?$", str(h.get("Proxy") or ""))
                    if m:
                        ts["funnel"][https] = int(m.group(1))
        except (ValueError, AttributeError):
            pass
    out["tailscale"] = ts
    return out


def mounts_now():
    """Every mount bb-sandbox manages, as it reads them: fstab's line and
    whether it is really mounted. Empty on a node with no bb-sandbox."""
    if not os.access(SANDBOX_BIN, os.X_OK):
        return []
    out = _run([SANDBOX_BIN, "list", "--json"])
    try:
        got = json.loads(out)
    except ValueError:
        return []
    got = [m for m in got if isinstance(m, dict)] if isinstance(got, list) else []
    # A mount fstab has and the kernel does not is tried once, here, and
    # the server's sentence kept beside it: "not mounted" on the row said
    # nothing about WHY, and the why was the whole story when the sandbox
    # moved to an address the host's export did not name: the mount was
    # refused with "access denied by server", nofail let the boot go on,
    # and nothing anywhere repeated the refusal. Root only: mount is.
    if os.geteuid() == 0:
        for m in got:
            if m.get("mounted") or not str(m.get("path") or "").startswith("/"):
                continue
            err = mount_try(m["path"])
            if err:
                m["error"] = err
            else:
                m["mounted"] = True
                m["real"] = m.get("source") or ""
    # A mount that is there and answers Stale file handle is worse than one
    # that is missing: every list of mounts calls it fine and every read
    # fails (roadmap R41; builderbot-dev's up failed on exactly this, 15
    # Sep). Remounting on this side does not help when the export was
    # re-created under it on the host, so the fix is named as the host's.
    for m in got:
        if m.get("mounted") and str(m.get("path") or "").startswith("/"):
            try:
                os.statvfs(m["path"])
            except OSError as e:
                if e.errno == errno.ESTALE:
                    m["stale"] = True
                    m["error"] = ("mounted, but the handle is stale: the export was re-created "
                                  "under it on the host; re-export it there (Unraid: the share's "
                                  "NFS setting off and on, or a pool the mover leaves alone), "
                                  "then Apply storage here")
    return got


def mount_try(path):
    """`mount PATH` from fstab, and what it said when it failed: the last
    line, which for NFS is the server's own reason. "" on success. Half a
    minute at most: an NFS server that is down keeps mount retrying in the
    foreground for two, and a census must not wait that out."""
    try:
        p = subprocess.run(["mount", path], capture_output=True, text=True, timeout=30, check=False)
    except subprocess.TimeoutExpired:
        return "mount gave no answer in 30s; the server is not reachable"
    except OSError as e:
        return str(e)[:200]
    if p.returncode == 0:
        return ""
    lines = [ln.strip() for ln in (p.stderr or p.stdout).splitlines() if ln.strip()]
    return (lines[-1] if lines else f"mount exited {p.returncode}")[:200]


def _client_allows(client, addr):
    """Whether one client entry of an NFS export ('*', a CIDR, an address,
    a hostname) admits addr. A name it cannot resolve is not a refusal."""
    c = client.strip()
    if not c or c.startswith("*") or c == "(everyone)":
        return True
    try:
        ip = ipaddress.ip_address(addr.split("/")[0])
        if "/" in c:
            return ip in ipaddress.ip_network(c, strict=False)
        return ipaddress.ip_address(c) == ip
    except ValueError:
        return True


def export_gaps(addr):
    """The NFS mounts in fstab whose server exports them to named clients
    that do not include addr, the address this node is about to move to.
    From `showmount -e` on each server; a server that does not answer, or
    a machine without showmount, contributes nothing rather than a refusal.
    The Unraid rule the docs prescribe names exactly one address, so a
    node that moves without the rule moving loses every share at once."""
    if not addr or not _have("showmount"):
        return []
    gaps, seen = [], {}
    for m in mounts_now():
        if not str(m.get("type") or "").startswith("nfs"):
            continue
        host, _, exp = str(m.get("source") or "").partition(":")
        if not host or not exp.startswith("/"):
            continue
        if host not in seen:
            seen[host] = _run(["showmount", "-e", "--no-headers", host], timeout=15)
        for line in seen[host].splitlines():
            parts = line.split()
            if len(parts) < 2 or parts[0].startswith("Export list"):
                continue
            path, clients = parts[0], " ".join(parts[1:])
            if exp != path and not exp.startswith(path.rstrip("/") + "/"):
                continue
            if not any(_client_allows(c, addr) for c in clients.split(",")):
                gaps.append(f"{host} exports {path} to {clients}, not to {addr.split('/')[0]}")
    return gaps


def network_now():
    """The address the machine is on, as facts rather than as intent: the
    interface the default route leaves by, its addresses, the gateway, and
    the resolvers. From `ip -j`, which every distro this can run on has."""
    net = {"interface": "", "addresses": [], "gateway": "", "dns": [], "routes": []}
    try:
        # ...and the static routes beside the default one: what goes where
        # through which router, which the row compares with what is saved.
        for r in json.loads(_run(["ip", "-j", "route", "show"]) or "[]"):
            if isinstance(r, dict) and r.get("dst") not in (None, "default") and r.get("gateway"):
                net["routes"].append({"to": str(r["dst"])[:64], "via": str(r["gateway"])[:64]})
        net["routes"] = net["routes"][:32]
    except (ValueError, OSError):
        pass
    try:
        routes = json.loads(_run(["ip", "-j", "route", "show", "default"]) or "[]")
        for r in routes:
            if isinstance(r, dict) and r.get("dev"):
                net["interface"] = str(r["dev"])[:32]
                net["gateway"] = str(r.get("gateway") or "")[:64]
                break
        if net["interface"]:
            addrs = json.loads(_run(["ip", "-j", "addr", "show", "dev", net["interface"]]) or "[]")
            for a in addrs:
                for i in (a.get("addr_info") or []) if isinstance(a, dict) else []:
                    if i.get("family") == "inet" and i.get("local"):
                        net["addresses"].append(f"{i['local']}/{i.get('prefixlen', 32)}")
    except (ValueError, OSError):
        pass
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"):
                    net["dns"].append(line.split()[1][:64])
    except (OSError, IndexError):
        pass
    return net


def _os_release():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def controller_ip(url):
    """The address the controller's hostname resolves to now (IPv4 first,
    the way the provisioner chose it), or "" when it does not resolve."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if not host:
        return ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return ""
    for fam, _t, _p, _c, sa in infos:
        if fam == socket.AF_INET:
            return sa[0]
    return infos[0][4][0] if infos else ""


def init_now():
    """Which init runs this machine: what a service of ours is, there."""
    if platform.system() == "Darwin":
        return "launchd"
    if os.path.isdir("/run/systemd/system"):
        return "systemd"
    if _have("rc-service"):
        return "openrc"
    if os.path.isdir("/etc/sv") and _have("sv"):
        return "runit"
    return ""


def distro_now():
    """What this machine is, as the facts the agent picks its commands by:
    the distribution and its family from /etc/os-release, its package
    manager, and its network backend. In the census, so the controller and
    the row can say which tools a change would go through."""
    d = {"id": "", "family": "", "pretty": "", "pkg": "", "network": "", "init": ""}
    like = ""
    if platform.system() == "Darwin":
        # No os-release on a Mac; sw_vers is the same fact. Its own family:
        # brew for packages, no network backend (a Mac's address is its
        # owner's), launchd for a service.
        brew = _have(BREW_BIN) or os.path.exists("/opt/homebrew/bin/brew")
        d.update({"id": "macos", "family": "macos",
                  "pretty": ("macOS " + _run(["sw_vers", "-productVersion"])).strip(),
                  "pkg": "brew" if brew else "", "network": "", "init": "launchd"})
        return d
    try:
        with open(OS_RELEASE, errors="replace") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                v = v.strip().strip('"')
                if k == "ID":
                    d["id"] = v[:32]
                elif k == "ID_LIKE":
                    like = v
                elif k == "PRETTY_NAME":
                    d["pretty"] = v[:80]
    except OSError:
        pass
    # A derivative lands with its parent through ID_LIKE: Mint, Pop!_OS and
    # Kali with Debian; Fedora, CentOS Stream, Rocky and Alma with RHEL;
    # Manjaro, EndeavourOS and CachyOS with Arch; Leap and Tumbleweed with
    # SUSE. The independents are their own family.
    ids = {d["id"], *like.split()}
    for family, members in (("debian", {"debian", "ubuntu", "raspbian"}),
                            ("rhel", {"rhel", "fedora", "centos", "rocky", "almalinux"}),
                            ("arch", {"arch", "archlinux", "manjaro"}),
                            ("suse", {"suse", "opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles"}),
                            ("alpine", {"alpine"}), ("void", {"void"}), ("gentoo", {"gentoo"}),
                            ("nixos", {"nixos"}), ("slackware", {"slackware"})):
        if ids & members:
            d["family"] = family
            break
    else:
        d["family"] = d["id"]
    d["pkg"] = pkg_backend()[0]
    b = net_backend()
    d["network"] = b.name if b else ""
    d["init"] = init_now()
    return d


class Sampler:
    """CPU as a percentage over the interval since the last sample, which
    is the poll interval, so the number on the row is 'the last 25 seconds'
    and not an instant nobody can act on."""

    def __init__(self):
        self.last = self._stat()

    @staticmethod
    def _stat():
        try:
            with open("/proc/stat") as f:
                parts = [int(x) for x in f.readline().split()[1:]]
            return sum(parts), parts[3] + (parts[4] if len(parts) > 4 else 0)
        except (OSError, ValueError, IndexError):
            return 0, 0

    def sample(self, state, running):
        now = self._stat()
        dt, di = now[0] - self.last[0], now[1] - self.last[1]
        self.last = now
        tot, used = _mem()
        try:
            load1 = os.getloadavg()[0]
        except OSError:
            load1 = 0.0
        return {"cpu_pct": round(100.0 * (dt - di) / dt, 1) if dt > 0 else 0.0,
                "load1": round(load1, 2), "mem_mb": tot, "mem_used_mb": used,
                "stores": _stores(state.get("stores")), "running": running,
                "cores": os.cpu_count() or 0, "kinds": _proc_kinds(),
                **_gpu_sample(), **({"gpu_procs": _gpu_procs(), "gpu_mem_kinds": _gpu_mem_kinds()}
                                     if shutil.which("nvidia-smi") else {})}
