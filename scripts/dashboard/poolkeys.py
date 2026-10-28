"""Encrypted pools (R162 step 3): the passphrase of each ZFS pool made with
native encryption on the controller's own machine, the person's choice of
where it lives: kept here, sealed under the install key as every secret
is, so the pool unlocks itself at every boot (what it protects against: a
disk pulled from the machine, or the machine's disks alone); or asked for
after every boot on the Storage page and held in this process's memory
only until the pool reports unlocked (what it protects against: the whole
machine taken, at the cost of a person at the page after each boot). The
hello hands the own machine's agent what it may load; Safe mode boots
with every pool locked, since the hello then carries nothing.
"""
import base64
import json
import os
import re
import threading
import time

STATE = None
write_json = None
seal = unseal = sealing = None
SEALED = "sealed:"
POOL_RE = re.compile(r"[a-z][a-z0-9_-]{0,30}")
PENDING_S = 900
_lock = threading.RLock()
_pending = {}              # pool -> (passphrase, until): an ask-mode key on its way to the agent


def configure(**deps):
    globals().update({k: v for k, v in deps.items() if k in globals()})
    if "state" in deps:
        globals()["STATE"] = str(deps["state"])


def _path():
    return os.path.join(STATE, "poolkeys.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("pools"), dict) else {"pools": {}}
    except (OSError, ValueError):
        return {"pools": {}}


def _save(d):
    (write_json or _write)(_path(), d)


def _write(path, data):
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _keep(v):
    if seal and sealing and sealing():
        return SEALED + base64.b64encode(seal(str(v).encode())).decode()
    return str(v)


def _open(v):
    v = str(v or "")
    if v.startswith(SEALED):
        try:
            return unseal(base64.b64decode(v[len(SEALED):])).decode() if unseal else ""
        except Exception:                                   # noqa: BLE001 (Locked, or damaged: no value)
            return ""
    return v


def ok_passphrase(p):
    return isinstance(p, str) and 8 <= len(p) <= 512 and "\n" not in p


def set_key(pool, passphrase, kept):
    """A pool's key as it is made or changed: kept here sealed, or asked
    after every boot (then handed over once, now). {ok} or {error}."""
    if not POOL_RE.fullmatch(str(pool or "")):
        return {"error": "not a pool name"}
    if not ok_passphrase(passphrase):
        return {"error": "a passphrase is 8 to 512 characters on one line"}
    with _lock:
        d = _load()
        d["pools"][pool] = {"mode": "kept" if kept else "ask", "key": _keep(passphrase) if kept else "", "set_at": int(time.time())}
        _save(d)
        if not kept:
            _pending[pool] = (passphrase, time.time() + PENDING_S)
    return {"ok": True, "pool": pool, "mode": "kept" if kept else "ask"}


def offer(pool, passphrase):
    """An ask-mode pool's passphrase typed after a boot: handed to the agent
    at its next hello and forgotten once the pool reports unlocked."""
    if not POOL_RE.fullmatch(str(pool or "")) or not ok_passphrase(passphrase):
        return {"error": "a pool and its passphrase, 8 characters at least"}
    with _lock:
        _pending[pool] = (passphrase, time.time() + PENDING_S)
    return {"ok": True, "pool": pool}


def forget(pool):
    """The key no longer kept here: asked after every boot from now on."""
    with _lock:
        d = _load()
        if pool not in d["pools"]:
            return {"error": "no key recorded for that pool"}
        d["pools"][pool] = {"mode": "ask", "key": "", "set_at": int(time.time())}
        _save(d)
        _pending.pop(pool, None)
    return {"ok": True, "pool": pool, "mode": "ask"}


def remove(pool):
    with _lock:
        d = _load()
        d["pools"].pop(pool, None)
        _save(d)
        _pending.pop(pool, None)
    return {"ok": True}


def modes():
    """{pool: mode} for the page: never a key."""
    return {p: v.get("mode", "ask") for p, v in _load()["pools"].items()}


def wanted(unlocked=(), safe_mode=False):
    """[{pool, passphrase}] for the own machine's hello: every kept key,
    and each ask-mode key offered and not yet taken; nothing in Safe mode.
    `unlocked` is what the census says is open, which clears the offers."""
    if safe_mode:
        return []
    out = []
    with _lock:
        now = time.time()
        for pool in [p for p, (_k, until) in _pending.items() if p in unlocked or until < now]:
            _pending.pop(pool, None)
        for pool, v in _load()["pools"].items():
            if v.get("mode") == "kept" and v.get("key"):
                k = _open(v["key"])
                if k:
                    out.append({"pool": pool, "passphrase": k})
        for pool, (k, _until) in _pending.items():
            if not any(x["pool"] == pool for x in out):
                out.append({"pool": pool, "passphrase": k})
    return out


def seal_all(again=False):
    if not (seal and sealing and sealing()):
        return 0
    n = 0
    with _lock:
        d = _load()
        for v in d["pools"].values():
            k = v.get("key") or ""
            if k and (again or not k.startswith(SEALED)):
                opened = _open(k)
                if opened:
                    v["key"] = _keep(opened); n += 1
        if n:
            _save(d)
    return n
