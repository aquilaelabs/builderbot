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
import json
import os
import re
import sys
import tempfile
import time

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import devapp  # noqa: E402
from fields import field  # noqa: E402

# What the verbs at the foot need from the rest of the server, set by
# server.py: a project's Run its container dial, the account store, the
# asking (phone.ask_rebuild), and the sessions' networks told when a
# container changes hands (R79).
dial = None
users = None
ask_rebuild = None
net_nudge = None


def _targets(name):
    """The containers `name` means, as the daemon reports them now: the one
    it lists under that name or id, else every container of the instance or
    written container the Docker tab lists as `name`.

    The rule every executing surface here follows: what reaches a command
    line is a string this server handed out. A name typed by somebody, or
    remembered by a page from a listing five minutes old, is not that, so it
    is looked up again before it is used (R68 step 1).

    The second half is what `bb devapp ls` prints: an instance under its
    compose name, whose containers are named for it and its services
    (mediareducer-dev-mediareducer-1). Looked up by container name alone, that
    name found nothing, and a project's own dev instance was refused to its
    session as not its own, its log with it (reports #4, #6 and #9).
    """
    got = devapp.containers().get("containers") or []
    one = [c for c in got if name and (c.get("name") == name or c.get("id") == name)]
    if one:
        return one[:1]
    row = devapp.row_named(name)
    if not row:
        return []
    pn = devapp._pname(*row)
    return [c for c in got if c.get("project") == pn]


def _known_container(name):
    """The container the daemon just reported under this name, or None: the
    first of what the name means, which for an instance is one of its
    services (its project is the instance's, so a row's owner is read off
    it the same)."""
    return (_targets(name) or [None])[0]


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
    cs = _targets(name)
    if not cs:
        return {"error": f"no container called {name} on this daemon now: the list is "
                         "read again before anything is acted on, and it has moved"}
    # Every container the name means: an instance's services together.
    r = devapp._run([devapp.DOCKER, what, *[c.get("name") or c.get("id") for c in cs]], timeout=60)
    if r["code"] != 0:
        return {"error": devapp._why_not(r["out"]) or f"{what} failed"}
    did = ", ".join(c.get("name") or c.get("id") for c in cs)
    return {"ok": True, "out": f"{what}ped {did}" if what == "stop" else f"{what}ed {did}"}


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
    cs = _targets(name)
    if not cs:
        return {"error": f"no container called {name} on this daemon now"}
    n = str(int(lines or devapp.LOG_LINES))
    parts = []
    for c in cs:
        r = devapp._run([devapp.DOCKER, "logs", "--tail", n, "--timestamps",
                         c.get("name") or c.get("id")], timeout=30)
        # A container that has said nothing is not an error, and neither is
        # one whose log the daemon answered on stderr: docker writes a
        # container's own stderr there, which for most images is most of
        # the log.
        if r["code"] != 0 and not (r["out"] or "").strip():
            return {"error": devapp._why_not(r["out"]) or "could not read the log"}
        # An instance's services, each under its name; one container, as it is.
        parts.append((f"== {c.get('name') or c.get('id')} ==\n" if len(cs) > 1 else "")
                     + (r["out"] or ""))
    return {"ok": True, "name": name if len(cs) > 1 else (cs[0].get("name") or cs[0].get("id")),
            "text": "\n".join(parts)[-60000:]}


COMPOSE_MAX = 200_000            # a compose file is a page, not a payload


def name_free(name):
    """Why a container cannot be made under `name`, or "": one the store
    has, or a name another project's instance resolves to. Asked before a
    session's request reaches the bell as well as by create_container, so an
    administrator is not asked to decide on a request no answer can build
    (B309). The way forward is named rather than "pick another name": the
    usual reason to ask again under a name is to change that container,
    and a second name is a second container on the same data."""
    slug = devapp._slug(name) or ""
    if slug in devapp._load():
        return (f"{slug} already exists here. To change it, the operator removes it from "
                "the Docker tab first, or a session changes a variable with bb devapp "
                f"--container {slug} env set FILE and then bb devapp --container {slug} rebuild")
    return devapp.name_clash(slug, devapp.MAIN)


# A build declared anywhere in the text, flow style included: the only case
# the check below has anything to ask compose about.
_BUILD_KEY = re.compile(r"\bbuild\s*:")


def _contexts(compose_text, env, where):
    """{service: (build context, inline)} as compose resolves them with
    `where` as the project directory and `env` as the env file, the way
    create's own call is made; None when compose cannot read the file."""
    cf = os.path.join(os.path.dirname(env), os.path.basename(where) + ".yml")
    try:
        with open(cf, "w", encoding="utf-8") as fh:
            fh.write(devapp.env_to_instance(compose_text, env))
    except OSError:
        return None
    r = devapp._run([devapp.DOCKER, "compose", "--project-name", "bb-buildcheck",
                     "--project-directory", where, "-f", cf, "--env-file", env,
                     "config", "--format", "json"], timeout=30)
    raw = r["out"] or ""
    i = raw.find("{")
    if r["code"] != 0 or i < 0:
        return None
    try:
        cfg = json.JSONDecoder().raw_decode(raw[i:])[0]
    except ValueError:
        return None
    out = {}
    for svc, sv in ((cfg.get("services") if isinstance(cfg, dict) else None) or {}).items():
        b = sv.get("build") if isinstance(sv, dict) else None
        if isinstance(b, dict):
            out[svc] = (str(b.get("context") or "."), bool(b.get("dockerfile_inline")))
    return out


def relative_builds(compose_text, env_text=""):
    """The services of a compose file that would build from a relative
    context: for a container written here that is its own data directory,
    which is empty, since compose resolves a relative path against the
    project directory it is handed and such a container has no project tree
    behind it (B329). Asked of compose itself, twice, with two scratch
    directories standing in for the data directory: a context that moves
    with the project directory is relative, however it was written (a bare
    `build: .`, `..`, a context key, the default context, a variable), and
    one that stays put is an absolute path or a URL. A context compose
    leaves unresolved (the harness's stub) counts as relative. Empty when
    nothing is built from a path, for a dockerfile_inline, and when compose
    cannot read the file, which create refuses in its own words."""
    if not _BUILD_KEY.search(compose_text or ""):
        return []
    with tempfile.TemporaryDirectory(prefix="bb-buildcheck-") as tmp:
        env = os.path.join(tmp, ".env")
        try:
            with open(env, "w", encoding="utf-8") as fh:
                fh.write(env_text or "")
        except OSError:
            return []
        one = _contexts(compose_text, env, os.path.join(tmp, "one"))
        two = _contexts(compose_text, env, os.path.join(tmp, "two", "deeper"))
    if one is None or two is None:
        return []
    out = []
    for svc, (ctx, inline) in sorted(one.items()):
        if inline or "://" in ctx or ctx.startswith("git@"):
            continue
        if not ctx.startswith("/") or two.get(svc, (ctx, False))[0] != ctx:
            out.append(svc)
    return out


def build_refusal(name, compose_text, env_text=""):
    """Why a container written here would build nothing, or "": said by
    create and by Edit, and before a session's ask reaches anybody's bell."""
    svcs = relative_builds(compose_text, env_text)
    if not svcs:
        return ""
    return (f"{name or 'this container'} builds {', '.join(svcs)} from a relative path, and a "
            "container written here has no project tree behind it: compose resolves that path "
            "against the container's own data directory, which is empty, so there is nothing to "
            "build. A project's own code goes into Docker from a compose file at the project's "
            "root (docker-compose.yml or compose.yml), with Send to Docker on its Artifacts tab "
            "or bb devapp new from a session, and builds from the tree. A container written "
            "here builds from an absolute path or a git URL.")


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
        why = name_free(slug)
        if why:
            return {"error": why}
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
    # ...and a file that reads but builds from its own empty data directory
    # is a container that can never be built (B329), taken away the same way.
    why = build_refusal(name, compose_text, env_text)
    if why:
        devapp.forget_container(slug)
        return {"error": why}
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
    why = "" if r["code"] != 0 else build_refusal(name, compose_text, env_text)
    if r["code"] != 0 or why:
        with contextlib.suppress(OSError):
            f.write_text(was, encoding="utf-8")
        return {"error": why or ("compose will not read that:\n" + r["out"]).strip()[-600:]}
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


# ---- the Docker tab's verbs, one call from the dashboard -----------------------

def not_ours(what, sess=""):
    """The refusal for a container that does not belong to the caller's
    project. The owner is not named: to a session that would be another
    project's name, which is the thing it may not read."""
    return (f"{what} does not belong to {sess}: a session reaches its own project's "
            "containers, and an administrator sets which project each belongs to on "
            "the Docker tab" if sess else
            f"{what} does not belong to one of your projects: an administrator sets "
            "which project each container belongs to on the Docker tab")


def _answer(r):
    return r, (400 if r.get("error") else 200)


def session_verb(sess, me, act, name, req):
    """A SESSION's word on one container that belongs to its project (the
    operator, 24 Sep): on its project's nodes, its log when it asks, since
    that is reading it, and start, stop or restart as the project's Run its
    container setting allows. (payload, status)."""
    # Looked for on each of the project's nodes, primary first: its
    # containers live on any of them (R82), and asking the primary
    # alone refused the project's own dev instance on its second
    # node as not its own (B268).
    c, owner, nid = None, "", devapp.project_daemon(sess)
    for cand in (devapp.nodes_of(sess) or [nid]):
        with devapp.on_node(cand or None):
            c, owner = owned_container(name)
        if c:
            nid = cand
            break
    # A stranger's container and a missing one answer alike; one of the
    # project's own with nothing running under it is said as that.
    if owner != sess:
        row = devapp.row_named(name)
        if row and devapp.owner_of(*row) == sess:
            return {"error": f"{name} has no containers on its node now: bb devapp says "
                             "whether it is built and up"}, 400
        return {"error": not_ours(name, sess)}, 403
    if act == "logs":
        with devapp.on_node(nid or None):
            return container_logs(name), 200
    if act not in ("start", "stop", "restart"):
        return {"error": f"a session starts, stops or restarts a "
                         f"container, or reads its log, not {act!r}"}, 400
    mode = dial(sess)
    if mode == "deny":
        return {"error": devapp.RUN_DENIED}, 403
    if mode == "ask":
        acct = users.account_of(me) or {}
        return _answer(ask_rebuild(
            field(req, "why"), sess, "", c["name"],
            asker_uid=str(acct.get("uid") or ""),
            asker_name=str(acct.get("name") or ""),
            asker_admin=users.is_admin(acct), ctl=act, node=nid))
    with devapp.on_node(nid or None):
        return _answer(container_ctl(name, act))


def admin_verb(act, name, nid, under):
    """An administrator's word on one container on node `nid`: which project
    it belongs to (`under`, one the server has checked, or none), its log,
    or start, stop and restart. Every docker call is addressed at that
    node's daemon, the way the manager's own listing is. (payload,
    status)."""
    with devapp.on_node(nid or None):
        if act == "owner":
            r = set_container_owner(name, under)
            # Whose it is also decides whose sessions may reach it (R79).
            if not r.get("error"):
                net_nudge()
            return _answer(r)
        if act == "logs":
            return container_logs(name), 200
        return _answer(container_ctl(name, act))


def tab_verb(act, name, req, seen):
    """A container from a compose file written on the Docker tab, with no
    project behind it: read or save one, or create one. `seen()` is the
    projects this account sees. (payload, status)."""
    if act == "read":
        if name not in overview_names():
            return {"error": f"no container {name}"}, 400
        return read_container(name), 200
    if act == "save":
        if name not in overview_names():
            return {"error": f"no container {name}"}, 400
        return _answer(update_container(name, req.get("compose") or "", req.get("env") or ""))
    if act != "create":
        return {"error": f"unknown action: {act}"}, 400
    # A name that is also a project would collide in the store, which is
    # keyed by one namespace for both kinds, and the collision is on the
    # SLUG, not the typing. `builderbot` is not the project `BuilderBot`
    # by string comparison and is exactly it by the time _pname has run:
    # same compose project name, same env file, same data directory, with
    # nothing anywhere saying the two had met.
    mine = seen()
    clash = next((p for p in mine if devapp._slug(p) == devapp._slug(name)), "")
    if name and clash:
        return {"error": f"that is the project {clash}: a "
                         f"container written here needs a name "
                         f"of its own"}, 400
    # The project it belongs to, when one is picked: only a project this
    # account can see, or none.
    under = field(req, "owner")
    if under and under not in mine:
        return {"error": f"not a project: {under}"}, 400
    r = create_container(name, req.get("compose") or "",
                         req.get("env") or "", field(req, "node"), under)
    # Made for a project: its sessions may reach it (R79).
    if not r.get("error") and under:
        net_nudge()
    return _answer(r)


def manager_view(nid, seen):
    """The Docker manager's whole page in one answer: every instance bound
    to the node, and every container on that node's daemon that is not one
    of them. `seen` is None for an administrator, or the projects whose
    instances and containers this account may see: a node is shared, and
    anything else on it is another project's work, or nobody's (the
    operator, 24 Sep)."""
    # Refresh is the retry: drop the memoised availability first, so a
    # daemon wired up thirty seconds ago is noticed by pressing the
    # button rather than by waiting for the memo to lapse.
    devapp.forget_available()
    got = devapp.overview(nid or None)
    if seen is not None:
        got["instances"] = [i for i in got.get("instances") or []
                            if i.get("owner") in seen]
        got["containers"] = [c for c in got.get("containers") or []
                             if c.get("owner") in seen]
        # The branches go with them: the Build from picker is an
        # administrator's.
        got["refs"] = {}
        return got
    # The branches each listed project could be built from. Here
    # rather than per row: they come from one `for-each-ref` per
    # project, and the picker needs them before anybody presses.
    got["refs"] = {p: devapp.refs_of(p)
                   for p in {i["project"] for i in got.get("instances") or []}
                   if not devapp.is_file_source(p)}
    return got
