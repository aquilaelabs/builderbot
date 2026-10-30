"""An unlock that gives up less (R158 step 5), and a key of the person's
own (R157).

What the controller holds of a person's key store, and for how long:

  * a token is opened per use, for the time the person picks (Profile,
    Your key store: a quarter of an hour, an hour, eight hours, or while
    they are signed in), and the opened line is what the controller keeps,
    in memory; the entry's seal is opened again after that, not before;
  * each use is logged where the person reads it (Profile): when, which
    token, on which project, for what (a push, a fetch, CI watching, a
    release) and by whom (them, their session, or nobody's work);
  * a store under a key of the person's own (accountkeys "own": a passkey's
    PRF output, or a key they keep themselves) is opened only while they
    have unlocked it: the account key is then here in memory until the
    window ends or they press Lock, and nothing of theirs opens without it;
    a store under the install key has no unlock to ask for, so its window
    bounds how long an opened token stays here.

Git is handed an opened token through a handout file (handout): one line
in RUN_DIR/<who>/<project>, 0600, written when a token is used and shredded
when the window ends, the store is locked, or the person signs out
everywhere, so git-credential-bb opens nothing itself for a person's token.
"""
import base64
import contextlib
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

import statefile

STATE = None
RUN_DIR = Path("/run/bb-git")
DEFAULT_FOR = 3600
CHOICES = (900, 3600, 28800, 0)              # 0: while signed in
USES_KEEP = 200
OWN_INFO = b"builderbot own key v1|"
_lock = threading.RLock()
# {uid: {"key": bytes or None, "until": t (0: while signed in), "tokens": {fid: {"line", "until"}}}}
_open = {}
# Set by configure(): the account key under the install key, an entry
# opened with a key, the "own" record of an account, whether a person is
# signed in anywhere, and ts() for the X25519 arithmetic.
key_under_install = None
open_entry = None
entry_of = None
own_of = None
set_for = None
live = None
ts = None
wipe = None


def configure(**deps):
    globals().update({k: v for k, v in deps.items() if k in globals() or k in ("STATE",)})
    if "state" in deps:
        globals()["STATE"] = Path(deps["state"])
    if "run_dir" in deps and deps["run_dir"]:
        globals()["RUN_DIR"] = Path(deps["run_dir"])


# ---- the window ------------------------------------------------------------

def unlock_for(uid):
    """The person's pick (seconds; 0 while signed in), DEFAULT_FOR until
    they pick."""
    r = (entry_of(uid) if entry_of else None) or {}
    v = r.get("unlock_for")
    return int(v) if isinstance(v, int) and v in CHOICES else DEFAULT_FOR


def _until(uid):
    f = unlock_for(uid)
    return 0 if f == 0 else int(time.time()) + f


def _live(uid):
    """Whether the person is signed in anywhere (logins.live unless the
    server gave another answer)."""
    try:
        if live:
            return bool(live(uid))
        import logins                                           # noqa: PLC0415
        return bool(logins.live(uid))
    except Exception:                                           # noqa: BLE001
        return False


def _ts():
    if ts:
        return ts()
    import tokenkeys                                            # noqa: PLC0415
    return tokenkeys.ts()


def _wipe(b):
    if wipe:
        return wipe(b)
    import hardening                                            # noqa: PLC0415
    return hardening.wipe(b)


def _expired(uid, until):
    return (int(time.time()) > until) if until else not _live(uid)


def _row(uid):
    r = _open.get(uid)
    if r and _expired(uid, r["until"]):
        lock(uid, why="the window ended" if r["until"] else "signed out everywhere")
        return None
    return r


def is_own(uid):
    return bool(own_of and own_of(uid))


def opened_key(uid):
    """The account key, for an account under a key of its own: while
    unlocked, else None. accountkeys.key_of asks here."""
    with _lock:
        r = _row(uid)
        return bytes(r["key"]) if r and r.get("key") else None


def locked(uid):
    """Whether the account's store is shut: an own-key account with no
    window open. One under the install key is never locked."""
    if not is_own(uid):
        return False
    with _lock:
        return not (_row(uid) and _row(uid).get("key"))


def _secret_to_private(secret, uid):
    """The X25519 private half a person's secret stands for (a passkey's
    PRF output, or the key they keep), derived so the secret itself is
    never the key."""
    from cryptography.hazmat.primitives import hashes            # noqa: PLC0415
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF     # noqa: PLC0415
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=OWN_INFO + str(uid).encode()).derive(bytes(secret))


def public_of(secret, uid):
    """The public half (hex) the controller keeps for a person's secret."""
    return _ts().public(_secret_to_private(secret, uid))


def seal_to(secret_or_pub, uid, key):
    """The account key sealed to the person's public half: what the entry
    keeps; opened by open_with_secret."""
    pub = secret_or_pub if isinstance(secret_or_pub, str) else public_of(secret_or_pub, uid)
    return base64.b64encode(_ts().seal(pub, bytes(key), {"for": "account key", "uid": uid})).decode()


def open_with_secret(sealed_b64, secret, uid):
    """The account key out of its own-key seal, or None when the secret is
    not the one it was sealed to."""
    t = _ts()
    try:
        blob = base64.b64decode(sealed_b64)
        R = t.header(blob).get("R", "")
        return t.open_with(t.key_for(_secret_to_private(secret, uid), R), blob)
    except (t.Refused, ValueError, KeyError, TypeError):
        return None


def unlock(uid, secret=None, for_s=None):
    """The store opened for the window: with the person's secret for an
    own-key account (refused when it is not theirs), nothing to give for
    one under the install key. {ok, until, for} or {error}."""
    if not _live(uid) and for_s == 0:
        return {"error": "while signed in needs a sign-in: this request proved a password, which lasts a quarter of an hour"}
    with _lock:
        if is_own(uid):
            own = own_of(uid) or {}
            if secret is None:
                return {"error": "this store is under a key of your own: your passkey, or the key you keep, opens it"}
            k = open_with_secret(own.get("sealed", ""), secret, uid)
            if k is None:
                return {"error": "that is not the key this store is under"}
        else:
            k = None
        if for_s is not None and for_s in CHOICES:
            _set_for(uid, for_s)
        until = _until(uid)
        r = _open.get(uid) or {"tokens": {}}
        if r.get("key"):
            _wipe(r["key"])
        r["key"], r["until"] = (bytearray(k) if k else None), until
        _open[uid] = r
    _use(uid, "", "", "", "unlocked", "")
    return {"ok": True, "until": until, "for": unlock_for(uid)}


def _set_for(uid, for_s):
    if set_for:
        set_for(uid, for_s)


def lock(uid, why="locked"):
    """Everything opened of the account let go and zeroed, the handouts
    shredded."""
    with _lock:
        r = _open.pop(uid, None)
        if r:
            if r.get("key"):
                _wipe(r["key"])
            for t in r.get("tokens", {}).values():
                t["line"] = ""
        _handouts_gone(uid)
    if r:
        _use(uid, "", "", "", why, "")
    return {"ok": True}


def status(uid):
    """What Profile and the page show: {own, locked, until, for, how}."""
    own = own_of(uid) if own_of else None
    with _lock:
        r = _row(uid)
    return {"own": bool(own), "how": (own or {}).get("how", ""), "passkey": (own or {}).get("passkey", ""),
            "locked": locked(uid), "until": int(r["until"]) if r else 0, "for": unlock_for(uid),
            "open_tokens": len([t for t in (r or {}).get("tokens", {}).values() if t.get("line")]) if r else 0}


# ---- a token, opened per use -------------------------------------------------

def token(uid, fid, why="", project="", by="", host="", login=""):
    """The opened line of the account's entry `fid`, for `why` on
    `project`, logged; "" when the store is locked or the entry is not
    theirs. Kept opened for the window, so the seal is opened once per
    window rather than per use."""
    if not uid or not fid:
        return ""
    with _lock:
        r = _row(uid)
        if is_own(uid) and not (r and r.get("key")):
            return ""
        t = (r or {}).get("tokens", {}).get(fid) if r else None
        if t and t.get("line") and not _expired(uid, t["until"]):
            line = t["line"]
        else:
            k = bytes(r["key"]) if r and r.get("key") else (key_under_install(uid) if key_under_install else None)
            if not k:
                return ""
            line = open_entry(uid, fid, k) if open_entry else ""
            if not line:
                return ""
            if r is None:
                r = _open[uid] = {"key": None, "until": _until(uid), "tokens": {}}
            r["tokens"][fid] = {"line": line, "until": _until(uid)}
    _use(uid, fid, host, login, why, project, by)
    return line


def forget_token(uid, fid):
    """The opened line of `uid`'s entry `fid` let go: its token was replaced
    or dropped, so the next use opens what the store holds now."""
    with _lock:
        t = ((_open.get(uid) or {}).get("tokens") or {}).pop(str(fid), None)
    if t and wipe and isinstance(t.get("line"), (bytes, bytearray)):
        wipe(t["line"])


def handout(uid, project, fid, why="", by="", host="", login=""):
    """The path git's helper reads the opened token from, for `project`:
    RUN_DIR/<uid>/<project>, written now from token(), or "" when there is
    nothing to hand out."""
    line = token(uid, fid, why, project, by, host, login)
    if not line:
        return ""
    d = _run_dir() / uid
    try:
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(d, 0o700)
        p = d / project
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(line + "\n")
        return str(p)
    except OSError:
        return ""


def _run_dir():
    d = RUN_DIR
    try:
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(d, 0o700)
        return d
    except OSError:
        d = STATE / "handouts"
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(d, 0o700)
        return d


def _shred(p):
    with contextlib.suppress(OSError):
        n = os.path.getsize(p)
        with open(p, "r+b") as f:
            f.write(b"\0" * n)
    with contextlib.suppress(OSError):
        os.unlink(p)


def _handouts_gone(uid):
    for base in (RUN_DIR, (STATE / "handouts") if STATE else None):
        d = base / uid if base else None
        if d and d.is_dir():
            for p in d.iterdir():
                _shred(p)
            with contextlib.suppress(OSError):
                d.rmdir()


def sweep():
    """Every window run out closed: called from the server's slow loop, so
    a handout does not outlive its window by more than a minute."""
    with _lock:
        for uid in list(_open):
            _row(uid)


def clear_all_handouts():
    """At a start: nothing handed out before this process is a token still
    on disk."""
    for base in (RUN_DIR, (STATE / "handouts") if STATE else None):
        if base and base.is_dir():
            for d in base.iterdir():
                if d.is_dir():
                    for p in d.iterdir():
                        _shred(p)
                    with contextlib.suppress(OSError):
                        d.rmdir()


# ---- the uses, where the person reads them -----------------------------------

def _uses_file():
    return STATE / "token-uses.json"


def _use(uid, fid, host, login, why, project, by=""):
    if not STATE:
        return
    row = {"at": int(time.time()), "fid": str(fid or "")[:24], "host": str(host or "")[:80], "login": str(login or "")[:80],
           "why": str(why or "")[:40], "project": str(project or "")[:120], "by": str(by or "")[:80]}
    with _lock:
        try:
            d = json.loads(_uses_file().read_text())
            d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            d = {}
        rows = [r for r in (d.get(uid) or []) if isinstance(r, dict)]
        rows.insert(0, row)
        d[uid] = rows[:USES_KEEP]
        with contextlib.suppress(OSError):
            statefile.write_json(_uses_file(), d, mode=0o600)


def uses(uid, n=50):
    """The account's last uses, newest first."""
    try:
        d = json.loads(_uses_file().read_text())
    except (OSError, ValueError):
        return []
    return [r for r in ((d.get(uid) if isinstance(d, dict) else None) or []) if isinstance(r, dict)][:n]


def forget(uid):
    """An account removed, or its store purged: nothing opened, no uses."""
    lock(uid, why="purged")
    with _lock:
        try:
            d = json.loads(_uses_file().read_text())
            if isinstance(d, dict) and d.pop(uid, None) is not None:
                statefile.write_json(_uses_file(), d, mode=0o600)
        except (OSError, ValueError):
            pass


def new_secret():
    """A key a person keeps themselves (64 hex), shown once."""
    return secrets.token_hex(32)


def secret_from_hex(text):
    t = str(text or "").strip().replace(" ", "")
    if len(t) != 64:
        return None
    try:
        return bytes.fromhex(t)
    except ValueError:
        return None


def prf_salt(uid):
    """The salt the page hands the passkey's PRF: fixed per account, so the
    same passkey gives the same secret every time."""
    return base64.urlsafe_b64encode(hashlib.sha256(OWN_INFO + str(uid).encode()).digest()).decode().rstrip("=")
