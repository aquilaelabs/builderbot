#!/usr/bin/env python3
"""One Anthropic account per BuilderBot account, without copying a grant.

**The credential does not travel, and this file is why.** Every failure this
has had came from one OAuth grant living on several machines: a refresh
ROTATES the refresh token, so two copies sign each other out (bug #64); a node
that was away holds one the server has retired (B100); and the machinery built
to make copying safe is itself something that can break, which it did. Claude
issues a grant per login. Two machines sharing one is the unsupported shape,
and the rotation is what punishes it.

So each machine signs in for itself and keeps its own grant, which it alone
refreshes. Nothing is pushed anywhere and the controller holds no credential
at all, which is also what lets this container carry no Claude.

**What the controller keeps instead is the IDENTITY**, per BuilderBot account:

    email, plan   the Anthropic account this BuilderBot account is bound to,
                  as the first node to sign in reported it
    gen           a counter, moved by a sign-out
    nodes         {node id: {email, at}}: who reports being signed in, and
                  as whom, which is what the card reads and what makes a
                  second Anthropic account visible the moment it appears

**The one-account rule is enforced by observation, and that is honest.** A
node reporting a different Anthropic account is refused and told to sign out
first; its sessions do not get to run as somebody else's login. It is not
enforcement by construction: nothing can stop a person typing another
account into `claude auth login` on a machine they have a shell on. What it
replaces is worse: before, that second account was silently copied to every
other node.

**Signing out reaches a machine that is not listening.** The generation moves
and the record is cleared; every node compares generations on its next check
(every connection, every prompt) and runs `claude auth logout` when its own is
behind. A node that is offline does it when it comes back. There is no queue,
because the node is the one that asks.

Path-pure, like changelog.py: handed the account's home, never resolving one.
"""
import json
import os
import time
from pathlib import Path

# What the dashboard's verbs below need from the server, set by server.py: the
# cached answer to who each home is signed in as, cleared when this changes
# it; nodes' names by id, [] when the node store is not up; and the answer
# itself for a home, read afresh.
forget_auth = None
node_names = None
claude_auth = None
home_for = None           # an account's uid -> its home, where its Claude record is

MARK = ".bb-grant.json"
MAX_NODES = 64


def _dir(home):
    return Path(home) / ".claude"


def _read(home):
    try:
        d = json.loads((_dir(home) / MARK).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(home, d):
    p = _dir(home)
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = p / (MARK + ".new")
    tmp.write_text(json.dumps(d))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p / MARK)


def state(home):
    """{signed_in, email, plan, gen, nodes}: what the card draws and what a
    node compares itself against.

    `signed_in` is "some node reports being signed in", because that is the
    only place a credential exists now. An account bound to an Anthropic
    account with no node signed in is a real state: everything was signed out,
    or the nodes are all away.
    """
    if not home:
        return {"signed_in": False, "email": "", "plan": "", "gen": 0, "nodes": {}}
    d = _read(home)
    on = d.get("nodes") if isinstance(d.get("nodes"), dict) else {}
    return {"signed_in": bool(on), "email": str(d.get("email") or ""),
            "plan": str(d.get("plan") or ""), "gen": int(d.get("gen") or 0),
            "nodes": on}


def report(home, node_id, email, plan="", signed_in=True):
    """A node saying what it is signed in as. Returns {ok, gen} or {error}.

    This is the whole of the one-account rule: the first report binds the
    BuilderBot account to an Anthropic one, and a later report of a different
    one is refused rather than recorded. Refused, not merely flagged: a node
    whose sessions would run as somebody else's login is not a warning.
    """
    if not home:
        return {"error": "this account has no home here"}
    if not node_id:
        return {"error": "a report says which node it is from"}
    d = _read(home)
    email = " ".join(str(email or "").split())[:120]
    on = d.get("nodes") if isinstance(d.get("nodes"), dict) else {}
    if not signed_in:
        on.pop(str(node_id), None)
        d["nodes"] = on
        # The binding survives a node signing out on its own: what releases it
        # is a SIGN-OUT, which is a decision, not a machine going quiet.
        _write(home, d)
        return {"ok": True, "gen": int(d.get("gen") or 0)}
    if not email:
        return {"error": "a node reporting a sign-in says which Anthropic account"}
    bound = str(d.get("email") or "")
    if bound and email.lower() != bound.lower():
        return {"error": f"this BuilderBot account is signed in to {bound}, and "
                         f"that machine is signed in as {email}. One Anthropic "
                         "account per BuilderBot account: sign out first, which "
                         "signs out every node, or sign that machine in to "
                         f"{bound}."}
    d["email"] = bound or email
    if plan:
        d["plan"] = " ".join(str(plan).split())[:40]
    on[str(node_id)] = {"email": email, "at": int(time.time())}
    d["nodes"] = dict(list(on.items())[:MAX_NODES])
    d.setdefault("gen", 0)
    _write(home, d)
    return {"ok": True, "gen": int(d["gen"])}


def sign_out(home):
    """Sign the account out, everywhere.

    The generation moves and the record is cleared. Every node compares
    generations on its next check and runs `claude auth logout` when its own
    is behind, so a node that is offline signs itself out when it comes back.
    Nothing is delivered and nothing is queued.

    The binding is released too: signing out is what makes the next sign-in
    free to be a different Anthropic account.
    """
    if not home:
        return {"error": "this account has no home here"}
    d = _read(home)
    was = str(d.get("email") or "")
    where = list((d.get("nodes") or {}).keys())
    gen = int(d.get("gen") or 0) + 1
    _write(home, {"gen": gen, "email": "", "plan": "", "nodes": {}})
    return {"ok": True, "gen": gen, "was": was, "nodes": where}


# ---- the dashboard's verbs, one call each --------------------------------------

def sign_out_verb(home):
    """Sign an account out of Claude, on every machine it is on, once the
    server has said none of its conversations is running. There is nothing
    here to delete (the credentials are the nodes'), so what this does is
    move the generation and clear the record: each node compares
    generations on its next sync (every connection, every prompt) and signs
    ITSELF out when its own is behind, which is what reaches one that is
    not listening. (payload, status)."""
    r = sign_out(home)
    forget_auth()
    if r.get("error"):
        return r, 500
    return {"ok": True, "gen": r["gen"],
            # What it reaches, said rather than assumed: a node that is not
            # dialing in signs itself out when it comes back, and the
            # sentence should not pretend they all go at once.
            "nodes": node_names(r["nodes"]),
            "auth": claude_auth(home=home)}, 200


def identity(home):
    """What a node asks: who this BuilderBot account is bound to and what
    the generation is. No credential leaves here, because none is kept
    here: a machine signs in for itself and keeps the grant it alone
    refreshes. Behind means sign yourself out. (payload, status)."""
    st = state(home)
    return {"email": st["email"], "plan": st["plan"],
            "gen": st["gen"], "signed_in": st["signed_in"],
            "nodes": len(st["nodes"])}, 200


def report_from(home, nid, req):
    """A node reporting what it is signed in AS, never the grant itself,
    once the server has said which node it is from the token. (payload,
    status)."""
    r = report(home, nid, req.get("email") or "", req.get("plan") or "",
               signed_in=bool(req.get("signed_in", True)))
    forget_auth()
    return r, (400 if r.get("error") else 200)


def logins_of(rows):
    """Which Anthropic account each BuilderBot account is signed in as, and
    whether two of them share one, for the Users tab.

    From the RECORD, not from a credential: no login lives on this container
    (R47), and what it keeps instead is which Anthropic account each of its
    accounts is bound to, as the node that signed in reported it.

    Anthropic's consumer terms allow one person per Claude account, so two
    BuilderBot accounts on one login is the thing the per-account homes exist
    to avoid, said on the row rather than left for somebody to work out.
    """
    out = []
    for u in rows:
        home = home_for(u.get("uid", "")) or os.environ.get("BUILDER_HOME", str(Path.home()))
        out.append(u | {"claude": state(home)["email"]})
    seen = {}
    for u in out:
        if u["claude"]:
            seen.setdefault(u["claude"], []).append(u["name"])
    for u in out:
        others = [n for n in seen.get(u["claude"], []) if n != u["name"]]
        u["claude_shared_with"] = others
    return out
