"""Problems with BuilderBot itself, reported by a session on any project.

A session working on somebody's app meets BuilderBot's own faults along the
way: a `bb` verb that misbehaves, a briefing that says something untrue, a
node that will not answer. Filed in that project's own tracker they were
lost to BuilderBot: the operator read them second hand, if at all, and the
session maintaining BuilderBot never saw them (the operator, 24 Sep, after
another project's session filed "bb test runs inside the container" as its
own B4). So they come here instead: `bb report "what happened"` from any
session, one store on the controller, read where BuilderBot's own work reads
the controller's state, the diagnostics (`bb diag reports`), and turned
into a bug in BuilderBot's tracker or closed from there (`bb report file N`,
`bb report close N "why"`). The session that reported one reads what became
of its project's reports with `bb report`.

Everything a report says goes through the diagnostics' redaction before it
is stored: a session pasting an error line pastes whatever was in it.
"""

import json
import os
import sys
import time
from pathlib import Path

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import statefile  # noqa: E402
from fields import field  # noqa: E402

write_json = None
FILE = None
redact = str              # diag.redact, injected
build = None              # () -> the controller's build, as a report records it
node_name = None          # project -> the name of the node it builds on, or ""
audit = None              # (principal, action, target, detail) -> the audit row

STATES = ("open", "filed", "closed")
MAX_TEXT = 2000
MAX_AREA = 200
# Kept, newest last. What is still open is never dropped for room: the
# oldest filed or closed ones go first.
MAX_KEPT = 300
# Open reports from one project. A session filing sixty is a session talking
# to itself, and the limit says so.
MAX_OPEN_PER_PROJECT = 40


def configure(*, write_json, state, redact=None, build=None):
    globals().update(write_json=write_json, FILE=Path(state) / "reports.json")
    if redact is not None:
        globals()["redact"] = redact
    if build is not None:
        globals()["build"] = build


_lock = statefile.on(lambda: FILE)


def _load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("reports"), list):
            return d
    except (OSError, ValueError):
        pass
    return {"seq": 0, "reports": []}


def _clean(text, n):
    return redact(" ".join(str(text or "").split()))[:n]


def _view(r):
    return {k: r.get(k) for k in ("id", "at", "project", "by", "node", "build", "text",
                                  "area", "repro", "state", "bug", "why", "done_at", "done_by")}


def add(project, text, *, by="", node="", area="", repro=""):
    """A new report from `project`'s session, or from a person on it; a
    person's about no project in particular has `project` "" (the header's
    Report a bug). {"ok", "id"} or {"error"}."""
    text = _clean(text, MAX_TEXT)
    if not text:
        return {"error": "say what happened: a report with no words is nothing to act on"}
    with _lock:
        d = _load()
        mine = [r for r in d["reports"] if r.get("project") == project and r.get("state") == "open"]
        if len(mine) >= MAX_OPEN_PER_PROJECT:
            return {"error": f"{project} already has {len(mine)} reports nobody has read: "
                             "wait for those to be looked at"}
        d["seq"] = int(d.get("seq") or 0) + 1
        rid = d["seq"]
        try:
            made = build() if build else ""
        except Exception as e:                                    # noqa: BLE001 (the caller's callback; a stamp never stops a report)
            made = ""
            print(f"dashboard: reports: no build stamp for #{rid}: {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
        d["reports"].append({"id": rid, "at": int(time.time()), "project": str(project)[:100],
                             "by": str(by or "")[:100], "node": str(node or "")[:100],
                             "build": str(made or "")[:80], "text": text,
                             "area": _clean(area, MAX_AREA), "repro": _clean(repro, MAX_TEXT),
                             "state": "open"})
        # Room is made from what is finished, oldest first.
        while len(d["reports"]) > MAX_KEPT:
            done = next((i for i, r in enumerate(d["reports"]) if r.get("state") != "open"), None)
            if done is None:
                break
            d["reports"].pop(done)
        write_json(FILE, d)
    return {"ok": True, "id": rid}


def get(rid):
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return None
    for r in _load()["reports"]:
        if r.get("id") == rid:
            return _view(r)
    return None


def listing(state="open", project=None, n=100):
    """Reports, newest first: in one state (or all with None), from one
    project (or all with None)."""
    out = [_view(r) for r in _load()["reports"]
           if (state is None or r.get("state") == state)
           and (project is None or r.get("project") == project)]
    return out[::-1][:n]


def _finish(rid, state, *, by="", bug="", why=""):
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return {"error": "not a report"}
    with _lock:
        d = _load()
        r = next((x for x in d["reports"] if x.get("id") == rid), None)
        if r is None:
            return {"error": f"no report #{rid}"}
        if r.get("state") != "open":
            return {"error": f"report #{rid} is already {r.get('state')}"
                             + (f" as {r['bug']}" if r.get("bug") else "")}
        r.update(state=state, done_at=int(time.time()), done_by=str(by or "")[:100])
        if bug:
            r["bug"] = str(bug)[:40]
        if why:
            r["why"] = _clean(why, MAX_AREA)
        write_json(FILE, d)
    return {"ok": True, "id": rid, "state": state}


def filed(rid, bug, by=""):
    """Report `rid` became `bug` in BuilderBot's tracker."""
    if not str(bug or "").strip():
        return {"error": "which bug it became is the point of filing it"}
    return _finish(rid, "filed", by=by, bug=str(bug).strip())


def close(rid, why, by=""):
    """Report `rid` needs nothing: a duplicate, the project's own fault, fixed already."""
    if not str(why or "").strip():
        return {"error": "say why it is closed: the session that reported it reads this"}
    return _finish(rid, "closed", by=by, why=why)


def counts():
    """How many are kept, and how many of those nobody has filed or closed."""
    rs = _load()["reports"]
    return {"all": len(rs), "open": sum(1 for r in rs if r.get("state") == "open")}


def clear():
    """Every report deleted, open ones included: the operator's Clear in
    Controller settings (24 Sep). The sequence is kept, so a report made
    afterwards never takes a number a bug's repro already names."""
    with _lock:
        d = _load()
        n = len(d["reports"])
        # What each project loses, kept as a count and a time, so its
        # session is told its reports were cleared rather than that it
        # never made any (B343): "no reports" after three acknowledged
        # ones read as a fault in the listing.
        gone = d.get("cleared") if isinstance(d.get("cleared"), dict) else {}
        now = int(time.time())
        for r in d["reports"]:
            k = str(r.get("project") or "")
            was = gone.get(k) or {"n": 0, "at": 0}
            gone[k] = {"n": int(was.get("n") or 0) + 1, "at": now}
        d["reports"] = []
        d["cleared"] = gone
        write_json(FILE, d)
    return {"ok": True, "cleared": n}


# ---- the dashboard's verbs, one call each ------------------------------------

def _answer(r):
    return r, (400 if r.get("error") else 200)


def own_verb(act, proj, req, *, by):
    """A project's own: add a report for it, or read what became of its
    reports, once the server has let the caller at the project (a session
    only at its own) and, for an add, its Report BuilderBot bugs dial.
    (payload, status)."""
    if act == "mine":
        # What became of each: open, filed, or closed with the words the
        # close addressed to it. Not the bug it became, which is a number in
        # BuilderBot's own tracker, nor who filed it: a session sees nothing
        # of another project's notebook, and two reports filed as one bug
        # would show that tracker's triage (B317).
        gone = (_load().get("cleared") or {}).get(str(proj)) if proj else None
        return {"reports": [{k: v for k, v in r.items() if k not in ("bug", "done_by")}
                            for r in listing(None, proj, n=30)],
                # ...and the ones the operator cleared, as a count and when,
                # so an emptied list is not read as one that never filled.
                "cleared": gone if isinstance(gone, dict) and gone.get("n") else None}, 200
    return _answer(add(proj, req.get("text"), by=by, node=node_name(proj) if proj else "",
                       area=req.get("area"), repro=req.get("repro")))


def diag_verb(act, req, *, by, principal):
    """Every project's reports, behind the diagnostics' own gate, since that
    is where BuilderBot's own work reads them (bb diag reports): list, read
    one, file one as a bug, close one, count, or clear them all. (payload,
    status)."""
    if act == "list":
        st = field(req, "state") or "open"
        return {"reports": listing(None if st == "all" else st)}, 200
    if act == "get":
        r = get(req.get("id"))
        return (r, 200) if r else ({"error": "no such report"}, 400)
    if act == "filed":
        return _answer(filed(req.get("id"), field(req, "bug"), by=by))
    if act == "close":
        return _answer(close(req.get("id"), field(req, "why"), by=by))
    if act == "count":
        return counts(), 200
    if act == "clear":
        r = clear()
        audit(principal, "reports-clear", "reports", {"cleared": r["cleared"]})
        return r, 200
    return {"error": f"unknown action: {act}"}, 400
