"""The CI runners a node keeps: their slots and state, and the configuration plane's runner verbs."""
import contextlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import tarfile
import time
import urllib.request
from .base import (
    ACT_RUNNER_BIN,
    ACT_RUNNER_RELEASES,
    RUNNER_DIR,
    RUNNER_RELEASES,
    RUNNER_TARBALL,
    _run,
    has_systemd,
    log,
)
from .toolchains import ci_log_dir, runner_env_text


def runner_slot(url):
    """The slot a runner's address maps to: its host and path, lowercase,
    letters, digits, dots and dashes, so it can name a directory on the
    node, a token file on the controller and a row on the tab. One runner
    per slot per node, since a runner's name on its host is the node's.
    The same function lives in scripts/dashboard/nodes.py; the two must agree."""
    rest = re.sub(r"^[a-z]+://", "", str(url or "").strip().lower()).rstrip("/")
    rest = re.sub(r"\.git$", "", rest)
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9.]+", "-", rest)).strip("-.")[:60]


def _runner_record(d):
    """The runner's own record of its registration in directory d, whichever
    runner: GitHub's writes agentName and gitHubUrl (with a BOM), act_runner
    writes name, address and id. {} when none is registered there."""
    try:
        with open(os.path.join(d, ".runner"), encoding="utf-8-sig") as f:
            j = json.load(f)
        return j if isinstance(j, dict) else {}
    except (OSError, ValueError):
        return {}


def runner_dirs():
    """Every directory holding a registered runner: RUNNER_DIR itself for a
    runner registered before a node could hold several (its unit names that
    path, so it stays), and RUNNER_DIR/<slot> for each since. [(dir, record)]."""
    out = []
    rec = _runner_record(RUNNER_DIR)
    if rec:
        out.append((RUNNER_DIR, rec))
    try:
        subs = sorted(os.listdir(RUNNER_DIR))
    except OSError:
        subs = []
    for sub in subs:
        d = os.path.join(RUNNER_DIR, sub)
        rec = _runner_record(d) if os.path.isdir(d) else {}
        if rec:
            out.append((d, rec))
    return out


def _runner_state(d, rec):
    """One runner as the census reports it: what it registered as and
    whether its listener is up, read from its own files."""
    labels = []
    with contextlib.suppress(OSError):
        with open(os.path.join(d, ".builderbot-labels")) as f:
            labels = [x for x in f.read().split(",") if x]
    # GitHub's runner listens as bin/Runner.Listener; act_runner as
    # `<dir>/act_runner daemon`, in the foreground under this agent.
    pg = (_run(["pgrep", "-f", os.path.join(d, "bin/Runner.Listener")])
          or _run(["pgrep", "-f", os.path.join(d, "act_runner") + " daemon"]))
    # WHERE ITS OUTPUT GOES, which only this machine knows. Under systemd
    # svc.sh writes the unit's name into .service and the listener's output
    # is the journal's; in the foreground it is runner.log under the data
    # store. Empty when there is no unit, and the controller reads the file.
    unit = ""
    if has_systemd():
        with contextlib.suppress(OSError):
            with open(os.path.join(d, ".service")) as f:
                unit = f.read().strip()[:120]
    url = str(rec.get("gitHubUrl") or rec.get("address") or "")[:200]
    with contextlib.suppress(OSError):
        with open(os.path.join(d, ".builderbot-url")) as f:
            url = f.read().strip()[:200] or url
    # GitHub's .runner says agentName and gitHubUrl; act_runner's says name
    # and address, which is also how the two are told apart.
    # The slot is the directory's name, which the controller chose from
    # the address the token was stored for; act_runner's own .runner holds
    # only the forge's root, which would name a different slot. A runner
    # registered in RUNNER_DIR itself, from before a node held several,
    # has no such directory and keeps the address-derived slot.
    return {"installed": True,
            "slot": (os.path.basename(d.rstrip("/")) if os.path.realpath(d) != os.path.realpath(RUNNER_DIR)
                     else runner_slot(url)),
            "name": str(rec.get("agentName") or rec.get("name") or "")[:80],
            "url": url, "forge": "gitea" if "address" in rec else "github",
            "unit": unit, "labels": labels[:16], "active": bool(pg),
            "busy": bool(_run(["pgrep", "-f", os.path.join(d, "bin/Runner.Worker")]))}


class RunnersMixin:
    """Agent's runner methods: one of the parts class Agent (agent.py) is made of."""

    def runner_env_sync(self):
        """Every runner's .env, kept equal to what runner_env_text says now:
        the node's toolchain and where CI logs are archived. _apply_runner
        writes it at install; a runner installed before this agent knew a
        line (bb-sandbox's was) ran with less. Rewritten when it differs, and
        the service cycled so the runner reads it, only while it is idle: a
        restart under a running job would kill the job."""
        for d, _rec in runner_dirs():
            self._runner_env_sync(d)

    def _runner_env_sync(self, d):
        want = runner_env_text(self.state)
        try:
            with open(os.path.join(d, ".env")) as f:
                have = f.read()
        except OSError:
            have = ""
        if have == want:
            return
        if _run(["pgrep", "-f", os.path.join(d, "bin/Runner.Worker")]):
            return                          # busy: next hello
        env = {}
        who = self.as_user(env, self.state.get("user") or "")
        self.own_dir(ci_log_dir(self.state), who)
        with contextlib.suppress(OSError):
            os.chmod(ci_log_dir(self.state), 0o755)
        with open(os.path.join(d, ".env"), "w") as f:
            f.write(want)
        if who:
            with contextlib.suppress(OSError):
                os.chown(os.path.join(d, ".env"), who["user"], who["group"])
        log("runner: its .env now carries the node's toolchain and the CI log directory; restarting the runner to read it")
        if os.path.isfile(os.path.join(d, "svc.sh")) and has_systemd():
            quiet = type("Q", (), {"say": staticmethod(lambda t: None)})()
            self._sh(quiet, ["bash", "./svc.sh", "stop"], cwd=d)
            self._sh(quiet, ["bash", "./svc.sh", "start"], cwd=d)
        else:
            self.runner_stop(d)
            self.runner_start(who, d=d)

    def _apply_runner(self, job, cfg):
        """The Actions runner as a service on this node (phase 7): fetched
        from GitHub's releases, registered with a token the controller mints
        on request (the PAT stays in the controller's root-only stash and
        the token lives for an hour), and run under systemd as the enrolled
        account by the runner's own svc.sh. Removal deregisters first, so
        GitHub does not keep a ghost. Labels are the tab's, the node's name
        among them, and are written beside the runner for the census."""
        want = bool(cfg.get("want", True))
        who = self.drop_privileges({})
        user = self.state.get("user") or "root"
        url = str(cfg.get("url") or "")
        slot = str(cfg.get("slot") or "") or runner_slot(url)
        # This runner's directory, one per git host: the one already
        # registered for this address (RUNNER_DIR itself for a runner from
        # before a node could hold several), else RUNNER_DIR/<slot>.
        d = self._runner_dir_for(slot, url)
        # Which host's runner: what is installed decides a removal, the
        # record decides an install.
        installed = _runner_record(d)
        if (installed.get("address") if installed else cfg.get("forge") == "gitea"):
            return self._apply_act_runner(job, cfg, want, who, d, installed, slot)
        if not want:
            if not os.path.isfile(os.path.join(d, ".runner")):
                job.say("no runner is installed here\n")
                return "succeeded", 0
            st, r = self.ctl.call("runner-token", {"kind": "remove", "slot": slot}, timeout=60)
            if st != 200 or not r.get("token"):
                job.say(f"could not get a removal token from the controller: {r.get('error', st)}\n")
                return "failed", 69
            self.runner_stop(d)
            if os.path.isfile(os.path.join(d, "svc.sh")) and has_systemd():
                self._sh(job, ["bash", "./svc.sh", "stop"], cwd=d)
                self._sh(job, ["bash", "./svc.sh", "uninstall"], cwd=d)
            code = self._run_as(job, who, d, [os.path.join(d, "config.sh"), "remove", "--token", r["token"]])
            if code != 0:
                job.say("deregistration did not complete; remove the runner in GitHub's settings if it lingers\n")
            shutil.rmtree(d, ignore_errors=True)
            self.hello()
            job.say("runner removed\n")
            return "succeeded", 0
        if not url.startswith("https://github.com/"):
            job.say(f"refused: the runner registers with a GitHub org or repo URL, not {url!r}\n")
            return "failed", 65
        labels = [re.sub(r"[^A-Za-z0-9._-]", "", str(x)) for x in (cfg.get("labels") or [])]
        labels = [x for x in labels if x][:16] or ["builderbot", "self-hosted"]
        name = re.sub(r"[^A-Za-z0-9._-]", "-", str(cfg.get("name") or socket.gethostname()))[:64]
        os.makedirs(d, exist_ok=True)
        if not os.path.isfile(os.path.join(d, "config.sh")):
            tar_path = os.path.join(d, "runner.tar.gz")
            if RUNNER_TARBALL:
                shutil.copyfile(RUNNER_TARBALL, tar_path)
                job.say(f"using the runner tarball at {RUNNER_TARBALL}\n")
            else:
                arch = {"x86_64": "x64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "arm"}.get(platform.machine(), "x64")
                osname = "osx" if platform.system() == "Darwin" else "linux"
                job.say("asking GitHub for the latest runner release…\n")
                try:
                    # nosemgrep: dynamic-urllib-use-detected (RUNNER_RELEASES is a literal at the top of this file)
                    with urllib.request.urlopen(RUNNER_RELEASES, timeout=30) as r:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected (a literal URL)
                        rel = json.load(r)
                    asset = next(a["browser_download_url"] for a in rel.get("assets", [])
                                 if a.get("name", "").startswith(f"actions-runner-{osname}-{arch}-")
                                 and a["name"].endswith(".tar.gz"))
                except (OSError, ValueError, StopIteration, KeyError) as e:
                    job.say(f"could not find the runner release: {e}\n")
                    return "failed", 69
                job.say(f"downloading {asset}\n")
                job.flush()
                try:
                    # The release API named it; only a web address is followed,
                    # since urlopen would open file:// as readily.
                    if not str(asset).lower().startswith("https://"):
                        raise ValueError(f"the release names a non-https asset: {str(asset)[:60]}")
                    with urllib.request.urlopen(asset, timeout=600) as r, open(tar_path, "wb") as f:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected (https checked above)
                        shutil.copyfileobj(r, f)
                except OSError as e:
                    job.say(f"download failed: {e}\n")
                    return "failed", 69
            with tarfile.open(tar_path) as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(d, filter="data")
                else:
                    tar.extractall(d)
            os.remove(tar_path)
        self.own_dir(d, who)
        if who:
            for dd, _dirs, files in os.walk(d):
                for x in [dd] + [os.path.join(dd, f) for f in files]:
                    with contextlib.suppress(OSError):
                        os.lchown(x, who["user"], who["group"])
        # A runner that is already configured locally refuses to be
        # configured again: `--replace` is about taking a NAME back on
        # GitHub's side, not about overwriting .runner here. So a Reinstall
        # after a half-finished install (registered, service not installed)
        # failed with "Cannot configure the runner because it is already
        # configured", and the retry was blocked by the state the first
        # attempt left. Clear it first, and mean it: deregister properly if
        # the controller will mint a removal token, and failing that take the
        # local config out of the way so this can proceed; a runner left on
        # GitHub's side is replaced by name a moment later.
        # The registration token FIRST, before anything standing is touched:
        # a reinstall whose token could not be minted used to stop and
        # uninstall the working runner, clear its registration, and only
        # then find out, leaving the node with no runner at all.
        st, r = self.ctl.call("runner-token", {"kind": "registration", "slot": slot}, timeout=60)
        if st != 200 or not r.get("token"):
            # One line, reason last: the row reads the log's last line.
            kept = ", so the runner already here is left as it was" if os.path.isfile(os.path.join(d, ".runner")) else ""
            job.say(f"could not get a registration token from the controller{kept}: {r.get('error', st)}\n")
            return "failed", 69
        if os.path.isfile(os.path.join(d, ".runner")):
            job.say("a runner is already configured here; clearing it before reinstalling\n")
            if os.path.isfile(os.path.join(d, "svc.sh")):
                self._sh(job, ["bash", "./svc.sh", "stop"], cwd=d)
                self._sh(job, ["bash", "./svc.sh", "uninstall"], cwd=d)
            st, rr = self.ctl.call("runner-token", {"kind": "remove", "slot": slot}, timeout=60)
            gone = False
            if st == 200 and rr.get("token"):
                gone = self._run_as(job, who, d, [os.path.join(d, "config.sh"), "remove",
                                                  "--token", rr["token"]]) == 0
            if not gone:
                job.say("deregistration did not complete; taking the local config out of the "
                        "way so the reinstall can proceed. The old runner is replaced by name.\n")
                for junk in (".runner", ".credentials", ".credentials_rsaparams", ".service"):
                    with contextlib.suppress(OSError):
                        os.remove(os.path.join(d, junk))
        job.say(f"registering {name} with {url} [{','.join(labels)}]\n")
        code = self._run_as(job, who, d, [os.path.join(d, "config.sh"), "--unattended", "--replace",
                                          "--url", url, "--token", r["token"], "--name", name,
                                          "--labels", ",".join(labels), "--work", "_work"])
        if code != 0:
            return "failed", code
        with open(os.path.join(d, ".builderbot-labels"), "w") as f:
            f.write(",".join(labels))
        # The runner reads .env into every job it runs: the node's toolchain,
        # so CI sees what bb build sees, and where the workflows' archive
        # step lands (see runner_env_text). The log directory is made here,
        # readable, so the session account can read what lands in it.
        logs = ci_log_dir(self.state)
        self.own_dir(logs, who)
        with contextlib.suppress(OSError):
            os.chmod(logs, 0o755)
        with open(os.path.join(d, ".env"), "w") as f:
            f.write(runner_env_text(self.state))
        if os.path.isfile(os.path.join(d, "svc.sh")) and has_systemd():
            for verb in (["install", user], ["start"]):
                if self._sh(job, ["bash", "./svc.sh", *verb], cwd=d) != 0:
                    # Registered but not serviced is a real state, and the
                    # row should say so rather than showing nothing: the
                    # census reads .runner, which exists by now.
                    self.hello()
                    job.say("the runner is registered with GitHub but its service did "
                            "not install; it will not pick up jobs until it does\n")
                    return "failed", 1
        else:
            # No systemd: a container node (this image in the node role),
            # or a guest machine without it (roadmap #23). The runner is
            # run.sh in the foreground under this agent, which supervises it
            # and takes it down with itself; the census's pgrep of
            # Runner.Listener reports it exactly as it would the service.
            if not self.runner_start(who, job, d):
                return "failed", 1
            job.say("no systemd here: the runner runs in the foreground under this agent\n")
        self.hello()
        job.say("runner installed and started\n")
        return "succeeded", 0

    @staticmethod
    def _runner_dir_for(slot, url=""):
        """Where a runner for this address lives, or would: the directory
        already registered for it, else RUNNER_DIR/<slot>."""
        want = url.rstrip("/").lower()
        for d, rec in runner_dirs():
            have = str(rec.get("gitHubUrl") or rec.get("address") or "").rstrip("/").lower()
            if (want and have == want) or (not want and runner_slot(have) == slot):
                return d
        return os.path.join(RUNNER_DIR, slot) if slot else RUNNER_DIR

    def _apply_act_runner(self, job, cfg, want, who, d, installed, slot):
        """Gitea's or Forgejo's runner (R53): act_runner, one static binary,
        registered with a token the controller fetches from the host's API
        with the node's own credential, and run as `act_runner daemon` in
        the foreground under this agent, which supervises it the way it
        does GitHub's runner on a node without systemd. Every label is
        `name:host`, so a job lands on this machine's own toolchain rather
        than in a container, which is what a BuilderBot node is for."""
        exe = os.path.join(d, "act_runner")
        if not want:
            if not installed:
                job.say("no runner is installed here\n")
                return "succeeded", 0
            rid = str(installed.get("id") or "")
            st, r = self.ctl.call("runner-token", {"kind": "remove", "slot": slot, "runner_id": rid}, timeout=60)
            if st != 200 or r.get("error"):
                job.say(f"could not delete the runner on its host: {r.get('error', st)}; "
                        "taking the local one down anyway\n")
            self.runner_stop(d)
            shutil.rmtree(d, ignore_errors=True)
            self.hello()
            job.say("runner removed\n")
            return "succeeded", 0
        url = str(cfg.get("url") or "")
        # http as well as https: a Gitea on the LAN, and the controller
        # accepted the address the same way when the token was stored.
        if not url.startswith(("https://", "http://")):
            job.say(f"refused: the runner registers with an https address (or http on your own network), not {url!r}\n")
            return "failed", 65
        labels = [re.sub(r"[^A-Za-z0-9._-]", "", str(x)) for x in (cfg.get("labels") or [])]
        labels = [x for x in labels if x][:16] or ["builderbot", "self-hosted"]
        name = re.sub(r"[^A-Za-z0-9._-]", "-", str(cfg.get("name") or socket.gethostname()))[:64]
        os.makedirs(d, exist_ok=True)
        if not os.path.isfile(exe):
            if ACT_RUNNER_BIN:
                shutil.copyfile(ACT_RUNNER_BIN, exe)
                job.say(f"using the act_runner at {ACT_RUNNER_BIN}\n")
            else:
                arch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "arm-7"}.get(platform.machine(), "amd64")
                job.say("asking gitea.com for the latest act_runner release…\n")
                rel = {}
                try:
                    # nosemgrep: dynamic-urllib-use-detected (ACT_RUNNER_RELEASES is a literal at the top of this file)
                    with urllib.request.urlopen(ACT_RUNNER_RELEASES, timeout=30) as r:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected (a literal URL)
                        rel = json.load(r)
                    asset = next(a["browser_download_url"] for a in rel.get("assets", [])
                                 if re.fullmatch(rf"(gitea-runner|act_runner)-[0-9.]+-linux-{arch}", a.get("name", "")))
                except (OSError, ValueError, KeyError) as e:
                    job.say(f"could not fetch the act_runner release from {ACT_RUNNER_RELEASES}: {e}\n")
                    return "failed", 69
                except StopIteration:
                    # The reason that was missing when the assets were renamed
                    # under us (B130): what the release holds, so the next
                    # rename is a one-line fix rather than a round trip.
                    names = [str(a.get("name") or "") for a in rel.get("assets", [])]
                    job.say(f"could not find the act_runner release: {rel.get('tag_name') or 'the latest release'} "
                            f"has no asset named gitea-runner-<version>-linux-{arch} or "
                            f"act_runner-<version>-linux-{arch}; it has {', '.join(names[:12]) or 'no assets'}\n")
                    return "failed", 69
                job.say(f"downloading {asset}\n")
                job.flush()
                try:
                    if not str(asset).lower().startswith("https://"):   # as for the GitHub runner above
                        raise ValueError(f"the release names a non-https asset: {str(asset)[:60]}")
                    with urllib.request.urlopen(asset, timeout=600) as r, open(exe, "wb") as f:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected (https checked above)
                        shutil.copyfileobj(r, f)
                except OSError as e:
                    job.say(f"download failed: {e}\n")
                    return "failed", 69
            os.chmod(exe, 0o755)
        self.own_dir(d, who)
        # The registration token first, so a token that cannot mint leaves
        # a runner already standing as it was.
        st, r = self.ctl.call("runner-token", {"kind": "registration", "slot": slot}, timeout=60)
        if st != 200 or not r.get("token"):
            kept = ", so the runner already here is left as it was" if installed else ""
            job.say(f"could not get a registration token from the controller{kept}: {r.get('error', st)}\n")
            return "failed", 69
        if installed:
            job.say("a runner is already registered here; deleting it on its host before registering again\n")
            self.runner_stop(d)
            self.ctl.call("runner-token", {"kind": "remove", "slot": slot,
                                           "runner_id": str(installed.get("id") or "")}, timeout=60)
            with contextlib.suppress(OSError):
                os.remove(os.path.join(d, ".runner"))
        # act_runner's --instance is the forge's ROOT: the scope (an
        # organization or a repository) is what the registration token
        # carries. Given the organization's URL it pings /lab/api/... and
        # retries a 404 forever (measured against a real Gitea, 15 Sep).
        u = urllib.parse.urlsplit(url)
        instance = f"{u.scheme}://{u.netloc}"
        job.say(f"registering {name} with {url} (instance {instance}) [{','.join(labels)}]\n")
        job.flush()          # a register can hang; the log says where it is (B129)
        code = self._run_as(job, who, d, [exe, "register", "--no-interactive", "--instance", instance,
                                          "--token", r["token"], "--name", name,
                                          "--labels", ",".join(f"{x}:host" for x in labels)])
        if code != 0:
            return "failed", code
        with open(os.path.join(d, ".builderbot-labels"), "w") as f:
            f.write(",".join(labels))
        # The address the token was stored for, beside the labels: .runner
        # records only the root it registered with, and the row says the
        # organization or repository, which is what a person typed.
        with open(os.path.join(d, ".builderbot-url"), "w") as f:
            f.write(url)
        logs = ci_log_dir(self.state)
        self.own_dir(logs, who)
        with contextlib.suppress(OSError):
            os.chmod(logs, 0o755)
        # act_runner reads .env into every job it runs, as GitHub's does.
        with open(os.path.join(d, ".env"), "w") as f:
            f.write(runner_env_text(self.state))
        self.own_dir(d, who)
        if not self.runner_start(who, job, d):
            return "failed", 1
        self.hello()
        job.say("runner installed and started\n")
        return "succeeded", 0

    def runner_start(self, who, job=None, d=None):
        """The runner in directory d as a child of this process, as the
        enrolled account, its output into runner.log under the data store:
        GitHub's run.sh, or `act_runner daemon`. Its own session, so a stop
        reaches the listener and the workers it forks alike."""
        d = d or RUNNER_DIR
        say = job.say if job else (lambda t: log(t.rstrip("\n")))
        if os.path.isfile(os.path.join(d, "run.sh")):
            argv = ["bash", "./run.sh"]
        elif os.path.isfile(os.path.join(d, "act_runner")):
            argv = [os.path.join(d, "act_runner"), "daemon"]
        else:
            say("the runner has nothing to start: no run.sh and no act_runner\n")
            return False
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "LANG": "C.UTF-8",
               "HOME": d}
        if who:
            import pwd
            with contextlib.suppress(KeyError):
                env["HOME"] = pwd.getpwuid(who["user"]).pw_dir
        logf = os.path.join((self.state.get("stores") or {}).get("data") or "/tmp", "runner.log")
        try:
            out = open(logf, "ab")
            self.runner_procs[d] = subprocess.Popen(argv, cwd=d, env=env,
                                                    stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                                    start_new_session=True, **who)
            out.close()
        except (OSError, RuntimeError) as e:
            say(f"the runner could not start: {e}\n")
            self.runner_procs.pop(d, None)
            return False
        self.runner_tried[d] = time.time()
        log(f"runner: {' '.join(argv)} started in the foreground (pid {self.runner_procs[d].pid}), log {logf}")
        return True

    def runner_stop(self, d=None):
        """Stop the runner in directory d, or every one this agent started."""
        for dd in ([d] if d else list(self.runner_procs)):
            p = self.runner_procs.pop(dd, None)
            if p is None or p.poll() is not None:
                continue
            for sig, wait in ((signal.SIGTERM, 10.0), (signal.SIGKILL, 3.0)):
                with contextlib.suppress(OSError):
                    os.killpg(p.pid, sig)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    p.wait(wait)
                    break

    def runner_check(self):
        """Once a loop: every configured runner this agent is responsible
        for that is not running is started (after this agent restarted, or
        after it exited), not more often than every thirty seconds each.
        GitHub's runner is systemd's where there is systemd; act_runner is
        always this agent's. One already listening from an earlier agent
        process is left to it."""
        for d, _rec in runner_dirs():
            if has_systemd() and not os.path.isfile(os.path.join(d, "act_runner")):
                continue
            p = self.runner_procs.get(d)
            if p is not None and p.poll() is None:
                continue
            if time.time() - self.runner_tried.get(d, 0) < 30:
                continue
            if (_run(["pgrep", "-f", os.path.join(d, "bin/Runner.Listener")])
                    or _run(["pgrep", "-f", os.path.join(d, "act_runner") + " daemon"])):
                self.runner_tried[d] = time.time()
                continue                    # an earlier agent's; working
            log(f"runner {os.path.basename(d)}: not running; starting" if p is None
                else f"runner {os.path.basename(d)}: exited ({p.returncode}); starting again")
            self.runner_start(self.drop_privileges({}), d=d)
