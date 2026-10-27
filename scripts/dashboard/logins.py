"""Who is signed in right now (R159): every browser sign-in as a row of its
own, made when the cookie is, touched as the cookie is used and dropped
when its browser signs out or it runs out; a device signed in as the
account (devices.py) counts the same way. The question it answers is
`live(uid)`: whether this person holds a live sign-in anywhere, which is
what their git tokens are usable while (gitcreds.helpers) and what the
Git view and bb git say when they are not.

Kept in /config/logins.json, 0600, nothing secret in it: the cookie itself
is stateless (server.make_token) and this only knows which of them were
handed out and still answer. Lost, every browser is signed out once, as a
cookie from before accounts was.
"""
import secrets
import threading
import time
from pathlib import Path

import statefile

STATE = None
DAYS = 30                    # the cookie's own life (server.SESSION_DAYS)
TOUCH_EVERY = 300            # how often a sign-in's last use is written
# A request that proved the password itself (Basic: bb from a terminal, a
# script) is a sign-in for a while after it, kept as one row per account.
BASIC_S = 900
devices_of = None            # uid -> the devices signed in as the account, set by the server
_lock = threading.Lock()


def configure(*, state, devices_of=None, days=None):
    globals().update(STATE=Path(state))
    if devices_of is not None:
        globals()["devices_of"] = devices_of
    if days:
        globals()["DAYS"] = int(days)


def _file():
    return STATE / "logins.json"


def _load():
    try:
        import json                                         # noqa: PLC0415
        d = json.loads(_file().read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _save(d):
    statefile.write_json(_file(), d, mode=0o600)


def _life(r):
    return BASIC_S if (r or {}).get("kind") == "basic" else DAYS * 86400


def _prune(d, now):
    for uid in list(d):
        rows = d.get(uid) if isinstance(d.get(uid), dict) else {}
        for lid in list(rows):
            r = rows[lid] if isinstance(rows[lid], dict) else {}
            if now - int(r.get("at") or 0) > _life(r):
                rows.pop(lid, None)
        if not rows:
            d.pop(uid, None)


def basic(uid):
    """The account proved its password on this request (Basic auth): signed
    in for BASIC_S from now, one row however many requests."""
    if not uid:
        return
    now = int(time.time())
    with _lock:
        d = _load()
        r = (d.get(uid) or {}).get("basic")
        if isinstance(r, dict) and now - int(r.get("at") or 0) < TOUCH_EVERY:
            return
        _prune(d, now)
        d.setdefault(uid, {})["basic"] = {"at": now, "last": now, "kind": "basic"}
        _save(d)


def mint(uid, where=""):
    """A new sign-in for this account: its id, which the cookie carries."""
    lid, now = secrets.token_urlsafe(9), int(time.time())
    if not uid:
        return lid
    with _lock:
        d = _load()
        _prune(d, now)
        d.setdefault(uid, {})[lid] = {"at": now, "last": now, "where": str(where or "")[:80]}
        _save(d)
    return lid


def seen(uid, lid):
    """The sign-in used just now: written at most every few minutes."""
    if not (uid and lid):
        return
    now = int(time.time())
    with _lock:
        d = _load()
        r = (d.get(uid) or {}).get(lid)
        if not isinstance(r, dict) or now - int(r.get("last") or 0) < TOUCH_EVERY:
            return
        r["last"] = now
        _save(d)


def drop(uid, lid):
    """A browser signed out: its sign-in is gone."""
    if not (uid and lid):
        return
    with _lock:
        d = _load()
        if isinstance(d.get(uid), dict) and d[uid].pop(lid, None) is not None:
            if not d[uid]:
                d.pop(uid, None)
            _save(d)


def drop_all(uid):
    """Every sign-in of the account gone: a password change, the account
    deleted, or signed out everywhere."""
    with _lock:
        d = _load()
        if d.pop(uid, None) is not None:
            _save(d)


def live(uid):
    """Whether the account holds a live sign-in now: a browser's not run
    out, or a device signed in as them."""
    if not uid:
        return False
    now = int(time.time())
    rows = _load().get(uid) or {}
    if any(isinstance(r, dict) and now - int(r.get("at") or 0) <= _life(r) for r in rows.values()):
        return True
    try:
        return bool(devices_of and devices_of(uid))
    except Exception:                                       # noqa: BLE001 (the devices table unreadable: not signed in)
        return False


def count(uid):
    """How many browsers are signed in as the account, for Profile."""
    now = int(time.time())
    return sum(1 for r in (_load().get(uid) or {}).values()
               if isinstance(r, dict) and r.get("kind") != "basic" and now - int(r.get("at") or 0) <= _life(r))
