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


def configure(*, state, write_json, project_prefs=None):
    globals().update(STATE=Path(state), write_json=write_json,
                     project_prefs=project_prefs)


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
    """The account's own settings, for its Profile tab: never a credential."""
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
    """Merge the Profile tab's fields: PROFILE_FIELDS only, each capped."""
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

# What a `user` may not do to a project they DO have. Named, not derived: a
# verb that should be restricted and is not listed is a decision somebody has
# to make, not something to infer from a URL.
#
# There is no "delete" here because there is no delete: a project is removed
# by moving it to the trash and purging it, and both are `trash`.
USER_DENIES = ("rename", "trash", "node", "create", "terminal", "git-auth",
               "docker-write", "toolchains-write", "jobs", "lock", "command-pin", "version")


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
        return name == u["session"]
    have = u.get("projects") or []
    return "*" in have or name in have


def visible(u, names):
    """`names`, minus what this account may not see."""
    if sees_all(u):
        return list(names)
    allow = set((u or {}).get("projects") or [])
    return [n for n in names if n in allow]


def may_see(u, name):
    return sees_all(u) or name in ((u or {}).get("projects") or [])


def is_admin(u):
    """Whether this account owns the machinery: nodes, toolchains, settings,
    other accounts. Everything that is not a project.

    A session token is never one, whatever it says: session_principal builds
    it with `user`, and this refuses to be talked out of that even if a future
    caller hands in a record claiming otherwise."""
    if (u or {}).get("session"):
        return False
    return u is ALL or (u or {}).get("role") in ("owner", "admin")


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
            return ""
        return (f"{project} is read-only from a session on {u['session']}: it reads "
                f"{project}'s code and notebook, and a session on {project} is what changes them")
    if project is not None and not may_work(u, project):
        return ("you have not taken this project on: add it to your own list "
                "on the Users tab" if is_admin(u) else
                "you were not given this project")
    # A session may never write the house rules it is being held to. Ahead of
    # the admin pass, because the operator's OWN session carries a token with
    # the operator's uid on it. This is not a question about who somebody is
    # but about what a session is, which is the same reason is_admin refuses
    # to be talked out of `user` above.
    if action == "rules" and (u or {}).get("session"):
        return ("a session cannot change the rules it is being held to: they "
                "are the operator's, written on the notebook's Briefing tab")
    # ...and may not approve what it has waiting (roadmap #27): a session
    # signing off its own additions is the setting not existing.
    if action == "pending" and (u or {}).get("session"):
        return ("what a session has waiting is the operator's to approve or "
                "deny, on the notebook; a session cannot answer for itself")
    if is_admin(u):
        return ""
    if action in USER_DENIES:
        return {"rename": "renaming a project is an administrator's",
                "trash": "deleting a project is an administrator's",
                "lock": "locking a project is an administrator's: it ends whoever's "
                        "Claude session is running there",
                "command-pin": "the pinned commands are one set for everybody on this "
                               "controller, so moving them is an administrator's",
                "version": "moving a project's version, releasing it or changing who may "
                           "is an administrator's: a release pushes a tag with the "
                           "project's own credentials",
                "jobs": "running a command on a node is an administrator's: a job "
                        "runs outside every session's view, as the node's own "
                        "account, so it reaches everything on that machine",
                "node": "which node a project builds on is an administrator's: "
                        "a node is shared, so changing it reaches every project "
                        "on it",
                # The one that makes the rest of the role mean something.
                # Everything else here is enforced by this server, in Python,
                # and a shell is the way around all of it: one uid, one tmux
                # server, and Bash covered by no deny list. Without a terminal
                # there is no hole to argue about, which is why an account
                # that may not have one gets a Claude console instead of a
                # window it could point somewhere else (roadmap #27).
                # A project this account made would not be in the list an
                # administrator gave it, so it would vanish on the next
                # paint, and the create dialog is one of the two places a
                # git token is written.
                "create": "making a project is an administrator's: the "
                          "projects you can work on are the ones you were "
                          "given",
                "terminal": "a shell is an administrator's: your Claude "
                            "session opens as a console instead",
                "git-auth": "how a project authenticates to its remote is an "
                            "administrator's: the token is what pushes, and "
                            "changing the method or clearing it reaches "
                            "everybody who works on it",
                "docker-write": "starting and stopping containers is an "
                                "administrator's: you can see what is "
                                "running and open it",
                "toolchains-write": "installing on a node is an administrator's: "
                                  "these are gigabytes on shared disk"}[action]
    if action == "admin":
        return "that is an administrator's"
    return ""


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
    return {**u, "projects": [u["session"], *reads], "reads": reads}


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
            "projects": [project], "session": project, "uid": uid}


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
                            "projects": ["*"],
                            "password": hash_password(password),
                            "created": int(time.time()), "seen": 0,
                            "prefs": {}}
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
                            "projects": list(projects or []),
                            "password": hash_password(password),
                            "created": int(time.time()), "seen": 0,
                            "prefs": {}}
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


def set_projects(name, projects):
    with _lock:
        d = load()
        u = d["users"].get(name)
        if not u:
            return {"error": f"no account called {name}"}
        u["projects"] = [str(p)[:120] for p in (projects or [])][:200]
        _save(d)
    return {"ok": True, "name": name, "projects": u["projects"]}


def take_on(name, project):
    """Put one project on this account's own list, the way the Users tab
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
        if "*" in have or project in have:
            return {"ok": True, "name": name, "projects": have}
        u["projects"] = (have + [str(project)[:120]])[:200]
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
    # The welcome panel's two marks: the getting-started guide has
    # been read, and which image's changelog was acknowledged.
    if isinstance(want.get("welcome_seen"), bool):
        keep["welcome_seen"] = want["welcome_seen"]
    if isinstance(want.get("image_seen"), str) and re.fullmatch(r"[0-9a-f]{0,40}", want["image_seen"]):
        keep["image_seen"] = want["image_seen"]
    if not keep:
        return {"error": "nothing here is a setting"}, 400
    return prefs_set(name, keep), 200


def verb(act, req, seen):
    """One of the Users tab's verbs on an account, an administrator's (the
    server holds that gate): add, a password, a role, the projects, a
    rename, the modal's one Save, remove. The store's own functions above
    hold the owner's protections. `seen()` is the projects this
    administrator sees. {ok} or {error}."""
    name = field(req, "name")
    pw = req.get("password") or ""
    if act == "add":
        r = add(name, pw, role=field(req, "role") or "user",
                projects=req.get("projects") or [])
    elif act == "passwd":
        r = set_password(name, pw)
    elif act == "role":
        r = set_role(name, field(req, "role"))
    elif act == "projects":
        # Only projects this admin can see; otherwise the tab becomes a
        # way to learn what exists by handing it out.
        mine = seen()
        r = set_projects(name, [p for p in (req.get("projects") or []) if p in mine])
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
        if not r.get("error") and isinstance(req.get("projects"), list):
            mine = seen()
            r = set_projects(name, [p for p in req["projects"] if p in mine])
        if not r.get("error") and pw:
            r = set_password(name, pw)
        if not r.get("error") and field(req, "to").strip() and field(req, "to").strip() != name:
            r = rename(name, field(req, "to").strip())
    elif act == "remove":
        r = remove(name)
    else:
        return {"error": "unknown action"}
    return r


def tab_view(me, projects, logins_of):
    """The Users tab's read, an administrator's: every account with the
    Claude login each is bound to (logins_of, claudegrant's), the owner, who
    is asking, the roles, and the projects this administrator can hand
    out."""
    return {"users": logins_of(all_users()), "owner": owner_name(),
            "me": (me or {}).get("name", ""), "roles": list(ROLES),
            "projects": projects}
