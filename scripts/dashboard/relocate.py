"""Copying or moving a dev instance to another node, its data with it (the
operator, 10 Oct): the Docker tab's Copy or move. A fresh container is Send
to Docker's; this one carries what the old one had.

Three jobs, one after another, each started when the one before succeeds
(done(), called from devactions.compose_done):

  out    on the old node: the instance stopped, its named volumes and its
         data directory packed into one file and sent to the controller;
         a copy starts the original again, a move leaves it stopped.
  in     on the new node: that file fetched, the volumes made again under
         the new instance's name and filled, the data directory filled.
  build  the new instance's ordinary rebuild there, which is a shipped one
         (R166) when the new node is not one of its project's nodes.

A move then takes the old node's containers down (`down`, volumes kept: the
old node still holds a copy of the data until somebody removes it). A move
that fails on the way puts the instance back where it was and starts it
there again; a copy that fails leaves the original as it was.

The data travels through the controller's images store, the way a shipped
image does, and lives there from the first job's upload to the second job's
end. Both nodes must be agent nodes: a plan is what carries the steps.
"""
import re
import posixpath
import time
import os
import threading

import devapp

# The small image that reads and writes a volume: a volume has no path the
# job's account can reach, so a container mounts it.
HELPER = "busybox:1.36"

# Run on the old node by python3 (the agent's interpreter): every volume of
# the compose project, and the data directory, packed into one tar beside a
# manifest naming them.
PACK_PY = r"""
import json, os, subprocess, sys, tarfile
pname, out, data, helper = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
work = os.path.dirname(out)
names = subprocess.run(["docker", "volume", "ls", "-q", "--filter",
                        "label=com.docker.compose.project=" + pname],
                       check=True, capture_output=True, text=True).stdout.split()
vols, parts = [], []
for i, v in enumerate(sorted(names)):
    part = f"vol-{i}.tgz"
    print(f"packing the volume {v}", flush=True)
    subprocess.run(["docker", "run", "--rm", "-v", f"{v}:/v:ro", "-v", f"{work}:/o", helper,
                    "tar", "czf", "/o/" + part, "-C", "/v", "."], check=True)
    vols.append({"name": v, "part": part})
    parts.append(part)
has_data = bool(data) and os.path.isdir(data)
if has_data:
    print(f"packing the data directory {data}", flush=True)
    subprocess.run(["docker", "run", "--rm", "-v", f"{data}:/v:ro", "-v", f"{work}:/o", helper,
                    "tar", "czf", "/o/data.tgz", "-C", "/v", "."], check=True)
    parts.append("data.tgz")
with open(os.path.join(work, "manifest.json"), "w") as f:
    json.dump({"project": pname, "volumes": vols, "data": has_data}, f)
with tarfile.open(out, "w") as t:
    for p in ["manifest.json", *parts]:
        t.add(os.path.join(work, p), arcname=p)
for p in ["manifest.json", *parts]:
    os.remove(os.path.join(work, p))
print(f"packed {len(vols)} volume(s)" + (" and the data directory" if has_data else ""), flush=True)
"""

# Run on the new node: the volumes made again under the new instance's name
# (labeled as compose labels its own, so compose takes them as its), filled,
# and the data directory filled. A volume already there with anything in
# it is refused rather than written over; an empty one (what a try that
# failed left behind) is filled. Neither script may spell the plan's {cdir}
# placeholder in its text: the agent rewrites that wherever it stands in
# argv, the python included, and the helper's mount pointed at the compose
# directory while the tar had gone into in/ (B659).
UNPACK_PY = r"""
import json, os, subprocess, sys, tarfile
pname, old, src, data, helper = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
work = os.path.join(os.path.dirname(src), "in")
os.makedirs(work, exist_ok=True)
with tarfile.open(src) as t:
    t.extractall(work, filter="data")
m = json.load(open(os.path.join(work, "manifest.json")))
have = set(subprocess.run(["docker", "volume", "ls", "-q"], check=True,
                          capture_output=True, text=True).stdout.split())
for v in m.get("volumes") or []:
    name = v["name"]
    key = name[len(old) + 1:] if name.startswith(old + "_") else name
    new = f"{pname}_{key}" if name.startswith(old + "_") else name
    if new in have:
        held = subprocess.run(["docker", "run", "--rm", "-v", f"{new}:/v:ro", helper, "sh", "-c", "ls -A /v | head -1"],
                              check=True, capture_output=True, text=True).stdout.strip()
        if held:
            sys.exit(f"a volume called {new} is already on this node with files in it: remove it first, or pick another name")
        print(f"filling the empty volume {new} left by an earlier try", flush=True)
    else:
        print(f"making the volume {new}", flush=True)
        subprocess.run(["docker", "volume", "create", "--label", "com.docker.compose.project=" + pname,
                        "--label", "com.docker.compose.volume=" + key, new], check=True, capture_output=True)
    subprocess.run(["docker", "run", "--rm", "-v", f"{new}:/v", "-v", f"{work}:/i:ro", helper,
                    "tar", "xzf", "/i/" + v["part"], "-C", "/v"], check=True)
if m.get("data"):
    if not data:
        sys.exit("the old node had a data directory and this one has no place for it")
    print(f"filling the data directory {data}", flush=True)
    subprocess.run(["docker", "run", "--rm", "-v", f"{data}:/v", "-v", f"{work}:/i:ro", helper,
                    "tar", "xzf", "/i/data.tgz", "-C", "/v"], check=True)
subprocess.run(["rm", "-rf", work, src])
print("unpacked", flush=True)
"""

def _a():
    """devactions, whose plans and rebuild this stands on. Imported when
    used: it imports this module for compose_done."""
    import devactions
    return devactions


def _data_file(project, instance):
    import paths
    d = paths.of("images")
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{devapp._pname(project, instance)}.data.tar"


def _node_row(nid):
    return devapp.queue.node(nid) if (devapp.queue is not None and nid) else None


def _drop(project, instance):
    """A copy that never came to be: its record and its env, and nothing of
    the original's. Not devactions._remove_records, which for a container
    written here forgets the whole container, the original with it."""
    with devapp._lock:
        d = devapp._load()
        if instance in (d.get(project) or {}):
            del d[project][instance]
            devapp.write_json(devapp.FILE, d)
    devapp.env_path(project, instance).unlink(missing_ok=True)
    devapp._bump()


def _set(project, instance, **fields):
    """Fields of an instance's record, None removing one."""
    with devapp._lock:
        d = devapp._load()
        rec = devapp._rec(d, project, instance)
        for k, v in fields.items():
            if v is None:
                rec.pop(k, None)
            else:
                rec[k] = v
        devapp.write_json(devapp.FILE, d)
    devapp._bump()

# Run on the node when a written container is renamed while down (the
# operator, 11 Oct: the name is editable in the Edit dialog once the
# container is down): each volume of the old compose project made again
# under the new name with compose's labels and filled through the helper,
# the old one removed, and the data directory moved. Nothing in it spells
# the plan's {cdir} placeholder (B659).
RENAME_PY = r"""
import os, subprocess, sys
old, new, data_old, data_new, helper = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
# The data directory first, and as root inside the helper: the appdata root
# is root's, so the jobs account can neither make nor rename a directory in
# it (aquilaeLabs, 11 Oct: the volume had moved and the directory could
# not, leaving the record on the old name). A rename in place, so it is
# instant and is put back if a volume below fails.
moved = False
def dmove(a, b):
    root = os.path.dirname(a)
    subprocess.run(["docker", "run", "--rm", "-v", root + ":/r", helper, "sh", "-c",
                    'if [ -e "/r/$2" ]; then rmdir "/r/$2" || exit 3; fi; mv "/r/$1" "/r/$2"',
                    "sh", os.path.basename(a), os.path.basename(b)], check=True)
if data_old and data_new and data_old != data_new and os.path.isdir(data_old):
    if os.path.dirname(data_old) != os.path.dirname(data_new):
        sys.exit("the data directory would leave its root: " + data_old + " to " + data_new)
    print("moving the data directory to " + data_new, flush=True)
    try:
        dmove(data_old, data_new)
    except subprocess.CalledProcessError:
        sys.exit(data_new + " is already there with files in it: move it away first, or pick another name")
    moved = True
try:
    names = subprocess.run(["docker", "volume", "ls", "-q", "--filter", "label=com.docker.compose.project=" + old],
                           check=True, capture_output=True, text=True).stdout.split()
    have = set(subprocess.run(["docker", "volume", "ls", "-q"], check=True, capture_output=True, text=True).stdout.split())
    for v in sorted(names):
        key = v[len(old) + 1:] if v.startswith(old + "_") else v
        target = f"{new}_{key}" if v.startswith(old + "_") else v
        if target == v:
            continue
        if target in have:
            raise SystemExit(f"a volume called {target} is already on this node: remove it first, or pick another name")
        print(f"carrying the volume {v} to {target}", flush=True)
        subprocess.run(["docker", "volume", "create", "--label", "com.docker.compose.project=" + new,
                        "--label", "com.docker.compose.volume=" + key, target], check=True, capture_output=True)
        subprocess.run(["docker", "run", "--rm", "-v", f"{v}:/v:ro", "-v", f"{target}:/w", helper,
                        "sh", "-c", "cp -a /v/. /w/"], check=True)
        subprocess.run(["docker", "volume", "rm", v], check=True, capture_output=True)
except BaseException:
    if moved:
        print("putting the data directory back at " + data_old, flush=True)
        dmove(data_new, data_old)
    raise
print("renamed", flush=True)
"""


def rename_job(name, new, instance=None):
    """A container renamed while down: its volumes carried to the new
    prefix and its data directory moved on its node, by one job; the
    records follow in rename_done. `name` is a written container's, or with
    `instance` the project a project's container is made from.
    {"ok", "job"} or {"error"}."""
    if devapp.queue is None:
        return {"error": "no job queue is configured here"}
    inst = devapp.MAIN if instance is None else instance
    old = devapp._pname(name, inst)
    nid = devapp._instance_node(name, inst)
    n = _node_row(nid)
    if not n or n.get("kind") != "agent" or n.get("state") != "online":
        return {"error": "the node it is on is not an agent node that is online, and only one of those can carry its data"}
    with devapp.on_node(nid):
        data_old = devapp.dev_data_dir(name, inst, make=False) or ""
        data_new = (posixpath.join(devapp.appdata_root(), new) if data_old else "")
    step = {"name": "renaming", "argv": ["python3", "-c", RENAME_PY, old, new, data_old, data_new, HELPER],
            "timeout": 3600}
    spec = {"project": name, "instance": inst, "action": "rename", "name": old, "files": {},
            "dirs": [], "gate": False, "rename": {"to": new, "own": instance is not None}, "plan": [step]}
    _set(name, inst, renaming=new)
    r = devapp.queue.job_add("operator", {"node": nid}, "compose", spec, name)
    if r.get("error"):
        _set(name, inst, renaming=None)
        return r
    devapp._bump()
    return {"ok": True, "started": True, "job": r["job"], "name": new}


def rename_done(job, state):
    """compose_done's turn for a rename's job: the records, the compose
    directory and the env follow the data under the new name; a failure
    leaves everything as it was and says what the job last wrote."""
    sp = (job or {}).get("spec") or {}
    old = sp.get("project") or ""
    inst = sp.get("instance") or devapp.MAIN
    rn = sp.get("rename") or {}
    new = str(rn.get("to") or "")
    if not old or not new:
        return ""
    if state != "succeeded":
        _set(old, inst, renaming=None)
        said = _last_said(job)
        return "renaming it failed" + (f": {said}" if said else "")
    if rn.get("own"):
        _name_instance(old, inst, new)
    else:
        _rename_records(old, new)
    return ""


def _name_instance(project, instance, new):
    """A project's container given its own name: the record carries it
    (devapp._pname reads it), and its env file follows; the instance keeps
    its key, so its worktree, its jobs and bb devapp --instance are where
    they were. A name that is the project's own default again is no name."""
    src = devapp.env_path(project, instance)
    with devapp._lock:
        d = devapp._load()
        rec = (d.get(project) or {}).get(instance)
        if rec is None:
            return
        rec.pop("renaming", None)
        default = devapp._slug(project) if instance == devapp.MAIN else devapp._slug(instance)
        if new == default:
            rec.pop("name", None)
        else:
            rec["name"] = new
        devapp.write_json(devapp.FILE, d)
    dst = devapp.env_path(project, instance)
    try:
        if src != dst and src.exists() and not dst.exists():
            src.rename(dst)
    except OSError as e:
        print(f"[relocate] renaming {src} to {dst}: {e}", flush=True)
    devapp._bump()


def _rename_records(old, new):
    """The written container's record under its new key, its compose file's
    directory and its env file renamed with it; the data and the volumes
    were carried by the node."""
    with devapp._lock:
        d = devapp._load()
        if old in d and new not in d:
            d[new] = d.pop(old)
            (d[new].get(devapp.MAIN) or {}).pop("renaming", None)
            devapp.write_json(devapp.FILE, d)
    for src, dst in ((devapp.containers_dir(old), devapp.containers_dir(new)),
                     (devapp.env_path(old, devapp.MAIN), devapp.env_path(new, devapp.MAIN))):
        try:
            if src.exists() and not dst.exists():
                src.rename(dst)
        except OSError as e:
            print(f"[relocate] renaming {src} to {dst}: {e}", flush=True)
    devapp._bump()


def builds_image(project, instance):
    """Whether a written container's compose file builds an image (a `build:`
    under a service), read off the file itself: compose resolves a build
    context against the project directory, so the answer needs no node."""
    f = devapp.compose_file(project, instance)
    try:
        text = f.read_text() if f else ""
    except OSError:
        return False
    return bool(re.search(r"^\s+build:", text, re.M))


def start(project, instance, mode, node, name="", env=None):
    """Copy (mode "copy", into a new instance called `name`) or move (mode
    "move", the same instance) an instance to `node`, its data with it, its
    env written from `env` when one is given. The first job is queued and
    the request answers with it; the rest follow on their own."""
    if devapp.queue is None:
        return {"error": "no job queue is configured here"}
    if mode not in ("copy", "move"):
        return {"error": "copy or move"}
    if instance not in (devapp._load().get(project) or {}):
        return {"error": f"{project} has no container {instance}"}
    old_node = devapp._instance_node(project, instance)
    target = str(node or "")
    for nid, what in ((old_node, "the node it is on"), (target, "the node it goes to")):
        n = _node_row(nid)
        if not n or n.get("kind") != "agent" or n.get("state") == "retired":
            return {"error": f"{what} is not an agent node, and only an agent node can carry its data"}
    if target == old_node:
        return {"error": f"it is already on {devapp.node_name(target)}"}
    if (_node_row(target) or {}).get("state") != "online":
        return {"error": f"{devapp.node_name(target)} is not online"}
    if _a()._active_job(project, instance):
        return {"error": "a job is running on it: wait for it, or Stop it, then copy or move it"}
    rec = dict(devapp._read_rec(project, instance))
    if rec.get("relocating"):
        return {"error": "it is already being copied or moved"}
    owner = rec.get("for") or project
    # A container written on the Docker tab ships too when its compose file
    # builds an image: the build needs the context the file names, which is
    # on the node it was written for and never on a hosting node. Built on
    # arrival instead, BuildKit refused the context on a node with no code
    # and the move went back with both down (turinglens, B716). One that
    # only pulls images still rebuilds wherever it lands.
    ship = target not in (devapp.nodes_of(owner) or []) and (rec.get("source") != "file" or builds_image(project, instance))
    if mode == "copy":
        dest = devapp.instance_key(project, name or "")
        if not dest:
            return {"error": "the copy needs a name of its own"}
        why = devapp.new_refusal(project, dest)
        if why:
            return {"error": why}
        keep = {k: v for k, v in rec.items()
                if k in ("for", "ref", "compose", "source", "risks_ack", "route")}
        with devapp._lock:
            d = devapp._load()
            why = devapp._taken(project, dest, d)
            if why:
                return {"error": why}
            new = devapp._rec(d, project, dest)
            new.update(keep)
            new["node"] = target
            if ship:
                new["ship"] = True
            devapp.write_json(devapp.FILE, d)
        devapp._bump()
        text = env if isinstance(env, str) else devapp.read_env(project, instance)
        if text:
            w = devapp.write_env(project, text, dest)
            if w.get("error"):
                _drop(project, dest)
                return w
    else:
        dest = instance
        if isinstance(env, str):
            _set(project, instance, relocate_env=devapp.read_env(project, instance))
            w = devapp.write_env(project, env, instance)
            if w.get("error"):
                return w
    plan = {"mode": mode, "from": instance, "to": dest, "old": old_node, "new": target,
            "ship": ship, "was_ship": bool(rec.get("ship")), "was_node": rec.get("node") or "",
            "old_pname": devapp._pname(project, instance)}
    _set(project, dest, relocating=plan | {"stage": "out"})
    held = {"project": project, "instance": instance, "action": "relocate-out", "hold": True,
            "relocate": plan | {"stage": "out"}}
    r = devapp.queue.job_add("operator", {"node": old_node}, "compose", held, project)
    if r.get("error"):
        _undo(project, plan, "")
        return r

    def prepare():
        try:
            with devapp.on_node(old_node):
                spec = _a()._plan_spec(project, instance, "stop")
                stop = _a()._plan(project, instance, "stop")
                start_ = _a()._plan(project, instance, "start") if mode == "copy" else []
                data = devapp.dev_data_dir(project, instance, make=False) or ""
            pack = {"name": "packing", "argv": ["python3", "-c", PACK_PY, plan["old_pname"],
                                                "{cdir}/data.tar", data, HELPER], "timeout": 7200}
            send = {"name": "sending", "upload": "{cdir}/data.tar", "to": f"devdata-put?job={r['job']}",
                    "timeout": 7200}
            devapp.queue.job_release(r["job"], spec | {
                "action": "relocate-out", "dirs": [], "gate": False,
                "relocate": plan | {"stage": "out"}, "plan": [*stop, pack, send, *start_]})
        except Exception as e:                                       # noqa: BLE001
            print(f"[relocate] preparing {project}/{instance}: {type(e).__name__}: {e}", flush=True)
            devapp.queue.job_refuse(r["job"], f"could not prepare it: {e}")
        finally:
            devapp._bump()

    threading.Thread(target=prepare, name=f"relocate-{r['job']}", daemon=True).start()
    return {"ok": True, "started": True, "job": r["job"], "instance": dest,
            "name": devapp._pname(project, dest), "ship": ship}


def _in_job(project, plan, out_job):
    """The new node's half: fetch, unpack."""
    dest = plan["to"]
    held = {"project": project, "instance": dest, "action": "relocate-in", "hold": True,
            "relocate": plan | {"stage": "in", "out_job": out_job}}
    r = devapp.queue.job_add("operator", {"node": plan["new"]}, "compose", held, project)
    if r.get("error"):
        return r
    with devapp.on_node(plan["new"]):
        data = devapp.dev_data_dir(project, dest, make=False) or ""
    fetch = {"name": "fetching", "fetch": f"devdata?job={r['job']}", "dest": "{cdir}/data.tar",
             "timeout": 7200}
    unpack = {"name": "unpacking", "argv": ["python3", "-c", UNPACK_PY, devapp._pname(project, dest),
                                            plan["old_pname"], "{cdir}/data.tar", data, HELPER],
              "timeout": 7200}
    devapp.queue.job_release(r["job"], {
        "project": project, "instance": dest, "action": "relocate-in",
        "name": devapp._pname(project, dest), "files": {}, "dirs": [data] if data else [],
        "gate": False, "relocate": plan | {"stage": "in", "out_job": out_job},
        "plan": [fetch, unpack]})
    _set(project, dest, relocating=plan | {"stage": "in"})
    return r


def _queue_on(project, instance, nid, action):
    """A plain compose action on one node, whichever node the record names:
    the old node's start after a failed move, its down after a done one."""
    held = {"project": project, "instance": instance, "action": action, "hold": True,
            "relocate": {"stage": "after"}}
    r = devapp.queue.job_add("operator", {"node": nid}, "compose", held, project)
    if r.get("error"):
        return
    with devapp.on_node(nid):
        spec = _a()._plan_spec(project, instance, action)
    devapp.queue.job_release(r["job"], spec | {"relocate": {"stage": "after"}, "gate": False})


def _undo(project, plan, why):
    """A move that failed goes back where it was, started there; a copy that
    failed before it was built is taken away, the original untouched."""
    dest = plan["to"]
    _data_file(project, dest).unlink(missing_ok=True)
    if plan["mode"] == "copy":
        if plan.get("stage") in ("out", "in"):
            _drop(project, dest)
        else:
            _set(project, dest, relocating=None, relocate_why=why or None,
                 relocate_at=int(time.time()) if why else None)
        return
    old_env = devapp._read_rec(project, dest).get("relocate_env")
    if isinstance(old_env, str):
        devapp.write_env(project, old_env, dest)
    # As it was: its own node, or none when it followed its project's.
    _set(project, dest, relocating=None, relocate_env=None, node=plan.get("was_node") or None,
         ship=True if plan.get("was_ship") else None, relocate_why=why or None,
         relocate_at=int(time.time()) if why else None)
    _queue_on(project, dest, plan["old"], "start")


def _last_said(job):
    """The last line a failed job wrote, for the row to carry: 'the Jobs
    tab has why' sent a person to a tab that then showed them nothing
    (B658), and the why is usually the log's last line (a tar's refusal, a
    volume already there)."""
    try:
        text = (devapp.queue.job((job or {}).get("id"), with_log=True) or {}).get("log") or ""
    except Exception:            # noqa: BLE001 (a missing log is no reason to lose the row's sentence)
        text = ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith(("$ ", "    ", "Traceback"))]
    return lines[-1][:200] if lines else ""


def done(job, state):
    """compose_done's turn for a relocation's job: the next one, or the way
    back. Returns the row's sentence for a failure, "" otherwise."""
    sp = (job or {}).get("spec") or {}
    rel = sp.get("relocate") or {}
    project = sp.get("project", "")
    stage = rel.get("stage")
    if stage == "after":
        return ""
    plan = {k: v for k, v in rel.items() if k not in ("stage", "out_job")}
    if stage == "out":
        if state != "succeeded" or not _data_file(project, plan["to"]).is_file():
            said = _last_said(job)
            _undo(project, plan | {"stage": "out"}, "the data could not be packed on the old node")
            return "packing its data on the old node failed" + (f": {said}" if said else "")
        r = _in_job(project, plan, job.get("id"))
        if r.get("error"):
            _undo(project, plan | {"stage": "out"}, r["error"])
            return r["error"]
        return ""
    if stage == "in":
        _data_file(project, plan["to"]).unlink(missing_ok=True)
        if state != "succeeded":
            said = _last_said(job)
            _undo(project, plan | {"stage": "in"}, "the data could not be unpacked on the new node")
            return "unpacking its data on the new node failed" + (f": {said}" if said else "")
        if plan["mode"] == "move":
            _set(project, plan["to"], node=plan["new"], ship=True if plan["ship"] else None)
        _set(project, plan["to"], relocating=plan | {"stage": "build"})
        ack = devapp._read_rec(project, plan["to"]).get("risks_ack") or ""
        payload, status = _a().act(project, plan["to"], "rebuild", {"ack": ack}, gate=True)
        if status != 200:
            _undo(project, plan | {"stage": "build"}, payload.get("error") or "")
            return payload.get("error") or "the rebuild could not start"
        return ""
    return ""


def built(project, instance, ok):
    """The new instance's rebuild reached an end: a move takes the old
    node's containers down, a failed one goes back; either way the record
    stops saying it is moving."""
    plan = devapp._read_rec(project, instance).get("relocating")
    if not isinstance(plan, dict) or plan.get("stage") != "build":
        return
    plan = {k: v for k, v in plan.items() if k != "stage"}
    if not ok:
        if plan["mode"] == "move":
            _queue_on(project, instance, plan["new"], "down")
        _undo(project, plan | {"stage": "build"}, "it would not build on the new node")
        return
    _set(project, instance, relocating=None, relocate_env=None, relocate_why=None, relocate_at=None)
    if plan["mode"] == "move":
        _queue_on(project, instance, plan["old"], "down")


def data_put(nid, q, stream, length):
    """The old node's packed data (agent verb devdata-put): only for a job
    of that node's that is sending it, whole or not at all."""
    j = devapp.queue.job(q.get("job", [""])[0], with_log=False) if devapp.queue else None
    sp = (j or {}).get("spec") or {}
    rel = sp.get("relocate") or {}
    if not j or j.get("node") != nid or j.get("state") not in ("assigned", "running") or rel.get("stage") != "out":
        return {"error": "no data is being sent by that job from this node"}, 403
    if length <= 0 or length > 256 * 1024 ** 3:
        return {"error": "the data is between 1 byte and 256 GB"}, 413
    dest = _data_file(sp.get("project", ""), rel.get("to") or "")
    # In pieces (R170): a node behind Cloudflare may send at most 100 MB a
    # request, so the agent sends `offset` and `total`, each piece appended
    # to one part file, and the file is whole when the last piece lands.
    # One body is offset 0 of its own length, the way it always was.
    try:
        offset = int(q.get("offset", ["0"])[0] or 0)
        total = int(q.get("total", [str(length)])[0] or length)
    except ValueError:
        return {"error": "offset and total are numbers"}, 400
    if offset < 0 or total < length or offset + length > total or total > 256 * 1024 ** 3:
        return {"error": "that piece is not within the data"}, 400
    tmp = dest.with_name(f".{dest.name}.part")
    have = tmp.stat().st_size if tmp.is_file() else 0
    if offset != have:
        # Not the next piece: a retry of one that landed is answered as
        # landed, anything else is said, so the file never has a hole.
        if offset + length <= have:
            return {"ok": True, "bytes": have, "again": True}, 200
        tmp.unlink(missing_ok=True) if offset == 0 else None
        if offset != 0:
            return {"error": f"the data has {have} bytes here and this piece starts at {offset}"}, 409
    got = 0
    with open(tmp, "ab" if offset else "wb") as f:
        while got < length:
            chunk = stream.read(min(1 << 20, length - got))
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
    if got != length:
        if not offset:
            tmp.unlink(missing_ok=True)
        else:
            with open(tmp, "ab") as f:
                f.truncate(offset)
        return {"error": "the data ended early"}, 400
    if offset + got < total:
        return {"ok": True, "bytes": offset + got, "more": True}, 200
    os.replace(tmp, dest)
    return {"ok": True, "bytes": total}, 200


def data_path(nid, q):
    """That data, for the new node's unpacking job (agent verb devdata)."""
    j = devapp.queue.job(q.get("job", [""])[0], with_log=False) if devapp.queue else None
    sp = (j or {}).get("spec") or {}
    rel = sp.get("relocate") or {}
    if not j or j.get("node") != nid or j.get("state") not in ("assigned", "running") or rel.get("stage") != "in":
        return None, ({"error": "no data is being fetched by that job on this node"}, 403)
    p = _data_file(sp.get("project", ""), sp.get("instance") or "")
    if not p.is_file():
        return None, ({"error": "the data is not here: copy or move it again"}, 404)
    return p, None


def view(project, instance):
    """What the row says while one is under way, or why the last one failed."""
    rec = devapp._read_rec(project, instance)
    plan = rec.get("relocating")
    if isinstance(plan, dict):
        verb = "copying" if plan.get("mode") == "copy" else "moving"
        where = devapp.node_name(plan.get("new") or "")
        step = {"out": "packing its data", "in": "unpacking its data",
                "build": "building"}.get(plan.get("stage"), "")
        return {"busy": True, "line": f"{verb} to {where}: {step}" if step else f"{verb} to {where}"}
    if rec.get("renaming"):
        return {"busy": True, "line": f"renaming it to {rec['renaming']}: the node carries its volumes and data"}
    # Why the last one did not happen is the bell's (attention below), where
    # it can be put away, and not the row's for ever (the operator, 11 Oct:
    # a failure from hours before still sat on a row renamed since).
    return None


def started(project, instance):
    """The instance built or started since: a failed copy or move from
    before is history, and the bell stops carrying it."""
    if devapp._read_rec(project, instance).get("relocate_why"):
        _set(project, instance, relocate_why=None, relocate_at=None)


def attention(node_name):
    """The bell's rows: each instance whose last copy or move did not
    happen, kind relocate, keyed by bellseen on when it failed."""
    out = []
    for project, insts in devapp._load().items():
        for inst, rec in insts.items():
            if not rec.get("relocate_why") or rec.get("relocating"):
                continue
            nid = devapp._instance_node(project, inst)
            out.append({"kind": "relocate", "id": f"{project}|{inst}", "name": devapp._pname(project, inst),
                        "project": project, "node": node_name(nid) if nid else "", "node_id": nid or "",
                        "why": str(rec["relocate_why"]), "at": int(rec.get("relocate_at") or 0)})
    return out

