"""Messages between accounts, and what each project's people are doing.

Two kinds of conversation and one store, because they are the same thing to
the person reading them: a line, from somebody, at a time.

  * a DIRECT conversation between two accounts, kept per pair;
  * a PROJECT feed, which everybody with that project sees, carrying both what
    people type into it and what the box notices them doing: a Claude session
    started, a rebuild, a prompt sent. The events are the point: on a shared
    project, "alice just started a session here" is the thing you want to know
    before you start one too.

WHO CAN READ WHAT falls out of the addressing and is checked at the door, not
here: a direct conversation is readable by its two ends, and a project feed by
whoever may see the project (users.may_see). This module stores and prunes; it
does not decide.

PROMPTS ARE RELAYED, and that is worth being plain about rather than quiet:
what somebody types to Claude on a shared project is shown to the others who
share it. That is the feature (it is how three people avoid doing the same
work twice) and it means a project is not a private place to think. The UI
says so where the feed is drawn, because a person should not find that out by
accident.

No websockets: the page polls, faster while the panel is open. That matches the
rest of this dashboard, where the terminals' sockets are the one exception and
everything else is a fifteen-second poll.
"""
import sys
import json
import threading
import time
from pathlib import Path

STATE = Path("/config")
write_json = None
# The account store, set by server.py: a conversation read is marked seen in
# the reader's own prefs (converse()).
users = None
_lock = threading.RLock()
_rev = 0

# Per conversation. Chat is a working channel rather than an archive: what
# matters is the last while, and an unbounded file is one somebody eventually
# has to delete by hand.
KEEP = 400
# How long since an account's last poll still counts as "here". The status
# poll is every fifteen seconds, so this is four missed ones, long enough to
# survive a slow page and short enough that a closed laptop goes quiet.
ONLINE_S = 70


def configure(*, state, write_json):
    globals().update(STATE=Path(state), write_json=write_json)


def _file():
    return STATE / "chat.json"


def rev():
    """Bumped on every write, so a poll can tell there is something new
    without shipping the messages on every one of them."""
    return _rev


def _load():
    try:
        d = json.loads(_file().read_text())
    except (OSError, ValueError):
        return {"dm": {}, "project": {}}
    if not isinstance(d, dict):
        return {"dm": {}, "project": {}}
    for k in ("dm", "project"):
        if not isinstance(d.get(k), dict):
            d[k] = {}
    return d


def pair(a, b):
    """The key for a direct conversation. Sorted, so it is the same key
    whichever end is asking; the alternative is two half-conversations that
    each hold what the other said."""
    return "|".join(sorted([str(a), str(b)]))


def _append(kind, key, row):
    global _rev
    with _lock:
        d = _load()
        msgs = d[kind].setdefault(key, [])
        msgs.append(row)
        del msgs[:-KEEP]
        write_json(_file(), d)
        _rev += 1
    return row


# Sub-second, unlike every other timestamp in this dashboard. Read state is
# "everything before when I looked", and two messages in the same second is
# what a conversation IS: at whole seconds the second one is indistinguishable
# from one already read, and stays unread forever or never.
def now():
    return round(time.time(), 3)


def say(from_uid, to_uid, text):
    """One account to another."""
    text = str(text or "").strip()[:4000]
    if not text or not from_uid or not to_uid or from_uid == to_uid:
        return {"error": "nothing to send"}
    _append("dm", pair(from_uid, to_uid),
            {"at": now(), "from": str(from_uid), "text": text})
    return {"ok": True}


def post(project, from_uid, text, kind="said"):
    """Into a project's feed. `kind` is "said" for something a person typed
    and a verb for something the box noticed; the reader is told which,
    because "alice: rebuild it" and "alice started a rebuild" are different
    claims and only one of them is the box's own observation."""
    text = str(text or "").strip()[:4000]
    if not text or not project:
        return {"error": "nothing to send"}
    _append("project", str(project),
            {"at": now(), "from": str(from_uid or ""),
             "kind": str(kind)[:20], "text": text})
    return {"ok": True}


def event(project, actor_uid, text):
    """Something the box noticed, for everyone sharing this project.

    Best effort and never raised: an activity line is not worth failing the
    action it is describing. Every caller is a handler that has just done
    something real, and a full disk here must not undo it.
    """
    # Swallowed on purpose, and said so: see the docstring. Broad because
    # the handler behind it has already acted, and the disk or a bug here
    # must not undo that; the log carries what was lost.
    try:
        post(project, actor_uid, text, kind="did")
    except Exception as e:                                  # noqa: BLE001
        print(f"dashboard: chat: activity line for {project} lost: {type(e).__name__}: {e}",
              file=sys.stderr, flush=True)


def direct(a, b, since=0):
    return [m for m in _load()["dm"].get(pair(a, b), [])
            if m.get("at", 0) > since]


def feed(project, since=0):
    return [m for m in _load()["project"].get(str(project), [])
            if m.get("at", 0) > since]


def unread(uid, others, projects, seen):
    """{key: count} of what has arrived since this account last looked.

    `seen` is the account's own {key: timestamp}, kept on its user record;
    read state is per person, so it cannot live beside the messages.
    """
    d = _load()
    out = {}
    for o in others:
        k = pair(uid, o)
        n = len([m for m in d["dm"].get(k, [])
                 if m.get("at", 0) > seen.get(f"dm:{o}", 0)
                 and m.get("from") != uid])
        if n:
            out[f"dm:{o}"] = n
    for p in projects:
        n = len([m for m in d["project"].get(p, [])
                 if m.get("at", 0) > seen.get(f"p:{p}", 0)
                 and m.get("from") != uid])
        if n:
            out[f"p:{p}"] = n
    return out


def online(polls, now=None):
    """Account names whose last status poll was recent enough to count as here.

    `polls` is {name: when}, kept in memory by the server rather than on the
    user records. Presence is ephemeral by nature (a restart having cleared
    it is the right answer), and the alternative was rewriting a file holding
    password hashes four times a minute per open browser.
    """
    now = now or time.time()
    return sorted(n for n, at in (polls or {}).items() if now - at < ONLINE_S)


def converse(act, me, uid, box, key, text, names):
    """Send into a conversation, mark it seen, and read it, once the server
    has decided this account may: `box` is ("project", name) or ("dm",
    the other's uid), `key` its seen mark, and `names` uid -> account name
    for the lines' authors. (payload, status)."""
    if act == "send":
        r = (post(box[1], uid, text) if box[0] == "project"
             else say(uid, box[1], text))
        if r.get("error"):
            return r, 400
    if act in ("send", "seen", "read"):
        # Reading it IS seeing it: the panel only asks for a conversation
        # somebody is looking at.
        users.prefs_set(me["name"], {"chat_seen":
                                     users.prefs(me).get("chat_seen", {}) | {key: now()}})
    msgs = (feed(box[1]) if box[0] == "project" else direct(uid, box[1]))
    return {"messages": [m | {"who": names.get(m.get("from"), "")} for m in msgs[-200:]],
            "rev": rev()}, 200
