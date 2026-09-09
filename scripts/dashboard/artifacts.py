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
import io
import os
import re
import subprocess
import time
import zipfile
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


def source_zip(project):
    """The code base as a zip, for the Artifacts tab's Download source:
    what git tracks plus what it would track — untracked files that are not
    ignored — under one top-level directory named for the project, and
    never .git itself, dist/ (the artifacts have their own downloads) or
    anything .gitignore hides, which is where build output, node_modules
    and caches live. Without git, the tree minus the directories every
    build system litters. Symlinks are skipped: one pointing out of the
    tree is not the code base, and the artifact download refuses the same
    trick. Built in memory, so it stops at SOURCE_CAP bytes with an error
    rather than hold a data directory somebody forgot to ignore: a code
    base fits; a tree that does not is not one. (name, bytes), None for no
    such project, or {"error"}."""
    root = (WORKSPACE / project).resolve()
    if not root.is_dir():
        return None
    files, sha = [], ""
    if (root / ".git").exists():
        p = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "-co", "--exclude-standard"],
                           capture_output=True, timeout=60, check=False)
        if p.returncode == 0:
            files = [f for f in p.stdout.decode("utf-8", "replace").split("\0") if f]
        q = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10, check=False)
        sha = q.stdout.strip() if q.returncode == 0 else ""
    if not files:
        skip = {".git", DIST, "node_modules", "build", ".gradle", "__pycache__", ".venv", "target", ".dart_tool"}
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in skip]
            for fn in fns:
                files.append(os.path.relpath(os.path.join(dp, fn), root))
    buf, total = io.BytesIO(), 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(set(files)):
            if f == DIST or f.startswith(DIST + "/"):
                continue
            fp = root / f
            if fp.is_symlink() or not fp.is_file():
                continue
            total += fp.stat().st_size
            if total > SOURCE_CAP:
                return {"error": f"the tree is over {SOURCE_CAP >> 20}MB before build output — "
                                 "something large is not ignored; .gitignore it, or fetch the "
                                 "repository with git instead"}
            z.write(fp, f"{project}/{f}")
    # A filename the header can carry: the quoted form is latin-1 and
    # unquoted characters end the token, so the name is reduced to the
    # safe set and the real project name stays inside the zip.
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", project) or "project"
    return f"{safe}-source-{sha or time.strftime('%Y%m%d-%H%M')}.zip", buf.getvalue()


SOURCE_CAP = 256 << 20
