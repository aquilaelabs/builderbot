"""The VMs a node runs (R91): KVM through libvirt, on a node whose VM host
feature is installed. Every command is built here from a fixed table with
checked arguments, run as the jobs account (in the libvirt group), never by a
session; the controller sends what to make, never a command line."""
import contextlib
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from xml.sax.saxutils import escape, quoteattr

from . import vmhw
from .base import _run

VIRSH = ["virsh", "-c", "qemu:///system"]
# Where the VM host feature keeps the cached cloud images and each VM's disk,
# its cloud-init seed and its XML: the jobs account's, made by the install.
VM_DIR = os.environ.get("BUILDERBOT_VM_DIR", "/var/lib/builderbot/vms")
DOMAIN_RE = re.compile(r"bbvm-[a-z0-9][a-z0-9-]{0,62}")
NETWORK_RE = re.compile(r"bbvm-[a-z0-9][a-z0-9-]{0,14}")
IMAGE_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,40}")
FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,120}")
SNAP_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,40}")
USER_RE = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
KEY_RE = re.compile(r"(ssh-(ed25519|rsa)|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/=]{20,800}( [^\n]{0,100})?")
ACTIONS = ("create", "start", "stop", "restart", "remove", "snapshot", "revert", "snapshot-rm",
           "eject", "disk-grow", "disk-add", "iso-add", "iso-rm", "hardware", "autostart", "vbios")
# An installer ISO a person fetched onto this node (R99), by its own name.
ISO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,100}\.iso")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
MAC_RE = re.compile(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}")
# VNC takes a password of eight characters at most.
VNC_PW_RE = re.compile(r"[A-Za-z0-9._-]{1,8}")
DISK_DEVS = ("vda", "vdb", "vdc", "vdd")
# The marker every domain this agent makes carries, beside its name prefix:
# libvirt's own <metadata>, so a domain somebody else made is never ours.
META_NS = "https://builderbot.dev/vm/1"
# What a VM may be given, whatever is asked: the controller's limits are the
# real ones (R91 step 7); these keep a typo from asking for a terabyte.
MAX_VCPUS, MAX_MEM_MB, MAX_DISK_GB = 64, 262144, 4096


def _state_word(s):
    """virsh's state, in the page's words."""
    s = s.strip().lower()
    return {"running": "running", "shut off": "stopped", "paused": "paused", "in shutdown": "stopping",
            "crashed": "crashed", "pmsuspended": "suspended"}.get(s, s or "unknown")


def vms_now():
    """The VMs this machine runs that BuilderBot made (their name prefix), as
    libvirt says, for the census: name, state, the address its network
    leased it, its vCPUs and memory, and its snapshots. Empty where there is
    no libvirt or it does not answer."""
    if not shutil.which("virsh"):
        return []
    out = []
    names = [n for n in _run(VIRSH + ["list", "--all", "--name"], timeout=15).split() if DOMAIN_RE.fullmatch(n)]
    for name in names[:64]:
        info = {}
        for line in _run(VIRSH + ["dominfo", name], timeout=10).splitlines():
            k, _, v = line.partition(":")
            info[k.strip().lower()] = v.strip()
        ip = ""
        if info.get("state") == "running":
            for line in _run(VIRSH + ["domifaddr", name, "--source", "lease"], timeout=10).splitlines():
                m = re.search(r"ipv4\s+([0-9.]+)/", line)
                if m:
                    ip = m.group(1)
                    break
        snaps = [s for s in _run(VIRSH + ["snapshot-list", name, "--name"], timeout=10).split() if SNAP_RE.fullmatch(s)]
        mem = re.match(r"(\d+)", info.get("max memory", ""))
        # Its screen while it runs (R99), and an installer's ISO still in
        # its drive, which the row offers to eject.
        screen = info.get("state") == "running" and _run(VIRSH + ["domdisplay", name], timeout=10).startswith("vnc://")
        iso = ""
        for line in _run(VIRSH + ["domblklist", name], timeout=10).splitlines():
            p = line.split(None, 1)
            if len(p) == 2 and p[0] == "sda" and p[1].strip().startswith(iso_dir() + "/"):
                iso = os.path.basename(p[1].strip())
        # Its hardware beyond size (R100), read off its own XML, and whether
        # it starts with its host.
        hw = vmhw.read(_run(VIRSH + ["dumpxml", name, "--inactive"], timeout=10))
        out.append({"hw": hw, "autostart": info.get("autostart") == "enable",
                    "screen": bool(screen), "iso": iso if ISO_RE.fullmatch(iso) else "",
                    "name": name, "state": _state_word(info.get("state", "")), "ip": ip,
                    "vcpus": int(info["cpu(s)"]) if info.get("cpu(s)", "").isdigit() else 0,
                    "mem_mb": int(mem.group(1)) // 1024 if mem else 0, "snapshots": snaps[:32]})
    return out


VMNET_TABLE = "builderbot_vmnet"
# What a VM may not reach unless the node's owner lets its VMs onto the LAN:
# every private, shared, link-local and loopback range, the same list the
# sessions are kept from.
VMNET_PRIVATE = ("10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
                 "192.168.0.0/16", "198.18.0.0/15")


def vmnet_table(ctl, lan=False):
    """The VMs' own firewall (R91 step 8), whole: a VM reaches the internet,
    the controller (its address and port) and its own project's network;
    not another project's VMs, not the LAN unless `lan`, and of this node
    only the DHCP and DNS libvirt serves it. Nothing starts a connection
    into a VM but its own project's sessions, which the sessions' table
    lets through by their project (sessnet)."""
    ctl_set = (" elements = { " + ", ".join(f"{a} . {p}" for a, p in ctl) + " };") if ctl else ""
    priv = "" if lan else ("\n\t\tiifname \"bbvm-n*\" ip daddr { " + ", ".join(VMNET_PRIVATE) + " } drop")
    return (f"table inet {VMNET_TABLE} {{\n"
            f"\tset ctl {{ type ipv4_addr . inet_service;{ctl_set} }}\n"
            "\tchain forward {\n"
            "\t\ttype filter hook forward priority -5; policy accept;\n"
            "\t\tiifname \"bbvm-n*\" ct state established,related accept\n"
            "\t\tiifname \"bbvm-n*\" oifname \"bbvm-n*\" drop\n"
            f"\t\tiifname \"bbvm-n*\" ip daddr . tcp dport @ctl accept{priv}\n"
            "\t\tiifname \"bbvm-n*\" meta nfproto ipv6 drop\n"
            "\t}\n"
            "\tchain input {\n"
            "\t\ttype filter hook input priority -5; policy accept;\n"
            "\t\tiifname \"bbvm-n*\" ct state established,related accept\n"
            "\t\tiifname \"bbvm-n*\" udp dport { 53, 67 } accept\n"
            "\t\tiifname \"bbvm-n*\" tcp dport 53 accept\n"
            "\t\tiifname \"bbvm-n*\" ip daddr . tcp dport @ctl accept\n"
            "\t\tiifname \"bbvm-n*\" drop\n"
            "\t}\n"
            "}\n")


_vmnet = {"applied": None, "at": 0.0}


def vmnet_keep(ctl, lan=False, now=0.0, nft="nft"):
    """The VMs' table in place while any project network is here, rewritten
    when what it should hold moves, and put back within half a minute of a
    flush or a reboot. "" or what went wrong."""
    try:
        here = any(n.startswith("bbvm-n") for n in os.listdir("/sys/class/net"))
    except OSError:
        here = False
    if not here:
        return ""
    want = vmnet_table(ctl, lan)
    gone = False
    if now - _vmnet["at"] > 30:
        _vmnet["at"] = now
        gone = subprocess.run([nft, "list", "table", "inet", VMNET_TABLE], capture_output=True,
                              check=False).returncode != 0
    if want == _vmnet["applied"] and not gone:
        return ""
    p = subprocess.run([nft, "-f", "-"], input=f"table inet {VMNET_TABLE}\ndelete table inet {VMNET_TABLE}\n" + want,
                       capture_output=True, text=True, check=False)
    if p.returncode:
        return f"nft refused the VMs' table: {(p.stderr or p.stdout).strip()[:200]}"
    _vmnet["applied"] = want
    return ""


def lan_iface():
    """The interface the host's default route leaves by, "" without one: where
    a VM made a node joins the LAN."""
    try:
        with open("/proc/net/route") as f:
            for line in f.read().splitlines()[1:]:
                p = line.split()
                if len(p) > 3 and p[1] == "00000000" and int(p[3], 16) & 2 and re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", p[0]):
                    return p[0]
    except (OSError, ValueError):
        pass
    return ""


def vm_pool():
    """Room where the VMs' disks go, for the census and the page."""
    try:
        du = shutil.disk_usage(VM_DIR)
    except OSError:
        return {}
    return {"path": VM_DIR, "free_mb": du.free // 2**20, "total_mb": du.total // 2**20}


def sums_lookup(text, filename):
    """The hash a checksum file gives for one file, or "": GNU style (HEX
    *NAME or HEX  NAME), BSD style (SHA256 (NAME) = HEX), or a file that is
    only the hash (Alpine's .sha512)."""
    for line in text.splitlines():
        line = line.strip()
        m = re.fullmatch(r"([0-9a-fA-F]{64}|[0-9a-fA-F]{128})\s+\*?(\S+)", line)
        if m and m.group(2) == filename:
            return m.group(1).lower()
        m = re.fullmatch(r"SHA(256|512) \((\S+)\) = ([0-9a-fA-F]+)", line)
        if m and m.group(2) == filename:
            return m.group(3).lower()
    only = text.strip()
    return only.lower() if re.fullmatch(r"[0-9a-fA-F]{64}|[0-9a-fA-F]{128}", only) else ""


ENROLL_HEAD = "#!/usr/bin/env bash\n# BuilderBot: enroll "


def user_data(hostname, user, keys, enroll=""):
    """cloud-init's user-data: one account, sudo without a password, the
    keys given and no password login; and, for a VM made a node (step 14),
    the controller's enroll script written as root's and run once at first
    boot, then removed, since the token in it is spent."""
    lines = ["#cloud-config", f"hostname: {hostname}", "ssh_pwauth: false", "users:",
             f"  - name: {user}", "    sudo: ALL=(ALL) NOPASSWD:ALL", "    shell: /bin/bash",
             "    ssh_authorized_keys:"]
    lines += [f"      - {json.dumps(k)}" for k in keys]
    # bash where the image has none (Alpine's): the account's shell, and
    # what the enroll script runs in, which never started there (R97's walk).
    # ...and sudo, which the account is given and Alpine does not carry.
    bash = "command -v bash >/dev/null && command -v sudo >/dev/null || apk add --no-cache bash sudo >/dev/null 2>&1 || true"
    # ...and Alpine's sshd turns a key away for an account whose password is
    # locked (!), which cloud-init leaves; no password (*) lets the key in.
    bash += f'; if command -v apk >/dev/null; then sed -i "s/^{user}:!/{user}:*/" /etc/shadow; fi'
    if enroll:
        import base64
        lines += ["write_files:", "  - path: /root/bb-enroll.sh", "    permissions: '0700'", "    encoding: b64",
                  f"    content: {base64.b64encode(enroll.encode()).decode()}",
                  "runcmd:", f"  - [sh, -c, '{bash}; bash /root/bb-enroll.sh > /root/bb-enroll.log 2>&1; rm -f /root/bb-enroll.sh']"]
    else:
        lines += ["runcmd:", f"  - [sh, -c, '{bash}']"]
    return "\n".join(lines) + "\n"


# The UEFI firmware VM host installs, named rather than left to libvirt's
# pick, which chose the AMD SEV build on the dev node (21 Oct): its code, and
# the template its variables file is copied from, by family.
OVMF_PAIRS = (("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd"),
              ("/usr/share/edk2/ovmf/OVMF_CODE.fd", "/usr/share/edk2/ovmf/OVMF_VARS.fd"),
              ("/usr/share/AAVMF/AAVMF_CODE.fd", "/usr/share/AAVMF/AAVMF_VARS.fd"),
              # Arch's edk2-ovmf, openSUSE's qemu-ovmf-x86_64, Alpine's ovmf.
              ("/usr/share/edk2/x64/OVMF_CODE.4m.fd", "/usr/share/edk2/x64/OVMF_VARS.4m.fd"),
              ("/usr/share/qemu/ovmf-x86_64-code.bin", "/usr/share/qemu/ovmf-x86_64-vars.bin"),
              ("/usr/share/OVMF/OVMF_CODE.fd", "/usr/share/OVMF/OVMF_VARS.fd"))


def ovmf():
    """(code, vars template) of the UEFI firmware here, or None."""
    return next((p for p in OVMF_PAIRS if os.path.isfile(p[0]) and os.path.isfile(p[1])), None)


def iso_dir():
    return os.path.join(VM_DIR, "iso")


def isos_now():
    """The installer ISOs fetched onto this node, for the census."""
    try:
        names = sorted(n for n in os.listdir(iso_dir()) if ISO_RE.fullmatch(n))
    except OSError:
        return []
    return [{"name": n, "mb": os.path.getsize(os.path.join(iso_dir(), n)) // 2**20} for n in names[:64]]


def domain_xml(name, project, vcpus, mem_mb, disk, seed, network, boot="bios", fw=None, nvram="", lan="",
               extra=(), installer=False, mac="", vnc_pw=""):
    """The domain, from a fixed shape: KVM, the host's CPU, virtio disk and
    network on the project's own network, the seed as a cdrom, a serial
    console and no graphics, and BuilderBot's marker in <metadata>. `boot`
    uefi is the q35 machine on the firmware VM host installs (OVMF), with
    Secure Boot off, for an image whose kernel will not start under BIOS.
    `lan`, the host's interface, puts it on the LAN instead (macvtap), as a
    VM made a node is: the controller reaches a node at its own address,
    which a project network behind the host's NAT does not have.
    R99: `installer` boots `seed` (then an installer's ISO) before the disk;
    `extra` are further disks (vdb on); every disk gives freed space back
    (discard); a screen over VNC on the loopback, with `vnc_pw` when given,
    for the dock's Screen; `mac` keeps the address a DHCP reservation knows."""
    mac_el = f"<mac address={quoteattr(mac)}/>" if mac else ""
    nic = (f"<interface type='direct'>{mac_el}<source dev={quoteattr(lan)} mode='bridge'/><model type='virtio'/></interface>"
           if lan else f"<interface type='network'>{mac_el}<source network={quoteattr(network)}/><model type='virtio'/></interface>")
    # A serial per disk, the same every boot, so /dev/disk/by-id names it
    # (virtio takes 20 bytes): this VM's and the disk's own.
    tag = hashlib.sha256(name.encode()).hexdigest()[:10]
    serial = lambda dev: f"<serial>bb{tag}-{dev}</serial>"  # noqa: E731
    boots = "<boot dev='cdrom'/><boot dev='hd'/>" if installer else "<boot dev='hd'/>"
    disks = "".join(f"\n    <disk type='file' device='disk'><driver name='qemu' type='qcow2' discard='unmap'/>"
                    f"<source file={quoteattr(d)}/><target dev='{DISK_DEVS[i + 1]}' bus='virtio'/>{serial(DISK_DEVS[i + 1])}</disk>"
                    for i, d in enumerate(list(extra)[:len(DISK_DEVS) - 1]))
    pw = f" passwd={quoteattr(vnc_pw)}" if vnc_pw else ""
    arch = escape(os.uname().machine)
    os_el = (f"<os><type arch='{arch}' machine='q35'>hvm</type>"
             f"<loader readonly='yes' type='pflash'>{escape(fw[0])}</loader>"
             # Made qcow2 at create from the template: libvirt snapshots a
             # UEFI VM only with its variables in qcow2 (a snapshot of a Debian
             # 13 VM failed on the raw copy it made itself).
             f"<nvram format='qcow2'>{escape(nvram)}</nvram>"
             f"{boots}</os>" if boot == "uefi" and fw else
             f"<os><type arch='{arch}'>hvm</type>{boots}</os>")
    return f"""<domain type='kvm'>
  <name>{escape(name)}</name>
  <metadata><bb:vm xmlns:bb={quoteattr(META_NS)} project={quoteattr(project)}/></metadata>
  <memory unit='MiB'>{int(mem_mb)}</memory>
  <vcpu>{int(vcpus)}</vcpu>
  {os_el}
  <features><acpi/><apic/></features>
  <cpu mode='host-passthrough'/>
  <devices>
    <disk type='file' device='disk'><driver name='qemu' type='qcow2' discard='unmap'/><source file={quoteattr(disk)}/><target dev='vda' bus='virtio'/>{serial('vda')}</disk>{disks}
    <disk type='file' device='cdrom'><driver name='qemu' type='raw'/><source file={quoteattr(seed)}/><target dev='sda' bus='sata'/><readonly/></disk>
    {nic}
    <graphics type='vnc' listen='127.0.0.1' autoport='yes'{pw}/>
    <video><model type='virtio'/></video>
    <input type='tablet' bus='usb'/>
    <serial type='pty'><target port='0'/></serial>
    <console type='pty'><target type='serial' port='0'/></console>
    <channel type='unix'><target type='virtio' name='org.qemu.guest_agent.0'/></channel>
    <rng model='virtio'><backend model='random'>/dev/urandom</backend></rng>
  </devices>
</domain>
"""


def network_xml(name, subnet):
    """A project's own network: NAT to the internet from its own /24, with
    libvirt's DHCP handing out the addresses."""
    net = ipaddress.ip_network(subnet)
    hosts = list(net.hosts())
    gw, lo, hi = hosts[0], hosts[9], hosts[-1]
    return f"""<network>
  <name>{escape(name)}</name>
  <forward mode='nat'/>
  <bridge name='{escape(name[:15])}' stp='on' delay='0'/>
  <ip address='{gw}' netmask='{net.netmask}'>
    <dhcp><range start='{lo}' end='{hi}'/></dhcp>
  </ip>
</network>
"""


class VmsMixin:
    """Agent's VM jobs: one of the parts class Agent (agent.py) is made of."""

    def _vm_run(self, job, argv, who, timeout=300, say=True):
        """One command of the table, as the jobs account; its words into the
        job's log. Returns the exit code."""
        env = dict(os.environ)
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, check=False, **who)
        except (OSError, subprocess.TimeoutExpired) as e:
            job.say(f"{os.path.basename(argv[0])} did not run: {e}\n")
            return 127
        text = (p.stdout + p.stderr).strip()
        if text and (say or p.returncode):
            job.say(text[-4000:] + "\n")
        return p.returncode

    def vm(self, job, spec):
        """One VM action. `spec` carries the action, the domain's name and
        what the action needs; each is checked against its shape before any
        command is built."""
        action = str(spec.get("action") or "")
        name = str(spec.get("domain") or "")
        if action not in ACTIONS:
            job.say(f"refused: {action or 'no action'} is not a VM action (one of {', '.join(ACTIONS)})\n")
            return "failed", 64
        if not DOMAIN_RE.fullmatch(name) and not action.startswith("iso-") and action != "vbios":
            job.say(f"refused: {name or 'no name'} is not a BuilderBot VM's name\n")
            return "failed", 64
        if not shutil.which("virsh") or not os.path.isdir(VM_DIR):
            job.say("refused: this node's VM host feature is not installed (its Features section installs it)\n")
            return "failed", 78
        who = self.drop_privileges({})
        job.say(f"vm {action} {name}\n")
        state, code = getattr(self, "_vm_" + action.replace("-", "_"))(job, spec, name, who)
        self.hello_again(f"the VM {name}: {action}")
        return state, code

    def _vm_exists(self, name, who):
        return subprocess.run(VIRSH + ["dominfo", name], capture_output=True, check=False, **who).returncode == 0

    def _vm_image(self, job, spec, who):
        """The cached base image for spec's OS, fetched and checked by the
        checksum file its publisher signs off on when it is not here yet."""
        img = spec.get("image") if isinstance(spec.get("image"), dict) else {}
        iid, url, sums, fname = (str(img.get(k) or "") for k in ("id", "url", "sums", "file"))
        if not (IMAGE_RE.fullmatch(iid) and FILE_RE.fullmatch(fname) and url.startswith("https://")
                and sums.startswith("https://")):
            job.say("refused: the image is not one of the catalog's (an id, an https address, its checksum file)\n")
            return ""
        path = os.path.join(VM_DIR, "images", iid + ".qcow2")
        if os.path.isfile(path):
            job.say(f"image {iid}: cached\n")
            return path
        self.own_dir(os.path.dirname(path), who)
        try:
            with urllib.request.urlopen(sums, timeout=60) as r:  # noqa: S310 (https, checked above)
                want = sums_lookup(r.read(2_000_000).decode("utf-8", "replace"), fname)
        except OSError as e:
            job.say(f"could not read {iid}'s checksums from {sums}: {e}\n")
            return ""
        if not want:
            job.say(f"{sums} names no checksum for {fname}\n")
            return ""
        h = hashlib.sha512() if len(want) == 128 else hashlib.sha256()
        part = path + ".part"
        job.step(f"downloading {iid}")
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:  # noqa: S310
                total = int(r.headers.get("Content-Length") or 0)
                got, said = 0, 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    if total and got * 10 // total > said:
                        said = got * 10 // total
                        job.say(f"{iid}: {said * 10}% of {total // 2**20} MB\n")
        except OSError as e:
            job.say(f"could not download {iid} from {url}: {e}\n")
            with contextlib.suppress(OSError):
                os.unlink(part)
            return ""
        if h.hexdigest() != want:
            job.say(f"{iid} does not match its publisher's checksum; not kept\n")
            os.unlink(part)
            return ""
        os.replace(part, path)
        if who:
            with contextlib.suppress(OSError):
                os.chown(path, who["user"], who["group"])
        job.say(f"image {iid}: downloaded and checked\n")
        return path

    def _vm_network(self, job, spec, who):
        """The project's network, made and started when it is not there."""
        net, subnet = str(spec.get("network") or ""), str(spec.get("subnet") or "")
        try:
            ok = NETWORK_RE.fullmatch(net) and ipaddress.ip_network(subnet).prefixlen == 24
        except ValueError:
            ok = False
        if not ok:
            job.say("refused: the network is not a project's (bbvm-NAME on a /24)\n")
            return False
        if subprocess.run(VIRSH + ["net-info", net], capture_output=True, check=False, **who).returncode != 0:
            with tempfile.NamedTemporaryFile("w", suffix=".xml", dir=VM_DIR, delete=False) as f:
                f.write(network_xml(net, subnet))
            os.chmod(f.name, 0o644)              # virsh reads it as the jobs account
            try:
                if self._vm_run(job, VIRSH + ["net-define", f.name], who) != 0:
                    return False
            finally:
                os.unlink(f.name)
            self._vm_run(job, VIRSH + ["net-autostart", net], who, say=False)
        active = subprocess.run(VIRSH + ["net-info", net], capture_output=True, text=True, check=False, **who).stdout
        if re.search(r"Active:\s+no", active):
            return self._vm_run(job, VIRSH + ["net-start", net], who) == 0
        return True

    def _vm_seed(self, job, path, hostname, user, keys, who, enroll=""):
        """The cloud-init seed: cidata on an ISO, by whichever tool is here."""
        with tempfile.TemporaryDirectory(dir=VM_DIR) as d:
            ud, md = os.path.join(d, "user-data"), os.path.join(d, "meta-data")
            with open(ud, "w") as f:
                f.write(user_data(hostname, user, keys, enroll))
            with open(md, "w") as f:
                f.write(f"instance-id: {hostname}\nlocal-hostname: {hostname}\n")
            for tool in ("cloud-localds", "genisoimage", "mkisofs", "xorrisofs"):
                if not shutil.which(tool):
                    continue
                argv = ([tool, path, ud, md] if tool == "cloud-localds"
                        else [tool, "-output", path, "-volid", "cidata", "-joliet", "-rock", ud, md])
                if self._vm_run(job, argv, {}, say=False) == 0:
                    if who:
                        with contextlib.suppress(OSError):
                            os.chown(path, who["user"], who["group"])
                    return True
            job.say("could not make the cloud-init seed: no cloud-localds, genisoimage, mkisofs or xorrisofs here\n")
            return False

    def _vm_create(self, job, spec, name, who):
        project = str(spec.get("project") or "")
        user = str(spec.get("user") or "builder")
        keys = [str(k).strip() for k in (spec.get("keys") or [])][:8]
        # From an installer (R99): its ISO on this node, a blank disk, no seed.
        iso = str((spec.get("installer") or {}).get("iso") or "") if isinstance(spec.get("installer"), dict) else ""
        try:
            vcpus, mem, disk_gb = int(spec.get("vcpus") or 0), int(spec.get("mem_mb") or 0), int(spec.get("disk_gb") or 0)
            extra_gb = [int(g) for g in (spec.get("disks") or [])][:len(DISK_DEVS) - 1]
        except (TypeError, ValueError):
            vcpus = mem = disk_gb = 0
            extra_gb = []
        mac = str(spec.get("mac") or "").lower()
        vnc_pw = str(spec.get("console_password") or "")
        if not (re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,60}", project) and USER_RE.fullmatch(user)
                and all(KEY_RE.fullmatch(k) for k in keys)
                and 1 <= vcpus <= MAX_VCPUS and 256 <= mem <= MAX_MEM_MB and 2 <= disk_gb <= MAX_DISK_GB
                and all(1 <= g <= MAX_DISK_GB for g in extra_gb)
                and (not iso or ISO_RE.fullmatch(iso)) and (not mac or MAC_RE.fullmatch(mac))
                and (not vnc_pw or VNC_PW_RE.fullmatch(vnc_pw))):
            job.say("refused: the VM's project, account, keys, size, disks, ISO, address or console password are not what a VM takes\n")
            return "failed", 64
        if self._vm_exists(name, who):
            job.say(f"refused: {name} is there already\n")
            return "failed", 73
        base = ""
        if iso:
            seed = os.path.join(iso_dir(), iso)
            if not os.path.isfile(seed):
                job.say(f"refused: {iso} is not on this node; Add ISO on the VMs page fetches it\n")
                return "failed", 66
        else:
            base = self._vm_image(job, spec, who)
            if not base:
                return "failed", 69
        enroll = "" if iso else str(spec.get("enroll") or "")
        # Made a node: on the LAN as its own machine, where the controller
        # reaches it; every other VM on its project's network.
        lan = lan_iface() if enroll else ""
        if enroll and not lan:
            job.say("refused: this machine has no default route to put a node VM on the LAN by\n")
            return "failed", 69
        # Wi-Fi carries one machine's address, not a guest's beside it: a node
        # VM on it would never get one.
        if lan and os.path.isdir(f"/sys/class/net/{lan}/wireless"):
            job.say(f"refused: {lan} is Wi-Fi, which will not carry a second machine's address; a node VM needs "
                    "this machine on a wired network (Ethernet, a bond or a bridge)\n")
            return "failed", 69
        if not lan and not self._vm_network(job, spec, who):
            return "failed", 69
        ddir = os.path.join(VM_DIR, "disks")
        self.own_dir(ddir, who)
        disk = os.path.join(ddir, name + ".qcow2")
        job.step("making its disk")
        made = ["qemu-img", "create", "-f", "qcow2", disk, f"{disk_gb}G"] if iso else \
            ["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", base, disk, f"{disk_gb}G"]
        if self._vm_run(job, made, who, say=False) != 0:
            return "failed", 70
        extra = []
        for i, g in enumerate(extra_gb):
            d = os.path.join(ddir, f"{name}-d{i + 1}.qcow2")
            if self._vm_run(job, ["qemu-img", "create", "-f", "qcow2", d, f"{g}G"], who, say=False) != 0:
                return "failed", 70
            extra.append(d)
        if extra:
            job.say(f"and {len(extra)} more disk{'s' if len(extra) > 1 else ''}: {', '.join(f'{g} GB' for g in extra_gb)}\n")
        if not iso:
            seed = os.path.join(ddir, name + "-seed.iso")
            hostname = name.removeprefix("bbvm-")[:63]
            if enroll and (not enroll.startswith(ENROLL_HEAD) or len(enroll) > 4_000_000):
                job.say("refused: what came to enroll the VM as a node is not the controller's enroll script\n")
                return "failed", 64
            if enroll:
                job.say(f"it joins the LAN on {lan} as its own machine and enrolls as a node at its first boot\n")
            if not self._vm_seed(job, seed, hostname, user, keys, who, enroll):
                return "failed", 70
        else:
            job.say(f"it boots {iso}: its installer is on its Screen, in the dock\n")
        xml = os.path.join(ddir, name + ".xml")
        boot = "uefi" if spec.get("boot") == "uefi" else "bios"
        fw = ovmf() if boot == "uefi" else None
        if boot == "uefi" and not fw:
            job.say("refused: this image boots by UEFI and the firmware is not here: run VM host's install again on the node's Features section\n")
            return "failed", 69
        nvram = os.path.join(ddir, name + "_VARS.qcow2")
        if fw and self._vm_run(job, ["qemu-img", "convert", "-f", "raw", "-O", "qcow2", fw[1], nvram], who, say=False) != 0:
            return "failed", 70
        text = domain_xml(name, project, vcpus, mem, disk, seed, str(spec.get("network") or ""), boot, fw,
                          nvram, lan, extra=extra, installer=bool(iso), mac=mac, vnc_pw=vnc_pw)
        # Its hardware beyond size (R100), where New VM gave any.
        hw, why = vmhw.clean(spec.get("hw"), vcpus, mem)
        if hw is None or (hw and not self._vm_hw_ok(job, hw)):
            if why:
                job.say(f"refused: {why}\n")
            return "failed", 64
        if hw:
            text = vmhw.apply(text, hw, vcpus, mem, lan=lan or lan_iface(), network=str(spec.get("network") or ""),
                              vbios_dir=os.path.join(VM_DIR, vmhw.VBIOS_DIR))
        with open(xml, "w") as f:
            f.write(text)
        job.step("starting it")
        if self._vm_run(job, VIRSH + ["define", xml], who) != 0:
            return "failed", 70
        # Starting with its host is asked for (R100), but for a node, whose
        # whole point is to be there.
        if spec.get("autostart") is True or enroll:
            self._vm_run(job, VIRSH + ["autostart", name], who, say=False)
        if self._vm_run(job, VIRSH + ["start", name], who) != 0:
            return "failed", 70
        job.say(f"{name} is running: {vcpus} vCPU, {mem} MB, {disk_gb} GB; it takes its address once it has booted\n")
        return "succeeded", 0

    def _vm_eject(self, job, spec, name, who):
        """The installer's ISO out of its drive, once the system is on disk,
        so the next boot is the disk's."""
        if not self._vm_exists(name, who):
            job.say(f"{name} is not on this machine\n")
            return "failed", 66
        live = "running" in subprocess.run(VIRSH + ["domstate", name], capture_output=True, text=True,
                                           check=False, **who).stdout
        argv = VIRSH + ["change-media", name, "sda", "--eject", "--config"] + (["--live"] if live else [])
        if self._vm_run(job, argv, who) != 0:
            return "failed", 70
        job.say("ejected: the next boot is from its disk\n")
        return "succeeded", 0

    def _vm_disk_grow(self, job, spec, name, who):
        """One of a stopped VM's disks made larger; the partition inside is
        the system's own to grow."""
        dev = str(spec.get("disk") or "vda")
        try:
            gb = int(spec.get("gb") or 0)
        except (TypeError, ValueError):
            gb = 0
        if dev not in DISK_DEVS or not 2 <= gb <= MAX_DISK_GB:
            job.say("refused: a disk is vda to vdd and a size in GB\n")
            return "failed", 64
        if "shut off" not in subprocess.run(VIRSH + ["domstate", name], capture_output=True, text=True,
                                            check=False, **who).stdout:
            job.say("refused: stop the VM first; a disk grows while it is off\n")
            return "failed", 75
        i = DISK_DEVS.index(dev)
        path = os.path.join(VM_DIR, "disks", name + (".qcow2" if i == 0 else f"-d{i}.qcow2"))
        if not os.path.isfile(path):
            job.say(f"{name} has no disk {dev}\n")
            return "failed", 66
        if self._vm_run(job, ["qemu-img", "resize", path, f"{gb}G"], who) != 0:
            job.say("qemu-img refused it: a disk grows and never shrinks\n")
            return "failed", 70
        job.say(f"{dev} is {gb} GB now; grow its partition inside the system to use it\n")
        return "succeeded", 0

    def _vm_disk_add(self, job, spec, name, who):
        """A further disk on a stopped VM, the next of vdb to vdd."""
        try:
            gb = int(spec.get("gb") or 0)
        except (TypeError, ValueError):
            gb = 0
        if not 1 <= gb <= MAX_DISK_GB:
            job.say("refused: a disk is 1 GB to 4 TB\n")
            return "failed", 64
        if "shut off" not in subprocess.run(VIRSH + ["domstate", name], capture_output=True, text=True,
                                            check=False, **who).stdout:
            job.say("refused: stop the VM first; a disk is added while it is off\n")
            return "failed", 75
        ddir = os.path.join(VM_DIR, "disks")
        i = next((k for k in range(1, len(DISK_DEVS)) if not os.path.exists(os.path.join(ddir, f"{name}-d{k}.qcow2"))), 0)
        if not i:
            job.say(f"refused: {name} has {len(DISK_DEVS)} disks already\n")
            return "failed", 64
        path = os.path.join(ddir, f"{name}-d{i}.qcow2")
        if self._vm_run(job, ["qemu-img", "create", "-f", "qcow2", path, f"{gb}G"], who, say=False) != 0:
            return "failed", 70
        if self._vm_run(job, VIRSH + ["attach-disk", name, path, DISK_DEVS[i], "--driver", "qemu", "--subdriver", "qcow2",
                                      "--targetbus", "virtio", "--config"], who) != 0:
            with contextlib.suppress(OSError):
                os.unlink(path)
            return "failed", 70
        job.say(f"{DISK_DEVS[i]}: a {gb} GB disk, there at its next start\n")
        return "succeeded", 0

    def _vm_hw_ok(self, job, hw):
        """What the host must hold for `hw`: a passed device not the host's own
        display's, PCI ones under an IOMMU, a LAN that is wired, virtiofsd for
        a share. Said and False when it does not."""
        host = vmhw.host_hw()
        for d in hw.get("devices") or []:
            if d["type"] == "pci":
                if not host["iommu"]:
                    job.say("refused: this machine's IOMMU is off (intel_iommu=on or amd_iommu=on on its kernel's "
                            "command line, and VT-d or AMD-Vi in its firmware), so no PCI device can be passed through\n")
                    return False
                row = next((p for p in host["pci"] if p["addr"] == d["addr"]), None)
                if not row:
                    job.say(f"refused: no PCI device {d['addr']} here\n")
                    return False
                if row["driver"] == "nvidia" and subprocess.run(["systemctl", "is-active", "--quiet", "builderbot-gpu-display"],
                                                                check=False).returncode == 0:
                    job.say(f"refused: {d['addr']} is the card the host's own display runs on (the emulators' GPU); "
                            "switch the GPU display off on the node's page first\n")
                    return False
        if hw.get("net") == "lan" and os.path.isdir(f"/sys/class/net/{lan_iface()}/wireless"):
            job.say("refused: this machine's LAN is Wi-Fi, which will not carry a second machine's address\n")
            return False
        if hw.get("share") and not (shutil.which("virtiofsd") or os.path.exists("/usr/libexec/virtiofsd")
                                    or os.path.exists("/usr/lib/qemu/virtiofsd")):
            job.say("refused: virtiofsd is not on this machine; VM host's install brings it from this build on: "
                    "install VM host again on the node's Features section\n")
            return False
        if hw.get("share") and not os.path.isdir(hw["share"]["path"]):
            job.say(f"refused: {hw['share']['path']} is not a folder on this node\n")
            return False
        return True

    def _vm_hardware(self, job, spec, name, who):
        """A stopped VM's hardware beyond size, changed: its own XML read,
        the record applied, defined again."""
        if not self._vm_exists(name, who):
            job.say(f"{name} is not on this machine\n")
            return "failed", 66
        if "shut off" not in subprocess.run(VIRSH + ["domstate", name], capture_output=True, text=True,
                                            check=False, **who).stdout:
            job.say("refused: stop the VM first; its hardware changes while it is off\n")
            return "failed", 75
        xml = subprocess.run(VIRSH + ["dumpxml", name, "--inactive"], capture_output=True, text=True,
                             check=False, **who).stdout
        m_v = re.search(r"<vcpu[^>]*>(\d+)</vcpu>", xml)
        cur = re.search(r"<currentMemory unit='KiB'>(\d+)</currentMemory>", xml) or re.search(r"<memory unit='KiB'>(\d+)</memory>", xml)
        vcpus, mem = int(m_v.group(1)) if m_v else 1, int(cur.group(1)) // 1024 if cur else 1024
        hw, why = vmhw.clean(spec.get("hw"), vcpus, mem)
        if hw is None:
            job.say(f"refused: {why}\n")
            return "failed", 64
        if not self._vm_hw_ok(job, hw):
            return "failed", 64
        try:
            text = vmhw.apply(xml, hw, vcpus, mem, lan=lan_iface(), network=str(spec.get("network") or ""),
                              vbios_dir=os.path.join(VM_DIR, vmhw.VBIOS_DIR))
        except ValueError as e:
            job.say(f"refused: {e}\n")
            return "failed", 65
        path = os.path.join(VM_DIR, "disks", name + ".xml")
        with open(path, "w") as f:
            f.write(text)
        if self._vm_run(job, VIRSH + ["define", path], who) != 0:
            return "failed", 70
        job.say(f"{name}'s hardware changed: " + ", ".join(sorted(hw)) + "\n")
        return "succeeded", 0

    def _vm_autostart(self, job, spec, name, who):
        on = spec.get("on") is True
        if self._vm_run(job, VIRSH + ["autostart", name] + ([] if on else ["--disable"]), who) != 0:
            return "failed", 70
        job.say(f"{name} {'starts' if on else 'no longer starts'} with its host\n")
        return "succeeded", 0

    def _vm_vbios(self, job, spec, name, who):
        """A GPU's vBIOS dumped through sysfs, as root (R100)."""
        if os.geteuid() != 0:
            job.say("refused: dumping a vBIOS is root's, and this agent is not\n")
            return "failed", 77
        got = vmhw.vbios_dump(str(spec.get("addr") or ""), os.path.join(VM_DIR, vmhw.VBIOS_DIR), job.say)
        return ("succeeded", 0) if got else ("failed", 70)

    def _vm_iso_add(self, job, spec, name, who):
        """An installer's ISO onto this node, kept only when it matches the
        SHA-256 given: from an https address, or uploaded on the VMs page
        and fetched from the controller with this node's own token (R99)."""
        iso = spec.get("iso") if isinstance(spec.get("iso"), dict) else {}
        fname, url, want = str(iso.get("name") or ""), str(iso.get("url") or ""), str(iso.get("sha256") or "").lower()
        upload = str(iso.get("upload") or "")
        if not (ISO_RE.fullmatch(fname) and (url.startswith("https://") or re.fullmatch(r"[0-9a-f]{16}", upload))
                and SHA256_RE.fullmatch(want)):
            job.say("refused: an ISO is a name ending .iso, an https address or an upload, and its SHA-256\n")
            return "failed", 64
        self.own_dir(iso_dir(), who)
        path = os.path.join(iso_dir(), fname)
        if os.path.isfile(path):
            job.say(f"{fname} is here already\n")
            return "succeeded", 0
        part = path + ".part"
        if upload:
            job.step(f"fetching {fname} from the controller")
            code, _ = self.ctl.fetch(f"iso?job={job.job['id']}&upload={upload}", part, timeout=7200)
            if code != 200:
                job.say(f"could not fetch {fname} from the controller ({code})\n")
                return "failed", 69
        elif not self._vm_iso_download(job, fname, url, part):
            return "failed", 69
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != want:
            job.say(f"{fname} does not match the SHA-256 given ({h.hexdigest()}); not kept\n")
            os.unlink(part)
            return "failed", 65
        os.replace(part, path)
        if who:
            with contextlib.suppress(OSError):
                os.chown(path, who["user"], who["group"])
        job.say(f"{fname}: {'uploaded' if upload else 'downloaded'} and checked, {os.path.getsize(path) // 2**20} MB\n")
        return "succeeded", 0

    @staticmethod
    def _vm_iso_download(job, fname, url, part):
        job.step(f"downloading {fname}")
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:  # noqa: S310 (https, checked by the caller)
                total = int(r.headers.get("Content-Length") or 0)
                got, said = 0, 0
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    f.write(chunk)
                    got += len(chunk)
                    if total and got * 10 // total > said:
                        said = got * 10 // total
                        job.say(f"{fname}: {said * 10}% of {total // 2**20} MB\n")
        except OSError as e:
            job.say(f"could not download {fname} from {url}: {e}\n")
            with contextlib.suppress(OSError):
                os.unlink(part)
            return False
        return True

    def _vm_iso_rm(self, job, spec, name, who):
        fname = str((spec.get("iso") or {}).get("name") or "") if isinstance(spec.get("iso"), dict) else ""
        if not ISO_RE.fullmatch(fname):
            job.say("refused: not an ISO's name\n")
            return "failed", 64
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(iso_dir(), fname))
        job.say(f"{fname} removed from this node\n")
        return "succeeded", 0

    def _vm_simple(self, job, name, who, argv, timeout=120):
        if not self._vm_exists(name, who):
            job.say(f"{name} is not on this machine\n")
            return "failed", 66
        return ("succeeded", 0) if self._vm_run(job, VIRSH + argv, who, timeout=timeout) == 0 else ("failed", 70)

    def _vm_start(self, job, spec, name, who):
        return self._vm_simple(job, name, who, ["start", name])

    def _vm_stop(self, job, spec, name, who):
        # Asked to shut down, as a power button; --force pulls the plug.
        return self._vm_simple(job, name, who, ["destroy", name] if spec.get("force") else ["shutdown", name])

    def _vm_restart(self, job, spec, name, who):
        return self._vm_simple(job, name, who, ["reboot", name])

    def _vm_remove(self, job, spec, name, who):
        if self._vm_exists(name, who):
            subprocess.run(VIRSH + ["destroy", name], capture_output=True, check=False, **who)
            for snap in subprocess.run(VIRSH + ["snapshot-list", name, "--name"], capture_output=True, text=True,
                                       check=False, **who).stdout.split():
                if SNAP_RE.fullmatch(snap):
                    self._vm_run(job, VIRSH + ["snapshot-delete", name, snap], who, say=False)
            if self._vm_run(job, VIRSH + ["undefine", name, "--nvram"], who) != 0 \
                    and self._vm_run(job, VIRSH + ["undefine", name], who) != 0:
                return "failed", 70
        for suffix in (".qcow2", "-seed.iso", ".xml", "_VARS.fd", "_VARS.qcow2", *(f"-d{i}.qcow2" for i in range(1, len(DISK_DEVS)))):
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(VM_DIR, "disks", name + suffix))
        job.say(f"{name} removed, with its disk and its snapshots\n")
        return "succeeded", 0

    def _vm_snapname(self, job, spec):
        snap = str(spec.get("snapshot") or "")
        if not SNAP_RE.fullmatch(snap):
            job.say(f"refused: {snap or 'no name'} is not a snapshot's name (letters, digits, . _ -)\n")
            return ""
        return snap

    def _vm_snapshot(self, job, spec, name, who):
        snap = self._vm_snapname(job, spec)
        if not snap:
            return "failed", 64
        desc = re.sub(r"[^\w .,:()'-]", "", str(spec.get("note") or ""))[:200]
        if not self._vm_nvram_qcow2(job, name, who):
            return "failed", 75
        argv = ["snapshot-create-as", name, snap] + (["--description", desc] if desc else [])
        return self._vm_simple(job, name, who, argv, timeout=600)

    def _vm_nvram_qcow2(self, job, name, who):
        """A UEFI VM made before 0.6.1 keeps its firmware variables raw, which
        libvirt will not snapshot: moved to qcow2 while it is off, the domain
        defined again on the new file. True when nothing is in the way."""
        xml = subprocess.run(VIRSH + ["dumpxml", name, "--inactive"], capture_output=True, text=True,
                             check=False, **who).stdout
        m = re.search(r"<nvram([^>]*)>([^<]+)</nvram>", xml)
        if not m or "qcow2" in m.group(1):
            return True
        if "shut off" not in subprocess.run(VIRSH + ["domstate", name], capture_output=True, text=True,
                                            check=False, **who).stdout:
            job.say("refused: this VM boots by UEFI and was made before its firmware's variables were kept in qcow2, "
                    "which a snapshot needs; stop it once and take the snapshot again, and they are moved while it is off\n")
            return False
        raw = m.group(2).strip()
        new = os.path.join(VM_DIR, "disks", name + "_VARS.qcow2")
        if self._vm_run(job, ["qemu-img", "convert", "-f", "raw", "-O", "qcow2", raw, new], who, say=False) != 0:
            # libvirt hands the raw file to its own account, which the jobs
            # account cannot read: fresh variables from the firmware's own
            # template then, which a cloud image boots from as before
            # (its disk's fallback loader) and an installed system may want
            # its boot entry set again in the firmware's menu.
            fw = ovmf()
            if not fw or self._vm_run(job, ["qemu-img", "convert", "-f", "raw", "-O", "qcow2", fw[1], new], who) != 0:
                return False
            job.say("its UEFI settings start fresh from the firmware's defaults: the old file was libvirt's to read\n")
        fixed = xml.replace(m.group(0), f"<nvram format='qcow2'>{escape(new)}</nvram>")
        path = os.path.join(VM_DIR, "disks", name + ".xml")
        with open(path, "w") as f:
            f.write(fixed)
        if self._vm_run(job, VIRSH + ["define", path], who) != 0:
            return False
        job.say("its UEFI variables are in qcow2 now, which a snapshot needs\n")
        return True

    def _vm_revert(self, job, spec, name, who):
        snap = self._vm_snapname(job, spec)
        return self._vm_simple(job, name, who, ["snapshot-revert", name, snap], timeout=600) if snap else ("failed", 64)

    def _vm_snapshot_rm(self, job, spec, name, who):
        snap = self._vm_snapname(job, spec)
        return self._vm_simple(job, name, who, ["snapshot-delete", name, snap], timeout=600) if snap else ("failed", 64)
