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


def configure(*, write_json, state, tell=None, tmux_name=None):
    globals().update(write_json=write_json, STATE=Path(state),
                     tell=tell, tmux_name=tmux_name)
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
    """Record one change — in the history, or in an open batch.

    The same arrangement the roadmap's log has, and now the same batch: a
    session working through a notebook is arriving at one state, not making a
    series of decisions the operator needs to read one at a time. The tracker
    still changes as it goes, visibly; only the record waits for commit.
    """
    ev = {"at": int(time.time()),
          "by": "claude" if by == "claude" else "you", **ev}
    b = d.get("batch", {}).get(project)
    if b is not None and ev["by"] == b.get("by", "claude"):
        b.setdefault("events", []).append(ev)
        return
    # Anyone else's change goes straight to the history, which is also what
    # makes revert's guard work: it looks there for the operator's hand.
    h = d.setdefault("history", {}).setdefault(project, [])
    h.append(ev)
    del h[:-MAX_HISTORY]


# ---- the tracker's half of a notebook batch ------------------------------
# Opened and closed by notebook.py, never on its own: a batch covers the whole
# notebook, and half of one is a state nothing here knows how to describe.

# What a batch's events fold down to. Coarser than the roadmap's because a
# bug has fewer moving parts: per bug, the filing if it happened, the last
# thing said about its contents, the last status it landed on, and whether it
# was handed to a session.
_CONTENT = ("edited", "noted")
_STATUS = ("fixed", "wontfix", "na", "reopened")


def _coalesce(events):
    filed, content, status, sent, dropped = {}, {}, {}, {}, {}
    order = []
    for e in events:
        i, act = e.get("id"), e.get("act", "")
        if i not in order:
            order.append(i)
        if act == "deleted":
            # Filed and dropped again inside one batch: neither happened as
            # far as anybody reading the log afterwards is concerned.
            if i in filed:
                filed.pop(i); content.pop(i, None); status.pop(i, None)
                sent.pop(i, None); dropped.pop(i, None)
                order.remove(i)
                continue
            dropped[i] = e
            content.pop(i, None); status.pop(i, None); sent.pop(i, None)
        elif act == "filed":
            filed[i] = e
        elif act in _CONTENT:
            # A title reworded after filing belongs on the filing, not beside
            # it — "filed X" then "edited X" reads as two events and was one.
            if i in filed:
                filed[i]["text"] = e.get("text", filed[i].get("text"))
                filed[i]["at"] = e["at"]
            else:
                content[i] = e
        elif act in _STATUS:
            status[i] = e
        elif act == "sent":
            sent[i] = e
        else:
            content[i] = e
    out = []
    for i in order:
        for bucket in (dropped, filed, content, status, sent):
            if i in bucket:
                out.append(bucket[i])
    return out


def begin(project, by="claude"):
    with _lock:
        d = load()
        if d.get("batch", {}).get(project):
            return {"error": "a batch is already open here"}
        h = d.get("history", {}).get(project) or []
        d.setdefault("batch", {})[project] = {
            "at": int(time.time()), "by": by, "events": [],
            "yours": sum(1 for e in h if e.get("by") == "you"),
            "rows": json.loads(json.dumps(d["projects"].get(project) or []))}
        save(d)
    return {"ok": True}


def batches():
    """Every project with a tracker batch open, for the status poll.

    One read of the file for all of them, the same as the roadmap's: this runs
    on every poll, and asking per project would be a load and a lock each.
    """
    with _lock:
        d = load().get("batch", {})
    return {p: {"at": b.get("at", 0), "by": b.get("by", ""),
                "changes": len(b.get("events") or [])}
            for p, b in d.items() if b}


def batch(project):
    """The open batch here, or None."""
    with _lock:
        b = load().get("batch", {}).get(project)
    return None if not b else {"at": b.get("at", 0), "by": b.get("by", ""),
                               "changes": len(b.get("events") or [])}


def commit(project):
    with _lock:
        d = load()
        b = d.get("batch", {}).get(project)
        if not b:
            return {"error": "nothing is open here"}
        kept = _coalesce(b.get("events") or [])
        h = d.setdefault("history", {}).setdefault(project, [])
        h.extend(kept)
        del h[:-MAX_HISTORY]
        del d["batch"][project]
        save(d)
    return {"ok": True, "written": len(kept),
            "folded": len(b.get("events") or []) - len(kept)}


def revert_blocked(project):
    """Why a revert would refuse, or None — see todo.revert_blocked."""
    with _lock:
        d = load()
        b = d.get("batch", {}).get(project)
        if not b:
            return "nothing is open here"
        h = d.get("history", {}).get(project) or []
        if sum(1 for e in h if e.get("by") == "you") > b.get("yours", 0):
            return ("the operator has changed the tracker since the batch "
                    "opened — reverting would undo their work too. "
                    "Commit it and correct what is wrong.")
    return None


def revert(project):
    why = revert_blocked(project)
    if why:
        return {"error": why}
    with _lock:
        d = load()
        b = d.get("batch", {}).get(project)
        if not b:
            return {"error": "nothing is open here"}
        d["projects"][project] = b.get("rows") or []
        del d["batch"][project]
        save(d)
    return {"ok": True, "dropped": len(b.get("events") or [])}


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


def revisions():
    """{project: how many things have happened to its tracker}.

    A revision number for the status poll, so an open Bugs tab can tell that
    a session wrote something without re-fetching the tracker every fifteen
    seconds to find out. The history length is exactly right for it: every
    write appends one entry, including the deletes and the status flips a
    count of open bugs would miss.
    """
    with _lock:
        h = load().get("history", {})
    return {p: len(rows) for p, rows in h.items()}


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


def send(project, bug_id, sessions=(), note=""):
    """Point a running session at one bug, by number rather than by contents.

    The message deliberately does NOT carry the report. It says which bug and
    tells the session to run `bb bug show N`, because the tracker is the copy
    that stays current: a report pasted into a conversation is a snapshot that
    starts going stale the moment somebody adds a note to it, and the session
    would then be working from the paste rather than from the file everything
    else here reads. One number and an instruction cannot drift.
    """
    if tell is None or tmux_name is None:
        return {"error": "no way to reach a session from here"}
    bug_id = _int(bug_id)
    if bug_id is None:
        return {"error": "not a bug"}
    with _lock:
        d = load()
        row = next((b for b in (d["projects"].get(project) or [])
                    if b.get("id") == bug_id), None)
    if row is None:
        return {"error": "no such bug"}
    # A closed bug is a record, not work. Sending one would ask a session to
    # go and deal with something somebody has already decided is dealt with —
    # and the three closes exist precisely to say which kind of dealt-with it
    # was. If it turns out not to have been, `reopen` is the honest way back,
    # and it leaves a line in the log saying so where this would leave none.
    if row.get("status") != "open":
        return {"error": f"bug #{bug_id} is {STATUS_WORDS.get(row['status'], row['status'])}"
                         " — reopen it first if it needs work again"}
    # No /model or /effort ahead of it: a project's pair are launch flags now,
    # so the session this reaches is already running on them.
    session = tmux_name("claude-" + project)
    line = (f"Please look at bug #{bug_id} in this project's tracker. "
            f"Run `bb bug show {bug_id}` for the report — the area, how to "
            f"reproduce it, expected against actual, and the notes so far. "
            f"When you have dealt with it, close it with `bb bug fix "
            f"{bug_id} \"what fixed it\"`, or one of the other closes if it "
            f"turns out not to be a fix.")
    note = " ".join(_clean(note or "", 500).split())
    if note:
        line += f"  (From the operator, with this: {note})"
    r = tell(session, line, sessions)
    if r.get("error") or not r.get("sent"):
        return r
    # Written down rather than only typed: "was this ever handed to a session,
    # and when?" is a tracker question, and the tracker is where the next
    # reader looks. It is not a status change — sent is not fixed.
    with _lock:
        d = load()
        _log(d, project, "you", {"act": "sent", "id": bug_id,
                                 "text": row.get("title", "")})
        save(d)
    return {"ok": True, "sent": True, "text": line}


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
