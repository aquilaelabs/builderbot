#!/usr/bin/env python3
"""A project's dev instance: built here, run here, controlled from the Containers page.

The question this answers used to be a GitHub Actions bill: a private
project's image was built on hosted minutes and pulled back to the same box
that could have built it. Now the box builds it, running `docker compose
build` against the project's own compose file, and the Containers page carries the
controls, one row per instance: Up, Down, Env, Rebuild, Remove. The project's
Artifacts view keeps the row that sends it there in the first place.

**Where docker actually is.** Not in this container, and not on this box: the
daemon belongs to a sandbox VM, a node the operator enrolled with a token,
whose address the node itself reports on every dial-in. That machine's only job
is running Docker. It holds no container anybody minds losing and has no route to the
server's, which is what makes build+run+bind-mounts (root-shaped power
wherever it lands) an acceptable thing to put behind a dashboard button.

That is the boundary. What is left in here bounds the SHAPE of what gets sent
rather than what it may reach: _guard() lets through table-lookup compose
commands, two reads, and three one-shot runs rebuilt argv-for-argv, so a bug
in a caller cannot become a freeform docker call. risks() answers the half no
check on a command can: a compose FILE saying `privileged: true` and mounting
/ is an ordinary-looking file, so it is read and what it reaches for is named
on the row and confirmed once per set before anything starts.

**What "rebuild needs the env filled in" means.** The one detectable signal:
the repo's .env.example gained keys the dev env file does not have. A rebuild
that hits that stops after `down`, rewrites the env file as the new example
with the old values preserved in comments, and leaves Up for the operator:
starting a service against an env it is known to be missing would just be a
crash with extra steps.

**BuilderBot itself is NOT excluded**, and the reason is worth a line: its
dev instance is a second container from the same compose file, on another
machine, so building or bouncing it never touches the container this dashboard
is running in, whose lifecycle belongs to Unraid. The first cut excluded it on
a stale argument (replacing the running container kills the builder
mid-flight, which is true and not what this does). Expect `up` to refuse while
the real instance holds the same host ports; that refusal is compose saying
so, and the env file is where a second instance gets different ones. A dev
build shows `unstamped` for its version, which is honest: it is one.

State: /config/devapps.json ({project: built_rev/built_at}), the env files in
/config/devenv/, one build job at a time in memory.

Since 25 Sep this file is the BASE: the store, the node block, the docker
runner, the compose-file readers, the risks and the env files. The layer that
runs and reports an instance (up, down, rebuild, test, remove, state, the
job runners and act) is devactions.py, and the containers BuilderBot did not
build are containers.py; both import this module, which knows neither.
"""
import contextlib
import functools
import hashlib
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

# The request's timing parts (server.py's trace), where there is a request:
# a suite or a verb loads this file by its path, outside the dashboard's
# directory, and times nothing.
try:
    import timing
    _timed = timing.timed
except ImportError:
    def _timed(name):
        return contextlib.nullcontext()

WORKSPACE = None
STATE = None
FILE = None
OWNERS = None
node_for = None
node_addr = None
ENVDIR = None
write_json = None
field = None                     # server.py's one-string-field reader, for act()
# Why a container of a project on a node cannot be given that node's NVIDIA
# card, or "": server.py's, which knows the node's switch, the project's
# setting and what the node's Toolchains tab holds (R102).
gpu_why = None
room_why = None         # set by server.py: (node id) -> why a build there would run out of disk, or "" (R110)
container_mem_gb = None  # set by server.py: () -> the memory limit in GB a container with none gets, 0 for none (R110)

DOCKER = os.environ.get("BB_DOCKER_BIN", "docker")

# The instance a project has always had, before instances were a thing. Every
# call that does not name one means this, which is what keeps the migration
# from being visible anywhere but here.
# What a session is told when its project's dial (Agents may: Run its
# container) says deny, wherever the refusal is made.
RUN_DENIED = ("running this project's containers is the operator's: rebuilding, "
              "starting and stopping them, changing their env, creating one and removing "
              "one are handed over in the project's settings, Agents may: Run its container")

MAIN = "main"
# The owner of a container BuilderBot deploys itself (R180): the nginx tab's
# container is the one today. Set by the deployment that writes it and by
# nothing else, not a person's picker and not a session, and given every
# bridge and every published port on its node by the containers' network
# map, since a proxy or a monitor that is nobody's has to see everybody's.
SYSTEM = "System"


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")

# Where a dev instance's data lives when the node addressed reports no
# appdata store. It is a STORE, reported per node with its path and its
# headroom and edited on the node's own Storage section (R17 step 2), because
# where a node keeps a container's databases is a fact about that node; this
# is the answer for a node that has not said, and BB_DEV_DATA_DIR is how the
# test harness points it at a scratch directory.
DEVDATA = os.environ.get("BB_DEV_DATA_DIR", "/devdata")
# Injected rather than worked out here: three readers already answer "where do
# the logs live" and a fourth copy of that rule is how they drift. None when
# nothing injected one: `bb doctor` loads this module on its own to ask
# available(), and a probe should not start writing files.
log_dir = None
project_node = None   # the project's own node, from prefs (docs/nodes.md §13)
node_reported = None  # a node's reported facts by id (nodes.node), for BB_DOCKER_GID
project_nodes = None  # ...and the set it works on, primary first (R82)
all_project_nodes = None  # () -> {project: [node ids]}, every project's set
reads_of = None           # project -> [projects it reads] (prefs.reads), set by the server
hosts_of = None           # project -> [node ids it hosts its containers on] (prefs hosts), set by the server
reaches_of = None         # (project, node) -> ["ADDR" or "ADDR:PORT"] its sessions there may reach (prefs.reaches_on)
node_paths = None     # a node's path mapping, from its record (docs/nodes.md §11)

# The daemon is a sandbox VM and nothing else. The node record names the
# machine; ssh:// and the bb account provision-linux.sh makes are filled in, so an
# address of any other kind turns the feature off with the reason on it rather
# than half-working.
#
# One arrangement because the boundary is the machine: reached over ssh with a
# key BuilderBot cannot read, holding nothing anybody minds losing. Aim the
# same feature at a daemon worth protecting and it needs a filter in front of
# it, and a filter that can be got wrong is not a boundary.


# The account nodes/provision-linux.sh makes on the sandbox VM. Assumed rather than
# asked for, because there is one provisioner and it makes one user: a setting
# whose only correct value is known is a way to get it wrong.
DEFAULT_USER = "bb"


# Which node's daemon the current thread is talking to. A thread-local rather
# than a parameter, because the address is read at the BOTTOM (_run, _guard,
# daemon_id, source()) and threading it down through every call site would put
# a `node=` on forty functions to serve the three entry points that actually
# choose one. Entry points wrap themselves in on_node(); everything below asks
# docker_host() exactly as it always has and gets the right answer.
_node_ctx = threading.local()


@contextlib.contextmanager
def on_node(node_id):
    """Address every docker call in this block at `node_id`'s daemon."""
    prev = getattr(_node_ctx, "addr", None)
    prev_id = getattr(_node_ctx, "node", None)
    _node_ctx.addr = node_addr(node_id) if node_addr and node_id else None
    _node_ctx.node = node_id or None
    try:
        yield
    finally:
        _node_ctx.addr = prev
        _node_ctx.node = prev_id


def _default_node():
    return node_for() if node_for else ""


def _instance_node(project, instance):
    """The node an instance is bound to: its record's, else the project's
    own node (one setting for everything a project does on a node), else
    nothing.

    Nothing, not a default: there is no primary docker manager (the
    operator, 25 Sep). An instance whose record names no node and whose
    project has none has no daemon, and everything that reaches for one
    says so rather than landing on whichever node was enrolled last.
    """
    nid = _read_rec(project, instance).get("node") or ""
    if not nid and project_node:
        nid = project_node(project) or ""
    if not nid and project_node is None and project_nodes is None and node_for:
        # No controller wiring (a probe, a test driving this in process): no
        # projects' settings to read, so the one daemon node_for names is
        # the arrangement, as it was before nodes had settings at all.
        nid = node_for() or ""
    return nid


def project_daemon(project):
    """The node THIS project works on: its own, or "" for none.

    Which is where its session runs (a project with no node keeps its session
    on the controller), and where a new instance of it would be built. The
    same chain _instance_node ends with, minus the record, so "is this
    instance on the machine this project works on" is one comparison.
    """
    return (project_node(project) if project_node else "") or ""


def instance_node(project, instance):
    """Which node an instance is on, for a caller outside this module.

    _instance_node is the rule; this is the name the server asks by, so the
    fallback chain (the record's node, else the project's, else the default
    docker host) stays written down in exactly one place.
    """
    return _instance_node(project, instance or only_instance(project))


def pin_to_current_node(project):
    """Fix this project's built instances to the node they are on, before the
    project's node setting moves them somewhere they do not exist.

    An instance with no node of its own follows the project's, which
    _instance_node above is the whole of. So changing that setting pointed the
    manager at a daemon holding none of this instance's containers, image or
    data directory. The containers on the old node kept running, which is
    right, and went invisible, which is not: the row that could stop or remove
    them had moved, so the one control for the thing still running was gone.

    Pinned at the moment the setting changes rather than worked out later, for
    the same reason _stamp writes a build's ref: afterwards nothing is left to
    say which node it meant.

    Only instances that have been BUILT somewhere. A record that is settings
    and nothing else has nothing on any daemon to strand, and belongs on
    whichever node the project is moving to.

    Returns the names pinned, oldest record first, for the caller to say so.
    """
    # What a record with no node of its own resolves to today, which is what
    # it is about to stop resolving to. Read once: every record here answers
    # the same way, by definition of having no node.
    here = project_daemon(project)
    if not here:
        return []
    pinned = []
    with _lock:
        d = _load()
        for name, rec in (d.get(project) or {}).items():
            if rec.get("node") or not rec.get("at"):
                continue
            _rec(d, project, name)["node"] = here
            pinned.append(name)
        if pinned:
            write_json(FILE, d)
    if pinned:
        _bump()
    return pinned


def _on_instance(fn):
    """Route a per-instance entry point at the daemon its instance is bound
    to. The decorator is the whole multi-host story for actions: the body
    stays exactly the single-daemon code it always was, and docker_host()
    answers with the right address underneath it."""
    @functools.wraps(fn)
    def wrapped(project, instance=MAIN, *a, **kw):
        with on_node(_instance_node(project, instance)):
            return fn(project, instance, *a, **kw)
    return wrapped


def docker_host():
    """The daemon the current call should talk to, as docker wants it
    addressed. Empty when there is none.

    Three sources, in order: the node context an entry point opened (the
    multi-host path), the environment (the arrangement that predates nodes,
    kept working untouched), nothing. The operator writes the machine, say
    `10.0.0.9`, and the scheme and the account are filled in; what is not
    allowed is a different KIND of address, which available() refuses by name
    rather than by handing docker something it will fail on obscurely.
    """
    # The node being addressed, and nothing else. DOCKER_HOST used to be the
    # fallback; it went with the ssh kind (roadmap #18), so a daemon this
    # container talks to is one somebody enrolled rather than one an
    # environment variable named.
    addr = (getattr(_node_ctx, "addr", None) or "").strip()
    if not addr:
        return ""
    scheme, sep, rest = addr.partition("://")
    if sep and scheme.lower() != "ssh":
        return addr                       # not ssh: available() says so
    host = rest if sep else addr
    return "ssh://" + (host if "@" in host else f"{DEFAULT_USER}@{host}")


# What nodes/provision-linux.sh stamps on the daemon it set up: a label in
# /etc/docker/daemon.json. Docker reports its own labels on `docker info`, so
# the check costs one read over the connection already being used: no second
# channel, no file to fetch, nothing on the VM to keep in step but the
# provisioner.
#
# It exists because "a machine that answers Docker on ssh" is not the same
# thing as "the sandbox". Everything the manager does beyond compose runs as
# root on the far side, and the whole reason that is safe is that the far side
# is a box whose job is being wrecked and reset. Pointed at a NAS, a
# workstation or the server itself, the same buttons are a different act.
SANDBOX_LABEL = "builderbot.sandbox"


def daemon_info():
    """The daemon's labels and its own id, or an error.

    One `docker info`, formatted to a single line: its Labels (where the
    provisioner's stamp is) and ID (which distinguishes two VMs that have worn
    the same address).
    """
    r = _run([DOCKER, "info", "--format",
              "{{json .}}"], timeout=15)
    if r["code"] != 0:
        return {"error": (r["out"] or "no daemon").strip()[:160]}
    try:
        d = json.loads(r["out"])
    except ValueError:
        return {"error": "docker info did not answer with JSON"}
    labels = d.get("Labels") or []
    if not isinstance(labels, list):
        labels = []
    return {"labels": [str(x) for x in labels], "id": str(d.get("ID") or "")}


def is_sandbox(labels):
    """Whether these daemon labels carry the provisioner's stamp."""
    return any(str(x).split("=")[0].strip() == SANDBOX_LABEL for x in labels)


def adopt(uid):
    """Make the daemon now answering the one the records are about.

    Two VMs can wear one address (a rebuilt sandbox, or a second machine given
    the old one's IP) and the address alone cannot tell them apart, so what a
    build was recorded against is checked by the daemon's OWN id as well. When
    it turns out to be a different machine, everything claiming a build on the
    old one is cleared: the rev, its date, the env gate a build tripped. The
    instance itself stays, because its compose file and its env are this side's
    and have nothing to do with which daemon is plugged in.

    The point is that "unknown" is a state to leave, not to live in. A manager
    pointed at a new VM should say what THIS daemon has, and rows quoting a
    build from a machine no longer in play are neither true nor unknown: they
    are the last one's answers, and clearing them is what makes the new one the
    source of truth.
    """
    if not uid:
        return
    here = daemon_id()
    with _lock:
        d = _load()
        moved = False
        for insts in d.values():
            for rec in insts.values():
                if not isinstance(rec, dict) or not rec.get("rev"):
                    continue
                # Only records about THIS address are this verification's
                # business. With one daemon that distinction did not exist;
                # with several, clearing another node's records because this
                # one answered would be the bug this function exists to stop,
                # pointed the other way.
                if rec.get("daemon") != here:
                    continue
                was = rec.get("daemon_uid")
                # An old record predating the uid is judged on its address, as
                # it always was: not knowing is not evidence of a move.
                if not was:
                    rec["daemon_uid"] = uid
                    moved = True
                elif was != uid:
                    for k in ("rev", "at", "await_env", "building_since",
                              "daemon", "daemon_uid"):
                        rec.pop(k, None)
                    moved = True
        if moved:
            write_json(FILE, d)
    if moved:
        _bump()


def daemon_id():
    """A stable name for the daemon a build landed on.

    The resolved address, so that filling the account in does not read as a
    different machine and invalidate every build that landed on it. What does
    invalidate one is the operator pointing this at another VM.
    """
    return docker_host().lower() or "none"


COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml",
                 "compose.yml", "compose.yaml")

_lock = threading.Lock()
# The store's own revision, folded into job_rev() beside the queue's: an
# instance added or an env file written moves the poll's token without a
# job. Bumped by _bump() on every mutation of /config/devapps.json.
_rev = 0

# The compose actions are JOBS on the queue (docs/nodes.md §2, phase 4): up,
# down, rebuild and remove each queue one "compose" job placed on the node the
# instance is bound to, and the runner below executes it with the node's
# daemon addressed. What that replaced was a module-global one-slot job dict
# that held the whole dashboard to one build at a time and died with the
# process; the row now reads its job from the store, a second instance's
# build waits its turn instead of being refused, and a build BuilderBot
# restarted under is failed as lost with that written on it. `queue` is
# nodes.py, bound by configure(); without one (a module test) the actions
# refuse rather than invent a job.
queue = None
runner = None                    # jobs.py, for Abort to reach the process

# How much of a long command's output the row carries. A pull writes a line
# per layer per progress tick, so this is a tail and not a transcript.


def work_tree(project, instance):
    """Where an instance pinned to a REF is built from, or None.

    A git worktree beside the project on the share, in the same
    `<project>-<something>` shape a second person's session already uses, so
    the projects list knows what it is looking at (and it carries a .bbignore
    besides). A worktree rather than a checkout, because the tree is shared:
    switching the project's own branch to look at a build moves it under every
    session and every person on it, and the Git view refuses that outright
    while somebody's session is standing in the directory.
    """
    ref = str(_read_rec(project, instance).get("ref") or "").strip()
    if not ref:
        return None
    return WORKSPACE / f"{_slug(project)}-{_slug(instance)}-build"


# ---------------------------------------------------------------------------
# the route (docs/nodes.md §7, phase 8)
#
# A deployment is an instance up on a node plus a ROUTE: how somebody reaches
# it. The record is uniform ({mode, port, url}) and the modes are tiers of
# one thing: `lan` is a published port on the node's LAN address, which is
# what the manager always offered; `funnel` is Tailscale Funnel on the node,
# a public HTTPS URL with no DNS or certificate to arrange, applied by the
# agent as a system job; `public` is the reverse-proxy mode the record is
# shaped for and this does not build. The traffic never transits the
# controller in any mode, which is what keeps every one of them cheap.

ROUTE_MODES = ("lan", "funnel", "public")


def _published(ports, local=False):
    """The published TCP ports of an instance, from either shape the two
    listings use: "7475->7474/tcp" or "127.0.0.1:7475->7474/tcp" strings,
    or {published, proto} dicts. With `local`, the ones bound to the
    loopback alone (R190), which no address of the node's reaches."""
    out, loop = [], []
    for p in ports or []:
        if isinstance(p, dict):
            if str(p.get("proto", "tcp")).lower() == "tcp" and str(p.get("published") or "").isdigit():
                (loop if str(p.get("host_ip") or "").startswith("127.") else out).append(int(p["published"]))
        elif isinstance(p, str) and "->" in p and p.endswith("/tcp"):
            head = p.split("->", 1)[0]
            bind, _, num = head.rpartition(":")
            if num.isdigit():
                (loop if bind.startswith("127.") or bind == "localhost" else out).append(int(num))
    return sorted(set(loop)) if local else sorted(set(out) | set(loop))


def route_view(project, instance, ports, prefer=None):
    """The instance's route as the row draws it: the mode and port on the
    record (lan on the first published port when nothing was chosen), the
    URL that follows from the node, and whether a funnel is actually up."""
    rec = _read_rec(project, instance)
    r = rec.get("route") if isinstance(rec.get("route"), dict) else {}
    mode = r.get("mode") if r.get("mode") in ROUTE_MODES else "lan"
    pub = _published(ports)
    liked = _published(prefer or [])
    port = (r.get("port") if isinstance(r.get("port"), int) and r.get("port") > 0
            else liked[0] if liked else pub[0] if pub else None)
    nid = _instance_node(project, instance)
    n = queue.node(nid) if queue is not None and nid else None
    out = {"mode": mode, "port": port, "ports": pub, "url": "", "ready": False, "why": "",
           "funnel_ok": False}
    if n:
        ts = ((n.get("reported") or {}).get("services") or {}).get("tailscale") or {}
        out["funnel_ok"] = bool(n["kind"] == "agent" and ts.get("installed")
                                and (n.get("reported") or {}).get("sandbox"))
    if mode == "lan":
        host = queue.route_host(nid) if queue is not None and nid else ""
        # A port bound to the loopback alone (R190) has no address of the
        # node's to be reached at: the node's nginx is what answers for it.
        if port in _published(ports, local=True) and port not in _published([p for p in ports or [] if not (
                isinstance(p, str) and p.split("->", 1)[0].rpartition(":")[0].startswith("127."))]):
            out["why"] = f"published on the node alone (127.0.0.1:{port}): its nginx answers for it"
        elif host and port:
            out["url"] = f"http://{host}:{port}/"
            out["ready"] = port in pub
        if not out["url"] and not out["why"]:
            out["why"] = "no published port" if not port else "no node address"
    elif mode == "funnel":
        ts = (((n or {}).get("reported") or {}).get("services") or {}).get("tailscale") or {}
        dns = ts.get("dns") or ""
        fwd = (ts.get("funnel") or {}).get("443")
        if dns:
            out["url"] = f"https://{dns}/"
        out["ready"] = bool(dns and port and fwd == port)
        out["why"] = ("" if out["ready"] else
                      "the node reports no tailscale" if not ts.get("installed") else
                      f"the node's funnel forwards to {fwd}, not {port}" if fwd and fwd != port else
                      "asked for; waiting for the node to report it")
    else:
        out["why"] = "public is not built; the record is shaped for it (docs/nodes.md §7)"
    return out


def job_why(j):
    """How a compose job ended, in words: a failed one whose reason is only
    its exit code says what its log says instead, as the Jobs page shows it
    (B96: a Rebuild whose image could not be pulled read 'exit 1' on its
    row, and why was only in the Jobs page's output)."""
    err = str(j.get("error") or "")
    if j.get("state") != "failed" or not re.fullmatch(r"\s*(exit \d+)?\s*", err):
        return err
    try:
        why = queue.failed_why(j["id"]) if hasattr(queue, "failed_why") else ""
    except Exception:  # a row is drawn without it, never refused
        why = ""
    if not why or why.strip() == err.strip():
        return err or "failed"
    return f"{why} ({err.strip()})" if err.strip() else why


def job_view(project, instance):
    """This instance's job as the row draws it: the one in flight, or the
    last one while it has something to say about how it ended. A job that
    succeeded is not news, so it is not shown; a failed or stopped one stays
    on the row until the next job on the instance replaces it."""
    if queue is None:
        return None
    for j in queue.jobs_for(project=project, type="compose", n=40):
        if (j.get("spec") or {}).get("instance", MAIN) != instance:
            continue
        running = j["state"] in queue.JOB_ACTIVE
        if not running and j["state"] == "succeeded":
            return None
        return {"id": j["id"], "running": running, "state": j["state"],
                "project": project, "instance": instance,
                "action": (j.get("spec") or {}).get("action", ""),
                "step": ("queued" if j["state"] == "queued" else j["step"])
                        if running else "",
                "error": "" if running else job_why(j),
                "aborting": bool(running and j["cancel"]),
                "node": j["node"]}
    return None


def latest_job():
    """The manager's one job line: the newest compose job that is in flight
    or ended badly, across every instance."""
    if queue is None:
        return None
    for j in queue.jobs_for(type="compose", n=1):
        sp = j.get("spec") or {}
        if j["state"] != "succeeded":
            return job_view(sp.get("project", ""), sp.get("instance", MAIN))
    return None


def configure(*, workspace, state, write_json, log_dir=None, node_for=None,
              node_addr=None, queue=None, runner=None, project_node=None, project_nodes=None,
              node_paths=None, field=None, node_reported=None):
    globals().update(WORKSPACE=Path(workspace), STATE=Path(state), node_reported=node_reported,
                     write_json=write_json, log_dir=log_dir, field=field,
                     node_for=node_for, node_addr=node_addr, project_node=project_node,
                     project_nodes=project_nodes,
                     node_paths=node_paths,
                     queue=queue, runner=runner)
    # The compose runner itself is devactions', registered by its own
    # configure(): this module is the base that layer stands on and does not
    # know it exists (25 Sep).
    globals()["FILE"] = Path(state) / "devapps.json"
    globals()["OWNERS"] = Path(state) / "docker-owners.json"
    globals()["ENVDIR"] = Path(state) / "devenv"


def job_rev():
    """The poll's cheap tell that something here moved: the store, and the
    queue's own rev, since a job's every log chunk is a repaint."""
    # The state-only rev: a row draws a job's state, step and how it ended,
    # never its output, so a line of output is not a reason to redraw.
    q = queue.jobs_state_rev() if queue is not None else 0
    return f"{_rev}:{q}:{_mtime(FILE)}"


def _mtime(p):
    try:
        return int(Path(p).stat().st_mtime_ns)
    except OSError:
        return 0


def _bump():
    global _rev
    _rev += 1


def _learn_host_key(addr):
    """Meet a node's ssh host key once, when that is the only thing in the way.

    `docker -H ssh://…` shells out to ssh, and ssh run non-interactively
    REFUSES an unknown host rather than asking, so a node the controller has
    never ssh'd to fails with "Host key verification failed" and every Docker
    control on the tab grays out. The documented cure was a person running
    ssh-keyscan on the controller, which R47 took away with sessions: there
    is no session here to run it in any more.

    So it is done here, on the failure, and only on the first meeting. The
    address came from the node's own authenticated dial-in, and a scan trusts
    whatever answers at it, which is exactly the exposure the manual step
    always had, no more. What is NOT done is replacing a key that CHANGED:
    that is a rebuilt VM or something worth looking at, and quietly accepting
    it would throw away the one thing host keys are for. Returns "learned",
    "changed" or "".
    """
    host = addr.split("://", 1)[-1].split("@")[-1].strip()
    port = "22"
    if host.count(":") == 1:
        host, port = host.rsplit(":", 1)
    if not host:
        return ""
    kh = Path(os.path.expanduser("~/.ssh/known_hosts"))
    try:
        seen = subprocess.run(["ssh-keygen", "-F", host, "-f", str(kh)],
                              capture_output=True, text=True, timeout=10, check=False)
        if seen.returncode == 0 and seen.stdout.strip():
            return "changed"
        scan = subprocess.run(["ssh-keyscan", "-T", "5", "-p", port, host],
                              capture_output=True, text=True, timeout=20, check=False)
        lines = [ln for ln in (scan.stdout or "").splitlines() if ln and not ln.startswith("#")]
        if not lines:
            return ""
        kh.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(kh, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(kh, 0o600)
    except (OSError, subprocess.SubprocessError):
        return ""
    _docker_log(f"learned the host key for {host}")
    return "learned"


def _why_not(out):
    """The REASON out of a failed docker call, which docker buries.

    Its connect error leads with the URL it tried and the whole ssh command
    line, and puts what actually went wrong at the very end after `stderr=`:

        error during connect: Get "http://docker.example.com/v1.56/version":
        command [ssh -l bb …] has exited with exit status 255, make sure the
        URL is valid … : stderr=ssh: connect to host 10.0.0.9 port 22: No
        route to host

    Cut to 120 characters from the FRONT, as this was, the row said "command
    [ssh -l bb -o ConnectTimeout=30 -T -- 10.0.0" and stopped: the operator
    was shown the part they already knew and none of the part that says what
    to fix. So the tail is what survives, and ssh's own words win outright
    when they are there.
    """
    s = " ".join((out or "").split())
    if not s:
        return "no daemon"
    if "stderr=" in s:
        s = s.split("stderr=")[-1].strip() or s
    return s if len(s) <= 200 else "…" + s[-200:]


def source():
    """The daemon being talked to, for the manager to name on the page.

    `strays` is the only judgement in here: a path-mapping pair naming a
    path this container does not have is a statement about the other machine
    that nothing on this side will ever act on. Harmless, and worth saying
    once rather than sitting in the setting looking like it does something.
    """
    addr = docker_host()
    # Named for what it IS, not for what it was meant to be: calling a tcp://
    # address "the sandbox VM" and then refusing it as not one, in the same
    # sentence, is how a status line stops being read. An agent node's
    # daemon is reached through its agent and nothing dials the address on
    # its record, so that one is named by the node (B264).
    n = _agent_here()
    kind = (n["name"] if n
            else "the sandbox VM" if addr.startswith("ssh://")
            else "an unsupported daemon" if addr else "")
    return {"kind": kind, "where": addr, "agent": bool(n),
            # WHICH node this answer is about, because the page cannot tell.
            # The status poll carries ONE daemon's verdict (the default
            # node's) and the manager may be looking at another, so a page
            # that cannot match the two applies the default node's absence to
            # every node there is. B109, which was fixed on the client by
            # comparing this id and then shipped with nothing setting it, so
            # the comparison quietly fell back to "yes, that is us" and the
            # bug came back whole.
            "node": getattr(_node_ctx, "node", None) or _default_node(),
            "strays": stray_map_entries(host_map()[0])}


def _agent_here():
    """The node these docker calls are addressed at, when it is an AGENT node
    whose agent is dialing in, else None.

    THE WHOLE OF B111 IS THIS DISTINCTION. On an agent node nothing about
    compose goes over ssh: _submit sends the entire plan to the agent and the
    agent runs it against that machine's own local docker socket. So the
    controller's ssh is the wrong question to judge the page by, and asking it
    is how a node the controller cannot ssh to had its Up, Down, Rebuild and
    Send ghosted while every one of them would have worked.

    A node with no agent keeps the ssh path below, which is the only way into
    one.
    """
    nid = getattr(_node_ctx, "node", None)
    if not nid or queue is None:
        return None
    n = queue.node(nid)
    return n if n and n.get("kind") == "agent" else None


# What each agent node last answered to a bare docker read, kept until an
# action on that node ends. It stands in while the node is on a job: a
# probe queued behind a build would wait the build out, and the row asking
# would hang with it.
_last_reads = {}
_reads_lock = threading.Lock()
# One answer per question per REQUEST, never per time: state() asks about
# running and existing per instance and the manager asks once for the page,
# and each ask is a job on the node, so a fetch that opened a scope costs
# one probe. A memo that outlived the request made an explicit Refresh
# return what the read before it saw.
_scope = threading.local()


@contextlib.contextmanager
def read_scope():
    """Share every bare docker read made inside the block. Opened by the
    entry points that answer one fetch (overview, the Artifacts payload)
    and by nothing that acts."""
    fresh = getattr(_scope, "reads", None) is None
    if fresh:
        _scope.reads = {}
    try:
        yield
    finally:
        if fresh:
            _scope.reads = None


def _forget_reads(node_id):
    """Drop what a node last answered: an action just changed it."""
    with _reads_lock:
        for k in [k for k in _last_reads if k[0] == node_id]:
            del _last_reads[k]


def _agent_exec(n, argv, timeout):
    """One docker verb on one container, run on the agent node as a probe
    job the Jobs page never keeps, in _run's own {"code", "out"} shape. Not
    _agent_read: a start is not a read, so nothing is memoised and a busy
    node is not answered from what it said before."""
    _docker_log("$ " + " ".join(argv) + f"   (on {n['name']})")
    r = queue.run_wait("dashboard", n["id"], argv, timeout=min(int(timeout), 25),
                       forget=True)
    out = ({"code": 1, "out": r["error"]} if r.get("error")
           else {"code": int(r.get("code") or 0), "out": r.get("out") or ""})
    _docker_result(argv, out["code"], out["out"])
    return out


def _agent_read(n, argv, timeout):
    """One bare docker read, run on the agent node as a probe job the Jobs
    tab never keeps, in _run's own {"code", "out"} shape."""
    key = (n["id"], tuple(argv))
    memo = getattr(_scope, "reads", None)
    if memo is not None and key in memo:
        return dict(memo[key])
    # Asked every time, busy or not (the operator, 11 Oct: the tab read
    # "down, as last seen" whenever anything ran on the node, which on a
    # shared node is most of the time, and through every change made from
    # it, since the change is itself a job). A short exec goes on the light
    # lane whatever else is running (nodes.job_next), so a busy node answers
    # it; what was kept stands in, marked stale, only when the node did not
    # answer at all.
    _docker_log("$ " + " ".join(argv) + f"   (on {n['name']})")
    r = queue.run_wait("dashboard", n["id"], argv, timeout=min(int(timeout), 25),
                       forget=True)
    if r.get("error"):
        with _reads_lock:
            hit = _last_reads.get(key)
        if hit is not None:
            out = dict(hit) | {"stale": True}
            if memo is not None:
                memo[key] = out
            return out
        out = {"code": 1, "out": r["error"]}
    else:
        out = {"code": int(r.get("code") or 0), "out": r.get("out") or ""}
    _docker_result(argv, out["code"], out["out"])
    with _reads_lock:
        _last_reads[key] = out
    if memo is not None:
        memo[key] = out
    return out


def _agent_instance_containers(n, project, instance, running_only):
    """The containers of one instance on an agent node, from the node's own
    listing: `compose ps` names the compose file by a path on THIS side,
    and on an agent node the daemon is on the other, so the answer comes
    from `docker ps` filtered by the compose project label, which is how
    the manager's overview already tells instances apart."""
    got = containers()
    if got.get("error"):
        return None
    pn = _pname(project, instance)
    mine = [c for c in got["containers"] if c["project"] == pn]
    if running_only:
        mine = [c for c in mine if c["state"] == "running"]
    return mine


def _no_daemon_why():
    """Why there is no daemon to send docker work to, said for this install
    (B147): nodes enrolled that run no Docker want Docker, not another node,
    and an install that holds enrolling off is not told to enroll."""
    enrolled = [n["name"] for n in (queue.node_list() if queue else [])
                if n.get("kind") != "local" and n.get("state") not in ("retired", "pending")]
    if enrolled:
        return (f"no node runs Docker that docker work can be sent to ({', '.join(enrolled[:3])}"
                f"{' and more' if len(enrolled) > 3 else ''}): install Docker on one, "
                "or enroll one that has it on the Nodes page")
    try:
        import featuresoff
        held = featuresoff.sentences().get("enroll")
    except ImportError:
        held = None
    if held:
        return f"no node with a daemon here. {held}"
    return ("no node with a daemon yet: enroll one on the Nodes page (Enroll node "
            "mints a token, then provision-linux.sh on the machine); see docs/sandbox-vm.md")


def _available_agent(n):
    """Whether an agent node can run compose, from what it says about itself.

    Two facts, both already in its census and neither of them ours to probe:
    `docker` is the server version that node's own `docker version` printed,
    which is exactly "can the agent run compose here", and `sandbox` is the
    provisioner's stamp, the same thing the label check below reads over ssh,
    asked on the machine that carries it.

    Nothing is run. That matters: this sits on the status poll's path, which
    walks it for the default node every fifteen seconds, so a probe here would
    be a job on that node around the clock.

    The agent DIALING IN is the first of the two, and the honest one: a job is
    how everything here reaches that machine, and job_add refuses one on a
    node whose agent is quiet. Probing its docker over ssh to answer a
    question the ssh has no part in was the whole mistake.

    The daemon's own id comes with them, from the same census. It is how two
    VMs wearing one address are told apart (adopt), and the census is the
    only place it is read from: never `docker info` over ssh. A node whose
    docker does not answer sends none, and a record with no id is judged on
    its address alone, which is documented as safe.
    """
    if not n.get("live"):
        return {"on": False,
                "why": f"{n['name']}'s agent is not dialing in, and everything "
                       "here runs as a job on it, so nothing can until it "
                       "does. The Nodes page says when it was last seen"} | source()
    rep = n.get("reported") or {}
    if not rep:
        return {"on": False,
                "why": f"{n['name']} has not said what it carries yet; its "
                       "agent dials in every few seconds, so this answers "
                       "itself shortly"} | source()
    if not rep.get("docker"):
        return {"on": False,
                "why": f"docker does not answer on {n['name']}: its agent "
                       "reports no daemon there. Install docker on that "
                       "machine, or check the agent's account is in its "
                       "docker group"} | source()
    if not rep.get("sandbox"):
        return {"on": False,
                "why": f"{n['name']} is not a BuilderBot sandbox: it does "
                       "not report the provisioner's stamp, and a container "
                       "here runs as root on that machine. Run "
                       "nodes/provision-linux.sh on it (again is fine, it "
                       "only adds what is missing); see "
                       "docs/sandbox-vm.md"} | source()
    uid = str(rep.get("docker_id") or "")
    if uid:
        adopt(uid)
    return {"on": True, "why": "", "id": uid} | source()


def available():
    """Whether the VM answers, and if not, why: said rather than guessed.

    A sandbox VM is the arrangement, not one of several. Everything the
    manager does beyond `compose` (making a data directory, migrating one)
    is a container run as root on the far side, which is only safe on a
    machine whose job is being wrecked and reset. So an address of any other
    kind is refused here, in one place, rather than half-working down the
    line: the controls gray out wearing this sentence.
    """
    n = _agent_here()
    if n:
        return _available_agent(n)
    addr = docker_host()
    if not addr:
        # Two different absences: no node anywhere, or nodes and this
        # project bound to none of them (there is no primary for it to
        # fall to), which wants "pick one" rather than "enroll one".
        have = [n for n in (queue.docker_nodes() if queue else []) if n.get("kind") != "local"]
        if have:
            return {"on": False,
                    "why": "this project has no node, so it has no daemon: pick one on its "
                           "notebook's Settings (" + ", ".join(n["name"] for n in have[:3]) + ")"} | source()
        return {"on": False, "why": _no_daemon_why()} | source()
    if not addr.startswith("ssh://"):
        return {"on": False,
                "why": f"the node answers at {addr}, and dev instances need a "
                       "sandbox VM; see docs/sandbox-vm.md"} | source()
    r = _run([DOCKER, "version", "--format", "{{.Server.Version}}"], timeout=10)
    if r["code"] != 0 and "host key verification failed" in (r["out"] or "").lower():
        # Never met this machine. Meet it, once, and ask again; the answer
        # to that is the real one either way.
        met = _learn_host_key(addr)
        if met == "learned":
            r = _run([DOCKER, "version", "--format", "{{.Server.Version}}"], timeout=10)
        elif met == "changed":
            return {"on": False,
                    "why": f"this machine's ssh host key is not the one already "
                           f"recorded for {addr.split('@')[-1]}. A rebuilt VM does "
                           "that, and so does something worth looking at. Clear "
                           "the old line from the controller's known_hosts if the "
                           "machine really was rebuilt"} | source()
    if r["code"] != 0:
        return {"on": False,
                "why": "docker does not answer: " + _why_not(r["out"])} | source()
    # It answers Docker. That is not the same as being the sandbox, and the
    # difference is the whole safety argument: a container run here is root on
    # the far side, which is fine on a box whose job is being wrecked and
    # nothing like fine on the server. So the daemon has to carry the stamp
    # nodes/provision-linux.sh puts on the one it made.
    info = daemon_info()
    if info.get("error"):
        return {"on": False,
                "why": "docker answers but will not say what it is: "
                       + info["error"]} | source()
    if not is_sandbox(info["labels"]):
        return {"on": False,
                "why": "this daemon is not a BuilderBot sandbox: it carries no "
                       f"{SANDBOX_LABEL} label. Run nodes/provision-linux.sh on the VM "
                       "(again is fine, it only adds what is missing); see "
                       "docs/sandbox-vm.md"} | source()
    # A verified daemon is the source of truth from here on. Adopting it clears
    # what was recorded against a DIFFERENT one, so pointing this at a new VM
    # does not leave rows quoting a build that happened on a machine no longer
    # in play.
    adopt(info["id"])
    return {"on": True, "why": "", "id": info["id"]} | source()


_avail = {"when": 0.0, "val": None}
# The same memo per node address, for calls made inside on_node(). The default
# arrangement keeps its own entry above, since it predates nodes, and the tests
# prime it directly.
_avail_hosts = {}


def _uid():
    """The verified daemon's own id, as last seen. Empty until one answers.
    A stamp with no id is judged on its address, which is how every record
    written before this field is judged."""
    with _avail_lock:
        return ((_avail["val"] or {}).get("id") or "")
_avail_lock = threading.Lock()
AVAIL_TTL = 30


def available_default():
    """available_cached() for the node nothing named: what the status poll
    asks, since the page's daemon gate is one answer for the whole box.

    It used to need no context: docker_host() fell back to DOCKER_HOST, so a
    call from anywhere found the one daemon there was. With the ssh kind
    retired the address comes from the node record and nothing else, so this
    has to say WHICH node it means, and the default node is the same one
    the manager opens on.
    """
    with on_node(_default_node()):
        return available_cached()


def available_cached():
    """available(), memoised for AVAIL_TTL seconds.

    available() shells out to `docker version` with a ten-second timeout, and
    the status poll runs every fifteen. Asking it on the poll (and the poll is
    what the page's Docker controls read) would put a subprocess and a network
    round trip on the page's heartbeat, for an answer that changes when the
    operator wires something up rather than between two polls.

    Short enough that plugging the daemon in and pressing Refresh notices, long
    enough that it is not on the critical path of anything.
    """
    now = time.time()
    ctx = getattr(_node_ctx, "addr", None)
    if ctx is None:
        with _avail_lock:
            if _avail["val"] is not None and now - _avail["when"] < AVAIL_TTL:
                return _avail["val"]
        val = available()
        with _avail_lock:
            _avail.update(when=now, val=val)
        return val
    with _avail_lock:
        ent = _avail_hosts.get(ctx)
        if ent and now - ent["when"] < AVAIL_TTL:
            return ent["val"]
    val = available()
    with _avail_lock:
        _avail_hosts[ctx] = {"when": now, "val": val}
    return val


def forget_available():
    """Drop the memo, for a control that has just been told to try again.
    All of them: Refresh means "look again", and a stale verdict on the node
    beside the one that was refreshed is the same staleness."""
    with _avail_lock:
        _avail["val"] = None
        _avail_hosts.clear()


# Every docker call that CHANGES anything is a compose call naming its own
# project. That keeps a bug in a caller to the containers that call is about,
# and until this guard it was true only because every call site happened to go
# through _compose(). The invariant is asserted at the one place they all pass
# through, which turns "the code always passes --project-name" into "the code
# cannot not". It says nothing about what a compose FILE asks for; see
# risks().
#
# `ps` is allowed alongside `version`. On the sandbox the containers are this
# dashboard's and whatever else was put there deliberately, so being unable to
# see them is not safety, it is a blind spot: the Docker Manager exists to
# show what is actually running.
#
# Both are READS. Nothing here lets a verb that changes something in, and the
# namespace rule below is untouched: seeing a container is not touching it.
# `info` joins them for one reason: it is where the daemon's own labels are,
# and a label is how this container tells a VM the provisioner made from any
# other machine that happens to answer Docker. Also a read.
# An image reference as compose writes one: registry, path and tag, no
# spaces and nothing a shell or docker would read as a flag.
_IMAGE_REF = re.compile(r"[a-z0-9][a-z0-9._/:-]{0,250}")
_BARE_OK = {"version", "ps", "info"}
# Acting on a container by name: the three verbs a person reaches for on a
# list, and the log they open it to read (R68 steps 1 and 2). Held apart from
# compose because these address a CONTAINER rather than a project, which is
# the whole point: a container this dashboard did not create has no compose
# project here to name.
_CTL_OK = {"start", "stop", "restart"}
# What docker itself accepts as a name, and an id. The shape is the guard's
# half; the caller's half is that the name came out of the daemon's own
# listing a moment ago.
_CTR_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
# How much of a log is worth carrying: enough to see what a container said on
# its way down, not so much that a page is a download.
LOG_LINES = 400


def _mount_ok(root):
    """Whether a devdata `docker run` may bind this path as /d.

    Two shapes, and the second is why this is a function (B192). A SHARE ROOT
    (/auxiliary for /auxiliary/plex-library), which is what a compose naming a
    path on the VM needs: the mount is the share and the names under it are
    made by the run. And THIS NODE'S APPDATA STORE, whatever depth the node
    reports it at, which is where a dev instance's own data goes.

    The second used to be covered by the first by accident, because the store
    was /devdata and a one-component path is a share root. A node that reports
    /var/lib/builderbot/appdata got its own module refused by its own guard,
    on every poll, and the refusal said so: BuilderBot asking BuilderBot for
    something and being told no is a bug in it, which is how this was found.

    Worth saying plainly, because the fix looks like a loosening and is not:
    the share-root rule ALREADY allows mounting /var to make a directory three
    levels under it, so naming the deep path instead is the narrower of the
    two, not the wider. What the rule is really for is stopping a mount of /
    or of a path with `..` in it, and both stay refused.

    The appdata root is read from this controller's own record of the node,
    never from the argv, so there is nothing here an argv can talk into
    matching that it could not already reach through the share root above.
    """
    root = (root or "").rstrip("/")
    if not root.startswith("/") or not _DEV_NAME.match(root[1:]):
        return False                              # "/", "", or a name with .. in it
    if "/" not in root[1:]:
        return True                               # a share root
    return root == appdata_root().rstrip("/")


def _guard(argv):
    """The reason to refuse this argv, or "" to let it run."""
    if not argv or argv[0] != DOCKER:
        return ""                      # git, and anything else not docker
    verb = argv[1] if len(argv) > 1 else ""
    if verb in _BARE_OK:
        return ""
    if not verb:
        return "a bare `docker` with no subcommand"
    # The runs that tend the dev-data directory, recognized by SHAPE and never
    # by verb. `docker run` with a bind is root on the daemon, so allowing the
    # verb would give away everything the namespace rule above protects;
    # allowing these gives away a mkdir, a mv and a test on one directory.
    # Every template is rebuilt from the names the argv itself carries and
    # compared whole, so the only way through is a command _devdata_argv could
    # have produced, and only where the daemon is a machine whose job is
    # being wrecked.
    if verb == "run":
        if not verified_sandbox():
            return ("`docker run` is only allowed where the daemon is a "
                    "sandbox VM the provisioner made, and this one does not "
                    "say it is")
        names = [a[3:] for a in argv if a.startswith("/d/")]
        # The mount source is read back out of the argv and required to be a
        # share root (one absolute component, a plain name) so the rebuild
        # below cannot be satisfied by mounting / or anything nested. This
        # says WHERE, the rebuild says WHAT; the reach is any share on the
        # daemon, which is the sandbox premise doing its job.
        mount = next((a for a in argv if a.endswith(":/d")), "")
        root = mount[:-3]
        if not _mount_ok(root):
            return (f"a `docker run` mounting {root or '?'}, which is neither a share "
                    "root nor this node's appdata store")
        if names and all(_DEV_NAME.match(n) for n in names) and any(
                argv == _devdata_argv(op, *names, root=root)
                for op in _DEVDATA_OPS):
            return ""
        return "a `docker run` this module did not build"
    # Start, stop, restart and the log, each by SHAPE: the verb and names
    # that look like names, one or an instance's several (container_ctl
    # acts on every container the name means; B770). Nothing else can ride
    # along, because each word is held to a name rather than scanned for
    # something bad.
    if verb in _CTL_OK:
        if argv[2:] and all(_CTR_NAME.match(a) for a in argv[2:]):
            return ""
        return f"a `docker {verb}` this module did not build"
    # Start on boot (R122): the restart policies read for a list, and one set
    # on named containers, each in the one shape this module builds. Refused
    # by this guard until B476, so the switch never read or set anything.
    if verb == "inspect":
        if argv[2:4] == ["--format", BOOT_FORMAT] and argv[4:] and all(_CTR_NAME.match(a) for a in argv[4:]):
            return ""
        # ...and an image's pulled digests, for the registry check
        # (imagecheck.py, R195): one image reference, in its one shape.
        if argv[2:6] == ["--type", "image", "--format", "{{json .RepoDigests}}"] and len(argv) == 7 \
                and _IMAGE_REF.fullmatch(argv[6]):
            return ""
        return "a `docker inspect` this module did not build"
    if verb == "update":
        if (argv[2:3] == ["--restart"] and len(argv) > 4 and argv[3] in ("unless-stopped", "no")
                and all(_CTR_NAME.match(a) for a in argv[4:])):
            return ""
        return "a `docker update` this module did not build"
    # The reads the Docker tab's 2.0 surfaces make (R216), each in the one
    # shape this module builds: what every container uses now, the images
    # and the volumes on the daemon and what they weigh.
    if verb == "stats":
        if argv[2:] == ["--no-stream", "--format", "{{json .}}"]:
            return ""
        return "a `docker stats` this module did not build"
    if verb == "images":
        if argv[2:] == ["--format", "{{json .}}"]:
            return ""
        return "a `docker images` this module did not build"
    # ...and the prunes the view offers, each exactly as PRUNES spells it and
    # nothing named: the four were added to PRUNES while this knew two, so
    # Prune unused images and Prune build cache were refused as a bug (B245).
    if argv[1:] in [list(p) for p in PRUNES.values()]:
        return ""
    if verb == "image":
        return "a `docker image` this module did not build"
    if verb == "volume":
        if argv[2:] == ["ls", "--format", "{{json .}}"]:
            return ""
        return "a `docker volume` this module did not build"
    if verb == "system":
        if argv[2:] == ["df", "--format", "{{json .}}"]:
            return ""
        return "a `docker system` this module did not build"
    if verb == "logs":
        if (len(argv) == 6 and argv[2] == "--tail" and argv[3].isdigit()
                and argv[4] == "--timestamps" and _CTR_NAME.match(argv[5])):
            return ""
        return "a `docker logs` this module did not build"
    if verb != "compose":
        return (f"`docker {verb}` is not reachable here: only compose, the "
                f"reads in {'/'.join(sorted(_BARE_OK))}, and "
                f"{'/'.join(sorted(_CTL_OK))} or logs on one container, are")
    # Every compose call names its project explicitly, so none of them can
    # fall back to compose's default, the directory it happens to be run
    # from. The VALUE is checked, not just the flag: _slug() returns "" for a
    # name with no letter or digit in it (a project directory called `---`),
    # and an empty --project-name is exactly the fallback this is here to
    # prevent. A prefix used to make that unreachable by always prepending
    # something, which is not the same as checking.
    try:
        name = argv[argv.index("--project-name") + 1]
    except (ValueError, IndexError):
        return "a compose call carrying no --project-name"
    if not name.strip():
        return "a compose call whose --project-name is empty"
    return ""


# Set by server.py (diag.redact): an argv or an output tail can carry a
# token, and docker.log is in the downloads.
redact = lambda text: text   # noqa: E731


def _docker_log(line):
    """One line into the Docker manager's own log, best effort.

    Its own file because these are somebody else's build output (minutes of
    layer progress per press) and putting that in the boot log would bury the
    session's own story in it. What DOES reach the boot log is the verdict: see
    _run, which prints a failure to stderr as well.
    """
    if not log_dir:
        return
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "docker.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {redact(line)}\n")
    except OSError:
        pass


def _run(argv, timeout=60, env_extra=None, sink=None, hold=None):
    """One docker or compose call.

    `sink` and `hold` are what make a long one watchable and stoppable. Without
    them the output arrives when the process exits, which for `compose build`
    is minutes of nothing followed by everything at once, a pull that looks
    like a hang. With a sink the lines are handed over as they are read, so
    the row's tail fills while it runs; with `hold` the process is offered to
    the caller so Abort has something to interrupt.

    Both optional, and every short call still takes the simple path: a
    `docker version` does not need a reader thread.
    """
    bad = _guard(argv)
    if bad:
        # Refused rather than raised: a build runs on a job thread, where an
        # exception would end the job with nothing to show for it. A code and a
        # message travel the path a real docker failure already travels, and
        # say plainly that this one is a bug here, not a daemon that said no.
        msg = "refused by BuilderBot, and this is a bug in it: " + bad
        print("[devapp] " + msg, file=sys.stderr, flush=True)
        return {"code": 126, "out": msg}
    # A bare docker READ addressed at an agent node runs ON that node, as
    # the compose actions already do (roadmap #18): the controller holds no
    # ssh into a node its agent dials out of, so `docker ps` over
    # DOCKER_HOST=ssh:// was the one call left dialing it and the one that
    # failed on every fresh deploy (B134). Streamed calls are builds and
    # never reach here on an agent node; _submit ships those whole.
    # ...and the 2.0 reads the same way (R216): what the containers use,
    # the images, the volumes and what they weigh.
    if sink is None and hold is None and argv[:1] == [DOCKER] \
            and len(argv) > 1 and (argv[1] in _BARE_OK | {"inspect", "stats", "images"}
                                   or argv[1:3] in (["volume", "ls"], ["system", "df"])):
        n = _agent_here()
        if n:
            return _agent_read(n, argv, timeout)
    # ...and the verbs addressed at one container by name (its log, start,
    # stop, restart) run there the same way, as one exec and never from a
    # kept answer: they fell through to DOCKER_HOST=ssh:// below, which on
    # an agent node is the path R85 names and no controller holds a key
    # for, so a session's bb devapp log on the dev pair met "Host key
    # verification failed" from the VM (B312).
    if sink is None and hold is None and argv[:1] == [DOCKER] \
            and len(argv) > 1 and (argv[1] in _CTL_OK | {"logs", "update"}
                                   or argv[1:] in [list(p) for p in PRUNES.values()]):
        n = _agent_here()
        if n:
            return _agent_exec(n, argv, timeout)
    _docker_log("$ " + " ".join(argv))
    env = dict(os.environ)
    # The resolved address, so `auto` never reaches the docker CLI, which does
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
            # doing: noise in a row or a doctor line that has room for a
            # sentence.
            return {"code": 1, "out": f"timed out after {timeout}s"}
        except (OSError, subprocess.SubprocessError) as e:
            return {"code": 1, "out": str(e)}
        out = (r.stdout or "") + (r.stderr or "")
        _docker_result(argv, r.returncode, out)
        return {"code": r.returncode, "out": out}
    res = _run_streamed(argv, timeout, env, sink, hold)
    _docker_result(argv, res["code"], res["out"])
    return res


def _docker_result(argv, code, out):
    """How a call ended, in the manager's log, and on stderr when it failed.

    The failure goes to stderr because that is the container's own stream and
    therefore the boot log: a compose call that did not work is exactly the
    kind of thing you want to find when reading the session's story an hour
    later, without having to know there is a second file.
    """
    tail = " ".join((out or "").split())[-300:]
    _docker_log(f"  -> exit {code}" + (f": {tail}" if tail else ""))
    if code != 0:
        print(f"[devapp] WARN: {' '.join(argv[:4])}… exited {code}"
              + (f": {tail[:200]}" if tail else ""),
              file=sys.stderr, flush=True)


def _run_streamed(argv, timeout, env, sink, hold):
    """The watchable form: read as it goes, and let it be killed.

    stderr is folded into stdout because that is where docker writes its
    progress and where compose writes everything; two streams read separately
    would interleave by luck rather than by time.

    Its own process group, so a kill reaches what the CLI is waiting on rather
    than only the CLI: the toolchain installer learned this against a `bb` that
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
# anything, so a container's name need not resemble its project's.
COMPOSE_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"


# What each container is using now (R216): one `docker stats` per ask,
# memoised a few seconds per daemon, so a page that redraws often does not
# sample the daemon on every redraw. Read beside the list, never inside it:
# stats takes a second or two to sample and the list must not wait on it.
STATS_TTL = 8
_stats = {}
_stats_lock = threading.Lock()


def _size_bytes(text):
    """'12.7MiB' or '1.2kB' as bytes, 0 for anything else."""
    m = re.match(r"\s*([0-9.]+)\s*([kKMGT]?i?B)", text or "")
    if not m:
        return 0
    n = float(m.group(1))
    unit = m.group(2)
    base = 1024 if "i" in unit else 1000
    power = "BKMGT".index(unit[0].upper()) if unit[0].upper() in "BKMGT" else 0
    return int(n * (base ** power))


def parse_stats(text):
    """{container name: {cpu, mem, mem_limit, mem_pct, rx, tx, pids}} from
    `docker stats --no-stream --format {{json .}}`: percentages as numbers,
    sizes as bytes."""
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            c = json.loads(line)
        except ValueError:
            continue
        name = c.get("Name") or ""
        if not name:
            continue
        mem = str(c.get("MemUsage") or "").split("/")
        net = str(c.get("NetIO") or "").split("/")
        pct = lambda v: float(str(v or "0").rstrip("%") or 0)  # noqa: E731
        out[name] = {"cpu": pct(c.get("CPUPerc")), "mem": _size_bytes(mem[0]),
                     "mem_limit": _size_bytes(mem[1]) if len(mem) > 1 else 0,
                     "mem_pct": pct(c.get("MemPerc")), "rx": _size_bytes(net[0]),
                     "tx": _size_bytes(net[1]) if len(net) > 1 else 0,
                     "pids": int(str(c.get("PIDs") or "0").strip() or 0)}
    return out


def stats():
    """The running containers' use now, by name, memoised STATS_TTL seconds
    per daemon; {"error": why} when the daemon did not answer."""
    key = getattr(_node_ctx, "addr", None) or ""
    now = time.time()
    with _stats_lock:
        ent = _stats.get(key)
        if ent and now - ent["when"] < STATS_TTL:
            return ent["val"]
    r = _run([DOCKER, "stats", "--no-stream", "--format", "{{json .}}"], timeout=20)
    val = {"error": _why_not(r["out"]), "stats": {}} if r["code"] != 0 else {"error": "", "stats": parse_stats(r["out"])}
    with _stats_lock:
        _stats[key] = {"when": now, "val": val}
    return val


def images_view():
    """The daemon's images and volumes (R216): each image with its size and
    age and whether a container here uses it, each volume with its driver,
    and what the daemon says the lot weighs and what a prune would give
    back. One listing each, memoised like stats."""
    key = "img:" + (getattr(_node_ctx, "addr", None) or "")
    now = time.time()
    with _stats_lock:
        ent = _stats.get(key)
        if ent and now - ent["when"] < STATS_TTL:
            return ent["val"]
    out = {"error": "", "images": [], "volumes": [], "df": []}
    # The three listings one after another, on this thread: the node a
    # call is addressed at is thread-local (on_node), so a pool of threads
    # would have asked the controller's own daemon instead.
    got = {k: _run(argv, timeout=20) for k, argv in (
        ("images", [DOCKER, "images", "--format", "{{json .}}"]),
        ("volumes", [DOCKER, "volume", "ls", "--format", "{{json .}}"]),
        ("df", [DOCKER, "system", "df", "--format", "{{json .}}"]))}
    r = got["images"]
    if r["code"] != 0:
        out["error"] = _why_not(r["out"])
    else:
        used = {c["image"] for c in (containers().get("containers") or [])}
        for line in r["out"].splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                c = json.loads(line)
            except ValueError:
                continue
            repo, tag = c.get("Repository", ""), c.get("Tag", "")
            iid = str(c.get("ID") or "").split(":")[-1][:12]
            # In use by the name a container was started from: repo:tag, the
            # bare repo for :latest, or the id.
            names = {f"{repo}:{tag}", iid} | ({repo} if tag == "latest" else set())
            out["images"].append({
                "repo": repo, "tag": tag, "id": iid,
                "size": _size_bytes(c.get("Size", "")), "created": c.get("CreatedSince", ""),
                "used": bool(names & used) or any(u.split(":")[-1][:12] == iid for u in used if u.startswith("sha256:")),
                "dangling": c.get("Repository") == "<none>" or c.get("Tag") == "<none>"})
    r = got["volumes"]
    if r["code"] == 0:
        for line in r["out"].splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                c = json.loads(line)
            except ValueError:
                continue
            out["volumes"].append({"name": c.get("Name", ""), "driver": c.get("Driver", "")})
    r = got["df"]
    if r["code"] == 0:
        for line in r["out"].splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                c = json.loads(line)
            except ValueError:
                continue
            out["df"].append({"kind": c.get("Type", ""), "count": int(str(c.get("TotalCount") or 0) or 0),
                              "active": int(str(c.get("Active") or 0) or 0), "size": _size_bytes(c.get("Size", "")),
                              "reclaimable": _size_bytes(str(c.get("Reclaimable", "")).split(" ")[0])})
    out["images"].sort(key=lambda i: (i["used"], -i["size"]))
    with _stats_lock:
        _stats[key] = {"when": now, "val": out}
    return out


# What each prune removes (R110 step 3 adds the last two, which are where a
# busy node's disk goes: images nothing has used for two weeks, and the
# build cache older than a week). Nothing a container uses is ever touched.
PRUNES = {"images": ["image", "prune", "-f"],
          "volumes": ["volume", "prune", "-f"],
          "unused": ["image", "prune", "-a", "-f", "--filter", "until=336h"],
          "cache": ["builder", "prune", "-f", "--filter", "until=168h"]}


def prune(kind):
    """One of PRUNES: dangling images, volumes no container uses, images no
    container uses and two weeks old, or the build cache a week old.
    {"ok", "out"} with docker's own account of what went, or {"error"}."""
    if kind not in PRUNES:
        return {"error": "prune images, volumes, unused or cache"}
    argv = [DOCKER, *PRUNES[kind]]
    r = _run(argv, timeout=120)
    with _stats_lock:
        _stats.pop("img:" + (getattr(_node_ctx, "addr", None) or ""), None)
    if r["code"] != 0:
        return {"error": _why_not(r["out"])}
    return {"ok": True, "out": r["out"].strip()[-2000:]}


def containers():
    """Everything on the daemon, and whose it is.

    All of them, not only ours. The operator asked to see what is running on
    that machine and showing half of it would be a listing that lies by
    omission: a port conflict with something this dashboard did not start is
    exactly the thing you open a list to find out about.

    `ours` is the honest part: a container is this dashboard's when its compose
    project is one this dashboard has a record of. Asked of the store rather
    than read off the name, so a container you started by hand over there is
    listed and marked as not ours: started, stopped or restarted by name one
    at a time, and nobody's project until its row names one.
    """
    r = _run([DOCKER, "ps", "--all", "--no-trunc", "--format", "{{json .}}"],
             timeout=25)
    if r["code"] != 0:
        # From the TAIL, through the same reader availability uses. Cut from
        # the front, as this was, docker's connect error reads "command [ssh
        # -l bb -o Connect…" and stops, which is the half the operator knew
        # (B106). It mattered less when a failed listing only grayed rows
        # nobody could act on; now that the controls stay live and this line
        # is the whole account of what is not known, it is the message.
        return {"error": _why_not(r["out"]), "containers": []}
    # Which compose projects are this dashboard's, asked of the store rather
    # than read off the name. A name used to answer it by carrying a prefix,
    # which meant every container had a longer name so that this one function
    # could do a string comparison.
    mine = {_pname(p, i) for p, insts in _load().items() for i in insts}
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
            # reads, and the whole one is still what docker was asked for, so
            # this is a display choice rather than a lossy fetch.
            "id": (c.get("ID") or "")[:12],
            "name": c.get("Names", ""),
            "image": c.get("Image", ""),
            "state": (c.get("State") or "").lower(),
            "status": c.get("Status", ""),
            "ports": _ports(c.get("Ports", "")),
            # ...and the ports published on every address, for a node whose
            # ports are meant to stay on it (R190).
            "open": sorted(set(_published(_ports(c.get("Ports", ""))))
                           - set(_published(_ports(c.get("Ports", "")), local=True))),
            "project": proj,
            "service": labels.get(SERVICE_LABEL, ""),
            "ours": proj in mine,
        })
    _boot_read(out)
    out.sort(key=lambda c: (not c["ours"], c["project"], c["name"]))
    return {"error": "", "containers": out, "stale": bool(r.get("stale"))}


# Start on boot (R122, the operator 4 Oct): a container's restart policy,
# read in one docker inspect for the whole list. unless-stopped or always is
# on: the daemon starts it when the node (or docker) starts, unless somebody
# stopped it. For an instance of BuilderBot's own the choice is kept on its
# record, because a rebuild recreates its containers with the compose file's
# policy, and the listing that finds one drifted puts the choice back.
BOOT_ON = ("always", "unless-stopped")
BOOT_FORMAT = "{{.Id}} {{.HostConfig.RestartPolicy.Name}}"
# Each container's policy by its id, so a listing inspects only containers it
# has not seen. On a node the listing is an agent job, and a second job for
# the inspect on every listing doubled what the Docker tab waits on: devapp.mjs
# timed out around Up in every gate that ran it beside another suite (B470).
# A rebuild makes new ids, read once; Start on boot writes what it set here.
_policies = {}
_asked_at = {}          # id -> when an inspect last went unanswered for it
_boot_thread = None     # the last read, for a test to wait on
UNKNOWN_S = 300


def boot_known(ids, policy):
    """What a press of Start on boot just set, so the next listing says it
    without asking docker again."""
    for i in ids:
        if i:
            _policies[str(i)[:12]] = policy


def _boot_read(out):
    ids = [c["id"] for c in out if c.get("id")]
    if not ids:
        return
    new = [i for i in ids if i not in _policies or
           (_policies[i] == "" and time.time() - _asked_at.get(i, 0) > UNKNOWN_S)]
    if new:
        # Read off the listing's path: the listing draws what is known, and
        # the next one (seconds later) has the rest. On a node the inspect is
        # a job of its own, and a listing that waited on it was what kept
        # the Docker tab's waits running out (B470, B476). An id the daemon
        # did not describe is remembered as unknown for a while, then asked
        # again.
        for i in new:
            _policies[i] = ""
            _asked_at[i] = time.time()
        n = _agent_here()
        argv = [DOCKER, "inspect", "--format", BOOT_FORMAT, *new]

        def read():
            r = _agent_read(n, argv, 30) if n else _run(argv, timeout=30)
            for ln in (r.get("out") or "").splitlines():
                bits = ln.split()
                if len(bits) == 2 and bits[0][:12] in _policies:
                    _policies[bits[0][:12]] = bits[1]
        global _boot_thread
        _boot_thread = threading.Thread(target=read, name="docker-boot", daemon=True)
        _boot_thread.start()
    # Bounded: past a few hundred ids, keep only the ones this list has. A
    # node switched away from is read again once, which costs one inspect.
    if len(_policies) > 500:
        for i in [i for i in _policies if i not in ids]:
            _policies.pop(i, None)
            _asked_at.pop(i, None)
    pol = {i: _policies.get(i, "") for i in ids}
    for c in out:
        c["restart"] = pol.get(c.get("id"), "")
        c["boot"] = c["restart"] in BOOT_ON
    want = {}
    for p, insts in _load().items():
        for i, rec in (insts or {}).items():
            if isinstance(rec, dict) and isinstance(rec.get("boot"), bool):
                want[_pname(p, i)] = rec["boot"]
    for on in (True, False):
        drift = [c for c in out if c.get("restart") and want.get(c.get("project")) is on and c["boot"] is not on]
        if drift:
            got = _run([DOCKER, "update", "--restart", "unless-stopped" if on else "no",
                        *[c["name"] or c["id"] for c in drift]], timeout=30)
            if got.get("code") == 0:
                for c in drift:
                    c["boot"], c["restart"] = on, "unless-stopped" if on else "no"
                boot_known([c.get("id") for c in drift], "unless-stopped" if on else "no")


def remember_boot(pname, on):
    """Keep an instance's Start on boot choice, so a rebuild cannot undo it;
    a container that is not one of BuilderBot's instances has nothing to keep."""
    with _lock:
        d = _load()
        for p, insts in d.items():
            for i in (insts or {}):
                if _pname(p, i) == pname:
                    _rec(d, p, i)["boot"] = bool(on)
                    write_json(FILE, d)
                    return True
    return False


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
    port arrives twice, as 0.0.0.0:8080->80/tcp and [::]:8080->80/tcp. Shown
    both ways it reads as two ports.
    """
    seen = []
    for bit in (raw or "").split(","):
        bit = bit.strip()
        if "->" not in bit:
            continue
        host, _, rest = bit.partition("->")
        bind, _, port = host.rpartition(":")
        # Bound to the loopback, it says so (R190): that is the port only the
        # node's own nginx reaches, and the row has to tell it from one
        # published on every address.
        entry = f"127.0.0.1:{port}->{rest}" if bind.startswith("127.") else f"{port}->{rest}"
        if entry not in seen:
            seen.append(entry)
    return seen


def containers_dir(name):
    return STATE / "containers" / name


def project_has_compose(project):
    """Whether the project's own checkout carries a compose file.

    Stats only, and deliberately: compose_file() consults the instance record
    first, which means reading the store, and this is asked for every project
    on every status poll. The question here is not "which file would an
    instance build from" but "is there anything to build at all", which is
    what decides whether the settings dialog offers to run the tests in a
    container (R68 step 6).
    """
    return any((WORKSPACE / project / n).is_file() for n in COMPOSE_NAMES)


# Every compose file a project has, not only the one at its root (the
# operator, 10 Oct): a repo with a site in site/ and an api in api/, or a
# docker-compose.prod.yml beside the main one. An override file is left out:
# compose merges it onto the file beside it, and alone it is half a file.
# compose.yml, docker-compose.yml, a variant after (compose.prod.yml) or a
# name before (admin.compose.yml: one file per service, as Turing Lens
# keeps them under deploy/containers/, 11 Oct).
OVERRIDE_RE = re.compile(r"[A-Za-z0-9_.-]+\.override\.ya?ml")
COMPOSE_RE = re.compile(r"(?:(?P<pre>[A-Za-z0-9_-]+)\.)?(docker-)?compose(?P<var>\.[A-Za-z0-9_-]+)?\.ya?ml")
COMPOSE_SKIP = {".git", "node_modules", ".gradle", "__pycache__", ".venv", "venv",
                ".next", ".cache", ".bb-map", "dist", "build", "vendor", ".worktrees"}
COMPOSE_DEPTH = 3
COMPOSE_MAX_FILES = 12
# Which file the next lookup means, over the record's: the Artifacts tab
# judges each file in turn this way (devactions.file_rows).
_pick = threading.local()


@contextlib.contextmanager
def composing(rel):
    """Within this, every lookup means `rel`, whatever the record says: a
    file judged as what Send would make of it."""
    was = getattr(_pick, "rel", None)
    _pick.rel = rel
    try:
        yield
    finally:
        _pick.rel = was


def compose_files(project):
    """The project's compose files, relative to its root, the root's own
    first: what the Artifacts view offers to send, one row each. A symlink is
    never one, file or directory (the audit of 26 Sep)."""
    return _compose_walk(project, overrides=False)


def override_files(project):
    """Every compose file in the project's tree an instance may lay over its
    own (the operator, 17 Oct): the sendable ones and the ones named
    `*.override.*`, which are never sent on their own."""
    return _compose_walk(project, overrides=True)


def _compose_walk(project, overrides=False):
    top = WORKSPACE / project
    out = [n for n in COMPOSE_NAMES if (top / n).is_file() and not (top / n).is_symlink()][:1]
    for d, dirs, files in os.walk(top):
        rel = os.path.relpath(d, top)
        depth = 0 if rel == "." else rel.count("/") + 1
        dirs[:] = sorted(x for x in dirs if x not in COMPOSE_SKIP and not x.startswith(".")
                         and not os.path.islink(os.path.join(d, x)) and depth < COMPOSE_DEPTH)
        for f in sorted(files):
            # ...and, for an override, one named for being one (staging.override.yml).
            if not (COMPOSE_RE.fullmatch(f) or (overrides and OVERRIDE_RE.fullmatch(f))) \
                    or (".override." in f and not overrides):
                continue
            r = f if rel == "." else f"{rel}/{f}"
            if r not in out and not os.path.islink(os.path.join(d, f)):
                out.append(r)
        if len(out) >= COMPOSE_MAX_FILES:
            break
    return out[:COMPOSE_MAX_FILES]


def compose_rel(project, instance=MAIN):
    """The compose file an instance is built from, relative to its project:
    the one Send was pressed on, else the root's own."""
    rel = getattr(_pick, "rel", None) or str(_read_rec(project, instance).get("compose") or "")
    if rel:
        return rel
    return next((n for n in COMPOSE_NAMES if (WORKSPACE / project / n).is_file()), "")


def compose_sub(project, instance=MAIN):
    """The folder that file is in, "" for the root: compose resolves the
    file's relative paths (build: ., ./data) against it, so it is the
    project directory every compose call names."""
    d = posixpath.dirname(compose_rel(project, instance))
    return "" if d in ("", ".") else d


def compose_ok(project, rel):
    """"" when `rel` is one of the project's compose files, else why not."""
    if rel and rel not in compose_files(project):
        return f"{project} has no compose file {rel}"
    return ""


def example_file(project, instance=MAIN):
    """The .env.example beside the instance's compose file: the root's for
    the root's, a folder's own for one in a folder. Not the root's for a
    folder's: compose reads a file's .env from its own folder, and the
    root's example asked a one-service site in a folder for every key of
    the project's own app (found sending R167's test container, 10 Oct)."""
    return WORKSPACE / project / compose_sub(project, instance) / ".env.example"


# A build context Docker fetches rather than reads from disk: a git URL
# (https://...git#ref, git@host:..., git://, ssh://) or a github.com path.
_REMOTE_CTX = re.compile(r"^(?:git@|git://|ssh://|https?://\S+?\.git(?:#\S*)?$|(?:https?://)?github\.com/)")


def remote_contexts(compose_text):
    """The git URLs a compose file builds from (B595), read off its `build:`
    and `context:` lines: a build from one is the files committed at that
    ref, so an untracked or ignored file changed in a working tree is never
    in it, and the rebuild's log says so before it builds."""
    out = []
    for line in str(compose_text or "").splitlines():
        m = re.match(r"\s*(?:build|context)\s*:\s*['\"]?([^'\"#\s][^'\"\s]*)['\"]?\s*$", line)
        if m and _REMOTE_CTX.match(m.group(1)) and m.group(1) not in out:
            out.append(m.group(1))
    return out


def compose_file(project, instance=MAIN):
    """The compose file behind an instance.

    Two sources, and the record says which. A project's instance is built from
    the working copy, which is the whole point of it. A container written here
    has no working copy at all: its compose file lives in /config beside the
    rest of the notebook's storage, where the project scan cannot see it and
    the backup that takes /config takes it too.
    """
    if _read_rec(project, instance).get("source") == "file":
        f = containers_dir(project) / "docker-compose.yml"
        return f if f.is_file() and not f.is_symlink() else None
    # A real file, never a link: a compose file symlinked to a controller
    # file went into the job spec and onto the node (the audit of 26 Sep).
    rel = compose_rel(project, instance)
    if not rel or ".." in rel.split("/") or rel.startswith("/"):
        return None
    p = WORKSPACE / project / rel
    try:
        inside = p.resolve().is_relative_to((WORKSPACE / project).resolve())
    except OSError:
        return None
    return p if inside and p.is_file() and not p.is_symlink() else None


# ---- an instance's override (the operator, 17 Oct) ---------------------------
# A second compose file from the project's tree, laid over the instance's own
# with compose's own -f after -f: its ports, env, volumes or an extra service
# for that one container, versioned with the tree and built from its branch
# as the base file is. Never text kept here (a compose outside the tree is
# what a project's container may not have), and never loaded by itself: an
# instance names one or has none. What it adds is read with the base file
# by every gate, the beside-the-app one included.
def override_rel(project, instance=MAIN):
    return str(_read_rec(project, instance).get("override") or "")


def override_file(project, instance=MAIN):
    """The instance's override as a real file inside the project, or None."""
    rel = override_rel(project, instance)
    if not rel or is_file_source(project, instance) or ".." in rel.split("/") or rel.startswith("/"):
        return None
    p = WORKSPACE / project / rel
    try:
        inside = p.resolve().is_relative_to((WORKSPACE / project).resolve())
    except OSError:
        return None
    return p if inside and p.is_file() and not p.is_symlink() else None


def override_ok(project, rel, instance=MAIN):
    """"" when `rel` may be laid over the instance's compose file, else why."""
    if not rel:
        return ""
    if rel not in override_files(project):
        return f"{project} has no compose file {rel} to lay over its own"
    if rel == (compose_rel(project, instance) or ""):
        return f"{rel} is the compose file it is built from, not one to lay over it"
    return ""


def set_override(project, instance, rel):
    """Name the instance's override, or none with ""."""
    rel = str(rel or "").strip()
    if is_file_source(project, instance):
        return {"error": "a container written here is all its own compose file: edit that instead"}
    why = override_ok(project, rel, instance)
    if why:
        return {"error": why}
    with _lock:
        store = _load()
        rec = _rec(store, project, instance)
        if rel:
            rec["override"] = rel
        else:
            rec.pop("override", None)
        write_json(FILE, store)
    _bump()
    return {"ok": True, "override": rel}


def pname(project, instance=MAIN):
    """What the container is called, for anybody outside this module who has
    to name one in a sentence: the rebuild request the operator reads, for
    instance. The underscore one stays the module's own."""
    return _pname(project, instance)


# A project's container named by hand (the operator, 11 Oct: a project's
# container is named whatever its owner wants, not after the project): the
# record's `name`, read through a table kept per store write, since _pname
# is on the poll path and is asked in loops over every instance.
_named = {"at": None, "map": {}}


def _names():
    try:
        at = FILE.stat().st_mtime_ns
    except (OSError, AttributeError, TypeError):
        at = None
    if at is None or at != _named["at"]:
        _named["map"] = {(p, i): str(r["name"]) for p, insts in _load().items()
                         for i, r in insts.items() if r.get("name") and r.get("source") != "file"}
        _named["at"] = at
    return _named["map"]


def _pname(project, instance=MAIN):
    """The compose project name: the prefix, then what the thing is called.

    A project's container renamed in the Edit dialog carries the name it was
    given on its record (`name`), and that wins over both rules below.

    The PROJECT used to be in here as well, as <project>-<instance>,
    which for a project called MediaReducer-Dev with an instance named after
    it read `mediareducer-dev-mediareducer-dev`. The project half only
    ever bought uniqueness, and uniqueness is checked directly now
    (taken_pnames) rather than spelled out in every name forever.

    A project's default instance is named for the PROJECT, because nobody
    typed a name for it: `main` is implied rather than chosen, and
    `alpha-main` was saying the same thing twice too.
    """
    own = _names().get((project, instance))
    if own:
        return own
    inst = _slug(instance) or MAIN
    return _slug(project) if inst == MAIN else inst


def name_clash(project, instance=MAIN):
    """Whether this instance's compose name is already a different one's.

    Container names and PROJECT names are separate things. A project called
    MediaReducer-Dev does not reserve `mediareducer-dev` for a container, and
    an earlier version of this checked that it did, which made a name the
    operator had every right to use come back refused. Nothing is reserved in
    advance; a project blocks no name until it actually has an instance.

    What cannot happen is two INSTANCES resolving to one compose project name,
    because that is one set of containers, one env file and one data directory
    with two rows driving them. Asked at the moment an instance is created or
    started, which is the moment the clash becomes real rather than possible.

    Which project owns an instance is not this question and is never derived
    from the name: it is owner_of, which is what decides whose session may
    touch it.
    """
    want = _pname(project, instance)
    for proj, insts in _load().items():
        for inst in insts:
            if (proj, inst) == (project, instance) or _pname(proj, inst) != want:
                continue
            whose = f"{proj}'s " + ("own container" if inst == MAIN else f"'{inst}'")
            return (f"{want} is already {whose}, and two of them would drive one "
                    f"set of containers"
                    + (": Build or Rebuild builds it on the Containers page" if inst == MAIN
                       else ", so this one needs another name"))
    return ""


def env_path(project, instance=MAIN):
    """One env file per INSTANCE, not per project.

    Two instances of one codebase exist to differ (different ports at the very
    least, or they cannot both run) so sharing an env would make the second
    one impossible. Named for the compose project, which is already unique and
    already slugged.
    """
    return ENVDIR / f"{_pname(project, instance)}.env"


# A service's `env_file: .env` names the project's own .env, which BuilderBot
# never writes: an instance's env is a file of its own (env_path), handed to
# compose as --env-file, and that fills ${VAR} in the compose text and
# nothing else. A compose file that reads its settings through env_file came
# up without them, or not at all with the .env missing: what the operator
# typed into Send to Docker never reached Is-someone-Listening's container
# (24 Sep). The copy compose runs points those lines at the instance's env.
_ENV_KEY = re.compile(r"^(\s*)env_file:\s*(#.*)?$")
_ENV_ONE = re.compile(r"""^(\s*env_file:\s*)(["']?)(?:\./)?\.env\2(\s*(?:#.*)?)$""")
_ENV_ITEM = re.compile(r"""^(\s*-\s*(?:path:\s*)?)(["']?)(?:\./)?\.env\2(\s*(?:#.*)?)$""")


def env_to_instance(text, target):
    """`text` with each env_file that names the project's .env, in any of
    compose's three spellings (a value, a list item, a long-form `path:`),
    pointed at `target`. Unchanged when none does. By line, not by parsing:
    the server carries no YAML library, and these are the lines people write."""
    out, key = [], None           # the env_file key's indent, inside its list
    for line in (text or "").split("\n"):
        body = line.strip()
        ind = len(line) - len(line.lstrip())
        if key is not None and body and ind <= key and not (ind == key and body.startswith("-")):
            key = None
        m = _ENV_ONE.match(line)
        if m:
            out.append(f"{m.group(1)}{target}{m.group(3)}")
            continue
        m = _ENV_KEY.match(line)
        if m:
            key = len(m.group(1))
            out.append(line)
            continue
        m = _ENV_ITEM.match(line) if key is not None else None
        out.append(f"{m.group(1)}{target}{m.group(3)}" if m else line)
    return "\n".join(out)


def _compose(project, instance, *args):
    """The one shape every action runs: compose, pinned to this instance's
    name and env and to its project's file. A table of verbs, not a command
    string.

    The project directory and the compose file are the PROJECT's: every
    instance of a project is built from the same codebase, which is the whole
    point of having more than one of them.
    """
    cf = compose_file(project, instance)
    # What a relative bind source resolves against, and it must be a path the
    # DAEMON has. A project's own directory is one: /workspace has parity with
    # the sandbox by construction. /config does not: it is this container's
    # alone, so a container written here points at its data directory under
    # DEVDATA instead, which the daemon has whichever side made it, and which
    # is where its data belongs anyway.
    if _read_rec(project, instance).get("source") == "file":
        # The NAME of it, not a promise that it is there: _compose is on the
        # poll path (`ps`, `config`) and where the daemon makes this directory
        # itself, making it here would be a container launch every few seconds.
        # Compose does not care, since a missing --project-directory is only a
        # problem for a bind that has to resolve, which is `up` and `build`,
        # and those go through _dev_data_env, which does make it. Checked
        # against compose rather than assumed: `config -q`, `config --format
        # json` and `ps -aq` all exit 0 with the directory absent.
        pdir = (dev_data_dir(project, instance, make=False)
                or str(Path(appdata_root()) / _pname(project, instance)))
    else:
        # ...or the instance's own build tree, when it is pinned to a ref.
        # The SAME answer _plan gives, because the two are one command built
        # twice: the controller's runner uses this and an agent node gets the
        # plan, and the first version of this shipped with only the plan
        # changed, so a controller-run build quietly came from the project's
        # checkout while the row said it came from a branch.
        at = work_tree(project, instance)
        # ...and inside it, the folder the compose file is in.
        sub = compose_sub(project, instance)
        pdir = str((at if at is not None else WORKSPACE / project) / sub).rstrip("/")
    ep = env_path(project, instance)
    if ep.is_file() and cf is not None and cf.is_file():
        # The copy whose env_file lines name the instance's env, beside it,
        # written only when it differs: this is on the poll path.
        with contextlib.suppress(OSError):
            text = cf.read_text(encoding="utf-8")
            new = env_to_instance(text, str(ep))
            if new != text:
                copy = ENVDIR / f"{_pname(project, instance)}.compose.yml"
                if not copy.is_file() or copy.read_text(encoding="utf-8") != new:
                    copy.write_text(new, encoding="utf-8")
                cf = copy
    argv = [DOCKER, "compose", "--project-name", _pname(project, instance),
            "--project-directory", pdir, "-f", str(cf)]
    # ...and its override over it, its env_file lines pointed at the
    # instance's env as the base file's are, in a copy of its own.
    ov = override_file(project, instance)
    if ov is not None:
        if ep.is_file():
            with contextlib.suppress(OSError):
                text = ov.read_text(encoding="utf-8")
                new = env_to_instance(text, str(ep))
                if new != text:
                    copy = ENVDIR / f"{_pname(project, instance)}.override.yml"
                    if not copy.is_file() or copy.read_text(encoding="utf-8") != new:
                        copy.write_text(new, encoding="utf-8")
                    ov = copy
        argv += ["-f", str(ov)]
    if ep.is_file():
        argv += ["--env-file", str(ep)]
    return argv + list(args)


# ---------------------------------------------------------------------------
# this container's paths are not the daemon's
#
# The one thing about a remote daemon that is easy to forget and impossible to
# see: a bind mount's SOURCE is resolved by whoever runs the container, and
# that is the host. `/workspace/alpha` and `/devdata/alpha` mean
# something here and nothing over there, and docker does not error on a
# missing bind source, it creates an empty directory and mounts that. On Unraid the
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


def _pairs():
    """The mapping's pairs, from the node being addressed: its record's
    `config.paths` (docs/nodes.md §11; the row is where it is edited)."""
    nid = getattr(_node_ctx, "node", None) or _default_node()
    got = node_paths(nid) if node_paths and nid else {}
    return [(k, v) for k, v in got.items()]


def _synced_here(path):
    """Whether the node being addressed holds its projects as a synced copy
    (R162), which every agent node does unless taken off it (R164), and
    `path` is the projects root: its own /workspace holds the same trees at
    the same paths, so a compose's binds mean on it what they mean here
    (R163 step 4). A dev instance lives on its project's own nodes, which
    always hold it."""
    nid = getattr(_node_ctx, "node", None) or _default_node()
    n = queue.node(nid) if (queue is not None and nid) else None
    ws = str(WORKSPACE).rstrip("/") if WORKSPACE else ""
    return bool(n and ws and path.rstrip("/") == ws and n.get("kind") == "agent"
                and ((n.get("config") or {}).get("workspace") or "sync") == "sync")


def _node_mounts_at(path):
    """Whether the node being addressed reports a mount at exactly this
    path, from its census (nodes._census keeps `mounts`), or holds a synced
    copy there."""
    if _synced_here(path):
        return True
    nid = getattr(_node_ctx, "node", None) or _default_node()
    n = queue.node(nid) if (queue is not None and nid) else None
    for m in ((n or {}).get("reported") or {}).get("mounts") or []:
        if isinstance(m, dict) and str(m.get("path") or "").rstrip("/") == path \
                and m.get("mounted", True) and not m.get("stale"):
            return True
    return False


def host_map():
    """(container path -> host path, complaints about the pairs given).

    The node's "/container:/host" pairs (see _pairs). Each
    is checked against the mount it claims to describe: a host path has to end
    with that mount's own root path, so /devdata (root /appdata/builderbot-dev)
    accepts /mnt/cache/appdata/builderbot-dev and rejects /mnt/user/something.
    That is not proof, since two shares can end alike, but it catches the
    case this has to catch, which is a template whose two sides were edited
    apart.
    A rejected pair is dropped rather than used: no answer beats a wrong one,
    because a wrong one is the silent failure above wearing a fix.
    """
    roots, out, bad = _mount_roots(), {}, []
    root = None
    pairs = _pairs()
    # The projects at the same path on both machines is the ordinary
    # arrangement (a node holds its synced copy at /workspace, as this
    # container holds the original), so where nobody has written a pair for
    # it, /workspace maps to itself. A written pair still wins.
    ws = str(WORKSPACE).rstrip("/") if WORKSPACE else ""
    if ws and not any(h.strip().rstrip("/") == ws for h, _ in pairs) and _node_mounts_at(ws):
        pairs.append((ws, ws))
    for here, there in pairs:
        pair = f"{here}:{there}"
        here, there = here.strip().rstrip("/"), there.strip().rstrip("/")
        if not here.startswith("/") or not there.startswith("/"):
            bad.append(f"{pair} is not a /container:/host pair")
            continue
        # An identity pair is not a translation and there is nothing to check
        # it against: it says the daemon calls this path what we call it, which
        # is the sandbox-VM arrangement, the shares mounted over there at the
        # paths used over here. This container's mount table describes its own
        # mounts and says nothing about that machine's, so running the check
        # below on one would reject a mapping that is correct by construction.
        if here == there:
            out[here] = there
            # ...which makes it the one shape nothing above can catch, and it
            # is the shipped default. So the daemon is asked: an identity is
            # only TRUE of a daemon on another machine, which is what
            # sandbox_daemon() answers. Asked THROUGH that rather than by
            # reading the address here, because it is as often written with
            # the scheme left off as with it, and reading it directly reported
            # the shipped default as misconfigured.
            #
            # An agent node is the other machine that really does have this
            # path: it holds its synced copy of the projects at /workspace
            # (R163), so the identity is correct there for the same reason it
            # is correct on the sandbox VM, and saying otherwise put a warning
            # on every start once a second node was enrolled (B193). For any
            # other path its own census is the evidence, rather than the
            # address or an assumption about what a node must look like: it
            # lists what is mounted where on that machine.
            #
            # Left in place while the daemon is not the sandbox, the pair
            # claims that machine calls this path what we call it, and a
            # compose that believes it comes up on an empty directory.
            if not (sandbox_daemon() or _daemon_mounts(here)):
                bad.append(f"{here}:{there} says that machine calls this path "
                           f"what we call it, and its census reports no mount "
                           f"at {here}. Name the path its daemon really has")
        elif (root := roots.get(here)) is None:
            bad.append(f"{here} is not mounted in this container")
        elif root != "/" and not there.endswith(root):
            bad.append(f"{here} is mounted from {root}, which {there} "
                       f"does not end with: one side of the mapping moved")
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
# root the chown fails and takes the run down with it, measured on this box,
# "error while creating mount source path ...: chown ...: operation not
# permitted". The directory is left behind, so the SECOND press works. An
# intermittent-looking failure with a fixed cause.
#
# So the daemon makes it, in a container of its own. That is a `docker run`,
# which is root-equivalent on whichever machine answers, and acceptable only
# because that machine is the sandbox. Hence the gate below, and hence _guard
# recognizing these commands by rebuilding them rather than by allowing the
# verb: neither is load-bearing today, and both are what keeps this from
# becoming load-bearing by accident.

# Tiny, and on every registry. One pull per sandbox, the first time an instance
# is created rather than on a poll.
DEVDATA_IMAGE = "alpine"

# Every operation this module will ask the daemon to perform on that share.
_DEVDATA_OPS = {"mkdir": ["mkdir", "-p"], "mv": ["mv"], "test": ["test", "-d"]}

# What may follow /d/. Components separated by single slashes (a compose
# names /devdata/<instance>/config, which is two deep) with every component
# starting on a letter or digit, so `..` is not a name and nothing can climb
# out of the mount. No leading, trailing or doubled slash.
_DEV_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*$")


def sandbox_daemon():
    """Is the daemon a sandbox VM, a machine whose whole job is being wrecked?

    Which is the only daemon this talks to, so this is available()'s first
    check asked on its own, kept as the guard's own question rather than
    inherited, because it is what decides whether a `docker run` is allowed
    and a security check should not depend on a display function.

    The ADDRESS only, deliberately: this is asked while available() is still
    computing (source() reads host_map(), which reads this) so a version of
    it that consulted availability would call itself round in a circle. The
    stronger question, which is the one the guard asks, is verified_sandbox()
    below.
    """
    return docker_host().startswith("ssh://")


def verified_sandbox():
    """The guard's question: an ssh address AND a daemon carrying the stamp
    nodes/provision-linux.sh puts on the VM it made.

    An ssh address only proves somebody typed one. The label is the only thing
    that says the machine on the end is the box built to be wrecked, which is
    the entire reason running a container as root over there is acceptable.
    Read through the memo, so a run does not pay for a round trip the poll made
    thirty seconds ago, and never from the cache alone: an empty memo asks.
    """
    return bool(sandbox_daemon() and available_cached().get("on"))


def mkdir_root(path):
    """The share a mkdir on the daemon mounts to make this path, or "".

    The first component (/auxiliary for /auxiliary/plex-library) because
    that is the shape of a share, and it is what has to exist over there for
    the rest to be creatable as BuilderBot's own uid. Deliberately NOT a
    declared list: the VM's shares are the VM's business, and a field naming
    them on this container was one more thing to keep in step every time a
    share was added over there. The daemon being a sandbox is the boundary;
    what a compose file names plus a button press is the bound.

    "" for a path this will not touch: the share root itself (nothing below it
    to make, and docker creates a missing mount source as root, which is the
    failure this whole mechanism exists to avoid), or components that are not
    plain names, which is what keeps `..` and its relatives out of an argv.
    """
    parts = path.strip("/").split("/")
    if len(parts) < 2:
        return ""
    if all(_DEV_NAME.match(c) for c in parts):
        return "/" + parts[0]
    return ""


def _devdata_argv(op, *names, root=None):
    """One of the commands above, as the exact argv it will be run as.

    In one place because _guard rebuilds it from a candidate argv and compares
    against it, so what is allowed is these commands, not the verb they begin
    with. The root is the mount and the names are paths under it, which
    confines every one of them to it by construction rather than by checking;
    which roots may be named is mkdir_roots(), checked separately.

    Owned by whoever BuilderBot runs as. That is the point of doing it this
    way rather than letting docker create a missing bind source itself: docker
    makes it as root and then chowns it, which on a share that squashes root
    fails and takes the run down.
    """
    return [DOCKER, "run", "--rm", "-u", f"{os.getuid()}:{os.getgid()}",
            "-v", f"{(root or appdata_root()).rstrip('/')}:/d", DEVDATA_IMAGE,
            *_DEVDATA_OPS[op], *(f"/d/{n}" for n in names)]


def _devdata_run(op, *names, root=None, quiet=False):
    """Run one. True if it did what it was asked."""
    r = _run(_devdata_argv(op, *names, root=root), timeout=300)
    if r["code"] != 0:
        if not quiet:
            print(f"[devapp] {op} {' '.join(names)} failed on the daemon: "
                  f"{r['out'].strip()[:200]}", file=sys.stderr, flush=True)
        return False
    return True


def dev_data_dir(project, instance=MAIN, make=True):
    """The instance's data directory, made and named on the VM.

    DEVDATA is a path on the VM and the VM makes the directory, through the
    throwaway container above. So it does not have to be mounted on this side
    at all: one path meaning one thing, instead of a path here, a path there
    and a mapping between them that nothing could check.

    None when the mkdir failed. The caller then leaves BB_DEV_DATA unset and
    the compose fails loudly, which beats mounting an empty directory and
    calling it the cache drive.

    On an agent node the directory is the AGENT's to make: it travels in the
    plan's `dirs` and the agent makes it before the first step, so the path
    is answered whether or not the node has an ssh address. An agent that
    reports docker but no sshd (a node that is itself a container) has no
    address and used to get no data directory at all, so its up ran with the
    bind unplanned (found running this suite inside builderbot-dev, 15 Sep).
    """
    name = _pname(project, instance)
    if not sandbox_daemon():
        if not _agent_docker():
            return None
        return posixpath.join(appdata_root(), name)
    if make and not _devdata_run("mkdir", name):
        return None
    return posixpath.join(appdata_root(), name)


def appdata_root(node_id=None):
    """Where THIS node keeps its dev instances' data.

    The node's own `appdata` store where it reports one, and DEVDATA where it
    does not: a missing field is answered rather than refused.
    """
    nid = node_id or getattr(_node_ctx, "node", None) or _default_node()
    n = queue.node(nid) if (queue is not None and nid) else None
    st = ((n or {}).get("reported") or {}).get("stores")
    rec = st.get("appdata") if isinstance(st, dict) else None
    path = str((rec or {}).get("path") or "") if isinstance(rec, dict) else ""
    return path or DEVDATA


def _daemon_mounts(path):
    """Does the node being addressed report a mount at this path?

    The census lists what is mounted where on that machine, so this is the
    one question in here that is answered with evidence from the other end
    rather than inferred from an address (B193). False for a node that has
    not reported, which fails the way the check always did: it says so.
    """
    if _synced_here(path):
        return True
    nid = getattr(_node_ctx, "node", None) or _default_node()
    n = queue.node(nid) if (queue is not None and nid) else None
    ms = ((n or {}).get("reported") or {}).get("mounts")
    if not isinstance(ms, list):
        return False
    want = path.rstrip("/") or "/"
    return any(isinstance(m, dict) and m.get("mounted")
               and str(m.get("path") or "").rstrip("/") == want for m in ms)


def _agent_docker():
    """Is the node being addressed an agent node whose census reports
    docker? That node runs compose as a job and makes bind directories
    itself, so it needs no ssh address for a data directory to exist."""
    nid = getattr(_node_ctx, "node", None) or _default_node()
    n = queue.node(nid) if (queue is not None and nid) else None
    return bool(n and n.get("kind") == "agent"
                and ((n.get("reported") or {}).get("docker")))


def check_paths(node_id=None):
    """Do this container and the node's daemon mean the same directory by
    the projects share? (roadmap #13)

    Under an identity mapping host_map() accepts the pair unchecked and
    problems() has nothing to say, which is correct, because this container's
    mount table says nothing about the other machine's, so NOTHING verified
    that the two sides still agree, and the failure is silent twice over: docker
    answers a missing bind source by creating an empty directory, and the
    row says nothing. It bit on 27 Aug: /workspace was repointed here while
    the VM still mounted the parent directory, every project path was wrong
    by one component, and it took three silent rounds to settle. Make dirs
    raised the stakes since: a mismatch now builds a stray tree over there.

    So: a marker directory is made under the share HERE, and the daemon is
    asked whether it can see it at the path the mapping says the node calls
    the share. Through the same one-shot container the dev-data directory is
    made with (_devdata_argv, `test`), so the guard's rules cover it: the
    mount is a share root and the name is under it. The marker is removed
    whatever happens. Off the poll, because this is for when something changed.

    Three answers, never a guess: True (found), False (a clean "not there"),
    None with a sentence (the daemon could not be asked, or refused).
    """
    with on_node(node_id):
        mapping = host_map()[0]
        here = str(WORKSPACE).rstrip("/")
        # The identity is the shipped default and the rule (path parity), so
        # a mapping that says nothing about the share means "the same path".
        there = (mapping.get(here) or here).rstrip("/")
        out = {"same": None, "here": here, "there": there, "why": ""}
        if not sandbox_daemon():
            out["why"] = ("this node's daemon is not addressed as a sandbox, so "
                          "nothing can be run on it to look")
            return out
        name = f"bb-path-check-{os.urandom(4).hex()}"
        marker = Path(here) / name
        try:
            marker.mkdir()
        except OSError as e:
            out["why"] = f"could not make a marker under {here} here: {e}"
            return out
        try:
            # The probe mounts a share ROOT and names the rest, which is the
            # shape the guard rebuilds: /mnt/user/projects becomes the mount
            # /mnt and the name user/projects/<marker>.
            parts = there.strip("/").split("/")
            root = "/" + parts[0]
            rel = "/".join(parts[1:] + [name])
            r = _run(_devdata_argv("test", rel, root=root), timeout=120)
        finally:
            try:
                marker.rmdir()
            except OSError:
                pass
        if r["code"] == 0:
            out.update(same=True, why=(f"the same directory: a marker made under {here} "
                                       f"here was found at {there} on the node"))
        elif r["code"] == 1 and not r["out"].strip():
            # `test -d` says no with nothing on its output; a daemon that
            # could not be reached says so.
            out.update(same=False, why=(f"NOT the same directory: a marker made under "
                                        f"{here} here was not at {there} on the node. "
                                        "A compose over there would bind an empty tree, "
                                        "and Make dirs would build one"))
        else:
            out["why"] = ("could not ask the daemon: "
                          + (r["out"].strip()[:200] or f"exit {r['code']}"))
        return out

def _build_env(project, instance=MAIN):
    """BB_BUILD_REV, BB_BUILD_AT, BB_BUILD_VERSION and BB_BUILD_TAG (the
    version as an image tag can carry it) for a compose whose
    build args opt in with them: the commit the build is from (the tree's
    HEAD, or the pinned ref's tip), when, and the project's version in its
    file form. The same convention as BB_DEV_DATA, and the same reason: a
    compose file cannot know what it is being built from, and an image that
    cannot say which commit it runs is one nobody can reason about. Found
    when builderbot-dev came up with an empty stamp (15 Sep): CI passes the
    three as build args, a dev build passed nothing.
    """
    ref = (str(_read_rec(project, instance).get("ref") or "").strip()
           if instance else "")
    # A container with no project tree behind it (nginx's, one made with
    # bb container new) has no commit to stamp: asked anyway, git said
    # "cannot change to /workspace/nginx-NODE" in the log on every
    # update (12 Oct), as _head and _dirty already knew not to.
    tree = (WORKSPACE / project).is_dir()
    r = (_run(["git", "-C", str(WORKSPACE / project), "rev-parse", ref or "HEAD"], timeout=10)
         if tree else {"code": 1, "out": ""})
    out = {"BB_BUILD_AT": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())}
    if r["code"] == 0 and r["out"].strip():
        out["BB_BUILD_REV"] = r["out"].strip()
    # No version is a blank stamp, never a failed build: the module is
    # beside this one on the dashboard and absent in a module-level test.
    with contextlib.suppress(Exception):
        import version                                 # noqa: PLC0415
        # The IDENTITY form, which is what tools/build-image-here.sh stamps a
        # production image with, so one commit built either way answers with
        # one string. It used to take `file`, the docker-tag-safe form, whose
        # whole job is that it cannot carry `+`: the same build then read
        # 0.5.0-dev.1633+59d8912 on production and 0.5.0-dev.1633-59d8912 on
        # the dev instance, and the rule that makes this string the first
        # thing anybody compares turned one build into two (B158).
        forms = (version.render(project) or {}).get("forms") or {}
        f = forms.get("semver")
        if f:
            out["BB_BUILD_VERSION"] = str(f)
        # ...and the same version in the form an image tag can carry, with
        # no `+` (docker refused "...:0.5.0-dev.6+ba86e7d" as an invalid
        # reference, 20 Oct): the one to put after a colon.
        t = forms.get("file")
        if t:
            out["BB_BUILD_TAG"] = str(t)
    # The docker group's id on the instance's node (R86), for a compose that
    # runs a service as a member of it to reach the daemon's socket.
    with contextlib.suppress(Exception):
        nid = _instance_node(project, instance) if instance else ""
        g = (node_reported(nid) or {}).get("docker_gid") if nid and node_reported else None
        if isinstance(g, int):
            out["BB_DOCKER_GID"] = str(g)
    return out


def _dev_data_env(project, instance=MAIN):
    """BB_DEV_DATA for a compose that opts in with ${BB_DEV_DATA}/... paths.
    Cache-backed volumes by convention, nothing forced on a compose that never
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
    what the example already spells, with its own comments explaining each
    one, which is the half a list of names throws away. Seeded, not saved:
    nothing reaches disk until Save, so `missing_env` keeps answering about
    the stored file and Up stays honestly dead until the values are real.
    """
    try:
        example = example_file(project, instance).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if not example.strip():
        return ""
    return ("# Started from this project's .env.example. Fill in the values\n"
            "# and press Save; nothing is written until you do.\n\n"
            + example.rstrip() + "\n")


def write_env(project, text, instance=MAIN):
    if len(text or "") > 65536:
        return {"error": "that env file is over 64KB, and this holds settings, "
                         "not data"}
    # Never a variable that steers compose itself (COMPOSE_CONTROL).
    ctl = compose_control(text)
    if ctl:
        return {"error": compose_control_refusal(ctl)}
    try:
        ENVDIR.mkdir(parents=True, exist_ok=True)
        env_path(project, instance).write_text(text or "", encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write the env file: {e}"}
    _bump()
    return {"ok": True}


_VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)([^}]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def required_vars(compose_text):
    """The variables a compose file cannot do without: referenced as ${X}
    or $X with no default, or ${X:?...}."""
    out = set()
    for m in _VAR_REF.finditer(compose_text or ""):
        if m.group(3):
            out.add(m.group(3))
            continue
        name, rest = m.group(1), m.group(2) or ""
        if not rest or rest.startswith(("?", ":?")):
            out.add(name)
    return out


def defaulted_vars(compose_text):
    """The variables a compose file answers for itself (${X:-99}, ${X-99})
    and never also needs bare: the only kind the env gate may leave unset."""
    out = set()
    for m in _VAR_REF.finditer(compose_text or ""):
        if m.group(1) and (m.group(2) or "").startswith((":-", "-")):
            out.add(m.group(1))
    return out - required_vars(compose_text)


def missing_env(project, instance=MAIN):
    """Keys the repo's example declares that the dev env does not set,
    except the ones the compose file answers for itself (${PUID:-99}): the
    example lists those so they CAN be set, and asking for nine of them
    before a first Up was the operator's report (15 Sep). A key the file
    never names stays required: the example says it matters, and this side
    cannot tell what reads it.""" 
    try:
        example = example_file(project, instance).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return []
    have = set(_keys(read_env(project, instance)))
    cf = compose_file(project, instance)
    try:
        text = cf.read_text(encoding="utf-8", errors="replace") if cf else ""
    except OSError:
        text = ""
    optional = defaulted_vars(text)
    return [k for k in _keys(example) if k not in have and k not in optional]


def _gate_env(project, instance=MAIN):
    """Rewrite the env as the new example, old values kept in comments.

    The operator fills the new keys in and presses Up; their old answers are
    right there to copy rather than remembered or lost.
    """
    old = read_env(project, instance)
    try:
        example = example_file(project, instance).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        example = ""
    stamp = time.strftime("%Y-%m-%d %H:%M")
    kept = "\n".join("# old: " + ln for ln in old.splitlines() if ln.strip())
    text = (f"# The rebuild on {stamp} found new settings in .env.example.\n"
            f"# Fill them in below (your previous env is preserved in the\n"
            f"# 'old:' comments at the bottom) and then press Up.\n\n"
            f"{example.rstrip()}\n\n"
            f"# ---- what this file held before the rebuild ----\n{kept}\n")
    write_env(project, text)


# ---------------------------------------------------------------------------
# state

def overview(node_id=None):
    """Every instance, and everything else on the daemon, from ONE ps.

    `node_id` is the manager's picker: the containers come from that node's
    daemon, and the instance rows are the ones BOUND there: an instance
    belongs to the node it was created against, and showing it under every
    daemon would offer buttons that act somewhere other than where the row
    says. Unset means the default docker node, which is the arrangement that
    predates the picker.

    state() asks the daemon twice per instance (is it running, does anything
    exist) which is fine for one row and absurd for a manager listing all of
    them. The container list already answers both for everything at once: an
    instance's containers are the ones whose compose project is its name. So
    the whole page costs one docker call plus what is already on disk.

    What it deliberately does NOT compute is the expensive half: risks,
    problems, the parsed compose config. Those are per-instance questions
    asked when somebody acts on one, and state() still answers them.
    """
    # A daemon that is not there is asked nothing. `docker ps` over ssh to a
    # VM that is off sits until its 25-second timeout, so the manager spent
    # that long on a spinner and then showed one error line, when everything
    # the page can honestly say (which instances exist, what each was built
    # from, what its env still wants) is on this side of the wire and needs no
    # daemon at all. The rows come back either way; what the daemon owns is
    # whether they are running, and that stays unknown rather than guessed.
    picked = node_id or (node_for() if node_for else "")
    with contextlib.ExitStack() as ctx:
        ctx.enter_context(read_scope())
        if picked:
            ctx.enter_context(on_node(picked))
        return _overview_here(picked)


def _overview_here(picked):
    with _timed("docker:available"):
        got = available_cached()
    with _timed("docker:ps"):
        cs = containers() if got.get("on") else {
            "error": got.get("why") or "no docker daemon is reachable from here",
            "containers": []}
    by_proj = {}
    for c in cs["containers"]:
        by_proj.setdefault(c["project"], []).append(c)
    store = _load()
    out = []
    # The STORE's instances, not instances(): that one synthesises `main` for
    # any project with a compose file, which is right for "what may I act on"
    # and wrong here: it filled the manager with a row per project that had
    # never been sent anywhere, indistinguishable from ones that had. A record
    # exists because somebody pressed Send.
    # Nothing was asked, or asking failed, and either way nothing is known: the
    # client draws the row from the store and refuses to say running or
    # stopped. False on those fields would be a claim, and a daemon that died
    # inside the availability memo answers the same as one that was never
    # there.
    blind = not got.get("on") or bool(cs["error"])
    for project in sorted(store):
        # Once per PROJECT, not per instance: every instance of a project is
        # built from the same working copy, so the answer cannot differ
        # between them and asking git twice for it would be waste.
        filed = is_file_source(project)
        head, dirty = ("", False) if filed else (_head(project), _dirty(project))
        for inst in sorted(store[project]):
            # ...except an instance pinned to a ref, which is built from its
            # own tree and answers for that rather than for the working copy.
            pin = str((store[project][inst] or {}).get("ref") or "").strip()
            ihead, idirty = (_head(project, inst), False) if pin else (head, dirty)
            # The picker's node only, resolved exactly as the ACTIONS on
            # the row resolve it (_instance_node): the record's node, else
            # the PROJECT's, else the default. Those two chains used to
            # differ by the middle step, so an unbound instance of a project
            # bound to one node was listed under a different one: every
            # button on the row acting somewhere other than where the row
            # said, and two projects' containers appearing under a machine
            # nobody had ever sent them to.
            if picked and _instance_node(project, inst) != picked:
                continue
            # A container written here that compose is still reading, which
            # may yet be refused (B239).
            if time.time() - float((store[project][inst] or {}).get("pending") or 0) < PENDING_S:
                continue
            pn = _pname(project, inst)
            mine = by_proj.get(pn, [])
            rec = _read_rec(project, inst)
            same_daemon = rec.get("daemon") == daemon_id()
            # Whose sessions can reach it: the project it belongs to works
            # on a node, and this row is drawn under the daemon of another
            # (the project moved after this was built, pin_to_current_node)
            # means out of reach, said on the row (R79, the operator 25 Sep).
            whose = owner_of(project, inst, rec)
            own = nodes_of(whose) if whose else []
            # Where it belongs too: one of the nodes the project hosts its
            # containers on, or a node it was shipped to on purpose (R166).
            # Its sessions reach it there by its published ports, so neither
            # is out of place (the operator, 12 Oct: a hosting node's row
            # said so in red).
            hosted = picked in (hosts_of(whose) if whose and hosts_of else []) or bool(rec.get("ship"))
            out.append({
                "astray": ", ".join(node_name(n) for n in own) if own and picked and picked not in own and not hosted else "",
                "project": project, "instance": inst, "name": pn,
                # The project it belongs to, or "" for none: whose sessions
                # may see it and work on it, and the group it is drawn in.
                "owner": owner_of(project, inst, rec),
                # Its project was deleted (moved to the trash): drawn as
                # "X (deleted)" until X is restored or it is moved (8 Oct).
                "owner_gone": owner_gone(owner_of(project, inst, rec)),
                "owner_label": owner_label(owner_of(project, inst, rec)),
                "running": any(c["state"] == "running" for c in mine),
                "exists": bool(mine),
                "containers": len(mine),
                # Start on boot, as the daemon says for this instance's own
                # containers (R122). The listing's top-level containers are
                # the ones that belong to no instance, so the row's switch
                # read a list that never held its containers and always said
                # off (found walking the dev instance, 5 Oct).
                "boot": any(c.get("boot") for c in mine),
                # Ports from the containers themselves rather than from the
                # compose file: what is published is what the daemon says it
                # published, and a stopped instance publishes nothing.
                "ports": sorted({p for c in mine for p in c["ports"]}),
                "open_ports": sorted({p for c in mine for p in c.get("open") or []}),
                # The same rule state() uses: a build belongs to the daemon
                # it happened on, and a record from another names nothing here.
                "built_rev": rec.get("rev", "") if same_daemon else "",
                "built_at": rec.get("at", 0) if same_daemon else 0,
                # The ref that build was made from, stamped when it was made.
                # A different question from `ref` below, which is the pin the
                # NEXT build will use. Repointing an instance does not rebuild
                # it, so reading the pin to describe what is already built
                # names a branch that may never have been built here.
                "built_ref": rec.get("built_ref", "") if same_daemon else "",
                "await_env": bool(rec.get("await_env")) if same_daemon else False,
                # A build marker with no job behind it: BuilderBot restarted
                # while it was building (the Artifacts row said so until it
                # stopped following containers, 10 Oct).
                "interrupted": bool(same_daemon and rec.get("building_since")
                                    and not (job_view(project, inst) or {}).get("running")),
                "compose": compose_file(project, inst) is not None,
                # Which of the project's compose files, when not the root's.
                "compose_path": str(rec.get("compose") or ""),
                # ...and the one laid over it, when it has one.
                "override": str(rec.get("override") or ""),
                "source": "file" if filed else "project",
                # A file read and one git call. risks/problems stay out:
                # those are judgements to put in front of somebody about to
                # press a button, and belong on the row that asked.
                "missing_env": missing_env(project, inst),
                # A written container's revision is its definition, so
                # "changed" can mean what it means everywhere else (the source
                # has moved since the build) instead of being permanently true
                # because there was no revision to compare.
                "changed": (not (rec.get("rev") if same_daemon else "")
                            or (same_daemon
                                and rec.get("rev") != (built_rev(project, inst)
                                                       if filed else ihead))
                            or (idirty and not filed)),
                # What the NEXT build will use, when it is pinned to
                # something: the Ref line's own value, and what the row warns
                # about when it differs from what is already built.
                "ref": pin,
                # Each container of the instance, so the row can list them:
                # an instance is one thing to Up and Down and three things
                # to look at (the operator, 15 Sep).
                "services": [{"service": c.get("service", ""), "name": c.get("name", ""),
                              "state": c.get("state", ""), "status": c.get("status", ""),
                              "ports": c.get("ports", []), "image": c.get("image", "")}
                             for c in sorted(mine, key=lambda c: (c.get("service", ""), c.get("name", "")))],
                "route": route_view(project, inst,
                                    sorted({p for c in mine for p in c["ports"]}),
                                    # The project's own service first: the
                                    # lowest published port was the lab's
                                    # Gitea's ssh, which no browser reads.
                                    prefer=sorted({p for c in mine
                                                   if c.get("service") in (_slug(project), _slug(inst))
                                                   for p in c["ports"]})),
                "changed_why": ("moved" if same_daemon and rec.get("rev")
                                and rec.get("rev") != head
                                else "dirty" if dirty and same_daemon and rec.get("rev")
                                else ""),
            })
    # `stale`: the daemon's half is a listing kept from before the node's
    # current job began. Rows are drawn ghosted, as for a daemon that did not
    # answer, and the revision the job moves brings the next ask.
    return {"error": cs["error"], "blind": blind, "stale": bool(cs.get("stale")),
            "node": picked,
            # TWO QUESTIONS, kept apart, which is the whole of B111. "Can we
            # ACT" is availability: on an agent node compose runs on the
            # agent, against that machine's own socket, so a controller that
            # cannot ssh there changes nothing about whether Up works. "Can we
            # SEE" is the listing, which is still a `docker ps` from here and
            # does need the ssh. Folding the second into the first ghosted
            # every control on a node where all of them would have worked.
            "on": bool(got.get("on")), "why": got.get("why") or "",
            # WHICH DAEMON THIS ANSWER IS ABOUT, in its own words. The page had
            # only the status poll's copy, which is the DEFAULT node's, so the
            # line under the picker named a machine the picker was not on, and
            # said so in an address, which is the one thing there that looks
            # like proof.
            "src": source(),
            "instances": out,
            # The running job, if there is one. The manager used to look for
            # it on the status snapshot under a key nothing has ever set, so
            # `busy` was permanently false: a row kept saying "never built"
            # through its own build, and Up/Rebuild/Remove stayed live for a
            # second click the server then refused. It belongs here, with the
            # rest of what this page draws from.
            # While it is running OR while it has something to say about how it
            # ended. Dropped the moment it stopped, a build that failed (or one
            # stopped on purpose, which ends a job with no other trace) left
            # the row showing whatever state it happened to be in and no account
            # of why. It is replaced by the next job, which is when it stops
            # being the answer to "what just happened here".
            "job": latest_job(),
            # Only the ones that are not an instance of ours: the instances
            # above already account for those, and listing them twice would
            # make the page look like the daemon is running double. Each with
            # the project it was put under, read once for the node.
            "containers": [c | {"owner": held.get(c["name"], ""),
                                "owner_gone": owner_gone(held.get(c["name"], "")),
                                "owner_label": owner_label(held.get(c["name"], ""))}
                           for held in [_owners().get(picked or _node_here()) or {}]
                           for c in cs["containers"] if not c["ours"]]}


PENDING_S = 120                  # how long a container being checked stays unlisted


def forget_container(name):
    """Drop the record and the files. Only ever for one this wrote.

    Including the env, which it did not before. For a PROJECT's instance
    Remove deliberately keeps the env and the data (the promise is that
    sending it again finds them) but a written container has nowhere to
    come back FROM, which is the argument the compose file below is deleted
    on, and it applies to the env just the same. Kept, it left one file per
    removed container in /config/devenv with nothing that would ever read it
    again.

    Returns the env files it removed, for the log.
    """
    with _lock:
        d = _load()
        if name in d:
            del d[name]
            write_json(FILE, d)
    try:
        shutil.rmtree(containers_dir(name), ignore_errors=True)
    except OSError:
        pass
    gone = []
    f = env_path(name, MAIN)
    if f.is_file():
        with contextlib.suppress(OSError):
            f.unlink()
            gone.append(f.name)
    return gone


def node_name(nid):
    """A node's name for a sentence, or the id when the registry is not here."""
    n = queue.node(nid) if queue and nid else None
    return (n or {}).get("name") or nid or "none"


def nodes_of(whose):
    """The node set a project works on, primary first (R82), or []. None
    when nothing here can say: a module loaded without the controller's
    wiring (a probe, a test driving it in process) has no projects' settings
    to read, and the rule that needs them does not apply."""
    if project_nodes is None and project_node is None:
        return None
    got = project_nodes(whose) if project_nodes else None
    if got is None:
        own = (project_node(whose) if project_node else "") or ""
        got = [own] if own else []
    return [str(n) for n in got if n]


def on_project_node(whose, node="", ship=False):
    """(why, node): the node a container for project `whose` goes to, or the
    reason it cannot go anywhere. One rule, said in one place: a container
    lives on one of its project's nodes (R79 makes any other unreachable
    from the project's sessions), so `node` may only be one of those, and
    nothing means the primary. The exception is `ship` (R166): a container
    sent on purpose to a node the project is not on, whose image is built on
    one of the project's own nodes and shipped there, so the project's
    source never reaches it; the project still needs a node to build on."""
    own = nodes_of(whose)
    if own is None:
        return "", str(node or "")
    if not own:
        return (f"{whose} has no node, so there is nowhere to make its container: "
                "set its node in the project's settings first", "")
    if ship and node:
        return "", str(node)
    if node and str(node) not in own:
        return (f"{whose} works on {', '.join(node_name(n) for n in own)}, and a container "
                "for it anywhere else is out of reach of its sessions", "")
    return "", str(node) if node else own[0]


def instance_key(project, name):
    """The key a typed container name is recorded under: its slug, or MAIN
    for the project's own name. The default instance is named after the
    project, so asking for that name by hand is asking for that container,
    not a second one beside it; before this, the name a person naturally
    typed into "New container from X" was refused as a clash with X's own
    container, which nobody had built yet (the operator, 25 Sep)."""
    slug = _slug(name) or ""
    return MAIN if slug and slug == _slug(project) else slug


def _taken(project, slug, d):
    """Why the key `slug` is not free for a new container of `project` in
    the store `d`, or "". Not one the project has, and not one that another
    project has taken: the name no longer carries the project, so two of
    them asking for `dev` would be one compose project, one env file and one
    data directory wearing two rows, which is the collision the old
    spelling prevented by being long, and this prevents by asking."""
    if slug in (d.get(project) or {}):
        return (f"{project} already has its own container, {_pname(project, MAIN)}, "
                "on the Containers page: Build or Rebuild builds it there"
                if slug == MAIN else f"{project} already has an instance called {slug}")
    return name_clash(project, slug)


def new_refusal(project, key):
    """Why a new container keyed `key` (instance_key's answer) cannot be
    made for this project, or "": said before a session's asked one goes to
    a person, who would otherwise be answering a request no answer can
    build, and again by create_instance itself."""
    if not key:
        return "an instance needs a name with a letter or digit in it"
    if compose_file(project) is None:
        # Where BuilderBot looks, said: a session that wrote its compose
        # somewhere else read "no compose file" as not having one at all,
        # and went to bb container new, which builds from an empty
        # directory (B329).
        return (f"{project} has no compose file at its root to make an instance of: "
                f"{', '.join(COMPOSE_NAMES)} is where it is looked for")
    return _taken(project, key, _load())


def create_instance(project, name, node="", owner=None, ship=False, compose=""):
    """Register a new instance of a project. Nothing is built or started.

    `owner` is the project it belongs to when the caller said (another one,
    or "" for none); None is the default, the project it is built from.

    `node` is which docker-host the instance is bound to: the daemon every
    action on it will address. Empty means the default node, resolved at USE
    rather than stored, so an instance made before a second node existed
    follows the default when it moves.

    The name is slugged the same way it will be when it reaches a compose
    call, and checked against the slug rather than the typing, because
    `My App` and `my-app` are the same instance and the second should be
    refused rather than silently becoming the first.
    """
    slug = instance_key(project, name)
    why = new_refusal(project, slug) or compose_ok(project, compose)
    if why:
        return {"error": why}
    # A container lives on the node of the project it belongs to and nowhere
    # else: a session reaches only its own project's containers on its own
    # node (R79), so one anywhere else is out of reach of the work it is for
    # (the operator, 25 Sep). The project's node is where it goes; a node
    # named that differs is refused, and a project with no node has to be
    # given one first. A container for no project may go where it is asked.
    whose = project if owner is None else owner
    picked = str(node or "")
    # Sent to a node the project is not on (R166): shipped, never built there.
    ship = bool(ship and picked and whose and picked not in (nodes_of(whose) or []))
    if whose:
        why, node = on_project_node(whose, node, ship=ship)
        if why:
            return {"error": why}
        # Named by the caller: bound to it. Not named: the record carries no
        # node and follows its project's primary, so a project moved later
        # takes an instance that was never built along (pin_to_current_node
        # keeps a built one where it is).
        node = picked
    with _lock:
        d = _load()
        # Asked again under the lock that writes it: two sends at once.
        why = _taken(project, slug, d)
        if why:
            return {"error": why}
        rec = _rec(d, project, slug)
        if node:
            rec["node"] = str(node)
        if ship:
            rec["ship"] = True
        # The file Send was pressed on, when it is not the root's own: what
        # every build of this container comes from from now on.
        if compose and compose != next((n for n in COMPOSE_NAMES
                                         if (WORKSPACE / project / n).is_file()), ""):
            rec["compose"] = str(compose)
        # Stored the way owner_of reads it: nothing for the default.
        if owner is not None and owner != project:
            rec["for"] = str(owner)[:100]
        write_json(FILE, d)
    _bump()
    return {"ok": True, "project": project, "instance": slug,
            "name": _pname(project, slug)}


def set_ref(project, instance, ref):
    """Pin an instance to a branch (or a commit), or clear it with "".

    What it changes is where the next BUILD comes from, and nothing else: the
    running containers, the env and the data are the instance's own either
    way. Validated against the project's own repository rather than taken as
    given, because this string reaches `git checkout`, and refusing an
    unknown ref here is a sentence, where finding out at build time is a
    failed job.
    """
    ref = " ".join(str(ref or "").split())[:120]
    if instance not in (_load().get(project) or {}):
        return {"error": f"{project} has no instance called {instance}"}
    if ref:
        repo = WORKSPACE / project
        if not (repo / ".git").exists():
            return {"error": f"{project} is not a git repository, so there is "
                             "no branch to build from"}
        r = _run(["git", "-C", str(repo), "rev-parse", "--verify",
                  "--quiet", ref + "^{commit}"], timeout=15)
        if r["code"] != 0:
            return {"error": f"{project} has no branch or commit called {ref}"}
    with _lock:
        d = _load()
        rec = _rec(d, project, instance)
        if ref:
            rec["ref"] = ref
        else:
            rec.pop("ref", None)
        write_json(FILE, d)
    _bump()
    return {"ok": True, "ref": ref}


def owner_of(project, instance=MAIN, rec=None):
    """The project an instance or a written container belongs to, or "".

    Which project's sessions may see it and work on it, which group the
    Containers page draws it in and which notebook lists it: one setting for the
    three (the operator, 24 Sep). Stored as `for` and read by presence. No
    `for` is the default: the project it was built from, or none for a
    container written here, which has no project behind it. An empty `for`
    is none, set on purpose.
    """
    rec = _read_rec(project, instance) if rec is None else rec
    if "for" in rec:
        return str(rec.get("for") or "")
    return "" if rec.get("source") == "file" else project


# registry.label, set by the server (R154): the name a deleted project was
# shown under, which the registry keeps after its directory is gone.
label_of = None


def owner_label(owner):
    if owner == SYSTEM:
        return SYSTEM
    return (label_of(owner) if label_of and owner else owner) or ""


def owner_gone(owner):
    """True when a container's project is no project any more: deleted to
    the trash, its records kept under its name, so a restore gives every one
    of them back (the operator, 8 Oct)."""
    return bool(owner) and owner != SYSTEM and not (WORKSPACE / owner).is_dir()


def move_instance(project, instance, to):
    """Move a project's own instance to project `to` (the operator, 8 Oct:
    MediaReducer-Dev's dev container to MediaReducer before the old project
    goes). Recorded under `to` as the instance whose compose name is the one
    it already has, so its containers, env file and data directory stay
    exactly where they are; from then on it builds from `to`'s tree and is
    `to`'s. A written container is no project's build and moves with its
    project picker (set_owner) instead."""
    to = str(to or "").strip()
    if not to or to == project:
        return {"error": "name another project to move it to"}
    rec = _read_rec(project, instance)
    if not rec:
        return {"error": f"no instance {instance} of {project}"}
    if rec.get("source") == "file":
        return {"error": "a container written here is built from its own compose file, not a "
                         "project's: give it to another project with its project picker"}
    if not project_has_compose(to):
        return {"error": f"{to} has no compose file at its root to build this from"}
    node = _instance_node(project, instance)
    why, _ = on_project_node(to, node)
    if why:
        return {"error": why}
    name = _pname(project, instance)
    inst = instance_key(to, name)
    with _lock:
        d = _load()
        if inst in (d.get(to) or {}):
            return {"error": f"{to} already has a container called {name}"}
        r = (d.get(project) or {}).pop(instance, None)
        if r is None:
            return {"error": f"no instance {instance} of {project}"}
        if not d.get(project):
            d.pop(project, None)
        # Pinned where it is: its data directory is on that node, and a
        # record with no node would follow `to`'s primary instead.
        if node:
            r["node"] = str(node)
        # Its owner was the default (the project it was built from): now it
        # is `to`'s default. One given elsewhere on purpose stays given.
        if "for" not in r or r.get("for") == to:
            r.pop("for", None)
        # A branch of the old repository means nothing in the new one.
        ref = r.pop("ref", None)
        d.setdefault(to, {})[inst] = r
        write_json(FILE, d)
    _bump()
    return {"ok": True, "project": to, "instance": inst, "name": name, "was": project,
            "dropped_ref": ref or ""}


def set_owner(project, instance, owner):
    """Which project an instance or a written container belongs to: a
    project's name, or "" for none. server.py has checked that the name is a
    project; this stores it the way owner_of reads it, with no `for` at all
    when the answer is the default."""
    owner = str(owner or "").strip()[:100]
    # Only to a project on the node it is on: given to one that works
    # elsewhere it would be out of reach of that project's sessions (R79).
    if owner and owner != project:
        here = _instance_node(project, instance)
        own = nodes_of(owner)
        if own is not None and not own:
            return {"error": f"{owner} has no node: set one in its settings before giving it a container"}
        if own and here and here not in own:
            return {"error": f"{_pname(project, instance)} is on {node_name(here)} and {owner} works on "
                             f"{', '.join(node_name(n) for n in own)}: its sessions could not reach it"}
    with _lock:
        d = _load()
        if instance not in (d.get(project) or {}):
            return {"error": f"{project} has no instance called {instance}"}
        rec = _rec(d, project, instance)
        if owner == ("" if rec.get("source") == "file" else project):
            rec.pop("for", None)
        else:
            rec["for"] = owner
        write_json(FILE, d)
    _bump()
    return {"ok": True, "owner": owner}


def session_net_own(node_id):
    """What each project owns on `node_id`, for its agent to keep each session
    to its own project's network (R79): the compose projects of the instances
    bound there, under the project each belongs to, and the containers the
    operator gave a project there, by name. {project: {"compose", "names"}}.
    The project a container belongs to is the Containers page's: the same answer
    decides whose sessions may work on it and whose may reach it."""
    out = {}
    blank = lambda: {"compose": set(), "names": set(), "peers": set(), "hosts": set()}  # noqa: E731
    for project, insts in _load().items():
        for inst, rec in insts.items():
            owner = owner_of(project, inst, rec)
            if owner and _instance_node(project, inst) == node_id:
                out.setdefault(owner, blank())["compose"].add(_pname(project, inst))
    for name, owner in (_owners().get(node_id) or {}).items():
        out.setdefault(owner, blank())["names"].add(name)
    # ...and what each project that can have a session HERE holds on its
    # other nodes (R82): the published ports of its containers there, from
    # what those nodes report, and the whole address of a node that is not a
    # sandbox (a Mac, Windows, a guest), which has no containers to narrow
    # to. The project's set is the operator's; a node outside it is never
    # named, so a session reaches its own project's things and no other.
    sets = all_project_nodes() if all_project_nodes else {}

    def held_on(project, nid):
        """The compose projects and container names `project` owns on `nid`."""
        mine = {_pname(p, i) for p, insts in _load().items() for i, rec in insts.items()
                if owner_of(p, i, rec) == project and _instance_node(p, i) == nid}
        return mine | {name for name, owner in (_owners().get(nid) or {}).items() if owner == project}

    def reach(o, project, other):
        """Into `o`, what `project` holds on another node: the whole address
        of a node that is not a sandbox, else its containers' published ports."""
        n = queue.node(other) if queue else None
        if not n:
            return
        addr = str((n.get("agent") or {}).get("addr") or "").strip()
        if not re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", addr):
            return
        rep = n.get("reported") or {}
        # A hosting-only node is a public box: what it says of itself does
        # not open it whole, only its containers' ports (R92).
        if not rep.get("sandbox") and not (n.get("config") or {}).get("host_only"):
            o["hosts"].add(addr)
            return
        pub = rep.get("published") or {}
        for key in held_on(project, other):
            for port in pub.get(key) or []:
                o["peers"].add((addr, int(port)))

    # ...and every node holding a container the project owns, its own or
    # one sent elsewhere on purpose (R166), so a session on the project's
    # node reaches a container shipped to another.
    held = {}
    for p, insts in _load().items():
        for i, rec in insts.items():
            owner = owner_of(p, i, rec)
            if owner:
                held.setdefault(owner, set()).add(_instance_node(p, i))
    for project, nids in sets.items():
        if node_id not in (nids or []):
            continue
        o = out.setdefault(project, blank())
        for other in list(nids) + sorted(held.get(project, set()) - set(nids)):
            if other and other != node_id:
                reach(o, project, other)
        # ...and what its settings name besides (Also reaches, the operator,
        # 7 Oct): a whole machine, or one port on it.
        for e in (reaches_of(project, node_id) if reaches_of else []) or []:
            addr, _, port = str(e).partition(":")
            if port:
                o["peers"].add((addr, int(port)))
            else:
                o["hosts"].add(addr)
        # ...and the containers of the projects this one READS (prefs.reads),
        # here and on this project's other nodes, so a session can open
        # their pages and photograph them: read-only is about the tree and
        # the notebook, and a running page is there to be looked at. On
        # this project's nodes only: a read project's node this one is not
        # on stays out, until the operator adds this project to it.
        for r in (reads_of(project) if reads_of else []) or []:
            if r == project:
                continue
            o["compose"] |= held_on(r, node_id) & {c for c in out.get(r, blank())["compose"]}
            o["compose"] |= {_pname(p, i) for p, insts in _load().items() for i, rec in insts.items()
                             if owner_of(p, i, rec) == r and _instance_node(p, i) == node_id}
            o["names"] |= {name for name, owner in (_owners().get(node_id) or {}).items() if owner == r}
            for other in nids:
                if other != node_id:
                    reach(o, r, other)
    return {p: {k: sorted(v) for k, v in o.items()} for p, o in sorted(out.items())}


def container_net_own(node_id):
    """What each compose project on `node_id` may reach of the others (R178):
    {compose project: {owner, to: [compose projects]}}, the owner's own and
    those of the projects it reads (prefs.reads). The agent turns it into
    bridge pairs; a compose project not named here reaches its own and no
    other. A container the operator gave a project is named by its name,
    which is its compose project when it was started by compose."""
    owned = {}
    for project, insts in _load().items():
        for inst, rec in insts.items():
            owner = owner_of(project, inst, rec)
            if owner and _instance_node(project, inst) == node_id:
                owned.setdefault(owner, set()).add(_pname(project, inst))
    for name, owner in (_owners().get(node_id) or {}).items():
        owned.setdefault(owner, set()).add(name)
    out = {}
    for owner, comps in owned.items():
        to = set(comps)
        for r in (reads_of(owner) if reads_of and owner != SYSTEM else []) or []:
            to |= owned.get(r, set())
        # BuilderBot's own (R180) reaches every compose project here by
        # `all`, which covers a container nobody here knows of.
        for c in comps:
            out[c] = {"owner": owner, "to": sorted(to)} | ({"all": True} if owner == SYSTEM else {})
    return dict(sorted(out.items()))


def row_named(name):
    """(project, instance) of the instance or written container the Docker
    tab lists as `name`, or None. How a session names one that is not its
    project's own (bb devapp --container)."""
    for proj, insts in _load().items():
        for inst in insts:
            if _pname(proj, inst) == name:
                return proj, inst
    return None


def _owners():
    """Which project each container BuilderBot did not start belongs to:
    {node: {container name: project}}. A file of its own, because the
    instance store is {project: {instance: record}} and _load keeps nothing
    else."""
    try:
        with open(OWNERS) as f:
            d = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(d, dict):
        return {}
    return {n: {c: p for c, p in v.items() if isinstance(p, str) and p}
            for n, v in d.items() if isinstance(v, dict)}


def _node_here():
    """The node the current block addresses, or the default one: the key a
    container's owner is kept under, since a name is only unique on its own
    daemon."""
    return getattr(_node_ctx, "node", None) or _default_node() or ""

def refs_of(project):
    """The branches this project could be built from, newest commit first,
    for the picker on the row. Local branches only: a remote-tracking one
    would be a build of something nobody here has fetched."""
    def run():
        r = _run(["git", "-C", str(WORKSPACE / project), "for-each-ref",
                  "--sort=-committerdate", "--format=%(refname:short)",
                  "refs/heads/"], timeout=15)
        return [b.strip() for b in (r["out"] or "").splitlines() if b.strip()][:60]
    return list(_git_memoed(project, "refs", run))


def instances(project):
    """The instance names this project has, oldest record first.

    `main` is always offered even where nothing has been built yet: a project
    with a compose file has one instance conceptually from the moment it has
    the file, and a list that was empty until the first build would make the
    first build impossible to start from.
    """
    have = list((_load().get(project) or {}).keys())
    return have or [MAIN]


def only_instance(project):
    """The instance a request means when it names none: the project's only
    recorded one, else `main`."""
    have = list((_load().get(project) or {}).keys())
    return have[0] if len(have) == 1 else MAIN


# The name a project is shown under, which a rename changes and its folder
# does not (R154): set by server.py to registry.label.
label_of = lambda p: p   # noqa: E731


def send_name(project, compose=""):
    """The name a new container of a project gets when nobody typed one:
    named for what the project is called now (a renamed Clanker-Detector
    offers turing-lens, not its folder's name: the operator, 10 Oct), with
    the folder or the variant of the compose file it is made from after it
    (turing-lens-site, turing-lens-prod), so two files are not offered one
    name. The project's own container while that is free, then -2, -3 and on,
    the first no container here holds. Send to Docker opens on it and `bb
    devapp new` takes it, so sending again makes another container beside
    the first rather than a refusal (the operator, 26 Sep)."""
    base = _slug(label_of(project)) or _slug(project) or "container"
    rel = str(compose or "")
    sub = posixpath.dirname(rel)
    m = COMPOSE_RE.fullmatch(posixpath.basename(rel)) if rel else None
    # A file named for its service (admin.compose.yml) is named by that
    # alone; one named by its folder or variant, by those.
    if m and m.group("pre"):
        tail = [_slug(m.group("pre"))]
    else:
        tail = [_slug(sub.replace("/", "-"))] if sub else []
        if m and m.group("var"):
            tail.append(_slug(m.group("var")[1:]))
    base = "-".join([base] + [t for t in tail if t])
    d = _load()
    if not _taken(project, instance_key(project, base), d):
        return project if instance_key(project, base) == MAIN else base
    n = 2
    while _taken(project, instance_key(project, f"{base}-{n}"), d):
        n += 1
    return f"{base}-{n}"


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
    """The store: {project: {instance: record}}."""
    try:
        with open(FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    return {proj: val for proj, val in d.items()
            if isinstance(val, dict) and all(isinstance(v, dict) for v in val.values())}


# The last _config failure on this thread, in compose's own words.
_cfg_err = threading.local()


def config_error():
    """What compose said when the last _config on this thread failed, "" if
    it did not or said nothing."""
    return getattr(_cfg_err, "said", "")


# A variable the file says it cannot start without: ${NAME:?why} or ${NAME?why}.
_REQUIRED_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):?\?")


def insisted_vars(project, instance=MAIN):
    """The variables the compose file insists on (${NAME:?...}), in order,
    once each: what its env must set before compose will read it at all."""
    cf = compose_file(project, instance)
    try:
        text = cf.read_text(encoding="utf-8") if cf is not None else ""
    except OSError:
        return []
    out = []
    for m in _REQUIRED_RE.finditer(text):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out[:32]


def _config(project, instance=MAIN, env_extra=None):
    """The compose file as compose itself resolves it: variables substituted,
    relative paths made absolute against the project directory.

    None when it cannot be read, which every caller has to treat as the
    cautious answer rather than as "nothing here".

    Deliberately not memoised. A cache on the compose file's mtime is wrong:
    what compose resolves also depends on an `include:`, an `extends:`, a
    `.env` beside the file, none of which that key can see, and a stale
    resolved compose means the row judges a file nobody has any more. The call
    is a subprocess, so the discipline is asking it once per answer rather
    than making it cheap to ask carelessly: state() does that for one row, and
    overview() for the listing it draws.
    """
    r = _run(_compose(project, instance, "config", "--format", "json"), timeout=30, env_extra=env_extra)
    _cfg_err.said = ""
    if r["code"] != 0:
        # What compose said, kept for the caller that shows it (the
        # Artifacts tab's row): "cannot read it" without compose's own
        # sentence left a session guessing which line was wrong.
        lines = [x.strip() for x in str(r.get("out") or "").splitlines() if x.strip()]
        _cfg_err.said = " ".join(lines[-3:])[:400]
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

    A compose that only runs published images (`image: postgres` and no
    `build:`) has nothing for Build to do, and Up should not wait on one.
    A compose that declares a build must not be brought up before it has
    been: `compose up` would build it ITSELF, silently, through the buildx
    path this feature deliberately avoids, and the operator would get the
    403 from a button that never mentioned building.
    """
    if cfg is None:
        # Unreadable compose: assume it builds, which is the cautious way
        # round: Up stays gated rather than firing an implicit build.
        return True
    return any(bool(sv.get("build")) for sv in _services(cfg).values())


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


def missing_dirs(project, cfg, instance=MAIN):
    """Bind sources that do not exist yet, split by whether we can make them.

    Docker creates a missing bind source itself (as root, then chowning it)
    which on a share that squashes root fails and takes the whole run down
    ("operation not permitted"), leaving the directory behind so the SECOND
    press works. An intermittent-looking failure with a fixed cause, and the
    reason this exists: the directories are made first, by whoever owns them.

    Only what this container can actually reach through its own mounts. A path
    it cannot see is not a path it should be inventing on the other machine's
    disk: that one is already what problems() is complaining about, and the
    answer there is the mapping rather than a mkdir.

    Two ways to make one, and a third case that is neither:

    - This container mounts it. mkdir here, and the daemon sees it because the
      share is the same one.
    - It is a path under a share the daemon has. A one-shot container over
      there makes it, as BuilderBot's uid; see _devdata_argv. The ordinary
      case with a sandbox VM: the dev-data and media shares are mounted over
      there and need not be here, and which shares those are is the VM's
      business, not a list kept on this container.
    - It is a share root itself, or not a path made of plain names. Named on
      the row and left alone: there is nothing below a share root to make,
      and docker creating the root itself is the as-root failure this exists
      to avoid.

    Returns (makeable, unreachable), both sorted lists of paths.

    A path on the daemon's side cannot be looked at from here, so one this has
    already made is remembered instead; otherwise the row goes on saying three
    directories are missing after the button that made them, and the button
    that worked looks like it did nothing. `mkdir -p` either way, so a record
    that has gone stale costs a directory being made twice.
    """
    if cfg is None:
        return [], []
    # Read without _rec: that one creates the record it is asked for, which on
    # a path that never writes would invent an instance for every project the
    # manager draws.
    done = set(((_load().get(project) or {}).get(instance) or {})
               .get("made_dirs") or [])
    # Longest first, so a path under /devdata matches /devdata rather than /.
    mine = sorted((m for m in _mount_roots() if m != "/"), key=len, reverse=True)
    under = lambda p, roots: any(p == r or p.startswith(r + "/") for r in roots)
    remote = sandbox_daemon()
    make, cannot = set(), set()
    for _, sv in sorted(_services(cfg).items()):
        for src in _binds(sv, project):
            if Path(src).exists():
                continue
            if src in done and not under(src, mine):
                continue                    # made over there, and unlookable here
            if under(src, mine) or (remote and mkdir_root(src)):
                make.add(src)
            else:
                cannot.add(src)
    return sorted(make), sorted(cannot)


def ensure_dirs(project, instance=MAIN, sink=None):
    """Make the bind directories, as the step before starting rather than a
    button somebody has to remember.

    It was a button, and a button you must press before another button is not
    a step, it is a trap: Up failed, and the reason it failed was a control
    sitting unpressed two inches away. Nothing about the decision was ever the
    operator's. Docker will create a missing bind source itself if this does
    not, as root, which is the failure the whole mechanism exists to avoid.

    Never fatal. What it could not make is reported into the job log and the
    compose runs anyway: the honest order is to try, then let compose say what
    actually went wrong, rather than refusing on this module's own reading of
    a file compose is about to read for itself.
    """
    r = make_dirs(project, instance)
    say = sink or (lambda _line: None)
    if r.get("made"):
        say(f"made {len(r['made'])} bind director"
            f"{'y' if len(r['made']) == 1 else 'ies'}\n")
    for line in r.get("failed") or []:
        say(f"could not make {line}\n")
    for d in r.get("unreachable") or []:
        say(f"{d} is not BuilderBot's to make, so docker will try it as root\n")
    return r


@_on_instance
def make_dirs(project, instance=MAIN):
    """Create the bind directories this container can reach. (made, failed).

    Owned by whoever BuilderBot runs as, which is the same ownership the
    per-instance dev-data directory gets and what the Unraid convention
    expects. `mkdir -p` throughout, so one that already exists is left alone
    and pressing this twice is the same as pressing it once.

    Made HERE when this container mounts the share, and on the DAEMON when it
    does not and the operator has declared the path: same result, different
    side, and the row does not distinguish because the operator should not
    have to care which.
    """
    make, cannot = missing_dirs(project, _config(project, instance), instance)
    mine = sorted((m for m in _mount_roots() if m != "/"), key=len, reverse=True)
    made, failed = [], []
    # Grouped by the root they sit under: one container per share rather than
    # one per directory, which for a compose naming three under /devdata is
    # one launch instead of three.
    remote = {}
    for d in make:
        if any(d == m or d.startswith(m + "/") for m in mine):
            try:
                Path(d).mkdir(parents=True, exist_ok=True)
                made.append(d)
            except OSError as e:
                failed.append(f"{d}: {e}")
            continue
        remote.setdefault(mkdir_root(d), []).append(d)
    for root, paths in sorted(remote.items()):
        rels = [p[len(root):].strip("/") for p in paths]
        if _devdata_run("mkdir", *rels, root=root):
            made.extend(paths)
        else:
            failed.extend(f"{p}: the daemon could not make it" for p in paths)
    if remote and made:
        with _lock:
            d = _load()
            rec = _rec(d, project, instance)
            rec["made_dirs"] = sorted(set(rec.get("made_dirs") or []) | set(made))
            write_json(FILE, d)
    _bump()
    return {"ok": True, "made": made, "failed": failed, "unreachable": cannot}


def risks(project, cfg):
    """What this compose asks for beyond its own directory.

    The half of the blast radius no check on a COMMAND can bound. A container
    started from a file saying `privileged: true` and mounting `/` is named as
    innocently as any other and passes every check that can be made on a
    name, so the file itself is read, and what it asks for is put in front of
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
            out.append(f"{name} runs privileged: root on the host, in effect")
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
        if str(sv.get("userns_mode") or "") == "host":
            out.append(f"{name} shares the host's user namespace")
        loose = [o for o in (sv.get("security_opt") or []) if isinstance(o, str) and "unconfined" in o]
        if loose:
            out.append(f"{name} drops a security profile: {', '.join(loose)}")
        # A bind mount of what gives control of the node is a risk a person
        # acknowledges, whatever the row already shows about it: with the
        # project's Run its container dial on auto, a session writes the
        # compose and rebuilds it, so a mount of / or of the docker socket
        # was root on the node for the asking (the audit of 26 Sep). A data
        # share (/mnt/..., /srv, /media) is the ordinary case the row lists
        # and is not repeated here; the root, the system directories and
        # the socket are.
        for host in _bind_sources(sv):
            if host == "/var/run/docker.sock" or host.endswith("/docker.sock"):
                out.append(f"{name} mounts the docker socket: every container on the node, and root through it")
            elif _system_path(host):
                out.append(f"{name} mounts {host} of the host: the node's own system, not a share")
    return out


def _bind_sources(sv):
    """The host paths a service binds, as written: `src:dst[:mode]` strings
    and long-form entries with a source. A named volume is not one."""
    out = []
    for v in sv.get("volumes") or []:
        if isinstance(v, str):
            src = v.split(":", 1)[0] if ":" in v else ""
        elif isinstance(v, dict):
            src = str(v.get("source") or "") if str(v.get("type") or "bind") == "bind" else ""
        else:
            src = ""
        if src and (src.startswith("/") or src.startswith(".") or src.startswith("~")):
            out.append(src)
    return out


SYSTEM_ROOTS = ("/etc", "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/boot", "/root",
                "/var", "/proc", "/sys", "/dev", "/run", "/home", "/opt")


def _system_path(host):
    """Whether a bind's host path is the node's root or one of its system
    directories: what a container could take the machine over through."""
    path = os.path.normpath(str(host))
    if path == "/":
        return True
    return any(path == r or path.startswith(r + "/") for r in SYSTEM_ROOTS)


def our_paths(mapping):
    """The paths this container has that the mapping speaks for.

    Was a hardcoded pair (/workspace and /devdata) which is what the mapping
    held on the day it was written and not what it holds now. A share added to
    both sides (an /auxiliary for general storage, say) was then translated by
    to_host and judged by nothing: a bind under it could name a directory the
    daemon does not have, and the answer to a missing bind source is an empty
    directory silently mounted in its place.

    Derived instead, so adding a mount to both sides is a setting rather than a
    code change. Existence is the filter, and it is the honest one: a mapping
    may name a path that only the DAEMON has, which is fine and common, and is
    not something this side can check anything about.
    """
    ours = [p for p in mapping if Path(p).is_dir()]
    # WORKSPACE whether or not it is mapped, because with no mapping on the
    # node's record there is nothing at all and a project's own binds are
    # exactly what wants checking.
    #
    # DEVDATA deliberately NOT: it is a path on the VM, which makes those
    # directories itself. Adding it here judged binds under it against THIS
    # container's mount table and called every correct compose file broken,
    # "/devdata/x is this container's path, the daemon does not have it", on
    # the one path the daemon certainly does have. If it is mounted on both
    # sides and named in the mapping, the line above covers it like any other.
    if str(WORKSPACE) not in ours and WORKSPACE.is_dir():
        ours.append(str(WORKSPACE))
    return ours


def stray_map_entries(mapping):
    """Mapped paths this container does not have.

    Not an error: /auxiliary can be a share the sandbox mounts and BuilderBot
    has no business reading. But it is a line of configuration that nothing
    else here will ever act on, and saying so once beats it sitting in the
    variable looking like it does something.
    """
    return sorted(p for p in mapping if not Path(p).is_dir())


def _root_of(path):
    """The first component of a path, which is the pair a mapping would name.

    /devdata/binhex-sonarr/data is not what goes in the node's mapping;
    /devdata is, and a message that suggests the bind's whole path teaches the
    wrong shape.
    """
    parts = [p for p in str(path).split("/") if p]
    return "/" + parts[0] if parts else str(path)


def problems(project, cfg):
    """Paths this compose gives the daemon that the daemon will not find.

    A different thing from risks(): those are decisions the operator may
    reasonably make, this is a compose file that cannot work. Kept apart so
    the confirmation stays about the first kind: asking someone to confirm a
    configuration error teaches them to confirm without reading.

    Only OUR paths are judged: every path this container has that the mapping
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
            # "the daemon does not have it" was the old wording, and it is a
            # claim this side cannot make: nothing here can see the other
            # machine's filesystem, which is the whole reason the mapping is a
            # setting. Against a sandbox VM it was usually false as well: the
            # share is mounted over there at the same path, and the honest
            # answer is that BuilderBot has not been told so.
            out.append(
                f"{name} mounts {src}, which is this container's path. "
                + (f"The daemon calls that {there}" if there else
                   f"The node's path mapping does not say what the daemon calls "
                   f"it. Add a pair for it on the node's row (Nodes page, Advanced, "
                   f"Path mapping): {_root_of(src)}:{_root_of(src)} if the daemon "
                   f"mounts the same share at the same path"))
    return out


# A ports line that names every address: the literal, or a variable that
# defaults to it (`${REGISTRY_BIND:-0.0.0.0}:9787:8787`), with the variable
# a person can set in the env to put it right.
_EVERY_ADDR = re.compile(r"""^\s*-\s*['"]?(?:\$\{(?P<var>[A-Za-z_][A-Za-z0-9_]*)(?::-0\.0\.0\.0)?\}|(?P<lit>0\.0\.0\.0)):""", re.M)


def every_address(project, instance=MAIN):
    """Where the compose file behind an instance publishes on every address
    (R217): {"vars": [names], "literal": bool}, or None when it names no
    address, which leaves the daemon's default (127.0.0.1 on a node whose
    ports stay on it, R190) to decide. Read as text, since a variable's
    default is its spelling and the resolved config has only the value."""
    f = compose_file(project, instance)
    if f is None:
        return None
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found = {"vars": [], "literal": False}
    for m in _EVERY_ADDR.finditer(text):
        if m.group("lit"):
            found["literal"] = True
        elif m.group("var") and m.group("var") not in found["vars"]:
            # A variable with no default names every address only when the
            # env leaves it empty; the one defaulting to 0.0.0.0 is the case.
            if ":-0.0.0.0" in m.group(0):
                found["vars"].append(m.group("var"))
    return found if found["vars"] or found["literal"] else None


def taken_ports(project, instance, ports):
    """The host ports this instance would publish that something ELSE on the
    same daemon already has, as ["6789 (jumble)", ...].

    Two instances of one project publish the same ports by construction,
    because they are the same compose file, so "run the branch beside the one
    that is up" collides on the second Up and compose says so in its own
    words, after the press. This is the same fact before it: read off the container
    list the manager already has, which is one `ps` it already paid for.

    A compose file whose published ports come from the env has an answer (the
    env file is per instance); one that hard-codes them does not, and what
    this owes that case is a sentence rather than a surprise.
    """
    want = {str(p.get("published") or "").strip()
            for p in (ports or []) if str(p.get("published") or "").strip()}
    if not want:
        return []
    mine = _pname(project, instance)
    out = []
    for c in (containers().get("containers") or []):
        if c.get("project") == mine:
            continue                     # our own, which Up replaces
        for p in _published(c.get("ports") or []):
            if str(p) in want:
                out.append(f"{p} ({c.get('name') or c.get('project') or 'another container'})")
    return sorted(set(out))


def wiring(cfg):
    """What this compose publishes and what it mounts.

    Shaped the way Unraid's own Containers page shows it, because that is where the
    operator reads the same facts about every other container on the box: the
    container's side on the left, the host's on the right, and an arrow that
    says which way it goes: one way into the container for a read-only mount,
    both ways for a writable one.

    Off the resolved config, so a path or a port assembled out of variables is
    the value compose arrived at and not the spelling. Both spellings of each
    are handled for the same reason _binds does it: depending on one shape of
    somebody else's JSON is how a reader quietly stops reading.

    Each line carries its service: a stack's ports in one list could not be
    told apart, which container answers on which (B252).
    """
    if cfg is None:
        return {"ports": [], "mounts": []}
    ports, mounts = [], []
    for name, sv in sorted(_services(cfg).items()):
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
                ports.append({"service": name, "target": tgt, "published": pub,
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
                mounts.append({"service": name, "target": tgt, "source": src, "ro": ro})
    return {"ports": ports, "mounts": mounts}


def risk_digest(rs):
    """A stable name for one set of risks, so that acknowledging them stops
    counting the moment the compose file asks for something new."""
    if not rs:
        return ""
    return hashlib.sha256("\n".join(sorted(rs)).encode()).hexdigest()[:12]


def gpu_asks(cfg):
    """The services of this compose that reserve an NVIDIA GPU, by name, in
    any of the three spellings compose takes: a device reservation under
    deploy.resources (driver nvidia, or the gpu capability with no driver
    named), `runtime: nvidia`, or `gpus:`."""
    out = []
    for name, sv in sorted(_services(cfg).items()):
        res = (((sv.get("deploy") or {}).get("resources") or {}).get("reservations") or {}) \
            if isinstance(sv.get("deploy"), dict) else {}
        devs = res.get("devices") if isinstance(res, dict) else None
        asks = str(sv.get("runtime") or "") == "nvidia" or bool(sv.get("gpus"))
        for d in devs if isinstance(devs, list) else []:
            if not isinstance(d, dict):
                continue
            caps = [str(c) for c in (d.get("capabilities") or [])] if isinstance(d.get("capabilities"), list) else []
            drv = str(d.get("driver") or "")
            if drv == "nvidia" or (not drv and "gpu" in caps):
                asks = True
        if asks:
            out.append(name)
    return out


def room_gate(project, instance=MAIN):
    """The reason a build on this instance's node would run out of disk, or
    "" (R110): Docker's images and build cache under the node's floor fail
    a build partway, with a disk-full error that names neither (set by
    server.py through room_why)."""
    if room_why is None:
        return ""
    return room_why(_instance_node(project, instance)) or ""


def gpu_gate(project, instance=MAIN, cfg=None):
    """The reason a compose that reserves the GPU cannot start on this
    instance's node, or "": Docker's own answer there is "could not select
    device driver nvidia", after the build, which names neither the toolkit
    nor the setting that said no (R102)."""
    if gpu_why is None:
        return ""
    asks = gpu_asks(cfg if cfg is not None else _config(project, instance))
    if not asks:
        return ""
    why = gpu_why(project, _instance_node(project, instance))
    if not why:
        return ""
    return (f"{', '.join(asks[:3])} reserve{'s' if len(asks) == 1 else ''} the NVIDIA GPU in the compose file, and "
            + why)


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
    # With the way past it: a person acknowledges the list where it is
    # shown, once, and it holds until the compose asks for more. Taking the
    # risky lines out of the compose is the move the bare refusal suggested,
    # and it broke the container it was for (24 Sep, a PUID/PGID image that
    # needs CHOWN and SETUID). A session's build never meets this: its
    # project's Run its container setting is its answer (rebuild's `gate`).
    return ("this compose asks for more than its own directory: "
            + "; ".join(rs[:3]) + (" …" if len(rs) > 3 else "")
            + ". A person acknowledges that once by pressing Build or Rebuild on its row "
              "on the Containers page, where the list is shown")


# ---- what a build ships beside the app (the operator, 17 Oct) -------------
# A project's dev container is the one built from its tree; a service that
# runs a published image beside it (a database, a git host, a seed) rides in
# its stack, is rebuilt and pinned to its branch with it, and ships when it
# does. So one that was not there at its last build is a person's to say
# yes to, where the build is pressed, before it ships: "so the person knows
# what is actually being shipped". The first build after this landed takes
# what is there as the baseline; a session's build is stopped and told who
# answers, since the yes is a person's.
def beside_services(cfg):
    """The services a resolved compose runs from a published image, with
    nothing built from the tree: what rides beside the app."""
    return sorted(n for n, sv in _services(cfg).items() if not sv.get("build"))


def beside_new(project, instance=MAIN, cfg=None):
    """The image-only services its last build did not ship and nobody has
    said yes to, or [] (none, or no baseline yet, which the next build
    takes)."""
    rec = _read_rec(project, instance)
    if "beside" not in rec or cfg is None:
        return []
    known = set(rec.get("beside") or [])
    return [n for n in beside_services(cfg) if n not in known]


def beside_digest(new):
    return hashlib.sha256("\n".join(sorted(new)).encode()).hexdigest()[:12] if new else ""


def _set_beside(project, instance, names):
    with _lock:
        store = _load()
        _rec(store, project, instance)["beside"] = sorted(names)
        write_json(FILE, store)


def _beside_gate(project, instance=MAIN, yes=""):
    """The reason to stop before a build ships a service beside the app that
    its last one did not, or "" to go ahead. `yes` is a person's answer, the
    digest of the services the Containers page showed them; a session never
    carries one (rebuild passes "" for a session's build)."""
    if is_file_source(project, instance):
        return ""                       # a container written here is all its own stack
    cfg = _config(project, instance)
    if cfg is None:
        return ""                       # unreadable: the build says so itself
    now = beside_services(cfg)
    rec = _read_rec(project, instance)
    new = [n for n in now if n not in set(rec.get("beside") or [])] if "beside" in rec else []
    if not new or (yes and yes == beside_digest(new)):
        if rec.get("beside") != now:
            _set_beside(project, instance, now)
        return ""
    return (f"the project's compose now runs {', '.join(new)} beside the app, which its last build did not "
            "ship: a person says whether that is part of the app by pressing Rebuild on its row on the "
            "Containers page, where it is named; if it is not, it is a container of its own (bb container new), "
            "not a service in the project's compose file")


# The variables that would make compose read another file, another stack or
# another set of the file's services than the build was pressed for: what a
# dev container runs is its compose file and its branch, nothing an env says.
COMPOSE_CONTROL = ("COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_PROFILES", "COMPOSE_PATH_SEPARATOR")


def compose_control(text):
    """The compose-control variables an env sets, in order, or []."""
    out = []
    for line in str(text or "").splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) in COMPOSE_CONTROL and m.group(1) not in out:
            out.append(m.group(1))
    return out


def compose_control_refusal(names):
    return (f"{', '.join(names)} {'is' if len(names) == 1 else 'are'} not an env setting here: what a container "
            "runs is its compose file (and, for a project's, its branch), so the services it starts are the "
            "file's to say; take the line out of its env (Env)")


def is_file_source(project, instance=MAIN):
    return _read_rec(project, instance).get("source") == "file"


def built_rev(project, instance=MAIN):
    """What "this build was made from", for whichever kind of source it is.

    A project's is its git commit. A container WRITTEN here has no repository
    behind it, so _head asked git about a directory that is not one, got ""
    back, and warned about it on every poll, and the record's rev stayed
    empty. built_rev being empty is what the row reads as never-built, so the
    button said Build forever on a container that had been built a dozen
    times, and Rebuild could never appear.

    Its revision is its definition: the compose file and the env, hashed. That
    is the thing a rebuild would pick up, so it is the honest answer to both
    questions the row asks: what was this built from, and has it moved since.
    """
    if not is_file_source(project):
        return _head(project, instance)
    h = hashlib.sha256()
    for part in (_container_text(project), read_env(project, instance) or ""):
        h.update(part.encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()[:7]


def _container_text(name):
    try:
        return (containers_dir(name) / "docker-compose.yml").read_text(
            encoding="utf-8")
    except OSError:
        return ""


# What git said about a project, kept until the repository moves. The
# manager's listing asks HEAD, the branches and the pinned refs of every
# project it lists on every draw, and a draw is one per revision while a job
# runs; each ask is a subprocess reading a tree on the share (B205). A commit,
# a checkout or a fetch changes one of .git's few top-level files, so their
# mtimes are the key: the same key, the same answer, and no git run. `status`
# is not here, because a working tree can move without .git moving.
_git_memo = {}
_git_memo_lock = threading.Lock()
_GIT_STAMPS = ("HEAD", "index", "packed-refs", "refs", "logs/HEAD")


def _git_key(project):
    g = WORKSPACE / project / ".git"
    return tuple(_mtime(g / n) for n in _GIT_STAMPS)


def _git_memoed(project, what, run):
    key = (project, what)
    stamp = _git_key(project)
    with _git_memo_lock:
        hit = _git_memo.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    val = run()
    with _git_memo_lock:
        _git_memo[key] = (stamp, val)
    return val


def _head(project, instance=None):
    """The commit an instance is built FROM: the project tree's HEAD, or the
    ref's own tip when the instance is pinned to one. Both answers come from
    the project's repository, so a branch that has never been checked out is
    still a commit this can name."""
    ref = (str(_read_rec(project, instance).get("ref") or "").strip()
           if instance else "")
    if not (WORKSPACE / project).is_dir():
        return ""                      # no tree to ask (B634, as _dirty)

    def run():
        r = _run(["git", "-C", str(WORKSPACE / project), "rev-parse", "--short=7",
                  ref or "HEAD"], timeout=10)
        return r["out"].strip() if r["code"] == 0 else ""
    return _git_memoed(project, "head:" + ref, run)


def _dirty(project):
    # Without taking the index lock: this is polled for the row, and git
    # status refreshing the index would hold it just as a session in the
    # same tree runs git and meets index.lock: File exists (B155).
    # No tree, no question: a record under a written container's name that
    # lost its source mark (one a late job wrote back after a Remove) sent
    # git to a directory that is not there on every poll (B634).
    if not (WORKSPACE / project).is_dir():
        return False
    r = _run(["git", "-C", str(WORKSPACE / project), "status", "--porcelain"],
             timeout=10, env_extra={"GIT_OPTIONAL_LOCKS": "0"})
    return r["code"] == 0 and bool(r["out"].strip())
