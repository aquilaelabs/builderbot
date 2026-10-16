"""The layer that runs and reports an instance: up, down, rebuild, test,
remove, the row, and the verb dispatcher `bb devapp` and the Docker tab's
buttons reach through act().

An action is a JOB on the queue with a plan for the node the instance is
bound to, and everything here is either the plan (what compose is asked to
do, in which order, with which env), the runner that executes one on the
controller's own daemon, the bookkeeping a finished one writes, or state(),
the row that reports what came of it. What it stands on is the base:
the store, the node block, the docker runner, the compose-file readers, the
risks and the env files, all of which are devapp's and read through it.

Its own file since 25 Sep, the second cut of devapp.py (R77) after
containers.py. The first plan was to take the compose-file readers and the
env out, the way containers.py went; that failed on the dependency
direction: everything this layer does is BUILT ON those, so a module for
them would have had devapp importing it back, a cycle. The cut that holds
is the other way round: the layer on top leaves, the base stays, and the
base knows nothing of this file. server.py holds only the routes and hands
the compose runner to jobs.py through configure() here.
"""

import contextlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import devapp  # noqa: E402
import relocate  # noqa: E402


def configure(*, runner=None):
    """Hand the compose runner to jobs.py. Called by server.py after
    devapp.configure(), which is where `runner` also lands for Abort."""
    if runner is not None:
        runner.register("compose", run_compose_job)


# What request() needs from the rest of the server, set by server.py: the
# account store (who is asking, and whether they administer), the asking
# (phone.ask_rebuild), a line in the project's chat (chat.event), and the
# sessions' networks told when a container is made, removed or given to
# another project (R79).
users = None
ask_rebuild = None
say = None
net_nudge = None


# One action per INSTANCE at a time. Two clicks on one row are two compose
# calls on one project; two rows are two jobs, and the queue orders those.
BUSY = {"error": "something is already running on this instance: one at a time"}


def _active_job(project, instance):
    """The compose job queued or running for this instance, if any."""
    if devapp.queue is None:
        return None
    for j in devapp.queue.jobs_for(project=project, type="compose", active=True, n=50):
        if (j.get("spec") or {}).get("instance", devapp.MAIN) == instance:
            return j
    return None


def sync_work_tree(project, instance):
    """Put the instance's worktree on its ref, making it if it is not there.

    Returns "" or the reason it could not. Run before a build rather than
    when the ref is set: the ref is a setting and the branch it names moves,
    so what matters is where it points at the moment something is built.
    """
    at = devapp.work_tree(project, instance)
    if at is None:
        return ""
    ref = str(devapp._read_rec(project, instance).get("ref") or "").strip()
    repo = devapp.WORKSPACE / project
    if not (repo / ".git").exists():
        return f"{project} is not a git repository, so there is no branch to build"
    # DETACHED, both when it is made and every time it moves. A branch can be
    # checked out in one worktree at a time, and this tree is not the one that
    # matters: the project's own checkout is where people work. Claiming the
    # branch here broke it in both directions:
    #
    #   building an instance pinned to the branch the project is standing on
    #   was refused outright ("'rack-drift' is already used by worktree at
    #   /workspace/word-jumble"), which is the ordinary case, not an edge one;
    #
    #   and the reverse, which is worse because nothing says it: a build tree
    #   holding `main` meant the operator's own session could no longer
    #   `git checkout main`, a dashboard button quietly taking a branch
    #   hostage from somebody's shell.
    #
    # Nothing is ever committed here (the tree exists to be compose's
    # --project-directory), so it wants the ref's COMMIT and no claim on the
    # name. A tree made before this and still holding a branch detaches on its
    # next build and gives the name back.
    if not at.exists():
        r = devapp._run(["git", "-C", str(repo), "worktree", "add", "--force",
                         "--detach", str(at), ref], timeout=120)
        if r["code"] != 0:
            return f"could not make a worktree at {ref}: " + devapp._why_not(r["out"])
    else:
        r = devapp._run(["git", "-C", str(at), "checkout", "--force", "--detach", ref],
                        timeout=120)
        if r["code"] != 0:
            return f"could not put the build tree on {ref}: " + devapp._why_not(r["out"])
    try:
        # server.py's own name for it, spelled here rather than imported:
        # this module is configured by the server, not a child of it.
        (at / ".bbignore").write_text("a build tree, not a project\n")
    except OSError:
        pass                             # the marker is a courtesy to the list
    return ""


# The plan an agent node runs for one action (roadmap #18). The controller
# still decides what: these are the same docker calls the controller used to
# make over ssh, in the same order, with the compose file and env traveling
# beside them, so a node needs nothing but the token it enrolled with.
# `{cdir}` is the directory the agent writes those files into.
COMPOSE_MAX = 200_000            # a compose file is a page, not a payload


def set_compose(project, instance, text):
    """Write a project's own compose file from the Docker tab's Edit: the
    file in its tree, so the change is an uncommitted one the Git view shows
    like any other edit, and only once compose has read it: a file compose
    refuses is put back as it was, with compose's own words."""
    cf = devapp.compose_file(project, instance)
    if devapp.is_file_source(project, instance) or cf is None:
        return {"error": f"{project} has no compose file in its tree to edit"}
    if not isinstance(text, str) or not text.strip():
        return {"error": "a compose file is needed"}
    if len(text) > COMPOSE_MAX:
        return {"error": f"that compose file is over {COMPOSE_MAX // 1000}kB"}
    try:
        was = cf.read_text(encoding="utf-8")
    except OSError as e:
        return {"error": f"could not read {cf.name}: {e}"}
    if text == was:
        return {"ok": True, "unchanged": True}

    def put(body):
        tmp = cf.with_name(f".{cf.name}.bbedit")
        tmp.write_text(body, encoding="utf-8")
        os.chmod(tmp, cf.stat().st_mode & 0o7777)
        os.replace(tmp, cf)
    try:
        put(text)
    except OSError as e:
        return {"error": f"could not write {cf.name}: {e}"}
    with devapp.on_node(devapp._instance_node(project, instance)):
        r = devapp._run(devapp._compose(project, instance, "config", "-q"), timeout=30)
    if r["code"] != 0:
        with contextlib.suppress(OSError):
            put(was)
        return {"error": ("compose will not read that, so the file is as it was:\n" + r["out"]).strip()[-600:]}
    devapp._bump()
    return {"ok": True, "note": f"{cf.name} is changed in {project}'s tree, not committed: "
                                "rebuild to bring the change up"}


def _plan(project, instance, action, extra=None):
    pname = devapp._pname(project, instance)
    at = devapp.work_tree(project, instance)
    ship = shipped(project, instance)
    # A shipped instance (R166) lives on a node that does not hold the
    # project: it runs from its own compose directory there, and its image
    # comes built from elsewhere, so nothing here builds or pulls on it.
    # ...and inside the tree, the folder its compose file is in, which is
    # what the file's relative paths mean.
    sub = devapp.compose_sub(project, instance)
    pdir = ("{cdir}" if ship else str(at / sub).rstrip("/") if at is not None
            else str(devapp.WORKSPACE / project / sub).rstrip("/")
            if devapp._read_rec(project, instance).get("source") != "file"
            else (devapp.dev_data_dir(project, instance, make=False)
                  or str(Path(devapp.appdata_root()) / pname)))
    base = [devapp.DOCKER, "compose", "--project-name", pname,
            "--project-directory", pdir, "-f", "{cdir}/docker-compose.yml"]
    ienv = {}
    if devapp.env_path(project, instance).is_file():
        base += ["--env-file", "{cdir}/instance.env"]
        # What the copy's env_file lines name (env_to_instance, _plan_spec),
        # on every step, since down and exec load the file as well; the
        # agent puts its directory in for {cdir}.
        ienv = {"BB_INSTANCE_ENV": "{cdir}/instance.env"}
    env = ienv | devapp._dev_data_env(project, instance) | devapp._build_env(project, instance)
    # The commit and the time read where and when the build runs, not when
    # it was queued: a rebuild that waited in the node's queue built the tree
    # as it was then and was stamped with the commit from before (B479).
    # The queued values stay as the fallback, for a source that is no git
    # checkout.
    stamped = ["sh", "-c", 'r="$(git -C "$1" rev-parse HEAD 2>/dev/null)" && export BB_BUILD_REV="$r"; '
               'export BB_BUILD_AT="$(date -u +%Y-%m-%dT%H:%MZ)"; shift; exec "$@"', "sh", pdir]
    # --remove-orphans on both (B592): a service the compose file no longer
    # names, renamed or dropped since it was started, was left running by
    # down and by remove, holding its ports, and the next up failed on them.
    # A shipped instance builds nothing on its node (the image came in the
    # tar), and pulls what it lacks: the tar carries the built images alone,
    # and with --pull never a service on a registry image (mariadb:11) met
    # "No such image" and the move was undone (B660, aquilaeLabs, 11 Oct).
    up = {"name": "starting", "argv": stamped + base + ["up", "-d", "--remove-orphans"]
          + (["--no-build", "--pull", "missing"] if ship else []), "timeout": 1800, "env": env}
    down = {"name": "stopping", "argv": base + ["down", "--remove-orphans"], "timeout": 180, "env": ienv}
    build = {"name": "building", "argv": stamped + base + ["build"], "timeout": 3600, "env": env}
    # The env gate, in the only place a PLAN can carry it: a rebuild that
    # would start an instance whose env does not answer the repo's new
    # settings stops after `down`, and the controller rewrites the env and
    # waits for the operator (compose_done's `gate` branch, and _gate_env).
    #
    # The controller's own runner decides this between the down and the up,
    # with the build already done. Here the whole plan is fixed before the
    # node sees it, so it is decided up front, which is the same answer,
    # because neither the build nor the down touches .env.example or the
    # instance env. What it must NOT do is send `up` anyway and gate
    # afterwards: that is the broken start the gate exists to prevent.
    # ...and one arriving on another node (relocate.py's last stage) builds
    # and stays down: the person decides when it serves there, and a move
    # takes the old node's down once the build lands (the operator, 13 Oct;
    # R208).
    rel = devapp._read_rec(project, instance).get("relocating")
    arriving = isinstance(rel, dict) and rel.get("stage") == "build"
    rebuild = [build, down] if devapp.missing_env(project, instance) or arriving else [build, down, up]
    # The project's own test command, inside its running instance (roadmap
    # R48): `exec` into the service the project builds, with the command the
    # settings dialog recorded and nothing else, and the caller's arguments
    # as positional parameters, never spliced into the command. -T because
    # there is no terminal on a job; BB_TEST_TIMING so the registry can read
    # the run.
    test = []
    if action == "test" and extra:
        # In the project's own directory inside the container when the
        # compose file mounts it there; the image's working directory
        # otherwise. The first run of BuilderBot's suite inside its own
        # instance ran at / and found no scripts/ (15 Sep).
        wd = ["-w", extra["workdir"]] if extra.get("workdir") else []
        # BB_IN_INSTANCE says this run IS the container's, which is the one
        # thing a suite cannot work out for itself: the dev instance is a
        # container like any other and the controller is one too. run.sh
        # reads it to tell "tests run here" from "tests were run around me".
        # BB_TEST_WORKERS, bare, carries the node's test-workers setting
        # from the job's environment into the container (R81): compose
        # exec forwards nothing else of the caller's.
        argv = base + ["exec", "-T", "-e", "BB_TEST_TIMING=1",
                       "-e", "BB_IN_INSTANCE=1", "-e", "BB_TEST_WORKERS", *wd, extra["service"],
                       "sh", "-c", extra["cmd"] + ' "$@"', "test", *extra.get("args", [])]
        test = [{"name": "testing", "argv": argv, "timeout": 3600, "env": ienv}]
    # Stopped and started again in place, its containers kept: what copying
    # or moving an instance's data does around reading it (relocate.py).
    # Update (R195): the registry images pulled again, then up, so what moved
    # upstream is what runs; nothing is built. --ignore-buildable leaves the
    # services built from code to Rebuild.
    pull = {"name": "pulling", "argv": base + ["pull", "--ignore-buildable"], "timeout": 1800, "env": ienv}
    stop = {"name": "stopping", "argv": base + ["stop"], "timeout": 180, "env": ienv}
    start = {"name": "starting", "argv": base + ["start"], "timeout": 300, "env": ienv}
    return {"up": [up], "down": [down], "remove": [down],
            "rebuild": rebuild, "test": test, "stop": [stop], "start": [start],
            "update": [pull, up]}.get(action) or []


# ---- an image shipped to a node that does not hold the project (R166) ------------
#
# A project's dev instance may live on a node the project is not bound to (a
# web-facing box), and the project's source never goes there: the image is
# built on a node that holds the project, saved, sent up to the controller,
# and fetched, loaded and started on the instance's node. Two jobs, one per
# node: the build node's (ship: build) and, queued when that one succeeds,
# the instance node's (ship: run). The image file lives in the controller's
# images store (paths.py) from the first job's upload to the second job's
# end, and on each node only inside that job's own compose directory.

# Run on the build node by python3 (the agent's own interpreter): the images
# the compose file BUILDS, by their names, saved to one file. A service that
# only pulls an image is left to be pulled where it runs.
SAVE_PY = r"""
import json, subprocess, sys
argv, out, pname = json.loads(sys.argv[1]), sys.argv[2], sys.argv[3]
cfg = json.loads(subprocess.run(argv + ["config", "--format", "json"], check=True,
                                capture_output=True, text=True).stdout)
names = sorted({(sv.get("image") or f"{pname}-{name}")
                for name, sv in (cfg.get("services") or {}).items() if sv.get("build")})
if not names:
    sys.exit("nothing in the compose file is built here, so there is no image to ship")
print("saving " + ", ".join(names), flush=True)
subprocess.run(["docker", "save", "-o", out, *names], check=True)
"""


def shipped(project, instance):
    """Whether this instance's image is built elsewhere and shipped (R166)."""
    return bool(devapp._read_rec(project, instance).get("ship"))


def ship_binds(project, cfg):
    """The binds of a shipped instance that reach into the project's tree,
    which its node does not have and must not: refused before a build."""
    if cfg is None:
        return []
    tree = str(devapp.WORKSPACE / project)
    out = []
    for name, sv in sorted(devapp._services(cfg).items()):
        for src in devapp._binds(sv, project):
            if src == tree or src.startswith(tree + "/"):
                out.append(f"{name} mounts {src}")
    return out


def _image_file(project, instance):
    import paths
    d = paths.of("images")
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{devapp._pname(project, instance)}.tar"


def _ship_build_spec(project, instance, job_id):
    """The build node's half: build from its own copy, save what was built,
    send it up. Never starts anything there."""
    spec = _plan_spec(project, instance, "rebuild")
    pname = devapp._pname(project, instance)
    # The project directory the build resolves paths against: the tree for
    # a project's instance, the data directory for a written one (as _plan
    # has it), on the node that builds.
    pdir = ((devapp.dev_data_dir(project, instance, make=False) or str(Path(devapp.appdata_root()) / pname))
            if devapp.is_file_source(project, instance)
            else str(devapp.WORKSPACE / project / devapp.compose_sub(project, instance)).rstrip("/"))
    base = [devapp.DOCKER, "compose", "--project-name", pname,
            "--project-directory", pdir, "-f", "{cdir}/docker-compose.yml"]
    if "instance.env" in spec["files"]:
        base += ["--env-file", "{cdir}/instance.env"]
    env = ({"BB_INSTANCE_ENV": "{cdir}/instance.env"} if "instance.env" in spec["files"] else {}) \
        | devapp._dev_data_env(project, instance) | devapp._build_env(project, instance)
    build = {"name": "building", "argv": base + ["build"], "timeout": 3600, "env": env}
    save = {"name": "saving", "argv": ["python3", "-c", SAVE_PY, json.dumps(base), "{cdir}/image.tar", pname],
            "timeout": 1800, "env": env}
    ship = {"name": "shipping", "upload": "{cdir}/image.tar", "to": f"devimage-put?job={job_id}", "timeout": 3600}
    return spec | {"dirs": [], "gate": False, "ship": "build", "plan": [build, save, ship]}


def _ship_run_spec(project, instance, job_id):
    """The instance node's half: fetch the image, load it, start the
    instance from it."""
    spec = _plan_spec(project, instance, "rebuild")
    plan = [p for p in _plan(project, instance, "rebuild") if p["name"] != "building"]
    fetch = {"name": "fetching", "fetch": f"devimage?job={job_id}", "dest": "{cdir}/image.tar", "timeout": 3600}
    load = {"name": "loading", "argv": [devapp.DOCKER, "load", "-i", "{cdir}/image.tar"], "timeout": 1800}
    drop = {"name": "loading", "argv": ["rm", "-f", "{cdir}/image.tar"], "timeout": 60}
    return spec | {"ship": "run", "plan": [fetch, load, drop, *plan]}


def _ship_submit(project, instance, target):
    """A shipped instance's rebuild: the build node's job now, the instance
    node's when it succeeds (ship_next, from compose_done)."""
    # A written container builds on its owner's node, where the context its
    # compose file names is (B716); a project's on its own.
    owner = devapp.owner_of(project, instance) or project
    own = devapp.nodes_of(owner) or []
    if not own:
        return {"error": f"{owner} has no node of its own to build its image on: set one in its settings"}
    builder, _ = devapp.queue.first_up(own) if hasattr(devapp.queue, "first_up") else (own[0], "")
    builder = builder or own[0]
    held = {"project": project, "instance": instance, "action": "rebuild", "hold": True,
            "ship": "build", "target": target}
    r = devapp.queue.job_add("operator", {"node": builder}, "compose", held, project)
    if r.get("error"):
        return r
    devapp._bump()

    def prepare():
        try:
            with devapp.on_node(builder):
                cfg = devapp._config(project, instance)
                bad = ship_binds(project, cfg)
                if bad:
                    devapp.queue.job_refuse(r["job"], (
                        f"{devapp.node_name(target)} does not hold {project}, so a bind into its tree has "
                        "nothing behind it there: " + "; ".join(bad)
                        + ". Use a named volume, or the instance's data directory"))
                    return
                if devapp.queue.job_release(r["job"], _ship_build_spec(project, instance, r["job"])):
                    with devapp._lock:
                        d = devapp._load()
                        devapp._rec(d, project, instance)["building_since"] = int(time.time())
                        devapp.write_json(devapp.FILE, d)
        except Exception as e:                                       # noqa: BLE001
            print(f"[devapp] preparing the shipped build of {project}/{instance}: {type(e).__name__}: {e}",
                  flush=True)
            devapp.queue.job_refuse(r["job"], f"could not prepare the build: {e}")
        finally:
            devapp._bump()

    threading.Thread(target=prepare, name=f"prepare-{r['job']}", daemon=True).start()
    return {"ok": True, "started": True, "job": r["job"], "built_on": devapp.node_name(builder)}


def ship_next(job, state):
    """After the build node's half: on success, the instance node's half,
    queued with its own job id in its plan; on anything else, the image
    file goes and the row says why (compose_done returns the reason)."""
    sp = job.get("spec") or {}
    project, instance = sp.get("project", ""), sp.get("instance") or devapp.MAIN
    if state != "succeeded" or not _image_file(project, instance).is_file():
        _image_file(project, instance).unlink(missing_ok=True)
        _clear_marker(project, instance)
        return
    target = sp.get("target") or devapp._instance_node(project, instance)
    held = {"project": project, "instance": instance, "action": "rebuild", "hold": True, "ship": "run"}
    r = devapp.queue.job_add("operator", {"node": target}, "compose", held, project)
    if r.get("error"):
        _image_file(project, instance).unlink(missing_ok=True)
        _clear_marker(project, instance)
        return
    with devapp.on_node(target):
        devapp.queue.job_release(r["job"], _ship_run_spec(project, instance, r["job"]))


def image_put(nid, q, stream, length):
    """The build node's upload (agent verb devimage-put): only for a job of
    that node's that is shipping, into the images store, whole or not at all."""
    j = devapp.queue.job(q.get("job", [""])[0], with_log=False) if devapp.queue else None
    sp = (j or {}).get("spec") or {}
    if not j or j.get("node") != nid or j.get("state") not in ("assigned", "running") or sp.get("ship") != "build":
        return {"error": "no image is being shipped by that job from this node"}, 403
    if length <= 0 or length > 64 * 1024 ** 3:
        return {"error": "an image is between 1 byte and 64 GB"}, 413
    dest = _image_file(sp.get("project", ""), sp.get("instance") or devapp.MAIN)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}")
    got = 0
    with open(tmp, "wb") as f:
        while got < length:
            chunk = stream.read(min(1 << 20, length - got))
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
    if got != length:
        tmp.unlink(missing_ok=True)
        return {"error": "the image ended early"}, 400
    os.replace(tmp, dest)
    return {"ok": True, "bytes": got}, 200


def image_path(nid, q):
    """The image for the instance node's fetch (agent verb devimage): only
    for a job of that node's that is loading one."""
    j = devapp.queue.job(q.get("job", [""])[0], with_log=False) if devapp.queue else None
    sp = (j or {}).get("spec") or {}
    # Assigned as well as running: the fetch is the run half's first step,
    # and on a public node it reached here before the agent's first log post
    # had marked the job running, so draconis was answered 403 (B648).
    if not j or j.get("node") != nid or j.get("state") not in ("assigned", "running") or sp.get("ship") != "run":
        return None, ({"error": "no image is being loaded by that job on this node"}, 403)
    p = _image_file(sp.get("project", ""), sp.get("instance") or devapp.MAIN)
    if not p.is_file():
        return None, ({"error": "the image is not here: build it again"}, 404)
    return p, None


def _plan_spec(project, instance, action, extra=None):
    """The whole of what an agent node needs for one action."""
    cf = devapp.compose_file(project, instance)
    files = {"docker-compose.yml": cf.read_text() if cf and cf.is_file() else ""}
    ep = devapp.env_path(project, instance)
    if ep.is_file():
        files["instance.env"] = ep.read_text()
        files["docker-compose.yml"] = devapp.env_to_instance(files["docker-compose.yml"],
                                                             "${BB_INSTANCE_ENV}")
    make, _cannot = devapp.missing_dirs(project, devapp._config(project, instance), instance)
    d = devapp.dev_data_dir(project, instance, make=False)
    return {"project": project, "instance": instance, "action": action,
            "name": devapp._pname(project, instance), "files": files,
            "dirs": sorted(set(list(make) + ([d] if d else []))),
            # Said in the spec as well as implied by the shorter plan, so the
            # bookkeeping does not have to infer intent from a step count.
            "gate": bool(action == "rebuild" and devapp.missing_env(project, instance)),
            "plan": _plan(project, instance, action, extra)}


def last_line(text):
    """The last line of a job's output that says something: not a command
    echo, not compose's progress lines ("Container x Creating"), not a
    traceback's indented frames; 200 characters at most."""
    skip = ("$ ", "    ", "Traceback")
    lines = [ln.strip() for ln in str(text or "").splitlines()]
    said = [ln for ln in lines if ln and not ln.startswith(skip)
            and not re.search(r"\b(Creating|Created|Starting|Started|Stopping|Stopped|Removing|Removed|Building|Built|Pulling|Pulled)\s*$", ln)]
    return (said or [ln for ln in lines if ln] or [""])[-1][:200]


def compose_done(job, state):
    """The records for an action the AGENT ran. Same bookkeeping the
    controller's own runner does, applied from the result: the node
    executes, this side remembers.

    Addressed at the job's node throughout, which is not decoration: a build
    is recorded against the daemon it landed on (daemon_id, _uid), and this
    runs from the agent's result post, where nothing has set that context.
    Without it every build a node ran was filed under the daemon "none", so
    state() read it as belonging to another machine and the row went back to
    saying nothing: the build happened, and the tab forgot it.
    """
    # Whatever the node's listing said before this action is no longer
    # true of it, and the row is read the moment the job ends.
    devapp._forget_reads((job or {}).get("node") or "")
    sp = (job or {}).get("spec") or {}
    with devapp.on_node((job or {}).get("node") or ""):
        # A relocation's own jobs (relocate.py) are its to follow on from.
        if sp.get("relocate"):
            return relocate.done(job, state)
        # ...and a rename's (relocate.rename_job): the records follow the data.
        if sp.get("rename"):
            return relocate.rename_done(job, state)
        said = _compose_done(job, state)
    # ...and the rebuild that ends one: the last half of a shipped one, or
    # the only one; a ship's first half that failed ends it too.
    if sp.get("action") == "rebuild" and not (sp.get("ship") == "build" and state == "succeeded"):
        relocate.built(sp.get("project", ""), sp.get("instance") or devapp.MAIN, state == "succeeded")
    # ...and one that built or started since a failed copy or move: that
    # failure is history, and the bell stops carrying it.
    if sp.get("action") in ("up", "rebuild", "update") and state == "succeeded" and not sp.get("ship") == "build":
        relocate.started(sp.get("project", ""), sp.get("instance") or devapp.MAIN)
    # ...and an update that pulled what was behind: nothing is, until the
    # next check says so (R195).
    if sp.get("action") == "update" and state == "succeeded":
        import imagecheck
        imagecheck.forget(devapp._pname(sp.get("project", ""), sp.get("instance") or devapp.MAIN))
    return said


def _compose_done(job, state):
    sp = (job or {}).get("spec") or {}
    project, instance = sp.get("project", ""), sp.get("instance") or devapp.MAIN
    action = sp.get("action")
    if sp.get("ship") == "build":
        # The build node's half (R166): nothing is recorded against it; the
        # instance node's half follows, or the row says why it did not, in
        # the words below.
        ship_next(job, state)
        if state == "succeeded":
            devapp._bump()
            return ""
    if sp.get("ship") == "run":
        _image_file(project, instance).unlink(missing_ok=True)
    # Only for a plan the AGENT ran. The controller's own runner does this
    # bookkeeping inline as it goes, and running it again from here undid
    # what it had decided: the env gate sets await_env after stopping, and
    # a second pass through the up branch cleared the flag the row is for.
    if not project or not action or not sp.get("plan"):
        return
    steps = 0
    for o in (job.get("outputs") or []):
        if isinstance(o, dict) and o.get("kind") == "compose":
            steps = int(o.get("steps_done") or 0)
    # rebuild records the build as soon as the build step passed, even when
    # the down or up after it did not: what was built IS built, and a row
    # that forgets says the code never compiled.
    # A shipped instance's build is recorded on its own node once the image
    # is loaded there (fetch, load, remove: three steps), never on the node
    # that built it (R166).
    if action == "rebuild" and sp.get("ship") != "build" and steps >= (3 if sp.get("ship") == "run" else 1):
        _record_build(project, instance)
    if state != "succeeded":
        _clear_marker(project, instance)
        devapp._bump()
        # The row's sentence, in the controller's words. The node reports
        # "exit 1", which is all it can honestly know (it ran an argv this
        # side composed), and the step names in that plan are what say which
        # part of the action died. Returned rather than written: job_result
        # owns the row (see nodes.job_result).
        if state == "canceled":
            return ""                     # the operator's own word is on it
        step = ""
        for o in (job.get("outputs") or []):
            if isinstance(o, dict) and o.get("kind") == "compose":
                step = str(o.get("failed_at") or "")
        # The output's last words ride the reason: the row shows the last
        # line of it, and the whole log is the Jobs tab's.
        tail = (devapp.queue.job_tail(job["id"], 500) if devapp.queue is not None else "").strip()
        head = {"building": "build failed", "saving": "saving the image failed",
                "shipping": "sending the image to the controller failed",
                "fetching": "fetching the image from the controller failed",
                "loading": "loading the image failed", "stopping": "stopping it failed",
                "starting": "up failed", "testing": "the tests failed",
                "preparing": "a bind directory could not be made on the node"}.get(step, "")
        # The row says what failed and the last line the step wrote, which
        # is where compose and docker put the reason ("No such image:
        # mariadb:11"); the whole tail was the row's before, newlines and
        # all, and read as a wall (the operator, 11 Oct). The log is the
        # Jobs tab's.
        return (head + ": " + last_line(tail)) if head and last_line(tail) else head
    # A gated rebuild built and stopped, and that is the whole of what it was
    # asked to do: rewrite the env with the old values in comments and leave
    # Up to the operator. The row below would clear the flag, so this returns.
    if sp.get("gate"):
        devapp._gate_env(project, instance)
        with devapp._lock:
            d = devapp._load()
            row = _kept(d, project, instance)
            if row is not None:
                row["await_env"] = True
                devapp.write_json(devapp.FILE, d)
        _clear_marker(project, instance)
        devapp._bump()
        return
    if action in ("up", "rebuild"):
        with devapp._lock:
            d = devapp._load()
            # A record Remove forgot meanwhile is not made again (B633).
            row = _kept(d, project, instance)
            if row is not None:
                row.pop("await_env", None)
                if not row.get("rev") or row.get("daemon") != devapp.daemon_id():
                    _stamp(row, project, instance)
                devapp.write_json(devapp.FILE, d)
    if action == "remove":
        _remove_records(project, instance)
    _clear_marker(project, instance)
    devapp._bump()


def _stamp(row, project, instance):
    """Write down what a build produced: the revision, and the ref it came from.

    The ref is written HERE, at the moment of the build, rather than read off
    the record when the row is drawn. The record's `ref` is the SETTING,
    which branch the NEXT rebuild will use, and changing it does not move
    what is already built. A row that describes a finished build from the
    setting says "built from <branch> <sha>" about a branch that may never
    have been built at all.
    """
    row.update(rev=devapp.built_rev(project, instance), at=int(time.time()),
               built_ref=str(row.get("ref") or ""),
               daemon=devapp.daemon_id(), daemon_uid=devapp._uid())


def _kept(d, project, instance):
    """The instance's record if it is still there, None once Remove forgot
    it: what a result that lands after the removal writes to (B633), where
    devapp._rec would make the row again. Only whether it is there: a
    record new made with nothing set is empty, and reading one with nothing
    but a marker as a ghost (B633's second way, closed since every marker
    goes through here too) left a first build unstamped, the row saying
    Build over a running container (B646)."""
    return (d.get(project) or {}).get(instance)


def _record_build(project, instance):
    with devapp._lock:
        d = devapp._load()
        rec = _kept(d, project, instance)
        # An instance removed while its rebuild was still running has no
        # record to stamp: making one here brought a Removed row back with
        # only rev, at and daemon on it (B633, 11 Oct). False says so.
        if rec is None:
            return False
        _stamp(rec, project, instance)
        devapp.write_json(devapp.FILE, d)
    return True


def _submit(project, instance, action, extra=None, check=None):
    """Queue a compose action for the node this instance is bound to.

    On an agent node the spec carries the whole plan and the agent runs it
    with the node's own docker (roadmap #18); on a node with no agent the
    spec names the action and the controller's runner does it over ssh, as
    it always has. Both are one `compose` job on the same queue.

    The job is queued at once, holding (spec["hold"], which job_next skips),
    and the request answers with it; the slow part, `check` (the risk
    gate's compose parse on the instance's node over ssh, the plan's own
    parse), runs on a thread behind that answer and then releases the job
    with its plan, or fails it with the refusal, where the row and the Jobs
    tab show the words. Before this a Rebuild answered only after parsing
    the compose on the node, up to 30s, and a phone dropped the request as
    a NetworkError with no reason (B260). A second press meanwhile meets
    BUSY, since the held job is active.
    """
    if devapp.queue is None:
        return {"error": "no job queue is configured here"}
    if _active_job(project, instance):
        return dict(BUSY)
    nid = devapp._instance_node(project, instance)
    if action == "rebuild" and shipped(project, instance):
        return _ship_submit(project, instance, nid)
    # An instance that follows its project (no node of its own) runs where
    # the project's primary is, or on the first of the set that is up when
    # the primary is not (R82 step 6); a bound instance stays where it is.
    fell_over = ""
    if nid and not devapp._read_rec(project, instance).get("node") and hasattr(devapp.queue, "first_up"):
        up, fell_over = devapp.queue.first_up(devapp.nodes_of(project) or [nid])
        nid = up or nid
    held = {"project": project, "instance": instance, "action": action, "hold": True}
    if fell_over:
        held["fell_over"] = fell_over
    r = devapp.queue.job_add("operator", {"node": nid}, "compose", held, project)
    if r.get("error"):
        return r
    devapp._bump()

    def prepare():
        try:
            with devapp.on_node(nid):
                why = check() if check else ""
                if why:
                    devapp.queue.job_refuse(r["job"], why)
                    return
                n = devapp.queue.node(nid) if nid else None
                spec = (_plan_spec(project, instance, action, extra)
                        if n and n["kind"] == "agent"
                        else {"project": project, "instance": instance, "action": action})
                if devapp.queue.job_release(r["job"], spec) and action == "rebuild":
                    # The started-marker: the row's "building since", cleared
                    # when the build reaches an end. Only on a record still
                    # there: a Remove racing this thread had the marker make
                    # the record again, empty but for it, and the build then
                    # stamped that into a ghost row (B633, the second way).
                    with devapp._lock:
                        d = devapp._load()
                        row = _kept(d, project, instance)
                        if row is not None:
                            row["building_since"] = int(time.time())
                            devapp.write_json(devapp.FILE, d)
        except Exception as e:                                       # noqa: BLE001
            # A fault preparing is the job's failure, said on its row,
            # never a thread dying quietly with the job held forever.
            print(f"[devapp] preparing {action} for {project}/{instance}: {type(e).__name__}: {e}",
                  flush=True)
            devapp.queue.job_refuse(r["job"], f"could not prepare the {action}: {e}")
        finally:
            devapp._bump()

    threading.Thread(target=prepare, name=f"prepare-{r['job']}", daemon=True).start()
    return {"ok": True, "started": True, "job": r["job"]}


def state_ports(project, instance):
    """The published ports of one instance, from the daemon, for a route
    that has to pick one."""
    try:
        return next((x["ports"] for x in states(project) if x["instance"] == instance), [])
    except Exception:            # noqa: BLE001 (a listing failure is 'none published')
        return []


def route_set(project, instance, mode, port=None):
    """Choose how an instance is reached. lan is a record; funnel is a
    record and a system job on the node (and leaving funnel turns the
    node's funnel off); public is refused, named as unbuilt."""
    if mode not in devapp.ROUTE_MODES:
        return {"error": f"a route is {', '.join(devapp.ROUTE_MODES)}"}
    if mode == "public":
        return {"error": "public routes are not built; lan and funnel are (docs/nodes.md §7)"}
    try:
        port = int(port) if port not in (None, "") else None
    except (TypeError, ValueError):
        return {"error": "a port is a number"}
    if port is not None and not 1 <= port <= 65535:
        return {"error": "a port is a number between 1 and 65535"}
    nid = devapp._instance_node(project, instance)
    was = (devapp._read_rec(project, instance).get("route") or {}).get("mode", "lan")
    job = None
    if mode == "funnel" or was == "funnel":
        if devapp.queue is None or not nid:
            return {"error": "no node to apply a funnel on"}
        fport = port or (devapp.route_view(project, instance, state_ports(project, instance)).get("port"))
        if not fport:
            return {"error": "a funnel needs a port, and the instance publishes none"}
        r = devapp.queue.node_funnel("operator", nid, fport, on=(mode == "funnel"))
        if r.get("error"):
            return r
        job = r.get("job")
    with devapp._lock:
        d = devapp._load()
        devapp._rec(d, project, instance)["route"] = {"mode": mode, "port": port}
        devapp.write_json(devapp.FILE, d)
    devapp._bump()
    return {"ok": True, "job": job}


def abort_job(project, instance):
    """Stop this instance's job, if it has one. True if there was one."""
    j = _active_job(project, instance)
    if j is None:
        return False
    if devapp.runner is not None:
        devapp.runner.cancel("operator", j["id"])
    else:
        devapp.queue.job_cancel("operator", j["id"])
    devapp._bump()
    return True


@devapp._on_instance
def remove_instance(project, instance):
    """Take a container out of the manager: down it, then forget the record.

    What is NOT removed is the env file and the data directory. Removing is
    the way to tidy the list, not a way to destroy work, and an instance
    remade under the same name finding its old env there is the behavior
    somebody who removed one by mistake would want. Deleting those is a shell
    away and is not something a button here should do quietly.

    **A daemon that does not answer still gives up its row.** Down is the
    first half of this and needs the daemon; forgetting the record is the
    second and is this side's own file. Making the whole verb wait on the
    daemon meant a row on a machine that had gone away could be removed by
    nobody, the one state a list must not have, because the row is the only
    control over the thing it names. So when the daemon is unreachable the
    record goes and what could not be done is said: anything up over there is
    left up, and the env and the data directory stay where they always do, so
    the same name sent again adopts all three.
    """
    if instance not in (devapp._load().get(project) or {}):
        return {"error": f"{project} has no instance called {instance}"}
    got = devapp.available_cached()
    # ...but an enrolled agent node that is only quiet has not gone away: a
    # compose job waits in its queue for its next poll (nodes.job_add takes
    # one on a quiet agent), and a node reads quiet for a minute every few
    # (B550). Forgetting the row there left the container running with no
    # row to remove it from and its name taken (B597), so the down is queued.
    n = devapp._agent_here()
    if not got.get("on") and n and n.get("state") == "online" and not n.get("live"):
        return _submit(project, instance, "remove")
    if not got.get("on"):
        _remove_records(project, instance)
        return {"ok": True, "forgot": True,
                "note": "its daemon does not answer, so nothing was taken "
                        "down: the row is gone and whatever was running there "
                        "is still running"}
    return _submit(project, instance, "remove")


def _job_remove(project, instance, run):
    run.step("stopping")
    r = devapp._run(devapp._compose(project, instance, "down", "--remove-orphans"), timeout=180,
                    sink=run.line, hold=run.hold)
    if run.canceled:
        return {"state": "canceled", "error": "stopped; it is still in the manager"}
    if r["code"] != 0:
        return {"state": "failed",
                "error": ("could not take it down, so it was left alone:\n"
                          + r["out"])[-500:]}
    # A container written here has nowhere else to come back from: its
    # compose file IS the thing, and leaving it behind would keep the name
    # taken by something with no row to remove it from. A project's instance
    # keeps its env and data, which is what that button already promises.
    _remove_records(project, instance)
    return {"state": "succeeded"}


def _remove_records(project, instance):
    """What a successful remove forgets. Shared by the controller's runner
    and the agent's completion hook, so the two cannot drift on which of a
    container's traces survive it."""
    if devapp.is_file_source(project, instance):
        devapp.forget_container(project)
        devapp._bump()
        return
    with devapp._lock:
        d = devapp._load()
        if instance in (d.get(project) or {}):
            del d[project][instance]
            if not d[project]:
                del d[project]
            devapp.write_json(devapp.FILE, d)
    devapp._bump()


def states(project):
    """Every instance of a project, in one call, for the manager."""
    with devapp.read_scope():
        return [state(project, i) for i in devapp.instances(project)]


def _running(project, instance=devapp.MAIN):
    n = devapp._agent_here()
    if n:
        return bool(devapp._agent_instance_containers(n, project, instance, True))
    r = devapp._run(devapp._compose(project, instance, "ps", "--status", "running", "-q"), timeout=20)
    return r["code"] == 0 and bool(r["out"].strip())


def _exists(project, instance=devapp.MAIN):
    """Does compose know about any container here, running or not?

    A container that EXITED (a crash, a bad entrypoint, an OOM) is still
    there, still holding its name and the project's network, and `down` is the
    only thing that clears it. Asking only about RUNNING containers is what
    left a crashed instance with a grayed-out Down and no way out of the
    dashboard at all.
    """
    n = devapp._agent_here()
    if n:
        return bool(devapp._agent_instance_containers(n, project, instance, False))
    r = devapp._run(devapp._compose(project, instance, "ps", "-aq"), timeout=20)
    return r["code"] == 0 and bool(r["out"].strip())


@devapp._on_instance
def running_names(project, instance=devapp.MAIN):
    """The names of an instance's running containers, from its own daemon:
    what a container's Shell may name (R218 step 4), asked when one opens
    rather than taken from the page's last listing. The daemon's own listing
    by the compose project's label, on any daemon: the one the row's
    services are drawn from, so the two cannot name a container apart."""
    got = devapp._agent_instance_containers(devapp._agent_here(), project, instance, True)
    return [c["name"] for c in (got or [])]


@devapp._on_instance
def state(project, instance=devapp.MAIN):
    """Everything the Artifacts row needs, or the reason there is no row."""
    if devapp.compose_file(project) is None:
        return {"compose": False}
    a = devapp.available()
    built = devapp._read_rec(project, instance)
    # A build only counts on the daemon it happened on. Repointing an instance
    # at another VM leaves the image and the containers behind on a machine
    # this container can no longer see, and the row went on saying "built from
    # <rev>" and offering Rebuild for something that had never been built here.
    # A record written before this field says nothing about which daemon it
    # was, and not knowing is not yes.
    #
    # Everything claiming a build goes: the rev and its date, the env gate a
    # build tripped, the marker saying one is in flight. What stays is the
    # operator's risk acknowledgement, which is about what the compose file
    # asks for and would be true on any daemon. Dropping the env gate costs
    # nothing: up() refuses on a live missing_env() rather than on the flag.
    if built.get("daemon") != devapp.daemon_id():
        built = {k: v for k, v in built.items()
                 if k not in ("rev", "at", "built_ref", "await_env",
                              "building_since")}
    out = {"compose": True, "available": a["on"], "why": a["why"],
           # WHICH machine that was about, which the row could not say. An
           # instance is pinned to the node it was made on and a project
           # repointed since keeps it, so "the node I pointed it at" and the
           # machine this actually asked are not always the same one, and
           # when the answer is a refusal, that is the first thing to know.
           "where": a.get("where", ""),
           # ...and what to call it: the node's name for an agent node, whose
           # ssh address `where` still carries for the page's port links and
           # nobody dials (B313). The row prints this one after a refusal.
           "daemon": a.get("kind", ""),
           # The compose project name, which is what actually groups the
           # containers, the network and the volumes. Not the container name:
           # a compose file may set container_name to anything it likes, and
           # there may be several. This is the one name that is always true.
           "instance": instance,
           "name": devapp._pname(project, instance),
           "needs_build": True,
           "built_rev": built.get("rev", ""), "built_at": built.get("at", 0),
           # The ref the build was MADE from, stamped when it was made. Not
           # `ref` below, which is the setting for the next one: a build does
           # not move because the pin did. Empty on a build made before this
           # was recorded, and then the row names the revision alone rather
           # than a branch nobody wrote down.
           "built_ref": built.get("built_ref", ""),
           # A container written here has no repository, so built_rev is its
           # definition hashed (devapp.built_rev), not a commit, and a verb
           # printing it says which (B735).
           "written": devapp.is_file_source(project, instance),
           "missing_env": devapp.missing_env(project, instance),
           "await_env": bool(built.get("await_env")),
           # A marker with no build running behind it means the container went
           # away mid-build: docker compose build is a subprocess of the
           # dashboard, so it died with it. Everything else already recovers
           # correctly (the last SUCCESSFUL build is still what built_rev
           # says, and Rebuild is live because the code has moved) but
           # without this the operator sees a button they thought they had
           # already pressed and is told nothing.
           "interrupted": bool(built.get("building_since")
                               and not _active_job(project, instance)),
           # Which branch it builds from, when it is pinned to one. On the
           # base dict rather than inside the `if a["on"]` below: what an
           # instance is built FROM is a fact about the record, and a daemon
           # that is not answering does not make it unknown.
           "ref": str(devapp._read_rec(project, instance).get("ref") or ""),
           "job": devapp.job_view(project, instance)}
    if a["on"]:
        cfg = devapp._config(project, instance)
        out["needs_build"] = devapp.needs_build(cfg)
        rs = devapp.risks(project, cfg)
        out["risks"] = rs
        out["problems"] = devapp.problems(project, cfg) + devapp.host_map()[1]
        # A compose that reserves the GPU on a node that cannot hand it to a
        # container is the same kind of thing: it cannot start as written.
        nogpu = devapp.gpu_gate(project, instance, cfg)
        if nogpu:
            out["problems"].append(nogpu)
        out.update(devapp.wiring(cfg))
        # ...and the ports somebody else is already on. After wiring(), which
        # is what says which ports this instance wants. Its own field rather
        # than a line in `problems`, because the two views that read this
        # disagree about what it means: on the Docker manager, where Up is,
        # it is a compose that cannot start as written, right now; on the
        # Artifacts view, whose one button is Send, it is a note that the
        # instance being sent will set its own port in its env, which is the
        # form Send opens. Folded into `problems` it read there as "will not
        # work", in red, over the button that makes it work.
        out["port_clash"] = devapp.taken_ports(project, instance, out.get("ports"))
        out["route"] = devapp.route_view(project, instance, out.get("ports"))
        out["risks_digest"] = devapp.risk_digest(rs)
        # True when nothing stands in the way: either the file asks for
        # nothing beyond its own directory, or the operator has already said
        # yes to exactly this set.
        out["risks_ack"] = (not rs
                            or built.get("risks_ack") == out["risks_digest"])
        out["running"] = _running(project, instance)
        # Only worth a second call when nothing is running: a running stack
        # self-evidently has containers, and this is on the artifacts poll.
        out["exists"] = out["running"] or _exists(project, instance)
        # A container written here has no repository: its revision is its
        # definition (built_rev hashes the compose file and the env), and git
        # asked about a directory that is not there warned on every poll and
        # left the row reading "changed" forever.
        filed = devapp.is_file_source(project, instance)
        head = devapp.built_rev(project, instance) if filed else devapp._head(project, instance)
        # An instance pinned to a ref is not waiting on the working copy: its
        # build tree is its own, and an uncommitted edit in the project's tree
        # says nothing about it. What "moved" means there is that the BRANCH
        # has, which is the comparison above.
        pinned = bool(devapp._read_rec(project, instance).get("ref"))
        dirty = False if pinned or filed else devapp._dirty(project)
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

@devapp._on_instance
def up(project, instance=devapp.MAIN, ack=""):
    # The refusals this side can make alone come first, so a request that
    # is going to be turned down does not flash a job at every other browser
    # on its way to saying no. The risk gate reads the compose on the node,
    # and runs behind the answer (B260): its refusal is the job's.
    miss = devapp.missing_env(project, instance)
    if miss:
        return {"error": "the env is missing " + ", ".join(miss[:4])
                         + (" …" if len(miss) > 4 else "")
                         + ": fill it in first (Env)"}
    clash = devapp.name_clash(project, instance)
    if clash:
        return {"error": clash}
    return _submit(project, instance, "up",
                   check=lambda: devapp.gpu_gate(project, instance) or devapp._risk_gate(project, instance, ack))


def _job_up(project, instance, run):
    run.step("starting")
    devapp.ensure_dirs(project, instance, sink=run.line)
    # `compose up -d`, and nothing more clever: compose builds an image that
    # is missing, so Up on a never-built project does what the CLI does
    # rather than refusing on a rule of this dashboard's invention. Streamed,
    # because that implicit build can pull for half an hour.
    r = devapp._run(devapp._compose(project, instance, "up", "-d", "--remove-orphans"), timeout=1800,
                    env_extra=devapp._dev_data_env(project, instance) | devapp._build_env(project, instance),
                    sink=run.line, hold=run.hold)
    if run.canceled:
        return {"state": "canceled", "error": "stopped"}
    if r["code"] != 0:
        # On the JOB, which is what the row reads: without this a failed Up
        # left a row that said "stopped" with no account of why.
        return {"state": "failed", "error": "up failed:\n" + r["out"][-400:]}
    with devapp._lock:
        d = devapp._load()
        # ...unless Remove forgot the record while this ran (B633).
        row = _kept(d, project, instance)
        if row is not None:
            row.pop("await_env", None)
            # An implicit build is still a build, so the row stops claiming the
            # project was never built while a container from it is running. Also
            # when the record belongs to a daemon we no longer talk to: state()
            # reads that as never-built-here, and without the second test the row
            # would go on saying so with the instance up in front of it.
            if not row.get("rev") or row.get("daemon") != devapp.daemon_id():
                _stamp(row, project, instance)
            devapp.write_json(devapp.FILE, d)
    devapp._bump()
    return {"state": "succeeded"}


@devapp._on_instance
def down(project, instance=devapp.MAIN):
    return _submit(project, instance, "down")


@devapp._on_instance
def update(project, instance=devapp.MAIN):
    """Update on a row whose registry images moved (imagecheck, R195): pull
    them again and up, nothing built."""
    return _submit(project, instance, "update")


_ARG = re.compile(r"[A-Za-z0-9._/:=@%+,-]{1,200}")


@devapp._on_instance
def test(project, instance=devapp.MAIN, cmd="", args=()):
    """Run the project's recorded test command inside its dev instance
    (roadmap R48, step 1): the container is the boundary, so a suite that
    tests BuilderBot cannot disturb the BuilderBot it is running on.

    The command is the settings dialog's, handed in by the server, never an
    argument the caller names; the arguments a runner takes (file names) go
    as positional parameters. `exec` needs the instance UP: a container that
    is down is said so, not started behind the operator's back. Only an
    agent node runs it, since every plan runs on the agent now.
    """
    if devapp.compose_file(project) is None:
        return {"error": "no compose file here, so there is no container to test in"}
    cmd = str(cmd or "").strip()
    if not cmd:
        return {"error": f"no test command is set for {project}: bb settings set test "
                         "'...' fills it in, or the operator does on the project's "
                         "notebook Settings (Build and test)"}
    bad = [a for a in args if not _ARG.fullmatch(str(a))]
    if bad:
        return {"error": f"an argument the test command cannot take: {bad[0]!r}"}
    # The two facts starting a run depends on, and only those. This asked for
    # the whole state() before it answered: a compose config parse, the risks,
    # the problems, the host mapping, a docker ps for port clashes, running,
    # exists and the git head, each a round trip through the agent to the node
    # and one after another. On an unlucky poll cycle that passed the caller's
    # thirty seconds, the caller gave up saying "timed out", and the run this
    # then started went on unattended inside the container for fifteen
    # minutes, holding the node's one slot (B202). Everything state() works
    # out is for a row somebody is looking at; nobody is looking here.
    a = devapp.available()
    if not a["on"]:
        return {"error": a["why"] or "the instance's daemon is not reachable"}
    if not _running(project, instance):
        return {"error": f"{devapp._pname(project, instance)} is not running: Up on the Docker tab "
                         "(or a rebuild) starts it, and the tests run inside it"}
    cfg = devapp._config(project, instance)
    services = devapp._services(cfg)
    if not services:
        return {"error": "the compose file names no service to run the tests in"}
    # The service the project builds, else the first one: the project's own
    # code is what the tests are about.
    service = next((n for n, sv in services.items() if sv.get("build")), next(iter(services)))
    workdir = project_dir_inside(services[service], project)
    nid = devapp._instance_node(project, instance)
    n = devapp.queue.node(nid) if (devapp.queue and nid) else None
    if not n or n["kind"] != "agent":
        return {"error": "tests run inside an instance on an agent node, and this one is not on one"}
    return _submit(project, instance, "test",
                   {"service": service, "cmd": cmd, "args": [str(a) for a in args][:32],
                    "workdir": workdir})


def project_dir_inside(sv, project):
    """Where a service sees the project's directory: the target of the bind
    that carries it (the directory itself, or a parent such as the whole
    projects share), with the rest of the path appended. "" when nothing
    mounts it, which is an image that copied the code at build time and
    whose own working directory is the right place."""
    try:
        pdir = str((devapp.WORKSPACE / project).resolve())
    except OSError:
        pdir = str(devapp.WORKSPACE / project)
    for v in sv.get("volumes") or []:
        if not isinstance(v, dict) or (v.get("type") or "") != "bind":
            continue
        src, tgt = str(v.get("source") or "").rstrip("/"), str(v.get("target") or "").rstrip("/")
        if not src or not tgt:
            continue
        try:
            src = str(Path(src).resolve())
        except OSError:
            pass
        if pdir == src:
            return tgt
        if pdir.startswith(src + "/"):
            return tgt + pdir[len(src):]
    return ""


def _job_update(project, instance, run):
    """Update where the controller runs the job itself: pull, then up."""
    run.step("pulling")
    r = devapp._run(devapp._compose(project, instance, "pull", "--ignore-buildable"), timeout=1800,
                    sink=run.line, hold=run.hold)
    if run.canceled:
        return {"state": "canceled", "error": "stopped before it started again"}
    if r["code"] != 0:
        return {"state": "failed", "error": ("could not pull its images:\n" + r["out"])[-500:]}
    return _job_up(project, instance, run)


def _job_down(project, instance, run):
    run.step("stopping")
    r = devapp._run(devapp._compose(project, instance, "down", "--remove-orphans"), timeout=180,
                    sink=run.line, hold=run.hold)
    if run.canceled:
        return {"state": "canceled", "error": "stopped"}
    if r["code"] != 0:
        return {"state": "failed", "error": ("down failed:\n" + r["out"])[-500:]}
    devapp._bump()
    return {"state": "succeeded"}


@devapp._on_instance
def rebuild(project, instance=devapp.MAIN, ack="", gate=True):
    """Build, then bounce, or stop at the env gate. A job: a build is
    minutes, and the poll watches it through job_rev. The name and the
    worktree are this side's and are checked in front of the answer; the
    risk gate reads the compose on the node and runs behind it (B260), so
    its refusal is the job's, on the row.

    `gate` is False for a build its project's setting has already answered
    for: a session's on auto, or a person's Allow on a session's question.
    The confirmation of what a compose asks for is a person's own press of
    Build; a session's build follows Claude may: Run its container like
    every other (the operator, 26 Sep: auto does it, ask asks, deny
    refuses)."""
    if devapp.compose_file(project) is None:
        return {"error": "no compose file here"}
    clash = devapp.name_clash(project, instance)
    if clash:
        return {"error": clash}
    moved = sync_work_tree(project, instance)
    if moved:
        return {"error": moved}
    # The GPU's gate is for a session's build too: it is about what the node
    # can do, not about who confirmed what.
    return _submit(project, instance, "rebuild",
                   check=lambda: devapp.gpu_gate(project, instance)
                   or (devapp._risk_gate(project, instance, ack) if gate else ""))


def run_compose_job(job, run):
    """The compose runner jobs.py calls for a "compose" job: one action on
    one instance, with the daemon of the node the job was placed on
    addressed for everything underneath."""
    sp = job.get("spec") or {}
    project, instance = sp.get("project", ""), sp.get("instance") or devapp.MAIN
    fn = {"up": _job_up, "down": _job_down, "rebuild": _job_rebuild,
          "remove": _job_remove, "update": _job_update}.get(sp.get("action"))
    if fn is None:
        return {"state": "failed", "error": f"unknown compose action {sp.get('action')!r}"}
    with devapp.on_node(job.get("node") or devapp._instance_node(project, instance)):
        return fn(project, instance, run)


def _clear_marker(project, instance=devapp.MAIN):
    """Drop the started-marker: the build reached an end, whichever end."""
    with devapp._lock:
        d = devapp._load()
        rec = (d.get(project) or {}).get(instance)
        if rec is not None:
            rec.pop("building_since", None)
            devapp.write_json(devapp.FILE, d)


def _job_rebuild(project, instance, run):
    try:
        run.step("building")
        if devapp.work_tree(project, instance) is not None:
            # A pinned instance builds from a worktree of its ref, which holds
            # the files committed there and nothing else: a gitignored file
            # changed beside the project's checkout is not in this build,
            # and the log says so before the build rather than after (B595).
            ref = str(devapp._read_rec(project, instance).get("ref") or "").strip()
            run.line(f"building from {ref} at {devapp._head(project, instance)[:12] or '?'}: "
                     "the files committed there; untracked and ignored files of the working tree are not in it\n")
        elif devapp._read_rec(project, instance).get("source") == "file":
            # ...and a container written here that builds from a git URL is
            # the same: the files committed at that ref, never a working
            # tree's untracked or ignored ones (B595).
            try:
                with open(devapp.compose_file(project, instance), encoding="utf-8") as fh:
                    urls = devapp.remote_contexts(fh.read())
            except (OSError, TypeError):
                urls = []
            for u in urls:
                run.line(f"building from {u}: the files committed there; untracked and ignored files of a working tree are not in it\n")
        r = devapp._run(devapp._compose(project, instance, "build"), timeout=3600,
                        env_extra=devapp._dev_data_env(project, instance) | devapp._build_env(project, instance),
                        sink=run.line, hold=run.hold)
        if run.canceled:
            return {"state": "canceled",
                    "error": "stopped; what had already been built is kept"}
        if r["code"] != 0:
            # The reason carries the output's last words: the row shows the
            # last line of it, and the whole log is the Jobs tab's.
            return {"state": "failed", "error": "build failed:\n" + r["out"][-400:]}
        if not _record_build(project, instance):
            # Removed from the Docker tab while it was building (B633): the
            # remove took it down, and nothing of it is started again.
            return {"state": "failed", "error": "removed from the Docker tab while it was building: the image is built, nothing started"}
        run.step("stopping")
        devapp._run(devapp._compose(project, instance, "down", "--remove-orphans"), timeout=180,
                    sink=run.line, hold=run.hold)
        # Checked here as well as after each of the other two. Abort during
        # this step reached nothing once: there was no held process to
        # signal and nothing read the flag again until after `up`, so the
        # container came up and the job then reported that it had been
        # stopped. Every phase boundary asks now.
        if run.canceled:
            return {"state": "canceled",
                    "error": "stopped: the image is built, but not started"}
        if devapp.missing_env(project, instance):
            # The gate: new settings exist that the env does not answer.
            # Rewrite the env with the old values in comments and leave Up
            # to the operator; see the module docstring.
            devapp._gate_env(project, instance)
            with devapp._lock:
                d = devapp._load()
                devapp._rec(d, project, instance)["await_env"] = True
                devapp.write_json(devapp.FILE, d)
            return {"state": "succeeded"}
        run.step("starting")
        devapp.ensure_dirs(project, instance, sink=run.line)
        # Streamed too: `up` pulls anything the build did not, which is the
        # long wait on a compose file made of published images rather than a
        # Dockerfile, exactly the case that looked like a hang.
        r = devapp._run(devapp._compose(project, instance, "up", "-d", "--remove-orphans"), timeout=600,
                        env_extra=devapp._dev_data_env(project, instance),
                        sink=run.line, hold=run.hold)
        if run.canceled:
            return {"state": "canceled",
                    "error": "stopped: the image is built, but not started"}
        if r["code"] != 0:
            return {"state": "failed", "error": "up failed:\n" + r["out"][-400:]}
        return {"state": "succeeded"}
    finally:
        # Whatever happened (built, failed, gated) the build is no longer in
        # flight, so the marker goes. Only a killed process leaves it behind,
        # which is exactly what it is for.
        _clear_marker(project, instance)
        devapp._bump()


def make_instance(project, instance, node="", owner=None, ref="", ship=False, compose=""):
    """A new container of a project, pinned to the branch it is to build
    from when one is named: `new` from the dialog or a session, and Allow on
    a session's asked one, which is the same making. Nothing is built.

    The pin comes before the first build, or that build comes from the
    project's checkout and the row says otherwise. A pin that is refused
    takes the record with it, or the retry that fixes the branch is told the
    container already exists (B259); nothing was built, so there is nothing
    else to undo.
    """
    r = devapp.create_instance(project, instance or devapp.MAIN, node, owner, ship=ship, compose=compose)
    if not r.get("error") and ref:
        p = devapp.set_ref(project, r["instance"], ref)
        if p.get("error"):
            _remove_records(project, r["instance"])
            return p
    return r


def act(project, instance, action, req, *, test_cmd="", gate=True):
    """One dev-instance verb, as the dashboard and `bb devapp` name them,
    once server.py has decided who may ask (docker-write, the per-project
    dial, a session's own node) and which instance is meant.

    The answer is (payload, status): a module's {ok} or {error} with 400 on
    the error, the way Handler._result reads one, and the instance's fresh
    state riding on every change so nothing on screen is stale. Here rather
    than in the handler because what a verb means is this module's to say
    (the one-file rule); the handler holds the gate and nothing else.
    `gate` is rebuild()'s: False for a session's, since a session's rebuild
    reaches here only on its project's `auto` (at `ask` it is a question to
    a person first, and at `deny` it is refused before this).
    """
    f = devapp.field
    if action == "abort":
        # Before the instance check below: a job can be running against an
        # instance that has since been removed, and stopping it must not
        # depend on the thing it is building still existing.
        return {"ok": True, "stopped": abort_job(project, instance)}, 200
    if action == "starter":
        # The project's .env.example, for a container that does not exist
        # yet: the send dialog opens on it so the env is filled in before
        # the first build rather than after it stops at the gate. Reads
        # nothing of the instance, which is the point: there is none.
        # The one beside the compose file Send was pressed on, when it has
        # its own.
        rel = f(req, "compose")
        if devapp.compose_ok(project, rel):
            return {"error": devapp.compose_ok(project, rel)}, 400
        with devapp.composing(rel or None):
            return {"text": devapp.starter(project)}, 200
    if action == "new":
        # The one action whose instance does not exist yet, which is what it
        # is for. Everything below names one that must exist, because the
        # string decides a compose project and a data directory and is not
        # somewhere an arbitrary one should reach.
        # The project it belongs to when the request says, "" being none.
        r = make_instance(project, instance, f(req, "node"),
                          f(req, "owner") if "owner" in req else None, f(req, "ref"),
                          ship=req.get("ship") is True, compose=f(req, "compose"))
        if not r.get("error") and isinstance(req.get("text"), str) \
                and req["text"].strip():
            # Written before the build that follows, so the first one has
            # the env it needs instead of stopping at the gate and asking
            # for it afterwards. A failed write is said: it was dropped, and
            # the build then ran as if nothing had been typed.
            w = devapp.write_env(project, req["text"], r["instance"])
            if w.get("error"):
                _remove_records(project, r["instance"])      # as above (B259)
                return r | {"error": w["error"]}, 400
        return r, (400 if r.get("error") else 200)
    if instance not in devapp.instances(project):
        # Named, so a verb that assumed the default meets the one that
        # exists (bb devapp rebuild with one instance called builderbot-dev).
        have = devapp.instances(project)
        return {"error": f"no instance {instance} of {project}"
                + (f"; --instance names one of {', '.join(have)}" if have else "")}, 400
    if action == "remove":
        r = remove_instance(project, instance)
        return r, (400 if r.get("error") else 200)
    if action == "ref":
        # Which branch this instance builds from. `docker-write` has already
        # had its say in the handler, so this is an administrator's like
        # every other thing that changes what a container IS.
        r = devapp.set_ref(project, instance, f(req, "ref"))
        return r, (400 if r.get("error") else 200)
    if action == "move":
        # Into another project, as its own instance (devapp.move_instance).
        # Not while a job builds it: the job names the old project.
        if _active_job(project, instance) is not None:
            return {"error": "a job is running on it: wait for it, or Stop it, then move it"}, 400
        r = devapp.move_instance(project, instance, f(req, "to"))
        return r, (400 if r.get("error") else 200)
    if action == "relocate":
        # To another node, its data with it (relocate.py): a copy beside
        # it under a new name, or the same one moved.
        env = req.get("text") if isinstance(req.get("text"), str) else None
        r = relocate.start(project, instance, f(req, "mode"), f(req, "node"), f(req, "name"), env,
                           data=f(req, "data"))
        return r, (400 if r.get("error") else 200)
    if action == "unpack":
        # Its data, carried as an archive, written into its volumes now
        # (relocate.unpack_start).
        r = relocate.unpack_start(project, instance)
        return r, (400 if r.get("error") else 200)
    if action == "owner":
        # Which project it belongs to. An administrator's too, and the name
        # was checked against the projects in the handler.
        r = devapp.set_owner(project, instance, f(req, "owner"))
        return r, (400 if r.get("error") else 200)
    if action == "state":
        # The full picture for one instance (risks, problems, the parsed
        # compose), which overview() deliberately does not compute for
        # every instance at once. Asked when somebody is about to act.
        return {"state": state(project, instance)}, 200
    # `ack` is the digest of the risk list the operator was actually
    # shown, not a bare yes. A compose file that gains a mount between
    # the row rendering and the button being pressed does not inherit the
    # acknowledgement of the one before it.
    # BuilderBot's own (System, R180) is managed: its name, compose file and
    # env are written by the surface that deployed it, never edited here
    # (the operator, 11 Oct).
    if action in ("env-set", "compose-set", "rename") and devapp.owner_of(project, instance) == devapp.SYSTEM:
        return {"error": f"{devapp._pname(project, instance)} is BuilderBot's own and managed: change it where it was deployed from"}, 400
    if action == "up":
        r = up(project, instance, f(req, "ack"))
    elif action == "down":
        r = down(project, instance)
    elif action == "update":
        r = update(project, instance)
    elif action == "test":
        r = test(project, instance, test_cmd,
                 [str(a) for a in (req.get("args") or [])][:32])
    elif action == "rebuild":
        r = rebuild(project, instance, f(req, "ack"), gate=gate)
    elif action == "env-get":
        # An empty env opens on the example rather than on nothing. The
        # `missing` list still answers about what is STORED, so the hint
        # under the box stays true while the box is only a draft.
        stored = devapp.read_env(project, instance)
        return {"text": stored or devapp.starter(project, instance),
                "seeded": not stored,
                "missing": devapp.missing_env(project, instance)}, 200
    elif action == "env-set":
        r = devapp.write_env(project, req.get("text") or "", instance)
    elif action == "compose-get":
        # The Docker tab's Edit on a project's instance (the operator, 9 Oct):
        # its compose file beside its env, in one dialog.
        cf = devapp.compose_file(project, instance)
        if devapp.is_file_source(project, instance) or cf is None:
            return {"error": f"{project} has no compose file in its tree to edit"}, 400
        return {"text": cf.read_text(encoding="utf-8", errors="replace"), "file": cf.name}, 200
    elif action == "compose-set":
        r = set_compose(project, instance, req.get("text"))
    elif action == "rename":
        # A project's container named whatever its owner wants, while it is
        # down (the operator, 11 Oct): the Edit dialog's Name field.
        import containers
        r = containers.rename_container(project, f(req, "name"), instance)
    elif action == "route":
        # How the instance is reached (docs/nodes.md §7): lan or funnel,
        # on which published port.
        r = route_set(project, instance, f(req, "mode"), req.get("port"))
    else:
        return {"error": f"unknown action: {action}"}, 400
    if r.get("error"):
        return r, 400
    return r | {"state": state(project, instance)}, 200


def host_ports(ports):
    """The node-side TCP port numbers of an instance's published ports, as
    _ports() writes them (127.0.0.1:9090->80/tcp, 9090->80/tcp)."""
    out = []
    for p in ports or []:
        host, _, rest = str(p).partition("->")
        if rest.endswith("/udp"):
            continue
        num = host.rpartition(":")[2]
        if num.isdigit() and int(num) not in out:
            out.append(int(num))
    return out


def probe(project, instance, req, principal):
    """Whether this instance answers on its node's loopback (R248): a TCP
    connect and an HTTP GET of `path` on each of its published ports, or on
    the one `port` names, run there by the node's agent. Read-only, so a
    session reads it as it reads the state, with no root ask: Turing Lens's
    `bb root run` for exactly this expired unseen after 15 minutes (14 Oct).
    Only the instance's own ports: the node's others are not this caller's
    to scan. (payload, status)."""
    if devapp.queue is None:
        return {"error": "nodes are not on in this install, so there is no node to probe from"}, 400
    nid = devapp._instance_node(project, instance)
    if not nid:
        return {"error": f"{devapp.pname(project, instance)} has no node to probe on"}, 400
    mine = host_ports(state_ports(project, instance))
    if not mine:
        return {"error": f"{devapp.pname(project, instance)} publishes no TCP port on its node "
                         "(is it up? bb devapp says)"}, 400
    want = devapp.field(req, "port")
    if want not in (None, ""):
        try:
            want = int(want)
        except (TypeError, ValueError):
            return {"error": "a port is a number"}, 400
        if want not in mine:
            return {"error": f"port {want} is not one {devapp.pname(project, instance)} publishes: "
                             + ", ".join(str(p) for p in mine)}, 400
        mine = [want]
    r = devapp.queue.probe_ports(principal, nid, mine, devapp.field(req, "path") or "/")
    if r.get("error"):
        return r, 400
    return {"ok": True, "name": devapp.pname(project, instance), "node": devapp.node_name(nid),
            "ports": r["ports"]}, 200


def request(project, instance, action, req, *, me, principal, dial="", test_cmd=""):
    """One dev-instance verb as the Docker tab and `bb devapp` send it, once
    server.py has decided this caller may: a session whose project's Run
    its container dial is at `ask` puts a change in front of a person
    instead (a rebuild, the env, making or removing the container); any
    other is act(), with a line in the project's chat first for what the
    others sharing it would want to know, and the sessions' networks told
    after a container is made, removed or given away. (payload, status)."""
    sess = me.get("session") or ""
    if action == "probe":
        return probe(project, instance, req, principal)
    if sess and dial == "ask" and action in ("rebuild", "env-set", "new", "remove"):
        # Aborting is not asked about: it stops a build this session
        # was already allowed to start, and a running build nobody
        # can stop is worse than one nobody approved. Reading the env
        # is not either: a session cannot propose a change to what it
        # cannot see, and the change is what is asked about.
        acct = users.account_of(me) or {}
        # The instance the handler resolved, as the auto path acts on it:
        # for a change, the project's only one when the request names
        # none; for a new one, the name Send would offer. Deriving it
        # again here made Allow write an env for, and build, an instance
        # the project did not have (the review of 24 Sep).
        want = devapp.instance_key(project, instance) if action == "new" else instance
        # A name no answer could make is refused here rather than put in
        # front of a person first.
        why = (devapp.new_refusal(project, want)
               or devapp.compose_ok(project, devapp.field(req, "compose"))) if action == "new" else ""
        if why:
            return {"error": why}, 400
        text = req.get("text") if action in ("env-set", "new") else None
        # env-set means the env, whatever was sent as it: a missing
        # text is an empty env, as the auto path writes one.
        if action == "env-set" and not isinstance(text, str):
            text = ""
        # Asked by, and answered to, the session's project; acting on
        # the container named, which may be one written here.
        r = ask_rebuild(
            devapp.field(req, "why"), sess, want, devapp.pname(project, want),
            asker_uid=str(acct.get("uid") or ""),
            asker_name=str(acct.get("name") or ""),
            asker_admin=users.is_admin(acct),
            env=text if isinstance(text, str) and (action == "env-set" or text.strip()) else None,
            create=action == "new", remove=action == "remove", target="" if project == sess else project,
            ref=devapp.field(req, "ref") if action == "new" else "",
            compose=devapp.field(req, "compose") if action == "new" else "",
            # Made on a hosting node the project names (prefs.hosts): built
            # on its own node and shipped there, once Allow is pressed.
            host=devapp.field(req, "node") if action == "new" and req.get("ship") is True else "",
            host_name=devapp.node_name(devapp.field(req, "node")) if action == "new" and req.get("ship") is True else "")
        # Which container it will be, which the session did not necessarily
        # choose, keyed and named as the auto path answers: it follows that
        # container's build once Allow starts it.
        return (r | {"instance": want, "name": devapp.pname(project, want)} if not r.get("error") else r), \
            (400 if r.get("error") else 200)
    # What the others sharing this project would want to know before they
    # press the same button, naming the instance the server resolved. Reads
    # and the env editor are not news, so they are not on this list.
    if action in ("up", "down", "rebuild", "update", "remove", "abort"):
        say(project, users.uid_of(me),
            f"{principal[len('user:'):]} ran {action} on "
            f"{project}" + (f" ({instance})" if instance != devapp.MAIN else ""))
    payload, status = act(project, instance, action, req, test_cmd=test_cmd, gate=not sess)
    # An instance made, removed or given to another project changes what
    # a project's sessions may reach on its node (R79).
    if status == 200 and action in ("new", "remove", "owner"):
        net_nudge()
    return payload, status


def file_rows(project):
    """The Artifacts tab's docker rows, one per compose file (the operator,
    10 Oct): what Send would make of each, judged before it is sent: what
    cannot work as written, what reaches beyond its own folder, a port
    already taken. Never which containers were made from it or how they are
    doing; that is the Docker tab's, and a row here that said "down" read as
    a second place to run them."""
    # Asked of the node a new container of the project would be made on, the
    # one state() asks for the project's own (_on_instance).
    with devapp.on_node(devapp._instance_node(project, devapp.MAIN)):
        return _file_rows(project)


def _file_rows(project):
    a = devapp.available()
    out = []
    for rel in devapp.compose_files(project):
        row = {"path": rel, "problems": [], "risks": [], "port_clash": [], "needs": []}
        if a["on"]:
            with devapp.composing(rel):
                cfg = devapp._config(project, devapp.MAIN)
                # A variable the file requires and nothing has set yet stops
                # compose before it reads a line, and that is the env's to
                # set after Send, not a fault (Turing Lens's deploy/vps,
                # 10 Oct): said as needed, and the rest judged with a stand-in.
                if cfg is None and "required variable" in devapp.config_error():
                    need = devapp.insisted_vars(project, devapp.MAIN)
                    if need:
                        cfg = devapp._config(project, devapp.MAIN, env_extra={v: "set-later" for v in need})
                        if cfg is not None:
                            row["needs"] = need
                if cfg is None:
                    said = devapp.config_error()
                    row["problems"] = ["compose cannot read it on its own (a file meant to be "
                                       "merged onto another, or one with a mistake in it)"
                                       + (f": {said}" if said else "")]
                else:
                    row["risks"] = devapp.risks(project, cfg)
                    row["problems"] = devapp.problems(project, cfg) + devapp.host_map()[1]
                    nogpu = devapp.gpu_gate(project, devapp.MAIN, cfg)
                    if nogpu:
                        row["problems"].append(nogpu)
                    row["port_clash"] = devapp.taken_ports(
                        project, devapp.MAIN, devapp.wiring(cfg).get("ports"))
        row["send_as"] = devapp.send_name(project, rel)
        out.append(row)
    return {"available": a["on"], "why": a["why"], "where": a.get("where", ""),
            "daemon": a.get("kind", ""), "files": out}


def row_states(name):
    """What the Artifacts tab says about sending a project to Docker: a row
    a compose file (file_rows), the name Send opens on, and how many
    containers the project already has, which its dialog says. Not how any
    of them is doing: that is the Docker tab's (the operator, 10 Oct). One
    read scope, since on an agent node each check is a probe job."""
    with devapp.read_scope():
        return {"compose_files": file_rows(name),
                # Its own for a project with none, another beside it after.
                "send_as": devapp.send_name(name),
                "containers": len(devapp._load().get(name) or {})}
