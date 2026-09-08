#!/usr/bin/env python3
"""A node, stood in for — the suite's docker host, on the agent channel.

The harness needs ONE node whose docker the controller can address, and it
used to get one from DOCKER_HOST: the server mirrored the variable into an
`ssh`-kind row at boot, and compose for that kind ran on the controller. Both
went with roadmap #24, so the node is enrolled with a token like any other and
its compose is the agent's — which means something has to be there to take it.

Two things this container cannot do are why the REAL agent is not run here:

  * it reports no sshd, because there is none and port 22 cannot be bound
    without privileges — and nodes._addr hands out an ssh address only for a
    node that reports one, which devapp.available() requires before the whole
    dev-instance manager will turn on;
  * it would report 127.0.0.1 as its address, which is where every other node
    a test enrolls dials in from, so the stub daemon could not tell them
    apart.

So run.sh enrolls the row with a written census and this takes its jobs. The
real agent is exercised end to end by agent.mjs, against a node of its own,
which is where that belongs — this is a stand-in for a machine, in the same
spirit as the stub docker it ends up calling.

It runs the plan the CONTROLLER sent and nothing of its own: same argvs, same
order, same {cdir} substitution, same outputs. That is what keeps it honest —
if it had opinions about compose it could pass while the product failed.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

URL = os.environ["STUB_AGENT_URL"].rstrip("/")
TOKEN = os.environ["STUB_AGENT_TOKEN"]
CDIR_ROOT = os.environ["STUB_AGENT_DIR"]
# What the row reports. sshd is the load-bearing one (see the module docstring);
# the rest is a plausible small VM so the meters have something to draw.
CENSUS = {"cpu": 4, "mem_mb": 8192, "arch": "x86_64", "system": "linux",
          "sshd": True, "docker": True,
          # adb, so the Phone tab lists this node: its adb is the harness's
          # stub on PATH, which answers as a phone that is always there.
          "toolchains": {"adb": "present", "web-ext": "present"},
          "stores": {"data": {"path": CDIR_ROOT, "free_mb": 50000,
                              "total_mb": 100000}},
          # A session half that is up but on a read-only projects share —
          # the arrangement a Docker-only sandbox was told to have, and the
          # one that stranded the first real session (nothing could be
          # saved). What the proxy refuses on, and the row says.
          "session": {"up": True, "port": 7681, "ro_port": 7682, "user": "bb",
                      "workspace": True, "writable": False, "boot": "1.1"}}


def call(verb, body, timeout=60):
    req = urllib.request.Request(
        f"{URL}/api/v1/agent/{verb}", method="POST",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": "application/json",
                 # Every call, not just the enrollment: the controller
                 # refreshes the address from the request on hello AND on
                 # every heartbeat, so a stub that only claimed to be `stub`
                 # once was 127.0.0.1 again within a poll.
                 "X-Forwarded-For": "stub"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status == 204:
                return None
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"error": f"{e.code} {e.read()[:200]!r}"}
    except (urllib.error.URLError, OSError, ValueError):
        return {"error": "unreachable"}


def stream(job, seq, argv, cwd, env, timeout=300):
    """Run one command, posting its output WHILE it runs and stopping when
    the controller says to.

    Both halves are load-bearing rather than polish: the suite asserts that a
    long build's output appears in the row before the command returns, and
    that Abort ends one — and a stub that buffered until exit, or ignored the
    cancel flag the log reply carries, would fail neither test honestly. This
    is what the shipped agent does; the difference is only that it has more
    to say about it.

    `seq` is the JOB's counter, not this command's. Every chunk of one job
    shares one sequence — the controller drops a seq it has already stored,
    which is what makes an agent's retry safe — so a second counter starting
    at 1 had its output silently swallowed. The log then held the command
    and nothing it said, which is a failed build with no account of why.
    """
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1)
    buf, last, deadline = [], time.time(), time.time() + timeout
    canceled = [False]

    def post():
        if not buf:
            return
        seq[0] += 1
        r = call("log", {"job": job["id"],
                         "chunks": [{"seq": seq[0], "chunk": "".join(buf)}]})
        buf.clear()
        if isinstance(r, dict) and r.get("cancel"):
            canceled[0] = True

    # Read with a timeout rather than line by line: a command that prints
    # three lines and then sits there (web-ext, once the add-on is on the
    # phone) must still have those lines posted, and must still hear a
    # cancel — both ride the half-second post, which a blocked readline
    # never reached.
    import select
    while True:
        ready, _, _ = select.select([p.stdout], [], [], 0.5)
        if ready:
            line = p.stdout.readline()
            if not line:
                break
            buf.append(line)
        if time.time() - last > 0.5:
            if buf:
                post()
            else:
                r = call("log", {"job": job["id"], "chunks": []})
                if isinstance(r, dict) and r.get("cancel"):
                    canceled[0] = True
            last = time.time()
        if canceled[0] or time.time() > deadline:
            p.kill()
            break
    p.stdout.close()
    code = p.wait()
    post()
    return ("canceled" if canceled[0] else
            "succeeded" if code == 0 else "failed"), code


def compose(job):
    """One dev-instance action, the way builderbot-agent.compose does it:
    the files beside the plan, the plan in order, {cdir} resolved to a
    directory of this node's own."""
    spec = job.get("spec") or {}
    name = "".join(c if c.isalnum() or c in "._-" else "_"
                   for c in str(spec.get("name") or "compose"))
    cdir = os.path.join(CDIR_ROOT, "compose", name)
    os.makedirs(cdir, exist_ok=True)
    seq, out = [0], []

    def say(text):
        seq[0] += 1
        call("log", {"job": job["id"], "chunks": [{"seq": seq[0], "chunk": text}]})

    for fname, boddy in (spec.get("files") or {}).items():
        with open(os.path.join(cdir, os.path.basename(str(fname))), "w") as f:
            f.write(str(boddy))
        say(f"wrote {os.path.basename(str(fname))}\n")
    for d in (spec.get("dirs") or [])[:32]:
        if str(d).startswith("/"):
            try:
                os.makedirs(str(d), exist_ok=True)
            except OSError:
                pass
    done = 0
    for stp in (spec.get("plan") or [])[:8]:
        argv = [str(a).replace("{cdir}", cdir) for a in (stp.get("argv") or [])]
        if not argv:
            continue
        call("log", {"job": job["id"], "chunks": [], "step": stp.get("name")})
        say("$ " + " ".join(argv) + "\n")
        env = dict(os.environ)
        env.update({k: str(v).replace("{cdir}", cdir)
                    for k, v in (stp.get("env") or {}).items()})
        state, code = stream(job, seq, argv, cdir, env)
        if state != "succeeded":
            out.append({"kind": "compose", "steps_done": done,
                        "failed_at": stp.get("name")})
            return state, code, out
        done += 1
    out.append({"kind": "compose", "steps_done": done})
    return "succeeded", 0, out


def run_exec(job):
    spec = job.get("spec") or {}
    argv = [str(a) for a in (spec.get("argv") or [])]
    if not argv:
        return "failed", 1, []
    # The data store exists once something has been written under it; an
    # exec job (the phone's adb) can be the first thing here.
    os.makedirs(CDIR_ROOT, exist_ok=True)
    env = dict(os.environ)
    env.update({str(k): str(v) for k, v in (spec.get("env") or {}).items()})
    state, code = stream(job, [0], argv, CDIR_ROOT, env, timeout=120)
    return state, code, []


def main():
    call("hello", {"census": CENSUS, "version": "harness", "running": []})
    last_hello = time.time()
    while True:
        # Long-polled, so a queued job is picked up at once and an idle loop
        # costs one held request rather than a spin.
        j = call("work", {"sample": {"cpu_pct": 1, "mem_mb": 8192,
                                     "mem_used_mb": 2048}, "running": [],
                          "wait": 5}, timeout=30)
        if isinstance(j, dict) and j.get("id"):
            try:
                if j.get("type") == "compose":
                    state, code, outputs = compose(j)
                elif j.get("type") == "exec":
                    state, code, outputs = run_exec(j)
                else:
                    state, code, outputs = "failed", 1, []
            except Exception as e:                       # a stub bug is a failed job
                state, code, outputs = "failed", 1, []
                call("log", {"job": j["id"],
                             "chunks": [{"seq": 99, "chunk": f"stub agent: {e}\n"}]})
            call("result", {"job": j["id"], "state": state, "exit": code,
                            "outputs": outputs,
                            "error": "" if state == "succeeded"
                            else "stopped" if state == "canceled"
                            else f"exit {code}"})
        # The census only rides hello, and the row goes stale without it.
        if time.time() - last_hello > 120:
            call("hello", {"census": CENSUS, "version": "harness", "running": []})
            last_hello = time.time()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
