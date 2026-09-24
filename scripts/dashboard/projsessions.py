#!/usr/bin/env python3
"""Every account's sessions on one project, for its settings dialog, and an
administrator ending one of them (the operator, 24 Sep).

A session is its account's (B172, server.py _not_theirs): nobody presses a
key in another person's session or types into it, administrators included,
because a key there answers a question it asked them. That stays true.
Ending one is the single exception, and an administrator's alone: a session
somebody left running holds a turn on its node and stands in a tree, and
the person who administers the box needs a way to stop it from the page.

Path-pure over the session rows: the listing, the name helpers, the
accounts and the kill are injected, so this file decides which sessions are
a project's and nothing about how a session is ended.
"""
import re

from names import tmux_name

SESSIONS = None       # () -> every session row, here and on the nodes
BASE = None           # name -> the name without its account prefix
OWNER = None          # name -> the uid in its prefix, "" for the owner's bare name
ACCOUNTS = None       # () -> {uid: account name}
OWNER_NAME = None     # () -> the owner's account name
END = None            # (name, node_id) -> the kill path's answer


def configure(*, sessions, base, owner, accounts, owner_name, end):
    globals().update(SESSIONS=sessions, BASE=base, OWNER=owner,
                     ACCOUNTS=accounts, OWNER_NAME=owner_name, END=end)


def _kind(base, project):
    """"claude" or "shell" when a session's unprefixed name is this project's,
    else "". Exact, by the names bb-tty gives them (claude-<p>, shell-<p> and
    shell-<p>-<n>), so a project called a-b is never read as a's."""
    t = tmux_name(project)
    if base == "claude-" + t:
        return "claude"
    if base == "shell-" + t or re.fullmatch(re.escape("shell-" + t) + r"-\d+", base):
        return "shell"
    return ""


def of(project):
    """[{name, node, node_id, who, kind, state, attached}] for every session
    on this project, every account's: Claude first within each person.
    `state` is a Claude session's working or waiting, empty for a shell."""
    names = ACCOUNTS()
    owner = OWNER_NAME() or ""
    rows = []
    for s in SESSIONS():
        kind = _kind(BASE(s["name"]), project)
        if not kind:
            continue
        uid = OWNER(s["name"])
        rows.append({"name": s["name"], "node": s.get("node", ""),
                     "node_id": s.get("node_id", ""),
                     "who": (names.get(uid) or uid) if uid else owner,
                     "kind": kind,
                     "state": (s.get("claude") or {}).get("state", ""),
                     "attached": bool(s.get("attached"))})
    rows.sort(key=lambda r: (r["who"], r["kind"] != "claude", r["name"]))
    return rows


def end(project, name, node=""):
    """End one of this project's sessions: {ok, who, kind} or {error}.

    Only a row of(project) lists can be named, so nothing else on the box is
    reachable from here, and the kill is the one the Sessions card uses."""
    row = next((r for r in of(project) if r["name"] == name
                and (not node or r["node_id"] == node)), None)
    if not row:
        return {"error": "no such session on this project"}
    r = END(row["name"], row["node_id"]) or {}
    if r.get("error") or r.get("code"):
        return {"error": r.get("error") or (r.get("out") or "tmux refused").strip()[:200]}
    return {"ok": True, "who": row["who"], "kind": row["kind"]}
