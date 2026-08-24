#!/usr/bin/env python3
"""Everything behind the notebook's bug tracker.

The roadmap is for design work — things somebody decided to build. A bug is a
different kind of record: nobody decided it, it has a place it lives and a way
to make it happen, and "done" means fixed rather than delivered. Mixing the two
in one list meant every bug was worded as a task and lost the fields a session
actually needs to act on it — where it is, how to reproduce it, and the gap
between what should happen and what does.

So bugs get their own file and their own shape. Either side writes them: the
operator reports one from the notebook's Bugs tab, a session through `bb bug`
when it trips over something out of scope for what it is on — the same reason
the roadmap exists, applied to defects.

A bug that turns out to be real is *closed*, not deleted — fixed or wontfix,
each with a note saying why — because a closed bug is the record that stops
the same report being investigated twice. Deleting exists for the other case,
which the first version of this file did not admit to: a report that should
never have been filed. A session mis-files one, a duplicate goes in twice,
somebody reports the wrong project. Closing those as "wontfix" lies about
them, and leaving them on the list is the noise a tracker is supposed to
remove. So a delete takes the row and leaves the reason in the log.

Same arrangement as todo.py: the server or the bb CLI hands over write_json
and the state directory; nothing here reaches back.
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
    globals()["FILE"] = Path(state) / "bugs.json"


_lock = threading.Lock()

SEVERITIES = ("low", "medium", "high", "critical")
# The ways a bug leaves the open list. "na" is for one that was real and
# stopped applying — the feature it was about was removed, the screen it lived
# on is gone — which is neither fixed (nobody fixed it) nor wontfix (it was
# not a decision to leave it). Saying either of those about it misleads
# whoever reads the tracker next.
STATUSES = ("open", "fixed", "wontfix", "na")

# What each looks like where there is room for a sentence.
STATUS_WORDS = {"open": "open", "fixed": "fixed", "wontfix": "won't fix",
                "na": "not applicable"}

# One line each; the two long fields get room for real repro steps and a real
# analysis. Capped so a paste cannot turn the tracker into a log file.
MAX_SHORT = 300
MAX_LONG = 4000
MAX_BUGS = 200

# What a report may carry besides its title. Fixed here, once: the CLI, the
# HTTP handler and the editor all consult this list rather than each keeping
# their own idea of what a bug is.
FIELDS = ("area", "repro", "expected", "actual", "notes")


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


def _int(v):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _clean(text, limit):
    """Trim a field: whitespace tidied, blank runs collapsed, capped.

    Interior newlines survive — repro steps and an analysis are written across
    lines on purpose — the same rule the roadmap's text follows.
    """
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(ln.split()) for ln in text.split("\n")]
    out = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)[:limit]


# Every change to the tracker, kept — the same reason the roadmap keeps its
# log: two people write this, and the tracker itself only shows the present
# tense. Capped per project alongside the bugs it describes.
MAX_HISTORY = 300


def _log(d, project, by, ev):
    h = d.setdefault("history", {}).setdefault(project, [])
    h.append({"at": int(time.time()),
              "by": "claude" if by == "claude" else "you", **ev})
    del h[:-MAX_HISTORY]


def history(project, limit=None, since=None, find=None):
    """What has happened to the tracker, newest first, optionally narrowed —
    the same filters the roadmap's log takes, because whoever learned one
    should not have to learn the other."""
    with _lock:
        h = load().get("history", {}).get(project) or []
    out = sorted(h, key=lambda e: -e.get("at", 0))
    if since is not None:
        cut = _int(since)
        if cut is not None:
            out = [e for e in out if e.get("at", 0) >= cut]
    if find:
        needle = str(find).lower()
        out = [e for e in out
               if any(needle in str(e.get(k, "")).lower()
                      for k in ("text", "note", "act"))]
    n = _int(limit)
    if n is not None and n > 0:
        out = out[:n]
    return out


def payload(project):
    """The Bugs tab's whole answer: open first, newest first within a group.

    Sorted on the way out rather than stored sorted, because the stored order
    is the record of when things were reported and a status flip should not
    rewrite the file's shape.
    """
    with _lock:
        rows = list(load()["projects"].get(project) or [])
    rows.sort(key=lambda b: (b.get("status") != "open", -b.get("at", 0)))
    return {"project": project, "bugs": rows}


def counts():
    """{project: open bugs} — one read for every project row."""
    with _lock:
        d = load()
    return {p: sum(1 for b in rows if b.get("status") == "open")
            for p, rows in d["projects"].items()}


def add(project, title, by="you", severity="medium", **fields):
    title = _clean(title, MAX_SHORT).replace("\n", " ")
    if not title:
        return {"error": "a bug needs a title — one line, what goes wrong"}
    if severity not in SEVERITIES:
        return {"error": f"severity is one of: {', '.join(SEVERITIES)}"}
    with _lock:
        d = load()
        rows = d["projects"].setdefault(project, [])
        if len(rows) >= MAX_BUGS:
            return {"error": f"{MAX_BUGS} bugs is the limit — close some, or "
                             "this stops being a tracker and starts being a log"}
        bug = {"id": max((int(b.get("id", 0)) for b in rows), default=0) + 1,
               "title": title, "severity": severity, "status": "open",
               "by": "claude" if by == "claude" else "you",
               "at": int(time.time())}
        for k in FIELDS:
            v = _clean(fields.get(k), MAX_LONG if k in ("repro", "notes")
                       else MAX_SHORT)
            if v:
                bug[k] = v
        rows.append(bug)
        _log(d, project, by, {"act": "filed", "id": bug["id"], "text": title,
                              "note": bug.get("severity", "")})
        save(d)
    return {"ok": True, "bug": bug}


def _edit(project, bug_id, change, by="you"):
    bug_id = _int(bug_id)
    if bug_id is None:
        return {"error": "not a bug number"}
    with _lock:
        d = load()
        rows = d["projects"].get(project) or []
        bug = next((b for b in rows if _int(b.get("id")) == bug_id), None)
        if bug is None:
            return {"error": f"no bug #{bug_id} here"}
        out = change(bug)
        ev = out.pop("log", None) if isinstance(out, dict) else None
        if not out.get("error"):
            if ev:
                _log(d, project, by, ev)
            bug["updated"] = int(time.time())
            save(d)
    return out


def edit(project, bug_id, by="you", act="edited", **fields):
    """Reword any of a bug's fields. Unknown keys are ignored rather than
    stored: the file's shape is this module's, not the request's.

    `act` names the event for the log — the CLI's `note` is an edit of the
    notes field, but "noted" and "edited" are different claims to whoever
    reads the history back.
    """
    def change(bug):
        if "title" in fields:
            t = _clean(fields["title"], MAX_SHORT).replace("\n", " ")
            if not t:
                return {"error": "a bug needs a title"}
            bug["title"] = t
        if "severity" in fields:
            if fields["severity"] not in SEVERITIES:
                return {"error": f"severity is one of: {', '.join(SEVERITIES)}"}
            bug["severity"] = fields["severity"]
        for k in FIELDS:
            if k in fields:
                v = _clean(fields[k], MAX_LONG if k in ("repro", "notes")
                           else MAX_SHORT)
                if v:
                    bug[k] = v
                else:
                    bug.pop(k, None)
        changed = sorted(set(fields) & (set(FIELDS) | {"title", "severity"}))
        return {"ok": True, "bug": bug,
                "log": {"act": act, "id": bug["id"], "text": bug["title"],
                        "note": ", ".join(changed)}}
    return _edit(project, bug_id, change, by)


def set_status(project, bug_id, status, note="", by="you"):
    """Close a bug, or open it again.

    The note is the point of closing: "fixed" alone tells the next reader
    nothing, "fixed: the picker re-measures on rotate now (commit abc)" is the
    record that stops the same report being chased twice.
    """
    if status not in STATUSES:
        return {"error": f"status is one of: {', '.join(STATUSES)}"}

    def change(bug):
        bug["status"] = status
        note_ = _clean(note, MAX_SHORT).replace("\n", " ")
        if status == "open":
            bug.pop("status_note", None)
            bug.pop("status_by", None)
        else:
            bug["status_note"] = note_
            bug["status_by"] = "claude" if by == "claude" else "you"
        return {"ok": True, "bug": bug,
                "log": {"act": "reopened" if status == "open" else status,
                        "id": bug["id"], "text": bug["title"], "note": note_}}
    return _edit(project, bug_id, change, by)


def remove(project, bug_id, why="", by="you"):
    """Take a report off the tracker for good.

    For a report that should not exist — mis-filed, duplicated, the wrong
    project — and nothing else. A bug that was real and is now dealt with is
    closed, which keeps it; this does not. The reason is kept in the log
    either way, because a row vanishing with no account of why is exactly the
    thing the history was added to prevent.
    """
    bug_id = _int(bug_id)
    if bug_id is None:
        return {"error": "not a bug number"}
    with _lock:
        d = load()
        rows = d["projects"].get(project) or []
        bug = next((b for b in rows if _int(b.get("id")) == bug_id), None)
        if bug is None:
            return {"error": f"no bug #{bug_id} here"}
        rows.remove(bug)
        _log(d, project, by, {"act": "deleted", "id": bug_id,
                              "text": bug.get("title", ""),
                              "note": _clean(why, MAX_SHORT).replace("\n", " ")})
        save(d)
    return {"ok": True}


def prompt(project):
    """The block bb-tty appends for a session, after the roadmap's.

    The open bugs by number, severity and title — enough to recognise one when
    the work touches it — with the fields left on disk behind `bb bug show`,
    because ten full repro scripts in every prompt is the price of nothing.
    """
    with _lock:
        rows = [b for b in (load()["projects"].get(project) or [])
                if b.get("status") == "open"]
    if not rows:
        return ""
    rows.sort(key=lambda b: (SEVERITIES.index(b.get("severity", "medium"))
                             if b.get("severity") in SEVERITIES else 1))
    lines = [f"- #{b['id']} [{b.get('severity', 'medium')}] {b['title']}"
             for b in reversed(rows)]
    return ("The project also has a bug tracker, with these open:\n\n"
            + "\n".join(lines) + "\n\n"
            "`bb bug show <n>` gives one in full — where it lives, how to "
            "reproduce it, what is known about why. When you fix one, close it "
            "with `bb bug fix <n> \"what fixed it\"`; when you find a new one "
            "and it is out of scope for what you are on, `bb bug add "
            "\"...\" --sev medium --area \"...\" --repro \"...\"` rather than "
            "only mentioning it. Add what you learn about an open one to its "
            "notes with `bb bug note <n> \"...\"` — the tracker is where the "
            "next session looks first.")
