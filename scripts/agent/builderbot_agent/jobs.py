"""A job: one piece of work the controller sent, run on its own thread."""
import contextlib
import json
import os
import pty
import re
import select
import shutil
import subprocess
import threading
import time
import traceback
import urllib.request
from .base import AGENT_INSTALLS, AGENT_LOGINS, AGENT_LOGOUTS, log
from .toolchains import sdk_env


# ---------------------------------------------------------------------------
# jobs

def pump(job, stream, keep_blank=True):
    """Read a child's output into a job's log on a thread of its own, and
    return the thread. The one reader every job uses (the operator, 12 Oct:
    four had diverged): lines split on newlines, a line a meter redrew in
    place kept as the frame it ended on, and a meter that never prints a
    newline posted as its last frame once it passes 64 kB, rather than
    held in memory until the child exits."""
    def run():
        buf = b""
        try:
            while True:
                chunk = os.read(stream.fileno(), 65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = _last_frame(line.decode("utf-8", "replace") + "\n")
                    if keep_blank or text.strip():
                        job.say(text)
                if len(buf) > 65536:
                    text = _last_frame(buf.decode("utf-8", "replace"))
                    buf = b""
                    if text.strip():
                        job.say(text + "\n")
            if buf:
                text = _last_frame(buf.decode("utf-8", "replace"))
                if keep_blank or text.strip():
                    job.say(text + "\n")
        except (OSError, ValueError):
            pass                      # the pipe went with the process
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _last_frame(line):
    """A line a progress meter redrew in place (frames joined by carriage
    returns) as the frame it ended on. Every frame used to go into the log:
    sdkmanager's unzip meter was most of a toolchain job's 60 kB, and the
    lines worth reading were lost among them (the operator, 12 Oct)."""
    if "\r" not in line:
        return line
    end = "\n" if line.endswith("\n") else ""
    frames = [f for f in line.rstrip("\n").split("\r") if f.strip()]
    return (frames[-1].rstrip() if frames else "") + end

class Job(threading.Thread):
    """One job, on its own thread, reporting as it goes.

    Output is posted in batches by sequence number; a batch the controller
    did not acknowledge stays in `pending` and goes with the next one, so
    nothing is lost across a controller restart and nothing is doubled (the
    controller drops a sequence it already has). The result is retried with
    backoff until acknowledged: this thread is the record of the job until
    the controller has it.
    """

    def __init__(self, agent, job):
        super().__init__(daemon=True, name=job["id"])
        self.agent, self.job = agent, job
        self.pending, self.seq = [], 0
        self.lock = threading.Lock()
        # A cancel is a fact about the job on the controller's row, and it
        # reaches here two ways: named in a work reply, or as `cancel: true`
        # on the reply to a log post. Either sets this; the child is killed
        # from the exec loop, and the result says "canceled" rather than
        # "failed" so the row does not read as the command's own fault.
        self.canceled = False
        self.proc = None
        # True once the work has ended and only its end is left to post: the
        # one state in which an update may leave the job behind (B520).
        self.reporting = False
        self.refused = 0         # the status of the last log post not taken
        self.outputs = []        # what the job left behind, for the result
        self.pending_step = ""   # the word for the row, sent with the next log
        # The write end of this job's pty, for a job that needs one. Only a
        # conversation does: `claude auth login` prints a URL and waits for a
        # code, and a pipe would leave the prompt sitting in a buffer nobody
        # ever sees. None for every other job, and the log loop checks.
        self.tty = None

    def cancel(self):
        self.canceled = True
        p = self.proc
        if p is not None and p.poll() is None:
            # On a thread of its own: the kill now waits for the child's
            # cleanup, and a cancel arrives on the agent's main loop.
            threading.Thread(target=self._kill, args=(p,), daemon=True).start()

    def step(self, name):
        """What this job is doing now, for the row. Rides the next log post
        rather than taking a verb of its own, since the agent is already talking
        to the controller every half second while a job runs."""
        with self.lock:
            self.pending_step = str(name)[:60]

    # What a job may hold unsent while the controller is unreachable: past
    # this the oldest goes, and one line says how much (B286: a chatty build
    # grew the agent without limit).
    PENDING_CAP = 8 * 1024 * 1024

    def say(self, text):
        # One line that alone exceeds a body would be refused forever, and
        # everything behind it with it; split rather than let that happen.
        with self.lock:
            for i in range(0, len(text), 32 * 1024):
                self.seq += 1
                self.pending.append({"seq": self.seq, "chunk": text[i:i + 32 * 1024]})
            held = sum(len(c["chunk"]) for c in self.pending)
            if held > self.PENDING_CAP:
                dropped, at = 0, None
                while self.pending and held > self.PENDING_CAP // 2:
                    gone = self.pending.pop(0)
                    at = gone["seq"] if at is None else at
                    dropped += len(gone["chunk"])
                    held -= len(gone["chunk"])
                # At the seq of the first chunk that went, which the
                # controller orders by: with a new one it read as after the
                # chunks that were kept, not where the gap is.
                self.pending.insert(0, {"seq": at, "chunk": f"[{dropped} bytes of output dropped here: "
                                        "the controller was unreachable and this job kept talking]\n"})

    BATCH = 40 * 1024      # under the controller's 64KB body cap, with headroom
    # How long a job's end may be refused by a controller that is answering
    # before the job is dropped: half an hour of retries at a minute apart.
    REPORT_GIVE_UP_S = 30 * 60

    def flush(self, keepalive=False):
        """Post what is pending, in bodies the controller will accept. A job
        that ran on while the controller was down can have megabytes waiting;
        they go in order, a slice at a time, and stop at the first refusal.

        `keepalive` posts even with nothing pending: the reply to a log post
        is the one channel the controller has INTO a running job (its
        cancel, a sign-in's code), and a flow waiting silently at a prompt
        would otherwise never hear it (16 Sep)."""
        while True:
            with self.lock:
                batch, size = [], 0
                # Measured as the body will be sent, and stopped BEFORE a
                # chunk that would carry it past the batch: a post over the
                # controller's cap was refused forever (B520).
                while self.pending:
                    more = len(json.dumps(self.pending[0]["chunk"]))
                    if batch and size + more > self.BATCH:
                        break
                    batch.append(self.pending.pop(0))
                    size += more
            if not batch:
                with self.lock:
                    step, self.pending_step = self.pending_step, ""
                if step or keepalive:
                    body = {"job": self.job["id"], "chunks": []}
                    if step:
                        body["step"] = step
                    st, r = self.agent.ctl.call("log", body, timeout=20)
                    if st == 200:
                        self._answered(r)
                return True
            with self.lock:
                step, self.pending_step = self.pending_step, ""
            body = {"job": self.job["id"], "chunks": batch}
            if step:
                body["step"] = step
            st, r = self.agent.ctl.call("log", body, timeout=20)
            # Refused for good (a job the controller no longer has, or not
            # this node's): the result loop posts only after a flush that
            # worked, so keeping these retried the job in this agent's count
            # forever, and every self-update failed "busy" (B519). Dropped,
            # and the result goes on to be refused in its turn.
            if st in (400, 401, 403, 404, 413):
                with self.lock:
                    left = len(self.pending)
                    self.pending = []
                log(f"{self.job['id']}: log refused ({st}); dropping {len(batch) + left} chunk(s)")
                return True
            if st != 200:
                with self.lock:
                    self.pending = batch + self.pending
                self.refused = st
                return False
            self._answered(r)

    def _answered(self, r):
        """What the controller sent down with its acknowledgement: a cancel,
        and anything it wants typed INTO this job. The only downward channel
        a running job has is this reply, which is why `cancel` has always
        ridden it; a sign-in's code rides it the same way. One line, and only
        a job that opened a pty has anywhere to put it."""
        if r.get("cancel") and not self.canceled:
            self.cancel()
        if r.get("input") and self.tty is not None:
            with contextlib.suppress(OSError):
                os.write(self.tty, (str(r["input"]) + "\n").encode())

    def run(self):
        spec = self.job.get("spec") or {}
        error = ""
        # What this job is, before it is anything else: a job that fails
        # without having said a word leaves the row with an exit code and an
        # empty log, and there is nothing to look at but the number. Every
        # path below can now only ADD to this line.
        self.say(f"{self.job.get('type') or 'exec'}"
                 + (f": {spec['apply']}" if spec.get("apply") else "") + "\n")
        # Posted now: a job turns running at its first log post, and one
        # that works in this process (a disk measure, a cache clear) said
        # nothing more until its end, so its row read "assigned" all the
        # while it ran (B250).
        self.flush()
        try:
            if self.job.get("type") == "self-update":
                state, code = self.agent.self_update(self, spec)
            elif self.job.get("type") == "system":
                state, code = self.agent.system(self, spec)
            elif self.job.get("type") == "compose":
                state, code = self.agent.compose(self, spec)
            elif self.job.get("type") == "vm":
                state, code = self.agent.vm(self, spec)
            elif self.job.get("type") == "toolchain":
                state, code = self.agent.toolchain(self, spec)
                # A recipe landed or left: the session environment is built
                # from the store's layout at ttyd's start, so a session
                # opened after this would still not find the new tool on
                # PATH (lint-tools on bb-sandbox, measured). The loop
                # restarts the ttyds; tmux sessions survive it. A check
                # writes nothing, so nothing has moved and restarting every
                # ttyd on the node to report a version number would be rude.
                if spec.get("action") != "check":
                    self.agent.session_renew()
                    # The census before the end: the controller says which
                    # names landed from what the store holds, and read from
                    # the census of before the job, a toolchain that had
                    # just landed read as failed until the next hello (the
                    # operator, 12 Oct: Build-Tools, installed, said failed).
                    self.agent.hello()
            elif self.job.get("type") == "image":
                state, code = self.agent.image(self, spec)
            elif self.job.get("type") == "sign":
                state, code = self.agent.sign(self, spec)
            elif self.job.get("type") == "sign-key":
                state, code = self.agent.sign_key(self, spec)
            elif self.job.get("type") == "cache-clear":
                state, code = self.agent.cache_clear(self, spec)
            elif self.job.get("type") == "storage":
                state, code = self.agent.storage_measure(self, spec)
            elif self.job.get("type") == "avd-remove":
                state, code = self.agent.avd_remove(self, spec)
            elif self.job.get("type") in ("claude-login", *AGENT_LOGINS):
                # Claude's, or another coding agent's (R95 step 3): the same
                # pty and the same channel, `bb login --flow` told which.
                state, code = self.claude_login(spec, AGENT_LOGINS.get(self.job.get("type"), ""))
                # Said on the next heartbeat rather than in five minutes:
                # the row that asked is waiting to read who signed in.
                self.agent._logins_at = 0
            elif self.job.get("type") in ("claude-logout", *AGENT_LOGOUTS):
                state, code = self.claude_logout(spec, AGENT_LOGOUTS.get(self.job.get("type"), ""))
                self.agent._logins_at = 0
            elif self.job.get("type") == "claude-update":
                state, code = self.agent.claude_update(self, spec)
            elif self.job.get("type") in AGENT_INSTALLS:
                # The other coding agents' installs (R95 step 2).
                state, code = self.agent.agent_update(self, spec)
            elif self.job.get("type") == "tell":
                state, code = self.agent.tell(self, spec)
            else:
                state, code = self.exec(spec)
        except Exception as e:                       # noqa: BLE001 (reported, not raised)
            # Broad because a runner's bug is this job's failure, not the
            # agent's: the row carries the sentence, the journal the traceback.
            self.say(f"agent error: {type(e).__name__}: {e}\n")
            log(f"job {self.job.get('id')}: agent error: {type(e).__name__}: {e}\n"
                + traceback.format_exc().rstrip())
            state, code, error = "failed", 70, f"agent error: {type(e).__name__}"
        if self.canceled:
            state, error = "canceled", "stopped by the operator"
        elif state == "failed" and not error:
            # A handler that knows why says so (self_update: what held it).
            error = getattr(self, "why", "") or f"exit {code}"
        # A container came, went or moved: the session network's sets are
        # rebuilt from `docker ps` every ten seconds, and a session told by
        # its rebuild that the instance was up curled its port inside that
        # window and was refused, the pair not yet in the set (B307). Read
        # again now, before the controller hears the job is done, so what
        # it reports up is reachable by the time anybody is told.
        if self.job.get("type") == "compose" \
                or os.path.basename(str((spec.get("argv") or [""])[0] or "")) == "docker":
            self.agent.sessnet.containers_at = 0.0
        self.report(state, code, error)
        self.agent.finished(self)
        if state == "succeeded" and self.job.get("type") == "self-update" and getattr(self, "installed", False):
            self.agent.reexec_when_idle()

    def report(self, state, code, error):
        """Post the job's end: its log first, then the result."""
        # Door 5: keep trying. The controller may be gone for a while; the
        # answer waits here, with backoff, until it is taken.
        #
        # ...but not for ever while the controller is there and will not take
        # it (the operator, 6 Oct: a stuck job should time out, the more so
        # when the controller says it is complete). A log the controller
        # answers and refuses no longer holds the end back: the end is posted
        # anyway, and a controller that has the job as complete takes it as
        # already done. Past REPORT_GIVE_UP_S of answers that are refusals
        # the job is dropped with a line in the journal. A controller that
        # cannot be reached is waited for as before: that is door 5.
        self.reporting = True
        delay = 1
        refused_since = None
        while True:
            flushed = self.flush()
            st = 0
            if flushed or self.refused:
                st, _ = self.agent.ctl.call(
                    "result", {"job": self.job["id"], "state": state, "exit": code,
                               "error": error, "outputs": self.outputs},
                    timeout=20)
                if st == 200:
                    break
                if st in (400, 401, 403, 404):
                    log(f"{self.job['id']}: result refused ({st}); dropping it")
                    break
            if st or (not flushed and self.refused):
                refused_since = refused_since or time.time()
                if time.time() - refused_since > self.REPORT_GIVE_UP_S:
                    log(f"{self.job['id']}: the controller refused this job's end for "
                        f"{self.REPORT_GIVE_UP_S // 60} minutes (last {st or self.refused}); dropping it")
                    break
            else:
                refused_since = None
            self.refused = 0
            time.sleep(delay)
            delay = min(delay * 2, 60)

    def claude_login(self, spec, agent=""):
        """`claude auth login` on this machine, under a pty, as the SESSION
        account (roadmap R47).

        A job of its own and not an exec, for two reasons that both matter.
        It drops to the session account rather than the enrolled job one:
        those are different accounts on purpose, and the credential has to
        land in the home a Claude session will read it from, owned by the
        account that will read it. And it wants a PTY: the flow prints a URL
        and then a prompt with no newline after it, which down a pipe sits in
        a buffer nobody ever sees.

        The conversation is the job's own log going up and `input` on the
        reply to a log post coming down, the same channel `cancel` has used
        since the start. Nothing new is opened toward this machine.
        """
        who_name = self.agent.session_account()
        env = dict(sdk_env(self.agent.state))
        env.update({"BUILDERBOT_NODE": self.agent.state.get("node_id", ""),
                    "BUILDERBOT_JOB": self.job["id"]})
        try:
            who = self.agent.as_user(env, who_name)
        except RuntimeError as e:
            self.say(f"refused: {e}\n")
            return "failed", 78
        if not who_name:
            self.say("refused: this node reports no session account, so there is "
                     "no home for a Claude login to land in\n")
            return "failed", 78
        into = self.agent.bundle(self, who)
        if not into:
            return "failed", 69
        # The BuilderBot account, so the bundle's own user_home resolves the
        # same per-account home bb-tty gives a session here. Resolved there
        # rather than here: one implementation of "where does this account
        # live on this machine", and it is that one.
        env["BUILDER_HOME"] = env.get("HOME", "")
        env["BB_ACCOUNT_UID"] = str(spec.get("uid") or "")
        # What the flow reports with, and where: the token the controller
        # minted for this sign-in, the controller's address, and the node
        # shape bb's own checks look for.
        if spec.get("token"):
            env["BB_TOKEN"] = str(spec["token"])
        env.setdefault("BB_CONTROLLER", str(self.agent.state.get("controller") or ""))
        env.setdefault("BUILDERBOT_ROLE", "node")
        env.setdefault("BB_NODE", str(self.agent.state.get("name") or ""))
        argv = ["bash", os.path.join(into, "scripts", "bb"), "login", "--flow"] + (["--agent", agent] if agent else [])
        master, slave = pty.openpty()
        self.say(f"signing in to {agent or 'Claude'} on this machine; the URL follows\n")
        try:
            self.proc = subprocess.Popen(
                argv, stdin=slave, stdout=slave, stderr=slave,
                cwd="/tmp", env=env, start_new_session=True, close_fds=True, **who)
        except (OSError, ValueError) as e:
            os.close(master), os.close(slave)
            self.say(f"could not start the sign-in: {e}\n")
            return "failed", 70
        os.close(slave)
        self.tty = master
        deadline = time.monotonic() + int(spec.get("timeout") or 900)
        last_beat = time.time()
        try:
            while True:
                if time.monotonic() > deadline:
                    self.say("the sign-in was not finished in time\n")
                    self.cancel()
                    return "failed", 75
                try:
                    r, _, _ = select.select([master], [], [], 0.5)
                except (OSError, ValueError):
                    break
                if not r:
                    # Quiet: the flow is waiting at its prompt. A heartbeat
                    # post is how the code the person pasted gets here.
                    if time.time() - last_beat >= 1.0:
                        self.flush(keepalive=True)
                        last_beat = time.time()
                if r:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    self.say(chunk.decode("utf-8", "replace"))
                    # Posted now, not at the end: the controller reads the
                    # sign-in URL out of this log and hands the code back,
                    # and the flow does not end until it has the code. Held
                    # until the end, the card said "starting the sign-in"
                    # until the timeout, on every node (16 Sep).
                    self.flush()
                if self.proc.poll() is not None:
                    break
        finally:
            self.tty = None
            with contextlib.suppress(OSError):
                os.close(master)
        code = self.proc.wait()
        return ("succeeded" if code == 0 else "failed"), code

    def claude_logout(self, spec, agent=""):
        """`claude auth logout` on this machine for one BuilderBot account,
        as the SESSION account and in that account's home here: the other
        half of claude_login. The login is this machine's, so this machine
        is the one that lets go of it; the heartbeat that follows says so."""
        who_name = self.agent.session_account()
        env = dict(sdk_env(self.agent.state))
        try:
            who = self.agent.as_user(env, who_name)
        except RuntimeError as e:
            self.say(f"refused: {e}\n")
            return "failed", 78
        if not who_name:
            self.say("refused: this node reports no session account, so no Claude login lives here\n")
            return "failed", 78
        uid = str(spec.get("uid") or "")
        if not re.fullmatch(r"u_[0-9a-f]{8}", uid):
            self.say("refused: a sign-out names the account it is for\n")
            return "failed", 64
        into = self.agent.bundle(self, who)
        if not into:
            return "failed", 69
        # The session account's home, which is this process's own where the
        # agent is not root and as_user changed nothing.
        env.setdefault("HOME", os.path.expanduser("~"))
        env["BUILDER_HOME"] = env["HOME"]
        env["BB_ACCOUNT_UID"] = uid
        env.setdefault("BUILDERBOT_ROLE", "node")
        env.setdefault("BB_NODE", str(self.agent.state.get("name") or ""))
        self.say(f"signing out of {agent or 'Claude'} on this machine\n")
        try:
            p = subprocess.run(["bash", os.path.join(into, "scripts", "bb"), "login", "--out"] + (["--agent", agent] if agent else []),
                               env=env, cwd="/tmp", capture_output=True, text=True,
                               timeout=int(spec.get("timeout") or 120), check=False, **who)
        except (OSError, subprocess.SubprocessError) as e:
            self.say(f"the sign-out did not run: {e}\n")
            return "failed", 70
        self.say((p.stdout or "") + (p.stderr or ""))
        return ("succeeded" if p.returncode == 0 else "failed"), p.returncode

    def exec(self, spec):
        need = spec.get("requires") or []
        if isinstance(need, str):
            need = [need]
        held = set(self.agent.state.get("capabilities") or [])
        missing = [c for c in need if c not in held]
        if missing or "system" in need:
            # Door 7, in one line: the node refuses what it was not enrolled
            # to do, and says which capability was asked for. "system" is not
            # a capability an exec can ask for at all: root work is its own
            # job type, and only the configuration plane queues it.
            self.say(f"refused: this node is not enrolled for {', '.join(missing or need)}\n")
            return "failed", 77
        argv = [str(a) for a in (spec.get("argv") or [])]
        stores = self.agent.state.get("stores") or {}
        cwd = spec.get("cwd") or stores.get("data") or "/tmp"
        # The node's own toolchains, for EVERY job. A build is the case this
        # whole store exists for, and it was the one case that did not get
        # them (bug #45).
        env = dict(sdk_env(self.agent.state))
        env.update({"BUILDERBOT_NODE": self.agent.state.get("node_id", ""),
                    "BUILDERBOT_JOB": self.job["id"]})
        who = self.agent.drop_privileges(env)
        bbv = [str(a) for a in (spec.get("bb") or [])]
        if bbv:
            # A bb verb, run from the bundle this controller ships with the
            # store as its SDK (docs/nodes.md phase 9): `bb emu start` on a
            # node is this. In a directory of the project's under the data
            # store, so what the verb writes has somewhere to be collected from.
            into = self.agent.bundle(self, who)
            if not into:
                return "failed", 69
            argv = ["bash", os.path.join(into, "scripts", "bb")] + bbv
            project = re.sub(r"[^A-Za-z0-9._-]", "_", str(spec.get("project") or "project"))
            cwd = os.path.join(stores.get("data") or "/tmp", "emu", project)
            self.agent.own_dir(cwd, who)
            env["BB_PROJECT"] = str(spec.get("project") or "")
        if not argv:
            self.say("refused: empty argv\n")
            return "failed", 64
        if not os.path.isdir(cwd):
            cwd = "/tmp"
        for k, v in (spec.get("env") or {}).items():
            env[str(k)] = str(v)
        # Inputs: files from the project's dist/, fetched into the working
        # directory by name: an APK for the emulator to install.
        for f in (spec.get("files") or [])[:8]:
            name = os.path.basename(str(f))
            # Into this node's artifact store for the project, and used from
            # there: a second emulator run on the same build copies nothing,
            # and on a node across a slow link that is the difference the
            # store exists for. The size decides whether it is the same file:
            # the controller sends no digest for a dist/ path.
            keep = self.agent.artifact_dir(spec.get("project"), who)
            dest = os.path.join(keep or cwd, name)
            want = spec.get("sizes", {}).get(str(f)) if isinstance(spec.get("sizes"), dict) else None
            if keep and os.path.isfile(dest) and want and os.path.getsize(dest) == want:
                self.say(f"{f} is already on this node ({want} bytes)\n")
            else:
                st, _ = self.agent.ctl.fetch(
                    f"file?job={self.job['id']}&path={urllib.parse.quote(str(f))}", dest)
                if st != 200:
                    self.say(f"could not fetch {f} from the controller ({st})\n")
                    return "failed", 69
                if who:
                    with contextlib.suppress(OSError):
                        os.chown(dest, who["user"], who["group"])
                self.say(f"fetched {f} ({os.path.getsize(dest)} bytes)"
                         + (f" into {keep}" if keep else "") + "\n")
            if keep and os.path.dirname(dest) != cwd:
                link = os.path.join(cwd, name)
                with contextlib.suppress(OSError):
                    if os.path.lexists(link):
                        os.remove(link)
                    os.symlink(dest, link)
        # A job with a source runs in a workspace of its own (docs/nodes.md
        # §6): the snapshot, materialized under the data store, with the
        # project's persistent cache beside it in the environment.
        src = self.job.get("source") or {}
        ws = None
        if src.get("digest"):
            ws = self.agent.materialize(self, src, who)
            if ws is None:
                return "failed", 66
            cwd = ws
            env["BUILDERBOT_WORKSPACE"] = ws
            project = re.sub(r"[^A-Za-z0-9._-]", "_", str(src.get("project") or spec.get("project") or "project"))
            cache = os.path.join(stores.get("cache") or "/tmp", project)
            self.agent.own_dir(cache, who)
            # Its last use, which the room keeper's prune by age reads
            # (cache_clear's older_days): a directory's own mtime moves only
            # when an entry is added, not when a build reads what is there.
            with contextlib.suppress(OSError):
                with open(os.path.join(cache, ".used"), "a"):
                    pass
                os.utime(os.path.join(cache, ".used"))
            env["BUILDERBOT_CACHE"] = cache
            env["BUILDERBOT_PROJECT"] = project
            self.say(f"workspace {ws} ({src.get('files', '?')} files); cache {cache}\n")
        try:
            timeout = float(spec.get("timeout") or 3600)
        except (TypeError, ValueError):
            timeout = 3600
        # Below the node's other work when the controller asks (a test run:
        # the emulator, a docker build and a session's own work keep the
        # CPU when they want it, and a run that only yields under contention
        # is not slower on a quiet box; the operator, 27 Sep). The coreutils
        # nice in front of the command, not a fork hook: see preexec_fn
        # below on why this process must not run one.
        try:
            nice = int(spec.get("nice") or 0)
        except (TypeError, ValueError):
            nice = 0
        if 0 < nice <= 19 and shutil.which("nice"):
            argv = ["nice", "-n", str(nice)] + argv
        try:
            p = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, start_new_session=True,
                                 **who)
        except OSError as e:
            self.say(f"could not start {argv[0]}: {e}\n")
            return "failed", 126
        self.proc = p
        if self.canceled:                 # asked to stop while it was starting
            self._kill(p)
        # The pipe is read on its own thread, and this one posts on a clock.
        # Reading and posting on one thread meant a job that printed a line
        # and then worked in silence never posted the line (readline blocked
        # until the next one), so the row sat at "assigned" with nothing in
        # its log, and a cancel sent on the log reply could not arrive.
        reader = pump(self, p.stdout)
        deadline = time.monotonic() + timeout
        killed = False
        while reader.is_alive():
            reader.join(0.5)
            if self.pending:
                self.flush()
            if time.monotonic() > deadline and not killed:
                self.say(f"timed out after {int(timeout)}s, killing it\n")
                self._kill(p)
                killed = True
        p.wait()
        self.proc = None
        if self.canceled:
            self.say("stopped\n")
            state, code = "canceled", 130
        elif killed:
            state, code = "failed", 124
        else:
            state, code = ("succeeded" if p.returncode == 0 else "failed"), p.returncode
        if ws is not None:
            self.agent.finish_workspace(self, ws, spec, state)
        elif state == "succeeded" and spec.get("outputs"):
            # No snapshot, but outputs asked for: what a bb verb wrote in
            # its directory comes back the same way a build's do.
            self.agent.deliver(self, cwd, spec.get("outputs") or [])
        return state, code

    @staticmethod
    def _kill(p, grace=60):
        # The whole session, not just the leader: a build spawns children
        # that would otherwise keep the pipe open and the job "running".
        # TERM first, then up to `grace` seconds for it to finish what it does
        # on TERM (a toolchain install removes its partial download, which
        # for flutter over NFS took longer than the two seconds this gave:
        # killed mid-delete, half of it stayed and read as installed, the
        # operator, 12 Oct), then KILL whatever is left of the group.
        try:
            os.killpg(p.pid, 15)
        except OSError:
            return
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if p.poll() is not None:
                break
            time.sleep(0.25)
        with contextlib.suppress(OSError):
            os.killpg(p.pid, 9)
