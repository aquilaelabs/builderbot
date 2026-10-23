"""workspace.py: snapshots and the artifact store (docs/nodes.md §6, phase 6).

The tree is edited HERE (/workspace is the projects share, the only writable
copy) and built THERE, on a node. Nothing network-mounts /workspace onto a
node (§6 says why, four times over); instead a job carries a snapshot of the
working tree, dirty edits included, and the node materializes it into a
job-scoped directory that is deleted after. What a build produces comes
back the same way and lands in the project's dist/, which is already the one
place the Artifacts view reads, with a provenance record beside it saying
what built it, from what, and where.

What this module owns:

  - snapshot(project): the working tree as git sees it (tracked plus
    untracked, minus ignored and minus .git) as one uncompressed tar under
    /config/snapshots, named by its sha256. Uncompressed on purpose: the
    digest is of the bytes, and an unchanged tree makes byte-identical tar
    (owner and mode normalized, mtimes kept), so the node's by-digest cache
    means an unchanged tree transfers nothing. The last few per project are
    kept; a snapshot is a job's input and not a backup.
  - path_for(digest): what the agent's `source` verb serves.
  - artifact_put(job, name, body): a file a job uploaded, into dist/ under a
    name the node chose and this side sanitized, plus dist/.provenance/ with
    the chain (job, node, source digest, command, sha256).
  - bundle(): bb and its library plus the toolchain catalog as one tar, which
    is what a node needs to run `bb toolchains install` against its own toolchain
    store: the toolchain recipes stay in one catalog (§6) and travel to the
    node by digest, like the agent itself does.
"""

import hashlib
import json
import os
import re
import subprocess
import tarfile
import threading
import time
from pathlib import Path

import artifacts  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
WORKSPACE = None
SNAPS = None
paths = None              # set by server.py: paths.py, where what grows is kept
KEEP_PER_PROJECT = 5
ARTIFACT_MAX = 1024 * 1024 * 1024        # a gigabyte: an APK is 30MB, an installer 300
_lock = threading.Lock()
_bundle = {}
# The tool packs' catalog rows (toolpacks.catalog_json, R77), handed over by
# the server: the bundle carries them as config/toolpacks.json beside the
# shipped catalog, which is how a node installs a pack by name.
packs_json = None
# ...and the packs made on the controller, each a git bundle carried as
# config/toolpacks/NAME.bundle (toolpacks.hosted_files): [(arcname, path)].
packs_files = None


def configure(*, workspace, state):
    globals()["WORKSPACE"] = Path(workspace)
    globals()["SNAPS"] = Path(state) / "snapshots"


def _snaps():
    """Where jobs' trees are kept: the Settings page's choice when the server
    has handed this module paths.py, read at use so a move applies to the
    next one; the state directory's own otherwise (a module test)."""
    return paths.of("job-snapshots") if paths else SNAPS


# ---------------------------------------------------------------------------
# snapshots

def _files(root):
    """The files a snapshot carries. Git's view when there is one (tracked
    and untracked, minus ignored), so build/ and node_modules/ stay behind
    without anybody listing them; every file but .git otherwise. dist/ is
    left out either way: it is the shelf the artifacts come BACK to, and
    shipping last week's APK to the node for it to ignore is waste."""
    names = None
    if (root / ".git").exists():
        try:
            p = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached",
                                "--others", "--exclude-standard"],
                               capture_output=True, timeout=120, check=False)
            if p.returncode == 0:
                names = [n for n in p.stdout.decode("utf-8", "surrogateescape").split("\0") if n]
        except (OSError, subprocess.SubprocessError):
            names = None
    if names is None:
        names = []
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x != ".git"]
            for f in files:
                names.append(os.path.relpath(os.path.join(d, f), root))
    return sorted(n for n in set(names) if not n.startswith("dist/") and n != "dist")


def snapshot(project):
    """The tree, now, as one tar; {digest, files, bytes, tar} or {error}."""
    root = WORKSPACE / project
    if not root.is_dir():
        return {"error": f"no project directory for {project}"}
    files = _files(root)
    snaps = _snaps()
    snaps.mkdir(parents=True, exist_ok=True)
    tmp = snaps / f".{project}.{os.getpid()}.{threading.get_ident()}.tar"
    n = size = 0
    with open(tmp, "wb") as fh, tarfile.open(fileobj=fh, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for rel in files:
            p = root / rel
            try:
                if p.is_symlink():
                    # A link that stays inside the tree travels as a link
                    # (B281: the node built a different tree without them);
                    # one that points out of it is left behind, since the
                    # node's extraction refuses it and would refuse the lot.
                    target = os.readlink(p)
                    inside = (not os.path.isabs(target)
                              and not os.path.normpath(os.path.join(os.path.dirname(rel), target)).startswith(".."))
                    if not inside:
                        continue
                    ti = tar.gettarinfo(str(p), arcname=rel)
                    ti.uid = ti.gid = 0
                    ti.uname = ti.gname = ""
                    ti.mtime = int(ti.mtime)
                    tar.addfile(ti)
                    n += 1
                    continue
                if not p.is_file():
                    continue
                ti = tar.gettarinfo(str(p), arcname=rel)
            except OSError:
                continue
            # Normalized so the digest is of the tree and not of who owns it
            # on this box; mtimes are kept because build tools read them.
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            ti.mtime = int(ti.mtime)
            ti.mode = 0o755 if ti.mode & 0o100 else 0o644
            with open(p, "rb") as f:
                tar.addfile(ti, f)
            n += 1
            size += ti.size
    h = hashlib.sha256()
    with open(tmp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    hexd = h.hexdigest()
    final = snaps / f"{hexd}.tar"
    with _lock:
        os.replace(tmp, final)
        meta = {"project": project, "at": int(time.time()), "files": n,
                "bytes": size, "tar": final.stat().st_size}
        (snaps / f"{hexd}.json").write_text(json.dumps(meta))
        _prune(project)
    return {"digest": "sha256:" + hexd} | meta


def _prune(project):
    """Keep the newest few per project. A job still queued against an older
    one gets 'no such snapshot' from the node and fails plainly, which is
    the honest answer to a tree that has moved on five times since."""
    have = []
    for mp in _snaps().glob("*.json"):
        try:
            m = json.loads(mp.read_text())
        except (OSError, ValueError):
            continue
        if m.get("project") == project:
            have.append((m.get("at", 0), mp))
    have.sort(reverse=True)
    for _, mp in have[KEEP_PER_PROJECT:]:
        for p in (mp, mp.with_suffix(".tar")):
            try:
                p.unlink()
            except OSError:
                pass


def path_for(digest):
    """The tar for a digest, or None. The digest is the file name, so a
    node asking for one it made up gets nothing rather than a path."""
    m = re.fullmatch(r"(?:sha256:)?([0-9a-f]{64})", str(digest or ""))
    if not m or _snaps() is None:
        return None
    p = _snaps() / f"{m.group(1)}.tar"
    return p if p.is_file() else None


# ---------------------------------------------------------------------------
# artifacts

def _safe_name(name):
    """A dist/ path a node may write: at most two levels, plain characters,
    no dots-only parts. The node chose it from the job's outputs globs; this
    side decides whether it is a name at all."""
    parts = [p for p in str(name or "").replace("\\", "/").split("/") if p]
    if not parts or len(parts) > 2:
        return None
    for p in parts:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,120}", p) or set(p) <= {"."}:
            return None
    return "/".join(parts)


def artifact_put(job, name, stream, length, extra=None):
    """A file a job uploaded, into the project's dist/. {path, size, sha256}
    or {error}. Streamed to a temp file beside the target and renamed, so
    the tab never lists a half-written APK."""
    rel = _safe_name(name)
    if rel is None:
        return {"error": f"not a name an artifact may have: {name!r}"}
    project = (job or {}).get("project") or ""
    root = WORKSPACE / project
    if not project or not root.is_dir():
        return {"error": "the job has no project directory to land in"}
    if not 0 < length <= ARTIFACT_MAX:
        return {"error": f"an artifact is between 1 byte and {ARTIFACT_MAX >> 20}MB"}
    dest = root / "dist" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{job['id']}.part")
    h = hashlib.sha256()
    got = 0
    try:
        with open(tmp, "wb") as f:
            while got < length:
                chunk = stream.read(min(1 << 20, length - got))
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
        if got != length:
            tmp.unlink(missing_ok=True)
            return {"error": f"short upload: {got} of {length} bytes"}
        os.replace(tmp, dest)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        return {"error": f"could not write {rel}: {e.strerror}"}
    spec = job.get("spec") or {}
    prov = {"job": job["id"], "node": job.get("node", ""), "type": job.get("type", ""),
            "source": job.get("source") or {}, "argv": spec.get("argv") or [],
            "requested_by": job.get("requested_by", ""), "at": int(time.time()),
            "sha256": h.hexdigest(), "size": got, "path": "dist/" + rel}
    # What the job adds about it: a sign job, what signed it (R106).
    prov.update(extra or {})
    pdir = root / "dist" / ".provenance"
    try:
        (pdir / (rel + ".json")).parent.mkdir(parents=True, exist_ok=True)
        (pdir / (rel + ".json")).write_text(json.dumps(prov, indent=1))
    except OSError:
        pass                                 # the artifact landed; the chain is best effort
    # A build landing is when the older ones are superseded, not when the
    # tab is next opened (the operator, 6 Oct).
    if "/" not in rel:
        try:
            artifacts.sweep_dev_builds(project, artifacts.dev_keep(project) if artifacts.dev_keep else artifacts.DEV_KEEP)
        except Exception as e:  # noqa: BLE001 (the artifact landed; the sweep is housekeeping)
            print(f"dashboard: dist sweep of {project}: {e}", flush=True)
    return {"path": "dist/" + rel, "size": got, "sha256": h.hexdigest()}


def file_path(project, rel):
    """A file under the project's dist/ a node may fetch as a job input:
    an APK to install on its emulator, say. dist/ only: the tree travels as
    a snapshot, and nothing else of a project is a node's to read."""
    rel = str(rel or "").replace("\\", "/")
    if rel.startswith("dist/"):
        rel = rel[5:]
    safe = _safe_name(rel)
    if safe is None or WORKSPACE is None:
        return None
    root = artifacts.dist_dir(WORKSPACE / project)
    if root is None:
        return None
    p = (root / safe).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        return None
    return p if p.is_file() else None


def provenance(project, rel):
    """What built dist/<rel>, if a job did. None for a file somebody copied."""
    rel = str(rel or "")
    if rel.startswith("dist/"):
        rel = rel[5:]
    p = WORKSPACE / project / "dist" / ".provenance" / (rel + ".json")
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# the toolchain bundle

# bb-tty and the two hooks it writes into a session's settings ride along
# since roadmap #24: a node runs sessions from this same bundle. NOT the
# rest of scripts/dashboard (the notebook modules, users.py, server.py),
# because a node has no /config for them to read; the verbs that need them
# are relayed back here (server._bb_relay).
BUNDLE_PARTS = ("scripts/bb", "scripts/lib", "config/toolchains.json", "nodes/provision-linux.sh", "nodes/families",
                # The root helper that builds a session's view, which the
                # agent installs from here on a sandbox node (R35).
                "nodes/bb-session",
                "scripts/dashboard/bb-tty", "scripts/dashboard/bb-work-note",
                "scripts/dashboard/bb-prompt-relay", "scripts/dashboard/bb-check-relay",
                "scripts/dashboard/bb-rule-hook",
                # ...and the other coding agents' one hook, which runs these
                # (R95 step 6): their hooks files name it in this bundle.
                "scripts/dashboard/bb-agent-hook",
                # The gate, which refuses every tool call while the
                # controller is not answering, so a node's sessions stop for
                # an update the same way the controller's do.
                "scripts/dashboard/bb-gate")


def bundle():
    """bb, its library and the catalog as one tar: {body, digest}. Rebuilt
    when any of its files moves, so a node installing a toolchain runs the
    recipes this controller ships right now, by digest."""
    stamp = []
    for part in BUNDLE_PARTS:
        p = REPO / part
        if p.is_dir():
            stamp.extend(int(x.stat().st_mtime_ns) for x in sorted(p.rglob("*")) if x.is_file())
        elif p.is_file():
            stamp.append(int(p.stat().st_mtime_ns))
    packs = packs_json() if packs_json else ""
    hosted = packs_files() if packs_files else []
    stamp.extend(int(p.stat().st_mtime_ns) for _, p in hosted)
    key = hash((tuple(stamp), packs))
    if _bundle.get("key") != key:
        import io
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for part in BUNDLE_PARTS:
                p = REPO / part
                if not p.exists():
                    continue
                for f in ([p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file())):
                    ti = tar.gettarinfo(str(f), arcname=str(f.relative_to(REPO)))
                    ti.uid = ti.gid = 0
                    ti.uname = ti.gname = ""
                    with open(f, "rb") as fh:
                        tar.addfile(ti, fh)
            if packs:
                data = packs.encode("utf-8")
                ti = tarfile.TarInfo("config/toolpacks.json")
                ti.size, ti.mode, ti.mtime = len(data), 0o644, int(time.time())
                tar.addfile(ti, io.BytesIO(data))
            for arc, f in hosted:
                ti = tar.gettarinfo(str(f), arcname=arc)
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = ""
                ti.mode = 0o644
                with open(f, "rb") as fh:
                    tar.addfile(ti, fh)
        body = buf.getvalue()
        _bundle.update(key=key, body=body,
                       digest="sha256:" + hashlib.sha256(body).hexdigest())
    return {"body": _bundle["body"], "digest": _bundle["digest"]}
