"""A new project's brief: what the person who made it wants built.

Typed into New project's dialog, and written into the new tree as
BUILDERBOT-BRIEF.md rather than CLAUDE.md. CLAUDE.md is read by every
session as standing instructions, so a request written on the first day
went on asserting its decisions after the project had moved past them.
The brief is a task for one session: the first time Claude is started on
the project, the dashboard shows it in a dialog, editable, beside the model
and the effort that session starts on. Build it hands the text to that
session as its first prompt; Start without it starts one that has not been
given it. Either way the file leaves the tree then, and is kept here, where
the notebook's Briefing view shows it.

The handover crosses machines: the dialog runs in a browser, the session
starts on a node. So Build it STAGES the text for the account that pressed
it, and bb-tty, starting that account's new session, TAKES it (bb brief
take, through the API as the session), which is the moment it moves out of
the tree. A take by anybody else, or with nothing staged, answers nothing.

Store: briefs.json, {project: {"kept": {...}, "staged": {...}}}, keyed by
project so a rename carries it (projects._KEYED).
"""
import contextlib
import json
import time
from pathlib import Path

import statefile

NAME = "BUILDERBOT-BRIEF.md"
# A brief is a paragraph or a page. The cap keeps a pasted log out of the
# first prompt, which travels as one argument on claude's command line.
MAX = 16 * 1024

WORKSPACE = None
FILE = None
write_json = None


def configure(*, workspace, state, write_json):
    globals().update(WORKSPACE=Path(workspace), FILE=Path(state) / "briefs.json",
                     write_json=write_json)


def _load():
    try:
        with open(FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _file(project):
    return WORKSPACE / project / NAME


def write(dest, text):
    """The brief for a project just made, and the sentence saying so.
    Nothing is written when nothing was typed."""
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) > MAX:
        return f"the brief is over {MAX // 1024}KB, so it was not kept"
    try:
        (Path(dest) / NAME).write_text(text + "\n", encoding="utf-8")
    except OSError as e:
        return f"could not write the brief: {e}"
    _exclude(dest)
    return "brief kept for the first Claude session"


def _exclude(dest):
    """The brief into the repository's own exclude file, so no commit takes
    it: a project made with a starting version commits the tree as made, and
    the brief rode in and then showed as a deletion once it left for the
    first session. Never the project's .gitignore, which is the project's."""
    p = Path(dest) / ".git" / "info" / "exclude"
    try:
        have = p.read_text() if p.exists() else ""
        if NAME in have.split("\n"):
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(("" if have.endswith("\n") or not have else "\n") + NAME + "\n")
    except OSError:
        pass


def pending(project):
    """Whether a brief is waiting in the tree for the first session."""
    try:
        return _file(project).is_file()
    except OSError:
        return False


def view(project, uid):
    """What the dialog and the notebook read: the brief waiting in the tree,
    whether this account has staged it, and the one kept after it left."""
    rec = _load().get(project) or {}
    text = ""
    if pending(project):
        with contextlib.suppress(OSError):
            text = _file(project).read_text(encoding="utf-8", errors="replace").strip()
    staged = rec.get("staged") or {}
    return {"pending": pending(project), "text": text,
            "staged": bool(staged) and staged.get("uid") == uid,
            "kept": rec.get("kept") or None}


def _move_out(project, d, text, sent, by):
    """The tree's file out of the codebase and into the store, as kept."""
    rec = d.setdefault(project, {})
    rec["kept"] = {"text": text, "at": int(time.time()), "by": by, "sent": sent}
    rec.pop("staged", None)
    with contextlib.suppress(OSError):
        _file(project).unlink()


def stage(project, uid, by, text):
    """Build it: the brief as edited, written back to the tree and marked
    for this account's next new session. (payload, status)."""
    text = (text or "").strip()
    if not text:
        return {"error": "the brief is empty: Start without it starts a session with no brief"}, 400
    if len(text) > MAX:
        return {"error": f"a brief is at most {MAX // 1024}KB"}, 400
    if not pending(project):
        return {"error": f"{project} has no brief waiting"}, 400
    with statefile.locked(FILE):
        try:
            _file(project).write_text(text + "\n", encoding="utf-8")
        except OSError as e:
            return {"error": f"could not write the brief: {e}"}, 500
        d = _load()
        d.setdefault(project, {})["staged"] = {"uid": uid, "by": by, "at": int(time.time())}
        write_json(FILE, d)
    return {"ok": True}, 200


def set_aside(project, by):
    """Start without it: the brief leaves the tree unsent and is kept.
    (payload, status)."""
    with statefile.locked(FILE):
        if not pending(project):
            return {"ok": True, "kept": False}, 200
        try:
            text = _file(project).read_text(encoding="utf-8", errors="replace").strip()
        except OSError as e:
            return {"error": f"could not read the brief: {e}"}, 500
        d = _load()
        _move_out(project, d, text, False, by)
        write_json(FILE, d)
    return {"ok": True, "kept": True}, 200


def take(project, uid):
    """bb-tty starting this account's new session: the staged brief, which
    leaves the tree now, or "" when this account staged none."""
    with statefile.locked(FILE):
        d = _load()
        rec = d.get(project) or {}
        staged = rec.get("staged") or {}
        if not staged or staged.get("uid") != uid:
            return ""
        text = ""
        if pending(project):
            with contextlib.suppress(OSError):
                text = _file(project).read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            rec.pop("staged", None)
            write_json(FILE, d)
            return ""
        _move_out(project, d, text, True, staged.get("by") or "")
        write_json(FILE, d)
    return text


def verb(project, req, uid, by, session):
    """POST /api/brief: stage and set aside are a person's, from the
    dialog; take is the session's own start. (payload, status)."""
    act = str(req.get("action") or "")
    if act == "take":
        return {"text": take(project, uid)}, 200
    if session:
        return {"error": "a session takes its brief when it starts; the dialog is a person's"}, 403
    if act == "stage":
        return stage(project, uid, by, str(req.get("text") or ""))
    if act == "aside":
        return set_aside(project, by)
    return {"error": f"unknown action: {act}"}, 400
