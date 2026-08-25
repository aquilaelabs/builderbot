#!/usr/bin/env python3
"""What a project has built, found in one place: its dist/ directory.

The convention is the feature. Build systems scatter their outputs — gradle
five directories deep, web-ext into web-ext-artifacts/, cargo into target/ —
and a tab that went looking for all of those would be a catalogue of build
systems that is wrong the week a new one arrives. So the deal is one word
long: **a project puts what it ships in dist/**, and this lists dist/ and
nothing else. A session that builds an APK copies it there; the template
tells it so. An empty tab on a project that builds things means the copy
step is missing, and the tab says exactly that rather than guessing.

Kinds are by extension, and the kind is what decides the actions offered:
everything can be downloaded, and an .xpi can additionally be pushed to the
paired phone — unpacked into a scratch directory and handed to web-ext, since
an XPI is a zip of exactly the source layout web-ext runs.
"""
import time
import zipfile
from pathlib import Path

WORKSPACE = None
SCRATCH = None

DIST = "dist"

# Extension -> kind. A short list on purpose: these are the things this
# operator's projects actually produce, and an unknown extension still shows —
# as "file", download only — rather than being hidden.
KINDS = {
    ".apk": "apk", ".aab": "aab", ".xpi": "xpi",
    ".ipa": "ipa", ".deb": "deb", ".rpm": "rpm",
    ".exe": "exe", ".msi": "msi", ".dmg": "dmg", ".appimage": "appimage",
}

# How deep inside dist/ to look. Two levels allows dist/android/app.apk
# without inviting a build tree to be symlinked in whole.
MAX_DEPTH = 2


def configure(*, workspace, scratch):
    globals().update(WORKSPACE=Path(workspace), SCRATCH=Path(scratch))


def listing(project):
    """Everything in the project's dist/, newest first."""
    root = WORKSPACE / project / DIST
    out = []
    if not root.is_dir():
        return out
    stack = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.name.startswith("."):
                continue
            if p.is_dir():
                if depth < MAX_DEPTH:
                    stack.append((p, depth + 1))
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            out.append({
                "path": str(p.relative_to(WORKSPACE / project)),
                "name": p.name,
                "kind": KINDS.get(p.suffix.lower(), "file"),
                "size": st.st_size,
                "at": int(st.st_mtime),
            })
    return sorted(out, key=lambda a: -a["at"])


def resolve(project, rel):
    """The absolute path of one artifact, or None for anything out of bounds.

    Resolved and prefix-checked rather than trusted: `rel` arrives from a
    browser, and a symlink inside dist/ pointing elsewhere must not turn the
    download endpoint into a file server for the whole box.
    """
    if not project or not rel:
        return None
    base = (WORKSPACE / project / DIST).resolve()
    try:
        p = (WORKSPACE / project / rel).resolve(strict=True)
    except OSError:
        return None
    if not str(p).startswith(str(base) + "/") and p.parent != base:
        return None
    if not str(p).startswith(str(base)):
        return None
    return p if p.is_file() else None


# The build that is live on the phone right now, as {(project, path): sha}.
# Kept only while its push session is: pushing the identical file into a live
# session would install nothing new, and saying so beats doing it — but once
# the session is stopped (or Firefox restarted with it), the same file is a
# legitimate thing to push again, so Stop clears this.
_live = {}


def xpi_sha(project, rel):
    import hashlib
    p = resolve(project, rel)
    if p is None:
        return None
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def live_matches(project, rel):
    sha = xpi_sha(project, rel)
    return sha is not None and _live.get((project, rel)) == sha


def set_live(project, rel):
    sha = xpi_sha(project, rel)
    if sha:
        _live[(project, rel)] = sha


def clear_live():
    _live.clear()


def unpack_xpi(project, rel):
    """An .xpi unpacked somewhere web-ext can run it, or an error.

    An XPI is a zip of exactly the unpacked-extension layout web-ext expects,
    so pushing one is: unzip, hand the directory over. Into the scratch area
    rather than beside the file — dist/ is the project's shipping shelf, and
    nothing here should write to it.
    """
    p = resolve(project, rel)
    if p is None or p.suffix.lower() != ".xpi":
        return None, "not an .xpi in this project's dist/"
    dest = SCRATCH / "xpi" / f"{project}-{int(time.time())}"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p) as z:
            # Guarded extraction: a hostile zip's ../ entries must not write
            # outside the scratch directory.
            for m in z.namelist():
                tgt = (dest / m).resolve()
                if not str(tgt).startswith(str(dest.resolve())):
                    return None, "that archive tries to write outside itself"
            z.extractall(dest)
    except (OSError, zipfile.BadZipFile) as e:
        return None, f"could not unpack it: {e}"
    if not (dest / "manifest.json").is_file():
        return None, "no manifest.json inside — not a WebExtension package"
    return dest, None
