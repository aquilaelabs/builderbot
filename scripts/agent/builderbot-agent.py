#!/usr/bin/env python3
"""BuilderBot's node agent: one file, standard library only, dialing OUT.

A node runs this under systemd. It enrolls once with a token the operator
minted on the Nodes tab, then loops for the life of the machine: say hello,
ask for work, run what it is given, report what happened. The controller
never connects to a node — a node needs no open port, no inbound rule and no
key the controller could lose — and the credential it holds opens nothing
but its own row (docs/nodes.md §4, §8).

The protocol is six verbs over plain HTTP, and this file speaks four of them
plus the download that fetches itself:

    POST /api/v1/agent/enroll     once: the enroll token in, the node token out
    POST /api/v1/agent/hello      on connect and every ten minutes: the census,
                                  and the ids of the jobs still running here
    POST /api/v1/agent/work       the long-poll: a heartbeat sample in, a job
                                  (or 204, or {"cancel": [ids]}) out, held up
                                  to `poll` seconds
    POST /api/v1/agent/log        chunks of a running job's output, by sequence;
                                  the reply carries `cancel: true` once the
                                  operator has stopped that job
    POST /api/v1/agent/result     the terminal state (succeeded, failed,
                                  canceled), exit code and a one-line error
    GET  /api/v1/agent/download   the agent the controller ships — self-update

Three rules this file keeps that are worth knowing before changing it:

  * The agent is the DURABLE side of a job (door 5). A controller restart
    must never kill running work: log chunks that could not be posted are
    kept and re-sent by sequence number, the result is retried until it is
    acknowledged, and a job started before the controller went away finishes
    and reports late.
  * The node enforces its own capabilities (door 7). A job that requires a
    capability this node was not enrolled with is refused HERE, whatever the
    controller's row says — the row is a claim, the enrollment is the fact.
  * Jobs never run as root. The unit runs the agent as root so that phase 5's
    system jobs (mounts, network) can, but an exec job drops to the account
    the provisioner enrolled — the same `bb` that docker runs as — before it
    runs anything. A session that reaches this box through a job has the
    reach it already had over ssh, and no more.

Runs anywhere Python 3.8+ is, with nothing installed:

    builderbot-agent enroll --controller URL --token bbe_… [--user bb]
                            [--store data=/path] [--pin sha256:…]
    builderbot-agent run            # the loop; what the unit runs
    builderbot-agent status         # what this node is, and does it answer
"""
import contextlib
import hashlib
import http.client
import json
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse

AGENT_VERSION = "3"
PROTOCOL = 1
# Where the enrollment lands. Overridable for tests, which run a throwaway
# agent against a throwaway controller and must not touch /etc.
NODE_JSON = os.environ.get("BUILDERBOT_NODE_JSON", "/etc/builderbot/node.json")
DEFAULT_STORES = {"data": "/var/lib/builderbot/data",
                  "packages": "/var/lib/builderbot/packages",
                  "cache": "/var/lib/builderbot/cache"}
# Where the configuration plane's tools are (docs/nodes.md §12, phase 5).
# bb-sandbox is the one copy of the mount logic, installed by the provisioner
# — its presence is what says this node was set up as a sandbox, and a
# `system` job is refused without it. The netplan seams exist so the tests
# can stand in for both without a root shell.
SANDBOX_BIN = os.environ.get("BUILDERBOT_SANDBOX_BIN", "/usr/local/sbin/bb-sandbox")
NETPLAN_DIR = os.environ.get("BUILDERBOT_NETPLAN_DIR", "/etc/netplan")
NETPLAN_BIN = os.environ.get("BUILDERBOT_NETPLAN_BIN", "netplan")
NETPLAN_FILE = "90-builderbot.yaml"
# How long a network change has to dial back in before it is reverted.
DIAL_BACK_S = 180


def log(msg):
    # journald stamps its own time; a bare line reads best in `journalctl -u`.
    print(f"[builderbot-agent] {msg}", file=sys.stderr, flush=True)


def own_digest():
    try:
        with open(os.path.abspath(__file__), "rb") as f:
            return "sha256:" + hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# the connection

class Controller:
    """One controller, one credential, one way to talk to it.

    TLS is verified by PIN, not by CA: the controller's certificate digest is
    learned at enrollment (given with --pin, or trusted on first use and
    printed so it can be checked) and every later connection must present
    the same one. A LAN dashboard with a self-signed certificate is exactly
    the case, and a CA is a later layer (docs/nodes.md §4). Plain http is
    allowed and said plainly: the token then travels in the clear, which is
    no worse than the dashboard's own credential already does on that
    network — and no better.
    """

    def __init__(self, url, token, pin=""):
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise SystemExit(f"controller URL is not http(s)://host[:port]: {url}")
        self.url, self.token, self.pin = url.rstrip("/"), token, pin
        self.scheme, self.host = u.scheme, u.hostname
        self.port = u.port or (443 if u.scheme == "https" else 80)
        self.base = u.path.rstrip("/")

    def _conn(self, timeout):
        if self.scheme == "http":
            return http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE       # the pin below is the check
        c = http.client.HTTPSConnection(self.host, self.port, timeout=timeout,
                                        context=ctx)
        c.connect()
        seen = "sha256:" + hashlib.sha256(c.sock.getpeercert(True)).hexdigest()
        if self.pin and seen != self.pin:
            c.close()
            raise ssl.SSLError(f"controller certificate changed: pinned "
                               f"{self.pin[:19]}…, presented {seen[:19]}…")
        self.seen_pin = seen
        return c

    def call(self, verb, body=None, timeout=30, method="POST", raw=False):
        """(status, decoded body). Status 0 means no answer at all —
        the controller is down or unreachable — and is the case the loop
        backs off on rather than treating as a refusal."""
        try:
            c = self._conn(timeout)
            hdrs = {"Authorization": "Bearer " + self.token,
                    "User-Agent": f"builderbot-agent/{AGENT_VERSION}"}
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                hdrs["Content-Type"] = "application/json"
            c.request(method, f"{self.base}/api/v1/agent/{verb}", data, hdrs)
            r = c.getresponse()
            payload = r.read()
            c.close()
        except (OSError, http.client.HTTPException) as e:
            return 0, {"error": f"{type(e).__name__}: {e}"}
        if raw:
            return r.status, payload
        if r.status == 204 or not payload:
            return r.status, {}
        try:
            return r.status, json.loads(payload)
        except ValueError:
            return r.status, {"error": payload[:200].decode("utf-8", "replace")}


# ---------------------------------------------------------------------------
# the census and the sample

def _run(argv, timeout=5):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           check=False)
        return (p.stdout or p.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _mem():
    tot = avail = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    tot = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return tot, max(0, tot - avail)


def _sshd_listening():
    # Port 22 in LISTEN (state 0A) in either table — cheaper and truer than
    # asking systemd, which does not know about a dropbear.
    for tab in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(tab) as f:
                for line in f.readlines()[1:]:
                    cols = line.split()
                    if cols[1].endswith(":0016") and cols[3] == "0A":
                        return True
        except OSError:
            continue
    return False


def _stores(stores):
    out = {}
    for role, path in (stores or {}).items():
        try:
            st = os.statvfs(path)
            out[role] = {"path": path,
                         "free_mb": st.f_bavail * st.f_frsize // (1024 * 1024),
                         "total_mb": st.f_blocks * st.f_frsize // (1024 * 1024)}
        except OSError:
            # Not there is a different fact from full: reported as null so
            # the row says "missing" rather than "0MB free".
            out[role] = {"path": path, "free_mb": None, "total_mb": None}
    return out


def census(state):
    """What this machine is. Asked at hello — every ten minutes — so the
    slow questions (docker, java) are allowed here and not in the sample."""
    tot, _ = _mem()
    tc = {}
    if shutil.which("java"):
        m = re.search(r'version "([^"]+)"', _run(["java", "-version"]))
        tc["java"] = m.group(1) if m else "present"
    for name in ("flutter", "dotnet", "node"):
        if shutil.which(name):
            tc[name] = (_run([name, "--version"]).splitlines() or ["present"])[0][:40]
    gpu = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]) \
        if shutil.which("nvidia-smi") else ""
    return {
        "cpu": os.cpu_count() or 0, "mem_mb": tot,
        "os": f"{platform.system().lower()} {platform.machine()} "
              f"{_os_release()}".strip(),
        # The two the placement selector matches on, as fields of their own:
        # a selector should not have to parse the display string above.
        "system": platform.system().lower(), "arch": platform.machine(),
        "hostname": socket.gethostname(),
        "docker": _run(["docker", "version", "--format", "{{.Server.Version}}"])
        if shutil.which("docker") else "",
        "gpu": gpu.splitlines()[0][:80] if gpu else "",
        "sshd": _sshd_listening(),
        "stores": _stores(state.get("stores")),
        "toolchains": tc,
        # The configuration plane's reported half (docs/nodes.md §12): what
        # is mounted and from where, and the address this machine is on.
        # The row draws the operator's desired config against these.
        "sandbox": os.access(SANDBOX_BIN, os.X_OK),
        "mounts": mounts_now(),
        "network": network_now(),
    }


def mounts_now():
    """Every mount bb-sandbox manages, as it reads them: fstab's line and
    whether it is really mounted. Empty on a node with no bb-sandbox."""
    if not os.access(SANDBOX_BIN, os.X_OK):
        return []
    out = _run([SANDBOX_BIN, "list", "--json"])
    try:
        got = json.loads(out)
    except ValueError:
        return []
    return [m for m in got if isinstance(m, dict)] if isinstance(got, list) else []


def network_now():
    """The address the machine is on, as facts rather than as intent: the
    interface the default route leaves by, its addresses, the gateway, and
    the resolvers. From `ip -j`, which every distro this can run on has."""
    net = {"interface": "", "addresses": [], "gateway": "", "dns": []}
    try:
        routes = json.loads(_run(["ip", "-j", "route", "show", "default"]) or "[]")
        for r in routes:
            if isinstance(r, dict) and r.get("dev"):
                net["interface"] = str(r["dev"])[:32]
                net["gateway"] = str(r.get("gateway") or "")[:64]
                break
        if net["interface"]:
            addrs = json.loads(_run(["ip", "-j", "addr", "show", "dev", net["interface"]]) or "[]")
            for a in addrs:
                for i in (a.get("addr_info") or []) if isinstance(a, dict) else []:
                    if i.get("family") == "inet" and i.get("local"):
                        net["addresses"].append(f"{i['local']}/{i.get('prefixlen', 32)}")
    except (ValueError, OSError):
        pass
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"):
                    net["dns"].append(line.split()[1][:64])
    except (OSError, IndexError):
        pass
    return net


def _os_release():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


class Sampler:
    """CPU as a percentage over the interval since the last sample — which
    is the poll interval, so the number on the row is 'the last 25 seconds'
    and not an instant nobody can act on."""

    def __init__(self):
        self.last = self._stat()

    @staticmethod
    def _stat():
        try:
            with open("/proc/stat") as f:
                parts = [int(x) for x in f.readline().split()[1:]]
            return sum(parts), parts[3] + (parts[4] if len(parts) > 4 else 0)
        except (OSError, ValueError, IndexError):
            return 0, 0

    def sample(self, state, running):
        now = self._stat()
        dt, di = now[0] - self.last[0], now[1] - self.last[1]
        self.last = now
        tot, used = _mem()
        try:
            load1 = os.getloadavg()[0]
        except OSError:
            load1 = 0.0
        return {"cpu_pct": round(100.0 * (dt - di) / dt, 1) if dt > 0 else 0.0,
                "load1": round(load1, 2), "mem_mb": tot, "mem_used_mb": used,
                "stores": _stores(state.get("stores")), "running": running}


# ---------------------------------------------------------------------------
# node.json

def load_state():
    try:
        with open(NODE_JSON) as f:
            return json.load(f)
    except OSError:
        raise SystemExit(f"{NODE_JSON} is missing — enroll this node first: "
                         "builderbot-agent enroll --controller URL --token …")
    except ValueError as e:
        raise SystemExit(f"{NODE_JSON} is not JSON ({e}); enroll again")


def save_state(state):
    d = os.path.dirname(NODE_JSON)
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = NODE_JSON + ".tmp"
    with open(tmp, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        json.dump(state, f, indent=2)
    os.replace(tmp, NODE_JSON)


# ---------------------------------------------------------------------------
# jobs

class Job(threading.Thread):
    """One job, on its own thread, reporting as it goes.

    Output is posted in batches by sequence number; a batch the controller
    did not acknowledge stays in `pending` and goes with the next one, so
    nothing is lost across a controller restart and nothing is doubled (the
    controller drops a sequence it already has). The result is retried with
    backoff until acknowledged — this thread is the record of the job until
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

    def cancel(self):
        self.canceled = True
        p = self.proc
        if p is not None and p.poll() is None:
            self._kill(p)

    def say(self, text):
        # One line that alone exceeds a body would be refused forever, and
        # everything behind it with it; split rather than let that happen.
        with self.lock:
            for i in range(0, len(text), 32 * 1024):
                self.seq += 1
                self.pending.append({"seq": self.seq, "chunk": text[i:i + 32 * 1024]})

    BATCH = 40 * 1024      # under the controller's 64KB body cap, with headroom

    def flush(self):
        """Post what is pending, in bodies the controller will accept. A job
        that ran on while the controller was down can have megabytes waiting;
        they go in order, a slice at a time, and stop at the first refusal."""
        while True:
            with self.lock:
                batch, size = [], 0
                while self.pending and size < self.BATCH:
                    batch.append(self.pending.pop(0))
                    size += len(batch[-1]["chunk"])
            if not batch:
                return True
            st, r = self.agent.ctl.call("log", {"job": self.job["id"], "chunks": batch},
                                        timeout=20)
            if st != 200:
                with self.lock:
                    self.pending = batch + self.pending
                return False
            if r.get("cancel") and not self.canceled:
                self.cancel()

    def run(self):
        spec = self.job.get("spec") or {}
        error = ""
        try:
            if self.job.get("type") == "self-update":
                state, code = self.agent.self_update(self, spec)
            elif self.job.get("type") == "system":
                state, code = self.agent.system(self, spec)
            else:
                state, code = self.exec(spec)
        except Exception as e:                       # noqa: BLE001 — reported, not raised
            self.say(f"agent error: {type(e).__name__}: {e}\n")
            state, code, error = "failed", 70, f"agent error: {type(e).__name__}"
        if self.canceled:
            state, error = "canceled", "stopped by the operator"
        elif state == "failed" and not error:
            error = f"exit {code}"
        # Door 5: keep trying. The controller may be gone for a while; the
        # answer waits here, with backoff, until it is taken.
        delay = 1
        while True:
            if self.flush():
                st, _ = self.agent.ctl.call(
                    "result", {"job": self.job["id"], "state": state, "exit": code,
                               "error": error},
                    timeout=20)
                if st == 200:
                    break
                if st in (400, 401, 403, 404):
                    log(f"{self.job['id']}: result refused ({st}); dropping it")
                    break
            time.sleep(delay)
            delay = min(delay * 2, 60)
        self.agent.finished(self)
        if state == "succeeded" and self.job.get("type") == "self-update":
            self.agent.reexec()

    def exec(self, spec):
        need = spec.get("requires") or []
        if isinstance(need, str):
            need = [need]
        held = set(self.agent.state.get("capabilities") or [])
        missing = [c for c in need if c not in held]
        if missing or "system" in need:
            # Door 7, in one line: the node refuses what it was not enrolled
            # to do, and says which capability was asked for. "system" is not
            # a capability an exec can ask for at all — root work is its own
            # job type, and only the configuration plane queues it.
            self.say(f"refused: this node is not enrolled for {', '.join(missing or need)}\n")
            return "failed", 77
        argv = [str(a) for a in (spec.get("argv") or [])]
        if not argv:
            self.say("refused: empty argv\n")
            return "failed", 64
        stores = self.agent.state.get("stores") or {}
        cwd = spec.get("cwd") or stores.get("data") or "/tmp"
        if not os.path.isdir(cwd):
            cwd = "/tmp"
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
               "LANG": "C.UTF-8", "BUILDERBOT_NODE": self.agent.state.get("node_id", ""),
               "BUILDERBOT_JOB": self.job["id"]}
        for k, v in (spec.get("env") or {}).items():
            env[str(k)] = str(v)
        who = self.agent.drop_privileges(env)
        try:
            timeout = float(spec.get("timeout") or 3600)
        except (TypeError, ValueError):
            timeout = 3600
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
        # and then worked in silence never posted the line — readline blocked
        # until the next one — so the row sat at "assigned" with nothing in
        # its log, and a cancel sent on the log reply could not arrive.
        def pump():
            try:
                for line in p.stdout:
                    self.say(line.decode("utf-8", "replace"))
            except (OSError, ValueError):
                pass                      # the pipe went with the process
        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        deadline = time.time() + timeout
        killed = False
        while reader.is_alive():
            reader.join(0.5)
            if self.pending:
                self.flush()
            if time.time() > deadline and not killed:
                self.say(f"timed out after {int(timeout)}s — killing it\n")
                self._kill(p)
                killed = True
        p.wait()
        self.proc = None
        if self.canceled:
            self.say("stopped\n")
            return "canceled", 130
        if killed:
            return "failed", 124
        return ("succeeded" if p.returncode == 0 else "failed"), p.returncode

    @staticmethod
    def _kill(p):
        # The whole session, not just the leader: a build spawns children
        # that would otherwise keep the pipe open and the job "running".
        try:
            os.killpg(p.pid, 15)
            time.sleep(2)
            os.killpg(p.pid, 9)
        except OSError:
            pass


class Agent:
    def __init__(self, state):
        self.state = state
        self.ctl = Controller(state["controller"], state["token"], state.get("pin", ""))
        self.jobs = {}
        self.lock = threading.Lock()
        self.sampler = Sampler()
        self.poll = 25
        self.hello_at = 0
        self.controller_digest = ""

    # -- privilege ---------------------------------------------------------
    def drop_privileges(self, env):
        """Popen keywords that make the child the enrolled account — empty
        when there is nothing to drop (not root, or enrolled as root on
        purpose). Popen's own user/group/extra_groups rather than a
        preexec_fn: this process has job threads, and a fork hook that runs
        between fork and exec can deadlock on a lock another thread held."""
        user = self.state.get("user") or ""
        if os.geteuid() != 0 or not user or user == "root":
            return {}
        import grp
        import pwd
        try:
            pw = pwd.getpwnam(user)
        except KeyError:
            raise RuntimeError(f"enrolled account {user!r} does not exist here")
        env.update({"HOME": pw.pw_dir, "USER": user, "LOGNAME": user})
        groups = [g.gr_gid for g in grp.getgrall() if user in g.gr_mem]
        return {"user": pw.pw_uid, "group": pw.pw_gid, "extra_groups": groups}

    # -- the channel -------------------------------------------------------
    def hello(self):
        # `running` is the list of job ids this process still holds. The
        # controller reconciles against it: a job its row says is running
        # here that this agent does not know was lost with a restart, and is
        # failed there rather than left running forever (docs/nodes.md §9).
        st, r = self.ctl.call("hello", {"census": census(self.state),
                                        "version": AGENT_VERSION,
                                        "digest": own_digest(),
                                        "running": self.running_ids()}, timeout=30)
        if st == 200:
            self.hello_at = time.time()
            self.poll = int(r.get("poll") or 25)
            self.controller_digest = (r.get("agent") or {}).get("digest") or ""
            n = r.get("node") or {}
            # The row's capabilities are the controller's claim; the ones
            # this node ENFORCES are the ones it enrolled with, kept in
            # node.json. Logged when they differ so the disagreement is
            # visible on the box, and never silently adopted.
            claimed = set(n.get("capabilities") or [])
            held = set(self.state.get("capabilities") or [])
            if claimed - held:
                log(f"controller lists {', '.join(sorted(claimed - held))} "
                    "for this node; not enrolled for it here, and jobs "
                    "needing it will be refused")
            log(f"hello: node {n.get('id')} ({n.get('name')}), state "
                f"{n.get('state')}, poll {self.poll}s")
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
        while True:
            if time.time() - self.hello_at > 600:
                st, r = self.hello()
                if st == 401:
                    log(f"refused: {r.get('error')} — this node's credential "
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
            n = self.running()
            # The controller counts what is running here from its own rows
            # and wakes a held poll when a job ends, so the poll is held at
            # full length whether or not anything is running. The count in
            # the sample is for the row's numbers, not for placement.
            wait = self.poll
            st, r = self.ctl.call("work", {"sample": self.sampler.sample(self.state, n),
                                           "running": n, "wait": wait},
                                  timeout=wait + 15)
            if st == 204:
                continue
            if st == 200 and r.get("cancel"):
                # Not a job: the ids of jobs here the operator has stopped.
                self.cancel([str(i) for i in r["cancel"]])
                continue
            if st == 200 and r.get("id"):
                self.take(r)
                continue
            if st == 401:
                log(f"refused: {r.get('error')} — re-enroll with a new token")
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
        if self.running() > 1:
            job.say("busy: other jobs are running; try again when they finish\n")
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
        me = os.path.abspath(__file__)
        tmp = me + ".new"
        with open(tmp, "wb") as f:
            f.write(body)
        os.chmod(tmp, 0o755)
        os.replace(tmp, me)
        job.say(f"installed {got[:19]}…; restarting\n")
        return "succeeded", 0

    # -- the configuration plane (docs/nodes.md §12, phase 5) -----------------
    def system(self, job, spec):
        """Apply the desired storage or network config the controller holds
        for this node — the one root-privileged thing the agent does. Not
        dropped to the enrolled account, because mounts and addresses are
        root's; offered by the controller only to nodes that enrolled as a
        sandbox, and refused here without bb-sandbox, which is the stamp."""
        if not os.access(SANDBOX_BIN, os.X_OK):
            job.say("refused: this node was not provisioned as a BuilderBot sandbox "
                    f"({SANDBOX_BIN} is not here), so it takes no system jobs\n")
            return "failed", 77
        what = spec.get("apply")
        cfg = spec.get("config") if isinstance(spec.get("config"), dict) else {}
        if what == "storage":
            return self._apply_storage(job, cfg)
        if what == "network":
            return self._apply_network(job, cfg)
        job.say(f"refused: unknown system job {what!r}\n")
        return "failed", 64

    def _sh(self, job, argv):
        """One command, its output into the job's log, its exit code back."""
        job.say("$ " + " ".join(argv) + "\n")
        try:
            p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=300, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            job.say(f"{argv[0]}: {e}\n")
            return 1
        for line in p.stdout.decode("utf-8", "replace").splitlines():
            if line.strip():
                job.say(line + "\n")
        return p.returncode

    def _apply_storage(self, job, cfg):
        """Mounts as a diff against what bb-sandbox has — remove what is no
        longer wanted, add or rewrite what is (add-nfs/add-share rewrite an
        existing fstab line, so this is idempotent) — then the stores, which
        are this agent's own file. Ends with a hello, so the row shows the
        applied state now rather than at the next census."""
        want = [m for m in (cfg.get("mounts") or []) if isinstance(m, dict)]
        have = {m.get("path"): m for m in mounts_now()}
        bad = 0
        for path, m in have.items():
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
            verb = "add-share" if kind == "virtiofs" else "add-nfs"
            if self._sh(job, [SANDBOX_BIN, verb, f"{src}:{path}" + (":ro" if ro else "")]) != 0:
                bad += 1
        stores = cfg.get("stores") if isinstance(cfg.get("stores"), dict) else {}
        if stores:
            mine = dict(self.state.get("stores") or {})
            for role, path in stores.items():
                if role not in DEFAULT_STORES or not str(path).startswith("/"):
                    continue
                try:
                    os.makedirs(path, exist_ok=True)
                    mine[role] = str(path)
                    job.say(f"{role} store: {path}\n")
                except OSError as e:
                    job.say(f"{role} store {path} could not be made: {e.strerror}\n")
                    bad += 1
            self.state["stores"] = mine
            save_state(self.state)
        self.hello()
        if bad:
            job.say(f"{bad} of the changes did not apply — the rest did\n")
            return "failed", 1
        job.say("storage applied\n")
        return "succeeded", 0

    def _apply_network(self, job, cfg):
        """Commit/confirm, because this is the one change that can cut the
        cord it arrives on (docs/nodes.md §12): write the netplan file,
        apply it, then dial the controller from wherever the machine landed.
        No answer within DIAL_BACK_S and the previous file is put back and
        applied again, and the failure is reported on reconnect."""
        if not shutil.which(NETPLAN_BIN) and not os.access(NETPLAN_BIN, os.X_OK):
            job.say("refused: network changes need netplan on this node, and it "
                    "has none — set the address by hand, or on a node that has it\n")
            return "failed", 77
        net = cfg.get("network") if isinstance(cfg.get("network"), dict) else cfg
        iface = str(net.get("interface") or network_now().get("interface") or "")
        if not iface:
            job.say("refused: no interface named and no default route to read one from\n")
            return "failed", 65
        mode = "static" if net.get("mode") == "static" else "dhcp"
        lines = ["network:", "  version: 2", "  ethernets:", f"    {iface}:"]
        if mode == "dhcp":
            lines.append("      dhcp4: true")
        else:
            addr, gw = str(net.get("address") or ""), str(net.get("gateway") or "")
            if not addr:
                job.say("refused: a static address needs an address\n")
                return "failed", 65
            lines += ["      dhcp4: false", f"      addresses: [{addr}]"]
            if gw:
                lines += ["      routes:", f"        - to: default", f"          via: {gw}"]
            dns = [str(d) for d in (net.get("dns") or []) if str(d)]
            if dns:
                lines += ["      nameservers:", f"        addresses: [{', '.join(dns)}]"]
        text = "\n".join(lines) + "\n"
        path = os.path.join(NETPLAN_DIR, NETPLAN_FILE)
        before = None
        try:
            with open(path) as f:
                before = f.read()
        except OSError:
            pass
        if before == text:
            job.say("already applied — the netplan file has not changed\n")
            return "succeeded", 0
        os.makedirs(NETPLAN_DIR, exist_ok=True)
        with open(path, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(text)
        job.say(f"wrote {path}:\n{text}")
        job.flush()                      # the last words before the cord is cut
        if self._sh(job, [NETPLAN_BIN, "apply"]) != 0:
            self._restore_netplan(job, path, before)
            return "failed", 1
        job.say(f"applied; dialing the controller back from the new address "
                f"(up to {DIAL_BACK_S}s)\n")
        deadline = time.time() + DIAL_BACK_S
        while time.time() < deadline:
            st, _ = self.hello()
            if st == 200:
                job.say(f"dialed back in from {network_now().get('addresses') or ['?']}\n")
                return "succeeded", 0
            time.sleep(5)
        job.say(f"could not reach the controller within {DIAL_BACK_S}s — reverting\n")
        self._restore_netplan(job, path, before)
        deadline = time.time() + DIAL_BACK_S
        while time.time() < deadline:
            if self.hello()[0] == 200:
                break
            time.sleep(5)
        job.say("reverted to the previous network config\n")
        return "failed", 68

    def _restore_netplan(self, job, path, before):
        if before is None:
            with contextlib.suppress(OSError):
                os.remove(path)
        else:
            with open(path, "w") as f:
                os.fchmod(f.fileno(), 0o600)
                f.write(before)
        self._sh(job, [NETPLAN_BIN, "apply"])

    def reexec(self):
        log("re-executing the new agent")
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), "run"])


# ---------------------------------------------------------------------------
# commands

def cmd_enroll(args):
    opts = {"--controller": "", "--token": "", "--user": "bb", "--pin": ""}
    stores = dict(DEFAULT_STORES)
    it = iter(args)
    for a in it:
        if a == "--store":
            role, _, path = next(it, "").partition("=")
            if role not in DEFAULT_STORES or not path.startswith("/"):
                raise SystemExit("--store takes data=/path, packages=/path or cache=/path")
            stores[role] = path
        elif a in opts:
            opts[a] = next(it, "")
        else:
            raise SystemExit(f"unknown option {a}")
    if not opts["--controller"] or not opts["--token"]:
        raise SystemExit("enroll needs --controller URL and --token bbe_…")
    if not opts["--token"].startswith("bbe_"):
        raise SystemExit("that is not an enrollment token (they start bbe_); "
                         "mint one on the controller's Nodes tab")
    for role, path in stores.items():
        # A store that cannot be made is reported, not fatal: its free space
        # reads as zero on the row, which is the true answer.
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            print(f"note: {role} store {path} could not be created ({e.strerror}); "
                  "it will report no space until it exists")
    ctl = Controller(opts["--controller"], opts["--token"], opts["--pin"])
    state = {"controller": ctl.url, "user": opts["--user"], "stores": stores}
    st, r = ctl.call("enroll", {"census": census(state), "version": AGENT_VERSION,
                                "digest": own_digest(), "user": opts["--user"]},
                     timeout=30)
    if st != 200:
        raise SystemExit(f"enrollment refused ({st}): {r.get('error', 'no answer')}")
    if ctl.scheme == "https":
        pin = opts["--pin"] or getattr(ctl, "seen_pin", "")
        state["pin"] = pin
        if not opts["--pin"]:
            print(f"pinned the controller's certificate on first use: {pin}\n"
                  f"  check it against the controller; a different one next "
                  f"time is refused")
    else:
        print("note: plain http — the node token travels unencrypted on this "
              "network, as the dashboard's own credential does. Put TLS in "
              "front of the controller and re-enroll to pin it.")
    state.update({"node_id": r["node_id"], "token": r["token"],
                  "name": r.get("name", ""), "capabilities": r.get("capabilities", []),
                  "enrolled": int(time.time()), "scheme": ctl.scheme})
    save_state(state)
    print(f"enrolled as node {r['node_id']} ({r.get('name')}) — "
          f"capabilities: {', '.join(r.get('capabilities') or []) or 'none'}")
    print(f"  credential in {NODE_JSON} (0600); jobs run as {opts['--user']}")


def cmd_run():
    state = load_state()
    log(f"node {state.get('node_id')} → {state.get('controller')}, agent "
        f"{AGENT_VERSION} {own_digest()[:19]}…")
    Agent(state).loop()


def cmd_status():
    state = load_state()
    shown = {k: v for k, v in state.items() if k != "token"}
    print(json.dumps(shown, indent=2))
    ctl = Controller(state["controller"], state["token"], state.get("pin", ""))
    st, r = ctl.call("hello", {"census": census(state), "version": AGENT_VERSION,
                               "digest": own_digest()}, timeout=20)
    if st == 200:
        n = r.get("node") or {}
        cur = (r.get("agent") or {}).get("digest") == own_digest()
        print(f"controller answers: this is node {n.get('id')} ({n.get('name')}), "
              f"state {n.get('state')}; agent {'current' if cur else 'differs from the controller’s'}")
    else:
        print(f"controller: {st} {r.get('error', 'no answer')}")
        sys.exit(1)


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "enroll":
        cmd_enroll(argv[1:])
    elif cmd == "run":
        cmd_run()
    elif cmd == "status":
        cmd_status()
    elif cmd == "sample":
        print(json.dumps(Sampler().sample(load_state(), 0), indent=2))
    else:
        print(__doc__.split("Runs anywhere")[-1].strip() if cmd in ("", "-h", "--help")
              else f"unknown command {cmd}", file=sys.stderr)
        sys.exit(0 if cmd in ("", "-h", "--help") else 64)


if __name__ == "__main__":
    main(sys.argv[1:])
