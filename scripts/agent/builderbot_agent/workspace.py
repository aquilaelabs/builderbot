"""The workspace (docs/nodes.md section 6): a job's source on disk, its artifacts, and the bundle of bb."""
import contextlib
import glob
import hashlib
import os
import re
import shutil
import tarfile
from .base import ROOT_BUNDLE_DIR, ROOT_TOOLS, TOOLS_DIR, log
from .stores import dir_bytes, tc_root


class WorkspaceMixin:
    """Agent's workspace methods: one of the parts class Agent (agent.py) is made of."""

    # -- the workspace (docs/nodes.md §6, phase 6) ------------------------------
    def own_dir(self, path, who):
        """Make a directory the enrolled account can use: a job runs as it,
        and this process is root."""
        os.makedirs(path, exist_ok=True)
        if who:
            with contextlib.suppress(OSError):
                os.chown(path, who["user"], who["group"])

    def materialize(self, job, src, who):
        """The job's source, on disk: the snapshot by digest, from the
        cache store when this node has fetched it before and from the
        controller otherwise, checked against its digest either way, then
        unpacked into a directory of the job's own under the data store."""
        stores = self.state.get("stores") or {}
        digest = str(src.get("digest") or "")
        hexd = digest.split(":", 1)[-1]
        if not re.fullmatch(r"[0-9a-f]{64}", hexd):
            job.say(f"refused: not a snapshot digest: {digest!r}\n")
            return None
        snaps = os.path.join(stores.get("cache") or "/tmp", "snapshots")
        os.makedirs(snaps, exist_ok=True)
        tar_path = os.path.join(snaps, hexd + ".tar")
        if not os.path.isfile(tar_path):
            job.say(f"fetching snapshot {hexd[:12]}…\n")
            st, _ = self.ctl.fetch(f"source?digest={hexd}", tar_path)
            if st != 200:
                job.say(f"the controller has no snapshot {hexd[:12]} ({st}): the tree "
                        "has moved on; queue the job again\n")
                return None
        h = hashlib.sha256()
        with open(tar_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != hexd:
            os.remove(tar_path)
            job.say("the cached snapshot did not match its digest; dropped it. Queue the job again\n")
            return None
        ws = os.path.join(stores.get("data") or "/tmp", "jobs", job.job["id"], "workspace")
        shutil.rmtree(os.path.dirname(ws), ignore_errors=True)
        os.makedirs(ws)
        with tarfile.open(tar_path) as tar:
            # Python 3.12's filter refuses paths that escape the target;
            # older interpreters get the members checked by hand.
            if hasattr(tarfile, "data_filter"):
                tar.extractall(ws, filter="data")
            else:
                for m in tar.getmembers():
                    if m.name.startswith("/") or ".." in m.name.split("/"):
                        raise RuntimeError(f"snapshot member escapes the workspace: {m.name}")
                tar.extractall(ws)
        if who:
            for d, _dirs, files in os.walk(os.path.dirname(ws)):
                for x in [d] + [os.path.join(d, f) for f in files]:
                    with contextlib.suppress(OSError):
                        os.lchown(x, who["user"], who["group"])
        return ws

    def finish_workspace(self, job, ws, spec, state):
        """After the command: on success upload what the outputs globs
        match and delete the job's directory; on failure keep it for
        inspection and drop the older kept one for the same project, so
        a run of failures does not fill the store."""
        jobdir = os.path.dirname(ws)
        project = str((job.job.get("source") or {}).get("project") or "")
        # What the build took on this node, its workspace and the project's
        # cache as it left them, measured before the workspace goes: the
        # Artifacts view shows it and the next build's room check wants at
        # least that much free (R110 step 7).
        cache = os.path.join(((self.state.get("stores") or {}).get("cache") or "/tmp"),
                             re.sub(r"[^A-Za-z0-9._-]", "_", project or "project"))
        took = {"kind": "room", "workspace": dir_bytes(jobdir), "cache": dir_bytes(cache)}
        if took["workspace"] is not None:
            job.outputs.append(took)
        if state == "succeeded":
            self.deliver(job, ws, spec.get("outputs") or [])
            shutil.rmtree(jobdir, ignore_errors=True)
            return
        # Kept: this one. Dropped: any earlier kept failure of the same project.
        marker = os.path.join(jobdir, "project")
        with contextlib.suppress(OSError):
            with open(marker, "w") as f:
                f.write(project)
        jobs_root = os.path.dirname(jobdir)
        for other in os.listdir(jobs_root) if os.path.isdir(jobs_root) else []:
            od = os.path.join(jobs_root, other)
            if od == jobdir or other in self.jobs:
                continue
            try:
                with open(os.path.join(od, "project")) as f:
                    if f.read() == project:
                        shutil.rmtree(od, ignore_errors=True)
            except OSError:
                continue
        job.say(f"the workspace is kept at {ws} for a look; the next failure of "
                f"{project or 'this project'} replaces it\n")
        job.outputs.append({"kind": "workspace", "path": ws})

    def deliver(self, job, base, outputs):
        """Upload what the outputs globs match under `base` as artifacts.
        dist/<basename>, which is what a person looks for; two matches
        sharing a name are told apart by the directory the second came
        from, so a debug and a release APK of the same name both arrive."""
        seen = set()
        for pat in list(outputs)[:16]:
            for hit in sorted(glob.glob(os.path.join(base, str(pat)), recursive=True)):
                if not os.path.isfile(hit):
                    continue
                rel = os.path.relpath(hit, base)
                name = os.path.basename(rel)
                if name in seen:
                    parent = os.path.basename(os.path.dirname(rel)) or "2"
                    name = f"{parent}-{name}"
                seen.add(name)
                st, r = self.ctl.upload(f"artifact?job={job.job['id']}&name={name}", hit)
                if st == 200 and not r.get("error"):
                    job.say(f"artifact {r['path']} ({os.path.getsize(hit)} bytes)\n")
                    job.outputs.append({"kind": "artifact", "path": r["path"],
                                        "size": r.get("size"), "sha256": r.get("sha256")})
                else:
                    job.say(f"could not deliver {rel}: {r.get('error') or st}\n")

    def bundle(self, job, who):
        """bb, its library and the catalog, from the controller by digest
        into the toolchain store; the directory it runs from, or '' when it
        could not be fetched. Shared by toolchain jobs, bb verbs, and (with
        no job, so `job` may be None and the log is this process's) the
        sessions this node runs (roadmap #24). `.bb/current` points at the
        newest unpacked copy, which is what a shell on this node puts on its
        PATH."""
        say = job.say if job else (lambda t: log(t.rstrip("\n")))
        store = tc_root(self.state)
        if not store:
            say("refused: this node has no toolchain store\n")
            return ""
        self.own_dir(store, who)
        bbdir = os.path.join(store, ".bb")
        os.makedirs(bbdir, exist_ok=True)
        # The tar lands where only root writes when this agent is root: a
        # path in the job's store is the job's to replace with a symlink.
        root = os.geteuid() == 0
        if root:
            os.makedirs(TOOLS_DIR, mode=0o700, exist_ok=True)
            os.chmod(TOOLS_DIR, 0o700)
        tar_path = os.path.join(TOOLS_DIR if root else bbdir, "bundle.tar")
        st, digest = self.ctl.fetch("download?what=bundle", tar_path)
        if st != 200:
            say(f"could not fetch bb from the controller ({st})\n")
            return ""
        hexd = digest.split(":", 1)[-1]
        # The bytes are what the header says they are, or nothing here runs
        # them: the digest names the bundle everywhere else.
        h = hashlib.sha256()
        with open(tar_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if not hexd or h.hexdigest() != hexd:
            say(f"refused: the bundle's bytes do not match the digest the controller named ({hexd[:12]})\n")
            with contextlib.suppress(OSError):
                os.unlink(tar_path)
            return ""
        if root:
            self._keep_root_tools(tar_path, hexd[:16] or "bundle", say)
            self._keep_root_bundle(tar_path, hexd[:16] or "bundle", say)
        into = os.path.join(bbdir, hexd[:16] or "bundle")
        if not os.path.isdir(into):
            with tarfile.open(tar_path) as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(into, filter="data")
                else:
                    tar.extractall(into)
            os.chmod(os.path.join(into, "scripts", "bb"), 0o755)
            for x in ("bb-tty", "bb-work-note", "bb-prompt-relay"):
                with contextlib.suppress(OSError):
                    os.chmod(os.path.join(into, "scripts", "dashboard", x), 0o755)
            say(f"bb {hexd[:12]} unpacked into {into}\n")
        with contextlib.suppress(OSError):
            tmp = os.path.join(bbdir, ".current.new")
            if os.path.lexists(tmp):
                os.unlink(tmp)
            os.symlink(os.path.basename(into), tmp)
            os.replace(tmp, os.path.join(bbdir, "current"))
        if who:
            for d, _dirs, files in os.walk(into):
                for x in [d] + [os.path.join(d, f) for f in files]:
                    with contextlib.suppress(OSError):
                        os.lchown(x, who["user"], who["group"])
        # Fetched by a job while the terminals open an older copy: leave the
        # change to the loop's session_check, which owns the session half;
        # this may be a job's thread. Without this the terminals opened
        # whatever bundle they were set up on until the next hello, up to ten
        # minutes, and a bb-tty that old looked for a transcript where the
        # bundle before it kept them.
        self.prune_bundles(bbdir, into)
        if self.session_up and self.session_bundle and digest != self.session_bundle:
            self.session_stale = into
        self.session_digest = digest
        return into

    @staticmethod
    def _keep_root_tools(tar_path, name, say):
        """Root's own copy of the tools it installs, lifted straight out of
        the checked tar into TOOLS_DIR/<name>/, and TOOLS_DIR/current pointed
        at it; the copies of other bundles go."""
        into = os.path.join(TOOLS_DIR, name)
        try:
            with tarfile.open(tar_path) as tar:
                for m in tar.getmembers():
                    rel = m.name.lstrip("./")
                    # ...and the provisioner's family files (R204), which it
                    # sources from beside itself.
                    if (rel not in ROOT_TOOLS and not rel.startswith("nodes/families/")) or not m.isfile():
                        continue
                    dest = os.path.join(into, rel)
                    os.makedirs(os.path.dirname(dest), mode=0o700, exist_ok=True)
                    src = tar.extractfile(m)
                    if src is None:
                        continue
                    fd = os.open(dest + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, "wb") as out:
                        shutil.copyfileobj(src, out)
                    os.replace(dest + ".new", dest)
            tmp = os.path.join(TOOLS_DIR, ".current.new")
            if os.path.lexists(tmp):
                os.unlink(tmp)
            os.symlink(name, tmp)
            os.replace(tmp, os.path.join(TOOLS_DIR, "current"))
            for other in os.listdir(TOOLS_DIR):
                if other not in (name, "current", "bundle.tar") and os.path.isdir(os.path.join(TOOLS_DIR, other)):
                    shutil.rmtree(os.path.join(TOOLS_DIR, other), ignore_errors=True)
        except (OSError, tarfile.TarError) as e:
            say(f"could not keep root's copy of the bundle's tools: {e}\n")

    @staticmethod
    def _keep_root_bundle(tar_path, name, say):
        """The whole bundle, root-owned and nobody else's to write, unpacked
        from the checked tar into ROOT_BUNDLE_DIR/<name>/ and current pointed
        at it (R125): what bb-session tty starts a terminal from. The two
        before it are kept for the terminals still running them."""
        into = os.path.join(ROOT_BUNDLE_DIR, name)
        try:
            os.makedirs(ROOT_BUNDLE_DIR, mode=0o755, exist_ok=True)
            os.chmod(ROOT_BUNDLE_DIR, 0o755)
            if not os.path.isdir(into):
                tmp = into + ".new"
                shutil.rmtree(tmp, ignore_errors=True)
                with tarfile.open(tar_path) as tar:
                    if hasattr(tarfile, "data_filter"):
                        tar.extractall(tmp, filter="data")
                    else:
                        tar.extractall(tmp)
                for d, dirs, files in os.walk(tmp):
                    for x in [d] + [os.path.join(d, f) for f in dirs + files]:
                        if os.path.islink(x):
                            continue
                        os.chown(x, 0, 0)
                        st = os.stat(x)
                        os.chmod(x, (st.st_mode & 0o755) | (0o755 if os.path.isdir(x) else 0o644))
                for x in ("scripts/bb", "scripts/dashboard/bb-tty", "scripts/dashboard/bb-work-note",
                          "scripts/dashboard/bb-prompt-relay"):
                    with contextlib.suppress(OSError):
                        os.chmod(os.path.join(tmp, x), 0o755)
                os.replace(tmp, into)
            link = os.path.join(ROOT_BUNDLE_DIR, ".current.new")
            if os.path.lexists(link):
                os.unlink(link)
            os.symlink(name, link)
            os.replace(link, os.path.join(ROOT_BUNDLE_DIR, "current"))
            kept = sorted((d for d in os.listdir(ROOT_BUNDLE_DIR)
                           if d not in (name, "current") and not d.startswith(".")
                           and os.path.isdir(os.path.join(ROOT_BUNDLE_DIR, d))),
                          key=lambda d: os.path.getmtime(os.path.join(ROOT_BUNDLE_DIR, d)), reverse=True)
            for old in kept[2:]:
                shutil.rmtree(os.path.join(ROOT_BUNDLE_DIR, old), ignore_errors=True)
        except (OSError, tarfile.TarError) as e:
            say(f"could not keep root's copy of the bundle: {e}\n")

    @staticmethod
    def prune_bundles(bbdir, keep):
        """Drop the bundles nothing is going to run again.

        Every delivery unpacks into a directory named for its digest, and
        nothing removed them: 33 of them in four days on the first node to be
        looked at, one per commit that touches bb. Small each, unbounded
        together.

        What has to survive: the newest, which the terminals run and `current`
        names, and the three newest, which versions() probes for an SDK
        inventory. A shell holds `current` on its PATH, never a digest, so
        nothing older is run again.
        """
        keep_n = 5
        try:
            names = [d for d in os.listdir(bbdir) if len(d) == 16
                     and all(c in "0123456789abcdef" for c in d)]
            dirs = [os.path.join(bbdir, d) for d in names
                    if os.path.isdir(os.path.join(bbdir, d))]
            dirs.sort(key=os.path.getmtime, reverse=True)
        except OSError:
            return
        for d in dirs[keep_n:]:
            with contextlib.suppress(OSError):
                if d != keep:
                    shutil.rmtree(d)

    def artifact_dir(self, project, who=None, make=True):
        """This node's copy of one project's artifacts. Per project, because
        a node may be several projects' node and two of them may both ship
        an app-release.apk."""
        root = (self.state.get("stores") or {}).get("artifacts") or ""
        if not root:
            return ""
        name = re.sub(r"[^A-Za-z0-9._-]", "_", str(project or "")) or "_"
        d = os.path.join(root, name)
        if make:
            self.own_dir(d, who)
        return d
