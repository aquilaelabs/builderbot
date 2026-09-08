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
from pathlib import Path

WORKSPACE = None

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


def configure(*, workspace):
    globals().update(WORKSPACE=Path(workspace))


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


