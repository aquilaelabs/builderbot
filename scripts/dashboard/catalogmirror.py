"""A mirror of the vetted catalog (R169 step 6), for a controller that cannot
reach it: one archive holding the catalog's index.json and index.sig as the
maintainers signed them, and a git bundle per repository holding every
commit the index pins there (repos/KEY.bundle, KEY the first 16 hex of the
sha256 of the repository's address, each pinned commit at refs/pins/SHA).
tools/catalog-mirror.py makes one on a machine with the network.

Import checks the signature against the key this install ships before
anything is kept, refuses a mirror older than the one held and one missing a
pinned repository, and keeps it under the state. The index then answers when
the catalog does not, and a pack's fetch takes its repository from the
mirror's bundle when it holds the commit, so nothing goes to the network;
such a pack is kept hosted, so the nodes take it from the controller too."""
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import catalogindex

STATE = None
unpack = None            # projects.unpack_archive: a spooled upload into a folder


def configure(*, state, unpack=None):
    globals().update(STATE=str(state), unpack=unpack)


def _dir():
    return Path(STATE) / "catalog-mirror"


def key(url):
    """A repository's file name in the mirror."""
    return hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:16]


def _git(args, timeout=120):
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=timeout, check=False)


def _heads(bundle):
    """The pinned commits a bundle holds, from its refs/pins/ heads."""
    r = _git(["bundle", "list-heads", str(bundle)], timeout=60)
    if r.returncode != 0:
        return set()
    return {ln.split()[0] for ln in r.stdout.splitlines() if " refs/pins/" in ln and len(ln.split()[0]) == 40}


def _read(d):
    """The mirror in folder `d`, checked: (index, None) or (None, why)."""
    try:
        data = (d / "index.json").read_bytes()
        sig = (d / "index.sig").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, "a mirror holds index.json and index.sig at its top, as tools/catalog-mirror.py writes it"
    why = catalogindex.verify(data, sig)
    if why:
        return None, why
    idx, why = catalogindex.parse(data)
    if why:
        return None, why
    return idx, None


_seen = {"stamp": None, "index": None}


def index():
    """The mirror's index as kept, marked as the mirror's, or None: read
    and checked once per import, as the status asks on every poll."""
    if not STATE:
        return None
    d = _dir()
    try:
        stamp = (d / "imported").stat().st_mtime_ns
    except OSError:
        _seen.update(stamp=None, index=None)
        return None
    if _seen["stamp"] == stamp:
        return _seen["index"]
    idx, why = _read(d)
    out = None
    if not why and idx:
        try:
            at = int((d / "imported").read_text().strip() or 0)
        except (OSError, ValueError):
            at = 0
        out = {**idx, "mirror": True, "imported_at": at, "fetched_at": at}
    _seen.update(stamp=stamp, index=out)
    return out


def held():
    """What the page says of it: {generated, packs, repos, imported_at} or None."""
    idx = index()
    if not idx:
        return None
    return {"generated": idx.get("generated", ""), "packs": len(idx.get("packs") or []),
            "repos": len(list((_dir() / "repos").glob("*.bundle"))), "imported_at": idx.get("imported_at", 0)}


def bundle(url, commit):
    """The mirror's bundle for `url` when it holds `commit`, or None: a
    fetch then reads refs/pins/COMMIT from it rather than the network."""
    if not STATE or not commit:
        return None
    b = _dir() / "repos" / f"{key(url)}.bundle"
    return str(b) if b.is_file() and commit in _heads(b) else None


def take(aid, now):
    """Keep a spooled mirror archive: {ok, generated, packs} or {error}."""
    if not unpack:
        return {"error": "uploads are not open here"}
    return _take(lambda dest: unpack(aid, dest), now)


def take_file(path, now):
    """Keep a mirror archive on disk (the stick's copy, R169 step 6): as
    take, and {same: True} when the one held was made at the same time."""
    try:
        with tarfile.open(path) as t:
            gen = _generated_in(t)
    except (OSError, tarfile.TarError) as e:
        return {"error": f"the mirror could not be read: {e}"}
    was = index()
    if was and gen and gen == str(was.get("generated", "")):
        return {"ok": True, "same": True}

    def untar(dest):
        try:
            with tarfile.open(path) as t:
                t.extractall(dest, filter="data")
        except (OSError, tarfile.TarError) as e:
            return {"error": f"the mirror could not be unpacked: {e}"}
        return {"files": 1}
    return _take(untar, now)


def _generated_in(t):
    """The generated stamp of the index inside an open mirror archive, or ""."""
    for m in t.getmembers():
        if m.isfile() and m.name.rstrip("/").endswith("index.json") and m.size < 4 << 20:
            try:
                return str(json.loads(t.extractfile(m).read().decode("utf-8")).get("generated", ""))
            except (ValueError, UnicodeDecodeError, AttributeError):
                return ""
    return ""


def _take(unpack_into, now):
    root = Path(STATE)
    root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="catalog-mirror-", dir=str(root)))
    try:
        got = unpack_into(tmp)
        if got.get("error"):
            return {"error": got["error"]}
        # A single top-level folder is the mirror, as a pack's upload is.
        kids = [p for p in tmp.iterdir()]
        d = kids[0] if len(kids) == 1 and kids[0].is_dir() else tmp
        idx, why = _read(d)
        if why:
            return {"error": f"not imported: {why}"}
        was = index()
        if was and str(idx.get("generated", "")) < str(was.get("generated", "")):
            return {"error": f"not imported: it was made {idx.get('generated') or 'earlier'}, before the mirror held here ({was.get('generated')})"}
        extra = [p.name for p in d.iterdir() if p.name not in ("index.json", "index.sig", "repos")]
        if extra:
            return {"error": f"not imported: a mirror holds index.json, index.sig and repos/ alone, and this has {', '.join(sorted(extra)[:5])}"}
        missing = []
        for e in idx.get("packs") or []:
            if e.get("withdrawn"):
                continue
            b = d / "repos" / f"{key(e['url'])}.bundle"
            if not b.is_file() or e["commit"] not in _heads(b):
                missing.append(e["name"])
        if missing:
            return {"error": f"not imported: it lacks the repository of {', '.join(missing[:5])}{' and more' if len(missing) > 5 else ''} at the commit the index pins"}
        (d / "imported").write_text(str(int(now)))
        old = root / "catalog-mirror.old"
        shutil.rmtree(old, ignore_errors=True)
        if _dir().exists():
            os.replace(_dir(), old)
        os.replace(d, _dir())
        shutil.rmtree(old, ignore_errors=True)
        return {"ok": True, "generated": idx.get("generated", ""), "packs": len(idx.get("packs") or [])}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def forget():
    shutil.rmtree(_dir(), ignore_errors=True)
    return {"ok": True}


