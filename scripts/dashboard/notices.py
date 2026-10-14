"""What the page has said to each account, kept (R218 step 6, the design's
the-dashboard/notifications rule). A toast says a thing for a few seconds
to whoever was looking; every one is also written here, so a failure you
were not at the screen for is still there to read on the Notifications
page, on every browser the account opens, until it is deleted or cleared.

One file per account under <state>/notices/, newest first, capped: a log
that grew without end would make the page that reads it slow and the file
that holds it large, and what is old enough to fall off the end is long
acted on. Each entry: id, at (epoch seconds), kind ("said" for what the
page said about a press, "ask" for an answer to an ask, "job" for how a
followed job ended), level ("info", "warn", "bad") and the text, with an
optional job id or link the page can open again.
"""
import json
import re
import threading
import time
from pathlib import Path

DIR = None                   # <state>/notices, set by configure()
write_json = None
_lock = threading.Lock()
CAP = 300
KINDS = ("said", "ask", "job")
LEVELS = ("info", "warn", "bad")


def configure(*, state, write_json):
    globals().update(DIR=Path(state) / "notices", write_json=write_json)


def _file(uid):
    # The account id's own shape, nothing else, since it names a file.
    return DIR / f"{uid}.json" if re.fullmatch(r"u_[0-9a-f]{8}", str(uid or "")) else None


def _load(uid):
    f = _file(uid)
    if not f:
        return []
    try:
        v = json.loads(f.read_text())
        return v if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def _save(uid, rows):
    DIR.mkdir(parents=True, exist_ok=True)
    write_json(_file(uid), rows[:CAP])


def listing(uid):
    """The account's notices, newest first. (payload, status)."""
    if not _file(uid):
        return {"error": "notices are kept for an account, and this request has none"}, 400
    return {"notices": _load(uid), "cap": CAP}, 200


def act(uid, req):
    """add, delete (one by id) or clear (all, or one kind). (payload, status)."""
    if not _file(uid):
        return {"error": "notices are kept for an account, and this request has none"}, 400
    action = str(req.get("action") or "")
    with _lock:
        rows = _load(uid)
        if action == "add":
            items = req.get("items") if isinstance(req.get("items"), list) else [req]
            added = []
            for it in items[:20]:
                text = str((it or {}).get("text") or "").strip()[:600]
                if not text:
                    continue
                row = {"id": f"n{time.time_ns():x}{len(added)}", "at": int(time.time()),
                       "kind": it.get("kind") if it.get("kind") in KINDS else "said",
                       "level": it.get("level") if it.get("level") in LEVELS else "info", "text": text}
                if re.fullmatch(r"j_[0-9a-f]+", str(it.get("job") or "")):
                    row["job"] = it["job"]
                added.append(row)
            if not added:
                return {"error": "nothing to keep: a notice needs its text"}, 400
            _save(uid, list(reversed(added)) + rows)
            return {"ok": True, "added": len(added)}, 200
        if action == "delete":
            ids = req.get("ids") if isinstance(req.get("ids"), list) else [req.get("id")]
            keep = [r for r in rows if r.get("id") not in set(map(str, ids))]
            _save(uid, keep)
            return {"ok": True, "deleted": len(rows) - len(keep)}, 200
        if action == "clear":
            kind = req.get("kind")
            keep = [r for r in rows if kind in KINDS and r.get("kind") != kind]
            _save(uid, keep)
            return {"ok": True, "cleared": len(rows) - len(keep)}, 200
    return {"error": f"no such action: {action or '(none)'}"}, 400
