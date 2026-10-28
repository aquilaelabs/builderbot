"""Backups off the machine (R162 step 5): the record of what the
controller's own machine copies where (a pool, the array or the
controller's state to the array, a disk or a share under /mnt/other), how
many runs to keep, each a row on the Storage page with Run now and a
schedule (the Schedules page's row, a system job on the own machine), its
last run from the census and on Home. The record goes to the own machine's
agent in its hello; the job names a row and the agent does the copy
(backups.py there, rsync with hard links between runs).
"""
import json
import os
import re
import secrets
import threading
import time

STATE = None
write_json = None
NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,30}")
ROOTS = ("/mnt/", "/srv/", "/var/lib/builderbot-controller")
MAX = 32
STALE_S = 2 * 86400
_lock = threading.RLock()


def configure(*, state, write_json=None):
    globals()["STATE"] = str(state)
    globals()["write_json"] = write_json or _write


def _write(path, data):
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def _path():
    return os.path.join(STATE, "storebackups.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("backups"), list) else {"backups": []}
    except (OSError, ValueError):
        return {"backups": []}


def _save(d):
    write_json(_path(), d)


def _path_ok(p):
    return os.path.isabs(p) and p.startswith(ROOTS) and ".." not in p.split("/") and len(p) <= 200 and re.fullmatch(r"[\w./ +-]+", p)


def clean(req, was=None):
    s = dict(was or {})
    name = str(req.get("name") or s.get("name") or "").strip().lower()
    if not NAME_RE.fullmatch(name):
        return None, "a backup's name is a letter, then letters, digits and hyphens, 31 at most: it is the folder its runs go under"
    src = str(req.get("source") or s.get("source") or "").strip().rstrip("/") or "/"
    dest = str(req.get("dest") or s.get("dest") or "").strip().rstrip("/") or "/"
    if not _path_ok(src) or not _path_ok(dest):
        return None, "a source and a destination are folders under /mnt (a pool, the array, another disk or share) or the controller's state"
    if src == dest or dest.startswith(src + "/") or src.startswith(dest + "/"):
        return None, "a backup goes somewhere other than inside its source"
    try:
        keep = int(req.get("keep") if req.get("keep") is not None else s.get("keep", 7))
    except (TypeError, ValueError):
        keep = 0
    if not 1 <= keep <= 365:
        return None, "a backup keeps 1 to 365 runs"
    s.update(name=name, source=src, dest=dest, keep=keep, on=req.get("on") is True if "on" in req else s.get("on", True))
    return s, ""


def set_backup(req):
    with _lock:
        d = _load()
        was = next((b for b in d["backups"] if b.get("id") == req.get("id")), None) if req.get("id") else None
        s, why = clean(req, was)
        if why:
            return {"error": why}
        if any(b.get("name") == s["name"] and b is not was for b in d["backups"]):
            return {"error": f"{s['name']} is taken by another backup"}
        if not was:
            if len(d["backups"]) >= MAX:
                return {"error": f"{MAX} backups are kept, the most there may be"}
            s["id"] = "b_" + secrets.token_hex(4)
            s["made"] = int(time.time())
            d["backups"].append(s)
        else:
            was.clear(); was.update(s)
        _save(d)
        return {"backup": dict(s)}


def remove(bid):
    with _lock:
        d = _load()
        before = len(d["backups"])
        d["backups"] = [b for b in d["backups"] if b.get("id") != bid]
        if len(d["backups"]) == before:
            return {"error": "no such backup"}
        _save(d)
        return {"ok": True}


def rows():
    return [dict(b) for b in _load()["backups"]]


def get(name):
    return next((dict(b) for b in _load()["backups"] if b.get("name") == name), None)


def wanted():
    """The record for the own machine's hello: what the job may be asked to run."""
    return [{k: b.get(k) for k in ("id", "name", "source", "dest", "keep")} for b in _load()["backups"]]


def summary(census_rows, scheduled_names=(), now=None):
    """For Home and the bell: {count, failed, stale, oldest_ok_at} from the
    census's last runs; a backup is stale when scheduled and its last good
    run is older than STALE_S, or it never ran."""
    now = now or time.time()
    by = {r.get("name"): r for r in census_rows or [] if isinstance(r, dict)}
    recs = _load()["backups"]
    failed = [b["name"] for b in recs if (by.get(b["name"]) or {}).get("last_at") and not (by.get(b["name"]) or {}).get("ok")]
    stale = [b["name"] for b in recs if b["name"] in scheduled_names and not failed.count(b["name"])
             and (not (by.get(b["name"]) or {}).get("last_at") or now - (by.get(b["name"]) or {}).get("last_at", 0) > STALE_S)]
    oks = [r["last_at"] for r in by.values() if r.get("ok") and r.get("last_at")]
    return {"count": len(recs), "failed": failed, "stale": stale, "oldest_ok_at": min(oks) if oks and len(oks) == len(recs) else 0,
            "newest_ok_at": max(oks) if oks else 0}
