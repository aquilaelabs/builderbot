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
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

WORKSPACE = None
STATE = None
FILE = None
ENVDIR = None
write_json = None

DOCKER = os.environ.get("BB_DOCKER_BIN", "docker")
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

COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml",
                 "compose.yml", "compose.yaml")

_lock = threading.Lock()

# One job at a time, like the package installer: two parallel builds on one
# daemon help nobody, and a queue would hide which click did what.
_job = {"running": False, "project": "", "step": "", "log": "", "error": "",
        "await_env": False}
_rev = 0


def configure(*, workspace, state, write_json):
    globals().update(WORKSPACE=Path(workspace), STATE=Path(state),
                     write_json=write_json)
    globals()["FILE"] = Path(state) / "devapps.json"
    globals()["ENVDIR"] = Path(state) / "devenv"


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
                "why": "docker does not answer: " + (r["out"] or "no daemon").strip()[:120]}
    return {"on": True, "why": ""}


# The classic builder, not BuildKit. `compose build` defaults to buildx,
# which boots a helper container and then ATTACHES to it — and attach is a
# hijacked connection, near enough to exec that a socket proxy worth having
# refuses it. Measured against the operator's own proxy: buildx dies with
# "unable to upgrade to tcp, received 403", the classic builder succeeds.
# It runs entirely daemon-side through POST /build, which is the endpoint
# the proxy's own BUILD flag governs — so this asks for exactly the
# permission the setup documentation tells people to grant, and no more.
_CLASSIC_BUILD = {"DOCKER_BUILDKIT": "0", "COMPOSE_DOCKER_CLI_BUILD": "1"}


def _run(argv, timeout=60, env_extra=None):
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
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout, env=env, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return {"code": 1, "out": str(e)}
    return {"code": r.returncode, "out": (r.stdout or "") + (r.stderr or "")}


def compose_file(project):
    for n in COMPOSE_NAMES:
        p = WORKSPACE / project / n
        if p.is_file():
            return p
    return None


def _pname(project):
    """The compose project name: namespaced, so a dev instance can never
    collide with a container the operator runs for real."""
    return "bbdev-" + re.sub(r"[^a-z0-9]+", "-", project.lower()).strip("-")


def env_path(project):
    return ENVDIR / f"{project}.env"


def _compose(project, *args):
    """The one shape every action runs: compose, pinned to this project's
    file, name and env. A table of verbs, not a command string."""
    cf = compose_file(project)
    argv = [DOCKER, "compose", "--project-name", _pname(project),
            "--project-directory", str(WORKSPACE / project), "-f", str(cf)]
    ep = env_path(project)
    if ep.is_file():
        argv += ["--env-file", str(ep)]
    return argv + list(args)


def _dev_data_env(project):
    """BB_DEV_DATA for a compose that opts in with ${BB_DEV_DATA}/... —
    cache-backed volumes by convention, nothing forced on a compose that
    never mentions it."""
    root = Path(DEVDATA)
    if not root.is_dir():
        return {}
    d = root / _pname(project)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {}
    return {"BB_DEV_DATA": str(d)}


# ---------------------------------------------------------------------------
# env files

def _keys(text):
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            out.append(line.split("=", 1)[0].strip())
    return out


def read_env(project):
    try:
        return env_path(project).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def starter(project):
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


def write_env(project, text):
    if len(text or "") > 65536:
        return {"error": "that env file is over 64KB — this holds settings, "
                         "not data"}
    try:
        ENVDIR.mkdir(parents=True, exist_ok=True)
        env_path(project).write_text(text or "", encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write the env file: {e}"}
    _bump()
    return {"ok": True}


def missing_env(project):
    """Keys the repo's example declares that the dev env does not set."""
    try:
        example = (WORKSPACE / project / ".env.example").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return []
    have = set(_keys(read_env(project)))
    return [k for k in _keys(example) if k not in have]


def _gate_env(project):
    """Rewrite the env as the new example, old values kept in comments.

    The operator fills the new keys in and presses Up; their old answers are
    right there to copy rather than remembered or lost.
    """
    old = read_env(project)
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

def _load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except (OSError, ValueError):
        pass
    return {}


def _running(project):
    r = _run(_compose(project, "ps", "--status", "running", "-q"), timeout=20)
    return r["code"] == 0 and bool(r["out"].strip())


def _head(project):
    r = _run(["git", "-C", str(WORKSPACE / project), "rev-parse", "--short=7",
              "HEAD"], timeout=10)
    return r["out"].strip() if r["code"] == 0 else ""


def _dirty(project):
    r = _run(["git", "-C", str(WORKSPACE / project), "status", "--porcelain"],
             timeout=10)
    return r["code"] == 0 and bool(r["out"].strip())


def state(project):
    """Everything the Artifacts row needs, or the reason there is no row."""
    if compose_file(project) is None:
        return {"compose": False}
    a = available()
    built = _load().get(project) or {}
    out = {"compose": True, "available": a["on"], "why": a["why"],
           "built_rev": built.get("rev", ""), "built_at": built.get("at", 0),
           "missing_env": missing_env(project),
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
           "job": dict(_job) if _job["project"] == project else None}
    if a["on"]:
        out["running"] = _running(project)
        head = _head(project)
        out["changed"] = (not built.get("rev")
                          or built.get("rev") != head or _dirty(project))
    else:
        out["running"] = False
        out["changed"] = False
    return out


# ---------------------------------------------------------------------------
# actions

def up(project):
    if _job["running"]:
        return {"error": "a build is already running — one at a time"}
    miss = missing_env(project)
    if miss:
        return {"error": "the env is missing " + ", ".join(miss[:4])
                         + (" …" if len(miss) > 4 else "")
                         + " — fill it in first (Env)"}
    r = _run(_compose(project, "up", "-d"), timeout=180,
             env_extra=_dev_data_env(project))
    if r["code"] != 0:
        return {"error": ("compose up failed:\n" + r["out"])[-500:]}
    with _lock:
        d = _load()
        d.setdefault(project, {}).pop("await_env", None)
        write_json(FILE, d)
    _bump()
    return {"ok": True}


def down(project):
    if _job["running"]:
        return {"error": "a build is already running — one at a time"}
    r = _run(_compose(project, "down"), timeout=180)
    if r["code"] != 0:
        return {"error": ("compose down failed:\n" + r["out"])[-500:]}
    _bump()
    return {"ok": True}


def rebuild(project):
    """Build, then bounce — or stop at the env gate. In a thread: a build is
    minutes, and the poll watches it through job_rev."""
    if _job["running"]:
        return {"error": "a build is already running — one at a time"}
    if compose_file(project) is None:
        return {"error": "no compose file here"}
    # On disk before the work starts, so a restart can tell "this build never
    # finished" from "no build has been asked for". The job dict is memory and
    # dies with the container; this outlives it.
    with _lock:
        d = _load()
        d.setdefault(project, {})["building_since"] = int(time.time())
        write_json(FILE, d)
    _job.update(running=True, project=project, step="building", log="",
                error="", await_env=False)
    _bump()
    threading.Thread(target=_worker, args=(project,), daemon=True).start()
    return {"ok": True, "started": True}


def _clear_marker(project):
    """Drop the started-marker — the build reached an end, whichever end."""
    with _lock:
        d = _load()
        if project in d:
            d[project].pop("building_since", None)
            write_json(FILE, d)


def _worker(project):
    try:
        r = _run(_compose(project, "build"), timeout=3600,
                 env_extra=_dev_data_env(project) | _CLASSIC_BUILD)
        _job["log"] = r["out"][-2000:]
        if r["code"] != 0:
            _job.update(error="build failed — the tail of its output is below",
                        step="")
            return
        with _lock:
            d = _load()
            d.setdefault(project, {}).update(rev=_head(project),
                                             at=int(time.time()))
            write_json(FILE, d)
        _job["step"] = "stopping"
        _bump()
        _run(_compose(project, "down"), timeout=180)
        if missing_env(project):
            # The gate: new settings exist that the env does not answer.
            # Rewrite the env with the old values in comments and leave Up
            # to the operator — see the module docstring.
            _gate_env(project)
            with _lock:
                d = _load()
                d.setdefault(project, {})["await_env"] = True
                write_json(FILE, d)
            _job.update(await_env=True, step="")
            return
        _job["step"] = "starting"
        _bump()
        r = _run(_compose(project, "up", "-d"), timeout=180,
                 env_extra=_dev_data_env(project))
        if r["code"] != 0:
            _job.update(error=("up failed:\n" + r["out"])[-500:], step="")
            return
        _job["step"] = ""
    finally:
        # Whatever happened — built, failed, gated — the build is no longer in
        # flight, so the marker goes. Only a killed process leaves it behind,
        # which is exactly what it is for.
        _clear_marker(project)
        _job["running"] = False
        _bump()
