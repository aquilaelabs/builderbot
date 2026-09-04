"""Who has the Claude session on a project.

One conversation per project is the rule, and it predates accounts: bb-tty
derives the session name from the project (`claude-<proj>`), so tmux has only
ever been able to hold one. The reason is not politeness — two Claude sessions
in one working tree edit the same files and undo each other.

What accounts added is the question this module answers: WHOSE. Without it a
second person pressing Claude on a project lands inside somebody else's
conversation, reads it, and types into it.

THE TMUX SESSION IS THE TRUTH ABOUT WHETHER; THIS FILE IS THE TRUTH ABOUT WHO.
That split is the whole design and it is what keeps the record from going
stale. A holder is only reported while the session it names is actually alive,
so:

  * the session ending releases it, with nothing to notice or sweep;
  * a container restart releases every one of them, because the tmux server
    went with the container — the same reasoning prune_claude_tabs already
    applies to the tabs;
  * an account being deleted releases theirs, because an id that is no longer
    an account cannot hold anything.

None of those needed code. What is written here is one line per project, and
it is only ever read alongside the live session list.
"""
import json
import threading
from pathlib import Path

STATE = Path("/config")
write_json = None
_lock = threading.RLock()


def configure(*, state, write_json):
    globals().update(STATE=Path(state), write_json=write_json)


def _file():
    return STATE / "claude-holders.json"


def _load():
    try:
        d = json.loads(_file().read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def session_name(project, tmux_name):
    """The tmux session a Claude conversation on `project` runs as."""
    return tmux_name(f"claude-{project}")


def holder(project, live, tmux_name, known=None):
    """Who holds this project's Claude session, or "" if nobody does.

    `live` is the set of tmux session names that exist; `known` is the set of
    account ids that still exist, when the caller has it. Both are passed in
    rather than looked up so this module knows nothing about tmux or accounts
    and can be reasoned about on its own.
    """
    if session_name(project, tmux_name) not in live:
        return ""
    who = str(_load().get(project) or "")
    if known is not None and who and who not in known:
        return ""              # the account went; the conversation is nobody's
    return who


def claim(project, uid):
    """Record who is opening this project's Claude session.

    Written on the way in rather than checked-then-written: the check is the
    caller's, and it has the live session list this does not. Claiming one
    already held by the same account is the ordinary case — a tab reconnecting
    — and is a no-op.
    """
    uid = str(uid or "")
    if not uid:
        return
    with _lock:
        d = _load()
        if d.get(project) == uid:
            return
        d[project] = uid
        write_json(_file(), d)


def forget(project):
    """Drop the record for a project. Only for a project that is going away —
    a session ending needs nothing, because the live check answers for it."""
    with _lock:
        d = _load()
        if d.pop(project, None) is not None:
            write_json(_file(), d)


def all_held(live, tmux_name, known=None):
    """{project: uid} for every project whose session is alive and held. The
    page needs the whole map, not one project at a time: it draws a Claude
    button per row."""
    d = _load()
    out = {}
    for project, uid in d.items():
        who = holder(project, live, tmux_name, known)
        if who:
            out[project] = who
    return out
