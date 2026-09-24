#!/usr/bin/env python3
"""What a project has built, found in one place: its dist/ directory, and
each account's worktree's dist/, listed apart as builds made on a branch.

The convention is the feature. Build systems scatter their outputs (gradle
five directories deep, web-ext into web-ext-artifacts/, cargo into target/)
and a tab that went looking for all of those would be a catalogue of build
systems that is wrong the week a new one arrives. So the deal is one word
long: **a project puts what it ships in dist/**, and this lists dist/ and
nothing else. A session that builds an APK copies it there; the template
tells it so. An empty tab on a project that builds things means the copy
step is missing, and the tab says exactly that rather than guessing.

Kinds are by extension, and the kind is what decides the actions offered:
everything can be downloaded, an .xpi can additionally be pushed to the
paired phone (unpacked into a scratch directory and handed to web-ext, since
an XPI is a zip of exactly the source layout web-ext runs), and a script can
be read without leaving the tab.

A script is the one kind that cannot be settled by extension alone: a shipped
shell installer is as often `dist/install` as `dist/install.sh`, and the thing
that actually says so is the shebang on its first line. So a file whose
extension this module does not know is opened and its first two bytes read.
Nothing is executed from here, ever: the tab downloads and it reads.
"""
import io
import os
import re
import subprocess
import time
import zipfile
from pathlib import Path

WORKSPACE = None
WORKTREES = None          # <workspace>/.worktrees: each account's tree, by uid

DIST = "dist"
UID_RE = re.compile(r"^u_[0-9a-f]{8}$")

# Extension -> kind. A short list on purpose: these are the things this
# operator's projects actually produce, and an unknown extension still shows
# (as "file", download only) rather than being hidden.
KINDS = {
    ".apk": "apk", ".aab": "aab", ".xpi": "xpi",
    ".ipa": "ipa", ".deb": "deb", ".rpm": "rpm",
    ".exe": "exe", ".msi": "msi", ".dmg": "dmg", ".appimage": "appimage",
    ".sh": "script", ".bash": "script", ".zsh": "script", ".ps1": "script",
}

# How much of a script the View control will show. A shipped installer is a
# few tens of kilobytes; past this it is a build output somebody should
# download, and holding a megabyte of text in a sheet helps nobody.
MAX_VIEW = 256 * 1024

# How deep inside dist/ to look. Two levels allows dist/android/app.apk
# without inviting a build tree to be symlinked in whole.
MAX_DEPTH = 2


def configure(*, workspace, worktrees=None):
    globals().update(WORKSPACE=Path(workspace),
                     WORKTREES=Path(worktrees) if worktrees else Path(workspace) / ".worktrees")


def _tree(project, tree=""):
    """The tree whose dist/ is meant: the project directory, or an account's
    worktree of it by uid, None for a uid that is not one (B237). A second
    account's session builds in its worktree, and its build lands there."""
    if not tree:
        return WORKSPACE / project
    if not UID_RE.match(str(tree)) or WORKTREES is None:
        return None
    return WORKTREES / project / str(tree)


def listing(project, tree=""):
    """Everything in the project's dist/, or a worktree's, newest first."""
    top = _tree(project, tree)
    out = []
    if top is None:
        return out
    root = top / DIST
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
            kind = KINDS.get(p.suffix.lower()) or _sniff(p)
            out.append({
                "path": str(p.relative_to(top)),
                "name": p.name,
                "kind": kind,
                # What the row may offer beyond Download. Sent rather than
                # derived in the page, so the one place that decides what a
                # file IS is also the place that decides what can be done
                # with it.
                "view": kind == "script" and st.st_size <= MAX_VIEW,
                "size": st.st_size,
                "at": int(st.st_mtime),
            })
    return sorted(out, key=lambda a: -a["at"])


def branches(project):
    """[{uid, branch, artifacts}] for each account's worktree of this project
    with something in its dist/ (B237). A second account's build lands in its
    worktree, where the tab used to never look, so its first build showed
    nothing. Listed apart from the project's own dist/, which is what ships:
    a branch's build is that branch's until it is merged."""
    out = []
    base = WORKTREES / project if WORKTREES else None
    if base is None or not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        if not UID_RE.match(d.name) or not d.is_dir():
            continue
        rows = listing(project, d.name)
        if rows:
            out.append({"uid": d.name, "branch": _branch_of(d), "artifacts": rows})
    return out


def _branch_of(tree):
    """The branch a worktree is on, read from its files and nothing run: its
    .git file names the worktree's git dir, whose HEAD names the branch."""
    try:
        g = (tree / ".git").read_text().strip()
        if not g.startswith("gitdir:"):
            return ""
        gd = Path(g[len("gitdir:"):].strip())
        head = ((gd if gd.is_absolute() else tree / gd) / "HEAD").read_text().strip()
    except OSError:
        return ""
    return head[len("ref: refs/heads/"):] if head.startswith("ref: refs/heads/") else ""


def _sniff(p):
    """"script" for a file that starts with a shebang, else "file".

    Only reached for an extension KINDS does not know, so an .apk is never
    opened to be asked what it is. Two bytes: this runs once per file in
    dist/ on every listing, and a listing is on a poll.
    """
    try:
        with open(p, "rb") as fh:
            return "script" if fh.read(2) == b"#!" else "file"
    except OSError:
        return "file"


def resolve(project, rel, tree=""):
    """The absolute path of one artifact, or None for anything out of bounds.

    Resolved and prefix-checked rather than trusted: `rel` and `tree` arrive
    from a browser, and a symlink inside dist/ pointing elsewhere must not
    turn the download endpoint into a file server for the whole box.
    """
    top = _tree(project, tree)
    if not project or not rel or top is None:
        return None
    base = (top / DIST).resolve()
    try:
        p = (top / rel).resolve(strict=True)
    except OSError:
        return None
    if not str(p).startswith(str(base) + "/") and p.parent != base:
        return None
    if not str(p).startswith(str(base)):
        return None
    return p if p.is_file() else None


def source_zip(project):
    """The code base as a zip, for the Artifacts tab's Download source:
    what git tracks plus what it would track (untracked files that are not
    ignored) under one top-level directory named for the project, and
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
                return {"error": f"the tree is over {SOURCE_CAP >> 20}MB before build output: "
                                 "something large is not ignored; .gitignore it, or fetch the "
                                 "repository with git instead"}
            z.write(fp, f"{project}/{f}")
    # A filename the header can carry: the quoted form is latin-1 and
    # unquoted characters end the token, so the name is reduced to the
    # safe set and the real project name stays inside the zip.
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", project) or "project"
    return f"{safe}-source-{sha or time.strftime('%Y%m%d-%H%M')}.zip", buf.getvalue()


SOURCE_CAP = 256 << 20
