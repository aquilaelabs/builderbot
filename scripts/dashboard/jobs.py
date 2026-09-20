"""jobs.py: the controller's own runner, and the numbers (docs/nodes.md §2,
§9; phase 4 of the nodes design).

nodes.py holds the queue: rows, placement, cancel flags. This module is the
side of it that RUNS things here. An agent takes its own work over the
channel; everything else (a compose action against some node's daemon, an
exec on a node that has no agent) is taken from the same table by a thread
in this process, through the same job_next() the agent calls, and reported
back through the same job_log() / job_result(). One queue, two runners, and
the rows cannot tell which one served them, which is what lets a node be
agent or ssh and both work.

What the executor owns:

  - the loop: every node the controller may run work for is asked for its
    next controller job, and each one found starts on a thread;
  - Run: what a runner talks back through, holding log lines (folded, so a
    docker pull is frames and not a transcript), the step it is on, the
    process to interrupt, and whether it has been asked to stop;
  - cancel: a flag on the row, read by a watcher that kills the held
    process group, the same verb an agent gets on the wire, delivered
    the local way (door 9: nothing on the wire names a signal);
  - the restart sweep: a job this process was running when it died is
    failed as lost at the next start, because it is;
  - /healthz and /metrics, made of nodes.job_counts().

Registered runners by type: "exec" is here, "compose" is devapp's, which
registers itself through configure(), so the compose code stays in the
compose module and this one knows nothing about compose files.
"""

import os
import signal
import subprocess
import sys
import threading
import time
import traceback

nodes = None
RUNNERS = {}
_runs = {}                       # job id -> Run, for the watcher and cancel
_lock = threading.Lock()
_started = [False]

# How much of a long command's output a row shows. A tail, not a transcript.
LOG_TAIL = 4000
# How often buffered lines reach the store while a command runs: the rows
# poll on a rev, so half a second is one repaint behind at worst.
FLUSH_S = 0.5
# The longest a held-back frame may wait. A pull writes a progress line
# many times a second and every one folds into the last, so the buffered
# line is always fresh and would never be written until the pull ended:
# minutes of nothing, the exact hang this streaming exists to prevent. Two
# seconds a frame is a log that moves; thirty frames a second is not a log.
HOLD_S = 2.0


def configure(*, nodes_module, runners=None):
    """Bind the queue and the runners, and start the loop once."""
    global nodes
    nodes = nodes_module
    RUNNERS["exec"] = run_exec
    RUNNERS.update(runners or {})
    if not _started[0]:
        _started[0] = True
        nodes.jobs_restart_sweep()
        threading.Thread(target=_loop, name="jobs", daemon=True).start()
        threading.Thread(target=_watch, name="jobs-cancel", daemon=True).start()


def register(job_type, fn):
    RUNNERS[job_type] = fn


# ---------------------------------------------------------------------------
# the log: frames fold, prose does not

def _progress_key(line):
    """What a compose progress line is ABOUT, or "" if it is not one.

    Compose writes progress as `<thing> <name> <state>`: an id and a verb and
    a number that moves. On a terminal it rewrites the line in place; with no
    terminal it writes a new one per tick, which is how a single layer becomes
    thirty lines of `5a96bc599c67 Extracting 2B` in the tail. The first two
    words are the thing being talked about, so two lines sharing them are two
    frames of one animation and only the last is worth keeping. Three words
    minimum, so a sentence is never treated as a progress frame.
    """
    parts = line.split()
    return " ".join(parts[:2]) if len(parts) >= 3 else ""


def fold(buf, line):
    """Append `line` to `buf`, replacing the last entry when this one
    supersedes it. Without this a pull of one image is hundreds of
    near-identical lines and whatever went wrong scrolled past long before
    anybody looked."""
    if buf:
        last = buf[-1]
        key = _progress_key(line)
        if last == line or (key and key == _progress_key(last)):
            buf[-1] = line
            return
    buf.append(line)


class Run:
    """One controller-run job's side of the conversation with the store.

    Lines are folded and buffered, and flushed on a clock rather than per
    line, except the LAST buffered line, which is held back while it is
    fresh, so a progress frame that is about to be superseded is written to
    the log once, as its final frame, and never as thirty. Held only while
    fresh: a job that prints one line and then works in silence would
    otherwise show nothing until it ended, and the watcher thread flushes a
    quiet run's last line for it.
    """

    def __init__(self, job):
        self.job = job
        self.id = job["id"]
        self.node = job["node"]
        self.canceled = False
        self.proc = None
        self._buf = []
        self._seq = 0
        self._at = time.time()          # last flush
        self._line_at = 0.0             # last line in
        self._lock = threading.Lock()

    def line(self, text):
        with self._lock:
            fold(self._buf, text)
            self._line_at = time.time()
        if time.time() - self._at > FLUSH_S:
            self.flush()

    def _held_too_long(self):
        """The held-back line is due: nothing has followed it for a while,
        or it has been superseded in place for longer than HOLD_S."""
        now = time.time()
        return now - self._line_at > FLUSH_S or now - self._at > HOLD_S

    def quiet(self):
        """Buffered output that is due, the watcher's cue to flush it."""
        return bool(self._buf) and self._held_too_long()

    def step(self, name):
        nodes.job_set(self.id, step=name)

    def hold(self, proc):
        """The process the job is inside, so cancel has something to reach."""
        self.proc = proc

    def flush(self, final=False):
        with self._lock:
            fresh = not final and not self._held_too_long()
            out = self._buf[:-1] if fresh else self._buf[:]
            # _at is when something was last WRITTEN, and stays put when
            # nothing was: it is what HOLD_S is measured from, and resetting
            # it here kept a fast-moving frame fresh forever.
            if not out:
                return
            chunks = []
            for ln in out:
                self._seq += 1
                chunks.append({"seq": self._seq, "chunk": ln})
            del self._buf[:len(out)]
            self._at = time.time()
        r = nodes.job_log(self.node, self.id, chunks)
        if r.get("cancel"):
            self.cancel()

    def cancel(self):
        """Asked to stop: the process group, not the process. A compose CLI
        waiting on a pull leaves the download running if only the CLI is
        signalled. What is already built stays; an abort is for the rest of
        the work, not for undoing what finished."""
        self.canceled = True
        p = self.proc
        if p is not None:
            kill_group(p)


def kill_group(p):
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass


def stream(argv, run, timeout, env=None, cwd=None):
    """Run argv with its output going to the run's log as it is produced,
    in its own process group, killable. {"code", "out"}: the tail of the
    output rides back for the runner's own reporting."""
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1,
                             env=env, cwd=cwd, start_new_session=True)
    except (OSError, subprocess.SubprocessError) as e:
        run.line(str(e) + "\n")
        return {"code": 1, "out": str(e)}
    run.hold(p)
    tail = []
    deadline = time.time() + timeout
    try:
        for ln in p.stdout:
            run.line(ln)
            tail.append(ln)
            del tail[:-60]
            if time.time() > deadline:
                kill_group(p)
                run.line(f"\ntimed out after {timeout}s\n")
                break
    except (OSError, ValueError):
        pass                          # the pipe went with the process
    finally:
        run.hold(None)
    try:
        code = p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        kill_group(p)
        code = 1
    return {"code": code, "out": "".join(tail)}


# ---------------------------------------------------------------------------
# the exec runner: argv on a node with no agent (local, ssh), or the
# controller's own exec on itself

def run_exec(job, run):
    spec = job.get("spec") or {}
    argv = [str(a) for a in (spec.get("argv") or [])]
    if not argv:
        return {"state": "failed", "error": "argv is empty"}
    n = nodes.node(job["node"]) or {}
    # Door 7 from this side: the node checks what it is enrolled for, and
    # here the controller IS the node's runner, so it checks for it.
    for c in spec.get("requires") or []:
        if c not in (n.get("capabilities") or []):
            run.line(f"refused: this node is not enrolled for {c}\n")
            run.flush(final=True)
            return {"state": "failed", "exit": 77,
                    "error": f"not enrolled for {c}"}
    timeout = int(spec.get("timeout") or 600)
    env = dict(os.environ)
    env["BUILDERBOT_NODE"] = job["node"]
    env["BUILDERBOT_JOB"] = job["id"]
    # Only local work reaches this runner. Everything on a node is the
    # agent's, compose included, and runner_of places it there, so a job
    # arriving here for another node is a placement fault, not something to
    # paper over by reaching for ssh. This used to run compose on the legacy
    # ssh kind over a key from this container; that kind is gone (#24).
    if not n or n.get("kind") == "local":
        cmd = argv
    else:
        return {"state": "failed",
                "error": f"{job['node']} is not this controller's to run; "
                         "its agent takes its own jobs"}
    r = stream(cmd, run, timeout, env=env)
    if run.canceled:
        return {"state": "canceled", "exit": r["code"], "error": "stopped"}
    return {"state": "succeeded" if r["code"] == 0 else "failed",
            "exit": r["code"],
            "error": "" if r["code"] == 0 else f"exit {r['code']}"}


# ---------------------------------------------------------------------------
# the loop

def _execute(job):
    run = Run(job)
    with _lock:
        _runs[job["id"]] = run
    fn = RUNNERS.get(job["type"])
    res = {"state": "failed", "error": f"no runner here for {job['type']}"}
    try:
        if fn:
            res = fn(job, run) or {"state": "succeeded"}
    except Exception as e:                       # a runner bug is a failed job, not a dead loop
        traceback.print_exc()
        res = {"state": "failed", "error": f"runner error: {e}"[:300]}
    finally:
        with _lock:
            _runs.pop(job["id"], None)
    try:
        run.flush(final=True)
    except Exception:
        traceback.print_exc()
    if run.canceled and res.get("state") != "canceled":
        res = {"state": "canceled", "exit": res.get("exit"),
               "error": res.get("error") or "stopped"}
    nodes.job_result(job["node"], job["id"], res.get("state", "failed"),
                     res.get("exit"), res.get("error", ""))


def _tick():
    """One pass: sweep what was lost, then start whatever is ours to run."""
    nodes.jobs_lost()
    for n in nodes.node_list():
        while True:
            j = nodes.job_next(n["id"], 0, runner="controller")
            if not j or "cancel" in j and "id" not in j:
                break
            threading.Thread(target=_execute, args=(j,),
                             name=f"job-{j['id']}", daemon=True).start()


def _loop():
    while True:
        try:
            _tick()
        except Exception:
            traceback.print_exc()
        with nodes._wake:
            nodes._wake.wait(5)


def _watch():
    """Cancel, delivered: the flag on the row becomes a kill of the held
    process. Woken by job_cancel through the same condition the queue
    uses, and once every few seconds regardless."""
    while True:
        with nodes._wake:
            nodes._wake.wait(3)
        try:
            with _lock:
                runs = list(_runs.values())
            for r in runs:
                if r.quiet():
                    r.flush()
                if r.canceled:
                    continue
                j = nodes.job(r.id, with_log=False)
                if j and j["cancel"]:
                    r.cancel()
        except Exception:
            traceback.print_exc()


def cancel(principal, job_id):
    """The operator's Cancel: flag the row, and if the job is ours, reach
    the process now rather than on the watcher's next look."""
    r = nodes.job_cancel(principal, job_id)
    with _lock:
        run = _runs.get(job_id)
    if run is not None:
        run.cancel()
    return r


# ---------------------------------------------------------------------------
# the numbers (docs/nodes.md §9)

def healthz():
    """Alive, and whether the store answers (no auth, no detail): what a
    monitor asks, not what an operator reads."""
    try:
        c = nodes.job_counts()
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}, 503
    return {"ok": True, "queued": c["jobs"].get("queued", 0),
            "running": c["jobs"].get("running", 0) + c["jobs"].get("assigned", 0),
            "runner": _started[0]}, 200


def metrics_text():
    """Prometheus exposition, from the same counts. Authenticated: a queue
    depth is not a secret, but a node list is a map of the operator's
    machines and this carries one name per node."""
    c = nodes.job_counts()
    out = ["# HELP builderbot_jobs Jobs by state.", "# TYPE builderbot_jobs gauge"]
    for k, v in sorted(c["jobs"].items()):
        out.append(f'builderbot_jobs{{state="{k}"}} {v}')
    out += ["# HELP builderbot_nodes Nodes by state.", "# TYPE builderbot_nodes gauge"]
    for k, v in sorted(c["nodes"].items()):
        out.append(f'builderbot_nodes{{state="{k}"}} {v}')
    out += ["# HELP builderbot_node_running Jobs running on a node.",
            "# TYPE builderbot_node_running gauge"]
    for n in nodes.node_list():
        name = n["name"].replace('"', "'")
        out.append(f'builderbot_node_running{{node="{name}",kind="{n["kind"]}"}} '
                   f'{nodes.job_running(n["id"])}')
        s = (n.get("reported") or {}).get("sample") or {}
        if "cpu_pct" in s:
            out.append(f'builderbot_node_cpu_pct{{node="{name}"}} {s["cpu_pct"]}')
        if "mem_used_mb" in s:
            out.append(f'builderbot_node_mem_used_mb{{node="{name}"}} {s["mem_used_mb"]}')
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    print("jobs.py is the dashboard's job runner; it is not a command.",
          file=sys.stderr)
    sys.exit(2)
