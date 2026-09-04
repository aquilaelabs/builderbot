"""Who may sign in to the DASHBOARD, and what they are allowed to see.

Not signin.py, which is the flow for signing in to Claude. Adjacent names,
unrelated jobs: that one hands a code to `claude auth login`, this one decides
whether the person at the browser gets a page at all.

The design is docs/users.md; this is step 1 of roadmap #22 and deliberately
enforces nothing. It replaces one string comparison — `DASHBOARD_AUTH` — with a
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
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

STATE = Path("/config")
write_json = None
_lock = threading.RLock()

ROLES = ("owner", "admin", "user")
# 600k is the OWASP floor for pbkdf2-sha256 at the time of writing. It costs
# about a fifth of a second here, which is the right price for a login and the
# wrong one for anything on a poll — nothing calls this per request.
ITERATIONS = 600_000
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,63}$")


def configure(*, state, write_json):
    globals().update(STATE=Path(state), write_json=write_json)


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

def load():
    try:
        d = json.loads(_file().read_text())
    except (OSError, ValueError):
        return {"users": {}}
    return d if isinstance(d.get("users"), dict) else {"users": {}}


def _save(d):
    write_json(_file(), d)
    # The file holds password hashes. write_json does not know that, so the
    # mode is set here rather than assumed — and tolerated when it fails,
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
        out.append({"name": name, "role": u.get("role", "user"),
                    "projects": list(u.get("projects") or []),
                    "created": u.get("created", 0), "seen": u.get("seen", 0)})
    return out


def get(name):
    u = load()["users"].get(str(name))
    return {**u, "name": str(name)} if u else None


def owner_name():
    for name, u in load()["users"].items():
        if u.get("role") == "owner":
            return name
    return ""


# --- seeding, once ---------------------------------------------------------

def seed(auth):
    """Make the owner from DASHBOARD_AUTH, on a boot that finds no store.

    Once. After this the file is the truth and the variable is ignored, which
    is the unhardwiring pattern the node path mapping used — and it matters
    that it stops being honoured: a credential that keeps working forever is a
    back door rather than a migration.

    Returns what happened, for the boot log to say.
    """
    with _lock:
        d = load()
        if d["users"]:
            return {"seeded": False, "why": "the store already has accounts"}
        name, _, password = str(auth or "").partition(":")
        if not name or not password:
            return {"seeded": False, "why": "DASHBOARD_AUTH is not user:password"}
        if not NAME_RE.match(name):
            return {"seeded": False, "why": f"{name!r} is not a usable account name"}
        d["users"][name] = {"role": "owner", "projects": ["*"],
                            "password": hash_password(password),
                            "created": int(time.time()), "seen": 0}
        _save(d)
    return {"seeded": True, "name": name}


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
# credential, and the account's stamp with it — so changing a password drops
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
    """Record that this account was just used. Best effort — a failed write
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
    changes it, so every cookie issued against the old one stops verifying —
    which is how a stateless token gets revocation without a table to keep.
    """
    return hashlib.sha256(str((u or {}).get("password", "")).encode()).hexdigest()[:16]


# --- editing ---------------------------------------------------------------

def add(name, password, role="user", projects=None):
    name = str(name or "").strip()
    if not NAME_RE.match(name):
        return {"error": "a name is letters, digits and . _ @ + - , up to 64"}
    if role not in ROLES or role == "owner":
        return {"error": "role must be admin or user — there is only one owner"}
    if len(password or "") < 8:
        return {"error": "a password is at least 8 characters"}
    with _lock:
        d = load()
        if name in d["users"]:
            return {"error": f"{name} already has an account"}
        d["users"][name] = {"role": role, "projects": list(projects or []),
                            "password": hash_password(password),
                            "created": int(time.time()), "seen": 0}
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
    """Change a role — never to or from owner.

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
            return {"error": "the owner cannot be deleted — rename it instead"}
        d["users"].pop(name)
        _save(d)
    return {"ok": True, "name": name}
