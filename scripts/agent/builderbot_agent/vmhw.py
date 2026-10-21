"""A VM's hardware beyond its size (R100): CPU pinning, a memory ceiling it
may balloon to, its network, a project folder shared in by virtiofs, and
devices passed through from the host (USB, PCI, a GPU with its vBIOS).

A VM's hardware is one record, `hw`, applied to its libvirt XML at New VM and
on a stopped VM alike, so the two can never disagree. Everything in it is
checked against its shape here before it reaches the XML; who may ask for
what (a passthrough is an administrator's) is the controller's to decide.
"""
import base64
import glob
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

PCI_RE = re.compile(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]")
USB_ID_RE = re.compile(r"0x[0-9a-f]{4}")
TAG_RE = re.compile(r"[a-z][a-z0-9_-]{0,30}")
VBIOS_DIR = "vbios"
MAX_CPUS = 512


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def _cpulist(text):
    """'0-3,8' as [0, 1, 2, 3, 8]."""
    out = []
    for part in str(text or "").split(","):
        a, _, b = part.strip().partition("-")
        if a.isdigit():
            out += list(range(int(a), int(b) + 1)) if b.isdigit() else [int(a)]
    return out[:MAX_CPUS]


def host_hw(sys_root="/sys"):
    """What a VM here could be given, for the census: the CPU threads in
    their core pairs (as Unraid draws them), the USB devices, the PCI devices
    with their IOMMU group and the driver that has them, and whether the
    IOMMU is on (without it no PCI device is passed through)."""
    pairs, seen = [], set()
    for d in sorted(glob.glob(f"{sys_root}/devices/system/cpu/cpu[0-9]*"), key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)))):
        sib = tuple(_cpulist(_read(f"{d}/topology/thread_siblings_list")))
        if sib and sib not in seen:
            seen.add(sib)
            pairs.append(list(sib))
    usb = []
    for d in sorted(glob.glob(f"{sys_root}/bus/usb/devices/*")):
        v, p = _read(f"{d}/idVendor"), _read(f"{d}/idProduct")
        if not (v and p) or _read(f"{d}/bDeviceClass") == "09":     # hubs are the host's own
            continue
        name = " ".join(x for x in (_read(f"{d}/manufacturer"), _read(f"{d}/product")) if x)[:80]
        usb.append({"vendor": "0x" + v.lower(), "product": "0x" + p.lower(), "name": name or f"{v}:{p}"})
    pci = []
    groups = glob.glob(f"{sys_root}/kernel/iommu_groups/*")
    for d in sorted(glob.glob(f"{sys_root}/bus/pci/devices/*")):
        addr = os.path.basename(d)
        cls = _read(f"{d}/class")
        # Displays, sound, USB and network controllers, storage: what a person
        # passes through; bridges and the host's own plumbing are left out.
        if not cls.startswith(("0x03", "0x04", "0x0c03", "0x02", "0x01")):
            continue
        link = f"{d}/iommu_group"
        drv = f"{d}/driver"
        pci.append({"addr": addr, "class": cls[:8], "vendor": _read(f"{d}/vendor"), "device": _read(f"{d}/device"),
                    "group": os.path.basename(os.readlink(link)) if os.path.islink(link) else "",
                    "driver": os.path.basename(os.readlink(drv)) if os.path.islink(drv) else ""})
    return {"cpus": pairs[:256], "usb": usb[:64], "pci": pci[:64], "iommu": bool(groups)}


def clean(hw, vcpus, mem_mb):
    """The record as it may be applied, or (None, why)."""
    hw = hw if isinstance(hw, dict) else {}
    out = {}
    if hw.get("cpuset") is not None:
        # An empty set is unpinned: the host schedules it as it likes.
        out["cpuset"] = sorted({int(c) for c in hw["cpuset"] if str(c).isdigit()})[:MAX_CPUS]
    if hw.get("mem_max_mb") not in (None, ""):
        try:
            mx = int(hw["mem_max_mb"])
        except (TypeError, ValueError):
            return None, "the memory ceiling is a whole number of MB"
        if mx < mem_mb:
            return None, f"the memory ceiling ({mx} MB) is under what it starts with ({mem_mb} MB)"
        out["mem_max_mb"] = mx
    if hw.get("net") is not None:
        if hw["net"] not in ("project", "lan"):
            return None, "a VM's network is its project's or the LAN"
        out["net"] = hw["net"]
    if hw.get("share") is not None:
        sh = hw["share"] if isinstance(hw["share"], dict) else {}
        if sh:
            path = os.path.normpath(str(sh.get("path") or ""))
            if not path.startswith("/workspace/") or ".." in path.split("/"):
                return None, "a shared folder is one of the project's own, under /workspace"
            tag = str(sh.get("tag") or "project")
            if not TAG_RE.fullmatch(tag):
                return None, "a shared folder's tag is a short lowercase name"
            out["share"] = {"path": path, "tag": tag, "ro": sh.get("ro") is True}
        else:
            out["share"] = {}
    if hw.get("devices") is not None:
        devs = []
        for d in hw["devices"][:8] if isinstance(hw["devices"], list) else []:
            if not isinstance(d, dict):
                continue
            if d.get("type") == "usb" and USB_ID_RE.fullmatch(str(d.get("vendor"))) and USB_ID_RE.fullmatch(str(d.get("product"))):
                devs.append({"type": "usb", "vendor": d["vendor"], "product": d["product"]})
            elif d.get("type") == "pci" and PCI_RE.fullmatch(str(d.get("addr"))):
                rom = str(d.get("rom") or "")
                devs.append({"type": "pci", "addr": d["addr"], **({"rom": rom} if re.fullmatch(r"[0-9a-f.-]+\.rom", rom) else {})})
            else:
                return None, f"not a device this takes: {str(d)[:80]}"
        out["devices"] = devs
    return out, ""


def _pci_parts(addr):
    dom, bus, rest = addr.split(":")
    slot, fn = rest.split(".")
    return {"domain": "0x" + dom, "bus": "0x" + bus, "slot": "0x" + slot, "function": "0x" + fn}


def _need(parent, tag):
    """A child the domain's XML must have; a domain without it is not one
    this made, and is refused by name rather than half edited."""
    el = parent.find(tag)
    if el is None:
        raise ValueError(f"the domain's XML has no <{tag}>")
    return el


def virtiofsd():
    """Where virtiofsd is, which a shared folder needs, or "": on the PATH
    on some systems, in libexec or qemu's own folder on others."""
    return shutil.which("virtiofsd") or next((p for p in ("/usr/libexec/virtiofsd", "/usr/lib/qemu/virtiofsd")
                                              if os.path.exists(p)), "")


def rom_name(addr):
    """The file a PCI card's dumped vBIOS is kept in, under VBIOS_DIR."""
    return addr.replace(":", "-") + ".rom"


def apply(xml, hw, vcpus, mem_mb, lan="", network="", vbios_dir=""):
    """The domain's XML with `hw` in it: each key given replaces what the XML
    had of it, each left out keeps it."""
    ET.register_namespace("bb", "https://builderbot.dev/vm/1")
    root = ET.fromstring(xml)
    dev, vcpu_el, mem_el = _need(root, "devices"), _need(root, "vcpu"), _need(root, "memory")
    if "cpuset" in hw:
        for old in root.findall("cputune"):
            root.remove(old)
        if hw["cpuset"]:
            tune = ET.Element("cputune")
            for i in range(vcpus):
                ET.SubElement(tune, "vcpupin", vcpu=str(i), cpuset=str(hw["cpuset"][i % len(hw["cpuset"])]))
            root.insert(list(root).index(vcpu_el) + 1, tune)
    if "mem_max_mb" in hw:
        mem_el.set("unit", "MiB")
        mem_el.text = str(hw["mem_max_mb"])
        cur = root.find("currentMemory")
        if cur is None:
            cur = ET.Element("currentMemory", unit="MiB")
            root.insert(list(root).index(mem_el) + 1, cur)
        cur.set("unit", "MiB")
        cur.text = str(mem_mb)
        for old in dev.findall("memballoon"):
            dev.remove(old)
        ET.SubElement(dev, "memballoon", model="virtio")
    if "net" in hw:
        nic = dev.find("interface")
        mac = nic.find("mac") if nic is not None else None
        new = ET.Element("interface", type="direct" if hw["net"] == "lan" else "network")
        if mac is not None:
            new.append(mac)
        if hw["net"] == "lan":
            ET.SubElement(new, "source", dev=lan, mode="bridge")
        else:
            ET.SubElement(new, "source", network=network)
        ET.SubElement(new, "model", type="virtio")
        if nic is not None:
            dev.insert(list(dev).index(nic), new)
            dev.remove(nic)
        else:
            dev.append(new)
    if "share" in hw:
        for old in dev.findall("filesystem"):
            dev.remove(old)
        for old in root.findall("memoryBacking"):
            root.remove(old)
        if hw["share"]:
            # virtiofs wants the guest's memory shared with virtiofsd.
            mb = ET.Element("memoryBacking")
            ET.SubElement(mb, "source", type="memfd")
            ET.SubElement(mb, "access", mode="shared")
            root.insert(list(root).index(vcpu_el), mb)
            fs = ET.SubElement(dev, "filesystem", type="mount", accessmode="passthrough")
            ET.SubElement(fs, "driver", type="virtiofs")
            ET.SubElement(fs, "source", dir=hw["share"]["path"])
            ET.SubElement(fs, "target", dir=hw["share"]["tag"])
            if hw["share"]["ro"]:
                ET.SubElement(fs, "readonly")
    if "devices" in hw:
        for old in dev.findall("hostdev"):
            dev.remove(old)
        for d in hw["devices"]:
            if d["type"] == "usb":
                h = ET.SubElement(dev, "hostdev", mode="subsystem", type="usb", managed="yes")
                src = ET.SubElement(h, "source")
                ET.SubElement(src, "vendor", id=d["vendor"])
                ET.SubElement(src, "product", id=d["product"])
            else:
                h = ET.SubElement(dev, "hostdev", mode="subsystem", type="pci", managed="yes")
                src = ET.SubElement(h, "source")
                ET.SubElement(src, "address", **_pci_parts(d["addr"]))
                # The card's dumped vBIOS when it has one, as Unraid's
                # passthrough wants: named for it or as dumped here.
                rom = d.get("rom") or rom_name(d["addr"])
                if vbios_dir and (d.get("rom") or os.path.isfile(os.path.join(vbios_dir, rom))):
                    ET.SubElement(h, "rom", file=os.path.join(vbios_dir, rom))
    return ET.tostring(root, encoding="unicode")


def read(xml):
    """What a domain's XML says of its hardware, for the census and the
    Hardware dialog's starting values."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return {}
    out = {}
    pins = sorted({int(str(p.get("cpuset"))) for p in root.findall("cputune/vcpupin") if str(p.get("cpuset") or "").isdigit()})
    out["cpuset"] = pins
    mem, cur = root.find("memory"), root.find("currentMemory")
    if mem is not None and cur is not None and mem.text and cur.text and mem.text != cur.text:
        unit = 1024 if (mem.get("unit") or "KiB") in ("KiB", "k") else 1
        out["mem_max_mb"] = int(mem.text) // unit
    nic = root.find("devices/interface")
    out["net"] = "lan" if nic is not None and nic.get("type") == "direct" else "project"
    fs = root.find("devices/filesystem")
    if fs is not None and fs.find("source") is not None:
        out["share"] = {"path": fs.find("source").get("dir") or "", "tag": (fs.find("target").get("dir") if fs.find("target") is not None else ""),
                        "ro": fs.find("readonly") is not None}
    devs = []
    for h in root.findall("devices/hostdev"):
        if h.get("type") == "usb":
            v, p = h.find("source/vendor"), h.find("source/product")
            if v is not None and p is not None:
                devs.append({"type": "usb", "vendor": v.get("id"), "product": p.get("id")})
        elif h.get("type") == "pci":
            a = h.find("source/address")
            if a is not None:
                devs.append({"type": "pci", "addr": "%s:%s:%s.%s" % tuple(str(a.get(k) or "0x0")[2:].zfill(w) for k, w in
                                                                         (("domain", 4), ("bus", 2), ("slot", 2), ("function", 1)))})
    out["devices"] = devs
    return out


def vbios_keep(addr, b64, out_dir, say):
    """A .rom given for the card at `addr` instead of dumped, kept where a
    dump would be, so its VM's hostdev carries it. Returns its name or "".
    """
    try:
        data = base64.b64decode(b64, validate=True)
    except ValueError:
        data = b""
    if not PCI_RE.fullmatch(addr) or not 2_000 <= len(data) <= 2 * 1024 * 1024 or data[:2] != b"\x55\xaa":
        say("refused: not a vBIOS for a PCI address (an option ROM starts 55 AA and is 2 KB to 2 MB)\n")
        return ""
    os.makedirs(out_dir, exist_ok=True)
    name = rom_name(addr)
    with open(os.path.join(out_dir, name), "wb") as f:
        f.write(data)
    say(f"{name}: {len(data) // 1024} KB, given on the VMs page\n")
    return name


def vbios_dump(addr, out_dir, say, sys_root="/sys"):
    """A GPU's vBIOS read through sysfs, as SpaceinvaderOne's script for
    Unraid does it: the VGA function only; a throwaway domain started and
    destroyed with the card in it to wake its ROM when the first read comes
    back short; kept under the VM host's own folder by its PCI address.
    Root's. Returns the file's name, or "" with why said."""
    if not PCI_RE.fullmatch(addr):
        say(f"refused: {addr} is not a PCI address\n")
        return ""
    d = f"{sys_root}/bus/pci/devices/{addr}"
    if not _read(f"{d}/class").startswith("0x0300"):
        say(f"refused: {addr} is not a GPU's display function (VGA); a card's audio or USB part has no vBIOS\n")
        return ""
    os.makedirs(out_dir, exist_ok=True)
    name = rom_name(addr)
    dest = os.path.join(out_dir, name)

    def read_rom():
        try:
            with open(f"{d}/rom", "w") as f:
                f.write("1")
            with open(f"{d}/rom", "rb") as f:
                data = f.read()
        except OSError as e:
            say(f"the ROM did not read: {e}\n")
            data = b""
        finally:
            try:
                with open(f"{d}/rom", "w") as f:
                    f.write("0")
            except OSError:
                pass
        return data

    data = read_rom()
    if len(data) < 70_000:
        # A card the host booted on keeps its ROM shadowed until a guest has
        # had it once: a domain with the card in it, started and destroyed.
        say("the first read was short: waking the card with a throwaway VM, then reading again\n")
        tmp = "bbvm-vbios-wake"
        xml = (f"<domain type='kvm'><name>{tmp}</name><memory unit='MiB'>256</memory><vcpu>1</vcpu>"
               "<os><type arch='x86_64' machine='q35'>hvm</type></os><devices>"
               f"<hostdev mode='subsystem' type='pci' managed='yes'><source><address "
               + " ".join(f"{k}='{v}'" for k, v in _pci_parts(addr).items()) + "/></source></hostdev></devices></domain>")
        path = os.path.join(out_dir, tmp + ".xml")
        with open(path, "w") as f:
            f.write(xml)
        virsh = ["virsh", "-c", "qemu:///system"]
        subprocess.run(virsh + ["define", path], capture_output=True, check=False)
        subprocess.run(virsh + ["start", tmp], capture_output=True, check=False)
        time.sleep(9)
        subprocess.run(virsh + ["destroy", tmp], capture_output=True, check=False)
        subprocess.run(virsh + ["undefine", tmp], capture_output=True, check=False)
        os.unlink(path)
        data = read_rom()
    if len(data) < 2_000:
        say("no vBIOS came back: the card may need binding to vfio-pci at boot first, or it is the one the "
            "host's own screen uses; a .rom from the card's maker (or TechPowerUp's collection) can be given instead\n")
        return ""
    with open(dest, "wb") as f:
        f.write(data)
    say(f"{name}: {len(data) // 1024} KB{', which is small for a vBIOS: try it, and give a .rom instead if the VM shows nothing' if len(data) < 70_000 else ''}\n")
    return name
