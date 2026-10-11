"""The agent: the loop that says hello, takes jobs and runs them, composed from the parts beside it."""
import contextlib
import hashlib
import os
import signal
import subprocess
import sys
import threading
import time
from . import AGENT_VERSION
from .coverage import _COV_OUT, _cov_write
from .base import BEAT_S, log, own_digest, own_path
from .controller import Controller
from .stores import save_state
from .toolchains import share_images
from .sessnet import SessionNet
from .runners import RunnersMixin
from .census import Sampler, census
from .jobs import Job
from .ftp import FtpServers
from .wssync import WorkspaceSync
from .claudesync import ClaudeMirror
from .sessions import SessionWatch, SessionsMixin
from .workspace import WorkspaceMixin
from .work import WorkMixin
from .configplane import ConfigPlaneMixin
from . import storage


class Agent(WorkspaceMixin, SessionsMixin, WorkMixin, ConfigPlaneMixin, RunnersMixin):
    def __init__(self, state):
        self.state = state
        self.ctl = Controller(state["controller"], state["token"], state.get("pin", ""))
        self.jobs = {}
        self.lock = threading.Lock()
        self.sampler = Sampler()
        self.poll = 25
        self.hello_at = 0
        self.controller_digest = ""
        self.warned_caps = False
        # The session half (roadmap #24): the two ttyd processes, the bundle
        # they run bb-tty from, and when the last start was tried.
        self.ttyd = []
        self.session_bundle = ""          # the digest the ttyds run from
        self.session_digest = ""          # the digest bundle() last fetched
        self.session_tried = 0
        self.session_stale = ""           # a newer bundle's directory, for the loop to restart onto
        self.session_bound = ""           # the address the ttyds were bound to, to notice it moving
        # The census for the loop's next hello, taken beside the loop rather
        # than in it (B380): the thread, and what it came back with.
        self.census_thread = None
        self.census_next = None
        self.fw_checked = 0.0             # when the session ports' firewall rule was last checked
        self.tool_lock = threading.Lock()  # the session tool's files, written from two threads
        self.sessnet = SessionNet(self)    # each session kept to its own project's network (R79)
        self.sesswatch = SessionWatch(self)  # its sessions reported as they change
        self.ftp = FtpServers(self)        # a project's file access over FTP (R151)
        self.wssync = WorkspaceSync(self)  # its projects as a synced copy, where it holds them so (R162)
        self.claudesync = ClaudeMirror(self, self.wssync)  # ...and its sessions' conversations with them (B613)
        # The runner as a child of this process where there is no systemd:
        # run.sh in the foreground, supervised here.
        self.runner_procs = {}            # runner directory -> its process
        self.runner_tried = {}            # runner directory -> when it was last started

    # -- privilege ---------------------------------------------------------
    def drop_privileges(self, env):
        """Popen keywords that make the child the enrolled account. Empty
        when there is nothing to drop (not root, or enrolled as root on
        purpose). Popen's own user/group/extra_groups rather than a
        preexec_fn: this process has job threads, and a fork hook that runs
        between fork and exec can deadlock on a lock another thread held."""
        return self.as_user(env, self.state.get("user") or "")

    def as_user(self, env, user):
        """The same, for a named account: jobs drop to the enrolled one,
        sessions to the session one (roadmap #24), and they are different
        accounts on purpose."""
        if os.geteuid() != 0 or not user or user == "root":
            return {}
        import grp
        import pwd
        try:
            pw = pwd.getpwnam(user)
        except KeyError as e:
            raise RuntimeError(f"enrolled account {user!r} does not exist here") from e
        env.update({"HOME": pw.pw_dir, "USER": user, "LOGNAME": user})
        groups = [g.gr_gid for g in grp.getgrall() if user in g.gr_mem]
        return {"user": pw.pw_uid, "group": pw.pw_gid, "extra_groups": groups}

    # -- the channel -------------------------------------------------------
    def census_take(self):
        """The census a hello carries. The layout's one standing rule first,
        kept by the running agent (never by `enroll`, which may run with a
        store it cannot write yet)."""
        try:
            share_images((self.state.get("stores") or {}).get("toolchains") or "")
        except OSError as e:
            log(f"toolchain store: could not share the images ({e})")
        return census(self.state)

    def hello_step(self):
        """The loop's ten-minute hello, with its census taken on a thread
        beside the loop (B380). The census asks the slow questions (the
        toolchain store, docker, the session half), and the loop used to
        stand still for it right after holding a full-length work poll; the
        controller stamps last heard from at the start of each work call and
        at the end of hello, and reads a node unheard for three polls as not
        answering, so a census slower than fifty seconds put "its agent is
        not answering" on every project row for one poll. Now the loop keeps
        polling while the census is taken, and says hello with it once it
        is there. Returns hello's (status, answer) when one was said, and
        None while the census is still being taken. The first hello of the
        process is said at once, as it always was: nothing here should run
        before the controller has heard from this agent."""
        if not self.hello_at:
            # ...and one asked for now (the clock zeroed by a refusal or a
            # job that changed the machine) is said with a census of its
            # own; a census still on its way from before is let go.
            self.census_thread = None
            self.census_next = None
            return self.hello()
        if self.census_thread is None:
            self.census_next = None

            def take():
                try:
                    self.census_next = self.census_take()
                except Exception as e:                               # noqa: BLE001
                    log(f"census: {type(e).__name__}: {e}")
            self.census_thread = threading.Thread(target=take, daemon=True, name="census")
            self.census_thread.start()
            return None
        if self.census_thread.is_alive():
            return None
        self.census_thread = None
        c, self.census_next = self.census_next, None
        return self.hello(taken=c) if c is not None else self.hello()

    def census_beating(self):
        """census_take on the loop, with the controller told every twenty
        seconds that this node is still here: the census asks the slow
        questions, over a minute on a busy node, and with the work poll
        stopped for it the node read as not answering on every project row
        (the operator, 7 Oct). A controller without the beat verb answers
        404 and nothing else changes."""
        done = threading.Event()

        def beat():
            while not done.wait(BEAT_S):
                self.ctl.call("beat", {}, timeout=10)
        threading.Thread(target=beat, name="beat", daemon=True).start()
        try:
            return self.census_take()
        finally:
            done.set()

    def hello(self, taken=None):
        # `running` is the list of job ids this process still holds. The
        # controller reconciles against it: a job its row says is running
        # here that this agent does not know was lost with a restart, and is
        # failed there rather than left running forever (docs/nodes.md §9).
        # `taken` is a census hello_step took beside the loop; anybody else
        # takes one here, now.
        c = taken if taken is not None else self.census_beating()
        st, r = self.ctl.call("hello", {"census": c,
                                        "version": AGENT_VERSION,
                                        "digest": own_digest(),
                                        "running": self.running_ids(),
                                        "keep": self.keep_report()}, timeout=30)
        if st == 200:
            self.hello_at = time.monotonic()
            self.poll = int(r.get("poll") or 25)
            self.controller_digest = (r.get("agent") or {}).get("digest") or ""
            # Where toolchains land, from the controller's catalog. Kept on the
            # record so a job started before the next hello still has it, and
            # only replaced when the controller actually sends one: an older
            # controller says nothing and this node keeps its built-in answer.
            lay = r.get("layout")
            if isinstance(lay, list) and lay and lay != self.state.get("layout"):
                self.state["layout"] = lay
                save_state(self.state)
            # The idle rule for Claude sessions (the controller's idle.py),
            # kept in node.json so it is enforced here while the controller
            # is down. A node's sessions outlive a controller restart on
            # purpose; the rule about when they end must not.
            im = r.get("session_idle_minutes")
            if isinstance(im, int) and im >= 0 and im != self.state.get("session_idle_minutes"):
                self.state["session_idle_minutes"] = im
                save_state(self.state)
                log(f"sessions: idle rule is {im} minute(s)" if im else "sessions: no idle rule")
            # How many workers a test run here may use (R81), kept in
            # node.json the same way; 0 is this machine's cores.
            tw = r.get("test_workers")
            if isinstance(tw, int) and tw >= 0 and tw != self.state.get("test_workers", 0):
                self.state["test_workers"] = tw
                save_state(self.state)
                log(f"tests: {tw} worker(s) per run" if tw else "tests: every core per run")
            # Fresh credentials for the Claude sessions alive here (R27). A
            # session that is talking slides its own token forward on every
            # answer it gets; one sitting idle has nothing to slide it, and a
            # dead token is never renewed, which is what makes the life mean
            # anything for one that leaked. So the machine the session is on
            # keeps it, on the beat it already has.
            # Hosting only (the operator, 10 Oct): kept in node.json, and the
            # session half stopped the moment it is said; nothing of a
            # session, a synced copy or bb runs here after.
            ho = bool(r.get("host_only"))
            if ho != bool(self.state.get("host_only")):
                self.state["host_only"] = ho
                save_state(self.state)
                log("hosting only: containers, and nothing of a project or a session" if ho
                    else "no longer hosting only")
                if ho:
                    self.session_stop()
            self.keep_session_tokens(r.get("session_tokens") or [])
            # Whether each session here is kept to its own project's network,
            # and what each project owns here (R79), kept in node.json so it
            # holds while the controller is down. Only replaced when the
            # controller sends it: an older one says nothing.
            # The FTPS servers for its projects' file access (R151); a
            # controller from before them says nothing, and nothing runs.
            ft = r.get("ftp")
            if isinstance(ft, list):
                self.ftp.want(ft)
            sn = r.get("session_net")
            if isinstance(sn, dict) and sn != self.state.get("session_net"):
                self.state["session_net"] = {"on": bool(sn.get("on")),
                                             "own": sn.get("own") if isinstance(sn.get("own"), dict) else {},
                                             # ...and the containers' (R178): whether each project's
                                             # are kept to their own network here, and the map.
                                             "ctr_on": bool(sn.get("ctr_on")),
                                             "ctr": sn.get("ctr") if isinstance(sn.get("ctr"), dict) else {}}
                save_state(self.state)
            n = r.get("node") or {}
            # The row's capabilities are the controller's claim; the ones
            # this node ENFORCES are the ones it enrolled with, kept in
            # node.json. Logged when they differ so the disagreement is
            # visible on the box, and never silently adopted.
            claimed = set(n.get("capabilities") or [])
            held = set(self.state.get("capabilities") or [])
            # Once per process, not per hello: a node enrolled before the
            # controller stopped asking about capabilities has fewer than the
            # row claims, and saying so every ten minutes forever is noise
            # about a difference nothing acts on until a job requires one.
            if claimed - held and not self.warned_caps:
                self.warned_caps = True
                log(f"controller lists {', '.join(sorted(claimed - held))} "
                    "for this node; not enrolled for it here, and jobs "
                    "needing it will be refused. Re-enroll to adopt them.")
            log(f"hello: node {n.get('id')} ({n.get('name')}), state "
                f"{n.get('state')}, poll {self.poll}s")
            # The sessions this node runs use the bb the controller ships;
            # when that moves, fetch it and restart the ttyds onto it. The
            # running sessions are tmux's and survive the restart; only the
            # next connection runs the new bb-tty. Never fatal: the session
            # half must not take the job half down with it: a toolchain
            # store this process cannot write is a node with no sessions,
            # not a node with no agent.
            before = self.session_bundle
            self.session_try(r.get("bundle") or "")
            # The helper the new bundle carries goes in with the bundle. The
            # loop refreshes it before its hello and the bundle arrives after,
            # so it waited for the next hello: for ten minutes a session was
            # started by the new launcher under the old helper (B377).
            if self.session_bundle != before:
                self.refresh_session_tool()
            self.runner_env_sync()
            # A bundle that moved carries a catalog that may have moved with
            # it, and the census read that catalog before the fetch: one more
            # hello now, so the row does not show the old answer until the
            # next ten-minute one (R57). Once: the second sees no move.
            if before and self.session_bundle != before and not getattr(self, "_rehello", False):
                self._rehello = True
                try:
                    log("bundle moved: a fresh census follows")
                    return self.hello()
                finally:
                    self._rehello = False
        return st, r

    def running(self):
        with self.lock:
            return len(self.jobs)

    def running_ids(self):
        with self.lock:
            return sorted(self.jobs)

    def finished(self, job):
        with self.lock:
            self.jobs.pop(job.job["id"], None)

    def cancel(self, ids):
        with self.lock:
            hit = [self.jobs[i] for i in ids if i in self.jobs]
        for j in hit:
            log(f"job {j.job['id']}: canceled by the controller")
            j.cancel()

    def loop(self):
        delay = 1
        # The hourly walk of the disks, on its own thread (storage.py).
        storage.start(lambda: self.state)
        # What is THIS process's to end, ended by it. The ttyds go: a stop of
        # the unit is an update or a reboot, and the new agent starts its own.
        # The tmux servers they attached do not: they are their own daemons,
        # the sessions are inside them, and a conversation should survive an
        # agent update the way it survives a ttyd restart.
        #
        # That was already the intent and systemd was undoing it: the default
        # KillMode=control-group takes every process in the cgroup after this
        # handler returns, tmux included, so Update agent ended every session
        # on the machine (B107). The unit says KillMode=process now, which
        # means the jobs are this handler's to end too. With control-group
        # systemd was killing those, and leaving a build running while the
        # controller re-queues it is the one thing that change could have
        # cost.
        def bye(*_):
            with self.lock:
                running = list(self.jobs.values())
            for j in running:
                j.cancel()
            # Each job's end, said by this process before it goes: the job
            # threads die with it and the row read "lost: the agent
            # restarted" for a stop that was ordered (B287). Best effort, a
            # few seconds each; a controller that is away hears it at the
            # next hello's reconcile instead.
            for j in running:
                try:
                    self.ctl.call("result", {"job": j.job["id"], "state": "canceled", "exit": None,
                                             "error": "canceled: the agent was stopped", "outputs": []},
                                  timeout=5)
                except Exception as e:                               # noqa: BLE001
                    log(f"{j.job['id']}: could not say it was stopped: {e}")
            self.session_stop()
            self.runner_stop()
            self.ftp.stop_all()
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, bye)
        # The session half first, so the first hello's census already says
        # it is up: the bundle fetch answers with its own digest, so nothing
        # from hello is needed to start. A controller that is down fails the
        # fetch and the hello alike, and the hello that eventually succeeds
        # starts the sessions then.
        self.refresh_session_tool()
        self.quiet_distro_ttyd()
        self.keep_sessions_through_restart()
        self.session_try()
        self.sessnet.start()
        self.sesswatch.start()
        self.wssync.start()
        self.claudesync.start()
        while True:
            # The monotonic clock: a clock step killed a running job as timed
            # out and stopped hello for the size of the step (B286). Zero
            # means due now, whichever clock.
            if not self.hello_at or time.monotonic() - self.hello_at > 600:
                self.refresh_session_tool()
                self.quiet_distro_ttyd()
                said = self.hello_step()
                # None: the census is on its way; the work poll below is the
                # heartbeat meanwhile, and the next turn of the loop asks again.
                st, r = said if said is not None else (200, {})
                if st == 401:
                    log(f"refused: {r.get('error')}; this node's credential "
                        "is no longer good. Re-enroll with a new token.")
                    time.sleep(300)
                    continue
                if st != 200:
                    log(f"controller not answering ({st} {r.get('error', '')}); "
                        f"retrying in {delay}s")
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                delay = 1
            self.session_check()
            self.session_firewall_check()
            self.session_idle_reap()
            self.runner_check()
            n = self.running()
            # The controller counts what is running here from its own rows
            # and wakes a held poll when a job ends, so the poll is held at
            # full length whether or not anything is running. The count in
            # the sample is for the row's numbers, not for placement.
            wait = self.poll
            sample = self.sampler.sample(self.state, n)
            # The sessions this node runs ride the heartbeat (roadmap #24),
            # so the dashboard's Sessions card lists them beside its own.
            if self.ttyd:
                sample["sessions"] = self.sessions_now()
            # ...and the ports its containers publish, for other nodes'
            # sessions of the same project (R82).
            pub = self.published_now()
            if pub is not None:
                sample["published"] = pub
            # ...and what each account here is signed in to Claude as, on its
            # own slower clock, so the controller's record is true without a
            # session having to run (B104). Absent from most heartbeats,
            # which the controller reads as "no news" rather than as none.
            logins = self.logins_now()
            if logins is not None:
                sample["logins"] = logins
            # ...and each synced project's state here (R162).
            synced = self.wssync.status()
            if synced is not None:
                sample["sync"] = synced
            # ...and, leaving it, what is still to go up; and the last
            # clean-up's answer, until the controller has read it (R164).
            drain = self.wssync.drain()
            if drain is not None:
                sample["sync_drain"] = drain
            if self.wssync.clean_ask and (self.wssync.done() or {}).get("token") == self.wssync.clean_ask:
                sample["sync_clean"] = self.wssync.done()
            st, r = self.ctl.call("work", {"sample": sample, "running": n, "wait": wait},
                                  timeout=wait + 15)
            if st == 204:
                continue
            if st == 200 and r.get("cancel"):
                # Not a job: the ids of jobs here the operator has stopped.
                self.cancel([str(i) for i in r["cancel"]])
                continue
            if st == 200 and r.get("kill_sessions"):
                # ...or sessions here the operator ended from the Sessions
                # card: the session account's tmux is only reachable as it.
                self.kill_sessions([str(x) for x in r["kill_sessions"]])
                continue
            if st == 200 and r.get("tmux"):
                # ...or keys for a session here: the phone keyboard's row,
                # a console's line, a macro: typed into the pane as the
                # dashboard would type them into its own tmux.
                self.tmux_ops(r["tmux"] if isinstance(r["tmux"], list) else [])
                continue
            if st == 200 and r.get("sync"):
                # ...or synced projects that moved: the sync thread asks
                # what changed now rather than at its next look (R162).
                self.wssync.nudge(r["sync"] if isinstance(r["sync"], dict) else {})
                continue
            if st == 200 and r.get("hello"):
                # The controller refused something on the strength of a
                # census that may have gone stale. The census rides hello
                # every ten minutes, which is fine for a display and too
                # coarse for a gate. Say it again now, so the retry the
                # operator is about to make reasons about this machine as it
                # is rather than as it was.
                self.hello_at = 0
                continue
            if st == 200 and r.get("id"):
                self.take(r)
                continue
            if st == 401:
                log(f"refused: {r.get('error')}; re-enroll with a new token")
                self.hello_at = 0
                time.sleep(300)
                continue
            log(f"work: {st} {r.get('error', '')}; retrying in {delay}s")
            self.hello_at = 0                 # say hello again on the way back
            time.sleep(delay)
            delay = min(delay * 2, 60)

    def take(self, job):
        with self.lock:
            if job["id"] in self.jobs:
                return
            j = Job(self, job)
            self.jobs[job["id"]] = j
        log(f"job {job['id']}: {job.get('type')} "
            f"{' '.join((job.get('spec') or {}).get('argv') or [])[:80]}")
        j.start()

    # -- self-update (door 4) ------------------------------------------------
    def self_update(self, job, spec):
        want = spec.get("digest") or self.controller_digest
        # A job is passed over only when it is stuck: its work has ended and
        # it is only posting its end, AND the controller has it as finished
        # or dropped (spec "settled", B520). One like that blocked the update
        # that was the only way to unstick it. A job still working is never
        # left behind, whatever the controller says. The rest are named, so
        # one is seen rather than guessed at (B519).
        settled = set(spec.get("settled") or [])
        with self.lock:
            held = dict(self.jobs)
        others = sorted(i for i, j in held.items() if i != job.job["id"]
                        and not (i in settled and getattr(j, "reporting", False)))
        if others:
            job.say(f"busy: other jobs are running ({', '.join(others)}); try again when they finish\n")
            return "failed", 75
        st, body = self.ctl.call("download", None, timeout=60, method="GET", raw=True)
        if st != 200:
            job.say(f"download failed: {st}\n")
            return "failed", 69
        got = "sha256:" + hashlib.sha256(body).hexdigest()
        if want and got != want:
            job.say(f"digest mismatch: wanted {want[:19]}…, got {got[:19]}…\n")
            return "failed", 65
        if got == own_digest():
            job.say("already current\n")
            return "succeeded", 0
        me = own_path()
        tmp = me + ".new"
        with open(tmp, "wb") as f:
            f.write(body)
        os.chmod(tmp, 0o755)
        os.replace(tmp, me)
        job.say(f"installed {got[:19]}…; restarting\n")
        return "succeeded", 0

    def _run_as(self, job, who, cwd, argv):
        """One command as the enrolled account, in the runner's directory,
        its output into the log. config.sh refuses to run as root."""
        job.say("$ " + " ".join(a if "--token" not in argv[max(0, i - 1)] else "…" for i, a in enumerate(argv)) + "\n")
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "LANG": "C.UTF-8",
               "HOME": cwd}
        who2 = dict(who)
        if who:
            import pwd
            with contextlib.suppress(KeyError):
                env["HOME"] = pwd.getpwuid(who["user"]).pw_dir
        try:
            p = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=600, check=False, **who2)
        except (OSError, subprocess.SubprocessError) as e:
            job.say(f"{argv[0]}: {e}\n")
            return 1
        for line in p.stdout.decode("utf-8", "replace").splitlines():
            if line.strip():
                job.say(line + "\n")
        return p.returncode

    def reexec(self):
        # The ttyds first: execv keeps the children and loses every handle
        # to them, so the new image would find its ports held by processes
        # it cannot see and serve nothing new for as long as they lived.
        # The sessions are tmux's and stay; the new agent starts ttyd from
        # the bundle that is current, which is the point of updating.
        self.session_stop()
        log("re-executing the new agent")
        if _COV_OUT:
            _cov_write()        # an exec runs no exit hook, and this process's counts are its own
        os.execv(sys.executable, [sys.executable, own_path(), "run"])
