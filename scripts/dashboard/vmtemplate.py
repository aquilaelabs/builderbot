#!/usr/bin/env python3
"""The Unraid domain XML for a new sandbox VM, with this one's identity in it.

`nodes/unraid-vm.xml` is the machine — q35, shared memory backing, a virtio
rng, sizes for something that compiles — and it is one file for every
distribution. What it cannot be is a template you paste twice: three fields
in it belong to ONE virtual machine, and a second VM wearing them is a
second VM pointing at the first one's OVMF nvram file and answering to its
MAC on the network.

So this renders that file rather than copying it: a UUID, the nvram path
named after that UUID (Unraid names it that way and libvirt writes it
there), a MAC on QEMU's own 52:54:00 prefix, and the name the operator gave,
which is also the domain directory their vdisk lives in. Nothing else about
the machine moves — the reasoning in the file's comments is the reasoning
here.

Both identities are GIVEN as well as generated, and that is the whole of the
sequencing problem. Unraid mints its own pair when the VM is created in Form
view: the nvram file on disk is named after its UUID, and any DHCP
reservation was made against its MAC. So a fresh pair is right for a machine
that does not exist yet, and Unraid's pair is right the moment it does —
pasting them in is what keeps the firmware variables and the address the
ones already set up.

The comments themselves are stripped from what comes back. They are for
whoever reads the repository; Unraid drops them the moment the VM is saved,
and 130 lines of them in a paste box is 130 lines to scroll past.
"""
import random
import re
import uuid
from pathlib import Path

# The shipped machine. Two directories up from this module is the repo root
# in a checkout and /opt/builderbot in the image, so one expression finds it
# in both — which is what `bb dashboard dev` needs to serve the checkout's.
TEMPLATE = Path(__file__).resolve().parents[2] / "nodes" / "unraid-vm.xml"

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


def mac():
    """A locally administered MAC on QEMU's prefix, which is what Unraid
    hands a VM it makes: 52:54:00 and three bytes of its own."""
    return "52:54:00:%02x:%02x:%02x" % tuple(random.randrange(256) for _ in range(3))


def defaults():
    """What the dialog opens on: the machine the template describes, with an
    identity minted here — right for a VM that does not exist yet, and
    replaced by Unraid's when it does."""
    return {"name": "bb-sandbox", "cores": 6, "memory_gb": 16, "disk_gb": 200,
            "iso": "ubuntu-26.04-live-server-amd64.iso",
            "uuid": str(uuid.uuid4()), "mac": mac()}


def render(name="", cores=None, memory_gb=None, iso="", uid="", hw=""):
    """{xml, name, uuid, mac, ...} for a new VM, or {error}.

    Every value is checked before it becomes XML rather than escaped and
    hoped for: this is a file the operator pastes into a hypervisor, and a
    name that is not a name has nowhere sensible to end up.
    """
    d = defaults()
    name = str(name or d["name"]).strip()
    iso = str(iso or d["iso"]).strip()
    if not NAME_RE.fullmatch(name):
        return {"error": "a name is letters, digits, dot, dash or underscore — "
                         "it is the domain's name and its folder under /mnt/user/domains"}
    if not ISO_RE.fullmatch(iso):
        return {"error": f"the installer is a file name ending .iso, in {ISOS} — not a path"}
    uid = str(uid or "").strip().lower() or str(uuid.uuid4())
    hw = str(hw or "").strip().lower() or mac()
    if not UUID_RE.fullmatch(uid):
        return {"error": "a uuid is 8-4-4-4-12 hex digits — Unraid shows the VM's on its "
                         "edit page, and leaving this blank mints one"}
    if not MAC_RE.fullmatch(hw):
        return {"error": "a MAC is six hex pairs separated by colons"}
    try:
        cores = int(cores) if cores not in (None, "") else d["cores"]
        memory_gb = int(memory_gb) if memory_gb not in (None, "") else d["memory_gb"]
    except (TypeError, ValueError):
        return {"error": "cores and memory are whole numbers"}
    if not CORES[0] <= cores <= CORES[1]:
        return {"error": f"cores is between {CORES[0]} and {CORES[1]}"}
    if not MEM_GB[0] <= memory_gb <= MEM_GB[1]:
        return {"error": f"memory is between {MEM_GB[0]} and {MEM_GB[1]} GiB"}
    try:
        xml = TEMPLATE.read_text(encoding="utf-8")
    except OSError as e:
        return {"error": f"the shipped machine could not be read ({TEMPLATE}): {e}"}

    kib = memory_gb * 1024 * 1024
    # Comments first: what follows rewrites values inside elements, and a
    # comment that mentions one would otherwise be rewritten too.
    xml = re.sub(r"<!--.*?-->\n?", "", xml, flags=re.S)
    xml = re.sub(r"\n{3,}", "\n\n", xml).strip() + "\n"
    subs = [
        (r"<uuid>[^<]*</uuid>", f"<uuid>{uid}</uuid>"),
        (r"<nvram>[^<]*</nvram>",
         f"<nvram>/etc/libvirt/qemu/nvram/{uid}_VARS-pure-efi.fd</nvram>"),
        (r"<name>[^<]*</name>", f"<name>{_esc(name)}</name>"),
        (r'<mac address="[^"]*"/>', f'<mac address="{hw}"/>'),
        (r'<source file="/mnt/user/domains/[^"]*"/>',
         f'<source file="{DOMAINS}/{_esc(name)}/vdisk1.qcow2"/>'),
        (r'<source file="/mnt/user/isos/[^"]*"/>',
         f'<source file="{ISOS}/{_esc(iso)}"/>'),
        (r'<memory unit="KiB">\d+</memory>', f'<memory unit="KiB">{kib}</memory>'),
        (r'<currentMemory unit="KiB">\d+</currentMemory>',
         f'<currentMemory unit="KiB">{kib}</currentMemory>'),
        (r'<vcpu placement="static">\d+</vcpu>',
         f'<vcpu placement="static">{cores}</vcpu>'),
    ]
    for pat, to in subs:
        xml, n = re.subn(pat, to, xml, count=1)
        if not n:
            return {"error": f"the shipped machine has no {pat.split('[')[0].strip('<>')} "
                             "to fill in — nodes/unraid-vm.xml has moved under this"}
    return {"xml": xml, "name": name, "uuid": uid, "mac": hw,
            "cores": cores, "memory_gb": memory_gb,
            "disk": f"{DOMAINS}/{name}/vdisk1.qcow2", "iso": f"{ISOS}/{iso}"}
