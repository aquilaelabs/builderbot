#!/usr/bin/env python3
"""What a project has built, found in one place: its dist/ directory, and
each account's worktree's dist/, listed apart as builds made on a branch.

The convention is the feature. Build systems scatter their outputs (gradle
five directories deep, web-ext into web-ext-artifacts/, cargo into target/)
and a tab that went looking for all of those would be a catalog of build
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

What a session looks with is in dist/ too (R96): a reel's sheet under
dist/reel/NAME and an emulator shot under dist/emu, each with a record of
who asked and when. Those are not what the project ships, so the listing
leaves them out and the tab draws them as one Captures fold, and they go by
age: the project's "captures kept" days, swept here when the tab draws,
since nothing can tell whether another session is still reading one. The
rule is capture.py's (scripts/lib, loaded by path), the same one `bb
capture prune` applies on a node.
"""
import importlib.util
import io
import json
import os
import re
import subprocess
import threading
import time
import zipfile
from pathlib import Path

WORKSPACE = None
WORKTREES = None          # <workspace>/.worktrees: each account's tree, by uid
# What tab_view() composes, set by server.py: dist/ as the tab lists it with
# each file's provenance (the server's artifacts_of), account names by uid,
# what the project can and cannot do off this box (build_state), its dev
# instances' state (devactions, read in one scope), and the phone summary
# for its node and the asking account (phone.summary).
listing_of = None
account_names = None
build_state = None
instance_states = None
phone_summary = None

DIST = "dist"
UID_RE = re.compile(r"^u_[0-9a-f]{8}$")
# The project's "captures kept" days, set by server.py from prefs.
capture_days = None
# ...and how many dev builds of each kind it keeps (R105), from prefs too.
dev_keep = None
# The routes this project has a signing key for (signing.py, R106), set by
# the server: what Sign on an .apk or .aab row may offer.
sign_routes = None
# scripts/lib/capture.py, loaded by path: captures(dist) and prune(dist, days, names).
_capture = None

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


def configure(*, workspace, worktrees=None, capture=None, state=None, write_json=None):
    globals().update(WORKSPACE=Path(workspace),
                     WORKTREES=Path(worktrees) if worktrees else Path(workspace) / ".worktrees",
                     PINS=Path(state) / "artifact-pins.json" if state else None,
                     _write_json=write_json)
    path = Path(capture) if capture else Path(__file__).resolve().parent.parent / "lib" / "capture.py"
    spec = importlib.util.spec_from_file_location("bb_capture", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    globals()["_capture"] = mod


def _tree(project, tree=""):
    """The tree whose dist/ is meant: the project directory, or an account's
    worktree of it by uid, None for a uid that is not one (B237). A second
    account's session builds in its worktree, and its build lands there."""
    if not tree:
        return WORKSPACE / project
    if not UID_RE.match(str(tree)) or WORKTREES is None:
        return None
    return WORKTREES / project / str(tree)


def dist_dir(top):
    """The tree's dist/ as a real path, or None when it is not inside the
    tree: a dist that is a symlink to /config made the artifact download a
    file server for the controller (the audit of 26 Sep), since the base
    every check measured against was wherever the link pointed."""
    try:
        real, base = top.resolve(), (top / DIST).resolve()
    except OSError:
        return None
    if base != real / DIST and real not in base.parents:
        return None
    return base


def listing(project, tree=""):
    """Everything in the project's dist/, or a worktree's, newest first."""
    top = _tree(project, tree)
    out = []
    if top is None:
        return out
    root = dist_dir(top)
    if root is None or not root.is_dir():
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
                # The captures' own directories are the Captures fold's.
                if depth == 0 and p.name in _capture.CAPTURE_DIRS:
                    continue
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
    base = dist_dir(top)
    if base is None:
        return None
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


# ---- the captures: listed apart, swept by age, let go by name ---------------------

def captures_of(project):
    """The project's captures as the tab's fold lists them, after the sweep:
    each {name, kind, path (under dist/), at, by, node, size}, newest first,
    and the days the project keeps them. The sweep runs here, on the read
    that shows them, so a capture is never removed by anything a person is
    not looking at."""
    root = dist_dir(WORKSPACE / project)
    days = capture_days(project) if capture_days else 7
    if root is None or not root.is_dir():
        return {"captures": [], "capture_days": days}
    try:
        _capture.prune(str(root), days)
        rows = _capture.captures(str(root))
    except OSError:
        rows = []
    return {"captures": [{k: v for k, v in c.items() if k != "file"} | {"path": f"{DIST}/{c['path']}"}
                         for c in rows],
            "capture_days": days}


def forget_capture(project, name):
    """One capture removed now, by the person who decided: the tab's
    Remove. (payload, status)."""
    root = dist_dir(WORKSPACE / project)
    name = str(name or "")
    if root is None or not root.is_dir() or not name:
        return {"error": "no such capture"}, 404
    gone = _capture.prune(str(root), None, {name})
    if not gone:
        return {"error": f"no capture named {name}: it may have been removed already"}, 404
    return {"ok": True, "removed": name}, 200


# ---- the tab's read and its downloads, one call each from the dashboard --------

# ---- pins: an artifact a person does not want to lose --------------------------
# {project: {path under the project, "dist/...": {by, at}}}, under /config, so
# a pin is the controller's record of a person's choice and not a file in the
# tree a build or a session could overwrite. A pinned artifact is never swept
# and does not count toward the dev builds kept beside it (the operator, 30
# Sep). A pin on a file that is gone is left and harmless: the listing only
# marks files that are there.
PINS = None
_write_json = None
_pins_lock = threading.Lock()


def _pins_all():
    try:
        with open(PINS, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def pins(project):
    """{path: {by, at}} pinned in this project's dist/."""
    got = _pins_all().get(project) if PINS else None
    return got if isinstance(got, dict) else {}


def pin(project, rel, on, by=""):
    """Pin or unpin one artifact in the project's dist/. (payload, status)."""
    if PINS is None or _write_json is None:
        return {"error": "pins are not kept on this controller"}, 500
    rel = str(rel or "")
    f = resolve(project, rel)
    if on and f is None:
        return {"error": "no such artifact"}, 404
    if rel.split("/")[1:2] and rel.split("/")[1] in _capture.CAPTURE_DIRS:
        return {"error": "a capture goes by the project's days; pin what the project ships"}, 400
    with _pins_lock:
        d = _pins_all()
        mine = d.get(project) if isinstance(d.get(project), dict) else {}
        if on:
            mine[rel] = {"by": str(by or "")[:60], "at": int(time.time())}
        else:
            mine.pop(rel, None)
        if mine:
            d[project] = mine
        else:
            d.pop(project, None)
        _write_json(PINS, d)
    return {"ok": True, "path": rel, "pinned": bool(on)}, 200


# ---- dev builds: the newest few of each (R105) ---------------------------------
# A dev build carries its version in its name the way bb version --file
# spells it (0.1.0-dev.17-9e09ad3, -dirty when the tree was), and a session
# building all day leaves one file per build: seven debug APKs, 133 MB, in
# one day on Shebang-DevBoard (30 Sep). Files that are one build of the same
# thing differ only in that version, so the name with it taken out is the
# kind; of each kind the newest few stay (the project's "dev builds kept",
# DEV_KEEP unless it says; 0 keeps them all) and the rest go when the tab
# draws, like captures. A release (no -dev.N) is never swept, nor a file
# whose name carries no version: nothing here can tell those are superseded.
DEV_KEEP = 3
DEV_VERSION = re.compile(r"(?<![0-9A-Za-z])\d+\.\d+\.\d+-dev\.\d+-[0-9a-f]{7,40}(?:-dirty)?(?![0-9A-Za-z])")


def dev_kind(name):
    """The name with its dev version taken out, or None for a file that is
    not a dev build."""
    m = DEV_VERSION.search(name)
    return None if m is None else name[:m.start()] + "*" + name[m.end():]


def sweep_dev_builds(project, keep=DEV_KEEP):
    """The dev builds of each kind past the newest `keep`, removed from the
    project's dist/ (its top level only, where a build lands). Returns the
    names removed."""
    root = dist_dir(WORKSPACE / project) if WORKSPACE else None
    if root is None or not root.is_dir():
        return []
    kinds = {}
    for p in root.iterdir():
        k = dev_kind(p.name) if p.is_file() and not p.name.startswith(".") else None
        if k is None:
            continue
        try:
            kinds.setdefault(k, []).append((p.stat().st_mtime, p))
        except OSError:
            continue
    # A pinned one is kept, and is not one of the `keep` beside it.
    held = {Path(r).name for r in pins(project) if r.count("/") == 1}
    gone = []
    for rows in kinds.values():
        rows = [r for r in rows if r[1].name not in held]
        for _, p in sorted(rows, key=lambda r: -r[0])[keep:]:
            try:
                p.unlink()
                gone.append(p.name)
            except OSError:
                pass
    return sorted(gone)


def tab_view(name, uid):
    """The Artifacts tab's whole read for one project, as account `uid`
    sees it: what it built, each account's own builds from its worktree
    (B237) apart from dist/, which is what ships, what the project can and
    cannot do off this box, its dev instances, and the phone."""
    keep = dev_keep(name) if dev_keep else DEV_KEEP
    if keep:
        sweep_dev_builds(name, keep)
    held = pins(name)
    return ({"artifacts": [a | ({"pinned": True, "pinned_by": held[a["path"]].get("by", "")}
                                if a.get("path") in held else {}) for a in listing_of(name)],
             "dev_keep": keep,
             "sign_routes": sign_routes(name) if sign_routes else [],
             "branches": [g | {"who": account_names().get(g["uid"], g["uid"])}
                          for g in branches(name)],
             "build": build_state(name)}
            | captures_of(name) | instance_states(name) | phone_summary(name, uid))


def download(name, rel, tree=""):
    """One file for the download: ((filename, bytes), 200), or an error and
    its status. Resolved and prefix-checked in resolve(): a symlink inside
    dist/ must not turn this into a file server for the whole box. `tree`
    is an account's worktree by uid, for a build made there (B237)."""
    f = resolve(name, rel, tree)
    if f is None:
        return {"error": "no such artifact"}, 404
    try:
        data = f.read_bytes()
    except OSError as e:
        return {"error": str(e)}, 500
    # A name with a quote or a line break would end the header early.
    return (re.sub(r"[^A-Za-z0-9._ -]", "_", f.name)[:200], data), 200


def source_download(name):
    """The code base as a zip for the download: ((filename, bytes), 200), or
    an error and its status. What git tracks and would track, never .git,
    dist/ or what .gitignore hides."""
    try:
        got = source_zip(name)
    except (OSError, subprocess.SubprocessError) as e:
        return {"error": str(e)}, 500
    if got is None:
        return {"error": "no such project"}, 404
    if isinstance(got, dict):
        return got, 413
    return got, 200
