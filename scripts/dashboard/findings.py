#!/usr/bin/env python3
"""What the scanner used to say, so a finding that goes away leaves a trace.

The other three notebook views keep a log because somebody *did* something —
a step reworded, a bug closed, a memory written. Nothing here is written by
anyone: the scan runs on the host, the container gets a read-only report, and
between two runs a finding can simply stop being in it. Fixed, or the file
went, or a rule changed on the host, or the scanner never reached that project
— the report cannot tell those apart and neither can this. What it can say is
*it was here on the 3rd and it is not here now*, which is the question worth
answering and had no answer at all before.

So this log is derived rather than recorded: each read of the report is
compared against the last one, and the difference is the entry.

**What counts as the same finding.** (rule, path) within a project —
deliberately not the line. Line numbers move whenever anything is inserted
above them, so a key including the line turns one edit into a gone-and-found
pair for every finding below it, and a log full of that is a log nobody reads.
The cost is that three hits of one rule in one file are one row here; when
that count changes the entry says so rather than pretending something new
appeared.

**The first read of a project seeds silently.** Logging everything as "found"
on the day this was added would stamp a discovery date on findings older than
the feature, and a confidently wrong date is worse than none.

**An empty report is not the same as a clean one.** If a project is absent
from the scan entirely — the scanner failed, or never covered it — every
finding it had would read as fixed. That is exactly the SARIF trap the rest of
this project is careful about, so `seen()` is told whether the project was
actually covered, and a project that was not covered is left alone.
"""
import json
import threading
import time
from pathlib import Path

write_json = None
STATE = None
FILE = None

def configure(*, write_json, state):
    globals().update(write_json=write_json, STATE=Path(state))
    globals()["FILE"] = Path(state) / "findings-log.json"


_lock = threading.Lock()

# Room for a working record, the same as the roadmap's and the tracker's. A
# weekly scan over a handful of projects will not reach this; a rule that
# flickers on and off would, and the cap is what stops it pushing everything
# else out of the file.
MAX_HISTORY = 300


def load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("projects"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"projects": {}}


def save(d):
    write_json(FILE, d)


def _key(row):
    """(rule, path) — see the module docstring for why the line is left out."""
    return "\t".join([str(row.get("rule") or ""), str(row.get("path") or "")])


def _digest(rows):
    """The current report for one project, as {key: {what the log needs}}."""
    out = {}
    for r in rows:
        k = _key(r)
        cur = out.get(k)
        if cur is None:
            out[k] = {"rule": r.get("rule") or "", "path": r.get("path") or "",
                      "level": r.get("level") or "warning",
                      "desc": (r.get("desc") or "")[:200], "n": 1}
        else:
            cur["n"] += 1
            # The worst level a file has for this rule is the one worth
            # keeping: a note beside an error should not read as a note.
            if _RANK.get(r.get("level"), 1) > _RANK.get(cur["level"], 1):
                cur["level"] = r.get("level") or cur["level"]
    return out


_RANK = {"note": 0, "warning": 1, "error": 2}


def seen(project, rows, covered=True):
    """Compare this read against the last, and log what changed.

    `covered` is whether the scan actually looked at this project. A report
    that simply does not mention it says nothing about its findings, and
    treating that as "everything was fixed" is the exact SARIF mistake this
    project refuses to make elsewhere — so it returns without touching
    anything.

    Returns the number of entries written, which is zero on the overwhelming
    majority of calls: this runs on every read of the report, and the report
    changes weekly.
    """
    if not covered:
        return 0
    now = _digest(rows)
    with _lock:
        d = load()
        p = d["projects"].setdefault(project, {})
        was = p.get("seen")
        if was is None:
            # First sight of this project: take the snapshot, write no
            # history. See the module docstring.
            p["seen"] = now
            save(d)
            return 0
        events = []
        at = int(time.time())
        for k, cur in now.items():
            old = was.get(k)
            if old is None:
                events.append({"at": at, "act": "found", **_row(cur)})
            elif old.get("n") != cur.get("n") or old.get("level") != cur.get("level"):
                events.append({"at": at, "act": "changed", **_row(cur),
                               "was": f"{old.get('n', 1)} x {old.get('level', '?')}"})
        for k, old in was.items():
            if k not in now:
                events.append({"at": at, "act": "gone", **_row(old)})
        if not events:
            return 0
        h = d.setdefault("history", {}).setdefault(project, [])
        h.extend(events)
        del h[:-MAX_HISTORY]
        p["seen"] = now
        save(d)
    return len(events)


def _row(v):
    return {"rule": v.get("rule", ""), "path": v.get("path", ""),
            "level": v.get("level", "warning"), "desc": v.get("desc", ""),
            "n": v.get("n", 1)}


def history(project, limit=None, since=None, find=None):
    """What the scanner has stopped and started saying here, newest first.

    The same three filters the roadmap's and the tracker's logs take, narrowed
    here rather than by the caller for the same reason: the reader that matters
    most is a session, and a log dumped whole costs more context than the one
    line wanted from it.
    """
    with _lock:
        h = load().get("history", {}).get(project) or []
    out = sorted(h, key=lambda e: -e.get("at", 0))
    if since is not None:
        # An absolute epoch, the same as the roadmap's and the tracker's take.
        # Both callers already compute it — the CLI from a day count or a
        # date, the panel from its dropdown — and having one of the four logs
        # mean something different by the same argument is a trap.
        cut = _int(since)
        if cut is not None:
            out = [e for e in out if e.get("at", 0) >= cut]
    if find:
        needle = str(find).lower()
        out = [e for e in out
               if needle in " ".join([str(e.get("rule", "")), str(e.get("path", "")),
                                      str(e.get("desc", "")), str(e.get("act", "")),
                                      str(e.get("level", ""))]).lower()]
    n = _int(limit)
    out = out if n in (None, 0) else out[:n]
    # Shaped like the other three logs — at / act / text / note / by — so the
    # same pane renders it and the same eye reads it. `by` is empty on
    # purpose: nobody here did this, which is the one honest thing to say
    # about a finding that stopped being reported.
    return [{"at": e.get("at", 0), "act": e.get("act", "changed"),
             "text": e.get("path") or "(no path)",
             "by": "",
             "note": " · ".join(x for x in [
                 e.get("level", ""),
                 e.get("rule", ""),
                 f"x{e['n']}" if e.get("n", 1) > 1 else "",
                 f"was {e['was']}" if e.get("was") else "",
             ] if x)}
            for e in out]


def revisions():
    """{project: how many things have happened to its findings}.

    The poll's cheap way to notice the log moved, the same shape the tracker
    uses — one read of the file for every project rather than one each.
    """
    with _lock:
        h = load().get("history", {})
    return {p: len(rows) for p, rows in h.items()}


def _int(v):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
