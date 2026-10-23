#!/usr/bin/env python3
"""Which nodes each BuilderBot account is signed in to Claude on, and as whom.

**A Claude login belongs to one account on one node.** A person signs in on
each node they want Claude to work on, from that node's row on the Nodes
tab, and signs out there. Nothing carries a login from one machine to
another and the controller holds no credential at all, which is also what
lets this container carry no Claude.

That is not a convenience given up lightly: every failure this has had came
from one OAuth grant living on several machines. A refresh ROTATES the
refresh token, so two copies sign each other out (bug #64), and a node that
was away holds one the server has retired (B100). Claude issues a grant per
login, so a login per machine is the supported shape.

**What the controller keeps is what each node reported**, per BuilderBot
account:

    nodes   {node id: {email, plan, at}}: the Anthropic account that node
            says this BuilderBot account is signed in as there

It is a report, not a rule: a person may sign one node in to one Anthropic
account and another node in to another, and the row of each says which.
The Users page says when two BuilderBot accounts are on one Anthropic
account, since Anthropic's terms allow one person per Claude account.

The other coding agents (R95 step 3) keep the same record, one file per
agent: what each node reported the account is signed in to ChatGPT (Codex
CLI) or GitHub (Copilot CLI) as there. Every function takes the agent's id,
Claude's when none is named, whose file is where it always was.

Path-pure, like changelog.py: handed the account's home, never resolving one.
"""
import json
import os
import time
from pathlib import Path

# What logins_of needs from the server, set by server.py: an account's uid
# to its home, where its record is.
home_for = None

MARK = ".bb-grant.json"
MAX_NODES = 64


def _path(home, agent="claude"):
    """Claude's record where it always was; another agent's beside it, in
    the account's own .claude. Not under .config: on the controller that is
    one of the box's shared dotfiles (BB_SHARED_DOTFILES), so every account
    read and wrote one file, and a node's report that a second account had
    no Codex login took the first one's away (B236)."""
    if agent == "claude":
        return Path(home) / ".claude" / MARK
    return Path(home) / ".claude" / f".bb-grant-{agent}.json"


def _read(home, agent="claude"):
    try:
        d = json.loads(_path(home, agent).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(home, d, agent="claude"):
    p = _path(home, agent)
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".new")
    tmp.write_text(json.dumps(d))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def nodes_of(home, agent="claude"):
    """{node id: {email, plan, at}}: every node that reports this account
    signed in, which is what the node rows and the project rows draw."""
    if not home:
        return {}
    d = _read(home, agent)
    on = d.get("nodes")
    # A record from when the plan was the account's carries it beside the
    # nodes: read from there once, and each node's next report writes its own.
    return {str(k): {"email": str(v.get("email") or ""),
                     "plan": str(v.get("plan") or d.get("plan") or ""),
                     "at": int(v.get("at") or 0)}
            for k, v in (on.items() if isinstance(on, dict) else [])
            if isinstance(v, dict) and v.get("email")}


def on(home, node_id, agent="claude"):
    """What this account is signed in as on one node: {email, plan, at}, or
    {} when that node reports no login of theirs."""
    return nodes_of(home, agent).get(str(node_id or ""), {})


def report(home, node_id, email, plan="", signed_in=True, agent="claude"):
    """A node saying what this account is signed in as there, or that it is
    not. {ok, plan} or {error}. An empty plan leaves a stored one be, and
    the answer carries what is stored: the plan is asked of Claude Code only
    when the controller has none, which is once after a sign-in."""
    if not home:
        return {"error": "this account has no home here"}
    if not node_id:
        return {"error": "a report says which node it is from"}
    d = _read(home, agent)
    rows = d.get("nodes") if isinstance(d.get("nodes"), dict) else {}
    email = " ".join(str(email or "").split())[:120]
    if not signed_in:
        # Said on every terminal's connection, for every agent: a node that
        # was not signed in is not written again.
        if str(node_id) not in rows:
            return {"ok": True}
        rows.pop(str(node_id), None)
        _write(home, {"nodes": rows}, agent)
        return {"ok": True}
    if not email:
        return {"error": "a node reporting a sign-in says which account"}
    was = rows.get(str(node_id)) if isinstance(rows.get(str(node_id)), dict) else {}
    # Another Anthropic account on the same node is another sign-in, and its
    # plan is not the last one's.
    kept = str(was.get("plan") or d.get("plan") or "") if str(was.get("email") or "").lower() == email.lower() else ""
    row = {"email": email, "plan": " ".join(str(plan or "").split())[:40] or kept,
           "at": int(time.time())}
    rows[str(node_id)] = row
    _write(home, {"nodes": dict(list(rows.items())[:MAX_NODES])}, agent)
    return {"ok": True, "plan": row["plan"]}


def logins_of(rows):
    """Which Anthropic accounts each BuilderBot account is signed in as, on
    any node, and whether two of them share one, for the Users page.

    From the record, not from a credential: no login lives on this container
    (R47), and what it keeps instead is what each node reported.

    Anthropic's consumer terms allow one person per Claude account, so two
    BuilderBot accounts on one login is said on the row rather than left for
    somebody to work out.
    """
    out = []
    for u in rows:
        home = home_for(u.get("uid", "")) or os.environ.get("BUILDER_HOME", str(Path.home()))
        emails = sorted({v["email"] for v in nodes_of(home).values()}, key=str.lower)
        out.append(u | {"claude": ", ".join(emails), "_emails": {e.lower() for e in emails}})
    for u in out:
        u["claude_shared_with"] = [o["name"] for o in out
                                   if o["name"] != u["name"] and o["_emails"] & u["_emails"]]
    for u in out:
        del u["_emails"]
    return out
