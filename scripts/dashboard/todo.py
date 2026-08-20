#!/usr/bin/env python3
"""The per-project to-do list — the one thing here that both sides write.

Everything else the dashboard holds is one-way. The package list is the
container's; a memory is Claude's; the project list is the filesystem's. This
is shared: the operator adds "make the picker wrap properly", a session adds
"a project can be created in one click and only deleted from a shell", and
either can tick something off. That is what makes it worth a panel rather than
a file somebody has to remember to open.

It exists because nothing else here can hold that. `gh` is unauthenticated on
this box by design, so GitHub Issues are unreachable from inside it, and until
now a thing noticed mid-task and left undone lived in the conversation and died
with it.

Where it lives is the other half. /config, beside the tab strip and the
excluded projects — not the repository. A list like this churns far faster than
commits, and a checkbox tapped on a phone must not turn into an uncommitted
change. Anything that deserves to be permanent graduates out of here: into
CLAUDE.md, a commit message, or a test that fails when it regresses.

The server imports this and hands it the helpers it needs; nothing here reaches
back into the server. bb reads and writes the same file through `bb todo`, so a
session can add an item without a browser.
"""
import json
import threading
import time
from pathlib import Path

# The server's, injected rather than imported — same shape as packages.py.
write_json = None
STATE = None
FILE = None


def configure(*, write_json, state):
    globals().update(write_json=write_json, STATE=Path(state))
    globals()["FILE"] = Path(state) / "todos.json"


_lock = threading.Lock()

# Room for a working list, not an issue tracker. A list nobody can read at a
# glance is one nobody reads at all, and this one is put in front of every
# session that starts — so its length is a cost paid on every conversation.
MAX_OPEN = 30
MAX_TEXT = 500

# Ticked items stay a while, because "what did we just finish" is worth having
# for a day or two, and then they are noise.
KEEP_DONE_DAYS = 7


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


def _prune(rows):
    """Drop ticked items once they have been ticked long enough."""
    cut = time.time() - KEEP_DONE_DAYS * 86400
    return [r for r in rows if not (r.get("done") and r.get("done_at", 0) < cut)]


def items(project):
    with _lock:
        d = load()
        rows = _prune(d["projects"].get(project) or [])
    rows.sort(key=lambda r: (bool(r.get("done")), -r.get("added", 0)))
    return rows


def counts():
    """{project: open count} for the project rows."""
    with _lock:
        d = load()
    return {p: sum(1 for r in _prune(rows) if not r.get("done"))
            for p, rows in d["projects"].items()}


def _next_id(rows):
    return max((int(r.get("id", 0)) for r in rows), default=0) + 1


def add(project, text, by="you"):
    text = (text or "").strip()
    if not text:
        return {"error": "nothing to add"}
    if len(text) > MAX_TEXT:
        return {"error": f"too long — {MAX_TEXT} characters is the limit"}
    with _lock:
        d = load()
        rows = _prune(d["projects"].get(project) or [])
        if sum(1 for r in rows if not r.get("done")) >= MAX_OPEN:
            return {"error": f"{MAX_OPEN} open items is the limit — this list "
                             "goes in front of every session, so it has to stay "
                             "readable"}
        row = {"id": _next_id(rows), "text": text, "done": False,
               "added": int(time.time()), "by": "claude" if by == "claude" else "you"}
        rows.append(row)
        d["projects"][project] = rows
        save(d)
    return {"ok": True, "item": row}


def _find(rows, item_id):
    return next((r for r in rows if int(r.get("id", 0)) == item_id), None)


def _edit(project, item_id, change):
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return {"error": "not an item"}
    with _lock:
        d = load()
        rows = _prune(d["projects"].get(project) or [])
        row = _find(rows, item_id)
        if row is None:
            return {"error": "no such item"}
        out = change(row, rows)
        d["projects"][project] = rows
        save(d)
    return out


def set_done(project, item_id, done):
    def change(row, rows):
        row["done"] = bool(done)
        row["done_at"] = int(time.time()) if done else 0
        return {"ok": True, "item": row}
    return _edit(project, item_id, change)


def edit(project, item_id, text):
    text = (text or "").strip()
    if not text:
        return {"error": "nothing to say"}
    if len(text) > MAX_TEXT:
        return {"error": f"too long — {MAX_TEXT} characters is the limit"}

    def change(row, rows):
        row["text"] = text
        return {"ok": True, "item": row}
    return _edit(project, item_id, change)


def remove(project, item_id):
    def change(row, rows):
        rows.remove(row)
        return {"ok": True}
    return _edit(project, item_id, change)


def clear_done(project):
    with _lock:
        d = load()
        rows = [r for r in (d["projects"].get(project) or []) if not r.get("done")]
        d["projects"][project] = rows
        save(d)
    return {"ok": True}


def prompt(project):
    """The block bb-tty appends to a session's system prompt.

    Open items only, and plain text: this is read once at the start of a
    conversation, and a session that spends its first act parsing a data
    structure has already lost the point of it. Empty when there is nothing,
    so a project with no list adds nothing to any prompt.
    """
    rows = [r for r in items(project) if not r.get("done")]
    if not rows:
        return ""
    lines = [f"- {r['text']}" + ("  (you added this in an earlier session)"
                                 if r.get("by") == "claude" else "")
             for r in rows]
    return ("The operator keeps a shared to-do list for this project, and this "
            "is what is on it:\n\n" + "\n".join(lines) + "\n\n"
            "It is context, not instructions: work on an item when asked, or "
            "when it is plainly part of what was asked. Tick one off with "
            "`bb todo done <n>` when you finish it, and add one with "
            "`bb todo add \"...\"` when you notice something worth doing and "
            "it is out of scope for what you are on. Do not restate the list "
            "back to the operator — they can see it.")
