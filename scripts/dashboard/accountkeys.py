"""Each account's own key, for its coding agents' sign-ins sealed on the
nodes (R154; the operator, 27 Oct: made per account and kept by the
controller, sealed under the install key).

An account's key pair on a node is derived from this key rather than from
the install key (tokenkeys.py), so changing the install key leaves every
sign-in on the nodes as it is, and an account changes its own from its
Profile. A change keeps the one before it while a node still holds a
sign-in sealed under it: the node opens that one with the old key the next
time its person opens a terminal there, and seals it again under the new.

  STATE/account-keys.json  {uid: {"key": sealed, "prev": sealed, "made": t,
                            "changed": t}}, each key 32 bytes sealed under
                            the install key; nothing here opens without it
"""
import base64
import contextlib
import hashlib
import json
import re
import secrets
import threading
import time

import signing
import statefile

STATE = None
_lock = threading.Lock()
# Set by configure(): (uid, key) -> how many sign-ins on the nodes are still
# sealed under that account key (tokenkeys).
on_nodes = None


def configure(*, state, nodes_under=None):
    globals().update(STATE=state, on_nodes=nodes_under)


def _file():
    return STATE / "account-keys.json"


def _load():
    try:
        d = json.loads(_file().read_text())
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def _save(d):
    statefile.write_json(_file(), d, mode=0o600)


def _open(v):
    try:
        return signing.unseal(base64.b64decode(v)) if v else None
    except (signing.Locked, ValueError):
        return None


def _keep(k):
    return base64.b64encode(signing.seal(k)).decode()


def key_of(uid, make=True):
    """The account's key, made the first time it is asked for, or None with
    no install key (nothing is sealed then) or a uid that is not one."""
    if signing.MASTER is None or not re.fullmatch(r"u_[0-9a-f]{8}", str(uid or "")):
        return None
    r = _load().get(uid) or {}
    k = _open(r.get("key"))
    if k or not make:
        return k
    with _lock:
        d = _load()
        r = d.get(uid) or {}
        k = _open(r.get("key"))
        if k:
            return k
        k = secrets.token_bytes(32)
        now = int(time.time())
        d[uid] = {"key": _keep(k), "made": now, "changed": now}
        with contextlib.suppress(OSError):
            _save(d)
            return k
    return None


def previous_of(uid):
    """The one before the account's key, while a change keeps it."""
    return _open((_load().get(uid) or {}).get("prev"))


def fingerprint(k):
    h = hashlib.sha256(b"builderbot account key fingerprint\0" + k).hexdigest()[:8]
    return f"{h[:4]} {h[4:]}"


def _drop_previous(uid):
    prev = previous_of(uid)
    if not prev or (on_nodes and on_nodes(uid, prev)):
        return False
    with _lock:
        d = _load()
        if (d.get(uid) or {}).pop("prev", None) is not None:
            _save(d)
    return True


def status(uid):
    """What Profile shows of the account's key: nothing that opens anything."""
    k = key_of(uid, make=False)
    if not k:
        return {"has": False, "sealing": signing.MASTER is not None}
    _drop_previous(uid)
    r = _load().get(uid) or {}
    prev = previous_of(uid)
    return {"has": True, "sealing": True, "fingerprint": fingerprint(k), "made": r.get("made", 0),
            "changed": r.get("changed", 0), "previous": bool(prev),
            "previous_on_nodes": int(on_nodes(uid, prev) if prev and on_nodes else 0)}


KEY_RE = re.compile(r"[0-9a-fA-F]{64}")


def change(uid, new=""):
    """A new key for the account, made or pasted (64 hex characters); the one
    before kept while the nodes still hold sign-ins sealed under it."""
    if signing.MASTER is None:
        return {"error": "this install has no key, so no sign-in is sealed on the nodes"}, 409
    new = (new or "").strip()
    if new and not KEY_RE.fullmatch(new):
        return {"error": "an account key is 64 hex characters"}, 400
    old = key_of(uid)
    if old is None:
        return {"error": "no such account"}, 404
    if previous_of(uid) and not _drop_previous(uid):
        n = on_nodes(uid, previous_of(uid)) if on_nodes else 0
        return {"error": f"the key before this one still opens {n} of your sign-in{'' if n == 1 else 's'} on the nodes: "
                         "each moves to today's key when you next open a terminal there"}, 409
    k = bytes.fromhex(new) if new else secrets.token_bytes(32)
    if k == old:
        return {"error": "that is today's key"}, 400
    with _lock:
        d = _load()
        r = d.get(uid) or {}
        r.update(key=_keep(k), prev=_keep(old), changed=int(time.time()))
        d[uid] = r
        _save(d)
    _drop_previous(uid)
    return {"ok": True, "fingerprint": fingerprint(k)}, 200


def seal_all(again=False):
    """With `again`, after the install key changed: every account's keys
    sealed once more, under today's install key. Returns how many."""
    if signing.MASTER is None or not again:
        return 0
    n = 0
    with _lock:
        d = _load()
        for r in d.values():
            for slot in ("key", "prev"):
                k = _open(r.get(slot)) if isinstance(r, dict) else None
                if k:
                    r[slot] = _keep(k)
                    n += 1
        if n:
            _save(d)
    return n


def forget(uid):
    """An account removed: its keys go with it."""
    with _lock:
        d = _load()
        if d.pop(uid, None) is not None:
            with contextlib.suppress(OSError):
                _save(d)

