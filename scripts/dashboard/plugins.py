"""Which Claude Code plugins each person has installed, on each node.

A plugin is a person's choice, made with /plugin inside their own session, and
it lives in that account's ~/.claude on the node the session ran on. Nothing
about it is BuilderBot's to install or refuse (docs: only machine-wide managed
settings can restrict one). What is BuilderBot's is being able to see them: a
tester whose session behaves oddly may have ten plugins adding their own hooks
and instructions beside BuilderBot's, and "which plugins do you have" should
have an answer on the Profile page and in bb diag rather than a trip to the
node.

The facts arrive the way a node's logins do: the agent runs `bb login --list`
as the session account every few minutes and carries its rows up on the
heartbeat, each with the plugins that account installed there. An agent too
old to send them sends rows without the field, which says nothing and changes
nothing here; a row with the field set to None means the account never
installed one.

Kept as {uid: {node id: {"at": when, "plugins": [...]}}} in its own file, and
written only when what a node says differs from what is stored, since this
arrives on a heartbeat and a heartbeat must not cost a write.
"""
import json
import time
from pathlib import Path

import statefile

STATE = Path("/config")
write_json = None


def configure(*, state, write_json):
    globals().update(STATE=Path(state), write_json=write_json)


def _file():
    return STATE / "claude-plugins.json"


def _load():
    try:
        d = json.loads(_file().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _clean(rows):
    out = []
    for r in (rows if isinstance(rows, list) else [])[:64]:
        if not isinstance(r, dict) or not str(r.get("id") or "").strip():
            continue
        en = r.get("enabled")
        out.append({"id": str(r["id"])[:120], "version": str(r.get("version") or "")[:40],
                    "scope": str(r.get("scope") or "")[:12],
                    "project": str(r.get("project") or "")[:80],
                    "enabled": None if en is None else bool(en)})
    return sorted(out, key=lambda x: (x["id"], x["scope"], x["project"]))


def report(node_id, rows):
    """What a node's `bb login --list` said about each account's plugins.
    True when anything was written."""
    if not isinstance(rows, list):
        return False
    with statefile.locked(_file()):
        d = _load()
        moved = False
        for r in rows[:64]:
            if not isinstance(r, dict):
                continue
            uid = str(r.get("uid") or "")
            if not uid.startswith("u_") or len(uid) > 16:
                continue
            got = _clean(r.get("plugins"))
            mine = d.setdefault(uid, {})
            if not got:
                if node_id in mine:
                    del mine[node_id]
                    moved = True
                if not mine:
                    d.pop(uid, None)
                continue
            if (mine.get(node_id) or {}).get("plugins") == got:
                continue
            mine[node_id] = {"at": int(time.time()), "plugins": got}
            moved = True
        if moved:
            write_json(_file(), d)
        return moved


def of(uid, node_names=None):
    """[{node, name, at, plugins}] for one account, one entry per node it has
    any on. `node_names` maps an id to the name to show; an id it does not
    name (a node since removed) is shown as its id."""
    names = node_names or {}
    return [{"node": nid, "name": names.get(nid, nid), "at": v.get("at", 0),
             "plugins": v.get("plugins") or []}
            for nid, v in sorted((_load().get(uid) or {}).items())]


def everyone():
    """{uid: {node id: [...]}} for bb diag: every account's, on every node."""
    return {uid: {nid: v.get("plugins") or [] for nid, v in per.items()}
            for uid, per in _load().items()}
