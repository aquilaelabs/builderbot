"""Other disks and other shares on the controller's own machine (R162 step
4): a USB or eSATA disk, or a remote SMB or NFS share, mounted from the
Storage page as a backup target or a source to copy in, never pooled.
The record is the controller's (extmounts.json under the state, a share's
password sealed under the install key as every secret is), handed whole to
the own machine's root agent in its hello, which mounts what the record
says and unmounts what it no longer says (the agent's extmounts.py); the
census says what is mounted, present and how full. Eject is the record
turned off: the agent unmounts at its next hello, within a minute, and the
row says the disk is safe to pull.
"""
import base64
import json
import os
import re
import secrets
import threading
import time

STATE = None
write_json = None
seal = unseal = sealing = None
SEALED = "sealed:"
KINDS = ("disk", "smb", "nfs")
NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,30}")
HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,120}")
MAX = 32
_lock = threading.RLock()


def configure(**deps):
    globals().update({k: v for k, v in deps.items() if k in globals()})
    if "state" in deps:
        globals()["STATE"] = str(deps["state"])


def _path():
    return os.path.join(STATE, "extmounts.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("mounts"), list) else {"mounts": []}
    except (OSError, ValueError):
        return {"mounts": []}


def _save(d):
    (write_json or _write)(_path(), d)


def _write(path, data):
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
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


def clean(req, was=None):
    """A mount as the page sends it, held to its shape: {kind, name, source
    (a disk's by-id link, //host/share, host:/path), fs, user, password,
    ro, on}; (record, "") or (None, why)."""
    s = dict(was or {})
    kind = str(req.get("kind") or s.get("kind") or "")
    name = str(req.get("name") or s.get("name") or "").strip().lower()
    if kind not in KINDS:
        return None, "a mount is a disk, an SMB share or an NFS export"
    if not NAME_RE.fullmatch(name):
        return None, "a mount's name is a letter, then letters, digits and hyphens, 31 at most: it is the folder under /mnt/other"
    s.update(kind=kind, name=name, ro=req.get("ro") is True if "ro" in req else bool(s.get("ro")), on=req.get("on") is True if "on" in req else s.get("on", True))
    if kind == "disk":
        src = str(req.get("source") or s.get("source") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,118}", src):
            return None, "a disk is named by its by-id link (the Storage page's disks say it)"
        s["source"] = src
    else:
        host = str(req.get("host") or s.get("host") or "").strip()
        path = str(req.get("path") or s.get("path") or "").strip()
        if not HOST_RE.fullmatch(host):
            return None, "a remote share takes the host it is on (a name or an address)"
        if kind == "smb":
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. $-]{0,78}", path):
                return None, "an SMB share takes its share name on the host"
            user = str(req.get("user") if req.get("user") is not None else s.get("user") or "").strip()
            if user and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@\\-]{0,62}", user):
                return None, "an SMB user is a name (DOMAIN\\\\name or name@domain too)"
            s["user"] = user
            if req.get("password"):
                s["password"] = _keep(str(req["password"])[:200])
            elif "password" not in s:
                s["password"] = ""
        else:
            if not path.startswith("/") or ".." in path.split("/") or len(path) > 200:
                return None, "an NFS export takes its path on the host, from /"
        s.update(host=host, path=path)
    return s, ""


def set_mount(req):
    """Add or change one: {mount} or {error}. A name taken by another is refused."""
    with _lock:
        d = _load()
        was = next((m for m in d["mounts"] if m.get("id") == req.get("id")), None) if req.get("id") else None
        s, why = clean(req, was)
        if why:
            return {"error": why}
        if any(m.get("name") == s["name"] and m is not was for m in d["mounts"]):
            return {"error": f"{s['name']} is taken by another mount"}
        if not was:
            if len(d["mounts"]) >= MAX:
                return {"error": f"{MAX} mounts are kept, the most there may be"}
            s["id"] = "x_" + secrets.token_hex(4)
            s["made"] = int(time.time())
            d["mounts"].append(s)
        else:
            was.clear(); was.update(s)
        _save(d)
        return {"mount": _row(s)}


def remove(mid):
    with _lock:
        d = _load()
        before = len(d["mounts"])
        d["mounts"] = [m for m in d["mounts"] if m.get("id") != mid]
        if len(d["mounts"]) == before:
            return {"error": "no such mount"}
        _save(d)
        return {"ok": True}


def turn(mid, on):
    """Mounted or unmounted (Eject): the agent follows at its next hello."""
    with _lock:
        d = _load()
        m = next((m for m in d["mounts"] if m.get("id") == mid), None)
        if not m:
            return {"error": "no such mount"}
        m["on"] = on is True
        _save(d)
        return {"mount": _row(m)}


def _row(m):
    return {k: m.get(k) for k in ("id", "kind", "name", "source", "host", "path", "user", "ro", "on", "made") if k in m} | {"password_set": bool(m.get("password"))}


def rows():
    """The record for the page: never a password."""
    return [_row(m) for m in _load()["mounts"]]


def wanted():
    """The record for the own machine's hello, the passwords opened: what
    the agent mounts and unmounts."""
    out = []
    for m in _load()["mounts"]:
        r = {k: m.get(k) for k in ("id", "kind", "name", "source", "host", "path", "user", "ro", "on") if k in m}
        if m.get("kind") == "smb":
            r["password"] = _open(m.get("password"))
        out.append(r)
    return out


def seal_all(again=False):
    """After the install key changed, or once there is one: every password sealed."""
    if not (seal and sealing and sealing()):
        return 0
    n = 0
    with _lock:
        d = _load()
        for m in d["mounts"]:
            v = m.get("password") or ""
            if v and (again or not v.startswith(SEALED)):
                opened = _open(v)
                if opened:
                    m["password"] = _keep(opened); n += 1
        if n:
            _save(d)
    return n
