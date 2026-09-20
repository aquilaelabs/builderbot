#!/usr/bin/env python3
"""Check every system package a recipe names against the distributions' own
package indexes.

config/toolchains.json lists, per recipe and per package manager, the machine's
own packages the recipe needs (`system.apt`, `system.dnf`, ...), and the agent
installs them on a node it administers. A name that does not exist on that
node's release fails the install with the package manager's own complaint,
on somebody's machine, after the download. This asks the indexes instead:
for each release below it fetches the repositories' package list once,
caches it, and says per recipe which names are not there.

An entry may name alternatives, "libasound2t64|libasound2": the agent takes
the first the machine's repositories have, and this counts the entry as met
when any of them is in the index. The release column says which one it is.

    tools/check-sysdeps.py              every recipe, every release
    tools/check-sysdeps.py playwright   one recipe
    tools/check-sysdeps.py --fresh      fetch the indexes again

Network, so not part of bb lint or CI: run it after changing a `system` list
and before a release. Exits 1 when a name is missing somewhere it is listed.
"""
import gzip
import io
import json
import lzma
import os
import re
import sys
import tarfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from compression import zstd            # Python 3.14
except ImportError:                          # older: the zstd indexes are skipped
    zstd = None

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "builderbot" / "sysdeps-index"
MAX_AGE = 7 * 86400

UBU = "http://archive.ubuntu.com/ubuntu/dists/{}/{}/binary-amd64/Packages.gz"
DEB = "http://deb.debian.org/debian/dists/{}/{}/binary-amd64/Packages.xz"
ROCKY = "https://dl.rockylinux.org/pub/rocky/{}/{}/x86_64/os/"
# What each package manager is checked against: the releases a node is
# likeliest to be, oldest supported first.
RELEASES = {
    "apt": [
        ("Ubuntu 22.04", [UBU.format("jammy", c) for c in ("main", "universe")]),
        ("Ubuntu 24.04", [UBU.format("noble", c) for c in ("main", "universe")]),
        ("Ubuntu 26.04", [UBU.format("resolute", c) for c in ("main", "universe")]),
        ("Debian 12", [DEB.format("bookworm", "main")]),
        ("Debian 13", [DEB.format("trixie", "main")]),
    ],
    "dnf": [
        ("Rocky 9", [ROCKY.format(9, r) for r in ("BaseOS", "AppStream", "CRB")]),
        ("Rocky 10", [ROCKY.format(10, r) for r in ("BaseOS", "AppStream", "CRB")]),
        ("Fedora 43", ["https://dl.fedoraproject.org/pub/fedora/linux/releases/43/Everything/x86_64/os/"]),
    ],
    "pacman": [
        ("Arch", ["https://geo.mirror.pkgbuild.com/{}/os/x86_64/{}.db".format(r, r) for r in ("core", "extra")]),
    ],
    "zypper": [
        ("openSUSE Leap 15.6", ["https://download.opensuse.org/distribution/leap/15.6/repo/oss/"]),
        ("openSUSE Tumbleweed", ["https://download.opensuse.org/tumbleweed/repo/oss/"]),
    ],
    "apk": [
        ("Alpine 3.22", ["https://dl-cdn.alpinelinux.org/alpine/v3.22/{}/x86_64/APKINDEX.tar.gz".format(r)
                         for r in ("main", "community")]),
    ],
}


def fetch(url, fresh):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / re.sub(r"[^A-Za-z0-9._-]", "_", url)
    if fresh or not f.exists() or time.time() - f.stat().st_mtime > MAX_AGE:
        req = urllib.request.Request(url, headers={"User-Agent": "builderbot-check-sysdeps"})
        with urllib.request.urlopen(req, timeout=120) as r:
            f.write_bytes(r.read())
    return f.read_bytes()


def unpack(name, data):
    if name.endswith(".gz"):
        return gzip.decompress(data)
    if name.endswith(".xz"):
        return lzma.decompress(data)
    if name.endswith(".zst"):
        if zstd is None:
            raise RuntimeError("a zstd index needs Python 3.14")
        return zstd.decompress(data)
    return data


def names_deb(data):
    text = data.decode("utf-8", "replace")
    got = set(re.findall(r"^Package: (\S+)", text, re.M))
    # A virtual package apt installs when exactly one package provides it.
    for line in re.findall(r"^Provides: (.+)$", text, re.M):
        got.update(re.sub(r"\s*\(.*?\)", "", x).strip() for x in line.split(","))
    return got


def names_rpmmd(base, fresh):
    repomd = ET.fromstring(fetch(base + "repodata/repomd.xml", fresh))
    ns = {"r": "http://linux.duke.edu/metadata/repo"}
    href = next((loc.get("href") for d in repomd.findall("r:data", ns)
                 if d.get("type") == "primary" and (loc := d.find("r:location", ns)) is not None), "")
    if not href:
        raise RuntimeError(f"{base} names no primary index")
    root = ET.fromstring(unpack(href, fetch(base + href, fresh)))
    common = "{http://linux.duke.edu/metadata/common}"
    return {p.findtext(common + "name") for p in root.iter(common + "package")}


def names_arch(data):
    got = set()
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        for m in t.getmembers():
            f = t.extractfile(m) if m.name.endswith("/desc") else None
            if f:
                desc = f.read().decode("utf-8", "replace")
                got.update(re.findall(r"%NAME%\n(\S+)", desc))
                prov = re.search(r"%PROVIDES%\n((?:.+\n)+)", desc)
                if prov:
                    got.update(re.split(r"[=<>]", x)[0] for x in prov.group(1).split())
    return got


def names_apk(data):
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        f = t.extractfile("APKINDEX")
        idx = f.read().decode("utf-8", "replace") if f else ""
    return set(re.findall(r"^P:(\S+)", idx, re.M))


def index(manager, urls, fresh):
    got = set()
    for u in urls:
        if manager == "apt":
            got |= names_deb(unpack(u, fetch(u, fresh)))
        elif manager in ("dnf", "zypper"):
            got |= names_rpmmd(u, fresh)
        elif manager == "pacman":
            got |= names_arch(fetch(u, fresh))
        elif manager == "apk":
            got |= names_apk(fetch(u, fresh))
    return got


def main(argv):
    fresh = "--fresh" in argv
    only = [a for a in argv if not a.startswith("-")]
    cat = json.loads((ROOT / "config" / "toolchains.json").read_text())["toolchains"]
    recipes = [p for p in cat if p.get("system") and (not only or p["name"] in only)]
    bad = 0
    for manager, releases in RELEASES.items():
        lists = {p["name"]: p["system"].get(manager) or [] for p in recipes}
        if not any(lists.values()):
            continue
        for label, urls in releases:
            try:
                have = index(manager, urls, fresh)
            except Exception as e:                  # noqa: BLE001 - say it and carry on
                print(f"{manager:7} {label:20} could not read the index: {e}")
                continue
            for name, entries in lists.items():
                if not entries:
                    continue
                missing, chose = [], []
                for entry in entries:
                    alts = entry.split("|")
                    hit = next((a for a in alts if a in have), "")
                    if not hit:
                        missing.append(entry)
                    elif len(alts) > 1:
                        chose.append(hit)
                note = f" (takes {', '.join(chose)})" if chose else ""
                if missing:
                    bad += 1
                    print(f"{manager:7} {label:20} {name:18} MISSING {' '.join(missing)}{note}")
                else:
                    print(f"{manager:7} {label:20} {name:18} ok, {len(entries)} named{note}")
    # What no release is checked for, so a gap is said rather than implied.
    for p in recipes:
        for manager in p["system"]:
            if manager not in RELEASES:
                print(f"{manager:7} {'(not checked)':20} {p['name']:18} no index this tool reads")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
