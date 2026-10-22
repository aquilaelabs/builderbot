"""The jobs that do a project's work: compose, toolchains, signing, images and system packages."""
import base64
import contextlib
import errno
import glob
import os
import re
import shutil
import stat
import subprocess
import time
import urllib.request
import zipfile
from . import keyops, storage
from .base import DRIVER, SANDBOX_BIN, TOOLKIT
from .stores import tc_root, tc_scope
from .backends import pkg_backend
from .toolchains import held_recipes, read_catalog, sdk_env, sysdeps_missing, tc_dir, tc_users, tc_users_said, tc_verbs
from .gpu import DRIVER_PKG, _gpu_card


# More names than the catalog has recipes is a request that is wrong, not a
# batch to trim.
TC_NAMES_MAX = 64



def cache_age_days(path):
    """Days since a job last used a project's cache directory: its .used
    stamp, else the directory's own time; 0 for one that cannot be read,
    so a prune by age leaves it alone."""
    for p in (os.path.join(path, ".used"), path):
        with contextlib.suppress(OSError):
            return max(0.0, (time.time() - os.stat(p).st_mtime) / 86400)
    return 0.0

class WorkMixin:
    """Agent's project-work jobs: one of the parts class Agent (agent.py) is made of."""

    # -- compose, locally (docs/nodes.md §7; roadmap #18) ----------------------
    def compose(self, job, spec):
        """One dev-instance action, run with the node's OWN docker.

        The controller still decides WHAT: it sends an ordered plan of argvs
        with the compose file and env beside them, and does the bookkeeping
        when this ends. What moved here is the execution, which is the whole
        point, because it is what let a node need an ssh key from the
        controller on top of the token it enrolled with. Nothing dials in
        now; docker is local.
        """
        if not shutil.which("docker"):
            job.say("refused: this node has no docker\n")
            return "failed", 78
        name = re.sub(r"[^A-Za-z0-9._-]", "_", str(spec.get("name") or "compose"))
        cdir = os.path.join((self.state.get("stores") or {}).get("data") or "/tmp",
                            "compose", name)
        who = self.drop_privileges({})
        self.own_dir(cdir, who)
        job.say(f"compose for {name} in {cdir}\n")
        # The compose file and the env, as the controller holds them: this
        # node never reads the project's tree for them, so a file edited on
        # the controller is the one that runs here.
        for fname, body in (spec.get("files") or {}).items():
            base = os.path.basename(str(fname))
            if not base or base.startswith("."):
                base = base or "file"
            path = os.path.join(cdir, base)
            with open(path, "w") as f:
                f.write(str(body))
            if who:
                with contextlib.suppress(OSError):
                    os.chown(path, who["user"], who["group"])
            job.say(f"wrote {base} ({len(str(body))} bytes)\n")
        # The bind directories, made here rather than by a throwaway
        # container over ssh: this process is already on the machine that
        # has them, and docker creating a missing bind source as root is the
        # failure the whole mechanism exists to avoid.
        for d in (spec.get("dirs") or [])[:32]:
            d = str(d)
            if not d.startswith("/") or ".." in d.split("/"):
                job.say(f"skipping a bind directory that is not a plain path: {d}\n")
                continue
            # A socket or a device that is there (the daemon's socket) is
            # bound as it is: making it a directory can only fail, and that
            # ended every compose that mounted /var/run/docker.sock (diag
            # report #117). A plain file where a directory should be still
            # fails below, before the plan runs.
            with contextlib.suppress(OSError):
                mode = os.stat(d).st_mode
                if stat.S_ISSOCK(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
                    job.say(f"bind source {d} is a socket or a device, bound as it is\n")
                    continue
            try:
                # Only a directory this step makes is given to the session
                # account. One that was there already is somebody's: the
                # config directory of a container running as another user,
                # or a tree an administrator just chowned on request, and
                # handing it to the agent's account on every rebuild broke
                # the containers that owned it (B315).
                had = os.path.isdir(d)
                os.makedirs(d, exist_ok=True)
                if who and not had:
                    with contextlib.suppress(OSError):
                        os.chown(d, who["user"], who["group"])
                job.say(f"bind directory {d}" + (" (already there, left as it is)" if had else "") + "\n")
            except OSError as e:
                # A bind source this machine cannot make. Whether that ends
                # the job depends on whether docker could do better: it runs
                # as root, so an agent that is root and failed has proved
                # docker will fail too, and a stale NFS handle or a file in
                # the way defeats any privilege. Then the up cannot work and
                # is not tried: docker would report the same mkdir in worse
                # words ("mkdir /devdata: file exists" over a stale handle,
                # measured 15 Sep). An unprivileged agent (a guest node)
                # names it and carries on, since docker may still make it.
                why = e.strerror or str(e)
                hopeless = (os.geteuid() == 0 or e.errno == errno.ESTALE
                            or isinstance(e, (NotADirectoryError, FileExistsError)))
                hint = (": the mount under it is stale; remount it on this node"
                        if e.errno == errno.ESTALE or "stale" in why.lower() else "")
                if not hopeless:
                    job.say(f"could not make {d}: {why}; this agent is not root, so docker may still\n")
                    continue
                job.say(f"could not make {d}: {why}{hint}\n")
                job.outputs.append({"kind": "compose", "steps_done": 0, "failed_at": "preparing"})
                return "failed", 73
        done = 0
        for stp in (spec.get("plan") or [])[:8]:
            if job.canceled:
                job.say("stopped\n")
                job.outputs.append({"kind": "compose", "steps_done": done})
                return "canceled", 130
            # An image shipped between two nodes (R166): the build node
            # uploads what it saved to the controller, and the node the
            # instance lives on fetches it, so the project's source never
            # reaches a node that does not hold the project. The file is the
            # job's alone: named under its own compose directory, and removed
            # here once it has gone up.
            if stp.get("upload") or stp.get("fetch"):
                job.step(str(stp.get("name") or "shipping"))
                st_, code = self.ship_step(job, stp, cdir)
                if st_ != "succeeded":
                    job.outputs.append({"kind": "compose", "steps_done": done,
                                        "failed_at": stp.get("name")})
                    return st_, code
                done += 1
                continue
            argv = [str(a).replace("{cdir}", cdir) for a in (stp.get("argv") or [])]
            if not argv:
                continue
            job.step(str(stp.get("name") or "working"))
            # The command, then its output: a log of output with no command
            # is unreadable, and the controller's own runner has always
            # written this line.
            job.say("$ " + " ".join(argv) + "\n")
            # The agent's OWN environment is the base here, unlike an exec
            # job: docker on this node should behave as it does for the
            # account that runs it, since a proxy, a DOCKER_CONFIG, a rootless
            # socket are all the node's own arrangement, and a compose that
            # ignored them would work by luck. Not who it is, though: the
            # job's drop gives HOME, USER and LOGNAME their account's, and
            # OpenRC hands a root service HOME=/root, which docker run as
            # another account cannot read and then finds no compose plugin.
            env = {k: v for k, v in os.environ.items() if k not in ("HOME", "USER", "LOGNAME")}
            env.update(sdk_env(self.state))
            env.update({k: str(v).replace("{cdir}", cdir)
                        for k, v in (stp.get("env") or {}).items()})
            st_, code = job.exec({"argv": argv, "cwd": cdir, "env": env,
                                  "timeout": stp.get("timeout") or 1800})
            if st_ != "succeeded":
                job.outputs.append({"kind": "compose", "steps_done": done,
                                    "failed_at": stp.get("name")})
                return st_, code
            done += 1
        job.outputs.append({"kind": "compose", "steps_done": done})
        return "succeeded", 0

    def ship_step(self, job, stp, cdir):
        """One half of shipping an image (R166): `upload` sends a file under
        this job's compose directory to the controller and removes it here;
        `fetch` brings one down into it. The path never leaves the compose
        directory, and the controller's verb is the only one either names."""
        path = str(stp.get("upload") or stp.get("dest") or "").replace("{cdir}", cdir)
        real = os.path.realpath(path)
        if not real.startswith(os.path.realpath(cdir) + "/"):
            job.say(f"refused: {path} is not in this job's directory\n")
            return "failed", 78
        verb = str(stp.get("to") or stp.get("fetch") or "")
        # The image a shipped instance runs (R166), or the data a copied or
        # moved one carries (relocate.py on the controller).
        if not verb.startswith(("devimage", "devdata")):
            job.say(f"refused: not the controller's image or data verb: {verb[:40]}\n")
            return "failed", 78
        what = "the data" if verb.startswith("devdata") else "the image"
        if stp.get("upload"):
            if not os.path.isfile(real):
                job.say(f"nothing to send: {path} is not there\n")
                return "failed", 66
            size = os.path.getsize(real)
            job.say(f"sending {what} to the controller ({size >> 20} MB)\n")
            if self.state.get("reach") == "public" and verb.startswith("devdata"):
                # A tunnel's edge may cap a request's body (Cloudflare: 100
                # MB, R170): in pieces.
                code, r = self.ctl.upload_pieces(verb, real, 64 << 20, timeout=int(stp.get("timeout") or 3600),
                                                 say=lambda off: job.say(f"  {off >> 20} MB sent\n"))
            else:
                code, r = self.ctl.upload(verb, real, timeout=int(stp.get("timeout") or 3600))
            with contextlib.suppress(OSError):
                os.remove(real)
            if code != 200:
                job.say(f"the controller answered {code}: {(r or {}).get('error') or ''}\n")
                return "failed", 75
            job.say("sent, and removed here\n")
            return "succeeded", 0
        job.say(f"fetching {what} from the controller\n")
        code, _ = self.ctl.fetch(verb, real, timeout=int(stp.get("timeout") or 3600))
        if code != 200:
            job.say(f"the controller answered {code}\n")
            return "failed", 75
        who = self.drop_privileges({})
        if who:
            with contextlib.suppress(OSError):
                os.chown(real, who["user"], who["group"])
        job.say(f"fetched ({os.path.getsize(real) >> 20} MB)\n")
        return "succeeded", 0

    def cache_clear(self, job, spec):
        """Drop this node's build caches: one project's, or all of them.
        The one thing that goes wrong with caches is a full disk, and this
        is the button for it (docs/nodes.md §6). With older_days, only the
        ones no job has used for that long (the controller's room keeper,
        R110 step 7), read off the stamp a job leaves (.used), else the
        directory's own time."""
        root = (self.state.get("stores") or {}).get("cache") or ""
        if not root or not os.path.isdir(root):
            job.say("no cache store here\n")
            return "succeeded", 0
        project = re.sub(r"[^A-Za-z0-9._-]", "_", str(spec.get("project") or ""))
        targets = [os.path.join(root, project)] if project else \
                  [os.path.join(root, d) for d in os.listdir(root)]
        try:
            days = float(spec.get("older_days") or 0)
        except (TypeError, ValueError):
            days = 0
        n = 0
        for t in targets:
            if days > 0 and cache_age_days(t) < days:
                continue
            if os.path.isdir(t):
                shutil.rmtree(t, ignore_errors=True)
                job.say(f"removed {t}\n")
                n += 1
        job.say(f"cleared {n} director{'y' if n == 1 else 'ies'}\n")
        self.hello()
        return "succeeded", 0

    def storage_measure(self, job, spec):
        """The Storage page's Measure now: a walk of the disks at once
        rather than at the next hour, then a hello so the tab has it."""
        job.say("measuring the disks\n")
        got = storage.measure(self.state)
        job.say(f"measured {len(got.get('filesystems') or [])} filesystems and "
                f"{len(got.get('projects') or {})} projects in {got.get('took_s', 0)}s\n")
        self.hello()
        return "succeeded", 0

    # -- toolchains (docs/nodes.md §6) --------------------------------------------
    def toolchain(self, job, spec):
        """`bb toolchains install|remove NAME` against this node's toolchain store,
        with the bb the controller ships: the bundle (bb, its library, the
        catalog) is fetched by digest into the store and run from there as
        the enrolled account, SDK_ROOT pointing at the store. One catalog,
        per-node state; the census reports what landed."""
        store = tc_root(self.state)
        if not store:
            job.say("refused: this node has no toolchain store\n")
            return "failed", 78
        action = spec.get("action")
        names = [re.sub(r"[^A-Za-z0-9:;._-]", "", str(n)) for n in (spec.get("names") or [])]
        # Every name it was sent, or a refusal that says so: this kept the
        # first eight and dropped the rest without a word, so a batch of
        # nine reported success with the ninth never tried, and the move of
        # twenty-eight installed eight (the operator, 12 Oct).
        if len(names) > TC_NAMES_MAX:
            job.say(f"refused: {len(names)} toolchains in one job; at most {TC_NAMES_MAX}\n")
            return "failed", 64
        if action not in ("install", "remove", "sysdeps", "check") or (
                not names and action not in ("sysdeps", "check")):
            job.say("refused: a toolchain job installs or removes named toolchains, "
                    "installs the system packages the held ones need, or checks "
                    "what is newer upstream\n")
            return "failed", 64
        who = self.drop_privileges({})
        into = self.bundle(job, who)
        if not into:
            return "failed", 69
        if action == "sysdeps":
            return self.sysdeps(job, names, into)
        # The NVIDIA driver (R102), a member of the batch like any row, but
        # the machine's and not the store's: installed or removed as root by
        # bb-sandbox, after the store's names, since it ends at a restart.
        drv = [n for n in names if n == DRIVER or n.startswith(DRIVER + ":")]
        # ...and the container toolkit beside it, the machine's as well.
        ctk = [n for n in names if n == TOOLKIT]
        names = [n for n in names if n not in drv and n not in ctk]
        if action == "clean":
            # A retired node's directory on the store (R196). The controller
            # offered these names; each is checked again here: a node id at
            # the top of the store, never this node's own, and nothing
            # running from it.
            base = (self.state.get("stores") or {}).get("toolchains") or ""
            bad = 0
            for name in names:
                job.step(name)
                d = os.path.join(base, name)
                if (not base or name == tc_scope() or not re.fullmatch(r"n_[0-9a-f]{4,32}", name)
                        or not os.path.isdir(d)):
                    job.say(f"refused: {name} is not a directory this node may take off the store\n")
                    bad += 1
                    continue
                users = tc_users(d)
                if users:
                    job.say(tc_users_said(name, users))
                    bad += 1
                    continue
                job.say(f"== taking {d} off the store\n")
                try:
                    shutil.rmtree(d)
                except OSError as e:
                    job.say(f"could not take {d} off: {e}\n")
                    bad += 1
            self.hello()
            return ("failed", 1) if bad else ("succeeded", 0)
        if action == "check":
            # apt's lists brought current first, as root, so the census after
            # the check says what the driver would update to.
            if _gpu_card() and os.access(SANDBOX_BIN, os.X_OK):
                self.refresh_sandbox_tool(job)
                self._sh(job, [SANDBOX_BIN, "gpu-driver", "refresh"], timeout=300)
                self.hello_again("the GPU driver check refreshed apt")
            # What is newer upstream, asked from HERE rather than from the
            # controller, because the answer is about this store: the version
            # a recipe would fetch is the same everywhere, but what is
            # installed to compare it against is the node's. One command for
            # every name, because `bb toolchains check` with no argument
            # already means all of them, and the controller reads the TSV out
            # of this job's log (R67).
            job.step("checking")
            job.say(f"== bb toolchains check {' '.join(names)}\n")
            return job.exec({"argv": ["bash", os.path.join(into, "scripts", "bb"),
                                       "toolchains", "check", *names],
                              "cwd": store, "timeout": spec.get("timeout") or 900,
                              "env": sdk_env(self.state)})
        bad = 0
        # The catalog the bundle carries, for where each toolchain lives:
        # what an update or a removal would pull out from under whatever is
        # running it (the operator, 6 Oct).
        try:
            cat = read_catalog(into)
            cat = cat.get("toolchains", cat) if isinstance(cat, dict) else cat
            cat = {e.get("name"): e for e in (cat if isinstance(cat, list) else cat.values())
                   if isinstance(e, dict)}
        except (AttributeError, TypeError):
            cat = {}
        for name in names:
            # Which one it is on, for the tab's "Installing …". Only compose
            # jobs set this before, so a toolchain job on a node drew the verb
            # with nothing after it.
            job.step(name)
            # Refused while anything is running from it: a session's build,
            # its emulator, a Gradle daemon. Named, so the operator knows whose.
            d = tc_dir(store, name, cat.get(name), action)
            users = tc_users(d) if d else []
            if users:
                job.say(tc_users_said(name, users))
                bad += 1
                continue
            if action == "install" and not self._system_deps(job, name, into):
                bad += 1
                continue
            # One verb, or a remove and then the install for a recipe that
            # cannot update in place (tc_verbs, R193): the remove that fails
            # ends this name there, with the old one still installed.
            for verb in tc_verbs(store, name, cat.get(name), action):
                job.say(f"== bb toolchains {verb} {name}\n")
                st_, code = job.exec({"argv": ["bash", os.path.join(into, "scripts", "bb"),
                                                "toolchains", verb, name],
                                       "cwd": store, "timeout": spec.get("step_timeout") or spec.get("timeout") or 3600,
                                       "env": sdk_env(self.state)})
                if st_ != "succeeded":
                    bad += 1
                    if st_ == "canceled":
                        return st_, code
                    break
            else:
                # Landed: the terminal server is started again now, not when
                # the whole batch ends, so a session opened meanwhile has it
                # on its PATH (the operator, 12 Oct: one opened an hour into
                # a batch still had the old environment). Open sessions run on.
                if action in ("install", "update"):
                    self.session_renew()
        # The machine's own two, in the order each needs: the toolkit hands
        # the driver's libraries to a container, so it goes on after the
        # driver and comes off before it.
        own = [*drv[:1], *ctk[:1]] if action == "install" else [*ctk[:1], *drv[:1]]
        for name in own:
            mine = TOOLKIT if name == TOOLKIT else DRIVER
            job.step(mine)
            pkg = name.partition(":")[2] if mine == DRIVER else ""
            if pkg and not DRIVER_PKG.fullmatch(pkg):
                job.say(f"refused: {pkg} is not a driver package apt offers by that name\n")
                bad += 1
            elif not os.access(SANDBOX_BIN, os.X_OK):
                # The stamp, as every job that changes the machine itself
                # asks; bb-sandbox refuses by itself where it is not root.
                job.say(f"refused: {mine} is this machine's own, and this node was not "
                        f"provisioned as a BuilderBot sandbox ({SANDBOX_BIN} is not here)\n")
                bad += 1
            else:
                self.refresh_sandbox_tool(job)
                verb = "gpu-container" if mine == TOOLKIT else "gpu-driver"
                job.say(f"== bb-sandbox {verb} {action} {pkg}\n")
                if self._sh(job, [SANDBOX_BIN, verb, action, *([pkg] if pkg else [])], timeout=2400):
                    bad += 1
        self.hello()
        if bad:
            job.say(f"{bad} of {len(names) + len(own)} did not {action}\n")
            return "failed", 1
        return "succeeded", 0

    def sign(self, job, spec):
        """Sign one build from the project's dist/ with one of its keys
        (R106): the build fetched as a job input, the key fetched over this
        agent's channel for this job alone, both into a 0700 directory of the
        enrolled account that is removed whatever happens. zipalign then
        apksigner for an .apk, jarsigner for an .aab, verified, and the result
        delivered to dist/ as NAME-signed. The passwords reach the tools in
        their environment, which another account cannot read.

        Refused where a session could read the key while it is used: an agent
        that is not root runs its jobs as the account its sessions run as,
        and so does one whose enrolled account is the session one."""
        enrolled = str(self.state.get("user") or "")
        if os.geteuid() != 0 or not enrolled or enrolled == "root" or enrolled == self.session_account():
            job.say("refused: jobs and Claude sessions run as one account on this node, so a session "
                    "could read the key while it is used; sign on a node provisioned as a sandbox\n")
            return "failed", 77
        route, rel = str(spec.get("route") or ""), str(spec.get("file") or "")
        kind = os.path.splitext(rel)[1].lower()
        if kind not in (".apk", ".aab") or not route:
            job.say("refused: a sign job names a route and an .apk or .aab\n")
            return "failed", 64
        store = tc_root(self.state)
        tools = {}
        if kind == ".apk":
            bt = sorted(glob.glob(os.path.join(store, "android", "build-tools", "*")),
                        key=lambda d: [int(x) if x.isdigit() else 0
                                       for x in re.split(r"[.-]", os.path.basename(d))])
            for name in ("zipalign", "apksigner", "aapt2"):
                hit = next((os.path.join(d, name) for d in reversed(bt)
                            if os.access(os.path.join(d, name), os.X_OK)), "")
                if not hit:
                    job.say(f"no {name} on this node: install android-tools from the Toolchains page\n")
                    return "failed", 69
                tools[name] = hit
        else:
            tools["jarsigner"] = os.path.join(store, "jdk", "bin", "jarsigner")
            if not os.access(tools["jarsigner"], os.X_OK):
                job.say("no jarsigner on this node: install the jdk from the Toolchains page\n")
                return "failed", 69
        env = dict(sdk_env(self.state))
        who = self.drop_privileges(env)
        stores = self.state.get("stores") or {}
        work = os.path.join(stores.get("data") or "/tmp", "sign", re.sub(r"[^A-Za-z0-9_-]", "_", job.job["id"]))
        try:
            os.makedirs(work, mode=0o700, exist_ok=True)
            os.chmod(work, 0o700)
            if who:
                os.chown(work, who["user"], who["group"])
            src = os.path.join(work, "in" + kind)
            st, _ = self.ctl.fetch(f"file?job={job.job['id']}&path={urllib.parse.quote(rel)}", src)
            if st != 200:
                job.say(f"could not fetch {rel} from the controller ({st})\n")
                return "failed", 69
            # Which app it is, so the controller can hand the key its package
            # is mapped to (R106 step 6): aapt2 for an .apk; a bundle's
            # manifest is a protobuf no tool here reads, and the package name
            # is the one string in it shaped like one after "package".
            package = ""
            if kind == ".apk":
                with contextlib.suppress(OSError, subprocess.SubprocessError):
                    p = subprocess.run([tools["aapt2"], "dump", "packagename", src], capture_output=True,
                                       text=True, timeout=60, check=False)
                    package = (p.stdout or "").strip().splitlines()[0] if p.returncode == 0 and p.stdout.strip() else ""
            else:
                with contextlib.suppress(OSError, KeyError, zipfile.BadZipFile):
                    with zipfile.ZipFile(src) as z:
                        man = z.read("base/manifest/AndroidManifest.xml")
                    at = man.find(b"package")
                    got = re.search(rb"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", man[at:at + 400]) if at >= 0 else None
                    package = got.group(0).decode() if got else ""
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+", package or ""):
                package = ""
            if package:
                job.say(f"the build is {package}\n")
            st, k = self.ctl.call("signing-key", {"job": job.job["id"], "package": package}, timeout=30)
            if st != 200 or not isinstance(k, dict) or not k.get("keystore"):
                job.say(f"the controller did not hand over the key: {(k or {}).get('error') or st}\n")
                return "failed", 69
            ks = os.path.join(work, "key")
            fd = os.open(ks, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(base64.b64decode(k["keystore"]))
            for p in (src, ks):
                if who:
                    os.chown(p, who["user"], who["group"])
            env.update({"BB_KS_PASS": str(k.get("store_pass") or ""),
                        "BB_KEY_PASS": str(k.get("key_pass") or k.get("store_pass") or "")})
            # A rotated key (R106 step 7): the key it replaced signs first and
            # the proof says the new one takes over, from Android 9 on.
            prev = k.get("previous") if kind == ".apk" and k.get("lineage") else None
            if prev:
                pks, lin = os.path.join(work, "previous"), os.path.join(work, "lineage")
                for path, data in ((pks, prev.get("keystore")), (lin, k.get("lineage"))):
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as f:
                        f.write(base64.b64decode(data or ""))
                    if who:
                        os.chown(path, who["user"], who["group"])
                env.update({"BB_PREV_KS": str(prev.get("store_pass") or ""),
                            "BB_PREV_KEY": str(prev.get("key_pass") or prev.get("store_pass") or "")})
            elif k.get("previous"):
                job.say("a bundle carries no proof of rotation: it is signed with the new key alone, "
                        "and Play upgrades its own key\n")
            alias = str(k.get("alias") or "")
            out = os.path.join(work, "out" + kind)

            def step(argv, what):
                try:
                    p = subprocess.run(argv, env=env, cwd=work, capture_output=True, text=True,
                                       timeout=600, check=False, **who)
                except (OSError, subprocess.SubprocessError) as e:
                    job.say(f"{what} did not run: {e}\n")
                    return None
                said = ((p.stdout or "") + (p.stderr or "")).strip()
                if p.returncode != 0:
                    job.say(f"{what} failed (exit {p.returncode}): {said[-800:]}\n")
                    return None
                return said
            if kind == ".apk":
                aligned = os.path.join(work, "aligned.apk")
                if step([tools["zipalign"], "-p", "-f", "4", src, aligned], "zipalign") is None:
                    return "failed", 1
                first = (["--ks", pks, "--ks-key-alias", str(prev.get("alias") or ""),
                          "--ks-pass", "env:BB_PREV_KS", "--key-pass", "env:BB_PREV_KEY", "--next-signer"]
                         if prev else [])
                tail = (["--lineage", lin, "--rotation-min-sdk-version", "28"] if prev else [])
                if step([tools["apksigner"], "sign", *first, "--ks", ks, "--ks-key-alias", alias,
                         "--ks-pass", "env:BB_KS_PASS", "--key-pass", "env:BB_KEY_PASS",
                         *tail, "--out", out, aligned], "apksigner sign") is None:
                    return "failed", 1
                said = step([tools["apksigner"], "verify", "--verbose", "--print-certs", out], "apksigner verify")
            else:
                shutil.copyfile(src, out)
                if who:
                    os.chown(out, who["user"], who["group"])
                if step([tools["jarsigner"], "-keystore", ks, "-storepass:env", "BB_KS_PASS",
                         "-keypass:env", "BB_KEY_PASS", out, alias], "jarsigner") is None:
                    return "failed", 1
                said = step([tools["jarsigner"], "-verify", out], "jarsigner -verify")
            if said is None:
                return "failed", 1
            got = re.search(r"SHA-256 digest:\s*([0-9a-fA-F]{64})", said)
            cert = got.group(1).upper() if got else ""
            # Which signature schemes verified, as apksigner says it; a
            # bundle is a jar signature (R106 step 4: the row says so).
            schemes = ",".join(re.findall(r"Verified using (v\d(?:\.\d)?) scheme[^:]*:\s*true", said)) \
                if kind == ".apk" else "jar"
            want = str(k.get("sha256") or "").replace(":", "").upper()
            if cert and want and cert != want:
                job.say("the signed build carries another certificate than the key that was kept\n")
                return "failed", 1
            base = os.path.basename(rel)[:-len(kind)]
            base = base.replace("-unsigned", "") if "-unsigned" in base else base
            name = f"{base}-signed{kind}"
            st, r = self.ctl.upload(f"artifact?job={job.job['id']}&name={name}&signed={route}"
                                    f"&cert={cert or want}&schemes={schemes}&key={k.get('key') or 'default'}"
                                    + (f"&rotated={prev.get('key')}" if prev else ""), out)
            if st != 200 or r.get("error"):
                job.say(f"could not deliver {name}: {r.get('error') or st}\n")
                return "failed", 1
            job.say(f"signed {rel} for {route} with the {k.get('key') or 'default'} key, {alias} "
                    f"({str(k.get('sha256') or '')[:23]}…): {r['path']}\n")
            job.outputs.append({"kind": "artifact", "path": r["path"], "size": r.get("size"),
                                "sha256": r.get("sha256"), "signed": route,
                                "cert": k.get("sha256") or ""})
            return "succeeded", 0
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def sign_key(self, job, spec):
        """The controller's signing key work, on this node (R106, the
        operator 22 Oct: the controller runs nothing): a keystore checked, a
        key made, a key wrapped under a backup's password, a rotation's
        proof, or a release's APK signed (keyops.py). What the job needs
        comes over this agent's channel for it alone (signing-key) and what
        it made goes back the same way (signing-result, and signing-put for
        a signed APK); none of it is written but into a 0700 directory of the
        enrolled account, removed whatever happens. Refused where a session
        could read it, as a sign job is."""
        jid = job.job["id"]

        def answer(r):
            st, got = self.ctl.call("signing-result", {"job": jid, **r}, timeout=60)
            if st != 200:
                job.say(f"the controller did not take the answer: {(got or {}).get('error') or st}\n")
            return st == 200
        enrolled = str(self.state.get("user") or "")
        if os.geteuid() != 0 or not enrolled or enrolled == "root" or enrolled == self.session_account():
            why = ("jobs and Claude sessions run as one account on this node, so a session could read "
                   "the key while it is used: sign on a node provisioned as a sandbox")
            job.say(f"refused: {why}\n")
            answer({"error": why})
            return "failed", 77
        op = str(spec.get("op") or "")
        if op not in ("inspect", "generate", "wrap", "rotate", "release"):
            job.say("refused: a sign-key job is inspect, generate, wrap, rotate or release\n")
            return "failed", 64
        tl, missing = keyops.tools(tc_root(self.state), op in ("rotate", "release"))
        if missing:
            job.say(f"no {missing} on this node: install it from the Toolchains page\n")
            answer({"missing": missing})
            return "failed", 69
        env = dict(sdk_env(self.state), **tl["env"])
        who = self.drop_privileges(env)
        stores = self.state.get("stores") or {}
        work = os.path.join(stores.get("data") or "/tmp", "sign-key", re.sub(r"[^A-Za-z0-9_-]", "_", jid))
        kw = {"work": work, "env": env, "who": who}
        try:
            os.makedirs(work, mode=0o700, exist_ok=True)
            os.chmod(work, 0o700)
            if who:
                os.chown(work, who["user"], who["group"])
            package, src = "", os.path.join(work, "in.apk")
            if op == "release":
                st, _ = self.ctl.fetch(f"file?job={jid}&path=release.apk", src)
                if st != 200:
                    job.say(f"could not fetch the APK from the controller ({st})\n")
                    answer({"error": f"the node could not fetch the APK from the controller ({st})"})
                    return "failed", 69
                if who:
                    os.chown(src, who["user"], who["group"])
                package = keyops.package_of(tl["aapt2"], src, **kw)
                if package:
                    job.say(f"the APK is {package}\n")
            st, k = self.ctl.call("signing-key", {"job": jid, "package": package}, timeout=30)
            if st != 200 or not isinstance(k, dict):
                why = (k or {}).get("error") if isinstance(k, dict) else ""
                job.say(f"the controller handed nothing over: {why or st}\n")
                answer({"error": why or f"the controller handed nothing over ({st})"})
                return "failed", 69

            def raw(d):
                return dict(d, keystore=base64.b64decode(d.get("keystore") or ""))
            b64 = lambda b: base64.b64encode(b).decode()   # noqa: E731
            job.say(f"{op} on this node\n")
            out, why = {}, ""
            if op == "inspect":
                alias, kind, sha, why = keyops.inspect(tl["keytool"], base64.b64decode(k.get("keystore") or ""),
                                                       str(k.get("store_pass") or ""), str(k.get("alias") or ""), **kw)
                out = {"alias": alias, "type": kind, "sha256": sha}
            elif op == "generate":
                pw = str(k.get("password") or "")
                blob, why = keyops.generate(tl["keytool"], str(k.get("alias") or ""), str(k.get("cn") or ""), pw, **kw)
                if not why:
                    alias, kind, sha, why = keyops.inspect(tl["keytool"], blob, pw, str(k.get("alias") or ""), **kw)
                    out = {"keystore": b64(blob), "alias": alias, "type": kind, "sha256": sha}
            elif op == "wrap":
                blob, why = keyops.wrap(tl["keytool"], base64.b64decode(k.get("keystore") or ""),
                                        str(k.get("store_pass") or ""), str(k.get("key_pass") or ""),
                                        str(k.get("alias") or ""), str(k.get("new_pass") or ""), **kw)
                out = {"keystore": b64(blob)}
            elif op == "rotate":
                proof, why = keyops.rotate(tl["apksigner"], raw(k.get("old") or {}), raw(k.get("new") or {}), **kw)
                out = {"lineage": b64(proof)}
            else:
                prev = k.get("previous")
                signed = os.path.join(work, "out.apk")
                got, why = keyops.sign_apk(tl, src, signed, raw(k), raw(prev) if prev else None,
                                           base64.b64decode(k.get("lineage") or ""), **kw)
                if not why:
                    st, r = self.ctl.upload(f"signing-put?job={jid}", signed)
                    if st != 200 or (r or {}).get("error"):
                        why = f"the signed APK did not reach the controller: {(r or {}).get('error') or st}"
                    out = {**got, "key": k.get("key") or "", "package": package,
                           "rotated_from": (prev or {}).get("key") or ""}
            if why:
                job.say(f"{op} failed: {why}\n")
                answer({"error": why})
                return "failed", 1
            if not answer(out):
                return "failed", 1
            job.say(f"{op} done\n")
            return "succeeded", 0
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def image(self, job, spec):
        """`bb emu image add|remove ID`: an Android system image onto this
        node's toolchain store, or off it. Not a toolchain (it exists at
        every API level at once), but it lives on the same store and goes
        through the same bundle, account and one-at-a-time rule, so this is
        toolchain() for one id, or for several in turn: the Emulator page's
        Install selected sends the ticked ones as `images` (R121), and the
        first that fails ends the job, as a toolchain install does. Nothing
        on PATH moves, so no session renew."""
        store = tc_root(self.state)
        if not store:
            job.say("refused: this node has no toolchain store, which is where images live\n")
            return "failed", 78
        action = spec.get("action")
        ids = [re.sub(r"[^A-Za-z0-9;._-]", "", str(i or ""))
               for i in (spec.get("images") or [])][:20]
        ids = [i for i in ids if i]
        if action not in ("add", "remove") or not ids:
            job.say("refused: an image job adds or removes named system images\n")
            return "failed", 64
        who = self.drop_privileges({})
        into = self.bundle(job, who)
        if not into:
            return "failed", 69
        st_, code = "succeeded", 0
        for iid in ids:
            job.step(iid)
            job.say(f"== bb emu image {action} {iid}\n")
            st_, code = job.exec({"argv": ["bash", os.path.join(into, "scripts", "bb"),
                                            "emu", "image", action, iid],
                                   "cwd": store, "timeout": spec.get("step_timeout") or spec.get("timeout") or 3600,
                                   "env": sdk_env(self.state)})
            if st_ != "succeeded":
                break
        self.hello()
        return st_, code

    def _system_deps(self, job, name, into):
        """A recipe's `system.apt` (or `system.dnf`, on the RHEL family)
        packages, from the catalog the bundle
        carries: installed here, as root, on a node this agent may
        administer (the sandbox stamp; roadmap #23 refines it to a class);
        named and left to the owner anywhere else. The recipe itself runs
        as the job account, which is why this cannot be part of it.
        Playwright's browsers launched from the store and died on
        libatk-1.0.so.0 behind a stack that said the browser had closed.
        False when the install was tried and failed; a missing package on a
        node this cannot administer is a warning, not a refusal: the
        download is still worth having, and the tool names what is missing
        when it is used."""
        cat = read_catalog(into)
        fam, query, install = pkg_backend()
        missing, other = sysdeps_missing(cat, name, fam, query)
        # Which family this machine is decides which list applies. A recipe
        # that names packages for the other family only is not wrong, it is
        # incomplete for this node: say so with the names it does have, so
        # the owner can find their equivalents, and carry on to the recipe.
        if other:
            job.say(f"{name} needs system packages its recipe names for {other[0]} only; "
                    f"this node's are its owner's to install; the {other[0]} names: "
                    f"{' '.join(other[1])}\n")
        if not missing:
            return True
        if not self.administers():
            job.say(f"{name} needs system packages this node's owner installs, "
                    f"not this agent, which does not administer the machine: "
                    f"{' '.join(missing)}\n")
            return True
        job.say(f"== system packages for {name}: {' '.join(missing)}\n")
        return self._install_system(job, name, fam, install, missing)

    def administers(self):
        """Whether this agent may install system packages here: root, on a
        node provisioned as a sandbox (the stamp; roadmap R23 refines it to
        a class). Anywhere else the machine is its owner's."""
        return os.geteuid() == 0 and os.access(SANDBOX_BIN, os.X_OK)

    def sysdeps(self, job, names, into):
        """Install the system packages the recipes already on the store need
        here, without touching the recipes (roadmap R51). The store is a
        share, so a toolchain installed from one node is on every node that
        mounts it, while the libraries it needs are each machine's own: a
        node enrolled afterwards has dotnet and not libicu, and the only
        gesture that installed libicu was reinstalling dotnet onto the share
        for everybody. Named recipes, or every held one when none are."""
        cat = read_catalog(into)
        fam, query, install = pkg_backend()
        if not fam:
            job.say("refused: no package manager this agent knows is on this machine\n")
            return "failed", 78
        held = held_recipes(self.state, cat)
        want = [n for n in names if n in held] if names else held
        if names and not want:
            job.say(f"none of {' '.join(names)} is on this node's store, so nothing here needs anything\n")
            return "succeeded", 0
        needed = {}
        for name in want:
            missing, other = sysdeps_missing(cat, name, fam, query)
            if other:
                job.say(f"{name}: its recipe names packages for {other[0]} only, not {fam}; "
                        f"the {other[0]} names: {' '.join(other[1])}\n")
            if missing:
                needed[name] = missing
        if not needed:
            job.say(f"every system package the held recipes need is installed here ({fam})\n")
            return "succeeded", 0
        if not self.administers():
            job.say("refused: this agent does not administer the machine, so its owner "
                    "installs these: "
                    + "; ".join(f"{n}: {' '.join(m)}" for n, m in needed.items()) + "\n")
            return "failed", 77
        bad = 0
        for name, missing in needed.items():
            job.step(name)
            job.say(f"== system packages for {name}: {' '.join(missing)}\n")
            if not self._install_system(job, name, fam, install, missing):
                bad += 1
        self.hello()
        if bad:
            job.say(f"{bad} of {len(needed)} did not install\n")
            return "failed", 1
        return "succeeded", 0

    def _install_system(self, job, name, fam, install, missing):
        env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
        try:
            # emerge builds from source: fifteen minutes is a package
            # manager's clock, not a compiler's.
            p = subprocess.run([*install, *missing], env=env, capture_output=True, text=True,
                               timeout=4 * 3600 if fam == "emerge" else 900, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            job.say(f"{install[0]}: {e}\n")
            return False
        if p.returncode != 0:
            job.say((p.stdout or "")[-2000:] + (p.stderr or "")[-2000:])
            job.say(f"{name}: its system packages did not install (exit {p.returncode})\n")
            return False
        return True
