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
the compose runner to jobs.py through configure() here, as devapp used to.
"""

import contextlib
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


def configure(*, runner=None):
    """Hand the compose runner to jobs.py. Called by server.py after
    devapp.configure(), which is where `runner` also lands for Abort."""
    if runner is not None:
        runner.register("compose", run_compose_job)


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
# make over ssh, in the same order, with the compose file and env travelling
# beside them, so a node needs nothing but the token it enrolled with.
# `{cdir}` is the directory the agent writes those files into.
def _plan(project, instance, action, extra=None):
    pname = devapp._pname(project, instance)
    at = devapp.work_tree(project, instance)
    pdir = (str(at) if at is not None
            else str(devapp.WORKSPACE / project) if devapp._read_rec(project, instance).get("source") != "file"
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
    up = {"name": "starting", "argv": base + ["up", "-d"], "timeout": 1800, "env": env}
    down = {"name": "stopping", "argv": base + ["down"], "timeout": 180, "env": ienv}
    build = {"name": "building", "argv": base + ["build"], "timeout": 3600, "env": env}
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
    rebuild = [build, down] if devapp.missing_env(project, instance) else [build, down, up]
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
    return {"up": [up], "down": [down], "remove": [down],
            "rebuild": rebuild, "test": test}.get(action) or []


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
    with devapp.on_node((job or {}).get("node") or ""):
        return _compose_done(job, state)


def _compose_done(job, state):
    sp = (job or {}).get("spec") or {}
    project, instance = sp.get("project", ""), sp.get("instance") or devapp.MAIN
    action = sp.get("action")
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
    if action == "rebuild" and steps >= 1:
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
        head = {"building": "build failed", "stopping": "stopping it failed",
                "starting": "up failed", "testing": "the tests failed",
                "preparing": "a bind directory could not be made on the node"}.get(step, "")
        # The head stays whole and only the tail is cut: sliced from the end
        # as one string, a long tail took the head with it and the row
        # stopped saying what had failed.
        return (head + ":\n" + tail[-400:]) if head and tail else head
    # A gated rebuild built and stopped, and that is the whole of what it was
    # asked to do: rewrite the env with the old values in comments and leave
    # Up to the operator. The row below would clear the flag, so this returns.
    if sp.get("gate"):
        devapp._gate_env(project, instance)
        with devapp._lock:
            d = devapp._load()
            devapp._rec(d, project, instance)["await_env"] = True
            devapp.write_json(devapp.FILE, d)
        _clear_marker(project, instance)
        devapp._bump()
        return
    if action in ("up", "rebuild"):
        with devapp._lock:
            d = devapp._load()
            row = devapp._rec(d, project, instance)
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


def _record_build(project, instance):
    with devapp._lock:
        d = devapp._load()
        _stamp(devapp._rec(d, project, instance), project, instance)
        devapp.write_json(devapp.FILE, d)


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
    held = {"project": project, "instance": instance, "action": action, "hold": True}
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
                    # when the build reaches an end.
                    with devapp._lock:
                        d = devapp._load()
                        devapp._rec(d, project, instance)["building_since"] = int(time.time())
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
    remade under the same name finding its old env there is the behaviour
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
    if not got.get("on"):
        _remove_records(project, instance)
        return {"ok": True, "forgot": True,
                "note": "its daemon does not answer, so nothing was taken "
                        "down: the row is gone and whatever was running there "
                        "is still running"}
    return _submit(project, instance, "remove")


def _job_remove(project, instance, run):
    run.step("stopping")
    r = devapp._run(devapp._compose(project, instance, "down"), timeout=180,
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
    left a crashed instance with a greyed-out Down and no way out of the
    dashboard at all.
    """
    n = devapp._agent_here()
    if n:
        return bool(devapp._agent_instance_containers(n, project, instance, False))
    r = devapp._run(devapp._compose(project, instance, "ps", "-aq"), timeout=20)
    return r["code"] == 0 and bool(r["out"].strip())


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
        head = devapp._head(project, instance)
        # An instance pinned to a ref is not waiting on the working copy: its
        # build tree is its own, and an uncommitted edit in the project's tree
        # says nothing about it. What "moved" means there is that the BRANCH
        # has, which is the comparison above.
        pinned = bool(devapp._read_rec(project, instance).get("ref"))
        dirty = False if pinned else devapp._dirty(project)
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
    return _submit(project, instance, "up")


def _job_up(project, instance, run):
    run.step("starting")
    devapp.ensure_dirs(project, instance, sink=run.line)
    # `compose up -d`, and nothing more clever: compose builds an image that
    # is missing, so Up on a never-built project does what the CLI does
    # rather than refusing on a rule of this dashboard's invention. Streamed,
    # because that implicit build can pull for half an hour.
    r = devapp._run(devapp._compose(project, instance, "up", "-d"), timeout=1800,
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
        row = devapp._rec(d, project, instance)
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
                         "'...' fills it in, or the operator does in the project's "
                         "settings dialog (Build and test)"}
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


def _job_down(project, instance, run):
    run.step("stopping")
    r = devapp._run(devapp._compose(project, instance, "down"), timeout=180,
                    sink=run.line, hold=run.hold)
    if run.canceled:
        return {"state": "canceled", "error": "stopped"}
    if r["code"] != 0:
        return {"state": "failed", "error": ("down failed:\n" + r["out"])[-500:]}
    devapp._bump()
    return {"state": "succeeded"}


@devapp._on_instance
def rebuild(project, instance=devapp.MAIN, ack=""):
    """Build, then bounce, or stop at the env gate. A job: a build is
    minutes, and the poll watches it through job_rev. The name and the
    worktree are this side's and are checked in front of the answer; the
    risk gate reads the compose on the node and runs behind it (B260), so
    its refusal is the job's, on the row."""
    if devapp.compose_file(project) is None:
        return {"error": "no compose file here"}
    clash = devapp.name_clash(project, instance)
    if clash:
        return {"error": clash}
    moved = sync_work_tree(project, instance)
    if moved:
        return {"error": moved}
    return _submit(project, instance, "rebuild",
                   check=lambda: devapp._risk_gate(project, instance, ack))


def run_compose_job(job, run):
    """The compose runner jobs.py calls for a "compose" job: one action on
    one instance, with the daemon of the node the job was placed on
    addressed for everything underneath."""
    sp = job.get("spec") or {}
    project, instance = sp.get("project", ""), sp.get("instance") or devapp.MAIN
    fn = {"up": _job_up, "down": _job_down, "rebuild": _job_rebuild,
          "remove": _job_remove}.get(sp.get("action"))
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
        with devapp._lock:
            d = devapp._load()
            _stamp(devapp._rec(d, project, instance), project, instance)
            devapp.write_json(devapp.FILE, d)
        run.step("stopping")
        devapp._run(devapp._compose(project, instance, "down"), timeout=180,
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
        r = devapp._run(devapp._compose(project, instance, "up", "-d"), timeout=600,
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


def act(project, instance, action, req, *, test_cmd=""):
    """One dev-instance verb, as the dashboard and `bb devapp` name them,
    once server.py has decided who may ask (docker-write, the per-project
    dial, a session's own node) and which instance is meant.

    The answer is (payload, status): a module's {ok} or {error} with 400 on
    the error, the way Handler._result reads one, and the instance's fresh
    state riding on every change so nothing on screen is stale. Here rather
    than in the handler because what a verb means is this module's to say
    (the one-file rule); the handler holds the gate and nothing else.
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
        return {"text": devapp.starter(project)}, 200
    if action == "new":
        # The one action whose instance does not exist yet, which is what it
        # is for. Everything below names one that must exist, because the
        # string decides a compose project and a data directory and is not
        # somewhere an arbitrary one should reach.
        # The project it belongs to when the request says, "" being none.
        r = devapp.create_instance(project, instance, f(req, "node"),
                                   f(req, "owner") if "owner" in req else None)
        if not r.get("error") and f(req, "ref"):
            # Pinned before the build the dialog starts, or the first one
            # comes from the project's checkout and the row says otherwise.
            p = devapp.set_ref(project, r["instance"], f(req, "ref"))
            if p.get("error"):
                # The record goes with the refused request, or the retry
                # that fixes the ref is told the instance already exists
                # (B259). Nothing was built, so there is nothing else to undo.
                _remove_records(project, r["instance"])
                return p, 400
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
        if not r.get("error"):
            # Said now rather than at the first rebuild: a compose that asks
            # for more than its own directory cannot be built until a person
            # has acknowledged it, and "rebuild builds it" was untrue (24 Sep).
            # After the env, which a path in the compose can come from.
            with contextlib.suppress(Exception):
                why = devapp.unacked_risks(project, r["instance"])
                if why:
                    r["needs_ack"] = why
        return r, (400 if r.get("error") else 200)
    if instance not in devapp.instances(project):
        return {"error": f"no instance {instance} of {project}"}, 400
    if action == "remove":
        r = remove_instance(project, instance)
        return r, (400 if r.get("error") else 200)
    if action == "ref":
        # Which branch this instance builds from. `docker-write` has already
        # had its say in the handler, so this is an administrator's like
        # every other thing that changes what a container IS.
        r = devapp.set_ref(project, instance, f(req, "ref"))
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
    if action == "up":
        r = up(project, instance, f(req, "ack"))
    elif action == "down":
        r = down(project, instance)
    elif action == "test":
        r = test(project, instance, test_cmd,
                 [str(a) for a in (req.get("args") or [])][:32])
    elif action == "rebuild":
        r = rebuild(project, instance, f(req, "ack"))
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
    elif action == "route":
        # How the instance is reached (docs/nodes.md §7): lan or funnel,
        # on which published port.
        r = route_set(project, instance, f(req, "mode"), req.get("port"))
    else:
        return {"error": f"unknown action: {action}"}, 400
    if r.get("error"):
        return r, 400
    return r | {"state": state(project, instance)}, 200
