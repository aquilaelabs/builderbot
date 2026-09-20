#!/usr/bin/env python3
"""Read config/toolchains.json on bb's behalf.

The recipes are data now: every URL, branch, flag, archive layout and
environment variable a toolchain needs lives in that file, and this is the part
that reads them out: fields, argument vectors with their placeholders filled
in, and the version each upstream currently offers.

It sits beside bb rather than inside it because the reading is JSON work and
the resolvers are not alike. Each upstream announces its current release in a
different shape (a bare line of text, a redirect to a tag, a JSON index of
every build it has ever made), and that is a paragraph of python apiece
against a page of shell.

Placeholders, substituted into url templates and argv:

    {dir}      where the toolchain is being installed
    {version}  whatever the version resolver returned
    {script}   the installer this recipe downloaded, for kind "script"

Usage (all output is plain, and empty means "not set"):

    sdkmeta.py names
    sdkmeta.py field  NAME source.strip
    sdkmeta.py argv   NAME source.run  dir=/sdk/go version=go1.27.0
    sdkmeta.py resolve NAME                 -> version <TAB> url
    sdkmeta.py size    NAME                 -> bytes of the download, if knowable
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

# Semgrep flags this import (use-defused-xml) and it is a fair thing to ask
# about, so the answer lives here rather than being re-derived every scan: the
# only XML parsed is Google's SDK repository index, fetched over TLS from
# dl.google.com. ElementTree does not resolve external entities at all, so XXE
# is not reachable; what remains is entity-expansion blowup, which requires
# Google's own CDN to serve a hostile index. Adding defusedxml would put a
# dependency in an otherwise stdlib-only tree to defend against that. If this
# ever parses XML from a source the catalog does not control, revisit it.
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
# BB_TOOLCHAINS_JSON points this at another catalog. It exists so the install
# machinery can be exercised against a fake one: five recipes fetched from
# file:// URLs prove the fetching, unpacking, environment and verify steps
# without spending gigabytes or touching the real toolchain store root.
CATALOG = os.environ.get("BB_TOOLCHAINS_JSON") or os.path.join(
    HERE, "..", "..", "config", "toolchains.json")
TIMEOUT = 30
# Some of these hosts hand a bare urllib a different answer, or none: go.dev
# serves the plain version file happily, github's release redirect does not
# mind, but it costs nothing to look like something that reads web pages.
UA = {"User-Agent": "builderbot-sdk/1 (+https://github.com/Stencil-Projects/BuilderBot)"}


def die(msg):
    print(f"sdkmeta: {msg}", file=sys.stderr)
    raise SystemExit(2)


def _catalog():
    """The whole file. Toolchains are most of it, but not all: see
    android_images, which is data about a thing that is not a toolchain."""
    try:
        with open(CATALOG) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        die(f"cannot read {CATALOG}: {e}")


def catalog():
    try:
        return _catalog()["toolchains"]
    except KeyError as e:
        die(f"cannot read {CATALOG}: {e}")


def toolchain(name):
    for p in catalog():
        if p.get("name") == name:
            return p
    die(f"no toolchain named {name!r} in the catalog")


def dig(obj, path):
    """A dotted path into nested dicts and lists, or None.

    A number walks into a list (source.then.0.run is the first follow-up
    step), which is not decoration: without it the .NET recipe's workload step
    resolved to nothing and quietly did not run, leaving a plain SDK behind
    where a MAUI one was asked for.
    """
    for part in path.split("."):
        if isinstance(obj, list):
            if not part.isdigit() or int(part) >= len(obj):
                return None
            obj = obj[int(part)]
        elif isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return None
    return obj


def fill(text, subs):
    for k, v in subs.items():
        text = text.replace("{" + k + "}", v)
    return text


_ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}


def this_platform():
    """"<os>/<arch>" for the machine running this, the way the catalog's
    `platforms` spells it: linux/amd64, darwin/arm64."""
    import platform as _p
    return f"{_p.system().lower()}/{_ARCH.get(_p.machine().lower(), _p.machine().lower())}"


def for_platform(value):
    """A recipe field that may differ per platform: a plain value, or a
    dict keyed "<os>/<arch>" with "<os>/*" as a fallback. A recipe whose
    download is one URL on Linux and another on a Mac writes the dict;
    everything else stays a string."""
    if not isinstance(value, dict):
        return value
    plat = this_platform()
    if plat in value:
        return value[plat]
    o = plat.partition("/")[0]
    if f"{o}/*" in value:
        return value[f"{o}/*"]
    return ""


# Documents fetched while resolving, kept briefly on disk.
#
# A check asks about thirteen toolchains in thirteen separate processes, and
# several of them want the same file: sdkmanager's package index answers for
# the emulator, the NDK and CMake alike, which is four hundred kilobytes
# fetched three times over. Anything upstream publishes as a catalogue changes
# on the order of days, so a few minutes of reuse costs nothing in accuracy
# and takes a check from 2.7MB to about half that.
#
# It is a cache and not a store: /tmp is cleared on every container start, and
# a missing or stale entry simply means fetching again.
CACHE_DIR = os.path.join(os.environ.get("TMPDIR", "/tmp"), "bb-sdkmeta-cache")
CACHE_TTL = int(os.environ.get("BB_SDK_CACHE_TTL", "900"))


def _cached(key, produce):
    """produce()'s bytes, remembered for CACHE_TTL by key."""
    if CACHE_TTL <= 0:
        return produce()
    path = os.path.join(CACHE_DIR, hashlib.sha256(key.encode()).hexdigest()[:32])
    try:
        if time.time() - os.path.getmtime(path) < CACHE_TTL:
            with open(path, "rb") as f:
                return f.read()
    except OSError:
        pass
    body = produce()
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        # Written aside and moved, so a reader never sees half a document.
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, path)
    except OSError:
        pass
    return body


def get(url, decode=True):
    def fetch():
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()

    body = _cached("GET " + url, fetch)
    return body.decode("utf-8", "replace") if decode else body


def final_url(url):
    """Where a redirect lands, without fetching the body.

    Used for the /releases/latest trick: the tag is in the URL, and asking the
    API for it instead would be rate-limited by IP for anonymous callers.
    """
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.url


def resolve(tc):
    """(version, url) for a toolchain, asking upstream what it currently offers.

    Either may come back empty: a recipe that needs no version does not have a
    resolver, and one whose resolver supplies the download URL itself has no
    template to fill in.
    """
    src = tc.get("source") or {}
    spec = src.get("version") or {}
    kind = spec.get("resolver")
    version, url = "", ""

    if kind == "text":
        # A file whose whole content is the current version. go.dev serves one.
        version = get(spec["url"]).strip().splitlines()[0].strip()
        want = spec.get("expect_prefix")
        if want and not version.startswith(want):
            die(f"{tc['name']}: expected a version starting {want!r}, got {version!r}")

    elif kind == "github-release":
        tag = final_url(f"https://github.com/{spec['repo']}/releases/latest").rstrip("/")
        tag = tag.rsplit("/", 1)[-1]
        version = tag
        for k, cut in (("trim_prefix", str.removeprefix), ("trim_suffix", str.removesuffix)):
            if spec.get(k):
                version = cut(version, spec[k])
        if spec.get("numeric") and not version.replace(".", "").isdigit():
            die(f"{tc['name']}: could not read a version out of the tag {tag!r}")

    elif kind == "zig-index":
        # An index of every build, newest release first and "master" among
        # them: the nightly is not what anybody asked to install.
        index = json.loads(get(spec["url"]))
        version = next(k for k in index if k != "master")
        asset = index[version].get(spec["asset"]) or {}
        url = asset.get("tarball") or ""
        if not url:
            die(f"{tc['name']}: the index offers no {spec['asset']} build for {version}")

    elif kind == "node-index":
        # nodejs.org's own index, newest release first. LTS only: a node
        # building somebody's project should be on the line upstream still
        # supports, not on the current release that moves under it. The
        # entry's version already carries its "v", which the download path
        # and the filename both want.
        index = json.loads(get(spec["url"]))
        version = next((r["version"] for r in index if r.get("lts")), "")
        if not version:
            die(f"{tc['name']}: the index offers no LTS release")

    elif kind:
        die(f"{tc['name']}: unknown version resolver {kind!r}")

    if src.get("url"):
        url = fill(for_platform(src["url"]) or "", {"version": version})
        if not url:
            die(f"{tc['name']}: no download for {this_platform()}; the recipe names "
                f"{', '.join(sorted(src['url']))}")
    return version, url


def content_length(url):
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        n = r.headers.get("Content-Length")
    return int(n) if n and n.isdigit() else 0


def download_urls(tc):
    """Every URL an install of this toolchain would fetch, or none.

    Two ways to know. A recipe whose own source.url is the payload (a tarball)
    is its own answer. Everything else has to ask the installer, and most of
    them will say: playwright's dry run names the five bundles it would pull,
    the .NET installer names the SDK archive it would pull. That is a command
    to run and a pattern to match, both of which are catalog entries rather
    than code here, so a toolchain that can be asked the same way needs no
    python at all.

    Some cannot be asked: a git clone has no content length, rustup fetches
    components it decides on as it goes, and sdkmanager keeps its sizes in a
    repository index this does not read. Those report nothing, which is the
    honest answer and is what the row then shows.
    """
    src = tc.get("source") or {}
    spec = src.get("download")
    if spec is None:
        _, url = resolve(tc)
        return [url] if url and src.get("kind") == "tarball" else []
    kind = spec.get("resolver")
    if kind in ("android-repo", "approximate"):
        return []                     # size_of answers these without a URL
    if kind == "url-matches":
        # The URLs are listed in a file upstream publishes rather than by a
        # command: rust's channel manifest names an archive per component, and
        # the three a minimal profile installs are the honest answer to what
        # `rustup` is about to fetch.
        if not spec.get("url") or not spec.get("match"):
            die(f"{tc['name']}: a url-matches download needs both url and match")
        try:
            return re.findall(spec["match"], get(spec["url"]))
        except Exception:  # noqa: BLE001
            return []
    if kind != "command-urls":
        die(f"{tc['name']}: unknown download resolver {kind!r}")
    if not spec.get("run") or not spec.get("match"):
        die(f"{tc['name']}: a command-urls download needs both run and match")
    env = dict(os.environ, **{k: str(v) for k, v in (spec.get("env") or {}).items()})
    # Cached like a fetched document, and for the same reason: the .NET dry run
    # downloads and executes a vendor script, and it was being run twice per
    # check: once to learn the version, once to learn the size.
    def dry_run():
        try:
            return subprocess.run(spec["run"], capture_output=True,
                                  timeout=120, env=env).stdout
        except (OSError, subprocess.SubprocessError):
            return b""

    out = _cached("RUN " + "\x00".join(spec["run"]), dry_run).decode("utf-8", "replace")
    return re.findall(spec["match"], out)


def _revision(pkg_el):
    rev = pkg_el.find("revision")
    if rev is None:
        return ()
    return tuple(int(x.text) if (x.text or "").isdigit() else 0 for x in rev)


def android_size(spec, pkg_id):
    """The size sdkmanager's own repository index gives for exactly this id.

    sdkmanager will not say what a package weighs, but the index it reads
    does, and that index is the only place an android download size exists
    before the download. Looked up by the id bb resolved rather than by
    picking the newest entry: the index's newest playstore image is an
    android-CANARY build nobody is installing, and the emulator appears twice,
    once stable and once on the dev channel, sixteen megabytes apart.
    """
    best = None
    for url in spec.get("xml") or []:
        try:
            root = ET.fromstring(get(url, decode=False))
        except Exception:  # noqa: BLE001 - one index missing is not fatal
            continue
        channels = {c.get("id"): (c.text or "") for c in root if c.tag.endswith("channel")}
        for el in root:
            if not el.tag.endswith("remotePackage") or el.get("path") != pkg_id:
                continue
            ref = el.find("channelRef")
            channel = channels.get(ref.get("ref"), "") if ref is not None else "stable"
            if channel and channel != "stable":
                continue
            for a in el.iter():
                if not a.tag.endswith("archive"):
                    continue
                host, arch = a.findtext("host-os"), a.findtext("host-arch")
                if host not in (None, "linux") or arch not in (None, "x64", "x86_64"):
                    continue
                size = a.findtext("complete/size") or ""
                if size.isdigit():
                    here = (_revision(el), int(size))
                    if best is None or here[0] > best[0]:
                        best = here
    return best[1] if best else 0


def image_flavors():
    """The android_images section of the catalog: flavor -> {label, about, xml}."""
    sec = _catalog().get("android_images") or {}
    return sec.get("abi") or "x86_64", sec.get("flavors") or {}


IMAGE_ID = re.compile(r"^system-images;android-([A-Za-z0-9.-]+);([A-Za-z0-9_-]+);(.+)$")


def available_images():
    """Every system image the catalog's flavors offer, from sdkmanager's index.

    One line per image (id, API level, flavor, bytes), which is what makes an
    API level offerable at all: sdkmanager cannot be asked what exists without
    a network round trip that prints a thousand rows, and cannot be asked what
    anything weighs at any price. The index answers both.

    Stable channel only, and only the archive this host could run: the index
    carries CANARY builds and other ABIs beside the ones anybody wants.
    """
    abi, flavors = image_flavors()
    rows = {}
    for flavor, spec in flavors.items():
        url = spec.get("xml")
        if not url:
            continue
        try:
            root = ET.fromstring(get(url, decode=False))
        except Exception:  # noqa: BLE001 - one index missing is not fatal
            continue
        channels = {c.get("id"): (c.text or "") for c in root if c.tag.endswith("channel")}
        for el in root:
            if not el.tag.endswith("remotePackage"):
                continue
            m = IMAGE_ID.match(el.get("path") or "")
            if not m or m.group(2) != flavor or m.group(3) != abi:
                continue
            ref = el.find("channelRef")
            channel = channels.get(ref.get("ref"), "") if ref is not None else "stable"
            if channel and channel != "stable":
                continue
            for a in el.iter():
                if not a.tag.endswith("archive"):
                    continue
                host, arch = a.findtext("host-os"), a.findtext("host-arch")
                if host not in (None, "linux") or arch not in (None, "x64", "x86_64"):
                    continue
                size = a.findtext("complete/size") or ""
                if not size.isdigit():
                    continue
                key = el.get("path")
                # The newest revision of an image that ships more than one.
                here = (_revision(el), int(size))
                if key not in rows or here[0] > rows[key][0]:
                    rows[key] = here
    out = []
    for key, (_, size) in rows.items():
        m = IMAGE_ID.match(key)
        out.append((key, m.group(1), m.group(2), size))
    # Newest level first, and a plain level ahead of the extension builds that
    # share its number: android-34 is what somebody picking "34" means, and
    # android-34-ext11 is a thing they would have to have gone looking for.
    # The index itself is in no order worth relying on.
    def key(row):
        m = re.match(r"(\d+)(.*)", row[1])
        return (-int(m.group(1)) if m else 0, bool(m and m.group(2)),
                m.group(2) if m else row[1], row[2])
    return sorted(out, key=key)


def size_of(tc, pkg_id=""):
    """What an install would download, in bytes, or empty when unknowable."""
    spec = (tc.get("source") or {}).get("download") or {}
    if spec.get("resolver") == "android-repo":
        return str(android_size(spec, pkg_id)) if pkg_id else ""
    if spec.get("resolver") == "approximate":
        # A number somebody wrote down, for the one recipe whose download
        # cannot be measured before it happens. Marked with a tilde all the
        # way to the row, so it is never mistaken for a measurement.
        n = spec.get("bytes")
        return f"~{n}" if isinstance(n, int) and n > 0 else ""
    total = 0
    for url in download_urls(tc):
        try:
            total += content_length(url)
        except Exception:  # noqa: BLE001
            # One unreachable mirror and the total is a lie, so say nothing.
            return ""
    return str(total) if total else ""


def main(argv):
    if not argv:
        die("usage: sdkmeta.py names|flavors|images|field|argv|resolve|size ...")
    op = argv[0]

    if op == "names":
        print("\n".join(p["name"] for p in catalog()))
        return

    if op == "flavors":
        abi, flavors = image_flavors()
        for name, spec in flavors.items():
            print(f"{name}\t{abi}\t{spec.get('label', name)}\t{spec.get('about', '')}")
        return

    if op == "images":
        for pid, api, flavor, size in available_images():
            print(f"{pid}\t{api}\t{flavor}\t{size}")
        return

    if len(argv) < 2:
        die(f"{op} needs a toolchain name")
    tc = toolchain(argv[1])

    if op == "field":
        # A per-platform value (a dict keyed "<os>/<arch>") answers for the
        # machine running this: a tarball's strip count, a script's url.
        v = for_platform(dig(tc, argv[2])) if len(argv) > 2 else None
        if isinstance(v, bool):
            v = "1" if v else ""
        print("" if v is None else v)

    elif op == "argv":
        subs = dict(a.split("=", 1) for a in argv[3:] if "=" in a)
        items = dig(tc, argv[2]) or []
        if not isinstance(items, list):
            die(f"{argv[2]} is not a list")
        # NUL-separated, because an argument may hold anything a JSON string
        # can and the caller reads it into a bash array.
        sys.stdout.write("".join(fill(str(i), subs) + "\0" for i in items))

    elif op == "env":
        # KEY=VALUE per line, NUL-terminated for the same reason.
        subs = dict(a.split("=", 1) for a in argv[3:] if "=" in a)
        for k, v in (dig(tc, argv[2]) or {}).items():
            sys.stdout.write(f"{k}={fill(str(v), subs)}\0")

    elif op == "resolve":
        version, url = resolve(tc)
        print(f"{version}\t{url}")

    elif op == "size":
        # An optional package id, for the recipes whose size lives in an index
        # keyed by one: bb resolves it, so that the id asked about here is
        # exactly the id that would be installed.
        print(size_of(tc, argv[2] if len(argv) > 2 else ""))

    else:
        die(f"unknown operation {op!r}")


if __name__ == "__main__":
    main(sys.argv[1:])
