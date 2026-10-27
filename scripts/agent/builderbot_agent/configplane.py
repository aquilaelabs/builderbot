"""The configuration plane (docs/nodes.md section 12): the node's own system, storage and network, applied as root."""
import contextlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from .base import (
    daemon_json_with_ip,
    ROOT_BUNDLE_DIR,
    DEFAULT_STORES,
    DIAL_BACK_S,
    NEEDRESTART_DIR,
    RUNNER_DIR,
    SANDBOX_BIN,
    SESSION_BIN,
    SESSION_CONF,
    SESSION_SUDOERS,
    TAILSCALE_BIN,
    TOOLS_DIR,
    UNIT_DROPIN,
    _run,
    log,
)
from .stores import (
    _can_chown,
    dir_bytes,
    make_store,
    mount_covering,
    prune_made,
    save_state,
    store_path_ok,
    tc_root,
)
from .backends import net_backend
from .toolchains import extract_sandbox_tool
from .sessnet import session_conf, session_sudoers
from .runners import runner_dirs, runner_slot
from .census import FEATURES, _os_release, export_gaps, mounts_now, network_now, services_now
from .jobs import Job, pump


# The journal kept across boots (R185) and kept to a gigabyte: journald's own
# ceiling is a tenth of the filesystem up to 4 GB, which on a small VPS is
# more than the machine can spare and on a large one more than anyone reads.
# The same bytes as provision-linux.sh's keep_journal writes.
JOURNAL_DROPIN = ("# Written by BuilderBot (R185): keep the journal across boots, and at most 1G of it.\n"
                  "[Journal]\nStorage=persistent\nSystemMaxUse=1G\n")


class ConfigPlaneMixin:
    """Agent's configuration plane: one of the parts class Agent (agent.py) is made of."""

    # -- the configuration plane (docs/nodes.md §12, phase 5) -----------------
    def system(self, job, spec):
        """Apply the desired storage or network config the controller holds
        for this node: the one root-privileged thing the agent does. Not
        dropped to the enrolled account, because mounts and addresses are
        root's; offered by the controller only to nodes that enrolled as a
        sandbox, and refused here without bb-sandbox, which is the stamp."""
        what = spec.get("apply")
        self.refresh_sandbox_tool(job)
        # Per verb, not one stamp for all of them (roadmap #23): storage and
        # network edit fstab and netplan, which only a machine provisioned
        # as a sandbox (a MANAGED node) hands over. A runner needs only its
        # tarball and a funnel only tailscale, and a container node (this
        # image in the node role) or a guest machine has neither the stamp
        # nor any reason to be refused either of those.
        if what in ("storage", "network", "root", "gpu", "gpu-off", "feature") and not os.access(SANDBOX_BIN, os.X_OK):
            job.say(f"refused: {what} edits this machine's own configuration, and this node "
                    f"was not provisioned as a BuilderBot sandbox ({SANDBOX_BIN} is not here)\n")
            return "failed", 77
        cfg = spec.get("config") if isinstance(spec.get("config"), dict) else {}
        if what == "root":
            return self._apply_root(job, cfg)
        if what == "storage":
            return self._apply_storage(job, cfg)
        if what == "network":
            return self._apply_network(job, cfg)
        if what == "runner":
            return self._apply_runner(job, cfg)
        if what == "funnel":
            return self._apply_funnel(job, cfg)
        if what == "uninstall":
            return self._apply_uninstall(job, cfg)
        if what in ("reboot", "poweroff"):
            return self._apply_power(job, what)
        if what == "gpu":
            return self._apply_gpu(job)
        if what == "door":
            return self._apply_door(job, cfg)
        if what == "lockdown":
            return self._apply_lockdown(job)
        if what == "feature":
            return self._apply_feature(job, cfg)
        if what == "gpu-off":
            # The emulator off the card (R102): the display's unit stopped,
            # the driver left alone; then a hello, as the set-up sends.
            rc = self._sh(job, [SANDBOX_BIN, "gpu-off"], timeout=120)
            self.hello_again("the GPU was switched off")
            return ("succeeded", 0) if rc == 0 else ("failed", rc)
        job.say(f"refused: unknown system job {what!r}\n")
        return "failed", 64

    def apply_ports_local(self, on):
        """Published ports bound to 127.0.0.1 by default on this node (R190,
        the operator, 11 Oct: a port published on a public VPS was open to
        the world, not only to its nginx): docker's `ip` in daemon.json, and
        docker restarted once when the file changed (its containers come
        back on their restart policy). Not root: said, and the census says
        it is not in force. The hello carries the switch; the first hello
        of a fresh hosting node applies it before anything runs there."""
        path = "/etc/docker/daemon.json"
        if os.geteuid() != 0 or not shutil.which("docker"):
            # Once per run: it was said on every hello, switch on or off.
            if not getattr(self, "_ports_said", False):
                self._ports_said = True
                log("published ports: this agent is not root here, or docker is not here, so the bind address is left as it is")
            return
        try:
            text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
        except OSError as e:
            log(f"published ports: {path} could not be read ({e})")
            return
        new = daemon_json_with_ip(text, on)
        if new is None:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".new", "w", encoding="utf-8") as f:
                f.write(new)
            os.replace(path + ".new", path)
        except OSError as e:
            log(f"published ports: {path} could not be written ({e})")
            return
        log("docker's defaults changed (published ports bound to 127.0.0.1, container logs bounded); restarting docker" if on
            else "docker's defaults changed (published ports bound to every address, container logs bounded); restarting docker")
        sc = shutil.which("systemctl")
        if sc:
            subprocess.run([sc, "restart", "docker"], capture_output=True, timeout=180, check=False)
        self.hello_again("published ports' bind address changed")

    def keep_journal(self):
        """The journal kept across boots (R185), as the provisioner sets it
        on a fresh enrollment, for a node enrolled before it did: a drop-in,
        journald restarted only when it is new. Root's; once per agent run."""
        if getattr(self, "_journal_kept", False):
            return
        self._journal_kept = True
        f = "/etc/systemd/journald.conf.d/50-builderbot.conf"
        # A managed node only, the way the rest of upkeep tells one: root, and
        # stamped a sandbox. A guest's journal is its owner's (R23).
        if os.geteuid() != 0 or not os.path.isfile(SANDBOX_BIN) or not shutil.which("journalctl"):
            return
        try:
            # The provisioner's keep_journal writes the same bytes; a file
            # that is not them (an older one, without the ceiling) is
            # written again.
            if os.path.isfile(f) and open(f, encoding="utf-8").read() == JOURNAL_DROPIN:
                return
            os.makedirs(os.path.dirname(f), exist_ok=True)
            os.makedirs("/var/log/journal", exist_ok=True)
            with open(f + ".new", "w", encoding="utf-8") as out:
                out.write(JOURNAL_DROPIN)
            os.replace(f + ".new", f)
        except OSError as e:
            log(f"journal: could not keep it across boots ({e})")
            return
        for argv in (["systemd-tmpfiles", "--create", "--prefix", "/var/log/journal"],
                     ["systemctl", "restart", "systemd-journald"]):
            if shutil.which(argv[0]):
                subprocess.run(argv, capture_output=True, timeout=60, check=False)
        log("journal: kept across boots from now")

    def _apply_door(self, job, cfg):
        """The door in for SSH on or off (R174): cloudflared's service
        started or stopped (and kept so across a boot), or the node brought
        up on its tailnet or taken down. Root's, like every system job; the
        census that follows is what the row's switch reads."""
        d = self.state.get("door") if isinstance(self.state.get("door"), dict) else {}
        kind = str(d.get("kind") or "")
        if kind not in ("cloudflared", "tailscale"):
            job.say("refused: this node was provisioned with no door in (the Enroll dialog's SSH door)\n")
            return "failed", 77
        on = cfg.get("on", True)
        if kind == "cloudflared":
            sc = shutil.which("systemctl")
            if not sc:
                job.say("refused: cloudflared's service is systemd's, and this machine has none\n")
                return "failed", 77
            code = self._sh(job, [sc, "enable" if on else "disable", "--now", "cloudflared"], timeout=120)
        else:
            code = self._sh(job, [TAILSCALE_BIN, "up", "--ssh"] if on else [TAILSCALE_BIN, "down"], timeout=120)
        self.hello_again("the SSH door was opened or shut")
        if code != 0:
            return "failed", code
        job.say(f"the door is {'open' if on else 'shut'}: {kind}{' at ' + d['host'] if d.get('host') else ''}\n")
        return "succeeded", 0

    def _apply_feature(self, job, cfg):
        """A feature installed or removed (R91): bb-sandbox's own feature
        install, the one the provisioner's flag runs at enrollment, so the
        two ways cannot drift. The id and the verb are checked against the
        helper's table here as well, so nothing else reaches its argv."""
        fid, op = str(cfg.get("id") or ""), str(cfg.get("op") or "")
        if fid not in FEATURES or op not in ("install", "remove"):
            job.say(f"refused: {op or 'no verb'} {fid or 'no feature'} is not a feature verb (one of {', '.join(FEATURES)})\n")
            return "failed", 64
        rc = self._sh(job, [SANDBOX_BIN, "feature", op, fid], timeout=1800)
        self.hello_again(f"the {fid} feature was {'installed' if op == 'install' else 'removed'}")
        return ("succeeded", 0) if rc == 0 else ("failed", rc)

    def _apply_lockdown(self, job):
        """Lock down (R92): every container here stopped and kept from
        starting again at a boot (BuilderBot's nginx among them), and the
        door in shut. The controller retires this node when this ends, so
        its credential goes with it; a part that fails is said and the rest
        still done."""
        bad = 0
        docker = shutil.which("docker")
        ids = []
        if docker:
            r = subprocess.run([docker, "ps", "-q"], capture_output=True, text=True, timeout=60, check=False)
            ids = r.stdout.split()
            bad += r.returncode != 0
        if ids:
            job.say(f"stopping {len(ids)} container(s), and none starts again at a boot\n")
            bad += self._sh(job, [docker, "update", "--restart=no", *ids], timeout=120) != 0
            bad += self._sh(job, [docker, "stop", "-t", "10", *ids], timeout=600) != 0
        else:
            job.say("no container was running\n" if docker else "no docker here\n")
        d = self.state.get("door") if isinstance(self.state.get("door"), dict) else {}
        if d.get("kind") == "cloudflared" and shutil.which("systemctl"):
            bad += self._sh(job, ["systemctl", "disable", "--now", "cloudflared"], timeout=120) != 0
        elif d.get("kind") == "tailscale":
            bad += self._sh(job, [TAILSCALE_BIN, "down"], timeout=120) != 0
        job.say("locked down: this node's credential is revoked as this job ends\n" if not bad
                else f"locked down with {bad} step(s) failing, above; this node's credential is revoked as this job ends\n")
        return ("succeeded", 0) if not bad else ("failed", 1)

    def _apply_gpu(self, job):
        """The NVIDIA driver and a headless X server on the card, for the
        emulator's -gpu host (R20): bb-sandbox gpu does it and says whether
        a reboot has to follow; then a hello, so the row reads the display's
        state now rather than at the next census."""
        rc = self._sh(job, [SANDBOX_BIN, "gpu"], timeout=1800)
        self.hello_again("the GPU was set up")
        return ("succeeded", 0) if rc == 0 else ("failed", rc)

    def _apply_power(self, job, what):
        """Reboot the machine or power it off, a few seconds out, so this
        job's result reaches the controller before the agent goes with it.
        Root's, like a mount: an agent running as an account refuses and
        names the command for the machine's own console."""
        verb = "reboot" if what == "reboot" else "power off"
        if os.geteuid() != 0:
            job.say(f"refused: a {verb} is root's, and this agent does not run as root: on the "
                    f"machine, sudo {'reboot' if what == 'reboot' else 'poweroff'}\n")
            return "failed", 77
        # Every session here ended first, as End does, and said to the
        # controller before the machine goes (the operator, 26 Oct): cut off
        # by the power-off they were left open on the record, and a Restart
        # after the boot met one that was not there.
        names = [str((r or {}).get("name") or "") for r in (self.sessions_now() or [])]
        names = [n for n in names if n]
        if names:
            job.say(f"ending {len(names)} session{'' if len(names) == 1 else 's'} first: {', '.join(names)}\n")
            self.kill_sessions(names, why=f"before a {verb}")
            self.hello_again(f"its sessions ended before a {verb}")
            # ...and the hello that says so given time to leave: the loop
            # sends it, and a power-off three seconds out could beat it.
            for _ in range(20):
                time.sleep(0.5)
                if getattr(self, "hello_at", 1):
                    break
        cmd = ([shutil.which("systemctl"), what] if shutil.which("systemctl")
               else ["shutdown", "-r" if what == "reboot" else "-h", "now"])
        try:
            subprocess.Popen(["sh", "-c", 'sleep 3; exec "$@"', "sh", *cmd],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError as e:
            job.say(f"could not start the {verb}: {e}\n")
            return "failed", 69
        job.say(f"{verb} in 3 seconds; the row reads away until the agent dials in again"
                + ("" if what == "reboot" else ", which after a power off takes somebody switching the machine on")
                + "\n")
        return "succeeded", 0

    def refresh_sandbox_tool(self, job):
        """The machine's bb-sandbox brought up to the bundle's copy before a
        system job runs, when this agent is root and a copy is there to
        compare: the provisioner wrote it once, a verb the controller now
        asks for (uninstall, 15 Sep) may be newer than that write, and the
        bundle carries the provisioner it is embedded in. Said when it
        changes, silent otherwise; a machine that was never a sandbox has no
        copy and gets none."""
        if os.geteuid() != 0 or not os.path.isfile(SANDBOX_BIN):
            return
        # The bundle fetched first (B163): nothing else in a system job does,
        # so root's copy was whatever some other job or a session had last
        # pulled, and a job pressed right after a controller update ran the
        # helper from before it. A fetch of an unchanged bundle is one
        # download checked by digest. Not on a hosting-only node, which the
        # controller refuses the bundle (403 at the head of every system
        # job's log, R97's walk): its helper is the one Enroll again writes.
        if tc_root(self.state) and not self.state.get("host_only"):
            try:
                who = self.as_user({}, self.state.get("user") or "")
            except RuntimeError:
                who = {}
            self.bundle(job, who)
        # From root's own copy, never the store's: the store is the job
        # account's to write.
        src = os.path.join(TOOLS_DIR, "current", "nodes", "provision-linux.sh")
        if not os.path.isfile(src):
            return
        try:
            with open(src, encoding="utf-8") as f:
                want = extract_sandbox_tool(f.read())
            with open(SANDBOX_BIN, encoding="utf-8") as f:
                have = f.read()
        except OSError:
            return
        if not want or want == have:
            return
        tmp = SANDBOX_BIN + ".new"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(want)
            os.chmod(tmp, 0o750)
            os.replace(tmp, SANDBOX_BIN)
        except OSError as e:
            job.say(f"could not refresh {SANDBOX_BIN} from the bundle: {e}\n")
            return
        job.say(f"{SANDBOX_BIN} refreshed from the bundle\n")

    def quiet_distro_ttyd(self, run=_run):
        """The distribution's own ttyd switched off, on a managed node (B167).

        Debian's package enables ttyd.service: root, on lo:7681, serving a
        login prompt, which nothing here asked for and which every session on
        the machine can reach over loopback. The provisioner disables it, but
        only when it runs, so a node provisioned before that fix kept it until
        somebody re-provisioned. This is the process that is already on every
        node, so it asks each time it does its upkeep and says so when it acts.
        Not on a guest: that machine's services are its owner's (R23). The
        agent's own ttyds are processes it started, not this unit."""
        if os.geteuid() != 0 or not os.path.isfile(SANDBOX_BIN) or not shutil.which("systemctl"):
            return False
        on = (run(["systemctl", "is-enabled", "ttyd.service"]) == "enabled"
              or run(["systemctl", "is-active", "ttyd.service"]) == "active")
        if not on:
            return False
        run(["systemctl", "disable", "--now", "ttyd.service"], timeout=30)
        log("sessions: switched off the distribution's own ttyd.service (root, on lo:7681), "
            "which every session on this machine could reach")
        return True

    def keep_sessions_through_restart(self, run=_run):
        """The sessions outlive a stop of this unit, on a managed node (B538).

        The provisioner writes the unit with KillMode=process (B107), but only
        when it installs it, and it installs it only when it is not already
        running, so a node enrolled before then kept systemd's default, which
        takes every process in the cgroup on a stop: the tmux servers and
        every Claude session in them. On 7 Oct an unattended upgrade of
        librsvg had needrestart restart this unit, and every session on
        bb-sandbox ended. So the agent puts the setting in a drop-in itself,
        and tells needrestart to leave it alone: an upgraded library is
        picked up at the next agent update or reboot, not mid-conversation.
        Not on a guest, whose services are its owner's (R23)."""
        if os.geteuid() != 0 or not os.path.isfile(SANDBOX_BIN) or not shutil.which("systemctl"):
            return []
        did = []
        want = "[Service]\nKillMode=process\n"
        if run(["systemctl", "show", "-p", "KillMode", "--value", "builderbot-agent"]) != "process":
            try:
                os.makedirs(os.path.dirname(UNIT_DROPIN), exist_ok=True)
                with open(UNIT_DROPIN, "w", encoding="utf-8") as f:
                    f.write(want)
                run(["systemctl", "daemon-reload"], timeout=30)
                did.append("unit")
                log("sessions: this unit now stops its own process only (KillMode=process), "
                    "so a restart of the agent no longer ends the sessions")
            except OSError as e:
                log(f"sessions: could not write {UNIT_DROPIN}: {e}")
        if os.path.isdir(NEEDRESTART_DIR):
            conf = os.path.join(NEEDRESTART_DIR, "conf.d", "builderbot.conf")
            body = ("# Written by the BuilderBot agent (B538): a restart of the agent after a\n"
                    "# library upgrade ended every Claude session on the node.\n"
                    "$nrconf{override_rc}{qr(^builderbot-agent\\.service$)} = 0;\n")
            try:
                with open(conf, encoding="utf-8") as f:
                    same = f.read() == body
            except OSError:
                same = False
            if not same:
                try:
                    os.makedirs(os.path.dirname(conf), exist_ok=True)
                    with open(conf, "w", encoding="utf-8") as f:
                        f.write(body)
                    did.append("needrestart")
                    log("sessions: needrestart leaves the agent alone after an upgrade")
                except OSError as e:
                    log(f"sessions: could not write {conf}: {e}")
        return did

    def refresh_session_tool(self):
        """The session's view kept installed (R35): bb-session from the bundle,
        its layout file, and the session account's sudo rule, on a node set up
        as a sandbox whose agent is root and which runs sessions. Written when
        they differ and said when they change. A sudo rule is checked with
        visudo before it replaces anything, since a broken file under
        sudoers.d takes sudo away from every account on the machine; and it is
        written beside its final name with a dot in it, which sudo skips."""
        if self.state.get("host_only"):
            return                       # no sessions on a hosting-only node
        with self.tool_lock:
            self._refresh_session_tool()

    def _refresh_session_tool(self):
        user = self.session_account()
        if os.geteuid() != 0 or not os.path.isfile(SANDBOX_BIN) or not user:
            return
        src = os.path.join(TOOLS_DIR, "current", "nodes", "bb-session")
        try:
            with open(src, encoding="utf-8") as f:
                tool = f.read()
        except OSError:
            return
        wrote = []
        # Accounts as their own users (R125), once the agent has made the
        # group and bb-session is there to hold each to its own account.
        ready = getattr(self, "account_users_ready", None)
        accounts = {"controller": self.ctl.url, "pin": self.state.get("pin", ""),
                    "bundle": os.path.join(ROOT_BUNDLE_DIR, "current")} if ready and ready() else None
        for path, text, mode, sudoers in ((SESSION_BIN, tool, 0o755, False),
                                          (SESSION_CONF, session_conf(self.state, user, self.sessnet.conf_on, accounts),
                                           0o644, False),
                                          (SESSION_SUDOERS, session_sudoers(user, bool(accounts)), 0o440, True)):
            try:
                with open(path, encoding="utf-8") as f:
                    if f.read() == text:
                        continue
            except OSError:
                pass
            tmp = path + ".new"
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(text)
                os.chmod(tmp, mode)
                os.chown(tmp, 0, 0)
                if sudoers and shutil.which("visudo"):
                    r = subprocess.run(["visudo", "-cf", tmp], capture_output=True, text=True,
                                       timeout=20, check=False)
                    if r.returncode:
                        os.unlink(tmp)
                        log(f"not writing {path}: visudo refused it: {(r.stdout + r.stderr).strip()[:200]}")
                        continue
                os.replace(tmp, path)
                wrote.append(path)
            except OSError as e:
                log(f"could not write {path}: {e}")
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
        if wrote:
            log(f"the session's view: {', '.join(wrote)} written from the bundle")

    def _apply_uninstall(self, job, cfg=None):
        """Take BuilderBot off this machine, from the Nodes page. The runners
        first, deregistered on their forges with the tokens the controller
        mints while this agent can still ask; then `bb-sandbox uninstall`,
        started detached from this process because it removes this process
        (the unit, the accounts, the files). The controller retires the
        node when this job succeeds; the agent's last hello is its last."""
        if not os.access(SANDBOX_BIN, os.X_OK):
            job.say(f"refused: {SANDBOX_BIN} is not here, so this node was not provisioned as a sandbox\n")
            return "failed", 77
        for d, rec in runner_dirs():
            url = str(rec.get("gitHubUrl") or rec.get("address") or "")
            with contextlib.suppress(OSError):
                with open(os.path.join(d, ".builderbot-url")) as f:
                    url = f.read().strip() or url
            slot = os.path.basename(d.rstrip("/")) if os.path.realpath(d) != os.path.realpath(RUNNER_DIR) else runner_slot(url)
            job.say(f"deregistering the runner {slot} on its forge\n")
            job.flush()
            st, code = self._apply_runner(job, {"want": False, "slot": slot, "url": url,
                                                "forge": "gitea" if "address" in rec else "github"})
            if st != "succeeded":
                job.say(f"the runner {slot} could not be deregistered (exit {code}); it stays listed on its forge\n")
        argv = [SANDBOX_BIN, "uninstall", "--yes"]
        # The rings asked for (the operator, 11 Oct): the stores on the
        # disk, what was configured from the dashboard, a hosting node's
        # doors and proxy. Without them the machine keeps those.
        for ring in ("stores", "configured", "doors"):
            if (cfg or {}).get(ring):
                argv.append("--" + ring)
        # Under a transient unit of its own where this agent is root on a
        # systemd machine, so the uninstall outlives the unit it removes;
        # anywhere else (the harness, a machine without systemd) a detached
        # process, which the removal of this one does not take with it.
        # Started, then WATCHED for a few seconds before this job reports
        # (B132): an uninstall that fails at once (a bb-sandbox without the
        # verb, a refusal) must fail this job, or the controller retires a
        # node whose machine is untouched and whose credential is then dead.
        started = False
        proc = None
        if os.geteuid() == 0 and shutil.which("systemd-run"):
            r = subprocess.run(["systemd-run", "--unit", "builderbot-uninstall", "--collect",
                                "--quiet", *argv], capture_output=True, text=True, check=False)
            started = r.returncode == 0
            if not started:
                job.say(f"systemd-run would not take it ({(r.stderr or '').strip()[:120]}); starting it detached instead\n")
        if not started:
            # Its output kept on the machine, where its owner can read why
            # an uninstall stopped: the agent it would have reported to is
            # what it removes.
            out = "/var/log/builderbot-uninstall.log" if os.geteuid() == 0 else "/tmp/builderbot-uninstall.log"
            try:
                with open(out, "ab") as logf:
                    proc = subprocess.Popen(argv, stdout=logf, stderr=logf, start_new_session=True)
            except OSError as e:
                job.say(f"could not start the uninstall: {e}\n")
                return "failed", 69
        job.say("the uninstall is running on this machine\n")
        job.flush()
        time.sleep(4)
        if proc is not None:
            code = proc.poll()
            if code not in (None, 0):
                job.say(f"the uninstall ended at once with exit {code}; nothing of this node was retired\n")
                return "failed", code
        elif started:
            r = subprocess.run(["systemctl", "show", "-p", "ActiveState,Result", "builderbot-uninstall"],
                               capture_output=True, text=True, check=False)
            state = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
            if state.get("ActiveState") in ("failed",) or state.get("Result") not in ("", "success", None):
                tail = subprocess.run(["journalctl", "-u", "builderbot-uninstall", "--no-pager", "-n", "5", "-o", "cat"],
                                      capture_output=True, text=True, check=False).stdout.strip()
                job.say(f"the uninstall failed at once ({state.get('Result')}): {tail[-300:]}\n"
                        "nothing of this node was retired\n")
                return "failed", 70
        job.say("it is still running; this agent goes with it, so this is its last word\n")
        return "succeeded", 0

    def _sh(self, job, argv, cwd=None, timeout=300):
        """One command, its output into the job's log, its exit code back.

        `cwd` matters more than it looks: the runner's own svc.sh resolves
        everything relative to where it is invoked and refuses with "Must run
        from runner root or install is corrupt" anywhere else, which is
        exactly what a registered-but-serviceless runner came from.

        Streamed, the way Job.exec and _apply_root are: its output pumped
        as it comes and the log posted on a clock. It used to run the command
        to the end and post nothing meanwhile, so the NVIDIA rows on the
        Toolchains page never said installing (the step rides a log post) and
        the job sat at assigned for as long as apt took (30 Sep).
        """
        # A job that cannot post or be canceled (a check's own stand-in, a
        # test's) still runs the command and hears its output.
        flush = getattr(job, "flush", None) or (lambda: True)
        stopped = lambda: bool(getattr(job, "canceled", False))  # noqa: E731
        job.say("$ " + " ".join(argv) + "\n")
        flush()                          # the step and the command, now
        began = time.monotonic()
        try:
            p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            job.say(f"{argv[0]}: {e}\n")
            return 1
        with contextlib.suppress(AttributeError):
            job.proc = p
        if stopped():
            Job._kill(p)

        reader = pump(job, p.stdout, keep_blank=False)
        deadline, killed = time.monotonic() + timeout, False
        while reader.is_alive():
            reader.join(0.5)
            if getattr(job, "pending", None):
                flush()
            if time.monotonic() > deadline and not killed:
                job.say(f"timed out after {int(timeout)}s, killing it\n")
                Job._kill(p)
                killed = True
        p.wait()
        with contextlib.suppress(OSError):
            p.stdout.close()
        with contextlib.suppress(AttributeError):
            job.proc = None
        if stopped():
            job.say("stopped\n")
            return 130
        # A slow step says how slow (B243): an apply that took a minute to
        # change nothing gave no way to tell which command took it.
        took = time.monotonic() - began
        if took >= 3:
            job.say(f"   (took {took:.0f}s)\n")
        return 124 if killed else p.returncode

    def _apply_root(self, job, cfg):
        """One command as root, that a person allowed (roadmap R38). The
        controller queues this only after an administrator read the reason
        and the exact command and pressed Allow; the job's log opens with
        both and who it was, so the Jobs page is the record. Nothing about
        the command is interpreted here: it is run as given, as root, once,
        and its output and exit code go back. Not sudo: there is no second
        command without a second question."""
        argv = [str(a) for a in (cfg.get("argv") or []) if str(a)]
        if not argv:
            job.say("refused: nothing to run\n")
            return "failed", 64
        job.say(f"# root on this node, allowed by {cfg.get('by') or 'the operator'}: "
                f"{cfg.get('why') or '(no reason given)'}\n")
        try:
            timeout = max(1, min(int(cfg.get("timeout") or 600), 3600))
        except (TypeError, ValueError):
            timeout = 600
        # The same shape as Job.exec (its own process group, output pumped
        # as it comes, the log posted on a clock so a cancel can arrive and
        # land), minus the drop to the enrolled account, which is the point.
        # Not _sh: that blocks until the command ends with nothing posted,
        # so a cancel had nothing to reach and a timeout killed only the
        # direct child.
        job.say("$ " + " ".join(argv) + "\n")
        job.flush()
        try:
            p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        except OSError as e:
            job.say(f"could not start {argv[0]}: {e}\n")
            return "failed", 126
        job.proc = p
        if job.canceled:
            job._kill(p)

        reader = pump(job, p.stdout)
        deadline, killed = time.monotonic() + timeout, False
        while reader.is_alive():
            reader.join(0.5)
            if job.pending:
                job.flush()
            if time.monotonic() > deadline and not killed:
                job.say(f"timed out after {timeout}s, killing it\n")
                job._kill(p)
                killed = True
        p.wait()
        job.proc = None
        if job.canceled:
            job.say("stopped\n")
            return "canceled", 130
        if killed:
            return "failed", 124
        return ("succeeded" if p.returncode == 0 else "failed"), p.returncode

    SESSION_PROFILE = "/etc/profile.d/builderbot-session.sh"

    def write_session_profile(self, job=None):
        """The console shell's PATH line, from where the toolchain store IS.
        The provisioner writes this file once, naming the store it was
        given; a Storage apply that moves the store left it naming the old
        one, so a shell as the session account had no bb (B135). Rewritten
        from the agent's own record after every apply, root only, and left
        alone where the file was never written (a guest node)."""
        if os.geteuid() != 0 or not os.path.isfile(self.SESSION_PROFILE):
            return
        who = self.session_account()
        root = tc_root(self.state)
        ctl = (self.ctl.url or "").rstrip("/")
        text = (
            "# Written by BuilderBot's agent. A session on this node, at a console.\n"
            'case "$(id -un)" in\n'
            f"    {who})\n"
            "        export BUILDERBOT_ROLE=node WORKSPACE=/workspace\n"
            '        export BB_NODE="$(hostname)"\n'
            + (f'        export BB_CONTROLLER="{ctl}"\n' if ctl else "")
            + (f'        [ -d "{root}/.bb/current/scripts" ] \\\n'
               f'            && PATH="{root}/.bb/current/scripts:$PATH"\n' if root else "")
            + '        PATH="$HOME/.local/bin:$PATH"\n'
            "        ;;\n"
            "esac\n")
        try:
            tmp = self.SESSION_PROFILE + ".tmp"
            with open(tmp, "w") as f:
                f.write(text)
            os.chmod(tmp, 0o644)
            os.replace(tmp, self.SESSION_PROFILE)
            if job:
                job.say(f"console PATH: {self.SESSION_PROFILE} names {root or 'no store'}\n")
        except OSError as e:
            log(f"could not write {self.SESSION_PROFILE}: {e}")

    def _apply_storage(self, job, cfg):
        """Mounts as a diff against what bb-sandbox has: remove what is no
        longer wanted, add or rewrite what is (add-nfs/add-share rewrite an
        existing fstab line, so this is idempotent), then the stores, which
        are this agent's own file. Ends with a hello, so the row shows the
        applied state now rather than at the next census."""
        want = [m for m in (cfg.get("mounts") or []) if isinstance(m, dict)]
        have = {m.get("path"): m for m in mounts_now()}
        bad = 0
        for path in have:
            if not any(w.get("path") == path for w in want):
                if self._sh(job, [SANDBOX_BIN, "remove", path]) != 0:
                    bad += 1
        for w in want:
            path, src = str(w.get("path") or ""), str(w.get("source") or "")
            kind, ro = str(w.get("type") or "nfs"), bool(w.get("ro"))
            if not path.startswith("/") or not src:
                job.say(f"skipping a mount with no path or source: {w!r}\n")
                bad += 1
                continue
            if (why := store_path_ok(path, "a mount point")):
                job.say(f"refused the mount at {path}: {why}\n")
                bad += 1
                continue
            # Already there as wanted: said, and nothing run (B243). Every
            # mount used to be applied again on every apply, which cost a
            # node with four shares over a minute to change nothing.
            h = have.get(path) or {}
            if (h.get("mounted") and not h.get("stale") and str(h.get("source") or "") == src
                    and str(h.get("type") or "nfs") == kind and bool(h.get("ro")) == ro
                    and str(h.get("real") or "") == src):
                job.say(f"== {path} is mounted from {src}, as it is wanted\n")
                continue
            verb = "add-share" if kind == "virtiofs" else "add-nfs"
            if self._sh(job, [SANDBOX_BIN, verb, f"{src}:{path}" + (":ro" if ro else "")]) != 0:
                bad += 1
        stores = cfg.get("stores") if isinstance(cfg.get("stores"), dict) else {}
        # A store that moves holds the node's sessions while it does (R120
        # step 7): written where every session's gate reads it, and taken
        # away however this ends.
        was_at = dict(self.state.get("stores") or {})
        moving = sorted(r for r, p in stores.items() if r in DEFAULT_STORES and r != "cache"
                        and was_at.get(r) and str(was_at[r]).rstrip("/") != str(p).rstrip("/"))
        # Where the hold goes is fixed now: a move of the toolchain store
        # itself repoints the bundle, and the sessions' gates read the one
        # they started with.
        self._hold_at = self._hold_file() if moving else None
        if moving:
            self._hold(f"moving its {' and '.join(moving)} store{'s' if len(moving) > 1 else ''}")
        try:
            bad += self._apply_stores(job, stores, cfg)
        finally:
            if moving:
                self._hold(None)
            self._hold_at = None
        self.hello()
        if bad:
            job.say(f"{bad} of the changes did not apply; the rest did\n")
            return "failed", 1
        job.say("storage applied\n")
        return "succeeded", 0

    def _hold_file(self):
        """Where a session's gate on this node looks for a hold: beside the
        bundle in the toolchain store, which every session reads (its bb is
        there), or None on a node without one."""
        root = tc_root(self.state)
        return os.path.join(root, ".bb", "hold.json") if root else None

    def _hold(self, said):
        """Hold this node's sessions with `said` (what is happening, in
        words), or lift the hold with None. Rewritten as the work goes, with
        when it was last said, so a hold left by an agent that died is seen
        as stale rather than holding forever."""
        f = getattr(self, "_hold_at", None)
        if not f:
            return
        try:
            if said is None:
                with contextlib.suppress(FileNotFoundError):
                    os.remove(f)
                return
            now = int(time.time())
            was = {}
            with contextlib.suppress(OSError, ValueError):
                with open(f) as fh:
                    was = json.load(fh)
            tmp = f + ".new"
            with open(tmp, "w") as fh:
                json.dump({"what": "storage", "node": self.state.get("name") or "",
                           "said": said, "since": int(was.get("since") or now), "updated": now}, fh)
            os.chmod(tmp, 0o644)
            os.replace(tmp, f)
        except OSError:
            pass

    def _apply_stores(self, job, stores, cfg):
        """The stores half of a storage apply: how many did not apply."""
        bad = 0
        if stores:
            # Read the mounts back AFTER applying them: what a store may sit
            # on is what is mounted now, not what was asked for.
            live = mounts_now()
            mine = dict(self.state.get("stores") or {})
            # What this agent created for each store, so a move can take
            # back exactly that and nothing else.
            marks = dict(self.state.get("store_made") or {})
            # The stores asked to move without their data (R120).
            keep = {str(r) for r in (cfg.get("keep") or []) if isinstance(r, str)}
            for role, path in stores.items():
                if role not in DEFAULT_STORES:
                    continue
                why = store_path_ok(path)
                if why:
                    job.say(f"refused {role} store: {why}\n")
                    bad += 1
                    continue
                # The silent failure this exists to stop: a share that is in
                # fstab but not mounted leaves its mountpoint an ordinary
                # empty directory, mkdir cheerfully makes the store inside
                # it, and everything then lands on the node's own disk while
                # the row reports a healthy store with plenty of room. So a
                # store under a configured mount is refused unless that
                # mount is really mounted: fix the share, or take the entry
                # out and mean it locally.
                cover = mount_covering(path, live)
                if cover and not os.path.ismount(str(cover.get("path") or "")):
                    job.say(f"refused {role} store {path}: it is inside {cover.get('path')}, "
                            f"which is configured as a {cover.get('type') or 'nfs'} mount from "
                            f"{cover.get('source') or '?'} and is NOT mounted. Writing there would "
                            f"put {role} on this node's own disk and look like it worked. Fix the "
                            f"mount, or remove it from this node's mounts if {path} is meant to be "
                            f"local.\n")
                    bad += 1
                    continue
                # ...nor one mounted wrong (the operator, 23 Oct: a store on
                # a configured share must be on that share, mounted, or the
                # apply fails): a stale handle, or another export than the
                # one configured, is not the share it names.
                if cover and (cover.get("stale") or (cover.get("real") and cover.get("source")
                                                    and cover["real"] != cover["source"])):
                    job.say(f"refused {role} store {path}: it is inside {cover.get('path')}, which is "
                            + ("mounted but stale (the export went away under it)"
                               if cover.get("stale") else
                               f"mounted from {cover.get('real')} rather than {cover.get('source')}")
                            + f". {role} stays where it was until that mount is right.\n")
                    bad += 1
                    continue
                try:
                    made = make_store(path)
                except OSError as e:
                    job.say(f"{role} store {path} could not be made: {e.strerror}\n")
                    bad += 1
                    continue
                if made:
                    job.say(f"{role}: made {', '.join(made)}\n")
                was = str(mine.get(role) or "")
                if was and was.rstrip("/") != str(path).rstrip("/") and role in keep:
                    try:
                        with os.scandir(path) as it:
                            there = any(True for _ in it)
                    except OSError:
                        there = False
                    job.say(f"{role}: now {path}, "
                            f"{'using what is already there' if there else 'starting empty'} as asked; "
                            f"what was in {was} stays there\n")
                    marks[role] = made
                elif was and was.rstrip("/") != str(path).rstrip("/"):
                    if not self._move_store(job, role, was, str(path)):
                        # The move did not happen, so nothing was written to
                        # the new place: leave no litter behind either.
                        for d in prune_made(made)[0]:
                            job.say(f"{role}: removed {d} again; the move did not happen\n")
                        bad += 1
                        continue
                    self._retire_store(job, role, was, marks.get(role) or [])
                    marks[role] = made
                else:
                    # Same path. Keep the original record (it says what was
                    # made for this store the FIRST time, which is what a
                    # later move has to clean up) and add anything this run
                    # had to put back.
                    prev = list(marks.get(role) or [])
                    marks[role] = prev + [d for d in made if d not in prev]
                mine[role] = str(path)
                job.say(f"{role} store: {path}\n")
            self.state["stores"] = mine
            self.write_session_profile(job)
            self.state["store_made"] = marks
            save_state(self.state)
        return bad

    def _move_store(self, job, role, old, new):
        """Repointing a store used to leave its contents behind: the node
        started using an empty directory and the toolchains, AVDs or built
        artifacts stayed where they were, with nothing saying so. So the
        contents come across first, and the job only repoints if they did.

        The source is never deleted, the same rule the node-change
        migration keeps (roadmap #17). A half-finished move must leave the
        old store able to serve, and reclaiming the space is the operator's
        to do once they can see both.

        `cache` is the exception: it is rebuildable by definition, and a
        cold cache costs the next build time and never correctness, so
        copying tens of gigabytes of it across a link would be work for
        nothing.
        """
        if not os.path.isdir(old):
            job.say(f"{role}: nothing at {old} to bring across\n")
            return True
        # Never a merge (R120): copied into a folder that already holds
        # files, the old store's would overwrite theirs by name. The page
        # puts a store that is pointed at one in a folder named for the
        # node inside it; anything else asking for this is refused.
        try:
            with os.scandir(new) as it:
                holds = any(True for _ in it)
        except OSError:
            holds = False
        if holds and role != "cache":
            job.say(f"refused: {new} already holds files, and copying {role} into it would "
                    f"mix the two. Point {role} at an empty folder, or move it without its "
                    f"data. {role} still points at {old}.\n")
            return False
        if role == "cache":
            job.say(f"{role}: leaving {old} where it is, because a cache is rebuildable "
                    f"and the new one starts cold\n")
            return True
        try:
            if not os.listdir(old):
                job.say(f"{role}: {old} is empty, nothing to bring across\n")
                return True
        except OSError as e:
            job.say(f"{role}: cannot read {old}: {e.strerror}\n")
            return False
        size = dir_bytes(old)
        try:
            free = shutil.disk_usage(new).free
        except OSError as e:
            # The share the store is being pointed at, not reachable from
            # here. Said plainly: an unguarded disk_usage raised out of the
            # job and came back as "agent error: FileNotFoundError", which
            # names the exception rather than the path.
            job.say(f"refused: {new} cannot be read ({e.strerror}). Nothing was moved "
                    f"and {role} still points at {old}.\n")
            return False
        if size is not None:
            job.say(f"{role}: bringing {size // 1048576}MB across from {old}; "
                    f"{free // 1048576}MB free at {new}\n")
            if size > free:
                job.say(f"refused: {new} has not got room for it. Nothing was moved and "
                        f"{role} still points at {old}.\n")
                return False
        else:
            job.say(f"{role}: bringing {old} across (size unknown)\n")
        # cp -a, not shutil: it keeps ownership, times and links, and one C
        # process beats a per-file round trip over NFS. Six hours, because
        # a toolchain store is tens of gigabytes and this is the one system
        # job that can legitimately take that long.
        #
        # ...but not ownership where ownership is not the mover's to keep. A
        # share exported all_squash (which is what the projects and SDK
        # shares here ARE, so that a file written from any machine is owned
        # the way the array expects) refuses every chown, and `cp -a` then
        # exits non-zero after copying every byte correctly. The store move
        # read that as a failed copy and refused to repoint, with the data
        # sitting in the new place: "Operation not permitted", four times,
        # and a job that says the copy failed when it did not.
        argv = ["cp", "-a"]
        if not _can_chown(new):
            argv.append("--no-preserve=ownership")
            job.say(f"{new} squashes ownership (an all_squash export, most likely), so "
                    f"the copy keeps times, modes and links and the export decides the "
                    f"owner, which is the arrangement, not a loss.\n")
        # The store's ENTRIES, not `old/.`: given the directory itself cp
        # ends by setting the destination's own times, which a squashed
        # export refuses for a root it does not let this account own, and
        # an otherwise complete copy (of an empty store, the first time)
        # came back as a failure. An empty store has nothing to copy.
        try:
            entries = sorted(os.path.join(old, e) for e in os.listdir(old))
        except OSError as e:
            job.say(f"refused: could not read {old}: {e}\n")
            return False
        # How far it has got, said in the hold every session on the node
        # reads (R120 step 7), so a held session can say more than "wait".
        stop = threading.Event()

        def tick():
            while not stop.wait(20):
                got = dir_bytes(new)
                far = (f"{min(99, got * 100 // size)}% copied" if size and got is not None
                       else f"{(got or 0) // 1048576}MB copied")
                self._hold(f"moving its {role} store to {new}: {far}")
        if entries:
            threading.Thread(target=tick, daemon=True).start()
        try:
            copied = not entries or self._sh(job, argv + entries + [new + "/"], timeout=21600) == 0
        finally:
            stop.set()
        if not copied:
            job.say(f"refused: the copy failed. {role} still points at {old}, "
                    f"which is untouched.\n")
            return False
        job.say(f"{role}: copied. The old copy at {old} is left in place; "
                f"delete it yourself once you are satisfied.\n")
        return True

    def _retire_store(self, job, role, old, made):
        """After a store has moved, take back the directories this agent
        made for it, and only those, and only if they are empty.

        Which is usually none of them, and saying so matters: the move keeps
        the old copy on purpose, so the store directory is not empty and
        rmdir refuses it. That is the correct outcome, not a failure, and
        the log says which path is still holding data so it can be removed
        deliberately. The empty case is real too: a store that was
        configured and never written to leaves directories behind that
        nobody wants.
        """
        if not made:
            job.say(f"{role}: {old} was not made by this agent, so it is left alone\n")
            return
        removed, kept = prune_made(made)
        if removed:
            job.say(f"{role}: removed {', '.join(removed)} (made for this store "
                    f"and empty now)\n")
        for path, why in kept:
            job.say(f"{role}: {path} stays ({why})"
                    + (": the old copy is in there; remove it yourself when you are "
                       "satisfied the move worked\n" if "empty" in (why or "").lower()
                       else "\n"))

    def _apply_network(self, job, cfg):
        """Commit/confirm, because this is the one change that can cut the
        cord it arrives on (docs/nodes.md §12): render the desired address
        through whichever backend owns this machine's network (netplan, or
        NetworkManager), apply it, then dial the controller from wherever
        the machine landed. No answer within DIAL_BACK_S and the previous
        config is put back and applied again, and the failure is reported
        on reconnect. The spec is the same whatever the backend."""
        backend = net_backend()
        if backend is None:
            job.say("refused: network changes need a backend this agent drives (netplan, "
                    "NetworkManager, systemd-networkd, wicked, ifupdown or dhcpcd), and "
                    f"{_os_release() or 'this node'} has none of them running; set the address "
                    "by hand, or on a node that has one\n")
            return "failed", 77
        net = cfg.get("network") if isinstance(cfg.get("network"), dict) else cfg
        iface = str(net.get("interface") or network_now().get("interface") or "")
        if not iface:
            job.say("refused: no interface named and no default route to read one from\n")
            return "failed", 65
        mode = "static" if net.get("mode") == "static" else "dhcp"
        addr, gw = str(net.get("address") or ""), str(net.get("gateway") or "")
        dns = [str(d) for d in (net.get("dns") or []) if str(d)]
        # Static routes (the operator, 7 Oct), in either mode: a network
        # beyond this one and the router that reaches it.
        routes = [{"to": str(r.get("to") or ""), "via": str(r.get("via") or "")}
                  for r in (net.get("routes") or []) if isinstance(r, dict)]
        routes = [r for r in routes if re.fullmatch(r"[0-9.]+/\d{1,2}", r["to"])
                  and re.fullmatch(r"[0-9.]+", r["via"])][:32]
        if routes and getattr(backend, "no_routes", ""):
            job.say(f"refused: {backend.no_routes}\n")
            return "failed", 77
        if mode == "static" and not addr:
            job.say("refused: a static address needs an address\n")
            return "failed", 65
        why = backend.ready(iface)
        if why:
            job.say(f"refused: {why}\n")
            return "failed", 77
        # The one check that would have saved the operator's evening: the
        # host's NFS exports name this node's address, so a node that moves
        # loses its mounts unless the rule moves first, and the mount
        # fails quietly under nofail, at the next boot, on a share the
        # sessions need. Asked of the servers before anything changes.
        gaps = export_gaps(addr) if mode == "static" else []
        if gaps:
            job.say("refused: the host's NFS exports admit this node's current address and not "
                    "the new one, so the shares would not mount after the move. Change the rule "
                    "on the host first (Unraid: Shares -> the share -> NFS Security Settings), "
                    "then apply again:\n  " + "\n  ".join(gaps) + "\n")
            return "failed", 77
        desired = backend.render(iface, mode, addr, gw, dns, routes)
        before = backend.snapshot(iface)
        if backend.same(desired, before):
            job.say(f"already applied: {backend.name} already has this config\n")
            return "succeeded", 0
        if backend.apply(self, job, iface, desired, before) != 0:
            backend.restore(self, job, iface, before)
            return "failed", 1
        job.say(f"applied; dialing the controller back from the new address "
                f"(up to {DIAL_BACK_S}s)\n")
        deadline = time.time() + DIAL_BACK_S
        while time.time() < deadline:
            st, _ = self.hello()
            if st == 200:
                job.say(f"dialed back in from {network_now().get('addresses') or ['?']}\n")
                return "succeeded", 0
            # Never past the deadline: a fixed five seconds means a window
            # shorter than five seconds still costs five, which is what the
            # test that shortens DIAL_BACK_S was paying twice over.
            time.sleep(max(0.0, min(5.0, deadline - time.time())))
        job.say(f"could not reach the controller within {DIAL_BACK_S}s; reverting\n")
        backend.restore(self, job, iface, before)
        deadline = time.time() + DIAL_BACK_S
        while time.time() < deadline:
            if self.hello()[0] == 200:
                break
            time.sleep(max(0.0, min(5.0, deadline - time.time())))
        job.say("reverted to the previous network config\n")
        return "failed", 68

    def _apply_funnel(self, job, cfg):
        """Tailscale Funnel for one local port on https 443 (docs/nodes.md
        §7): tailscale's own CLI does the certificate, the DNS and the
        firewall, and its status is what the census reports afterwards."""
        if not (shutil.which(TAILSCALE_BIN) or os.access(TAILSCALE_BIN, os.X_OK)):
            job.say("refused: tailscale is not installed on this node\n")
            return "failed", 77
        try:
            port = int(cfg.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        if not 1 <= port <= 65535:
            job.say("refused: a funnel forwards to a port number\n")
            return "failed", 65
        if cfg.get("on", True):
            code = self._sh(job, [TAILSCALE_BIN, "funnel", "--bg", "--https=443",
                                  f"http://127.0.0.1:{port}"])
        else:
            code = self._sh(job, [TAILSCALE_BIN, "funnel", "--https=443", "off"])
        self.hello()
        if code != 0:
            return "failed", code
        job.say(("funnel on: https://" + (services_now().get("tailscale") or {}).get("dns", "?")
                 + f" -> 127.0.0.1:{port}\n") if cfg.get("on", True) else "funnel off\n")
        return "succeeded", 0
