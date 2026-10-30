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
import xml.etree.ElementTree as ET  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml (libvirt's own XML from virsh on this node; and ElementTree resolves no external entity)

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
    their core pairs (as a hypervisor's form draws them), the USB devices, the PCI devices
    with their IOMMU group and the driver that has them, and whether the
    IOMMU is on (without it no PCI device is passed through)."""
    pairs, seen = [], set()
    for d in sorted(glob.glob(f"{sys_root}/devices/system/cpu/cpu[0-9]*"), key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)))):
        sib = tuple(_cpulist(_read(f"{d}/topology/thread_siblings_list")))
        if sib and sib not in seen:
            seen.add(sib)
            pairs.append(list(sib))
    usb = []
    mounts = _mounts()
    for d in sorted(glob.glob(f"{sys_root}/bus/usb/devices/*")):
        v, p = _read(f"{d}/idVendor"), _read(f"{d}/idProduct")
        if not (v and p) or _read(f"{d}/bDeviceClass") == "09":     # hubs are the host's own
            continue
        name = " ".join(x for x in (_read(f"{d}/manufacturer"), _read(f"{d}/product")) if x)[:80]
        # What names it again after a replug or a reboot (R116): its serial,
        # and its port (bus-port.port, the physical socket) when two are
        # alike; and what the host does with it, which a Give refuses on.
        port = os.path.basename(d)
        ifaces = glob.glob(f"{d}/{port}:*")
        drivers = sorted({os.path.basename(os.readlink(f"{i}/driver")) for i in ifaces if os.path.islink(f"{i}/driver")})
        disks = sorted(os.path.basename(b) for i in ifaces for b in glob.glob(f"{i}/host*/target*/*/block/*"))
        real = os.path.realpath(d)
        ctl = next((part for part in real.split("/") if PCI_RE.fullmatch(part)), "")
        usb.append({"vendor": "0x" + v.lower(), "product": "0x" + p.lower(), "name": name or f"{v}:{p}",
                    "serial": _read(f"{d}/serial")[:64], "port": port,
                    "bus": int(_read(f"{d}/busnum") or 0), "dev": int(_read(f"{d}/devnum") or 0),
                    "speed": _read(f"{d}/speed"), "driver": ",".join(drivers)[:60], "ctl": ctl,
                    "use": _usb_use(disks, mounts, sys_root)})
    pci = []
    groups = glob.glob(f"{sys_root}/kernel/iommu_groups/*")
    lan = _lan_pci(sys_root)
    for d in sorted(glob.glob(f"{sys_root}/bus/pci/devices/*")):
        addr = os.path.basename(d)
        cls = _read(f"{d}/class")
        # Displays, sound, USB and network controllers, storage: what a person
        # passes through; bridges and the host's own plumbing are left out.
        if not cls.startswith(("0x03", "0x04", "0x0c03", "0x02", "0x01")):
            continue
        link = f"{d}/iommu_group"
        drv = f"{d}/driver"
        # What the host itself needs of it (R116 step 4): the interface its
        # default route leaves by, a storage controller with a mounted disk
        # behind it, the USB controller a device the host uses hangs off.
        host = ""
        if addr == lan:
            host = "the host's LAN interface"
        elif cls.startswith("0x01"):
            held = [u for u in _pci_disks(d, mounts) if u]
            host = held[0] if held else ""
        elif cls.startswith("0x0c03"):
            held = [u["use"][0] for u in usb if u["ctl"] == addr and u["use"]]
            host = held[0] if held else ""
        pci.append({"addr": addr, "class": cls[:8], "vendor": _read(f"{d}/vendor"), "device": _read(f"{d}/device"),
                    "group": os.path.basename(os.readlink(link)) if os.path.islink(link) else "",
                    "driver": os.path.basename(os.readlink(drv)) if os.path.islink(drv) else "", "host": host})
    return {"cpus": pairs[:256], "usb": usb[:64], "pci": pci[:64], "iommu": bool(groups)}


def _mounts():
    """What is mounted where, by device, with the swap devices."""
    out = {}
    for path, col in (("/proc/mounts", 1), ("/proc/swaps", -1)):
        try:
            with open(path) as f:
                for line in f.read().splitlines()[1 if col < 0 else 0:]:
                    p = line.split()
                    if len(p) > 1 and p[0].startswith("/dev/"):
                        out.setdefault(os.path.realpath(p[0]), p[col] if col > 0 else "swap")
        except OSError:
            pass
    return out


def _disk_use(dk, mounts, sys_root="/sys"):
    """How the host uses block device `dk` and its partitions: a mount (the
    root or /boot said as booting from it), swap, or a pool (md, LVM, a
    mapper) holding it."""
    for dev, mnt in mounts.items():
        base = os.path.basename(dev)
        if base == dk or re.fullmatch(rf"{re.escape(dk)}p?\d+", base):
            if mnt in ("/", "/boot", "/boot/efi"):
                return f"the host boots from it ({base} is {mnt})"
            return f"{base} is {'swap' if mnt == 'swap' else 'mounted at ' + mnt}"
    held = glob.glob(f"{sys_root}/block/{dk}/holders/*") + glob.glob(f"{sys_root}/block/{dk}/{dk}*/holders/*")
    if held:
        return f"{dk} is in {os.path.basename(held[0])} (a pool or a mapper)"
    return ""


def _usb_use(disks, mounts, sys_root="/sys"):
    return [u for u in (_disk_use(dk, mounts, sys_root) for dk in disks) if u][:8]


def _pci_disks(d, mounts):
    """The use of each disk behind a storage controller's sysfs directory."""
    return [_disk_use(os.path.basename(b), mounts) for b in glob.glob(f"{d}/*/host*/target*/*/block/*")
            + glob.glob(f"{d}/host*/target*/*/block/*") + glob.glob(f"{d}/nvme/nvme*/nvme*n*")]


def _lan_pci(sys_root="/sys"):
    """The PCI address of the interface the default route leaves by."""
    try:
        with open("/proc/net/route") as f:
            for line in f.read().splitlines()[1:]:
                p = line.split()
                if len(p) > 3 and p[1] == "00000000" and int(p[3], 16) & 2:
                    dev = f"{sys_root}/class/net/{p[0]}/device"
                    return os.path.basename(os.path.realpath(dev)) if os.path.islink(dev) else ""
    except (OSError, ValueError):
        pass
    return ""


USB_SERIAL_RE = re.compile(r"[\w.:+/-]{0,64}")
USB_PORT_RE = re.compile(r"\d{1,3}-[\d.]{1,20}")


def usb_want(d):
    """A device as the controller names one (R116): its vendor and product,
    its serial and its port; None when it is not that shape."""
    if not isinstance(d, dict) or not (USB_ID_RE.fullmatch(str(d.get("vendor"))) and USB_ID_RE.fullmatch(str(d.get("product")))):
        return None
    serial, port = str(d.get("serial") or ""), str(d.get("port") or "")
    if not USB_SERIAL_RE.fullmatch(serial) or (port and not USB_PORT_RE.fullmatch(port)):
        return None
    return {"vendor": d["vendor"], "product": d["product"], "serial": serial, "port": port}


def usb_find(usb, want):
    """The host's device `want` names, or None: the ones of its vendor and
    product, the one with its serial among them, and when two are alike with
    no serial to tell them apart, the one in its port."""
    same = [u for u in usb if u.get("vendor") == want["vendor"] and u.get("product") == want["product"]]
    if want.get("serial"):
        # A serial named is the device: one alike with another serial is
        # another device, never a match.
        same = [u for u in same if u.get("serial") == want["serial"]]
    if len(same) > 1 and want.get("port"):
        same = [u for u in same if u.get("port") == want["port"]]
    return same[0] if same else None


def usb_same(a, b):
    """Whether two device names are of one device: vendor and product, and
    the serial where both have one, else the port where both have one."""
    if (a.get("vendor"), a.get("product")) != (b.get("vendor"), b.get("product")):
        return False
    if a.get("serial") and b.get("serial"):
        return a["serial"] == b["serial"]
    if a.get("port") and b.get("port"):
        return a["port"] == b["port"]
    return True


def usb_hostdev(dev, by_address=False):
    """libvirt's hostdev for one USB device (R116 step 3): by vendor and
    product, optional at the VM's start so a stick pulled out does not keep
    it from starting, and by its bus and device number too when the host
    has two alike, so the right one goes."""
    h = ET.Element("hostdev", mode="subsystem", type="usb", managed="yes")
    src = ET.SubElement(h, "source", startupPolicy="optional")
    ET.SubElement(src, "vendor", id=dev["vendor"])
    ET.SubElement(src, "product", id=dev["product"])
    if by_address:
        ET.SubElement(src, "address", bus=str(int(dev.get("bus") or 0)), device=str(int(dev.get("dev") or 0)))
    return ET.tostring(h, encoding="unicode")


def usb_refresh(xml, kept, usb):
    """The domain's USB hostdevs that name a bus and device number, pointed
    at where each device is now (its numbers move with every replug and
    reboot): the new XML, or None when nothing moved. A device not here now
    keeps its old numbers; its source is optional, so the VM starts without
    it."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    moved = False
    for h in root.findall("devices/hostdev"):
        if h.get("type") != "usb":
            continue
        src, addr = h.find("source"), h.find("source/address")
        v, p = h.find("source/vendor"), h.find("source/product")
        if src is None or addr is None or v is None or p is None:
            continue
        want = next((k for k in kept if k.get("vendor") == v.get("id") and k.get("product") == p.get("id")), None)
        dev = usb_find(usb, want) if want else None
        if dev and (addr.get("bus"), addr.get("device")) != (str(dev["bus"]), str(dev["dev"])):
            addr.set("bus", str(dev["bus"]))
            addr.set("device", str(dev["dev"]))
            moved = True
    return ET.tostring(root, encoding="unicode") if moved else None


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


VIRTIOFSD_WRAP = "/usr/local/libexec/builderbot-virtiofsd"
GUEST_UID = 2000   # the VM's account, whose the shared folder's files are inside (the wrapper's squash-host)


def virtiofsd():
    """What libvirt runs for a shared folder, or "" when this machine lacks
    a part: VM host's wrapper (provision-linux.sh, vmhost_virtiofsd), which
    maps every uid in the VM to the folder's owner here, and virtiofsd
    itself, on the PATH on some systems, in libexec or qemu's folder on
    others."""
    real = shutil.which("virtiofsd") or next((p for p in ("/usr/libexec/virtiofsd", "/usr/lib/qemu/virtiofsd")
                                              if os.path.exists(p)), "")
    return VIRTIOFSD_WRAP if real and os.access(VIRTIOFSD_WRAP, os.X_OK) else ""


def rom_name(addr):
    """The file a PCI card's dumped vBIOS is kept in, under VBIOS_DIR."""
    return addr.replace(":", "-") + ".rom"


def apply(xml, hw, vcpus, mem_mb, lan="", network="", vbios_dir="", fsd=""):
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
            if fsd:
                ET.SubElement(fs, "binary", path=fsd)
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
                src = ET.SubElement(h, "source", startupPolicy="optional")
                ET.SubElement(src, "vendor", id=d["vendor"])
                ET.SubElement(src, "product", id=d["product"])
            else:
                h = ET.SubElement(dev, "hostdev", mode="subsystem", type="pci", managed="yes")
                src = ET.SubElement(h, "source")
                ET.SubElement(src, "address", **_pci_parts(d["addr"]))
                # The card's dumped vBIOS when it has one, as a passthrough
                # setup wants: named for it or as dumped here.
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
    """A GPU's vBIOS read through sysfs, the way the usual dump script
    does it: the VGA function only; a throwaway domain started and
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
