#!/usr/bin/env python3
"""A project's dev instance: built here, run here, controlled from Artifacts.

The question this answers used to be a GitHub Actions bill: a private
project's image was built on hosted minutes and pulled back to the same box
that could have built it. Now the box builds it — `docker compose build`
against the project's own compose file — and the Artifacts tab carries the
controls, in the same row language as the APK it lists: Up, Down, Env,
Rebuild.

**Where docker actually is.** Not in this container. The daemon is the
host's, reached through a socket PROXY (tecnativa/docker-socket-proxy) whose
address arrives as DOCKER_HOST — the docker CLI honors that on its own. The
proxy's allowlist is the boundary: build, images, containers, networks and
volumes pass; exec and the swarm surface do not. Worth stating the honest
half too, the way the sibling-project rule does: build+run+bind-mounts is
root-shaped power over the host however it is filtered, and the reason this
is acceptable is that this is a sole-operator box and the controls below are
table-lookup compose commands, never freeform. Sessions are told the proxy
is not theirs; that is a guardrail, not a sandbox.

**And the proxy cannot scope to our containers**, which is worth being exact
about because it looks as if it should: its flags are per ENDPOINT, so
CONTAINERS=1 is the whole /containers API for every container on the host.
Two things here bound the reach instead, and they answer different halves.
_guard() makes the bbdev- namespace an invariant rather than a habit — every
docker call passes through _run(), and one that is not a namespaced compose
call does not run. risks() answers the half no namespace can: a compose file
saying `privileged: true` and mounting / produces a bbdev- container like
any other, so the file is read and what it reaches for is named on the row
and confirmed once per set before anything starts.

**What "rebuild needs the env filled in" means.** The one detectable signal:
the repo's .env.example gained keys the dev env file does not have. A rebuild
that hits that stops after `down`, rewrites the env file as the new example
with the old values preserved in comments, and leaves Up for the operator —
starting a service against an env it is known to be missing would just be a
crash with extra steps.

**BuilderBot itself is NOT excluded**, and the reason is worth a line: the
dev instance is `bbdev-builderbot`, a second container from the same compose
file — building or bouncing it never touches the container this dashboard is
running in, whose lifecycle belongs to Unraid. The first cut excluded it on a
stale argument (replacing the running container kills the builder mid-flight
— true, and not what this does). Expect `up` to refuse while the real
instance holds the same host ports; that refusal is compose saying so, and
the env file is where a second instance gets different ones. A dev build
shows `unstamped` for its version, which is honest: it is one.

State: /config/devapps.json ({project: built_rev/built_at}), the env files in
/config/devenv/, one build job at a time in memory.
"""
import hashlib
import contextlib
import json
import os
import posixpath
import signal
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

WORKSPACE = None
STATE = None
FILE = None
ENVDIR = None
write_json = None

DOCKER = os.environ.get("BB_DOCKER_BIN", "docker")

# The instance a project has always had, before instances were a thing. Every
# call that does not name one means this, which is what keeps the migration
# from being visible anywhere but here.
MAIN = "main"


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")

DEVDATA = os.environ.get("BB_DEV_DATA_DIR", "/devdata")

# DOCKER_HOST=auto means "find the socket proxy yourself". The address is a
# bridge-assigned container IP unless the operator published the port, and
# bridge IPs move when containers restart in a different order — so this
# resolves lazily and re-scans when the cached answer stops answering, rather
# than being read once at boot and going quietly stale.
_found = {"addr": "", "at": 0.0}
FOUND_TTL = 300.0
# The port a docker-socket-proxy listens on, and the raw daemon's two.
SCAN_PORTS = (2375, 2376)
SCAN_TIMEOUT = 0.4


def _answers(addr):
    """Whether a docker API is really there — the version endpoint is the one
    a proxy leaves open at its most locked-down defaults."""
    import urllib.error
    import urllib.request
    host = addr.split("://", 1)[-1]
    try:
        with urllib.request.urlopen(f"http://{host}/version",
                                    timeout=SCAN_TIMEOUT) as r:
            return b"ApiVersion" in r.read(4096)
    except (OSError, urllib.error.URLError, ValueError):
        # Every way a probe can miss: refused, timed out, not HTTP, or an
        # address the operator typed that urllib will not parse.
        return False


def _scan():
    """Look for the proxy: the gateway first (a published port), then the
    bridge this container is on. Threaded, because thirty sequential timeouts
    is half a minute of a dashboard poll."""
    cands = []
    # The default route is the host as this container sees it — where a
    # published port lands, and the stable answer when one exists.
    try:
        import subprocess as sp
        r = sp.run(["ip", "route"], capture_output=True, text=True,
                   timeout=5, check=False)
        gw = ""
        mine = ""
        for line in r.stdout.splitlines():
            if line.startswith("default via "):
                gw = line.split()[2]
            if " src " in line:
                mine = line.split(" src ")[1].split()[0]
    except (OSError, sp.SubprocessError):
        gw = mine = ""
    for port in SCAN_PORTS:
        if gw:
            cands.append(f"{gw}:{port}")
    # Then the bridge itself: a proxy with no published port is only
    # reachable at its own container address.
    if mine and mine.count(".") == 3:
        base = mine.rsplit(".", 1)[0]
        for i in range(2, 40):
            ip = f"{base}.{i}"
            if ip == mine:
                continue
            cands.append(f"{ip}:2375")
    hits = []
    lock = threading.Lock()

    def check(addr):
        if _answers(addr):
            with lock:
                hits.append(addr)

    threads = [threading.Thread(target=check, args=(c,), daemon=True)
               for c in cands]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=SCAN_TIMEOUT + 0.6)
    # Candidate order is the preference order: the gateway beats a bridge IP,
    # because a published port survives a restart and a bridge address does
    # not.
    for c in cands:
        if c in hits:
            return "tcp://" + c
    return ""


def docker_host():
    """The address to talk to, resolving `auto` and caching what it found.

    Anything other than `auto` is passed through untouched — an operator who
    typed an address means it, and a scan that second-guessed them would be
    the kind of help nobody asked for.
    """
    want = (os.environ.get("DOCKER_HOST") or "").strip()
    if want.lower() != "auto":
        return want
    now = time.time()
    if _found["addr"] and now - _found["at"] < FOUND_TTL:
        return _found["addr"]
    # Re-verify the cached answer before spending a scan on it.
    if _found["addr"] and _answers(_found["addr"]):
        _found["at"] = now
        return _found["addr"]
    _found.update(addr=_scan(), at=now)
    return _found["addr"]


def daemon_id():
    """A stable name for the daemon a build landed on.

    The CONFIGURED address, not the resolved one. Under `auto` the proxy's
    bridge IP moves whenever containers restart in a different order — that
    is the whole reason docker_host() re-scans — and a build is not
    invalidated by its address changing underneath it. What does invalidate
    one is the operator repointing the setting.
    """
    return (os.environ.get("DOCKER_HOST") or "").strip().lower() or "socket"


COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml",
                 "compose.yml", "compose.yaml")

_lock = threading.Lock()

# One job at a time, like the package installer: two parallel builds on one
# daemon help nobody, and a queue would hide which click did what.
# One job at a time across the whole dashboard, and it now names the instance
# as well as the project: two instances of one project are two builds, and a
# row watching "is my build running" must not light up for its neighbour's.
_job = {"running": False, "project": "", "instance": "", "step": "", "log": "",
        "error": "", "await_env": False, "aborting": False}
_rev = 0

# The process the job is inside right now, so Abort has something to interrupt.
# A list rather than a value because the worker thread writes it and a request
# thread reads it — the same shape, and the same reason, as the installer's.
_child = [None]

# How much of a long command's output the job carries. A pull writes a line per
# layer per progress tick, so this is a tail and not a transcript: enough to
# see what it is doing and where it stopped, not a log file kept in memory and
# posted to every poller.
LOG_TAIL = 4000


def _hold_child(proc):
    with _lock:
        _child[0] = proc


def _log_line(line):
    """One line from a running command, appended and trimmed.

    Written without the lock: this runs per line of a docker pull, the readers
    are a poll loop copying a string, and python's own assignment is atomic
    enough for a display. Correctness here is "the tail is recent", not "the
    tail is a consistent snapshot".
    """
    _job["log"] = (_job["log"] + line)[-LOG_TAIL:]


def abort_job():
    """Stop the job that is running, if any.

    Asks the process group rather than the process: a compose CLI waiting on a
    pull leaves the download running if only the CLI is signalled. What is
    already built stays — an abort is for the rest of the work, not for undoing
    what finished, which is the same bargain the package installer's makes.
    """
    with _lock:
        if not _job["running"]:
            return False
        _job["aborting"] = True
        proc = _child[0]
    if proc is not None:
        _kill_group(proc)
    _bump()
    return True


def configure(*, workspace, state, write_json):
    globals().update(WORKSPACE=Path(workspace), STATE=Path(state),
                     write_json=write_json)
    globals()["FILE"] = Path(state) / "devapps.json"
    globals()["ENVDIR"] = Path(state) / "devenv"
    _migrate_paths()


def _migrate_paths():
    """Move what the old one-instance-per-project layout named after a project.

    _load() migrates the JSON on read, which costs nothing and needs no write.
    These two cannot be done that way — they are a file and a directory whose
    NAMES were the project's, and the code that reads them now asks for the
    instance's name instead. Left alone, a dev instance would come up with an
    empty env and an empty data directory and look like a fresh one: the
    silent-empty-directory failure this module already warns about twice.

    Idempotent, and quiet when there is nothing to move — which is every run
    after the first, and every install that never had a dev instance.
    """
    try:
        for f in sorted(ENVDIR.glob("*.env")):
            if f.stem.startswith("bbdev-"):
                continue                       # already an instance's
            dst = env_path(f.stem, MAIN)
            if not dst.exists():
                f.rename(dst)
                print(f"[devapp] moved {f.name} to {dst.name} for the "
                      f"{MAIN} instance", flush=True)
    except OSError:
        pass
    try:
        root = Path(DEVDATA)
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            # bbdev-<project> with no instance suffix cannot be told from
            # bbdev-<project>-<instance> by shape, so this asks the store:
            # a directory whose name is exactly a known project's old pname
            # is the one to move.
            if not d.is_dir():
                continue
            for proj in _load():
                if d.name == f"bbdev-{_slug(proj)}":
                    dst = root / _pname(proj, MAIN)
                    if not dst.exists():
                        d.rename(dst)
                        print(f"[devapp] moved {d.name} to {dst.name}",
                              flush=True)
                    break
    except OSError:
        pass


def job_rev():
    """The poll's cheap tell that something here moved."""
    return f"{_rev}:{_mtime(FILE)}"


def _mtime(p):
    try:
        return int(Path(p).stat().st_mtime_ns)
    except OSError:
        return 0


def _bump():
    global _rev
    _rev += 1


def source():
    """Which daemon is actually being talked to, and whether two were named.

    Nothing stops an operator filling in both the socket mount and DOCKER_HOST
    — they are two settings on two screens, and a template cannot make one
    grey out the other. So the rule is precedence rather than refusal, and the
    point of this function is that the rule is stated in one place and shown
    where somebody looks, instead of being inferred differently by each reader:

      an address in DOCKER_HOST wins, always. `auto` prefers a proxy it can
      find and falls back to the socket. With neither, the feature is off.

    `shadowed` is the case worth naming: both are configured, the address won,
    and the mount is doing nothing. That is not an error — a socket left
    mounted while you try a sandbox VM is a reasonable thing to be in the
    middle of — but being told beats wondering, and it is the difference
    between "I have two settings" and "I know which one is live".

    Derived here rather than in each caller because both readers had their own
    copy and one of them was wrong: with `auto` set, a mounted socket and no
    proxy answering, `bb doctor` reported "a socket proxy at
    /var/run/docker.sock" — the kind from the setting, the address from the
    fallback, and a sentence contradicting itself.
    """
    sock = Path("/var/run/docker.sock").exists()
    addr = docker_host()
    # Mapped paths this container does not have. Said here because this is
    # where the relationship with the daemon is described, and that is what a
    # line of DOCKER_HOST_PATHS naming a path only the daemon has IS — a
    # statement about the other machine that nothing on this one will ever act
    # on. Harmless, and worth saying once rather than leaving in the variable
    # looking like it does something.
    strays = stray_map_entries(host_map()[0])
    if addr:
        return {"kind": "a sandbox VM" if addr.lower().startswith("ssh://")
                        else "a socket proxy",
                "where": addr, "shadowed": sock, "strays": strays}
    if sock:
        return {"kind": "the mounted socket", "where": "/var/run/docker.sock",
                "shadowed": False, "strays": strays}
    return {"kind": "", "where": "", "shadowed": False, "strays": strays}


def available():
    """Whether the daemon answers, and if not, why — said rather than guessed.

    DOCKER_HOST unset means the operator has not wired the proxy; the feature
    shows as absent-with-a-reason instead of a row of dead buttons.
    """
    want = (os.environ.get("DOCKER_HOST") or "").strip()
    if not want and not Path("/var/run/docker.sock").exists():
        return {"on": False, "why": "no DOCKER_HOST set — the socket proxy is "
                                    "not wired up; see docs/unraid.md"}
    if want.lower() == "auto" and not docker_host() \
            and not Path("/var/run/docker.sock").exists():
        return {"on": False,
                "why": "DOCKER_HOST is auto and no socket proxy answered on "
                       "this container's network — is it running, and does it "
                       "allow /version? See docs/unraid.md"}
    r = _run([DOCKER, "version", "--format", "{{.Server.Version}}"], timeout=10)
    if r["code"] != 0:
        return {"on": False,
                "why": "docker does not answer: " + (r["out"] or "no daemon").strip()[:120]} \
            | source()
    return {"on": True, "why": ""} | source()


_avail = {"when": 0.0, "val": None}
_avail_lock = threading.Lock()
AVAIL_TTL = 30


def available_cached():
    """available(), memoised for AVAIL_TTL seconds.

    available() shells out to `docker version` with a ten-second timeout, and
    the status poll runs every fifteen. Asking it on the poll — and the poll is
    what the page's Docker controls read — would put a subprocess and a network
    round trip on the page's heartbeat, for an answer that changes when the
    operator wires something up rather than between two polls.

    Short enough that plugging the daemon in and pressing Refresh notices, long
    enough that it is not on the critical path of anything.
    """
    now = time.time()
    with _avail_lock:
        if _avail["val"] is not None and now - _avail["when"] < AVAIL_TTL:
            return _avail["val"]
    val = available()
    with _avail_lock:
        _avail.update(when=now, val=val)
    return val


def forget_available():
    """Drop the memo — for a control that has just been told to try again."""
    with _avail_lock:
        _avail["val"] = None


# The classic builder, not BuildKit. `compose build` defaults to buildx,
# which boots a helper container and then ATTACHES to it — and attach is a
# hijacked connection, near enough to exec that a socket proxy worth having
# refuses it. Measured against the operator's own proxy: buildx dies with
# "unable to upgrade to tcp, received 403", the classic builder succeeds.
# It runs entirely daemon-side through POST /build, which is the endpoint
# the proxy's own BUILD flag governs — so this asks for exactly the
# permission the setup documentation tells people to grant, and no more.
_CLASSIC_BUILD = {"DOCKER_BUILDKIT": "0", "COMPOSE_DOCKER_CLI_BUILD": "1"}


# Every docker call that CHANGES anything is a compose call inside the
# project's own bbdev- namespace. That is what keeps the blast radius to
# containers this dashboard created — and until this guard it was true only
# because every call site happened to go through _compose(). A socket proxy
# cannot help with it: its flags are per ENDPOINT, so CONTAINERS=1 is the
# entire /containers API for every container on the host, and no arrangement
# of them means "only ours".
#
# So the invariant is asserted at the one place every call passes through,
# which turns "the code always passes --project-name" into "the code cannot
# not". It says nothing about what a compose FILE asks for — see risks().
#
# `ps` is allowed alongside `version`, and the reason it was not is worth
# keeping rather than deleting: this list used to be one verb long because
# DOCKER_HOST was a socket proxy onto the SERVER's daemon, where listing
# containers meant listing the operator's real ones. That is no longer where
# it points. Against a sandbox VM the containers are this dashboard's and
# whatever else was put there deliberately, and being unable to see them is
# not safety, it is a blind spot — the Docker Manager exists to show what is
# actually running.
#
# Both are READS. Nothing here lets a verb that changes something in, and the
# namespace rule below is untouched: seeing a container is not touching it.
_BARE_OK = {"version", "ps"}


def _guard(argv):
    """The reason to refuse this argv, or "" to let it run."""
    if not argv or argv[0] != DOCKER:
        return ""                      # git, and anything else not docker
    verb = argv[1] if len(argv) > 1 else ""
    if verb in _BARE_OK:
        return ""
    if not verb:
        return "a bare `docker` with no subcommand"
    # The runs that tend the dev-data directory, recognised by SHAPE and never
    # by verb. `docker run` with a bind is root on the daemon, so allowing the
    # verb would give away everything the namespace rule above protects;
    # allowing these gives away a mkdir, a mv and a test on one directory.
    # Every template is rebuilt from the names the argv itself carries and
    # compared whole, so the only way through is a command _devdata_argv could
    # have produced — and only where the daemon is a machine whose job is
    # being wrecked.
    if verb == "run":
        if not sandbox_daemon():
            return ("`docker run` — only where the daemon is a sandbox VM, "
                    "and this one is not")
        names = [a[3:] for a in argv if a.startswith("/d/")]
        if names and all(_DEV_NAME.match(n) for n in names) and any(
                argv == _devdata_argv(op, *names) for op in _DEVDATA_OPS):
            return ""
        return "a `docker run` this module did not build"
    if verb != "compose":
        return (f"`docker {verb}` — only compose, and the reads in "
                f"{'/'.join(sorted(_BARE_OK))}, are reachable here")
    try:
        name = argv[argv.index("--project-name") + 1]
    except (ValueError, IndexError):
        return "a compose call carrying no --project-name"
    if not name.startswith("bbdev-"):
        return f"a compose call outside the bbdev- namespace ({name})"
    return ""


def _run(argv, timeout=60, env_extra=None, sink=None, hold=None):
    """One docker or compose call.

    `sink` and `hold` are what make a long one watchable and stoppable. Without
    them the output arrives when the process exits, which for `compose build`
    is minutes of nothing followed by everything at once — a pull that looks
    like a hang. With a sink the lines are handed over as they are read, so
    the row's tail fills while it runs; with `hold` the process is offered to
    the caller so Abort has something to interrupt.

    Both optional, and every short call still takes the simple path: a
    `docker version` does not need a reader thread.
    """
    bad = _guard(argv)
    if bad:
        # Refused rather than raised: _worker runs builds on a thread, where an
        # exception would end the job with nothing to show for it. A code and a
        # message travel the path a real docker failure already travels — and
        # say plainly that this one is a bug here, not a daemon that said no.
        msg = "refused by BuilderBot, and this is a bug in it: " + bad
        print("[devapp] " + msg, file=sys.stderr, flush=True)
        return {"code": 126, "out": msg}
    env = dict(os.environ)
    # The resolved address, so `auto` never reaches the docker CLI — it does
    # not know the word.
    host = docker_host()
    if host:
        env["DOCKER_HOST"] = host
    else:
        env.pop("DOCKER_HOST", None)
    if env_extra:
        env.update(env_extra)
    if sink is None and hold is None:
        try:
            r = subprocess.run(argv, capture_output=True, text=True,
                               timeout=timeout, env=env, check=False)
        except subprocess.TimeoutExpired:
            # Ahead of the general case, which it is a subclass of. str() on
            # this one dumps the whole argv, and the argv is this module's own
            # doing — noise in a row or a doctor line that has room for a
            # sentence.
            return {"code": 1, "out": f"timed out after {timeout}s"}
        except (OSError, subprocess.SubprocessError) as e:
            return {"code": 1, "out": str(e)}
        return {"code": r.returncode, "out": (r.stdout or "") + (r.stderr or "")}
    return _run_streamed(argv, timeout, env, sink, hold)


def _run_streamed(argv, timeout, env, sink, hold):
    """The watchable form: read as it goes, and let it be killed.

    stderr is folded into stdout because that is where docker writes its
    progress and where compose writes everything — two streams read separately
    would interleave by luck rather than by time.

    Its own process group, so a kill reaches what the CLI is waiting on rather
    than only the CLI: the packages installer learned this against a `bb` that
    was itself waiting on a curl, and a compose call waiting on a pull is the
    same shape.
    """
    out = []
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             bufsize=1, env=env, start_new_session=True)
    except (OSError, subprocess.SubprocessError) as e:
        return {"code": 1, "out": str(e)}
    if hold:
        hold(p)
    deadline = time.time() + timeout
    try:
        for line in p.stdout:
            out.append(line)
            if sink:
                sink(line)
            if time.time() > deadline:
                _kill_group(p)
                out.append(f"\ntimed out after {timeout}s\n")
                break
    except (OSError, ValueError):
        pass                          # the pipe went with the process
    finally:
        if hold:
            hold(None)
    try:
        code = p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _kill_group(p)
        code = 1
    return {"code": code, "out": "".join(out)}


def _kill_group(p):
    """The group, not the process: a compose CLI waiting on a pull leaves the
    download running if only the CLI is signalled."""
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass

# The compose label every container started by compose carries. Read rather
# than parsed out of the name: a compose file may set container_name to
# anything, and the name is then not the namespace at all.
COMPOSE_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"


def containers():
    """Everything on the daemon, and whose it is.

    All of them, not only ours. The operator asked to see what is running on
    that machine and showing half of it would be a listing that lies by
    omission — a port conflict with something this dashboard did not start is
    exactly the thing you open a list to find out about.

    `ours` is the honest part: a container is this dashboard's when its compose
    project sits in the bbdev- namespace, which is the same rule _guard()
    enforces on every call that changes anything. Everything else is shown and
    marked as not ours, and nothing here offers to act on it.
    """
    r = _run([DOCKER, "ps", "--all", "--no-trunc", "--format", "{{json .}}"],
             timeout=25)
    if r["code"] != 0:
        return {"error": " ".join((r["out"] or "docker did not answer").split())[:200],
                "containers": []}
    out = []
    for line in r["out"].splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            c = json.loads(line)
        except ValueError:
            continue
        labels = _labels(c.get("Labels", ""))
        proj = labels.get(COMPOSE_LABEL, "")
        out.append({
            # Short, because the full id is 64 characters of nothing anyone
            # reads — and the whole one is still what docker was asked for, so
            # this is a display choice rather than a lossy fetch.
            "id": (c.get("ID") or "")[:12],
            "name": c.get("Names", ""),
            "image": c.get("Image", ""),
            "state": (c.get("State") or "").lower(),
            "status": c.get("Status", ""),
            "ports": _ports(c.get("Ports", "")),
            "project": proj,
            "service": labels.get(SERVICE_LABEL, ""),
            "ours": proj.startswith("bbdev-"),
        })
    out.sort(key=lambda c: (not c["ours"], c["project"], c["name"]))
    return {"error": "", "containers": out}


def _labels(raw):
    """docker's comma-separated k=v label string, as a dict.

    Split on the first = only: a label value may contain one, and the compose
    labels this cares about are paths and names often enough for that to
    matter.
    """
    d = {}
    for bit in (raw or "").split(","):
        k, sep, v = bit.partition("=")
        if sep:
            d[k.strip()] = v.strip()
    return d


def _ports(raw):
    """The published ports, deduplicated and without the noise.

    docker prints each mapping once per address family, so a single published
    port arrives twice — as 0.0.0.0:8080->80/tcp and [::]:8080->80/tcp. Shown
    both ways it reads as two ports.
    """
    seen = []
    for bit in (raw or "").split(","):
        bit = bit.strip()
        if "->" not in bit:
            continue
        host, _, rest = bit.partition("->")
        port = host.rsplit(":", 1)[-1]
        entry = f"{port}->{rest}"
        if entry not in seen:
            seen.append(entry)
    return seen


def containers_dir(name):
    return STATE / "containers" / name


def compose_file(project, instance=MAIN):
    """The compose file behind an instance.

    Two sources, and the record says which. A project's instance is built from
    the working copy — that is the whole point of it. A container written here
    has no working copy at all: its compose file lives in /config beside the
    rest of the notebook's storage, where the project scan cannot see it and
    the backup that takes /config takes it too.
    """
    if _read_rec(project, instance).get("source") == "file":
        f = containers_dir(project) / "docker-compose.yml"
        return f if f.is_file() else None
    for n in COMPOSE_NAMES:
        p = WORKSPACE / project / n
        if p.is_file():
            return p
    return None


def _pname(project, instance=MAIN):
    """The compose project name: namespaced, so a dev instance can never
    collide with a container the operator runs for real — and now carrying
    which instance of the project it is, because a project may have several.

    Both halves are slugged and joined with a dash, which means two different
    pairs could in principle collide (`a-b`/`c` and `a`/`b-c`). They cannot in
    practice: the project half is a directory name under /workspace and the
    instance half is chosen against the names already taken for that project,
    so a collision would need two projects to exist whose slugs overlap that
    way. Worth knowing rather than worth encoding around.
    """
    return f"bbdev-{_slug(project)}-{_slug(instance) or MAIN}"


def env_path(project, instance=MAIN):
    """One env file per INSTANCE, not per project.

    Two instances of one codebase exist to differ — different ports at the very
    least, or they cannot both run — so sharing an env would make the second
    one impossible. Named for the compose project, which is already unique and
    already slugged.
    """
    return ENVDIR / f"{_pname(project, instance)}.env"


def _compose(project, instance, *args):
    """The one shape every action runs: compose, pinned to this instance's
    name and env and to its project's file. A table of verbs, not a command
    string.

    The project directory and the compose file are the PROJECT's — every
    instance of a project is built from the same codebase, which is the whole
    point of having more than one of them.
    """
    cf = compose_file(project, instance)
    # What a relative bind source resolves against, and it must be a path the
    # DAEMON has. A project's own directory is one — /workspace has parity with
    # the sandbox by construction. /config does not: it is this container's
    # alone, so a container written here points at its data directory under
    # DEVDATA instead, which the daemon has whichever side made it, and which
    # is where its data belongs anyway.
    if _read_rec(project, instance).get("source") == "file":
        # The NAME of it, not a promise that it is there: _compose is on the
        # poll path (`ps`, `config`) and where the daemon makes this directory
        # itself, making it here would be a container launch every few seconds.
        # Compose does not care — a missing --project-directory is only a
        # problem for a bind that has to resolve, which is `up` and `build`,
        # and those go through _dev_data_env, which does make it. Checked
        # against compose rather than assumed: `config -q`, `config --format
        # json` and `ps -aq` all exit 0 with the directory absent.
        pdir = (dev_data_dir(project, instance, make=False)
                or str(Path(DEVDATA) / _pname(project, instance)))
    else:
        pdir = str(WORKSPACE / project)
    argv = [DOCKER, "compose", "--project-name", _pname(project, instance),
            "--project-directory", pdir, "-f", str(cf)]
    ep = env_path(project, instance)
    if ep.is_file():
        argv += ["--env-file", str(ep)]
    return argv + list(args)


# ---------------------------------------------------------------------------
# this container's paths are not the daemon's
#
# The one thing about a remote daemon that is easy to forget and impossible to
# see: a bind mount's SOURCE is resolved by whoever runs the container, and
# that is the host. `/workspace/alpha` and `/devdata/bbdev-alpha` mean
# something here and nothing over there — docker does not error on a missing
# bind source, it creates an empty directory and mounts that. On Unraid the
# root filesystem is RAM, so the failure is an app that starts with no data
# and loses it again at reboot, which reads as a bug in the app.
#
# So the operator states the mapping once, and it is checked rather than
# trusted. Only the paths BuilderBot itself hands over can be fixed by it;
# what a project's own compose file writes is the project's to get right, and
# is named on the row when it is a path the host will not find.


def _mount_roots():
    """{mount point: the path that mount has inside its own filesystem}.

    mountinfo's fourth field is the half that survives the trip: /devdata is
    mounted from /appdata/builderbot-dev of some pool, whatever that pool is
    called over on the host.
    """
    out = {}
    try:
        with open(os.environ.get("BB_MOUNTINFO", "/proc/self/mountinfo"),
                  encoding="utf-8") as f:
            for line in f:
                p = line.split()
                if len(p) > 4:
                    out[p[4]] = p[3]
    except OSError:
        pass
    return out


def host_map():
    """(container path -> host path, complaints about the pairs given).

    From DOCKER_HOST_PATHS, "/container:/host" pairs separated by commas. Each
    is checked against the mount it claims to describe: a host path has to end
    with that mount's own root path, so /devdata (root /appdata/builderbot-dev)
    accepts /mnt/cache/appdata/builderbot-dev and rejects /mnt/user/something.
    That is not proof — two shares can end alike — but it catches the case
    this has to catch, which is a template whose two sides were edited apart.
    A rejected pair is dropped rather than used: no answer beats a wrong one,
    because a wrong one is the silent failure above wearing a fix.
    """
    roots, out, bad = _mount_roots(), {}, []
    root = None
    for pair in (os.environ.get("DOCKER_HOST_PATHS") or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        here, _, there = pair.partition(":")
        here, there = here.rstrip("/"), there.strip().rstrip("/")
        if not here.startswith("/") or not there.startswith("/"):
            bad.append(f"{pair} is not a /container:/host pair")
            continue
        # An identity pair is not a translation and there is nothing to check
        # it against: it says the daemon calls this path what we call it, which
        # is the sandbox-VM arrangement — the shares mounted over there at the
        # paths used over here. This container's mount table describes its own
        # mounts and says nothing about that machine's, so running the check
        # below on one would reject a mapping that is correct by construction.
        if here == there:
            out[here] = there
        elif (root := roots.get(here)) is None:
            bad.append(f"{here} is not mounted in this container")
        elif root != "/" and not there.endswith(root):
            bad.append(f"{here} is mounted from {root}, which {there} "
                       f"does not end with — one side of the mapping moved")
        else:
            out[here] = there
    return out, bad


def to_host(path, mapping=None):
    """The host's name for a path of ours, or None when nobody has said."""
    mapping = host_map()[0] if mapping is None else mapping
    p = str(path).rstrip("/")
    # Longest prefix, so a mapping of a directory inside another one wins.
    for here in sorted(mapping, key=len, reverse=True):
        if p == here or p.startswith(here + "/"):
            return mapping[here] + p[len(here):]
    return None


# ---------------------------------------------------------------------------
# the dev-data directory, when only the daemon can see it
#
# BB_DEV_DATA points a compose file's volumes at a per-instance directory under
# DEVDATA, and somebody has to CREATE that directory. For a long time the only
# candidate was this container, which meant DEVDATA had to be mounted here as
# well as over there purely so mkdir had somewhere to run.
#
# Docker will not do it itself: given a bind source that does not exist it
# makes the directory as root and then chowns it, and on a share that squashes
# root the chown fails and takes the run down with it — measured on this box,
# "error while creating mount source path ...: chown ...: operation not
# permitted". The directory is left behind, so the SECOND press works. An
# intermittent-looking failure with a fixed cause.
#
# So the daemon makes it, in a container of its own. That is a `docker run`,
# which is root-equivalent on whichever machine answers — fine on a sandbox VM
# whose job is being wrecked, not fine on a socket proxy onto the server's own
# daemon. Hence the gate below, and hence _guard recognising these commands by
# rebuilding them rather than by allowing the verb.

# Tiny, and on every registry. One pull per sandbox, the first time an instance
# is created rather than on a poll.
DEVDATA_IMAGE = "alpine"

# Every operation this module will ask the daemon to perform on that share.
_DEVDATA_OPS = {"mkdir": ["mkdir", "-p"], "mv": ["mv"], "test": ["test", "-d"]}

# What may follow /d/. No slash, so nothing can climb out of the mount; no
# leading dot, so `..` is not a name.
_DEV_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def sandbox_daemon():
    """Is the daemon a sandbox VM — a machine whose whole job is being wrecked?

    The one question that decides whether this module may run anything other
    than compose. source() already works the answer out from DOCKER_HOST.
    """
    return source()["kind"] == "a sandbox VM"


def _devdata_argv(op, *names):
    """One of the commands above, as the exact argv it will be run as.

    In one place because _guard rebuilds it from a candidate argv and compares
    — so what is allowed is these commands, not the verb they begin with.
    DEVDATA itself is the mount and the names are its children, which confines
    every one of them to it by construction rather than by checking.

    Owned by whoever BuilderBot runs as: the same ownership the local mkdir
    this replaces produced, so an instance's data does not change hands when
    the arrangement does.
    """
    return [DOCKER, "run", "--rm", "-u", f"{os.getuid()}:{os.getgid()}",
            "-v", f"{DEVDATA.rstrip('/')}:/d", DEVDATA_IMAGE,
            *_DEVDATA_OPS[op], *(f"/d/{n}" for n in names)]


def _devdata_run(op, *names, quiet=False):
    """Run one. True if it did what it was asked."""
    r = _run(_devdata_argv(op, *names), timeout=300)
    if r["code"] != 0:
        if not quiet:
            print(f"[devapp] {op} {' '.join(names)} failed on the daemon: "
                  f"{r['out'].strip()[:200]}", file=sys.stderr, flush=True)
        return False
    return True


def dev_data_dir(project, instance=MAIN, make=True):
    """The instance's data directory, named the way the DAEMON names it.

    Two arrangements, and the only difference is who runs mkdir:

    - DEVDATA is mounted here. Make it here and translate through the mapping.
      What a socket proxy onto the server's own daemon requires, there being
      no safe way to ask that daemon to run a container.
    - It is not, and the daemon is a sandbox. DEVDATA is then a path on that
      machine and it makes the directory itself. Nothing has to be mounted
      here at all, which is the point: one shared path instead of two.

    None when neither applies — no mapping, or the mkdir failed. The caller
    then leaves BB_DEV_DATA unset and the compose fails loudly, which beats
    mounting an empty directory in the host's RAM and calling it the cache
    drive.
    """
    name = _pname(project, instance)
    root = Path(DEVDATA)
    if root.is_dir():
        d = root / name
        if make:
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError:
                return None
        return to_host(d)
    if sandbox_daemon():
        if make and not _devdata_run("mkdir", name):
            return None
        return posixpath.join(DEVDATA, name)
    return None


def rename_dev_data(old, new):
    """Move an instance's data when its project is renamed — (moved?, error).

    The case projects.py cannot reach with a rename(2), because the directory
    is on the daemon's disk and not on ours. It handles the mounted case
    itself; this answers False with no error when that is the arrangement, so
    nothing is done twice.

    A project that never had a dev instance has nothing to move and is not a
    failure — the same rule as the local move.
    """
    if Path(DEVDATA).is_dir() or not sandbox_daemon():
        return False, ""
    if not _devdata_run("test", old, quiet=True):
        return False, ""
    if not _devdata_run("mv", old, new):
        return False, ("the dev instance's data is on the sandbox and could "
                       "not be moved — it is still under the old name")
    return True, ""


def _dev_data_env(project, instance=MAIN):
    """BB_DEV_DATA for a compose that opts in with ${BB_DEV_DATA}/... —
    cache-backed volumes by convention, nothing forced on a compose that never
    mentions it.
    """
    d = dev_data_dir(project, instance)
    return {"BB_DEV_DATA": d} if d else {}


# ---------------------------------------------------------------------------
# env files

def _keys(text):
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            out.append(line.split("=", 1)[0].strip())
    return out


def read_env(project, instance=MAIN):
    try:
        return env_path(project, instance).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def starter(project, instance=MAIN):
    """What an empty editor opens on: the repo's .env.example, seeded.

    A blank box under a list of six key names asks the operator to type out
    what the example already spells — with its own comments explaining each
    one, which is the half a list of names throws away. Seeded, not saved:
    nothing reaches disk until Save, so `missing_env` keeps answering about
    the stored file and Up stays honestly dead until the values are real.
    """
    try:
        example = (WORKSPACE / project / ".env.example").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if not example.strip():
        return ""
    return ("# Started from this project's .env.example. Fill in the values\n"
            "# and press Save — nothing is written until you do.\n\n"
            + example.rstrip() + "\n")


def write_env(project, text, instance=MAIN):
    if len(text or "") > 65536:
        return {"error": "that env file is over 64KB — this holds settings, "
                         "not data"}
    try:
        ENVDIR.mkdir(parents=True, exist_ok=True)
        env_path(project, instance).write_text(text or "", encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write the env file: {e}"}
    _bump()
    return {"ok": True}


def missing_env(project, instance=MAIN):
    """Keys the repo's example declares that the dev env does not set."""
    try:
        example = (WORKSPACE / project / ".env.example").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return []
    have = set(_keys(read_env(project, instance)))
    return [k for k in _keys(example) if k not in have]


def _gate_env(project, instance=MAIN):
    """Rewrite the env as the new example, old values kept in comments.

    The operator fills the new keys in and presses Up; their old answers are
    right there to copy rather than remembered or lost.
    """
    old = read_env(project, instance)
    try:
        example = (WORKSPACE / project / ".env.example").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        example = ""
    stamp = time.strftime("%Y-%m-%d %H:%M")
    kept = "\n".join("# old: " + ln for ln in old.splitlines() if ln.strip())
    text = (f"# The rebuild on {stamp} found new settings in .env.example.\n"
            f"# Fill them in below — your previous env is preserved in the\n"
            f"# 'old:' comments at the bottom — then press Up.\n\n"
            f"{example.rstrip()}\n\n"
            f"# ---- what this file held before the rebuild ----\n{kept}\n")
    write_env(project, text)


# ---------------------------------------------------------------------------
# state

def _with_compose():
    """Projects that have a compose file, so could have an instance at all."""
    out = []
    try:
        for d in sorted(WORKSPACE.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and d.name != "_work" \
                    and compose_file(d.name) is not None:
                out.append(d.name)
    except OSError:
        pass
    return out


def overview():
    """Every instance, and everything else on the daemon, from ONE ps.

    state() asks the daemon twice per instance — is it running, does anything
    exist — which is fine for one row and absurd for a manager listing all of
    them. The container list already answers both for everything at once: an
    instance's containers are the ones whose compose project is its name. So
    the whole page costs one docker call plus what is already on disk.

    What it deliberately does NOT compute is the expensive half: risks,
    problems, the parsed compose config. Those are per-instance questions
    asked when somebody acts on one, and state() still answers them.
    """
    cs = containers()
    by_proj = {}
    for c in cs["containers"]:
        by_proj.setdefault(c["project"], []).append(c)
    store = _load()
    out = []
    # The STORE's instances, not instances() — that one synthesises `main` for
    # any project with a compose file, which is right for "what may I act on"
    # and wrong here: it filled the manager with a row per project that had
    # never been sent anywhere, indistinguishable from ones that had. A record
    # exists because somebody pressed Send.
    for project in sorted(store):
        # Once per PROJECT, not per instance: every instance of a project is
        # built from the same working copy, so the answer cannot differ
        # between them and asking git twice for it would be waste.
        filed = is_file_source(project)
        head, dirty = ("", False) if filed else (_head(project), _dirty(project))
        for inst in sorted(store[project]):
            pn = _pname(project, inst)
            mine = by_proj.get(pn, [])
            rec = _read_rec(project, inst)
            same_daemon = rec.get("daemon") == daemon_id()
            out.append({
                "project": project, "instance": inst, "name": pn,
                "running": any(c["state"] == "running" for c in mine),
                "exists": bool(mine),
                "containers": len(mine),
                # Ports from the containers themselves rather than from the
                # compose file: what is published is what the daemon says it
                # published, and a stopped instance publishes nothing.
                "ports": sorted({p for c in mine for p in c["ports"]}),
                # The same rule state() uses — a build belongs to the daemon
                # it happened on, and a record from another names nothing here.
                "built_rev": rec.get("rev", "") if same_daemon else "",
                "built_at": rec.get("at", 0) if same_daemon else 0,
                "await_env": bool(rec.get("await_env")) if same_daemon else False,
                "compose": compose_file(project, inst) is not None,
                "source": "file" if filed else "project",
                # Both are file reads and one git call, which is why they are
                # here and risks/problems are not: those parse the compose
                # file, and the manager lists every instance at once.
                "missing_env": missing_env(project, inst),
                "changed": True if filed else (
                    not (rec.get("rev") if same_daemon else "")
                    or (same_daemon and rec.get("rev") != head) or dirty),
                "changed_why": ("moved" if same_daemon and rec.get("rev")
                                and rec.get("rev") != head
                                else "dirty" if dirty and same_daemon and rec.get("rev")
                                else ""),
            })
    return {"error": cs["error"], "instances": out,
            # The running job, if there is one. The manager used to look for
            # it on the status snapshot under a key nothing has ever set, so
            # `busy` was permanently false: a row kept saying "never built"
            # through its own build, and Up/Rebuild/Remove stayed live for a
            # second click the server then refused. It belongs here, with the
            # rest of what this page draws from.
            # While it is running OR while it has something to say about how it
            # ended. Dropped the moment it stopped, a build that failed — or one
            # stopped on purpose, which ends a job with no other trace — left
            # the row showing whatever state it happened to be in and no account
            # of why. It is replaced by the next job, which is when it stops
            # being the answer to "what just happened here".
            "job": dict(_job) if (_job["running"] or _job["error"]) else None,
            # Only the ones that are not an instance of ours: the instances
            # above already account for those, and listing them twice would
            # make the page look like the daemon is running double.
            "containers": [c for c in cs["containers"] if not c["ours"]]}


COMPOSE_MAX = 200_000            # a compose file is a page, not a payload


def create_container(name, compose_text, env_text=""):
    """A container from a compose file written here, with no project behind it.

    The shape every other Docker front end uses: a stack is a name, a compose
    file and an environment. Labels are not a third field — in compose they
    live in the YAML, and a separate box for them would be inventing a concept
    this format does not have.

    Validated before it is registered, by asking compose itself to parse it:
    a file that does not resolve is a container that cannot start, and finding
    that out at Build time means the failure arrives one screen away from the
    text that caused it.
    """
    slug = _slug(name)
    if not slug:
        return {"error": "a container needs a name with a letter or digit in it"}
    if not (compose_text or "").strip():
        return {"error": "a compose file is needed"}
    if len(compose_text) > COMPOSE_MAX:
        return {"error": f"that compose file is over {COMPOSE_MAX // 1000}kB"}
    with _lock:
        if slug in _load():
            return {"error": f"{slug} already exists — pick another name"}
    d = containers_dir(slug)
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / "docker-compose.yml").write_text(compose_text, encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write it: {e}"}
    # Registered before the check, because the check goes through _compose()
    # and that reads the record to know where the file is. Removed again if
    # the file turns out not to parse, so a refusal leaves nothing behind.
    with _lock:
        d2 = _load()
        _rec(d2, slug, MAIN)["source"] = "file"
        write_json(FILE, d2)
    if (env_text or "").strip():
        write_env(slug, env_text, MAIN)
    r = _run(_compose(slug, MAIN, "config", "-q"), timeout=30)
    if r["code"] != 0:
        forget_container(slug)
        return {"error": ("compose will not read that:\n" + r["out"]).strip()[-600:]}
    _bump()
    return {"ok": True, "project": slug, "instance": MAIN,
            "name": _pname(slug, MAIN)}


def overview_names():
    """Every name the store knows — what an endpoint checks a request against."""
    return set(_load())


def update_container(name, compose_text, env_text):
    """Change what a container is, after it exists.

    Ports move, a volume is added, an image is pinned — a compose file written
    here is edited far more often than it is created, and without this the only
    way to change one was to remove it and write it again from memory.

    The old file is kept until the new one parses. A compose file that will not
    read is not a state to leave a container in, and the operator is looking at
    the text that caused it.
    """
    if not is_file_source(name):
        return {"error": f"{name} is not a container written here"}
    if not (compose_text or "").strip():
        return {"error": "a compose file is needed"}
    if len(compose_text) > COMPOSE_MAX:
        return {"error": f"that compose file is over {COMPOSE_MAX // 1000}kB"}
    f = containers_dir(name) / "docker-compose.yml"
    try:
        was = f.read_text(encoding="utf-8")
    except OSError:
        was = ""
    try:
        f.write_text(compose_text, encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write it: {e}"}
    r = _run(_compose(name, MAIN, "config", "-q"), timeout=30)
    if r["code"] != 0:
        with contextlib.suppress(OSError):
            f.write_text(was, encoding="utf-8")
        return {"error": ("compose will not read that:\n" + r["out"]).strip()[-600:]}
    write_env(name, env_text or "", MAIN)
    _bump()
    return {"ok": True, "project": name, "instance": MAIN,
            "note": "rebuild it to bring the change up"}


def read_container(name):
    """What was written, for the editor to open on."""
    try:
        compose = (containers_dir(name) / "docker-compose.yml").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        compose = ""
    return {"compose": compose, "env": read_env(name, MAIN)}


def forget_container(name):
    """Drop the record and the files. Only ever for one this wrote."""
    with _lock:
        d = _load()
        if name in d:
            del d[name]
            write_json(FILE, d)
    try:
        shutil.rmtree(containers_dir(name), ignore_errors=True)
    except OSError:
        pass


def create_instance(project, name):
    """Register a new instance of a project. Nothing is built or started.

    The name is slugged the same way it will be when it reaches a compose
    call, and checked against the slug rather than the typing — `My App` and
    `my-app` are the same instance and the second should be refused rather
    than silently becoming the first.
    """
    slug = _slug(name) or ""
    if not slug:
        return {"error": "an instance needs a name with a letter or digit in it"}
    if compose_file(project) is None:
        return {"error": f"{project} has no compose file to make an instance of"}
    with _lock:
        d = _load()
        if slug in (d.get(project) or {}):
            return {"error": f"{project} already has an instance called {slug}"}
        _rec(d, project, slug)
        write_json(FILE, d)
    _bump()
    return {"ok": True, "project": project, "instance": slug,
            "name": _pname(project, slug)}


def remove_instance(project, instance):
    """Take a container out of the manager: down it, then forget the record.

    What is NOT removed is the env file and the data directory. Removing is
    the way to tidy the list, not a way to destroy work — and an instance
    remade under the same name finding its old env there is the behaviour
    somebody who removed one by mistake would want. Deleting those is a shell
    away and is not something a button here should do quietly.
    """
    if instance not in (_load().get(project) or {}):
        return {"error": f"{project} has no instance called {instance}"}
    r = _run(_compose(project, instance, "down"), timeout=180)
    if r["code"] != 0:
        return {"error": ("could not take it down, so it was left alone:\n"
                          + r["out"])[-500:]}
    # A container written here has nowhere else to come back from — its
    # compose file IS the thing, and leaving it behind would keep the name
    # taken by something with no row to remove it from. A project's instance
    # keeps its env and data, which is what that button already promises.
    if is_file_source(project, instance):
        forget_container(project)
        _bump()
        return {"ok": True, "project": project, "instance": instance,
                "removed_files": True}
    with _lock:
        d = _load()
        if instance in (d.get(project) or {}):
            del d[project][instance]
            if not d[project]:
                del d[project]
            write_json(FILE, d)
    _bump()
    return {"ok": True, "project": project, "instance": instance}


def instances(project):
    """The instance names this project has, oldest record first.

    `main` is always offered even where nothing has been built yet: a project
    with a compose file has one instance conceptually from the moment it has
    the file, and a list that was empty until the first build would make the
    first build impossible to start from.
    """
    have = list((_load().get(project) or {}).keys())
    return have or [MAIN]


def states(project):
    """Every instance of a project, in one call, for the manager."""
    return [state(project, i) for i in instances(project)]


def _rec(d, project, instance):
    """One instance's record inside the store, created if it is not there.

    Every write goes through this rather than reaching in with two setdefaults,
    which is how the second level gets forgotten on one path and not another.
    """
    return d.setdefault(project, {}).setdefault(instance, {})


def _read_rec(project, instance):
    """The same, read-only and never creating anything."""
    return (_load().get(project) or {}).get(instance) or {}


def _load():
    """The store, always in its two-level shape: {project: {instance: record}}.

    Migrated on read rather than by a one-off script: the old shape is one
    record per project, and a record is recognisable — it has a rev, or a
    daemon, or an ack. Anything whose values are not dicts of dicts is the old
    layout and becomes the `main` instance, which is the name every call that
    does not ask for one uses. Nothing is written back here; the next save
    writes the new shape, and until then reading is enough.
    """
    try:
        with open(FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    out = {}
    for proj, val in d.items():
        if not isinstance(val, dict):
            continue
        # A dict of dicts is already instances; anything else is one record.
        if val and all(isinstance(v, dict) for v in val.values()):
            out[proj] = val
        else:
            out[proj] = {MAIN: val}
    return out


def _config(project, instance=MAIN):
    """The compose file as compose itself resolves it: variables substituted,
    relative paths made absolute against the project directory.

    None when it cannot be read, which every caller has to treat as the
    cautious answer rather than as "nothing here". Fetched once per poll
    because state() asks it two separate questions.
    """
    r = _run(_compose(project, instance, "config", "--format", "json"), timeout=30)
    if r["code"] != 0:
        return None
    try:
        d = json.loads(r["out"])
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def _services(cfg):
    return {n: sv for n, sv in ((cfg or {}).get("services") or {}).items()
            if isinstance(sv, dict)}


def needs_build(cfg):
    """Whether this compose has anything to build at all.

    A compose that only runs published images — `image: postgres` and no
    `build:` — has nothing for Build to do, and Up should not wait on one.
    A compose that declares a build must not be brought up before it has
    been: `compose up` would build it ITSELF, silently, through the buildx
    path this feature deliberately avoids, and the operator would get the
    403 from a button that never mentioned building.
    """
    if cfg is None:
        # Unreadable compose: assume it builds, which is the cautious way
        # round — Up stays gated rather than firing an implicit build.
        return True
    return any(bool(sv.get("build")) for sv in _services(cfg).values())


def _within(path, base):
    try:
        Path(path).resolve().relative_to(Path(base).resolve())
        return True
    except (ValueError, OSError):
        return False


def _binds(sv, project):
    """Host paths a service bind-mounts, in either spelling compose accepts:
    the normalized {"type": "bind", "source": ...} objects `config` emits, and
    the "host:container" short form, since depending on one shape of somebody
    else's JSON is how a check quietly stops checking."""
    out = []
    for v in sv.get("volumes") or []:
        src = ""
        if isinstance(v, dict):
            if (v.get("type") or "") != "bind":
                continue                    # a named volume is compose's own
            src = str(v.get("source") or "")
        elif isinstance(v, str):
            head = v.split(":")[0]
            # "data:/var/lib" names a volume; only a path is a host path.
            if head.startswith("/") or head.startswith("."):
                src = head
        if src:
            # Resolved, so that what the operator is shown is where the mount
            # actually lands: "../../etc" and a symlink both read as the
            # project's own directory until they are followed.
            p = Path(src) if src.startswith("/") else WORKSPACE / project / src
            try:
                out.append(str(p.resolve()))
            except OSError:
                out.append(str(p))
    return out


def risks(project, cfg):
    """What this compose asks for beyond its own directory.

    The half of the blast radius that no namespace can bound. A container
    started from a file saying `privileged: true` and mounting `/` is labelled
    bbdev- like every other one and passes every check that can be made on a
    name — so the file itself is read, and what it asks for is put in front of
    the operator before anything starts.

    Warned and confirmed rather than refused: a legitimate compose may want a
    host path (a media folder, the timezone file), and nothing here can tell
    which. The point is that it is never a surprise.
    """
    if cfg is None:
        return []
    out = []
    for name, sv in sorted(_services(cfg).items()):
        if sv.get("privileged"):
            out.append(f"{name} runs privileged — root on the host, in effect")
        # Named beside privileged rather than left out: a check that catches
        # `privileged: true` and misses `cap_add: [SYS_ADMIN]` has a hole in
        # it that is obvious to anyone who would use it.
        caps = sorted(c for c in (sv.get("cap_add") or []) if isinstance(c, str))
        if caps:
            out.append(f"{name} takes kernel capabilities: {', '.join(caps)}")
        devs = [d for d in (sv.get("devices") or []) if d]
        if devs:
            shown = ", ".join(str(d.get("source") if isinstance(d, dict) else d)
                              for d in devs[:3])
            out.append(f"{name} is handed host devices: {shown}"
                       + (" …" if len(devs) > 3 else ""))
        if str(sv.get("pid") or "") == "host":
            out.append(f"{name} shares the host's process namespace")
        if str(sv.get("network_mode") or "") == "host":
            out.append(f"{name} is on the host's own network")
    # Bind mounts are NOT listed here any more, and their absence is the
    # design rather than an oversight. wiring() puts every one of them on the
    # row, always, with the path it lands on — so repeating the ones that
    # reach outside the project restated what was already on screen two lines
    # above it, in worse words. What is left is the set that is invisible
    # otherwise: the flags that make a container more than a container.
    return out


def our_paths(mapping):
    """The paths this container has that the mapping speaks for.

    Was a hardcoded pair — /workspace and /devdata — which is what the mapping
    held on the day it was written and not what it holds now. A share added to
    both sides (an /auxiliary for general storage, say) was then translated by
    to_host and judged by nothing: a bind under it could name a directory the
    daemon does not have, and the answer to a missing bind source is an empty
    directory silently mounted in its place.

    Derived instead, so adding a mount to both sides is a setting rather than a
    code change. Existence is the filter, and it is the honest one: a mapping
    may name a path that only the DAEMON has — which is fine and common, and is
    not something this side can check anything about.
    """
    ours = [p for p in mapping if Path(p).is_dir()]
    # The two the mapping is usually silent about. With DOCKER_HOST_PATHS unset
    # there is no mapping at all, and these checks are exactly what says so.
    # DEVDATA only when this container actually has it: where the daemon makes
    # the dev-data directory itself that path is the DAEMON's, and judging it
    # as one of ours reports every correct compose file as broken.
    for p in (str(WORKSPACE), str(Path(DEVDATA))):
        if p not in ours and Path(p).is_dir():
            ours.append(p)
    return ours


def stray_map_entries(mapping):
    """Mapped paths this container does not have.

    Not an error: /auxiliary can be a share the sandbox mounts and BuilderBot
    has no business reading. But it is a line of configuration that nothing
    else here will ever act on, and saying so once beats it sitting in the
    variable looking like it does something.
    """
    return sorted(p for p in mapping if not Path(p).is_dir())


def problems(project, cfg):
    """Paths this compose gives the daemon that the daemon will not find.

    A different thing from risks(): those are decisions the operator may
    reasonably make, this is a compose file that cannot work. Kept apart so
    the confirmation stays about the first kind — asking someone to confirm a
    configuration error teaches them to confirm without reading.

    Only OUR paths are judged — every path this container has that the mapping
    speaks for, see our_paths(). Anything else is taken for a host path, which
    it usually is and which nothing here can check anyway.
    """
    if cfg is None:
        return []
    mapping = host_map()[0]
    ours = our_paths(mapping)
    out = []
    for name, sv in sorted(_services(cfg).items()):
        for src in _binds(sv, project):
            if not any(src == o or src.startswith(o + "/") for o in ours):
                continue
            there = to_host(src, mapping)
            # Identity means the daemon calls it the same thing we do, and
            # there is nothing wrong. That is the whole point of running the
            # daemon in a sandbox VM with the shares mounted at the paths
            # BuilderBot uses: the translation table becomes /workspace to
            # /workspace, and this check has nothing left to say. Without this
            # line the parity arrangement reports every correct compose file
            # as broken, and tells it to use the path it is already using.
            if there == src:
                continue
            out.append(
                f"{name} mounts {src}, which is this container's path — the "
                + (f"daemon calls that {there}" if there else
                   "daemon does not have it; say where it is with "
                   "DOCKER_HOST_PATHS"))
    return out


def wiring(cfg):
    """What this compose publishes and what it mounts.

    Shaped the way Unraid's own Docker tab shows it, because that is where the
    operator reads the same facts about every other container on the box: the
    container's side on the left, the host's on the right, and an arrow that
    says which way it goes — one way into the container for a read-only mount,
    both ways for a writable one.

    Off the resolved config, so a path or a port assembled out of variables is
    the value compose arrived at and not the spelling. Both spellings of each
    are handled for the same reason _binds does it: depending on one shape of
    somebody else's JSON is how a reader quietly stops reading.
    """
    if cfg is None:
        return {"ports": [], "mounts": []}
    ports, mounts = [], []
    for _name, sv in sorted(_services(cfg).items()):
        for p in sv.get("ports") or []:
            pub = tgt = proto = ""
            if isinstance(p, dict):
                pub, tgt = str(p.get("published") or ""), str(p.get("target") or "")
                proto = str(p.get("protocol") or "")
            elif isinstance(p, str):
                # "7475:7474/udp", "127.0.0.1:7475:7474", or a bare "7474"
                # for one the daemon picks.
                spec, _, proto = p.partition("/")
                bits = spec.split(":")
                tgt = bits[-1]
                pub = bits[-2] if len(bits) > 1 else ""
            if tgt:
                ports.append({"target": tgt, "published": pub,
                              "proto": (proto or "tcp").upper()})
        for v in sv.get("volumes") or []:
            src = tgt = ""
            ro = False
            if isinstance(v, dict):
                if (v.get("type") or "") != "bind":
                    continue           # a named volume has no host side to show
                src, tgt = str(v.get("source") or ""), str(v.get("target") or "")
                ro = bool(v.get("read_only"))
            elif isinstance(v, str):
                bits = v.split(":")
                if len(bits) < 2 or not (bits[0].startswith("/")
                                         or bits[0].startswith(".")):
                    continue
                src, tgt = bits[0], bits[1]
                ro = len(bits) > 2 and "ro" in bits[2].split(",")
            if src and tgt:
                mounts.append({"target": tgt, "source": src, "ro": ro})
    return {"ports": ports, "mounts": mounts}


def risk_digest(rs):
    """A stable name for one set of risks, so that acknowledging them stops
    counting the moment the compose file asks for something new."""
    if not rs:
        return ""
    return hashlib.sha256("\n".join(sorted(rs)).encode()).hexdigest()[:12]


def _risk_gate(project, instance=MAIN, ack=""):
    """The reason to stop before starting anything, or "" to go ahead."""
    rs = risks(project, _config(project, instance))
    if not rs:
        return ""
    d = risk_digest(rs)
    if _read_rec(project, instance).get("risks_ack") == d:
        return ""
    if ack and ack == d:
        with _lock:
            store = _load()
            _rec(store, project, instance)["risks_ack"] = d
            write_json(FILE, store)
        return ""
    return ("this compose asks for more than its own directory — "
            + "; ".join(rs[:3]) + (" …" if len(rs) > 3 else ""))


def _running(project, instance=MAIN):
    r = _run(_compose(project, instance, "ps", "--status", "running", "-q"), timeout=20)
    return r["code"] == 0 and bool(r["out"].strip())


def _exists(project, instance=MAIN):
    """Does compose know about any container here, running or not?

    A container that EXITED — a crash, a bad entrypoint, an OOM — is still
    there, still holding its name and the project's network, and `down` is the
    only thing that clears it. Asking only about RUNNING containers is what
    left a crashed instance with a greyed-out Down and no way out of the
    dashboard at all.
    """
    r = _run(_compose(project, instance, "ps", "-aq"), timeout=20)
    return r["code"] == 0 and bool(r["out"].strip())


def is_file_source(project, instance=MAIN):
    return _read_rec(project, instance).get("source") == "file"


def _head(project):
    r = _run(["git", "-C", str(WORKSPACE / project), "rev-parse", "--short=7",
              "HEAD"], timeout=10)
    return r["out"].strip() if r["code"] == 0 else ""


def _dirty(project):
    r = _run(["git", "-C", str(WORKSPACE / project), "status", "--porcelain"],
             timeout=10)
    return r["code"] == 0 and bool(r["out"].strip())


def state(project, instance=MAIN):
    """Everything the Artifacts row needs, or the reason there is no row."""
    if compose_file(project) is None:
        return {"compose": False}
    a = available()
    built = _read_rec(project, instance)
    # A build only counts on the daemon it happened on. Swinging DOCKER_HOST
    # from a socket proxy to a sandbox VM leaves the image and the containers
    # behind on a machine this container can no longer see, and the row went
    # on saying "built from <rev>" and offering Rebuild for something that had
    # never been built here. A record written before this field says nothing
    # about which daemon it was, and not knowing is not yes.
    #
    # Everything claiming a build goes: the rev and its date, the env gate a
    # build tripped, the marker saying one is in flight. What stays is the
    # operator's risk acknowledgement, which is about what the compose file
    # asks for and would be true on any daemon. Dropping the env gate costs
    # nothing — up() refuses on a live missing_env() rather than on the flag.
    if built.get("daemon") != daemon_id():
        built = {k: v for k, v in built.items()
                 if k not in ("rev", "at", "await_env", "building_since")}
    out = {"compose": True, "available": a["on"], "why": a["why"],
           # The compose project name, which is what actually namespaces the
           # containers, the network and the volumes. Not the container name:
           # a compose file may set container_name to anything it likes, and
           # there may be several. This is the one name that is always true.
           "instance": instance,
           "name": _pname(project, instance),
           "needs_build": True,
           "built_rev": built.get("rev", ""), "built_at": built.get("at", 0),
           "missing_env": missing_env(project, instance),
           "await_env": bool(built.get("await_env")),
           # A marker with no build running behind it means the container went
           # away mid-build: docker compose build is a subprocess of the
           # dashboard, so it died with it. Everything else already recovers
           # correctly — the last SUCCESSFUL build is still what built_rev
           # says, and Rebuild is live because the code has moved — but
           # without this the operator sees a button they thought they had
           # already pressed and is told nothing.
           "interrupted": bool(built.get("building_since")
                               and not _job["running"]),
           "job": (dict(_job) if _job["project"] == project
                   and _job["instance"] == instance else None)}
    if a["on"]:
        cfg = _config(project, instance)
        out["needs_build"] = needs_build(cfg)
        rs = risks(project, cfg)
        out["risks"] = rs
        out["problems"] = problems(project, cfg) + host_map()[1]
        out.update(wiring(cfg))
        out["risks_digest"] = risk_digest(rs)
        # True when nothing stands in the way — either the file asks for
        # nothing beyond its own directory, or the operator has already said
        # yes to exactly this set.
        out["risks_ack"] = (not rs
                            or built.get("risks_ack") == out["risks_digest"])
        out["running"] = _running(project, instance)
        # Only worth a second call when nothing is running: a running stack
        # self-evidently has containers, and this is on the artifacts poll.
        out["exists"] = out["running"] or _exists(project, instance)
        head = _head(project)
        dirty = _dirty(project)
        moved = bool(built.get("rev")) and built.get("rev") != head
        out["changed"] = not built.get("rev") or moved or dirty
        # WHICH of the two, because they are different facts and the row was
        # saying the wrong one: a commit since the build means the image is
        # behind the branch; an uncommitted edit means it is behind the
        # working tree. Both are reasons to offer Rebuild, and only one of
        # them is "the code has moved".
        out["changed_why"] = ("moved" if moved
                              else "dirty" if dirty and built.get("rev")
                              else "")
    else:
        out["running"] = False
        out["exists"] = False
        out["changed"] = False
        out["risks"] = []
        out["problems"] = []
        out["ports"] = []
        out["mounts"] = []
        out["risks_digest"] = ""
        out["risks_ack"] = True
    return out


# ---------------------------------------------------------------------------
# actions

def up(project, instance=MAIN, ack=""):
    if _job["running"]:
        return {"error": "a build is already running — one at a time"}
    gate = _risk_gate(project, instance, ack)
    if gate:
        return {"error": gate}
    miss = missing_env(project, instance)
    if miss:
        return {"error": "the env is missing " + ", ".join(miss[:4])
                         + (" …" if len(miss) > 4 else "")
                         + " — fill it in first (Env)"}

    # `compose up -d`, and nothing more clever: compose builds an image that
    # is missing, so Up on a never-built project does what the CLI does
    # rather than refusing on a rule of this dashboard's invention. The
    # classic builder rides along for exactly that case — an implicit build
    # through buildx would 403 against a socket proxy.
    r = _run(_compose(project, instance, "up", "-d"), timeout=1800,
             env_extra=_dev_data_env(project, instance) | _CLASSIC_BUILD)
    if r["code"] != 0:
        return {"error": ("compose up failed:\n" + r["out"])[-500:]}
    with _lock:
        d = _load()
        row = _rec(d, project, instance)
        row.pop("await_env", None)
        # An implicit build is still a build, so the row stops claiming the
        # project was never built while a container from it is running. Also
        # when the record belongs to a daemon we no longer talk to: state()
        # reads that as never-built-here, and without the second test the row
        # would go on saying so with the instance up in front of it.
        if not row.get("rev") or row.get("daemon") != daemon_id():
            row.update(rev=_head(project), at=int(time.time()),
                       daemon=daemon_id())
        write_json(FILE, d)
    _bump()
    return {"ok": True}


def down(project, instance=MAIN):
    if _job["running"]:
        return {"error": "a build is already running — one at a time"}
    r = _run(_compose(project, instance, "down"), timeout=180)
    if r["code"] != 0:
        return {"error": ("compose down failed:\n" + r["out"])[-500:]}
    _bump()
    return {"ok": True}


def rebuild(project, instance=MAIN, ack=""):
    """Build, then bounce — or stop at the env gate. In a thread: a build is
    minutes, and the poll watches it through job_rev."""
    if _job["running"]:
        return {"error": "a build is already running — one at a time"}
    if compose_file(project) is None:
        return {"error": "no compose file here"}
    # Before the build, not before the `up` inside it: a build runs this
    # project's Dockerfile, which is the same trust either way.
    gate = _risk_gate(project, instance, ack)
    if gate:
        return {"error": gate}
    # On disk before the work starts, so a restart can tell "this build never
    # finished" from "no build has been asked for". The job dict is memory and
    # dies with the container; this outlives it.
    with _lock:
        d = _load()
        _rec(d, project, instance)["building_since"] = int(time.time())
        write_json(FILE, d)
    _job.update(running=True, project=project, instance=instance,
                step="building", log="", error="", await_env=False,
                aborting=False)
    _bump()
    threading.Thread(target=_worker, args=(project, instance), daemon=True).start()
    return {"ok": True, "started": True}


def _clear_marker(project, instance=MAIN):
    """Drop the started-marker — the build reached an end, whichever end."""
    with _lock:
        d = _load()
        rec = (d.get(project) or {}).get(instance)
        if rec is not None:
            rec.pop("building_since", None)
            write_json(FILE, d)


def _worker(project, instance=MAIN):
    try:
        r = _run(_compose(project, instance, "build"), timeout=3600,
                 env_extra=_dev_data_env(project, instance) | _CLASSIC_BUILD,
                 sink=_log_line, hold=_hold_child)
        if _job["aborting"]:
            _job.update(error="stopped — what had already been built is kept",
                        step="")
            return
        if r["code"] != 0:
            _job.update(error="build failed — the tail of its output is below",
                        step="")
            return
        with _lock:
            d = _load()
            _rec(d, project, instance).update(rev=_head(project),
                                              at=int(time.time()),
                                              daemon=daemon_id())
            write_json(FILE, d)
        _job["step"] = "stopping"
        _bump()
        _run(_compose(project, instance, "down"), timeout=180)
        if missing_env(project, instance):
            # The gate: new settings exist that the env does not answer.
            # Rewrite the env with the old values in comments and leave Up
            # to the operator — see the module docstring.
            _gate_env(project, instance)
            with _lock:
                d = _load()
                _rec(d, project, instance)["await_env"] = True
                write_json(FILE, d)
            _job.update(await_env=True, step="")
            return
        _job["step"] = "starting"
        _bump()
        # Streamed too: `up` pulls anything the build did not, which is the
        # long wait on a compose file made of published images rather than a
        # Dockerfile — exactly the case that looked like a hang.
        r = _run(_compose(project, instance, "up", "-d"), timeout=600,
                 env_extra=_dev_data_env(project, instance),
                 sink=_log_line, hold=_hold_child)
        if _job["aborting"]:
            _job.update(error="stopped — the image is built; it was not started",
                        step="")
            return
        if r["code"] != 0:
            _job.update(error=("up failed:\n" + r["out"])[-500:], step="")
            return
        _job["step"] = ""
    finally:
        # Whatever happened — built, failed, gated — the build is no longer in
        # flight, so the marker goes. Only a killed process leaves it behind,
        # which is exactly what it is for.
        _clear_marker(project, instance)
        _job["running"] = False
        _bump()
