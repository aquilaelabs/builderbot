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
    "node": ("nodes", "set which node a project builds on"),
    "toolchains-write": ("nodes", "install and remove toolchains on a node"),
    "jobs": ("nodes", "run a command on a node as a job"),
    "terminal": ("nodes", "a shell on a node"),
    "create": ("controller", "make a project"),
    "runner": ("controller", "the CI runner tab and its settings"),
    "admin": ("controller", "everything else an administrator does: nodes, toolchains, settings, accounts"),
}
# The capabilities whose scope is over NODES (step 3): every node, the
# nodes of the account's projects, or named ones.
NODE_CAPS = frozenset(c for c, (g, _) in CAPS.items() if g == "nodes")
GROUPS = (("projects", "On a project"), ("nodes", "On a node"), ("controller", "The controller"))
# What `work` does not cover: each needs a grant of its own.
OWN_CAPS = frozenset(c for c in CAPS if c not in ("read", "work"))
SCOPES = ("mine", "all")           # or a list of project names

BUILTIN = {
    "owner": {"grants": [{"cap": "*", "scope": "all"}], "builtin": True,
              "note": "the account every other rule is a guard rail around"},
    "admin": {"grants": [{"cap": "*", "scope": "all"}], "builtin": True,
              "note": "the machinery: nodes, toolchains, settings, accounts; works on the projects on its own list"},
    "user": {"grants": [{"cap": "read", "scope": "mine"}, {"cap": "work", "scope": "mine"}], "builtin": True,
             "note": "reads and works on the projects it was given, and nothing of the machinery"},
}

FILE = None
write_json = None
_lock = threading.Lock()


def configure(*, state, write_json):
    globals().update(FILE=Path(state) / "roles.json", write_json=write_json)


def _load():
    try:
        v = json.loads(FILE.read_text())
    except (OSError, ValueError, TypeError, AttributeError):
        v = {}
    rs = v.get("roles") if isinstance(v, dict) and isinstance(v.get("roles"), dict) else {}
    out = {}
    for name, r in rs.items():
        if not isinstance(r, dict) or name in BUILTIN:
            continue
        out[str(name)] = {"grants": _clean_grants(r.get("grants")), "builtin": False,
                          "note": str(r.get("note") or "")[:200]}
    return out


def _save(custom):
    write_json(FILE, {"roles": custom})


def _clean_grants(gs):
    out = []
    for g in gs if isinstance(gs, list) else []:
        if not isinstance(g, dict):
            continue
        cap = str(g.get("cap") or "")
        if cap != "*" and cap not in CAPS:
            continue
        sc = g.get("scope")
        if isinstance(sc, list):
            sc = sorted({str(p)[:120] for p in sc if str(p).strip()})[:200]
            if not sc:
                continue
        elif sc not in SCOPES:
            continue
        out.append({"cap": cap, "scope": sc})
    return out[:200]


def all_roles():
    """Every role, built in first, as the tab lists them."""
    out = {n: dict(r, name=n) for n, r in BUILTIN.items()}
    with _lock:
        for n, r in sorted(_load().items()):
            out[n] = dict(r, name=n)
    return out


def get(name):
    return all_roles().get(str(name or ""))


def set_role(name, grants, note=""):
    """Make or change a role of your own; a built-in one is refused."""
    name = str(name or "").strip()
    if not NAME_RE.match(name):
        return {"error": "a role's name is letters, digits, spaces and . _ -, up to 40"}
    if name in BUILTIN:
        return {"error": f"{name} is built in: copy it into a role of your own"}
    gs = _clean_grants(grants)
    if not gs:
        return {"error": "a role needs at least one grant"}
    with _lock:
        d = _load()
        d[name] = {"grants": gs, "builtin": False, "note": str(note or "")[:200]}
        _save(d)
    return {"ok": True, "name": name, "grants": gs}


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


def rename_project(old, new):
    """A project renamed is renamed in every named scope."""
    with _lock:
        d = _load()
        moved = False
        for r in d.values():
            for g in r["grants"]:
                if isinstance(g["scope"], list) and old in g["scope"]:
                    g["scope"] = sorted({new if p == old else p for p in g["scope"]})
                    moved = True
        if moved:
            _save(d)
    return moved


def roles_of(u):
    """The roles an account carries: its list, or the one its role names
    (every account from before R137)."""
    rs = u.get("roles") if isinstance(u.get("roles"), list) else []
    rs = [str(r) for r in rs if str(r)]
    base = str(u.get("role") or "user")
    if base not in rs:
        rs.insert(0, base)
    return rs


def granted(u, action, project=None, on_project=None, node=None, nodes_of=None):
    """Whether this account's roles grant `action`, on `project` where one
    is named, or on `node` for a capability scoped over nodes. `on_project(u,
    name)` says whether the account is on that project (users.may_work),
    which is what the scope "mine" means; `nodes_of(u)` lists the nodes of
    the projects it is on, which is what "mine" means for a node. With
    nothing named, "mine" answers for the question "at all", as the gate
    did before roles: a capability on what you are on is one you have."""
    known = all_roles()
    where = node if action in NODE_CAPS else project
    for rn in roles_of(u):
        r = known.get(rn)
        if not r:
            continue
        for g in r["grants"]:
            cap = g["cap"]
            if cap == "*":
                pass
            elif cap == action:
                pass
            elif cap == "work" and action not in OWN_CAPS:
                pass
            else:
                continue
            sc = g["scope"]
            if sc == "all":
                return True
            if where is None:
                if sc == "mine":
                    return True
                continue
            if sc == "mine":
                if action in NODE_CAPS:
                    if nodes_of and where in (nodes_of(u) or ()):
                        return True
                elif on_project and on_project(u, where):
                    return True
            if isinstance(sc, list) and where in sc:
                return True
    return False


def summary(u):
    """The capabilities an account's roles add up to, for the Users tab:
    {cap: [scopes]}, "all" swallowing the rest."""
    out = {}
    known = all_roles()
    for rn in roles_of(u):
        r = known.get(rn)
        if not r:
            continue
        for g in r["grants"]:
            caps = list(CAPS) if g["cap"] == "*" else [g["cap"]]
            for c in caps:
                have = out.setdefault(c, [])
                if g["scope"] == "all":
                    out[c] = ["all"]
                elif "all" not in have and g["scope"] not in have:
                    have.append(g["scope"])
    return out
