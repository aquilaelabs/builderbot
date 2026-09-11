#!/usr/bin/env python3
"""One Anthropic account per BuilderBot account, across every node.

The credential is an OAuth pair in `$HOME/.claude/.credentials.json`, and
Claude Code reads it out of the home it runs in — so a node that runs an
account's sessions holds a COPY. That is the design and cannot be otherwise;
what this file decides is which copy is the truth and when the others have to
catch up.

**Why a generation, and not just a date.** A refresh rotates the refresh
token, so two machines each keeping a copy sign each other out (bug #64). The
fix was "whichever refreshed has the later expiresAt wins", and inside one
sign-in that is still right. It cannot express a SIGN-OUT: the absence of a
credential has no date, so a node coming back from a week offline would look
like the newest thing anybody had and put the account back. So every
deliberate act — a sign-in landing, a sign-out — moves a counter, and a node
compares counters first and dates second:

    controller's gen > mine   the controller acted while I was away.
                              Adopt what it has, INCLUDING nothing.
    equal                     same sign-in, so the refresh race applies:
                              later expiresAt wins, either direction.

A node that was offline signs itself out on the next sync, which is on every
connection and every prompt. Nothing is queued for it and nothing has to
reach it — it asks, and the answer is already true.

**One Anthropic account.** The email the grant belongs to is recorded beside
it, as the node reported it (`claude auth status --json` runs where Claude
is). A grant for a different one is refused rather than stored: signing a
second Anthropic account in on one node would otherwise propagate to every
other node on the next sync and quietly move the whole BuilderBot account to
it. Signing out releases the email, so the next sign-in may be anybody.

Deliberately path-pure, like changelog.py: it is handed the account's home
and never resolves one. Who an account is, and where their home is, is
users.py's and server.py's question and answering it twice would be a second
copy that drifts.
"""
import contextlib
import json
import os
import time
from pathlib import Path

FILE = ".credentials.json"
MARK = ".bb-grant.json"          # the generation and the email, beside it
PREV = ".credentials.json.prev"  # one round of history: a bad write signs you out


def _dir(home):
    return Path(home) / ".claude"


def read(home):
    """The credential as text, or "" — including after a sign-out."""
    if not home:
        return ""
    try:
        return (_dir(home) / FILE).read_text()
    except OSError:
        return ""


def expires_at(text):
    """When a grant stops being good, as the number a refresh moves. 0 for
    anything that is not one, so a real grant always wins a comparison."""
    try:
        return int((json.loads(text).get("claudeAiOauth") or {}).get("expiresAt") or 0)
    except (ValueError, AttributeError, TypeError):
        return 0


def mark(home):
    """{gen, email, at} — the generation this account is on and the Anthropic
    account its grant belongs to. Generation 0 means nothing has happened
    here yet, which is a different fact from a sign-out at generation 3."""
    try:
        d = json.loads((_dir(home) / MARK).read_text())
        return {"gen": int(d.get("gen") or 0), "email": str(d.get("email") or ""),
                "plan": str(d.get("plan") or ""), "at": int(d.get("at") or 0)}
    except (OSError, ValueError, TypeError, AttributeError):
        return {"gen": 0, "email": "", "plan": "", "at": 0}


def _write_mark(home, gen, email, plan=""):
    d = _dir(home)
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = d / (MARK + ".new")
    tmp.write_text(json.dumps({"gen": int(gen), "email": email, "plan": plan,
                               "at": int(time.time())}))
    os.chmod(tmp, 0o600)
    os.replace(tmp, d / MARK)


def state(home):
    """What the page and a node both ask: whether this account is signed in,
    to what, and on which generation."""
    m = mark(home)
    text = read(home)
    return {"signed_in": bool(expires_at(text)), "email": m["email"],
            "plan": m["plan"], "gen": m["gen"]}


def store(home, text, email="", plan=""):
    """A grant arriving from a node. Returns {ok, stored, why, gen}.

    Refused rather than stored for a different Anthropic account, and for a
    grant no newer than the one here — a machine that has been away cannot
    undo a sign-in that happened while it was gone.
    """
    if not home:
        return {"error": "this account has no home here"}
    if not isinstance(text, str) or len(text) > 65536:
        return {"error": "a credentials file is a JSON string"}
    mine = expires_at(text)
    if not mine:
        return {"error": "that is not a Claude grant — no claudeAiOauth.expiresAt"}
    m = mark(home)
    email = " ".join(str(email or "").split())[:120]
    if m["email"] and email and email.lower() != m["email"].lower():
        return {"error": f"this BuilderBot account is signed in to {m['email']}, "
                         f"and that grant is {email}'s. One Anthropic account per "
                         "BuilderBot account: sign out first, which signs out "
                         "every node."}
    have = read(home)
    if have and expires_at(have) >= mine:
        return {"ok": True, "stored": False, "gen": m["gen"],
                "why": "the grant here is the same or newer"}
    d = _dir(home)
    try:
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        if have:
            with contextlib.suppress(OSError):
                (d / PREV).write_text(have)
                os.chmod(d / PREV, 0o600)
        tmp = d / (FILE + ".new")
        tmp.write_text(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, d / FILE)
    except OSError as e:
        return {"error": f"could not store the grant: {e}"}
    # The generation moves on a sign-in LANDING, not on one starting: until
    # the credential is here there is nothing for another node to adopt, and
    # a node that adopted an empty controller would delete its own copy.
    gen = m["gen"] + 1
    _write_mark(home, gen, email or m["email"], plan or m["plan"])
    return {"ok": True, "stored": True, "gen": gen}


def sign_out(home):
    """Take the account's grant away, everywhere.

    The credential goes here and the generation moves, which is the whole of
    it: every node compares generations on its next sync and adopts what the
    controller has, and what it has is nothing. A node that is offline does
    that when it comes back — there is no queue, because the node asks.

    The email is released too: signing out is what makes the next sign-in
    free to be a different Anthropic account.
    """
    if not home:
        return {"error": "this account has no home here"}
    m = mark(home)
    d = _dir(home)
    have = read(home)
    try:
        if have:
            d.mkdir(mode=0o700, parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                (d / PREV).write_text(have)
                os.chmod(d / PREV, 0o600)
        with contextlib.suppress(OSError):
            (d / FILE).unlink()
    except OSError as e:
        return {"error": f"could not sign out: {e}"}
    gen = m["gen"] + 1
    _write_mark(home, gen, "", "")
    return {"ok": True, "gen": gen, "was": m["email"]}
