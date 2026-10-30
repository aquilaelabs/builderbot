#!/usr/bin/env python3
"""Make a mirror of the vetted catalog (R169 step 6), for a controller that
cannot reach it: run on a machine with the network, carry the file over,
and import it under Controller settings' Vetted catalog.

    tools/catalog-mirror.py OUT.tar.gz [--catalog URL] [--from-dir DIR]

The index is read from the catalog's address (the public one by default) or
from a checkout of the catalog (--from-dir), and its signature checked
against the key this tree ships before anything is fetched. Each repository
the index pins is fetched at every commit it pins there and written as one
git bundle, each commit at refs/pins/SHA; a withdrawn entry is left out. The
archive holds catalog-mirror/ with index.json and index.sig as signed and
repos/KEY.bundle, as the controller reads it (scripts/dashboard/catalogmirror.py)."""
import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts" / "dashboard"))
import catalogindex  # noqa: E402
import catalogmirror  # noqa: E402


def die(why):
    print(f"catalog-mirror: {why}", file=sys.stderr)
    sys.exit(1)


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        die(f"git {' '.join(args[:3])}: {(r.stderr or r.stdout).strip().splitlines()[-1:] or 'failed'}")
    return r.stdout


def main():
    ap = argparse.ArgumentParser(description="Make a mirror of the vetted catalog for a controller without the network.")
    ap.add_argument("out", help="the archive to write, e.g. catalog-mirror.tar.gz")
    ap.add_argument("--catalog", default=catalogindex.DEFAULT_URL, help="the catalog's address (the public one by default)")
    ap.add_argument("--from-dir", help="a checkout of the catalog: its index.json and index.sig rather than fetched")
    a = ap.parse_args()
    if a.from_dir:
        d = Path(a.from_dir)
        try:
            data, sig = (d / "index.json").read_bytes(), (d / "index.sig").read_text(encoding="utf-8")
        except OSError as e:
            die(f"{d} holds no index.json and index.sig: {e}")
    else:
        base = a.catalog.rstrip("/") + "/"
        try:
            data = urllib.request.urlopen(base + "index.json", timeout=30).read()
            sig = urllib.request.urlopen(base + "index.sig", timeout=30).read().decode("utf-8", "replace")
        except OSError as e:
            die(f"the catalog at {base} did not answer: {e}")
    why = catalogindex.verify(data, sig)
    if why:
        die(why)
    idx, why = catalogindex.parse(data)
    if why:
        die(why)
    pins = {}
    for e in idx["packs"]:
        if not e.get("withdrawn"):
            pins.setdefault(e["url"], set()).add(e["commit"])
    work = Path(tempfile.mkdtemp(prefix="catalog-mirror-"))
    try:
        root = work / "catalog-mirror"
        (root / "repos").mkdir(parents=True)
        (root / "index.json").write_bytes(data)
        (root / "index.sig").write_text(sig, encoding="utf-8")
        for url, commits in sorted(pins.items()):
            repo = work / "git" / catalogmirror.key(url)
            git("init", "-q", "--bare", str(repo))
            for c in sorted(commits):
                print(f"catalog-mirror: {url} at {c[:12]}")
                git("-C", str(repo), "fetch", "-q", url, c)
                git("-C", str(repo), "update-ref", f"refs/pins/{c}", c)
            git("-C", str(repo), "bundle", "create", "-q", str(root / "repos" / f"{catalogmirror.key(url)}.bundle"), "--all")
        with tarfile.open(a.out, "w:gz") as tar:
            tar.add(str(root), arcname="catalog-mirror")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"catalog-mirror: {a.out} holds {len(idx['packs'])} entries from {len(pins)} repositories, made {idx.get('generated') or 'at an unknown time'}")


if __name__ == "__main__":
    main()
