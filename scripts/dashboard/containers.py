"""Containers BuilderBot did not build from a project's compose file.

Three things a machine whose job is running containers has on it that are
not a project's dev instance: whatever is on the daemon already (the
operator asked for a manager, not a list of what BuilderBot happens to have
made), the containers written from a compose file on the Docker tab with no
project behind them (a stack is a name, a compose file and an environment,
the shape every other Docker front end uses), and the record of which
project a container BuilderBot did not start belongs to, kept by name on
its node. Their controls address a CONTAINER by name rather than a project,
which is why they sit apart from the instance's build and run: one verb and
one name, looked up again on the daemon before anything is acted on.

Its own file since 25 Sep. devapp.py held all of it and was 4,400 lines, and
the house rule is one module per feature beside server.py: what is shared,
the store, the node block, the docker runner and the env files, it reads
from devapp, which does not know this file exists. server.py holds only the
routes.
"""

import contextlib
import os
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import devapp  # noqa: E402


def _known_container(name):
    """The container the daemon just reported under this name, or None.

    The rule every executing surface here follows: what reaches a command
    line is a string this server handed out. A name typed by somebody, or
    remembered by a page from a listing five minutes old, is not that, so it
    is looked up again before it is used (R68 step 1).
    """
    for c in (devapp.containers().get("containers") or []):
        if name and (c.get("name") == name or c.get("id") == name):
            return c
    return None


def container_ctl(name, what):
    """Start, stop or restart one container on the picked node.

    Any container, not only ours. The operator asked for a manager rather
    than a list of what BuilderBot happens to have made, and a machine whose
    only job is running containers is the place that is safe: the daemon is
    the sandbox VM's, and the guard above is why the reach is one verb and
    one name rather than the docker CLI.
    """
    if what not in devapp._CTL_OK:
        return {"error": f"a container is started, stopped or restarted, not {what!r}"}
    c = _known_container(name)
    if not c:
        return {"error": f"no container called {name} on this daemon now: the list is "
                         "read again before anything is acted on, and it has moved"}
    r = devapp._run([devapp.DOCKER, what, c.get("name") or c.get("id")], timeout=60)
    if r["code"] != 0:
        return {"error": devapp._why_not(r["out"]) or f"{what} failed"}
    return {"ok": True, "out": f"{what}ped {c.get('name')}" if what == "stop"
                               else f"{what}ed {c.get('name')}"}


def owned_container(name):
    """The container the daemon reports under `name` now, with the project
    it belongs to: (None, "") when there is none. On the node the current
    block addresses."""
    c = _known_container(name)
    return (c, listed_owner(c)) if c else (None, "")


def ctl_on(node, name, what):
    """container_ctl on a named node, for a caller that opened no block of
    its own: Allow on a session's ask to start, stop or restart one."""
    with devapp.on_node(node or None):
        return container_ctl(name, what)


def container_logs(name, lines=None):
    """The tail of one container's log, timestamped.

    What a person opens a docker list to read. Timestamps because the
    question is almost always "when did it do that", and a tail because a
    page is not a download: LOG_LINES is what a restart loop needs to be
    legible.
    """
    c = _known_container(name)
    if not c:
        return {"error": f"no container called {name} on this daemon now"}
    n = str(int(lines or devapp.LOG_LINES))
    r = devapp._run([devapp.DOCKER, "logs", "--tail", n, "--timestamps",
                     c.get("name") or c.get("id")], timeout=30)
    # A container that has said nothing is not an error, and neither is one
    # whose log the daemon answered on stderr: docker writes a container's
    # own stderr there, which for most images is most of the log.
    if r["code"] != 0 and not (r["out"] or "").strip():
        return {"error": devapp._why_not(r["out"]) or "could not read the log"}
    return {"ok": True, "name": c.get("name") or c.get("id"),
            "text": (r["out"] or "")[-60000:]}


COMPOSE_MAX = 200_000            # a compose file is a page, not a payload


def create_container(name, compose_text, env_text="", node="", for_project=""):
    """A container from a compose file written here, with no project behind it.

    The shape every other Docker front end uses: a stack is a name, a compose
    file and an environment. Labels are not a third field: in compose they
    live in the YAML, and a separate box for them would be inventing a concept
    this format does not have.

    Validated before it is registered, by asking compose itself to parse it:
    a file that does not resolve is a container that cannot start, and finding
    that out at Build time means the failure arrives one screen away from the
    text that caused it.
    """
    slug = devapp._slug(name)
    if not slug:
        return {"error": "a container needs a name with a letter or digit in it"}
    if not (compose_text or "").strip():
        return {"error": "a compose file is needed"}
    if len(compose_text) > COMPOSE_MAX:
        return {"error": f"that compose file is over {COMPOSE_MAX // 1000}kB"}
    # On its project's node and nowhere else (devapp.on_project_node); one
    # for no project lives on the node it was made on, which the dialog
    # names and a request that did not gets from the block it runs in.
    if for_project:
        why, node = devapp.on_project_node(for_project, node)
        if why:
            return {"error": why}
    node = node or devapp._node_here()
    with devapp._lock:
        if slug in devapp._load():
            return {"error": f"{slug} already exists; pick another name"}
        clash = devapp.name_clash(slug, devapp.MAIN)
        if clash:
            return {"error": clash}
    d = devapp.containers_dir(slug)
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / "docker-compose.yml").write_text(compose_text, encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write it: {e}"}
    # Registered before the check, because the check goes through _compose()
    # and that reads the record to know where the file is. Removed again if
    # the file turns out not to parse, so a refusal leaves nothing behind.
    with devapp._lock:
        d2 = devapp._load()
        rec = devapp._rec(d2, slug, devapp.MAIN)
        rec["source"] = "file"
        # Not listed while compose reads it: a manager listing that landed
        # in this window drew a row for a container that was then refused
        # (B239). A time, so a record left by a restart mid-check is listed
        # again after PENDING_S rather than hidden with its name taken.
        rec["pending"] = int(time.time())
        if node:
            rec["node"] = str(node)
        # The project it belongs to (owner_of): a dev radarr for a media
        # project is that project's, listed in its notebook and reachable
        # by its sessions. None when not given, which is the default here.
        if for_project:
            rec["for"] = str(for_project)[:100]
        devapp.write_json(devapp.FILE, d2)
    if (env_text or "").strip():
        devapp.write_env(slug, env_text, devapp.MAIN)
    with devapp.on_node(devapp._instance_node(slug, devapp.MAIN)):
        r = devapp._run(devapp._compose(slug, devapp.MAIN, "config", "-q"), timeout=30)
    if r["code"] != 0:
        devapp.forget_container(slug)
        return {"error": ("compose will not read that:\n" + r["out"]).strip()[-600:]}
    with devapp._lock:
        d3 = devapp._load()
        ((d3.get(slug) or {}).get(devapp.MAIN) or {}).pop("pending", None)
        devapp.write_json(devapp.FILE, d3)
    devapp._bump()
    return {"ok": True, "project": slug, "instance": devapp.MAIN,
            "name": devapp._pname(slug, devapp.MAIN)}


def overview_names():
    """Every name the store knows: what an endpoint checks a request against."""
    return set(devapp._load())


def update_container(name, compose_text, env_text):
    """Change what a container is, after it exists.
    (Validation runs against the container's own node; see the on_node in
    the body.)

    Ports move, a volume is added, an image is pinned: a compose file written
    here is edited far more often than it is created, and without this the only
    way to change one was to remove it and write it again from memory.

    The old file is kept until the new one parses. A compose file that will not
    read is not a state to leave a container in, and the operator is looking at
    the text that caused it.
    """
    if not devapp.is_file_source(name):
        return {"error": f"{name} is not a container written here"}
    if not (compose_text or "").strip():
        return {"error": "a compose file is needed"}
    if len(compose_text) > COMPOSE_MAX:
        return {"error": f"that compose file is over {COMPOSE_MAX // 1000}kB"}
    f = devapp.containers_dir(name) / "docker-compose.yml"
    try:
        was = f.read_text(encoding="utf-8")
    except OSError:
        was = ""
    try:
        f.write_text(compose_text, encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write it: {e}"}
    with devapp.on_node(devapp._instance_node(name, devapp.MAIN)):
        r = devapp._run(devapp._compose(name, devapp.MAIN, "config", "-q"), timeout=30)
    if r["code"] != 0:
        with contextlib.suppress(OSError):
            f.write_text(was, encoding="utf-8")
        return {"error": ("compose will not read that:\n" + r["out"]).strip()[-600:]}
    devapp.write_env(name, env_text or "", devapp.MAIN)
    devapp._bump()
    return {"ok": True, "project": name, "instance": devapp.MAIN,
            "note": "rebuild it to bring the change up"}


def read_container(name):
    """What was written, for the editor to open on."""
    try:
        compose = (devapp.containers_dir(name) / "docker-compose.yml").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        compose = ""
    return {"compose": compose, "env": devapp.read_env(name, devapp.MAIN)}


def listed_owner(c):
    """The project a container from containers() belongs to, or "".

    One of ours belongs where its instance does. Any other belongs where the
    operator put it on its row, kept by name on its node, so the same
    container recreated under its name keeps its project."""
    if c.get("ours"):
        row = devapp.row_named(c.get("project") or "")
        return devapp.owner_of(*row) if row else ""
    return (devapp._owners().get(devapp._node_here()) or {}).get(c.get("name") or "", "")


def set_container_owner(name, owner):
    """Which project a container BuilderBot did not start belongs to, on the
    node the current block addresses; "" for none. Only a container the
    daemon reports now, looked up again as every executing surface here is."""
    c = _known_container(name)
    if not c:
        return {"error": f"no container called {name} on this daemon now"}
    if c.get("ours"):
        return {"error": f"{c.get('name')} is part of {c.get('project')}: its "
                         "project is set on that row"}
    owner = str(owner or "").strip()[:100]
    node = devapp._node_here()
    if owner:
        # Only to a project that works on this node: given to one elsewhere
        # it would be out of reach of that project's sessions (R79).
        why, own = devapp.on_project_node(owner, node)
        if why:
            return {"error": why}
    with devapp._lock:
        d = devapp._owners()
        held = d.setdefault(node, {})
        if owner:
            held[c.get("name")] = owner
        else:
            held.pop(c.get("name"), None)
            if not held:
                d.pop(node, None)
        devapp.write_json(devapp.OWNERS, d)
    devapp._bump()
    return {"ok": True, "owner": owner}
