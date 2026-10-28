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
                            the install key; nothing here opens without it.
                            An account under a key of its own (R157) has
                            "own" in place of "key": {"pub": the X25519
                            public half of what the person holds (a
                            passkey's PRF output, or a key they keep),
                            "sealed": the account key sealed to it, "how",
                            "passkey", "since"}, so the account key opens
                            only while they have unlocked it (unlocks.py);
                            "pubs" remembers each node's public halves, so
                            a node seals a login while the store is shut;
                            "unlock_for" is their window
  STATE/account-secrets.json  {uid: {"forges": {id: {"host", "sealed",
                            "login", "scheme", "at"}}}}: the account's key
                            store, each forge token it gave a repository
                            sealed under its own key (the operator, 27 Oct),
                            any number for one host (a fine-grained token is
                            often one repository's), sealed again when that
                            key changes; a project links to one by its id and
                            its git work uses it (gitcreds)
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
import unlocks

STATE = None
_lock = threading.RLock()
# Set by configure(): (uid, key) -> how many sign-ins on the nodes are still
# sealed under that account key (tokenkeys).
on_nodes = None


def configure(*, state, nodes_under=None):
    globals().update(STATE=state, on_nodes=nodes_under)
    # The unlock (unlocks.py) reads this store through these; the server
    # adds who is signed in, the arithmetic and the wipe.
    unlocks.configure(state=state, key_under_install=key_under_install, open_entry=open_entry_with,
                      entry_of=_entry, own_of=own_of, set_for=set_unlock_for)


def _file():
    return STATE / "account-keys.json"


def _secrets_file():
    return STATE / "account-secrets.json"


def _load_secrets():
    try:
        d = json.loads(_secrets_file().read_text())
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


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


def _entry(uid):
    return _load().get(uid) or {}


def own_of(uid):
    """The "own" record of an account under a key of its own (R157), or
    None for one under the install key."""
    r = _entry(uid).get("own")
    return r if isinstance(r, dict) and r.get("sealed") else None


def key_under_install(uid):
    """The account's key out of its seal under the install key, for
    unlocks: None for an account under a key of its own."""
    if signing.MASTER is None or not re.fullmatch(r"u_[0-9a-f]{8}", str(uid or "")):
        return None
    return _open(_entry(uid).get("key"))


def key_of(uid, make=True):
    """The account's key, made the first time it is asked for, or None with
    no install key (nothing is sealed then) or a uid that is not one. For
    an account under a key of its own (R157): the key while they have
    unlocked their store, else None."""
    if signing.MASTER is None or not re.fullmatch(r"u_[0-9a-f]{8}", str(uid or "")):
        return None
    r = _entry(uid)
    if own_of(uid):
        return unlocks.opened_key(uid)
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
    """What Profile shows of the account's key: nothing that opens anything.
    An own-key account's fingerprint is kept with its record, so it is
    shown while the store is locked too."""
    r = _load().get(uid) or {}
    own = own_of(uid)
    k = key_of(uid, make=False)
    if not k and not own:
        return {"has": False, "sealing": signing.MASTER is not None, **unlocks.status(uid)}
    _drop_previous(uid)
    prev = previous_of(uid)
    return {"has": True, "sealing": True, "fingerprint": fingerprint(k) if k else str(own.get("fingerprint") or ""),
            "made": r.get("made", 0),
            "changed": r.get("changed", 0), "previous": bool(prev),
            "previous_on_nodes": int(on_nodes(uid, prev) if prev and on_nodes else 0),
            **unlocks.status(uid)}


def set_unlock_for(uid, for_s):
    """The person's unlock window kept with their key record."""
    if for_s not in unlocks.CHOICES:
        return False
    with _lock:
        d = _load()
        d.setdefault(uid, {})["unlock_for"] = int(for_s)
        _save(d)
    return True


def remember_pub(uid, node, old, pub):
    """A node's public half for this account, kept so the node is handed
    it while the store is shut (tokenkeys.public)."""
    with _lock:
        d = _load()
        r = d.setdefault(uid, {})
        ps = r.setdefault("pubs", {})
        slot = ps.setdefault(str(node), {})
        key = "v1" if old else "v2"
        if slot.get(key) != pub:
            slot[key] = pub
            with contextlib.suppress(OSError):
                _save(d)


def pub_remembered(uid, node, old):
    return str(((_entry(uid).get("pubs") or {}).get(str(node)) or {}).get("v1" if old else "v2") or "")


def move_to_own(uid, secret, how, passkey=""):
    """The store moved under a key the person holds (R157 step 1): the
    account key, opened now, sealed to the public half of `secret` and the
    seal under the install key dropped; the window opens at once. Refused
    while the key before is still on the nodes, since both would have to
    move."""
    if signing.MASTER is None:
        return {"error": "this install has no key, so there is no key store to move"}, 409
    k = key_of(uid)
    if k is None:
        return {"error": "your store is locked: unlock it first, then move it" if own_of(uid) else "no such account"}, 409
    if previous_of(uid) and not _drop_previous(uid):
        return {"error": "the key before this one still opens sign-ins on the nodes: open a terminal there first, "
                         "and each moves to today's key"}, 409
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < 16:
        return {"error": "the secret is not one"}, 400
    pub = unlocks.public_of(secret, uid)
    with _lock:
        d = _load()
        r = d.get(uid) or {}
        r["own"] = {"pub": pub, "sealed": unlocks.seal_to(pub, uid, k), "how": "passkey" if how == "passkey" else "key",
                    "passkey": str(passkey or "")[:120], "since": int(time.time()), "fingerprint": fingerprint(k)}
        r.pop("key", None)
        r.pop("prev", None)
        d[uid] = r
        _save(d)
    unlocks.lock(uid, why="moved under your own key")
    got = unlocks.unlock(uid, secret)
    return {"ok": True, "fingerprint": fingerprint(k), "unlocked": bool(got.get("ok"))}, 200


def move_back(uid):
    """The store given back to this BuilderBot's install key, while it is
    unlocked: its key sealed under the install key again, the own record
    gone."""
    own = own_of(uid)
    if not own:
        return {"error": "your store is under this BuilderBot's key already"}, 400
    k = unlocks.opened_key(uid)
    if k is None:
        return {"error": "your store is locked: unlock it, then give the key back"}, 409
    with _lock:
        d = _load()
        r = d.get(uid) or {}
        r["key"] = _keep(k)
        r.pop("own", None)
        d[uid] = r
        _save(d)
    unlocks.lock(uid, why="given back to this BuilderBot")
    return {"ok": True, "fingerprint": fingerprint(k)}, 200


KEY_RE = re.compile(r"[0-9a-fA-F]{64}")


def change(uid, new=""):
    """A new key for the account, made or pasted (64 hex characters); the one
    before kept while the nodes still hold sign-ins sealed under it."""
    if signing.MASTER is None:
        return {"error": "this install has no key, so no sign-in is sealed on the nodes"}, 409
    new = (new or "").strip()
    if new and not KEY_RE.fullmatch(new):
        return {"error": "an account key is 64 hex characters"}, 400
    if own_of(uid):
        return {"error": "your store is under a key of your own: give it back to this BuilderBot first, or change what you hold"}, 409
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
        # The key store sealed again under the new key at once: only the
        # nodes' seals wait for a terminal to move them.
        sd = _load_secrets()
        for f in ((sd.get(uid) or {}).get("forges") or {}).values():
            with contextlib.suppress(signing.Locked, ValueError):
                f["sealed"] = base64.b64encode(signing.seal(signing.open_with(old, base64.b64decode(f["sealed"])), k)).decode()
        if uid in sd:
            statefile.write_json(_secrets_file(), sd, mode=0o600)
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
    """An account removed: its keys and its key store go with it."""
    unlocks.forget(uid)
    with _lock:
        d = _load()
        if d.pop(uid, None) is not None:
            with contextlib.suppress(OSError):
                _save(d)
        sd = _load_secrets()
        if sd.pop(uid, None) is not None:
            with contextlib.suppress(OSError):
                statefile.write_json(_secrets_file(), sd, mode=0o600)


# ---- the account's key store: the forge tokens it gave -------------------
# An entry's id names it for good; one written before ids (keyed by its
# host) keeps its host as its id.

def _entries(uid, sd=None):
    fs = ((sd if sd is not None else _load_secrets()).get(uid) or {}).get("forges") or {}
    return {fid: dict(f, host=f.get("host") or fid) for fid, f in fs.items() if isinstance(f, dict)}


def forges_of(uid):
    """What the account keeps, newest first, with no token: [{id, host,
    login, scheme, at}]."""
    rows = [{"id": fid, "host": f["host"], "login": f.get("login", ""), "scheme": f.get("scheme", "https"),
             "at": f.get("at", 0)} for fid, f in _entries(uid).items()]
    return sorted(rows, key=lambda r: -int(r["at"] or 0))


def _open_entry(k, f):
    try:
        return signing.open_with(k, base64.b64decode(f["sealed"])).decode()
    except (signing.Locked, ValueError, KeyError):
        return ""


def link_forge(uid, host, line, login):
    """A forge token the account gave, as git's credential line
    (scheme://user:token@host), sealed under the account's own key; the same
    token given twice is one entry. ({ok, id, host, login}, status)."""
    k = key_of(uid)
    if not k:
        return {"error": "this install has no key, so nothing can be kept in an account's key store"}, 409
    host = str(host).lower()
    with _lock:
        sd = _load_secrets()
        for fid, f in _entries(uid, sd).items():
            if f["host"] == host and _open_entry(k, f) == line:
                return {"ok": True, "id": fid, "host": host, "login": f.get("login", "")}, 200
        fid = secrets.token_hex(6)
        sd.setdefault(uid, {}).setdefault("forges", {})[fid] = {
            "host": host, "sealed": base64.b64encode(signing.seal(line.encode(), k)).decode(),
            "login": login, "scheme": line.split("://", 1)[0], "at": int(time.time())}
        statefile.write_json(_secrets_file(), sd, mode=0o600)
    return {"ok": True, "id": fid, "host": host, "login": login}, 200


def unlink_forge(uid, fid):
    with _lock:
        sd = _load_secrets()
        fs = (sd.get(uid) or {}).get("forges") or {}
        if fs.pop(str(fid), None) is None:
            return False
        statefile.write_json(_secrets_file(), sd, mode=0o600)
    return True


def entry_for(uid, fid="", host=""):
    """The entry `fid`, or the newest for `host`, with no token; None."""
    es = _entries(uid)
    f = es.get(str(fid)) if fid else next((e for e in sorted(es.values(), key=lambda e: -int(e.get("at") or 0))
                                           if e["host"] == str(host or "").lower()), None)
    if not f:
        return None
    fid = str(fid) if fid else next(i for i, e in es.items() if e is f)
    return {"id": fid, "host": f["host"], "login": f.get("login", "")}


def open_entry_with(uid, fid, k):
    """One entry opened with the account key `k`: unlocks' way in."""
    f = _entries(uid).get(str(fid))
    return _open_entry(k, f) if f and k else ""


def forge_line(uid, fid="", host="", why="", project="", by=""):
    """The account's credential line, opened per use through unlocks
    (R158 step 5): the entry `fid`, or its newest for `host`; "" for none,
    or while the store is locked."""
    e = entry_for(uid, fid, host)
    if not e:
        return ""
    return unlocks.token(uid, e["id"], why=why, project=project, by=by, host=e["host"], login=e["login"])


def forge_of(uid, fid):
    """One entry, with no token, or None."""
    f = _entries(uid).get(str(fid))
    return {"id": str(fid), "host": f["host"], "login": f.get("login", "")} if f else None
