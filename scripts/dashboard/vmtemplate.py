#!/usr/bin/env python3
"""What a new sandbox VM is made from, with this one's identity in it.

`nodes/unraid-vm.xml` is the machine (q35, shared memory backing, a virtio
rng, sizes for something that compiles) and it is one file for every
distribution. What it cannot be is a template you paste twice: three fields
in it belong to ONE virtual machine, and a second VM wearing them is a
second VM pointing at the first one's OVMF nvram file and answering to its
MAC on the network.

So this renders that file rather than copying it: a UUID, the nvram path
named after that UUID (Unraid names it that way and libvirt writes it
there), a MAC on QEMU's own 52:54:00 prefix, and the name the operator gave,
which is also the domain directory their vdisk lives in. Nothing else about
the machine moves: the reasoning in the file's comments is the reasoning
here.

Both identities are GIVEN as well as generated, and that is the whole of the
sequencing problem. Unraid mints its own pair when the VM is created in Form
view: the nvram file on disk is named after its UUID, and any DHCP
reservation was made against its MAC. So a fresh pair is right for a machine
that does not exist yet, and Unraid's pair is right the moment it does:
pasting them in is what keeps the firmware variables and the address the
ones already set up.

The comments themselves are stripped from what comes back. They are for
whoever reads the repository; Unraid drops them the moment the VM is saved,
and 130 lines of them in a paste box is 130 lines to scroll past.

AND THE SAME FOR SIX MORE HYPERVISORS. A node is a machine, not an Unraid
machine, and the shape above is the same question everywhere: cores, memory,
a disk, an installer, and an identity that must not be shared with another
VM. `nodes/vm/` holds one template per hypervisor and HYPERVISORS below says
what each of them is: the artifact it produces, the MAC range it accepts,
and the steps from that manager's "new VM" to an enrolled node.

The MAC range is the detail worth having a table for: every one of these
refuses, silently reassigns, or duplicates an address from the wrong vendor
prefix. VMware takes a static address only inside 00:50:56:00-3F, Hyper-V
uses 00:15:5D, VirtualBox 08:00:27, and QEMU and everything on top of it
52:54:00. Getting it wrong by hand gives you two machines on one address on
the day you make the second node.

Unraid is rendered from `nodes/unraid-vm.xml` (the real, pasteable machine
this repository keeps) by rewriting the values in place. The other six are
templates with placeholders, because there is no such thing as a VMware .vmx
or a `qm create` line that is useful without a name in it.
"""
import random
import re
import string
import uuid
from pathlib import Path

# The shipped machine. Two directories up from this module is the repo root
# in a checkout and /opt/builderbot in the image, so one expression finds it
# in both, which is what `bb dashboard dev` needs to serve the checkout's.
TEMPLATE = Path(__file__).resolve().parents[2] / "nodes" / "unraid-vm.xml"

# ---- the hypervisors -------------------------------------------------------
# One entry per manager: what to call it, the file it renders from, what the
# artifact is called and how it is used, the MAC prefix that manager accepts,
# and the steps from its own "new VM" to an enrolled node. The steps are the
# half somebody actually needs at the keyboard, and they are per hypervisor
# because "make a disk and boot the ISO" is six different gestures.
#
# `wants` says which identity fields the dialog offers. All of them take a
# MAC; only the ones that let a machine keep an id take a uuid.
# Whether unvetted hypervisors may be offered, from the controller's
# settings (server.py sets it); None reads as no. `vetted` on an entry is
# the evidence: a VM made from it and used, or "" for a template written to
# the hypervisor's documented shape and never run.
unvetted_ok = None

HYPERVISORS = {
    "unraid": {
        "label": "Unraid", "vetted": "bb-sandbox, bb-sandbox-redhat and bb-dev-sandbox were all made from it (2026-09-15)",
        "file": "unraid-vm.xml", "artifact": "domain XML", "lang": "xml",
        "mac_prefix": "52:54:00", "wants": ("uuid", "mac"),
        "steps": [
            "Unraid → VMS → Add VM → Linux. Name it {name}, give it {cores} cores, "
            "{memory_gb} GiB and a {disk_gb}G vdisk, and Create, which makes the folder "
            "and the disk.",
            "Open it → Edit → XML View, paste this over what is there, Update. Its uuid "
            "and MAC are above: paste Unraid's own into them and Generate again to keep "
            "the firmware settings and the address it already has.",
            "Start it and install: headless, no desktop, ssh on.",
            "Export the shares to its address first (Unraid → Shares → the share → NFS "
            "Security Settings) or every mount on it is refused.",
            "Back here, Enroll node mints a token; run the provision command it gives "
            "you on the VM, as root.",
        ],
    },
    "proxmox": {
        "label": "Proxmox VE", "vetted": "",
        "file": "vm/proxmox.sh", "artifact": "shell script", "lang": "sh",
        "mac_prefix": "52:54:00", "wants": ("uuid", "mac", "vmid"),
        "steps": [
            "Check the three names at the top: the storage the disks land on, the store "
            "holding {iso}, and the bridge.",
            "Run it on the Proxmox host as root. It creates the VM and starts it.",
            "Open its console in the web UI and install: no desktop, ssh on.",
            "Back here, Enroll node mints a token; run the provision command it gives "
            "you on the VM, as root.",
        ],
    },
    "libvirt": {
        "label": "libvirt / KVM", "vetted": "",
        "file": "vm/libvirt.sh", "artifact": "virt-install command", "lang": "sh",
        "mac_prefix": "52:54:00", "wants": ("uuid", "mac"),
        "steps": [
            "Check the bridge at the top: `virsh net-list` and `ip link` say what this "
            "host has.",
            "Run it as root on the KVM host. It defines the machine, makes the disk and "
            "starts the installer on the serial console.",
            "Install: no desktop, ssh on. `virsh console {name}` gets back to it.",
            "Back here, Enroll node mints a token; run the provision command it gives "
            "you on the VM, as root.",
        ],
    },
    "qemu": {
        "label": "QEMU (no manager)", "vetted": "",
        "file": "vm/qemu.sh", "artifact": "shell script", "lang": "sh",
        "mac_prefix": "52:54:00", "wants": ("uuid", "mac"),
        "steps": [
            "Check the two OVMF paths at the top: they differ between distributions.",
            "Run it as a user who can reach /dev/kvm. It makes the disk, copies the UEFI "
            "variables and boots the installer on this terminal.",
            "The network is user-mode, which is the one thing to change for real use: it "
            "reaches out but nothing reaches in. Swap it for a bridge, or keep the "
            "forwarded port for ssh.",
            "Back here, Enroll node mints a token; run the provision command it gives "
            "you on the VM, as root.",
        ],
    },
    "vmware": {
        "label": "VMware (Workstation, Fusion, ESXi)", "vetted": "",
        "file": "vm/vmware.vmx", "artifact": "VMX file", "lang": "ini",
        "mac_prefix": "00:50:56", "wants": ("uuid", "mac"),
        "steps": [
            "Make a folder for it and save this as {name}.vmx inside.",
            "Make the disk beside it: `vmware-vdiskmanager -c -s {disk_gb}GB -a lsilogic "
            "-t 1 {name}.vmdk`, or add one in the UI after opening the file.",
            "Open the .vmx and install: no desktop, ssh on.",
            "Back here, Enroll node mints a token; run the provision command it gives "
            "you on the VM, as root.",
        ],
    },
    "hyperv": {
        "label": "Hyper-V", "vetted": "",
        "file": "vm/hyperv.ps1", "artifact": "PowerShell script", "lang": "ps",
        "mac_prefix": "00:15:5D", "wants": ("mac",),
        "steps": [
            "Check the switch name at the top: `Get-VMSwitch` names them, and Default "
            "Switch is NAT rather than your LAN.",
            "Run it in an elevated PowerShell on the host.",
            "Connect to the VM and install: no desktop, ssh on. Secure Boot is off "
            "already, which is what lets a Linux installer start.",
            "Back here, Enroll node mints a token; run the provision command it gives "
            "you on the VM, as root.",
        ],
    },
    "virtualbox": {
        "label": "VirtualBox", "vetted": "",
        "file": "vm/virtualbox.sh", "artifact": "shell script", "lang": "sh",
        "mac_prefix": "08:00:27", "wants": ("uuid", "mac"),
        "steps": [
            "Check the bridge at the top: `VBoxManage list bridgedifs` names the host's "
            "interfaces.",
            "Run it as the user the VMs belong to. It creates the machine, the disk and "
            "starts it headless.",
            "Install over the console (`VBoxManage controlvm {name} screenshotpng`, or "
            "attach the GUI): no desktop, ssh on.",
            "Back here, Enroll node mints a token; run the provision command it gives "
            "you on the VM, as root.",
        ],
    },
}
DEFAULT_HV = "unraid"

# What Unraid calls things. The domain directory and the ISO share are its
# defaults, and a VM made in Form view has its vdisk in the first.
DOMAINS = "/mnt/user/domains"
ISOS = "/mnt/user/isos"

# A VM name is a directory under DOMAINS and a libvirt domain name, so it
# gets the strict charset both are happy with rather than a quoting rule.
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
# ...and an ISO is a file IN the ISO share, never a path into somewhere else.
ISO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,119}\.iso")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
MAC_RE = re.compile(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}")

CORES = (1, 64)
MEM_GB = (1, 512)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def mac(prefix="52:54:00"):
    """A MAC in the range this hypervisor accepts, with three bytes of its
    own. The prefix is not decoration: VMware refuses a static address
    outside 00:50:56:00-3F, and Hyper-V and VirtualBox each hand out their
    own, so a machine wearing somebody else's is the one that collides."""
    lo = 0x3F if prefix == "00:50:56" else 0xFF     # VMware's manual range
    return "%s:%02x:%02x:%02x" % (prefix, random.randrange(lo + 1),
                                  random.randrange(256), random.randrange(256))


def defaults(hv=DEFAULT_HV):
    """What the dialog opens on: the machine the template describes, with an
    identity minted here: right for a VM that does not exist yet, and
    replaced by the manager's own when it already made one."""
    spec = HYPERVISORS.get(hv) or HYPERVISORS[DEFAULT_HV]
    return {"name": "bb-sandbox", "cores": 6, "memory_gb": 16, "disk_gb": 200,
            "iso": "ubuntu-26.04-live-server-amd64.iso", "vmid": 9000,
            "uuid": str(uuid.uuid4()), "mac": mac(spec["mac_prefix"])}


def catalog():
    """What the dialog's picker offers: every hypervisor, with what each one
    hands back and which fields it takes.

    ALPHABETICAL by label, not the order they were written in (this box's own
    hypervisor first, then whatever was added next), which only the person
    who wrote it could predict.
    """
    return sorted(
        [{"id": k, "label": v["label"], "artifact": v["artifact"],
          "lang": v["lang"], "wants": list(v["wants"]),
          "mac_prefix": v["mac_prefix"], "dev": not v.get("vetted")}
         for k, v in HYPERVISORS.items() if allowed(v)],
        key=lambda h: h["label"].lower())


def allowed(v):
    """May this hypervisor be offered and rendered: vetted, or unvetted
    with the setting on."""
    return bool(v.get("vetted")) or bool(unvetted_ok and unvetted_ok())


def render(name="", cores=None, memory_gb=None, iso="", uid="", hw="",
           hv=DEFAULT_HV, disk_gb=None, vmid=None):
    """{text, name, uuid, mac, ...} for a new VM, or {error}.

    Every value is checked before it becomes the artifact rather than escaped
    and hoped for: this is a file the operator pastes into a hypervisor or a
    script they run as root, and a name that is not a name has nowhere
    sensible to end up.
    """
    hv = str(hv or DEFAULT_HV)
    spec = HYPERVISORS.get(hv)
    if spec and not allowed(spec):
        return {"error": f"{spec['label']} is dev, not yet vetted, so it is not offered here: "
                         "Debug settings on the Settings tab, 'Offer dev features' puts it back, tagged dev"}
    if not spec:
        return {"error": f"no template for {hv}; "
                         f"{', '.join(HYPERVISORS)} are the ones here"}
    d = defaults(hv)
    name = str(name or d["name"]).strip()
    iso = str(iso or d["iso"]).strip()
    if not NAME_RE.fullmatch(name):
        return {"error": "a name is letters, digits, dot, dash or underscore: "
                         "it is the domain's name and its folder under /mnt/user/domains"}
    if not ISO_RE.fullmatch(iso):
        return {"error": f"the installer is a file name ending .iso, in {ISOS}, not a path"}
    uid = str(uid or "").strip().lower() or str(uuid.uuid4())
    # Lowercased after minting, not before: the table writes 00:15:5D the
    # way the vendor does, and the comparison below is on the value.
    hw = (str(hw or "").strip() or mac(spec["mac_prefix"])).lower()
    if not UUID_RE.fullmatch(uid):
        return {"error": "a uuid is 8-4-4-4-12 hex digits; Unraid shows the VM's on its "
                         "edit page, and leaving this blank mints one"}
    if not MAC_RE.fullmatch(hw):
        return {"error": "a MAC is six hex pairs separated by colons"}
    # The prefix is the manager's, not a preference: an address outside its
    # range is refused (VMware), quietly replaced (Hyper-V), or collides with
    # the next machine it hands one to.
    if not hw.startswith(spec["mac_prefix"].lower()):
        return {"error": f"{spec['label']} takes a MAC in {spec['mac_prefix']}:xx:xx:xx; "
                         "leaving it blank mints one in range"}
    try:
        disk_gb = int(disk_gb) if disk_gb not in (None, "") else d["disk_gb"]
        vmid = int(vmid) if vmid not in (None, "") else d["vmid"]
    except (TypeError, ValueError):
        return {"error": "the disk size and the VM id are whole numbers"}
    if not 8 <= disk_gb <= 8192:
        return {"error": "the disk is between 8 and 8192 GiB"}
    if not 100 <= vmid <= 999999999:
        return {"error": "a Proxmox VM id is a number from 100 up"}
    try:
        cores = int(cores) if cores not in (None, "") else d["cores"]
        memory_gb = int(memory_gb) if memory_gb not in (None, "") else d["memory_gb"]
    except (TypeError, ValueError):
        return {"error": "cores and memory are whole numbers"}
    if not CORES[0] <= cores <= CORES[1]:
        return {"error": f"cores is between {CORES[0]} and {CORES[1]}"}
    if not MEM_GB[0] <= memory_gb <= MEM_GB[1]:
        return {"error": f"memory is between {MEM_GB[0]} and {MEM_GB[1]} GiB"}
    src = Path(__file__).resolve().parents[2] / "nodes" / spec["file"]
    try:
        text = src.read_text(encoding="utf-8")
    except OSError as e:
        return {"error": f"the shipped machine could not be read ({src}): {e}"}

    disk_dir = f"{DOMAINS}/{name}"
    fields = {
        "name": name, "uuid": uid, "mac": hw,
        # Two managers take a MAC with no separators, and one wants its own
        # id format: rendered here rather than in six templates.
        "mac_plain": hw.replace(":", "").upper(),
        "uuid_vmware": " ".join(uid.replace("-", "")[i:i + 2]
                                for i in range(0, 32, 2)).strip(),
        "cores": cores, "memory_mb": memory_gb * 1024, "memory_gb": memory_gb,
        "disk_gb": disk_gb, "disk_mb": disk_gb * 1024, "vmid": vmid,
        "iso": iso, "iso_path": f"{ISOS}/{iso}",
        "disk_dir": disk_dir, "disk_path": f"{disk_dir}/{name}.qcow2",
    }
    if hv == "unraid":
        r = _unraid(text, fields, memory_gb * 1024 * 1024)
        if r.get("error"):
            return r
        text = r["text"]
    else:
        # A template with placeholders, and every one of them filled: a
        # `${something}` left in a script somebody is about to run as root is
        # worse than a refusal saying which.
        text = string.Template(text).safe_substitute(
            {k: str(v) for k, v in fields.items()})
        left = re.findall(r"\$\{([a-z_]+)\}", text)
        if left:
            return {"error": f"{spec['file']} asks for {', '.join(sorted(set(left)))}, "
                             "which this does not know how to fill in"}
    return {"text": text, "hv": hv, "label": spec["label"],
            "artifact": spec["artifact"], "lang": spec["lang"],
            "steps": [str(x).format(**fields) for x in spec["steps"]],
            "disk_gb": disk_gb, "vmid": vmid, "name": name, "uuid": uid, "mac": hw,
            "cores": cores, "memory_gb": memory_gb,
            "disk": fields["disk_path"], "iso_file": iso}


def _unraid(text, f, kib):
    """The Unraid machine, rewritten in place rather than filled in.

    That file is a real domain anybody can paste as it stands (the docs
    point at it and its comments carry the reasoning), so it holds values,
    not placeholders, and this replaces the ones that belong to one machine.
    """
    # Comments first: what follows rewrites values inside elements, and a
    # comment that mentions one would otherwise be rewritten too.
    text = re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    subs = [
        (r"<uuid>[^<]*</uuid>", f"<uuid>{f['uuid']}</uuid>"),
        (r"<nvram>[^<]*</nvram>",
         f"<nvram>/etc/libvirt/qemu/nvram/{f['uuid']}_VARS-pure-efi.fd</nvram>"),
        (r"<name>[^<]*</name>", f"<name>{_esc(f['name'])}</name>"),
        (r'<mac address="[^"]*"/>', f'<mac address="{f["mac"]}"/>'),
        (r'<source file="/mnt/user/domains/[^"]*"/>',
         f'<source file="{DOMAINS}/{_esc(f["name"])}/vdisk1.qcow2"/>'),
        (r'<source file="/mnt/user/isos/[^"]*"/>',
         f'<source file="{ISOS}/{_esc(f["iso"])}"/>'),
        (r'<memory unit="KiB">\d+</memory>', f'<memory unit="KiB">{kib}</memory>'),
        (r'<currentMemory unit="KiB">\d+</currentMemory>',
         f'<currentMemory unit="KiB">{kib}</currentMemory>'),
        (r'<vcpu placement="static">\d+</vcpu>',
         f'<vcpu placement="static">{f["cores"]}</vcpu>'),
        # libvirt refuses a machine whose sockets x cores x threads is not
        # its vcpu count ("CPU topology doesn't match maximum vcpu count",
        # measured on Unraid with 4 vCPUs, 15 Sep): the topology moves with
        # the count, one socket, no threads, so the product is the count.
        (r'<topology sockets="\d+" cores="\d+" threads="\d+"/>',
         f'<topology sockets="1" cores="{f["cores"]}" threads="1"/>'),
    ]
    for pat, to in subs:
        text, n = re.subn(pat, to, text, count=1)
        if not n:
            return {"error": f"the shipped machine has no {pat.split('[')[0].strip('<>')} "
                             "to fill in; nodes/unraid-vm.xml has moved under this"}
    return {"text": text}
