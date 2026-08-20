#!/usr/bin/env python3
"""Read config/packages.json on bb's behalf.

The recipes are data now — every URL, branch, flag, archive layout and
environment variable a package needs lives in that file — and this is the part
that reads them out: fields, argument vectors with their placeholders filled
in, and the version each upstream currently offers.

It sits beside bb rather than inside it because the reading is JSON work and
the resolvers are not alike. Each upstream announces its current release in a
different shape — a bare line of text, a redirect to a tag, a JSON index of
every build it has ever made — and that is a paragraph of python apiece
against a page of shell.

Placeholders, substituted into url templates and argv:

    {dir}      where the package is being installed
    {version}  whatever the version resolver returned
    {script}   the installer this recipe downloaded, for kind "script"

Usage (all output is plain, and empty means "not set"):

    sdkmeta.py names
    sdkmeta.py field  NAME source.strip
    sdkmeta.py argv   NAME source.run  dir=/sdk/go version=go1.27.0
    sdkmeta.py resolve NAME                 -> version <TAB> url
    sdkmeta.py size    NAME                 -> bytes of the download, if knowable
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(HERE, "..", "..", "config", "packages.json")
TIMEOUT = 30
# Some of these hosts hand a bare urllib a different answer, or none: go.dev
# serves the plain version file happily, github's release redirect does not
# mind, but it costs nothing to look like something that reads web pages.
UA = {"User-Agent": "builderbot-sdk/1 (+https://github.com/Stencil-Projects/BuilderBot)"}


def die(msg):
    print(f"sdkmeta: {msg}", file=sys.stderr)
    raise SystemExit(2)


def catalog():
    try:
        with open(CATALOG) as f:
            return json.load(f)["packages"]
    except (OSError, ValueError, KeyError) as e:
        die(f"cannot read {CATALOG}: {e}")


def package(name):
    for p in catalog():
        if p.get("name") == name:
            return p
    die(f"no package named {name!r} in the catalog")


def dig(obj, path):
    """A dotted path into nested dicts, or None."""
    for part in path.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return None
        obj = obj[part]
    return obj


def fill(text, subs):
    for k, v in subs.items():
        text = text.replace("{" + k + "}", v)
    return text


def get(url, decode=True):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = r.read()
    return body.decode("utf-8", "replace") if decode else body


def final_url(url):
    """Where a redirect lands, without fetching the body.

    Used for the /releases/latest trick: the tag is in the URL, and asking the
    API for it instead would be rate-limited by IP for anonymous callers.
    """
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.url


def resolve(pkg):
    """(version, url) for a package, asking upstream what it currently offers.

    Either may come back empty: a recipe that needs no version does not have a
    resolver, and one whose resolver supplies the download URL itself has no
    template to fill in.
    """
    src = pkg.get("source") or {}
    spec = src.get("version") or {}
    kind = spec.get("resolver")
    version, url = "", ""

    if kind == "text":
        # A file whose whole content is the current version. go.dev serves one.
        version = get(spec["url"]).strip().splitlines()[0].strip()
        want = spec.get("expect_prefix")
        if want and not version.startswith(want):
            die(f"{pkg['name']}: expected a version starting {want!r}, got {version!r}")

    elif kind == "github-release":
        tag = final_url(f"https://github.com/{spec['repo']}/releases/latest").rstrip("/")
        tag = tag.rsplit("/", 1)[-1]
        version = tag
        for k, cut in (("trim_prefix", str.removeprefix), ("trim_suffix", str.removesuffix)):
            if spec.get(k):
                version = cut(version, spec[k])
        if spec.get("numeric") and not version.replace(".", "").isdigit():
            die(f"{pkg['name']}: could not read a version out of the tag {tag!r}")

    elif kind == "zig-index":
        # An index of every build, newest release first and "master" among
        # them: the nightly is not what anybody asked to install.
        index = json.loads(get(spec["url"]))
        version = next(k for k in index if k != "master")
        asset = index[version].get(spec["asset"]) or {}
        url = asset.get("tarball") or ""
        if not url:
            die(f"{pkg['name']}: the index offers no {spec['asset']} build for {version}")

    elif kind:
        die(f"{pkg['name']}: unknown version resolver {kind!r}")

    if src.get("url"):
        url = fill(src["url"], {"version": version})
    return version, url


def size_of(pkg):
    """The download in bytes, when the URL is the thing being installed.

    Only for tarballs. A "script" recipe's URL is an installer a few kilobytes
    long that then fetches the real payload, and reporting its Content-Length
    as the package size would be worse than saying nothing.
    """
    src = pkg.get("source") or {}
    if src.get("kind") != "tarball":
        return ""
    _, url = resolve(pkg)
    if not url:
        return ""
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.headers.get("Content-Length") or ""


def main(argv):
    if not argv:
        die("usage: sdkmeta.py names|field|argv|resolve|size ...")
    op = argv[0]

    if op == "names":
        print("\n".join(p["name"] for p in catalog()))
        return

    if len(argv) < 2:
        die(f"{op} needs a package name")
    pkg = package(argv[1])

    if op == "field":
        v = dig(pkg, argv[2]) if len(argv) > 2 else None
        if isinstance(v, bool):
            v = "1" if v else ""
        print("" if v is None else v)

    elif op == "argv":
        subs = dict(a.split("=", 1) for a in argv[3:] if "=" in a)
        items = dig(pkg, argv[2]) or []
        if not isinstance(items, list):
            die(f"{argv[2]} is not a list")
        # NUL-separated, because an argument may hold anything a JSON string
        # can and the caller reads it into a bash array.
        sys.stdout.write("".join(fill(str(i), subs) + "\0" for i in items))

    elif op == "env":
        # KEY=VALUE per line, NUL-terminated for the same reason.
        subs = dict(a.split("=", 1) for a in argv[3:] if "=" in a)
        for k, v in (dig(pkg, argv[2]) or {}).items():
            sys.stdout.write(f"{k}={fill(str(v), subs)}\0")

    elif op == "resolve":
        version, url = resolve(pkg)
        print(f"{version}\t{url}")

    elif op == "size":
        print(size_of(pkg))

    else:
        die(f"unknown operation {op!r}")


if __name__ == "__main__":
    main(sys.argv[1:])
