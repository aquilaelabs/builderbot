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
import json
import os
import re
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


# Every docker call this module makes is a compose call inside the project's
# own bbdev- namespace, plus one `docker version`. That is the whole of what
# keeps the blast radius to containers this dashboard created — and until this
# guard it was true only because every call site happened to go through
# _compose(). The socket proxy cannot help with it: its flags are per
# ENDPOINT, so CONTAINERS=1 is the entire /containers API for every container
# on the host, and no arrangement of them means "only ours".
#
# So the invariant is asserted at the one place every call passes through,
# which turns "the code always passes --project-name" into "the code cannot
# not". It says nothing about what a compose FILE asks for — see risks().
_BARE_OK = {"version"}


def _guard(argv):
    """The reason to refuse this argv, or "" to let it run."""
    if not argv or argv[0] != DOCKER:
        return ""                      # git, and anything else not docker
    verb = argv[1] if len(argv) > 1 else ""
    if verb in _BARE_OK:
        return ""
    if not verb:
        return "a bare `docker` with no subcommand"
    if verb != "compose":
        return f"`docker {verb}` — only compose and version are reachable here"
    try:
        name = argv[argv.index("--project-name") + 1]
    except (ValueError, IndexError):
        return "a compose call carrying no --project-name"
    if not name.startswith("bbdev-"):
        return f"a compose call outside the bbdev- namespace ({name})"
    return ""


def _run(argv, timeout=60, env_extra=None):
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
    for pair in (os.environ.get("DOCKER_HOST_PATHS") or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        here, _, there = pair.partition(":")
        here, there = here.rstrip("/"), there.strip().rstrip("/")
        if not here.startswith("/") or not there.startswith("/"):
            bad.append(f"{pair} is not a /container:/host pair")
            continue
        root = roots.get(here)
        if root is None:
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


def _dev_data_env(project):
    """BB_DEV_DATA for a compose that opts in with ${BB_DEV_DATA}/... —
    cache-backed volumes by convention, nothing forced on a compose that
    never mentions it.

    Handed over as the HOST's path, because the daemon that reads it is the
    host's. Unset when that is unknown: a compose referencing an unset
    variable fails loudly, and loudly is the whole improvement over mounting
    an empty directory in the host's RAM and calling it the cache drive.
    """
    root = Path(DEVDATA)
    if not root.is_dir():
        return {}
    d = root / _pname(project)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {}
    host = to_host(d)
    return {"BB_DEV_DATA": host} if host else {}


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


def _config(project):
    """The compose file as compose itself resolves it: variables substituted,
    relative paths made absolute against the project directory.

    None when it cannot be read, which every caller has to treat as the
    cautious answer rather than as "nothing here". Fetched once per poll
    because state() asks it two separate questions.
    """
    r = _run(_compose(project, "config", "--format", "json"), timeout=30)
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


def problems(project, cfg):
    """Paths this compose gives the daemon that the daemon will not find.

    A different thing from risks(): those are decisions the operator may
    reasonably make, this is a compose file that cannot work. Kept apart so
    the confirmation stays about the first kind — asking someone to confirm a
    configuration error teaches them to confirm without reading.

    Only OUR paths are judged. Anything else is taken for a host path, which
    it usually is and which nothing here can check anyway.
    """
    if cfg is None:
        return []
    mapping = host_map()[0]
    ours = [str(WORKSPACE), str(Path(DEVDATA))]
    out = []
    for name, sv in sorted(_services(cfg).items()):
        for src in _binds(sv, project):
            if not any(src == o or src.startswith(o + "/") for o in ours):
                continue
            there = to_host(src, mapping)
            out.append(
                f"{name} mounts {src}, which is this container's path — the "
                + (f"daemon is the host's and wants {there}" if there else
                   "daemon is the host's and has no such path; say where it "
                   "is with DOCKER_HOST_PATHS"))
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


def _risk_gate(project, ack=""):
    """The reason to stop before starting anything, or "" to go ahead."""
    rs = risks(project, _config(project))
    if not rs:
        return ""
    d = risk_digest(rs)
    if ((_load().get(project) or {}).get("risks_ack")) == d:
        return ""
    if ack and ack == d:
        with _lock:
            store = _load()
            store.setdefault(project, {})["risks_ack"] = d
            write_json(FILE, store)
        return ""
    return ("this compose asks for more than its own directory — "
            + "; ".join(rs[:3]) + (" …" if len(rs) > 3 else ""))


def _running(project):
    r = _run(_compose(project, "ps", "--status", "running", "-q"), timeout=20)
    return r["code"] == 0 and bool(r["out"].strip())


def _exists(project):
    """Does compose know about any container here, running or not?

    A container that EXITED — a crash, a bad entrypoint, an OOM — is still
    there, still holding its name and the project's network, and `down` is the
    only thing that clears it. Asking only about RUNNING containers is what
    left a crashed instance with a greyed-out Down and no way out of the
    dashboard at all.
    """
    r = _run(_compose(project, "ps", "-aq"), timeout=20)
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
           # The compose project name, which is what actually namespaces the
           # containers, the network and the volumes. Not the container name:
           # a compose file may set container_name to anything it likes, and
           # there may be several. This is the one name that is always true.
           "name": _pname(project),
           "needs_build": True,
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
        cfg = _config(project)
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
        out["running"] = _running(project)
        # Only worth a second call when nothing is running: a running stack
        # self-evidently has containers, and this is on the artifacts poll.
        out["exists"] = out["running"] or _exists(project)
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

def up(project, ack=""):
    if _job["running"]:
        return {"error": "a build is already running — one at a time"}
    gate = _risk_gate(project, ack)
    if gate:
        return {"error": gate}
    miss = missing_env(project)
    if miss:
        return {"error": "the env is missing " + ", ".join(miss[:4])
                         + (" …" if len(miss) > 4 else "")
                         + " — fill it in first (Env)"}

    # `compose up -d`, and nothing more clever: compose builds an image that
    # is missing, so Up on a never-built project does what the CLI does
    # rather than refusing on a rule of this dashboard's invention. The
    # classic builder rides along for exactly that case — an implicit build
    # through buildx would 403 against a socket proxy.
    r = _run(_compose(project, "up", "-d"), timeout=1800,
             env_extra=_dev_data_env(project) | _CLASSIC_BUILD)
    if r["code"] != 0:
        return {"error": ("compose up failed:\n" + r["out"])[-500:]}
    with _lock:
        d = _load()
        row = d.setdefault(project, {})
        row.pop("await_env", None)
        # An implicit build is still a build, so the row stops claiming the
        # project was never built while a container from it is running.
        if not row.get("rev"):
            row.update(rev=_head(project), at=int(time.time()))
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


def rebuild(project, ack=""):
    """Build, then bounce — or stop at the env gate. In a thread: a build is
    minutes, and the poll watches it through job_rev."""
    if _job["running"]:
        return {"error": "a build is already running — one at a time"}
    if compose_file(project) is None:
        return {"error": "no compose file here"}
    # Before the build, not before the `up` inside it: a build runs this
    # project's Dockerfile, which is the same trust either way.
    gate = _risk_gate(project, ack)
    if gate:
        return {"error": gate}
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
