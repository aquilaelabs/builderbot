"""Roles and permissions (R137): what an account may read and change, as
named roles made of grants, kept in roles.json beside users.json.

A grant is a CAPABILITY on a SCOPE. The capabilities are the actions the
server's gate already asks about (users.may), grouped for the tab: what is
done to a project, what reaches a node, and what is the controller's. A
scope says where: every project, the projects the account is on
(membership, the Users tab's list), or named projects. A role is a named
set of grants; an account carries one or more roles and their grants add
up, never subtract: adding a role never takes something away.

owner, admin and user are built in, with grants that reproduce what each
could do before roles existed, so nothing changes until a role is made or
given. Built-in roles are not edited: copy one into a role of your own.

The operator, 5 Oct: the permission settings were too inconsistent, and a
person should be given a group of permissions.
"""
import json
import re
import threading
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ._-]{0,39}$")

# Every capability the gate asks about, with its group and the sentence the
# tab shows beside it. `work` is everything a person does on a project that
# is not listed on its own below: the notebook, a Claude session, settings,
# builds and tests, the phone it is lent.
CAPS = {
    "read": ("projects", "read a project: its notebook, code and state"),
    "work": ("projects", "work on a project: the notebook, a Claude session, its settings, builds and tests"),
    "version": ("projects", "move a project's version and release it"),
    "lock": ("projects", "lock a project, ending whoever's session is on it"),
    "rename": ("projects", "rename a project"),
    "trash": ("projects", "delete a project"),
    "git-auth": ("projects", "change how a project authenticates to its remote"),
    "docker-write": ("projects", "start, stop and rebuild containers"),
    "command-pin": ("projects", "move the pinned commands, one set for everybody"),
    "ftp": ("projects", "turn on a project's file access over FTP, its port, and who may sign in to it"),
    "node": ("nodes", "set which node a project builds on"),
    "toolchains-write": ("nodes", "install and remove toolchains on a node"),
    "jobs": ("nodes", "run a command on a node as a job"),
    "terminal": ("nodes", "a shell on a node"),
    "create": ("controller", "make a project"),
    "runner": ("controller", "the CI runner tab and its settings"),
    "admin": ("controller", "everything else an administrator does: nodes, toolchains, settings, accounts"),
    "debug": ("controller", "debug mode, the controller's diagnostics and nodes' logs, and granting them to a project's sessions"),
}
# Granted by name only (the operator, 6 Oct): `*` does not reach these, so
# the built-in admin and a role that grants everything leave them out, and
# only the owner has them until a role names them. ftp too (R151): who may
# reach a project's files from outside BuilderBot is the owner's to hand on.
NAMED_ONLY = frozenset({"debug", "ftp"})
# The capabilities whose scope is over NODES (step 3): every node, the
# nodes of the account's projects, or named ones.
NODE_CAPS = frozenset(c for c, (g, _) in CAPS.items() if g == "nodes")
GROUPS = (("projects", "On a project"), ("nodes", "On a node"), ("controller", "The controller"))
# What `work` does not cover: each needs a grant of its own.
OWN_CAPS = frozenset(c for c in CAPS if c not in ("read", "work"))
SCOPES = ("mine", "all")           # or a list of project names

# ---- R152: areas, each Read and Write -------------------------------------
# The operator, 7 Oct: a role is a scope and, per area, Read or Write;
# Write needs Read, and an area without Read is not seen. Project areas hold
# on a project (a Global role's on every one, a role given on a project on
# that one); global areas only through a Global role, which only an
# administrator gives. Each sentence is what the Roles tab shows.
AREAS = (
    ("projects", "Projects", "project", "its notebook and code", "a Claude session, edits, builds and tests"),
    ("settings", "Project settings", "project", "the settings", "change them, lock, rename and delete"),
    ("releases", "Releases and versions", "project", "versions and releases", "move the version and release"),
    ("gitauth", "Git authentication", "project", "how it authenticates", "change the credential"),
    ("files", "File access", "project", "read the files over FTP or in an editor", "save, upload, rename and delete them"),
    ("containers", "Containers", "project", "its containers and their logs", "start, stop and rebuild them"),
    ("terminal", "Terminal", "project", "the shielded Claude console", "the full tmux shell"),
    ("nodes", "Nodes", "global", "the Nodes tab", "configure nodes, and what a project's sessions reach"),
    ("toolchains", "Toolchains", "global", "the Toolchains tab", "install and remove"),
    ("jobs", "Jobs", "global", "the Jobs tab", "run a command on a node"),
    ("runner", "CI runner", "global", "the runner tab", "install and configure runners"),
    ("accounts", "Accounts and roles", "global", "the Users and Roles tabs", "add accounts, give roles"),
    ("newprojects", "New projects", "global", "the nodes a project may be made on", "make a project, and own it"),
    ("controller", "Controller", "global", "settings and diagnostics", "settings, debug, pinned commands"),
    # The Storage tab (R169): what every node's disks hold, by project.
    # Read sees it; Write measures a node again now.
    ("storage", "Storage", "global", "the Storage tab", "measure a node's disks now"),
)
# The areas a Global role may hold on named nodes alone (its `nodes`, none
# named being every node): what reaches a machine (the operator, 7 Oct).
NODE_AREAS = frozenset({"nodes", "toolchains", "jobs", "newprojects", "storage"})
AREA_KEYS = tuple(a[0] for a in AREAS)
PROJECT_AREAS = frozenset(a[0] for a in AREAS if a[2] == "project")
LEVELS = ("read", "write")
ROLE_SCOPES = ("global", "projects")

# Today's actions (users.may) on that model: the area and the level each
# needs, so every refusal already in the server keeps its words.
CAP_AREA = {
    "read": ("projects", "read"), "work": ("projects", "write"),
    "version": ("releases", "write"),
    "lock": ("settings", "write"), "rename": ("settings", "write"), "trash": ("settings", "write"),
    "git-auth": ("gitauth", "write"), "docker-write": ("containers", "write"),
    "terminal": ("terminal", "write"),
    "node": ("nodes", "write"), "toolchains-write": ("toolchains", "write"), "jobs": ("jobs", "write"),
    "runner": ("runner", "write"),
    "command-pin": ("controller", "write"), "create": ("newprojects", "write"),
    "admin": ("accounts", "write"), "debug": ("controller", "write"),
    "ftp": ("settings", "write"),
}

_ALL = {a: "write" for a in AREA_KEYS}
BUILTIN = {
    # Named for a person (R255 step 1): BuilderBot's owner is not a
    # project's, and neither is the Owner of X role a project's owner holds.
    "owner": {"scope": "global", "perms": dict(_ALL), "builtin": True, "nodes": [], "label": "BuilderBot's owner",
              "note": "the account every other rule is a guard rail around"},
    "admin": {"scope": "global", "perms": dict(_ALL), "builtin": True, "nodes": [], "label": "Administrator",
              "note": "everything the owner may do, except change the owner's account or roles"},
}
# There is no built-in user role (the operator, 7 Oct): an account on `user`
# is moved to no role and so no permission, and a project's owner holds
# PROJECT_owner, given on that project, with every project area to write.
OWNER_PERMS = {a: "write" for a in PROJECT_AREAS}


def owner_role_name(project):
    """The role a project's owner holds on it: PROJECT_owner, in the letters a
    role's name may use."""
    base = re.sub(r"[^A-Za-z0-9 ._-]", "-", str(project))[:33] or "project"
    if not base[0].isalpha():
        base = "p" + base[:32]
    return base + "_owner"

FILE = None
write_json = None
_lock = threading.Lock()


def configure(*, state, write_json):
    globals().update(FILE=Path(state) / "roles.json", write_json=write_json)


def _perms(p):
    """{area: read|write}, the ones that name a known area and level."""
    p = p if isinstance(p, dict) else {}
    return {a: p[a] for a in AREA_KEYS if p.get(a) in LEVELS}


def _from_grants(gs):
    """A role from before R152, its grants on today's actions, as a scope and
    areas: a grant on everything or on every project is Global, anything
    narrower the user's projects (a role is now given per project)."""
    perms, scope = {}, "projects"
    for g in gs if isinstance(gs, list) else []:
        if not isinstance(g, dict):
            continue
        cap = str(g.get("cap") or "")
        pairs = list(_ALL.items()) if cap == "*" else [CAP_AREA[cap]] if cap in CAP_AREA else []
        for area, lvl in pairs:
            if perms.get(area) != "write":
                perms[area] = lvl
        if g.get("scope") == "all":
            scope = "global"
    if scope == "projects" and any(a not in PROJECT_AREAS for a in perms):
        scope = "global"
    return {"scope": scope, "perms": perms}


def _clean(r):
    r = r if isinstance(r, dict) else {}
    if "grants" in r and "perms" not in r:
        r = dict(r, **_from_grants(r.get("grants")))
    scope = r.get("scope") if r.get("scope") in ROLE_SCOPES else "projects"
    nodes = r.get("nodes") if isinstance(r.get("nodes"), list) and scope == "global" else []
    return {"scope": scope, "perms": _perms(r.get("perms")), "builtin": False,
            "note": str(r.get("note") or "")[:200],
            "nodes": sorted({str(n)[:40] for n in nodes if str(n).strip()})[:64]}


def _load():
    try:
        v = json.loads(FILE.read_text())
    except (OSError, ValueError, TypeError, AttributeError):
        v = {}
    rs = v.get("roles") if isinstance(v, dict) and isinstance(v.get("roles"), dict) else {}
    return {str(n): _clean(r) for n, r in rs.items() if n not in BUILTIN}


def _save(custom):
    write_json(FILE, {"roles": {n: {k: r.get(k) for k in ("scope", "perms", "note", "nodes")} for n, r in custom.items()}})


def ensure_owner_role(project):
    """PROJECT_owner made when it is not there yet; its name."""
    name = owner_role_name(project)
    with _lock:
        d = _load()
        if name not in d:
            d[name] = {"scope": "projects", "perms": dict(OWNER_PERMS), "builtin": False,
                       "note": f"the owner of {project}"}
            _save(d)
    return name


def all_roles():
    """Every role, built in first, as the tab lists them."""
    out = {n: dict(r, name=n) for n, r in BUILTIN.items()}
    with _lock:
        for n, r in sorted(_load().items()):
            out[n] = dict(r, name=n)
            # A project's owner role reads as whose it is, not as its key.
            if str(r.get("note") or "").startswith("the owner of ") and n.endswith("_owner"):
                out[n]["label"] = "Owner of " + str(r["note"])[len("the owner of "):]
    return out


def label(name):
    """How a role is named to a person: its label, or its name."""
    r = all_roles().get(str(name or ""))
    return (r or {}).get("label") or str(name or "")


def get(name):
    return all_roles().get(str(name or ""))


def set_role(name, scope="projects", perms=None, note="", grants=None, nodes=None):
    """Make or change a role; owner and admin are built in and refused.
    `grants` is the shape from before R152, converted. `nodes`, for a Global
    role, limits its node areas to those nodes (NODE_AREAS)."""
    name = str(name or "").strip()
    if not NAME_RE.match(name):
        return {"error": "a role's name is letters, digits, spaces and . _ -, up to 40"}
    if name in BUILTIN:
        return {"error": f"{name} is built in and not changed"}
    r = _clean({"grants": grants} if grants is not None and perms is None else
               {"scope": scope, "perms": perms or {}, "nodes": nodes or []})
    r["note"] = str(note or "")[:200]
    if r["scope"] == "projects" and any(a not in PROJECT_AREAS for a in r["perms"]):
        bad = ", ".join(a for a in r["perms"] if a not in PROJECT_AREAS)
        return {"error": f"a role on the user's projects holds project areas only, not {bad}: "
                         "make it an Everywhere role for those"}
    with _lock:
        d = _load()
        d[name] = r
        _save(d)
    return {"ok": True, "name": name, "scope": r["scope"], "perms": r["perms"], "nodes": r["nodes"]}


def remove(name):
    name = str(name or "")
    if name in BUILTIN:
        return {"error": f"{name} is built in"}
    with _lock:
        d = _load()
        if name not in d:
            return {"error": f"no role called {name}"}
        del d[name]
        _save(d)
    return {"ok": True, "name": name}

def roles_of(u):
    """The roles an account carries everywhere: its list, or the one its role
    names (every account from before R137). The ones it carries on a single
    project are project_roles_of's."""
    if not isinstance(u.get("roles"), list):
        return [str(u.get("role") or "user")]
    rs = [str(r) for r in u["roles"] if str(r)]
    # Owner and admin stay what the account's role says (is_admin reads it);
    # anything else is the list, which is the whole answer since R152.
    base = str(u.get("role") or "")
    if base in BUILTIN and base not in rs:
        rs.insert(0, base)
    return rs


def project_roles_of(u, project):
    """The roles an account was given on `project` alone (R152)."""
    pr = u.get("project_roles") if isinstance(u.get("project_roles"), dict) else {}
    got = pr.get(str(project)) if project is not None else None
    return [str(r) for r in got] if isinstance(got, list) else []


def level_of(u, area, project=None, on_project=None, node=None):
    """The level this account holds on `area` ("", read or write), on
    `project` where one is named. An Everywhere (global) role holds
    everywhere; a role on a project holds on the project it is given on, and
    nowhere through the account's own list since R155 (the operator, 8 Oct:
    one way to give a project role). A global area is only ever an
    Everywhere role's. With no project named, the best it holds anywhere.
    `on_project` is kept in the signature for the callers that pass it."""
    known = all_roles()
    best = ""

    def take(r):
        nonlocal best
        lvl = r["perms"].get(area, "")
        if lvl == "write" or (lvl == "read" and not best):
            best = lvl
    for rn in roles_of(u):
        r = known.get(rn)
        if not r:
            continue
        if r["scope"] == "global":
            # A node area held on named nodes holds there alone; with no
            # node asked about it answers for "anywhere".
            if area in NODE_AREAS and r.get("nodes") and node is not None and node not in r["nodes"]:
                continue
            take(r)
    if area in PROJECT_AREAS:
        if project is not None:
            names = project_roles_of(u, project)
        else:
            pr = u.get("project_roles") if isinstance(u.get("project_roles"), dict) else {}
            names = [x for v in pr.values() if isinstance(v, list) for x in v]
        for rn in names:
            r = known.get(rn)
            if r:
                take(r)
    return best


def granted(u, action, project=None, on_project=None, node=None, nodes_of=None):
    """Whether this account's roles grant `action` (one of today's, through
    CAP_AREA), on `project` where one is named. A node's actions are global
    areas, held through a Global role on every node."""
    # An action not listed on its own (roadmap, bugs, pending, a project's
    # settings saved) is work on the project, as before R152.
    area, need = CAP_AREA.get(action, ("projects", "write"))
    lvl = level_of(u, area, project if area in PROJECT_AREAS else None, on_project,
                   node if area in NODE_AREAS else None)
    return lvl == "write" or (need == "read" and lvl == "read")


def nodes_for(u, area):
    """The nodes an account holds `area` on through its Global roles: None
    for every node, else the ones named (an empty list: none)."""
    known, out = all_roles(), set()
    for rn in roles_of(u):
        r = known.get(rn)
        if not r or r["scope"] != "global" or not r["perms"].get(area):
            continue
        if not r.get("nodes") or rn in BUILTIN:
            return None
        out |= set(r["nodes"])
    return sorted(out)


def summary(u):
    """What an account's roles add up to, for the Users tab: {area: level},
    the best it holds anywhere."""
    out = {}
    for a in AREA_KEYS:
        lvl = level_of(u, a)
        if lvl:
            out[a] = lvl
    return out
