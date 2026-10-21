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
ACTIONS = ("create", "start", "stop", "restart", "remove", "snapshot", "revert", "snapshot-rm")
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
        out.append({"name": name, "state": _state_word(info.get("state", "")), "ip": ip,
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
    if enroll:
        import base64
        lines += ["write_files:", "  - path: /root/bb-enroll.sh", "    permissions: '0700'", "    encoding: b64",
                  f"    content: {base64.b64encode(enroll.encode()).decode()}",
                  "runcmd:", "  - [bash, -c, 'bash /root/bb-enroll.sh > /root/bb-enroll.log 2>&1; rm -f /root/bb-enroll.sh']"]
    return "\n".join(lines) + "\n"


# The UEFI firmware VM host installs, named rather than left to libvirt's
# pick, which chose the AMD SEV build on the dev node (21 Oct): its code, and
# the template its variables file is copied from, by family.
OVMF_PAIRS = (("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd"),
              ("/usr/share/edk2/ovmf/OVMF_CODE.fd", "/usr/share/edk2/ovmf/OVMF_VARS.fd"),
              ("/usr/share/AAVMF/AAVMF_CODE.fd", "/usr/share/AAVMF/AAVMF_VARS.fd"))


def ovmf():
    """(code, vars template) of the UEFI firmware here, or None."""
    return next((p for p in OVMF_PAIRS if os.path.isfile(p[0]) and os.path.isfile(p[1])), None)


def domain_xml(name, project, vcpus, mem_mb, disk, seed, network, boot="bios", fw=None, nvram="", lan=""):
    """The domain, from a fixed shape: KVM, the host's CPU, virtio disk and
    network on the project's own network, the seed as a cdrom, a serial
    console and no graphics, and BuilderBot's marker in <metadata>. `boot`
    uefi is the q35 machine on the firmware VM host installs (OVMF), with
    Secure Boot off, for an image whose kernel will not start under BIOS.
    `lan`, the host's interface, puts it on the LAN instead (macvtap), as a
    VM made a node is: the controller reaches a node at its own address,
    which a project network behind the host's NAT does not have."""
    nic = (f"<interface type='direct'><source dev={quoteattr(lan)} mode='bridge'/><model type='virtio'/></interface>"
           if lan else f"<interface type='network'><source network={quoteattr(network)}/><model type='virtio'/></interface>")
    arch = escape(os.uname().machine)
    os_el = (f"<os><type arch='{arch}' machine='q35'>hvm</type>"
             f"<loader readonly='yes' type='pflash'>{escape(fw[0])}</loader>"
             f"<nvram template={quoteattr(fw[1])}>{escape(nvram)}</nvram>"
             "<boot dev='hd'/></os>" if boot == "uefi" and fw else
             f"<os><type arch='{arch}'>hvm</type><boot dev='hd'/></os>")
    return f"""<domain type='kvm'>
  <name>{escape(name)}</name>
  <metadata><bb:vm xmlns:bb={quoteattr(META_NS)} project={quoteattr(project)}/></metadata>
  <memory unit='MiB'>{int(mem_mb)}</memory>
  <vcpu>{int(vcpus)}</vcpu>
  {os_el}
  <features><acpi/><apic/></features>
  <cpu mode='host-passthrough'/>
  <devices>
    <disk type='file' device='disk'><driver name='qemu' type='qcow2'/><source file={quoteattr(disk)}/><target dev='vda' bus='virtio'/></disk>
    <disk type='file' device='cdrom'><driver name='qemu' type='raw'/><source file={quoteattr(seed)}/><target dev='sda' bus='sata'/><readonly/></disk>
    {nic}
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
        if not DOMAIN_RE.fullmatch(name):
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
        try:
            vcpus, mem, disk_gb = int(spec.get("vcpus") or 0), int(spec.get("mem_mb") or 0), int(spec.get("disk_gb") or 0)
        except (TypeError, ValueError):
            vcpus = mem = disk_gb = 0
        if not (re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,60}", project) and USER_RE.fullmatch(user)
                and all(KEY_RE.fullmatch(k) for k in keys)
                and 1 <= vcpus <= MAX_VCPUS and 256 <= mem <= MAX_MEM_MB and 2 <= disk_gb <= MAX_DISK_GB):
            job.say("refused: the VM's project, account, keys or size are not what a VM takes\n")
            return "failed", 64
        if self._vm_exists(name, who):
            job.say(f"refused: {name} is there already\n")
            return "failed", 73
        base = self._vm_image(job, spec, who)
        if not base:
            return "failed", 69
        enroll = str(spec.get("enroll") or "")
        # Made a node: on the LAN as its own machine, where the controller
        # reaches it; every other VM on its project's network.
        lan = lan_iface() if enroll else ""
        if enroll and not lan:
            job.say("refused: this machine has no default route to put a node VM on the LAN by\n")
            return "failed", 69
        if not lan and not self._vm_network(job, spec, who):
            return "failed", 69
        ddir = os.path.join(VM_DIR, "disks")
        self.own_dir(ddir, who)
        disk, seed = os.path.join(ddir, name + ".qcow2"), os.path.join(ddir, name + "-seed.iso")
        job.step("making its disk")
        if self._vm_run(job, ["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", base, disk, f"{disk_gb}G"],
                        who, say=False) != 0:
            return "failed", 70
        hostname = name.removeprefix("bbvm-")[:63]
        if enroll and (not enroll.startswith(ENROLL_HEAD) or len(enroll) > 4_000_000):
            job.say("refused: what came to enroll the VM as a node is not the controller's enroll script\n")
            return "failed", 64
        if enroll:
            job.say(f"it joins the LAN on {lan} as its own machine and enrolls as a node at its first boot\n")
        if not self._vm_seed(job, seed, hostname, user, keys, who, enroll):
            return "failed", 70
        xml = os.path.join(ddir, name + ".xml")
        boot = "uefi" if spec.get("boot") == "uefi" else "bios"
        fw = ovmf() if boot == "uefi" else None
        if boot == "uefi" and not fw:
            job.say("refused: this image boots by UEFI and the firmware is not here: run VM host's install again on the node's Features section\n")
            return "failed", 69
        with open(xml, "w") as f:
            f.write(domain_xml(name, project, vcpus, mem, disk, seed, str(spec["network"]), boot, fw,
                               os.path.join(ddir, name + "_VARS.fd"), lan))
        job.step("starting it")
        if self._vm_run(job, VIRSH + ["define", xml], who) != 0:
            return "failed", 70
        self._vm_run(job, VIRSH + ["autostart", name], who, say=False)
        if self._vm_run(job, VIRSH + ["start", name], who) != 0:
            return "failed", 70
        job.say(f"{name} is running: {vcpus} vCPU, {mem} MB, {disk_gb} GB; it takes its address once it has booted\n")
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
        for suffix in (".qcow2", "-seed.iso", ".xml", "_VARS.fd"):
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
        argv = ["snapshot-create-as", name, snap] + (["--description", desc] if desc else [])
        return self._vm_simple(job, name, who, argv, timeout=600)

    def _vm_revert(self, job, spec, name, who):
        snap = self._vm_snapname(job, spec)
        return self._vm_simple(job, name, who, ["snapshot-revert", name, snap], timeout=600) if snap else ("failed", 64)

    def _vm_snapshot_rm(self, job, spec, name, who):
        snap = self._vm_snapname(job, spec)
        return self._vm_simple(job, name, who, ["snapshot-delete", name, snap], timeout=600) if snap else ("failed", 64)
