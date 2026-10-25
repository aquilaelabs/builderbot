"""Who may sign in to the DASHBOARD, and what they are allowed to see.

Not signin.py, which is the flow for signing in to Claude. Adjacent names,
unrelated jobs: that one hands a code to `claude auth login`, this one decides
whether the person at the browser gets a page at all.

The design is docs/users.md; this is step 1 of roadmap #22 and deliberately
enforces nothing. It replaces one string comparison (`DASHBOARD_AUTH`) with a
store of accounts, so that a later step has somebody to ask about. Every
account created here is an owner or an admin, and both can do everything, which
is why a single-operator install notices no difference at all.

Three roles: `owner` (exactly one, undeletable), `admin` (everything but acting
on the owner) and `user` (named projects, and the work inside them). The role
and the project list are stored now and read now; they are ENFORCED in step 2.

Passwords are pbkdf2-hmac-sha256 from the standard library, because the
dashboard has no dependencies and is not acquiring one for this. The iteration
count lives in each record rather than in a constant here, so raising it later
upgrades people as they sign in instead of locking everybody out at once.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from pathlib import Path

# The request-field reader verb() shares with the server (fields.py), found
# beside this file however it was loaded: the login path and bb load it by
# path, where a plain sibling import finds nothing.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fields import field  # noqa: E402
import roles  # noqa: E402

STATE = Path("/config")
write_json = None
# prefs.for_user: one person's settings on one project, for the git
# identity override below. Injected, so users.py stays the module the
# login path imports on its own.
project_prefs = None
_lock = threading.RLock()

ROLES = ("owner", "admin", "user")
# 600k is the OWASP floor for pbkdf2-sha256 at the time of writing. It costs
# about a fifth of a second here, which is the right price for a login and the
# wrong one for anything on a poll. Nothing calls this per request.
ITERATIONS = 600_000
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,63}$")


def configure(*, state, write_json, project_prefs=None, nodes_of=None):
    globals().update(STATE=Path(state), write_json=write_json,
                     project_prefs=project_prefs)
    if nodes_of is not None:
        globals()["nodes_of"] = nodes_of


# nodes_of(u): the nodes of the projects an account is on, which is what a
# node grant's scope "mine" means (R137 step 3). Set by the server from prefs.
nodes_of = None


def _file():
    return STATE / "users.json"


# --- passwords -------------------------------------------------------------

def hash_password(password, iterations=ITERATIONS):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def check_password(stored, password):
    """Constant-time where it counts, and False on anything malformed.

    A record this cannot parse is a record nobody can sign in as, which is the
    safe direction: a corrupted file locks the dashboard rather than opening
    it, and `bb users passwd` is the way back.
    """
    try:
        kind, iters, salt, want = str(stored).split("$", 3)
        if kind != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt), int(iters))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), want)


# --- the store -------------------------------------------------------------

def mint_uid():
    """A stable id for an account, minted once and never reused.

    The NAME is not it. The owner is deliberately renameable, which is the
    only way to retire the seeded one since it cannot be deleted, and every
    other account can be renamed too, so anything durable hung off a name is
    orphaned the first time somebody uses that. Homes, tab layouts, themes and
    the Claude-session holder all hang off this instead. Same rule as a node's
    (docs/nodes.md §15, door 1): ids are minted, never derived, never reused.
    """
    return "u_" + secrets.token_hex(4)


def load():
    try:
        d = json.loads(_file().read_text())
    except (OSError, ValueError):
        return {"users": {}}
    if not isinstance(d.get("users"), dict):
        return {"users": {}}
    return d


def _save(d):
    # Private from the instant it is in place, where the helper can take a
    # mode (statefile's); the harness and bb users hand in one that cannot.
    try:
        write_json(_file(), d, mode=0o600)
    except TypeError:
        write_json(_file(), d)
    # The file holds password hashes. write_json does not know that, so the
    # mode is set here rather than assumed, and tolerated when it fails,
    # because a dashboard that will not start is worse than one whose file is
    # readable by an account that could read /config anyway.
    try:
        os.chmod(_file(), 0o600)
    except OSError:
        pass


def all_users():
    """Every account, without the hashes. What a listing is allowed to see."""
    out = []
    for name, u in sorted(load()["users"].items()):
        pr = u.get("prefs") if isinstance(u.get("prefs"), dict) else {}
        out.append({"name": name, "uid": u.get("uid", ""),
                    "role": u.get("role", "user"),
                    "projects": list(u.get("projects") or []),
                    # The roles it carries (R137): its role, and any of your own.
                    "roles": roles.roles_of(u),
                    "created": u.get("created", 0), "seen": u.get("seen", 0),
                    # The Profile fields, for the Users tab's edit dialog:
                    # never a credential, never the theme.
                    "profile": {k: str(pr.get(k) or "")[:n] for k, n in PROFILE_FIELDS.items()}})
    return out


def get(name):
    u = load()["users"].get(str(name))
    return {**u, "name": str(name)} if u else None


def uid_of(u):
    """The minted id for a principal, or "" for one that is not a person.

    The server's own contexts (ALL) and a session's scoped token both reach
    code that wants to remember something per account. Neither should: a
    background sweep has no tab strip and a `bb` invocation has no browser. So
    they answer "" and every per-account store treats that as "do not store".
    """
    uid = (u or {}).get("uid") or ""
    return "" if uid == "\u0000server" else str(uid)


def starts_unpinned(u):
    """Whether this account's Home starts with no project pinned until it
    pins one (projects.load_project_pins). Every account made since 7 Oct
    does (the operator: a new user starts with nothing pinned and adds what
    they want); one made before keeps "all of them" until it pins, so an
    update does not empty a Home somebody was using."""
    return bool((u or {}).get("pins_empty"))


def tmux_prefix(u):
    """What this account's shell sessions are named with, or "" for none.

    A SHELL is per account: two people opening a terminal on one project must
    not land in each other's, which is what one name would do, since tmux
    attaches to an existing session rather than making a second.

    The OWNER is the exception, and it is the same exception as the home
    (lib/common.sh's user_home): they keep the unprefixed names, because a box
    with one operator is every box until somebody adds a second account, and
    an upgrade that renamed every running session under them would be a cost
    paid by everyone to serve a case most installs never reach.

    A Claude session is never prefixed at all, whoever opens it: one
    conversation per project is the rule, and who holds it is a record the
    dashboard keeps rather than a name (roadmap #26 step 2).
    """
    uid = uid_of(u)
    return f"{uid}~" if uid and uid != owner_uid() else ""


def owner_uid():
    for u in load()["users"].values():
        if u.get("role") == "owner":
            return u.get("uid") or ""
    return ""


def prefs(u):
    """This account's own settings: the theme, today. Never secret, and
    carried in the state payload, so nothing here may hold a credential."""
    rec = get((u or {}).get("name") or "") or {}
    p = rec.get("prefs")
    return dict(p) if isinstance(p, dict) else {}


# What an account may say about itself on its Profile tab, and how long
# each may be. Whitelisted by name: the store is read on the login path and
# holds password hashes, so nothing arbitrary is parked in it.
PROFILE_FIELDS = {"full_name": 120, "email": 200, "git_name": 120, "git_email": 200}


def account_of(u):
    """The account behind a principal: itself, or for a session's token the
    account it was minted for, found by uid. A session has an author too,
    and it is the person's."""
    u = u or {}
    if u.get("session") and u.get("uid"):
        for name, rec in load()["users"].items():
            if isinstance(rec, dict) and rec.get("uid") == u["uid"]:
                return {**rec, "name": name}
    return u


def profile(u):
    """The account's own settings, for its Profile page: never a credential."""
    p = prefs(account_of(u))
    return {k: str(p.get(k) or "")[:n] for k, n in PROFILE_FIELDS.items()}


def git_identity(u, project=""):
    """The name and email this account's commits carry: its git identity
    where it set one, else its real name and email, else nothing, because a
    made-up address would be a lie in every log it landed in (git_ready).

    Per ACCOUNT, not per project: two people working on one project are
    two authors, and a repo-level user.name would make them one. It reaches
    a session as git's environment (bb-tty exports GIT_AUTHOR_* and
    GIT_COMMITTER_*), which outranks any config a repository carries, so a
    project set up under the old per-project identity commits as the person
    at the keyboard all the same.
    """
    p = profile(u)
    # A per-project override first where the person set one: somebody may
    # commit to one repository under a different address, and that is a choice
    # about their own commits rather than the project's about everybody's.
    # Each field falls back on its own, so an override may set the email and
    # leave the name alone.
    base = {"name": p["git_name"] or p["full_name"],
            "email": p["git_email"] or p["email"]}
    over = {}
    if project and project_prefs:
        acc = account_of(u)
        over = project_prefs(str(acc.get("uid") or ""), project) or {}
    return identity_over(base, over)


def identity_over(base, over):
    """`base` with a per-project override applied, field by field.

    Beside git_identity so the precedence is written once: project_list wants
    the answer for a dozen projects from one read of each file, so it resolves
    them through here rather than calling git_identity per row.
    """
    over = over or {}
    return {"name": str(over.get("git_name") or "") or base["name"],
            "email": str(over.get("git_email") or "") or base["email"]}


def git_ready(u, project=""):
    """Whether this account's commits would carry an author: a name and an
    email, from the git fields or the plain ones. A Claude session is not
    started without it: every project is a repository, and a commit with
    no author is one git refuses, halfway through whatever the session was
    doing. Nothing is invented to fill the gap: an address made up from an
    account name would be a lie in every log it lands in."""
    g = git_identity(u, project)
    return bool(g["name"] and g["email"])


def git_env(u, project=""):
    """The four variables git reads ahead of any config, for a subprocess
    committing on this account's behalf; {} for a principal that is nobody."""
    g = git_identity(u, project)
    if not (g["name"] and g["email"]):
        return {}
    return {"GIT_AUTHOR_NAME": g["name"], "GIT_AUTHOR_EMAIL": g["email"],
            "GIT_COMMITTER_NAME": g["name"], "GIT_COMMITTER_EMAIL": g["email"]}


def profile_set(name, patch):
    """Merge the Profile page's fields: PROFILE_FIELDS only, each capped."""
    keep = {}
    for k, n in PROFILE_FIELDS.items():
        if k in patch:
            keep[k] = " ".join(str(patch.get(k) or "").split())[:n]
    if not keep:
        return {"error": "nothing here is a profile field"}
    for k in ("email", "git_email"):
        if keep.get(k) and not EMAIL_RE.fullmatch(keep[k]):
            return {"error": f"{keep[k]} is not an email address"}
    return prefs_set(name, keep)


# One local part, one @, a host with a dot in it, no whitespace. Not the
# RFC, whose grammar admits addresses no mail server has seen, but the
# shape every address anybody types here has, and the one a typo breaks.
EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


def change_password(name, current, new):
    """An account changing its OWN password: the current one is checked
    first, so a browser left signed in is not enough to lock its owner out."""
    if not authenticate(name, current or ""):
        return {"error": "the current password is not right"}
    return set_password(name, new)


def prefs_set(name, patch):
    """Merge into an account's prefs. Keys are whitelisted by the caller:
    this is reached from a signed-in browser, so an unbounded dict here would
    be a place to park arbitrary data in a file the login path reads."""
    with _lock:
        d = load()
        u = d["users"].get(str(name))
        if not u:
            return {"error": f"no account called {name}"}
        cur = u.get("prefs")
        u["prefs"] = (dict(cur) if isinstance(cur, dict) else {}) | dict(patch)
        _save(d)
    return {"ok": True, "prefs": u["prefs"]}


def owner_name():
    for name, u in load()["users"].items():
        if u.get("role") == "owner":
            return name
    return ""


# --- signing in ------------------------------------------------------------

def authenticate(name, password):
    """The account, or None. The only place a password is checked."""
    u = get(name)
    if not u or not check_password(u.get("password", ""), password or ""):
        return None
    return u


# Basic auth arrives on EVERY request `bb` makes and on every request the test
# suite makes, and a pbkdf2 verify costs a fifth of a second BY DESIGN. So the
# answer is remembered for a minute: the price stays on the sign-in rather than
# on the poll. What is kept is a digest of the credential and never the
# credential, and the account's stamp with it, so changing a password drops
# the cached answer on the next request instead of a minute later.
_recent = {}
_RECENT_S = 60


def authenticate_pair(pair):
    """`user:password` as Basic auth and `bb` send it.

    Split on the FIRST colon: a password may contain one, a username may not.
    """
    name, sep, password = str(pair or "").partition(":")
    if not sep:
        return None
    key = hashlib.sha256(str(pair).encode()).hexdigest()
    now = time.monotonic()
    with _lock:
        hit = _recent.get(key)
    if hit and hit[1] > now:
        u = get(hit[0])
        if u and hmac.compare_digest(stamp(u), hit[2]):
            return u
    u = authenticate(name, password)
    if u:
        with _lock:
            if len(_recent) > 64:            # a bounded cache, not a leak
                _recent.clear()
            _recent[key] = (u["name"], now + _RECENT_S, stamp(u))
    return u


def touch(name):
    """Record that this account was just used. Best effort: a failed write
    here must never cost somebody their sign-in."""
    try:
        with _lock:
            d = load()
            if name in d["users"]:
                d["users"][name]["seen"] = int(time.time())
                _save(d)
    except (OSError, ValueError):
        pass


def stamp(u):
    """What a session cookie is bound to, besides the name.

    The hash itself, folded down. Changing a password or deleting an account
    changes it, so every cookie issued against the old one stops verifying,
    which is how a stateless token gets revocation without a table to keep.
    """
    return hashlib.sha256(str((u or {}).get("password", "")).encode()).hexdigest()[:16]


# --- who may see and do what ------------------------------------------------
#
# Enforced from step 2. The shape to hold to: a project somebody cannot see is
# ABSENT rather than refused, which server.project_list() does by filtering,
# and that makes the existence check and the permission check the same check.
# Asking about a project you were not given returns what a typo returns.

# The server's own non-request contexts: a boot log, a background sweep, the
# doctor. They are not a person and are not filtered, and they say so by
# passing this rather than by passing None, which would be indistinguishable
# from "nobody is signed in" and must not be.
ALL = {"role": "owner", "projects": ["*"], "name": "\u0000server",
       "uid": "\u0000server"}
# repos.key_of, handed over by the server (R138): the project a name stands
# for, a repository's being its project's. An account's project list and its
# project roles are kept by project, so every name is asked through it.
# Unset, every name is its own.
home_of = None


def key_of(name):
    """The project `name` stands for (repos.key_of), or `name`."""
    return home_of(name) if home_of else name

# What a `user` may not do to a project they DO have. Named, not derived: a
# verb that should be restricted and is not listed is a decision somebody has
# to make, not something to infer from a URL.
#
# There is no "delete" here because there is no delete: a project is removed
# by moving it to the trash and purging it, and both are `trash`.
USER_DENIES = ("rename", "trash", "node", "create", "terminal", "git-auth", "runner",
               "docker-write", "toolchains-write", "jobs", "lock", "command-pin", "version", "debug",
               "ftp")


def sees_all(u):
    """Whether every project is LISTED for this account.

    Owner and admin see everything, and this is deliberately not the same
    question as whether they may touch it (see may_work). An administrator
    hidden from a project could not administer it, and a list with holes in it
    is how somebody goes looking for a project that is right there.

    A record carrying "*" sees everything too, which is what the seeded owner
    gets.
    """
    if u is ALL:
        return True
    if not u:
        return False                        # not signed in sees nothing
    return u.get("role") in ("owner", "admin") or "*" in (u.get("projects") or [])


def may_work(u, name):
    """Whether this account may CHANGE anything about `name`.

    The project list means the same thing for every role, which is the whole
    point of it: a project you did not take on is one you cannot edit, start a
    Claude session in, or rebuild, for an administrator exactly as for a
    user. What differs is the remedy. An administrator can add any project to
    their own list and carry on; a user has to be given one.

    So this is not a security boundary for an administrator and is not sold as
    one: it is the seatbelt that stops somebody with rights over forty
    projects working on the wrong one. For a `user` it is a boundary, because
    they cannot grant themselves anything.
    """
    if u is ALL:
        return True
    if not u:
        return False
    # A session works on the one project its token was minted for. The
    # others in its list are the ones that project reads (prefs.reads),
    # there to be seen and never changed.
    if u.get("session"):
        return name == u["session"] or key_of(name) == key_of(u["session"])
    # "*" lists every project (sees_all) and takes none on (R135): the
    # owner works on what they added to their own list, like everybody,
    # as a safeguard against working on the wrong one by accident.
    # A repository is worked on by whoever is on its project (R138).
    return key_of(name) in _keys(u)


def _keys(u):
    """The projects an account's list names, each as its project's key: an
    entry written as a repository's name before that repository was put in
    a project (an import, a clone) counts for the project it is in now."""
    return {key_of(p) for p in ((u or {}).get("projects") or [])}


def visible(u, names):
    """`names`, minus what this account may not see."""
    if sees_all(u):
        return list(names)
    allow = _keys(u)
    return [n for n in names if key_of(n) in allow]


def may_see(u, name):
    return sees_all(u) or key_of(name) in _keys(u)


def is_admin(u):
    """Whether this account owns the machinery: nodes, toolchains, settings,
    other accounts. Everything that is not a project.

    A session token is never one, whatever it says: session_principal builds
    it with `user`, and this refuses to be talked out of that even if a future
    caller hands in a record claiming otherwise."""
    if (u or {}).get("session"):
        return False
    return u is ALL or (u or {}).get("role") in ("owner", "admin")


def may_node(u, action, node_id=""):
    """Whether this account may do `action` on the node `node_id`, for the
    capabilities scoped over nodes (R137 step 3: toolchains-write, jobs,
    node, terminal). "" when it may, else the reason, like may()."""
    if u is ALL:
        return ""
    if not u:
        return "not signed in"
    if roles.granted(u, action, node=str(node_id or "") or None, nodes_of=nodes_of):
        return ""
    # A node area's answer is the node's (R152): asking again with no node
    # would answer "anywhere" for a role held on other nodes.
    area = roles.CAP_AREA.get(action, ("", ""))[0]
    if area in roles.NODE_AREAS and node_id:
        return may(u, action) or "your roles do not give that on this node"
    return may(u, action) or "that is not one of your roles' grants on that node"


def may_instance(u, action, instance="", name=""):
    """Whether this account may do `action` on one instance of its area (a
    node, a runner's NODE_ID/SLOT: roles.INSTANCE_AREAS, R260), "" when it
    may, else the reason. No `instance` is a new one, which a role holding
    the area on named instances alone does not reach: it is on none of them
    yet. `name` is how the refusal names the instance."""
    if u is ALL:
        return ""
    if (why := may(u, action)):
        return why
    area, need = roles.CAP_AREA.get(action, ("projects", "write"))
    if area not in roles.INSTANCE_AREAS or is_admin(u) or (u or {}).get("session"):
        return ""
    label = next((a[1] for a in roles.AREAS if a[0] == area), area)
    lvl, what = ("Write" if need == "write" else "Read"), ("runner" if area == "runner" else "node")
    if not instance:
        if roles.nodes_for(u, area, need) is None:
            return ""
        return (f"your roles give {label} {lvl} on some {what}s, not on every one, "
                f"and a new {what} is none of them yet: a role holding it on every {what} is set on the Roles page")
    if roles.granted(u, action, node=instance if area in roles.NODE_AREAS else None, instance=instance):
        return ""
    return f"your roles give no {label} {lvl} on {name or instance}: an administrator gives one on the Users page"


# The actions a session is refused whoever its account is, with what each
# reaches, for the refusal.
PERSON_ONLY = {
    "controller": "the controller's settings, logs and checks",
    "controller-read": "the controller's logs",
    "nodes-write": "changing the nodes",
    "containers-read": "every project's containers",
    "settings": "a project's settings, sessions and snapshots",
    "signing": "a project's signing keys",
}


def may(u, action, project=None):
    """Whether this account may do `action`, optionally to `project`.

    Returns "" when it may, and the reason when it may not, so a caller says
    the reason rather than inventing one, and a refusal reads the same
    wherever it is made.
    """
    if u is ALL:
        return ""
    if not u:
        return "not signed in"
    # Ahead of the admin pass, because it applies to them too: a project you
    # have not taken on is read-only whoever you are. The remedy differs and
    # the sentence says so.
    if project is not None and not may_see(u, project):
        return "not a project"              # the same answer a typo gets
    # A session on a project that reads this one: every read goes through,
    # and every write is refused with the reason, which is the whole of
    # what "reads" means. `bb` is the relay, whose own door keeps the
    # relayed words to reads (bbrelay.admit).
    if project is not None and u.get("session") and project != u["session"] \
            and project in (u.get("reads") or []):
        if action in READ_ACTIONS:
            return _session_account_why(u, "read", project)
        return (f"{project} is read-only from a session on {u['session']}: it reads "
                f"{project}'s code and notebook, and a session on {project} is what changes them")
    if project is not None and not may_work(u, project):
        return ("you hold no role on this project: give yourself one on it in your "
                "settings on the Users page" if is_admin(u) else
                "you were not given this project")
    # A session may never write the house rules it is being held to. Ahead of
    # the admin pass, because the operator's OWN session carries a token with
    # the operator's uid on it. This is not a question about who somebody is
    # but about what a session is, which is the same reason is_admin refuses
    # to be talked out of `user` above.
    if action == "rules" and (u or {}).get("session"):
        return ("a session cannot change the rules it is being held to: they "
                "are the operator's, written on the notebook's Briefing tab")
    # ...nor hand out the project's files to people outside BuilderBot (R151).
    if action == "ftp" and (u or {}).get("session"):
        return "who may reach a project's files over FTP is a person's to set, not a session's"
    # ...and may not approve what it has waiting (roadmap #27): a session
    # signing off its own additions is the setting not existing.
    if action == "pending" and (u or {}).get("session"):
        return ("what a session has waiting is the operator's to approve or "
                "deny, on the notebook; a session cannot answer for itself")
    # ...nor reach what was the administrator's before the areas said who
    # may (R255 step 3): the controller, its settings and logs, the nodes,
    # every container, a project's settings, sessions and snapshots, and
    # its signing keys. A role reaches them for a person; a session's token
    # carries its account's uid, and is still a session.
    if action in PERSON_ONLY and (u or {}).get("session"):
        return f"{PERSON_ONLY[action]} is a person's, not a session's"
    # Setting up a project's file access over FTP (R152 (f)): an
    # administrator's, or the project's own owner's; who may then sign in is
    # File access on their roles, which ftp.login reads.
    if action == "ftp" and project is not None:
        import membership
        if is_admin(u) or uid_of(u) == membership.owner_of(project):
            return ""
        return "file access over FTP is set up by the project's owner or an administrator"
    # The grants (R137): what the account's roles allow, on this project
    # where one is named. The built-in roles reproduce the answers from
    # before roles existed; a role of your own says exactly what it grants.
    if roles.granted(u, action, project, may_work):
        return ""
    if action in USER_DENIES:
        # What the action is and why it is guarded, with what it needs named
        # (R255 step 2): the area and level a role gives, not "an
        # administrator's", since a role of anybody's may grant it.
        what, why = {
            "rename": ("renaming a project", ""),
            "trash": ("deleting a project", ""),
            "lock": ("locking a project", "it ends whoever's session is running there"),
            "command-pin": ("moving the pinned commands", "they are one set for everybody on this controller"),
            "version": ("moving a project's version, releasing it or changing who may",
                        "a release pushes a tag with the project's own credentials"),
            "jobs": ("running a command on a node", "a job runs outside every session's view, as the "
                     "node's own account, so it reaches everything on that machine"),
            "node": ("choosing which node a project builds on",
                     "a node is shared, so changing it reaches every project on it"),
            # The CI runner tab (R137 step 3, the operator's R136 line):
            # its status stays on the Tools card for everybody.
            "runner": ("the CI runner's settings", "its status is on the Tools card"),
            # A project this account made would not be in the list it was
            # given, so it would vanish on the next paint, and the create
            # dialog is one of the two places a git token is written.
            "create": ("making a project", "the projects you can work on are the ones you were given"),
            # The one that makes the rest of the role mean something.
            # Everything else here is enforced by this server, in Python,
            # and a shell is the way around all of it: one uid, one tmux
            # server, and Bash covered by no deny list. Without a terminal
            # there is no hole to argue about, which is why an account
            # that may not have one gets a Claude console instead of a
            # window it could point somewhere else (roadmap #27).
            "terminal": ("a shell", "your agent's session opens as a console instead"),
            "git-auth": ("how a project authenticates to its remote", "the token is what pushes, and "
                         "changing the method or clearing it reaches everybody who works on it"),
            "docker-write": ("starting and stopping containers", "you can see what is running and open it"),
            "toolchains-write": ("installing on a node", "these are gigabytes on shared disk"),
            # Named only (roles.NAMED_ONLY): an administrator too is
            # refused until a role grants it by name (the operator, 6 Oct).
            "debug": ("the debug options", "BuilderBot's owner's, or a role's that grants debug by name"),
            "ftp": ("file access over FTP", "BuilderBot's owner's, or a role's that grants ftp by name"),
        }[action]
        return f"{what} {_needs(action, project)}" + (f" ({why})" if why else "")
    if action == "admin":
        return f"that {_needs(action, None)}"
    # Everything else, for a person, is what their roles give and nothing
    # more (R152, the operator, 7 Oct: no role, no permission); it used to
    # be allowed to anybody on the project's list. A session keeps its own
    # project's work: its token carries no roles, and the project's Claude
    # may settings are what hold it.
    if not (u or {}).get("session"):
        return _roles_why(action, project)
    return _session_account_why(u, action, project if project is not None else u.get("session"))


def _needs(action, project=None):
    """What an action needs, as a refusal says it (R255 step 2): "needs
    Projects Write on alpha, which your roles do not give: an administrator
    gives it on the Users page"."""
    area, need = roles.CAP_AREA.get(action, ("projects", "write"))
    label = next((a[1] for a in roles.AREAS if a[0] == area), area)
    where = f" on {project}" if project else ""
    return (f"needs {label} {'Write' if need == 'write' else 'Read'}{where}, which your roles do not give: "
            "an administrator gives it on the Users page")


def _roles_why(action, project=None, whose="your"):
    """The refusal for an action no role gives, naming the area and level."""
    area, need = roles.CAP_AREA.get(action, ("projects", "write"))
    label = next((a[1] for a in roles.AREAS if a[0] == area), area)
    where = f" on {project}" if project else ""
    return f"{whose} roles give no {label} {'Write' if need == 'write' else 'Read'}{where}: an administrator gives one on the Users page"


def _session_account_why(u, action, project):
    """A session does no more than the account behind it (R152, the
    operator, 7 Oct): what its own rules allow, and what that account's roles
    give on the project, whichever is less. "" when the account may."""
    acct = account_of(u)
    if not acct or acct is u or not acct.get("name"):
        return ""
    if is_admin(acct) or roles.granted(acct, action, project, may_work):
        return ""
    return _roles_why(action, project, f"{acct['name']}'s") + "; a session does no more than its account"


# --- what a session gets instead of the operator's password --------------
#
# A Claude session used to inherit DASHBOARD_AUTH, which is how "only the
# operator may install a toolchain" ended up being a rule the code asked nicely
# about (bug #16). It gets one of these instead: one project, `user` rights,
# and an expiry. Whoever holds it can do what a user can do on that project
# and nothing else: no other project, no nodes, no toolchains, no accounts.
#
# Stateless, signed with a key kept in the store. That buys revocation without
# a table to keep: rotating the key invalidates every session token at once,
# which is the granularity that matters here: they are minted fresh on every
# connection, so there is nothing long-lived to revoke individually.
SESSION_PREFIX = "bbs_"
SESSION_TTL = 12 * 3600


def _session_key():
    with _lock:
        d = load()
        k = d.get("session_key")
        if not k:
            k = secrets.token_hex(32)
            d["session_key"] = k
            _save(d)
    return k.encode()


def revoke_sessions():
    """Rotate the key: every token minted before this stops verifying."""
    with _lock:
        d = load()
        d["session_key"] = secrets.token_hex(32)
        _save(d)
    return {"ok": True}


def mint_session(project, ttl=SESSION_TTL, uid=""):
    """A token for one project and, when it is for a terminal on a node,
    for one ACCOUNT: `uid` names whose session it is, which is what lets
    the node fetch that account's Claude login and nobody else's (roadmap
    #24). A token minted with no account can do what a session on the
    project can do and nothing personal."""
    exp = str(int(time.time()) + int(ttl))
    body = f"{project}|{exp}|{uid}"
    sig = hmac.new(_session_key(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return SESSION_PREFIX + base64.urlsafe_b64encode(
        f"{body}|{sig}".encode()).decode().rstrip("=")


def renewal(tok):
    """A fresh token for the same session, when this one is past half its
    life, or "" when it is not (or is not a session token at all).

    A token lasts twelve hours and a conversation does not: one that was
    minted when its tab was opened ran out overnight while the session was
    still working, and every bb verb stopped with "expired" until the tab
    was opened again. From the remote view there is no tab to open, so the
    operator ended the session. So every authenticated call from a session
    is an opportunity to renew: past the halfway mark the answer carries a
    new token for the same project and account, and bb writes it where it
    looks. A session in use never runs out; only one idle for twelve hours
    does, and that one is told what to do.

    Only a token that still VERIFIES is renewed. An expired one is not, which
    is what makes twelve hours mean something for a token that leaked.
    """
    p = session_principal(tok)
    if not p:
        return ""
    raw = str(tok)[len(SESSION_PREFIX):]
    try:
        body = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
        exp = int(body.split("|")[1])
    except (ValueError, IndexError, UnicodeDecodeError):
        return ""
    if exp - time.time() > SESSION_TTL / 2:
        return ""
    return mint_session(p["session"], uid=p.get("uid", ""))


# What a session may do to a project it reads: look, and relay the reading
# verbs (checked word by word in bbrelay.admit). Everything else is a write.
READ_ACTIONS = ("read", "bb")


def with_reads(u, reads):
    """The session principal widened to the projects its own reads: they
    join its list, so the visibility gates let them through, and `reads`
    says which they are, so the write gates refuse them by name."""
    if not u or not u.get("session"):
        return u
    reads = [r for r in (reads or []) if r and r != u["session"]]
    return {**u, "projects": list(dict.fromkeys([u["session"], key_of(u["session"]), *reads])), "reads": reads}


def session_principal(tok):
    """The account a session token stands for, or None.

    Not a stored account: a synthetic principal with `user` rights over the
    one project it was minted for. `session` marks it as one, so an audit row
    can say a session did this rather than naming a person who did not, and
    `uid` is the account it was minted for, when it was minted for one.
    """
    tok = str(tok or "")
    if not tok.startswith(SESSION_PREFIX):
        return None
    raw = tok[len(SESSION_PREFIX):]
    try:
        body = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
        parts = body.split("|")
        if len(parts) != 4:
            return None
        project, exp, uid, sig = parts
    except (ValueError, UnicodeDecodeError):
        return None
    if not exp.isdigit() or int(exp) < time.time():
        return None
    signed = f"{project}|{exp}|{uid}"
    want = hmac.new(_session_key(), signed.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, want):
        return None
    return {"name": f"session:{project}", "role": "user",
            "projects": list(dict.fromkeys([project, key_of(project)])), "session": project, "uid": uid}


# --- editing ---------------------------------------------------------------

def claim(name, password):
    """Make the owner, on a store that has none. The first-run screen's verb.

    Not `add`, which refuses the owner role on purpose: there is only ever
    one, and it is not somebody an administrator creates. This is the one path
    that makes it, and it is closed by its own result: the second call finds
    an account and refuses.
    """
    name = str(name or "").strip()
    if not NAME_RE.match(name):
        return {"error": "a name is letters, digits and . _ @ + - , up to 64"}
    if len(password or "") < 8:
        return {"error": "a password is at least 8 characters"}
    with _lock:
        d = load()
        if d["users"]:
            return {"error": "this container already has an account"}
        d["users"][name] = {"uid": mint_uid(), "role": "owner",
                            # Sees every project by role; takes each on
                            # like everybody (R135).
                            "projects": [],
                            "password": hash_password(password),
                            "created": int(time.time()), "seen": 0,
                            "prefs": {}, "pins_empty": True}
        _save(d)
    return {"ok": True, "name": name}


def add(name, password, role="user", projects=None):
    name = str(name or "").strip()
    if not NAME_RE.match(name):
        return {"error": "a name is letters, digits and . _ @ + - , up to 64"}
    if role not in ROLES or role == "owner":
        return {"error": "role must be admin or user: there is only one owner"}
    if len(password or "") < 8:
        return {"error": "a password is at least 8 characters"}
    with _lock:
        d = load()
        if name in d["users"]:
            return {"error": f"{name} already has an account"}
        d["users"][name] = {"uid": mint_uid(), "role": role,
                            # No role, so no permission, until one is given on
                            # the Roles tab (R152; admin is its own).
                            "roles": [],
                            "projects": list(projects or []),
                            "password": hash_password(password),
                            "created": int(time.time()), "seen": 0,
                            # Starts with nothing pinned, and pins what it
                            # wants (the operator, 7 Oct): see starts_unpinned.
                            "prefs": {}, "pins_empty": True}
        _save(d)
    return {"ok": True, "name": name}


def set_password(name, password):
    if len(password or "") < 8:
        return {"error": "a password is at least 8 characters"}
    with _lock:
        d = load()
        if name not in d["users"]:
            return {"error": f"no account called {name}"}
        d["users"][name]["password"] = hash_password(password)
        _save(d)
    return {"ok": True, "name": name}


def set_role(name, role):
    """Change a role, never to or from owner.

    The owner is the account every other rule is a guard rail around: it cannot
    be demoted, and nobody can be promoted into a second one. Renaming it is
    `rename`; that is the one thing about it that moves.
    """
    if role not in ROLES or role == "owner":
        return {"error": "role must be admin or user"}
    with _lock:
        d = load()
        u = d["users"].get(name)
        if not u:
            return {"error": f"no account called {name}"}
        if u.get("role") == "owner":
            return {"error": "the owner cannot be demoted"}
        u["role"] = role
        _save(d)
    return {"ok": True, "name": name, "role": role}


def set_roles(name, want):
    """The roles of your own an account carries, beside its built-in role
    (R137): names the roles store knows; the built-in one stays what
    set_role made it, so is_admin keeps meaning what it meant."""
    known = roles.all_roles()
    want = [str(r) for r in (want if isinstance(want, list) else []) if str(r) in known and str(r) not in roles.BUILTIN]
    with _lock:
        d = load()
        u = d["users"].get(name)
        if not u:
            return {"error": f"no account called {name}"}
        u["roles"] = [str(u.get("role") or "user")] + sorted(set(want))[:50]
        _save(d)
    return {"ok": True, "name": name, "roles": u["roles"]}


def set_projects(name, projects):
    with _lock:
        d = load()
        u = d["users"].get(name)
        if not u:
            return {"error": f"no account called {name}"}
        # By project (R138): a repository named stands for its project.
        u["projects"] = list(dict.fromkeys(p if p == "*" else key_of(str(p)[:120]) for p in (projects or [])))[:200]
        _save(d)
    return {"ok": True, "name": name, "projects": u["projects"]}


def migrate_star(names):
    """An owner record that carried "*" (every project, taken on by
    construction, until R135) gets the projects that exist now by name, so
    nobody is locked out of what they were on; from then on a new project
    is taken on like an administrator's. Run once at start, with the
    projects on disk. Returns how many records moved."""
    moved = 0
    with _lock:
        d = load()
        for u in d["users"].values():
            have = list(u.get("projects") or [])
            if "*" not in have:
                continue
            kept = [p for p in have if p != "*"]
            u["projects"] = (kept + [n for n in sorted(names) if n not in kept])[:200]
            moved += 1
        if moved:
            _save(d)
    return moved

def give_owner_role(project, new_uid, old_uid=""):
    """PROJECT_owner moves with the project (R152): off the account that
    owned it, onto the one that does, on that project alone."""
    project = key_of(project)
    name = roles.ensure_owner_role(project)
    with _lock:
        d = load()
        for u in d["users"].values():
            pr = u.get("project_roles") if isinstance(u.get("project_roles"), dict) else {}
            have = [r for r in pr.get(project) or [] if r != name]
            if u.get("uid") == new_uid:
                have.append(name)
                u.setdefault("projects", [])
                if project not in u["projects"]:
                    u["projects"].append(project)
            if have:
                pr[project] = have
            else:
                pr.pop(project, None)
            u["project_roles"] = pr
        _save(d)
    return name


def migrate_r152(owned):
    """Once (R152, the operator, 7 Oct): an account on `user` carries no role
    and so no permission, and each project's owner (`owned`, {project: uid},
    BuilderBot's owner's own projects left out, since it holds everything)
    holds PROJECT_owner on it. Marked done in the store."""
    with _lock:
        d = load()
        if d.get("r152"):
            return False
        for u in d["users"].values():
            if u.get("role") not in ("owner", "admin"):
                u["role"] = "user"
                u["roles"] = [r for r in (u.get("roles") or []) if r not in ("user", "owner", "admin")]
        d["r152"] = True
        _save(d)
    for project, uid in sorted((owned or {}).items()):
        if uid and uid != owner_uid():
            give_owner_role(project, uid)
    return True


def give_project_role(project, uid, role):
    """Add one role on one project to an account, which puts it on the
    project (R155): an invitation accepted."""
    with _lock:
        d = load()
        for u in d["users"].values():
            if u.get("uid") != uid:
                continue
            project = key_of(project)
            pr = u.get("project_roles") if isinstance(u.get("project_roles"), dict) else {}
            pr[project] = sorted(set((pr.get(project) or []) + [str(role)]))
            u["project_roles"] = pr
            u.setdefault("projects", [])
            if project not in u["projects"] and "*" not in u["projects"]:
                u["projects"].append(project)
        _save(d)


def migrate_r155():
    """Once (R155, the operator, 8 Oct): a role on a project is given on the
    project, never through the account's own list, and being on a project is
    holding a role there. A project role an account held through its list
    is given on each project it was on, so nobody gains or loses anything
    (an account on every project, "*", gets it on each one there is now);
    a project it was on with no role, which allowed nothing, is let go.
    BuilderBot's owner and administrators hold everything and are left as
    they are. Marked done in the store."""
    import registry
    known = roles.all_roles()
    every = sorted(registry.labels()) if registry.FILE is not None else []
    with _lock:
        d = load()
        if d.get("r155"):
            return False
        for u in d["users"].values():
            if u.get("role") in ("owner", "admin"):
                continue
            pr = u.get("project_roles") if isinstance(u.get("project_roles"), dict) else {}
            on = list(u.get("projects") or [])
            on = every if "*" in on else on
            keep = []
            for rn in u.get("roles") or []:
                r = known.get(rn)
                if r and r.get("scope") == "projects":
                    for p in on:
                        pr[p] = sorted(set((pr.get(p) or []) + [rn]))
                else:
                    keep.append(rn)
            u["roles"] = keep
            u["project_roles"] = {p: rs for p, rs in pr.items() if rs}
            u["projects"] = sorted(u["project_roles"])
        d["r155"] = True
        _save(d)
    return True


def take_on(name, project):
    """Put one project on this account's own list, the way the Users page
    does; nothing to do for an account that has it or has every project.
    What the create paths call for whoever made the project (the operator,
    24 Sep): an administrator's new project was otherwise one they had not
    taken on, read-only to them until they added it by hand."""
    with _lock:
        d = load()
        u = d["users"].get(name)
        if not u:
            return {"error": f"no account called {name}"}
        have = list(u.get("projects") or [])
        project = key_of(str(project)[:120])
        if project in have:
            return {"ok": True, "name": name, "projects": have}
        u["projects"] = (have + [project])[:200]
        _save(d)
    return {"ok": True, "name": name, "projects": u["projects"]}


def rename(name, new):
    new = str(new or "").strip()
    if not NAME_RE.match(new):
        return {"error": "a name is letters, digits and . _ @ + - , up to 64"}
    with _lock:
        d = load()
        if name not in d["users"]:
            return {"error": f"no account called {name}"}
        if new in d["users"]:
            return {"error": f"{new} already has an account"}
        d["users"][new] = d["users"].pop(name)
        _save(d)
    return {"ok": True, "name": new, "was": name}


def remove(name):
    with _lock:
        d = load()
        u = d["users"].get(name)
        if not u:
            return {"error": f"no account called {name}"}
        if u.get("role") == "owner":
            return {"error": "the owner cannot be deleted: rename it instead"}
        d["users"].pop(name)
        _save(d)
    # Its invitations go, and what it owned falls back to BuilderBot's owner.
    import membership
    membership.forget_account(u.get("uid") or "")
    return {"ok": True, "name": name}


# ---------------------------------------------------------------------------
# the Users tab's verbs, one call from the dashboard's /api/users

def own_prefs(name, want):
    """An account setting its OWN appearance, which is nobody else's
    business: the theme, and the welcome panel's two marks. (payload,
    status)."""
    if not isinstance(want, dict):
        return {"error": "prefs is an object"}, 400
    # Named, not merged wholesale. This file is read on the login path
    # and holds password hashes; an unbounded dict here would be a
    # place to park arbitrary data in it.
    keep = {}
    theme = str(want.get("theme") or "")
    if re.fullmatch(r"[a-z]{2,12}", theme):
        keep["theme"] = theme
    # Dark, light or the device's own (R216): the scheme's other half, kept
    # beside it for the same reason.
    if want.get("mode") in ("dark", "light", "system"):
        keep["mode"] = want["mode"]
    # Less motion, or what the device asks for (the operator, 19 Oct): a
    # person's own, kept beside the scheme for the same reason.
    if want.get("motion") in ("reduce", "system"):
        keep["motion"] = want["motion"]
    # The welcome panel's two marks: the getting-started guide has
    # been read, and which image's changelog was acknowledged.
    if isinstance(want.get("welcome_seen"), bool):
        keep["welcome_seen"] = want["welcome_seen"]
    if isinstance(want.get("image_seen"), str) and re.fullmatch(r"[0-9a-f]{0,40}", want["image_seen"]):
        keep["image_seen"] = want["image_seen"]
    # The tour (R94): which pages this account has toured, by their kind,
    # and whether it skips the tour on every page; both cleared by Show the
    # tours again.
    if isinstance(want.get("tour_seen"), list):
        keep["tour_seen"] = sorted({str(k) for k in want["tour_seen"][:64] if re.fullmatch(r"[a-z][a-z0-9-]{0,30}", str(k))})
    if isinstance(want.get("tour_off"), bool):
        keep["tour_off"] = want["tour_off"]
    # A terminal's look, this person's in every tab of BuilderBot's own
    # terminal (R133 step 10): its text size, cursor and colors. Named and
    # bounded, as everything here is.
    if isinstance(want.get("term"), dict):
        import prefs as project_prefs
        t, look = want["term"], {}
        if isinstance(t.get("size"), int) and 9 <= t["size"] <= 28:
            look["size"] = t["size"]
        if t.get("cursor") in ("block", "bar", "underline"):
            look["cursor"] = t["cursor"]
        if isinstance(t.get("blink"), bool):
            look["blink"] = t["blink"]
        if t.get("scheme") in project_prefs.TERM_SCHEMES:
            look["scheme"] = t["scheme"]
        keep["term"] = look
    if not keep:
        return {"error": "nothing here is a setting"}, 400
    return prefs_set(name, keep), 200


def _members_refused(name, want, may_change):
    """Why this change to `name`'s projects may not be made, or "": each
    project added or taken off is asked of may_change (membership's rule:
    an invite-only project's people are its owner's to change)."""
    if not may_change:
        return ""
    have = set((get(name) or {}).get("projects") or [])
    for p in sorted(have ^ set(want)):
        if p == "*":
            continue
        why = may_change(p)
        if why:
            return why
    return ""


def verb(act, req, seen, may_change=None):
    """One of the Users page's verbs on an account, an administrator's (the
    server holds that gate): add, a password, a role, the projects, a
    rename, the modal's one Save, remove. The store's own functions above
    hold the owner's protections. `seen()` is the projects this
    administrator sees. {ok} or {error}."""
    name = field(req, "name")
    pw = req.get("password") or ""
    if act == "add":
        for p in req.get("projects") or []:
            why = may_change(p) if may_change else ""
            if why:
                return {"error": why}
        r = add(name, pw, role=field(req, "role") or "user",
                projects=req.get("projects") or [])
        # A name and an email with it (R134), the Profile's own two fields
        # and nothing of the git identity, which is theirs to set.
        pr = req.get("profile") if isinstance(req.get("profile"), dict) else {}
        pr = {k: pr[k] for k in ("full_name", "email") if pr.get(k)}
        if not r.get("error") and pr:
            r2 = profile_set(name, pr)
            if r2.get("error"):
                r = r2
    elif act == "passwd":
        r = set_password(name, pw)
    elif act == "role":
        r = set_role(name, field(req, "role"))
    elif act == "projects":
        # Only projects this admin can see; otherwise the tab becomes a
        # way to learn what exists by handing it out.
        mine = seen()
        want = [p for p in (req.get("projects") or []) if p in mine]
        why = _members_refused(name, want, may_change)
        r = {"error": why} if why else set_projects(name, want)
    elif act == "rename":
        r = rename(name, field(req, "to"))
    elif act == "edit":
        # The Users tab's modal: everything about one account in one
        # Save. Each part is the same store function the single verbs
        # use, so the owner protections hold here too; the rename goes
        # last so every other part lands under the name it was asked for.
        r = {"ok": True, "name": name}
        if isinstance(req.get("profile"), dict) and req["profile"]:
            r = profile_set(name, req["profile"])
        if not r.get("error") and field(req, "role"):
            r = set_role(name, field(req, "role")) if (get(name) or {}).get("role") != field(req, "role") else r
        if not r.get("error") and isinstance(req.get("roles"), list):
            r = set_roles(name, req["roles"])
        if not r.get("error") and isinstance(req.get("projects"), list):
            mine = seen()
            want = [p for p in req["projects"] if p in mine]
            why = _members_refused(name, want, may_change)
            r = {"error": why} if why else set_projects(name, want)
        if not r.get("error") and pw:
            r = set_password(name, pw)
        if not r.get("error") and field(req, "to").strip() and field(req, "to").strip() != name:
            r = rename(name, field(req, "to").strip())
    elif act == "remove":
        r = remove(name)
    else:
        return {"error": "unknown action"}
    return r


def what_may(name):
    """What an account may do, said once (R255 step 5): its roles by the
    names a person reads (and where each holds), and the areas they add up
    to with the best level held anywhere, in the Roles page's order."""
    rec = get(name) or {}
    # The projects that are projects now (B75): a grant on one in the bin or
    # purged is kept, for a restore to bring back, and is not said, nor
    # counted toward what the account may do.
    import registry
    live = registry.is_project if registry.FILE is not None else (lambda _p: True)
    pr = {p: rs for p, rs in (rec.get("project_roles") or {}).items() if live(p)}
    rec = dict(rec, project_roles=pr)
    held = [roles.label(r) for r in roles.roles_of(rec) if r != "user"]
    for proj, names in sorted(pr.items()):
        own = roles.owner_role_name(proj)
        held += [f"{roles.label(r)} on {roles.shown(proj)}" for r in names if r != own]
        held += [roles.label(r) for r in names if r == own]
    got = roles.summary(rec)
    return {"roles": held,
            "may": [[label, "Write" if got[key] == "write" else "Read"]
                    for key, label, *_ in roles.AREAS if got.get(key)]}


def tab_view(me, projects, logins_of):
    """The Users page's read, an administrator's: every account with the
    Claude login each is bound to (logins_of, claudegrant's), the owner, who
    is asking, the roles, and the projects this administrator can hand
    out."""
    rows = logins_of(all_users())
    for r in rows:
        r["what_may"] = what_may(r.get("name"))
    return {"users": rows, "owner": owner_name(),
            "me": (me or {}).get("name", ""), "roles": list(ROLES),
            # The roles of your own, for the edit dialog's picker (R137).
            "role_names": [n for n in roles.all_roles() if n not in roles.BUILTIN],
            # How each role is named to a person (R255 step 1).
            "role_labels": {n: roles.label(n) for n in roles.all_roles()},
            "projects": projects}


# ---- R152: an account's roles and projects, from the Roles tab -------------

def assignable(me):
    """What `me` may change on the Roles page's top section: every project
    and Global roles for an administrator; for a project's owner who is
    not one, the projects they own, with roles on the user's projects only
    (R152 (c)). {"admin": bool, "projects": [names]}."""
    import membership
    if not me or me.get("session"):
        return {"admin": False, "projects": []}
    # Accounts and roles Write through a role of one's own is the
    # administrator's top section too (B66); assign keeps the built-in admin
    # itself an administrator's.
    if is_admin(me) or not may(me, "admin"):
        return {"admin": True, "projects": None}
    mine = uid_of(me)
    owned = sorted(p for p, r in membership._owners()["projects"].items()
                   if (r or {}).get("owner") == mine)
    return {"admin": False, "projects": owned}


def assign(me, name, global_roles=None, project_roles=None):
    """Set an account's Everywhere roles and the roles it holds on each
    project, as far as `me` may (assignable): what is outside that is kept
    as it was, never refused silently. The projects it is on follow the
    roles (R155). (payload, status)."""
    can = assignable(me)
    if not can["admin"] and not can["projects"]:
        return {"error": "the Roles page's people are an administrator's, or a project owner's for "
                         "their own projects"}, 403
    known = roles.all_roles()
    with _lock:
        d = load()
        u = d["users"].get(str(name or ""))
        if not u:
            return {"error": f"no account called {name}"}, 400
        # The owner's account is nobody's but the owner's to change (R152 (a)).
        if u.get("role") == "owner" and (me or {}).get("role") != "owner":
            return {"error": "the owner's roles and projects are the owner's alone"}, 403
        # ...and the built-in admin an administrator's, given or taken (B66).
        if not is_admin(me) and (u.get("role") == "admin"
                                 or "admin" in [str(r) for r in global_roles or []]):
            return {"error": "the admin role and an administrator's account are an administrator's to change"}, 403
        if global_roles is not None:
            if not can["admin"]:
                return {"error": "Everywhere roles are an administrator's to give"}, 403
            want = [str(r) for r in global_roles if str(r) in known and str(r) != "owner"]
            # Everywhere roles only: a role on a project is given on it (R155).
            onp = [r for r in want if r not in roles.BUILTIN and known[r].get("scope") != "global"]
            if onp:
                return {"error": f"{', '.join(onp)} {'is a role' if len(onp) == 1 else 'are roles'} "
                                 "on a project: give it on the project, under Projects"}, 400
            if "admin" in want:
                u["role"] = "admin"
            elif u.get("role") == "admin":
                u["role"] = "user"
            u["roles"] = sorted({r for r in want if r not in roles.BUILTIN})
        scope = None if can["admin"] else set(can["projects"])
        if project_roles is not None:
            pr = u.get("project_roles") if isinstance(u.get("project_roles"), dict) else {}
            for p, rs in (project_roles or {}).items():
                p = str(p)
                if scope is not None and p not in scope:
                    continue
                got = []
                for r in rs if isinstance(rs, list) else []:
                    role = known.get(str(r))
                    if not role:
                        continue
                    # A role on a project is given on it; an Everywhere
                    # one is the account's, above (R155).
                    if role.get("scope") != "projects":
                        return {"error": f"{r} holds everywhere: give it under Everywhere roles"}, 400
                    got.append(str(r))
                if got:
                    pr[p] = sorted(set(got))
                else:
                    pr.pop(p, None)
            u["project_roles"] = pr
            # On a project is holding a role there (R155): the list follows
            # the roles, kept as it was where the account has every project.
            if "*" not in (u.get("projects") or []):
                u["projects"] = sorted(p for p, rs in pr.items() if rs)
        _save(d)
        out = {k: u.get(k) for k in ("role", "roles", "projects", "project_roles")}
    return {"ok": True, "name": name, **out}, 200


def rekey(old, new):
    """Every account's list and roles that name `old` (a repository, before
    it was put in a project) name its project `new` instead (R138): what
    migration 0010 does, for a repository placed since (repos.place)."""
    with _lock:
        d = load()
        changed = False
        for u in d["users"].values():
            have = list(u.get("projects") or [])
            if old in have:
                u["projects"] = list(dict.fromkeys(new if p == old else p for p in have))
                changed = True
            pr = u.get("project_roles") if isinstance(u.get("project_roles"), dict) else {}
            if old in pr:
                was = pr.pop(old)
                pr[new] = sorted(set(pr.get(new) or []) | set(was if isinstance(was, list) else []))
                u["project_roles"] = pr
                changed = True
        if changed:
            _save(d)


def forget_project(project):
    """A project that is gone for good off every account: its list and the
    roles held on it (membership.forget_project, B95)."""
    project = str(project or "")
    with _lock:
        d = load()
        changed = False
        for u in d["users"].values():
            have = list(u.get("projects") or [])
            if project in have:
                u["projects"] = [p for p in have if p != project]
                changed = True
            pr = u.get("project_roles") if isinstance(u.get("project_roles"), dict) else {}
            if project in pr:
                pr.pop(project)
                u["project_roles"] = pr
                changed = True
        if changed:
            _save(d)


def forget_role(name):
    """A removed role taken off every account that held it, everywhere and
    on each project (B20): left on them, a role made later under the same
    name would hand them its access without anybody giving it. How many
    accounts held it."""
    n = 0
    with _lock:
        d = load()
        for u in d["users"].values():
            held = False
            if name in (u.get("roles") or []):
                u["roles"] = [r for r in u["roles"] if r != name]
                held = True
            pr = u.get("project_roles") if isinstance(u.get("project_roles"), dict) else {}
            for proj in list(pr):
                if name in (pr[proj] or []):
                    pr[proj] = [r for r in pr[proj] if r != name]
                    held = True
                    if not pr[proj]:
                        pr.pop(proj)
            if held:
                u["project_roles"] = pr
                n += 1
        if n:
            _save(d)
    return n
