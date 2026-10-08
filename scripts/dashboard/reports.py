"""Problems with BuilderBot itself, reported by a session on any project.

A session working on somebody's app meets BuilderBot's own faults along the
way: a `bb` verb that misbehaves, a briefing that says something untrue, a
node that will not answer. Filed in that project's own tracker they were
lost to BuilderBot: the operator read them second hand, if at all, and the
session maintaining BuilderBot never saw them (the operator, 24 Sep, after
another project's session filed "bb test runs inside the container" as its
own B4). So they come here instead: `bb report "what happened"` from any
session, one store on the controller, read where BuilderBot's own work reads
the controller's state, the diagnostics (`bb diag reports`), and cleared
from Controller settings.

A log and nothing more: no report is filed, closed or answered from here,
and no session follows one up. That loop worked only where BuilderBot's own
project sits on the same controller as the sessions reporting to it, which
is this one install and no other, and a clear left sessions reading
answers to reports that were gone (the operator, 8 Oct).

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

write_json = None
FILE = None
redact = str              # diag.redact, injected
build = None              # () -> the controller's build, as a report records it
node_name = None          # project -> the name of the node it builds on, or ""
audit = None              # (principal, action, target, detail) -> the audit row

MAX_TEXT = 2000
MAX_AREA = 200
# Kept, newest last, the oldest dropped for room.
MAX_KEPT = 300
# Reports kept from one project. A session filing sixty is a session talking
# to itself, and the limit says so.
MAX_PER_PROJECT = 40


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


# How much of a reporter's conversation a report keeps: its end, where the
# problem is (the operator, 2 Oct). A whole one is often tens of megabytes.
CONVERSATION_MAX = 400 * 1024


def _files():
    return FILE.parent / "report-files"


def conversation(rid):
    """The conversation a report carries, as stored (redacted), or ""."""
    try:
        return (_files() / f"{int(rid)}.txt").read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError, TypeError):
        return ""


def _view(r):
    return {k: r.get(k) for k in ("id", "at", "project", "by", "node", "build", "text",
                                  "area", "repro", "conversation")}


def add(project, text, *, by="", node="", area="", repro="", conversation=None):
    """A new report from `project`'s session, or from a person on it; a
    person's about no project in particular has `project` "" (the header's
    Report a bug). {"ok", "id"} or {"error"}."""
    text = _clean(text, MAX_TEXT)
    if not text:
        return {"error": "say what happened: a report with no words is nothing to act on"}
    with _lock:
        d = _load()
        mine = [r for r in d["reports"] if r.get("project") == project]
        if len(mine) >= MAX_PER_PROJECT:
            return {"error": f"{project} already has {len(mine)} reports in the log: "
                             "put what is new into one of those words, or wait for them to be cleared"}
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
                             "area": _clean(area, MAX_AREA), "repro": _clean(repro, MAX_TEXT)})
        # The reporter's latest conversation on the project, when they chose
        # to send it: its end, redacted like everything else here, kept
        # beside the store and named on the report.
        if isinstance(conversation, dict) and conversation.get("text"):
            body = conversation["text"]
            cut = len(body) > CONVERSATION_MAX
            body = redact(body[-CONVERSATION_MAX:])
            if cut:
                body = "[the start is cut: this is the conversation's last part]\n" + body
            try:
                _files().mkdir(parents=True, exist_ok=True)
                (_files() / f"{rid}.txt").write_text(body, encoding="utf-8")
                d["reports"][-1]["conversation"] = {"id": str(conversation.get("id") or "")[:80],
                                                    "bytes": len(body.encode("utf-8")), "cut": cut}
            except OSError as e:
                print(f"dashboard: reports: #{rid}'s conversation was not kept: {e}", file=sys.stderr, flush=True)
        # Room is made from the oldest, its conversation with it.
        while len(d["reports"]) > MAX_KEPT:
            old = d["reports"].pop(0)
            (_files() / f"{old.get('id')}.txt").unlink(missing_ok=True)
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


def listing(project=None, n=100):
    """Reports, newest first, from one project (or all with None)."""
    out = [_view(r) for r in _load()["reports"] if project is None or r.get("project") == project]
    return out[::-1][:n]


def counts():
    """How many are kept."""
    return {"all": len(_load()["reports"])}


def clear():
    """Every report deleted, with the conversations they carry: the
    operator's Clear in Controller settings (24 Sep). The sequence is kept,
    so a report made afterwards never takes a number a bug's repro already
    names."""
    with _lock:
        d = _load()
        n = len(d["reports"])
        for r in d["reports"]:
            (_files() / f"{r.get('id')}.txt").unlink(missing_ok=True)
        write_json(FILE, {"seq": int(d.get("seq") or 0), "reports": []})
    return {"ok": True, "cleared": n}


# ---- the dashboard's verbs, one call each ------------------------------------

def _answer(r):
    return r, (400 if r.get("error") else 200)


def own_verb(act, proj, req, *, by):
    """A project's own: add a report for it, once the server has let the
    caller at the project (a session only at its own) and its Report
    BuilderBot bugs dial. (payload, status)."""
    return _answer(add(proj, req.get("text"), by=by, node=node_name(proj) if proj else "",
                       area=req.get("area"), repro=req.get("repro"),
                       conversation=req.get("_conversation")))


def diag_verb(act, req, *, by, principal):
    """Every project's reports, behind the diagnostics' own gate, since that
    is where they are read (bb diag reports): list, read one or the
    conversation it carries, count, or clear them all. (payload, status)."""
    if act == "list":
        return {"reports": listing()}, 200
    if act == "get":
        r = get(req.get("id"))
        return (r, 200) if r else ({"error": "no such report"}, 400)
    if act == "conversation":
        # The reporter's conversation a report carries (the operator, 2 Oct):
        # bb report conversation N, behind the diagnostics' gate like get.
        text = conversation(req.get("id"))
        return ({"text": text}, 200) if text else ({"error": "that report carries no conversation"}, 400)
    if act == "count":
        return counts(), 200
    if act == "clear":
        r = clear()
        audit(principal, "reports-clear", "reports", {"cleared": r["cleared"]})
        return r, 200
    return {"error": f"unknown action: {act}"}, 400
