"""The controller's half of the coding agents' sealed sign-ins (R126).

Each account's key pair on each node is made here from the account's own
key (R154, accountkeys.py; from the install key, R135, before that) and
kept nowhere: the node is handed the public half to seal with
(public), and the key that opens one of its seals is made only for a
terminal a person opened for their own account (wrapped_for), wrapped to
the node agent's key for this boot. The arithmetic is tokenseal.py's, the
node agent's own file, loaded here by path so both ends share one.

Rotating the install key: the key before it (INSTALL_KEY_PREVIOUS, a file
in /run beside the key) is kept while nodes still hold seals made under it, and a
terminal's open carries the keys of both; the node opens with the one that
fits and seals again under the new public key, after which the previous
key can go.
"""
import base64
import importlib.util
import os
from pathlib import Path

import accountkeys
import signing

PREV_FILE = "/run/builderbot-key-previous"
AGENT_DIR = ""      # the node agent's directory, set by configure()

_ts = {}
_pub_cache = {}


def configure(*, agent_dir):
    global AGENT_DIR
    AGENT_DIR = agent_dir
    _ts.clear()


def ts():
    """tokenseal.py, the agent's own, loaded by path once."""
    if "mod" not in _ts:
        spec = importlib.util.spec_from_file_location(
            "bb_tokenseal", os.path.join(str(AGENT_DIR), "builderbot_agent", "tokenseal.py"))
        if spec is None or spec.loader is None:
            raise ImportError("no tokenseal.py beside the agent")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ts["mod"] = mod
    return _ts["mod"]


def keys():
    """The install key, then the one before it while a rotation keeps it
    (INSTALL_KEY_PREVIOUS, which the entrypoint writes beside the key)."""
    try:
        prev = Path(os.environ.get("BB_INSTALL_KEY_PREVIOUS_FILE") or PREV_FILE).read_bytes().strip()
    except OSError:
        prev = b""
    return [k for k in (signing.MASTER, prev if len(prev) >= 16 else None) if k]


def _pub(k, node, uid, old=False):
    """The public half of the account's key pair on this node: X25519's
    (R158 step 3), or with `old` the format before's, which a 0.8.x node
    still seals with."""
    cache = (k, node, uid, old)
    if cache not in _pub_cache:
        _pub_cache.clear() if len(_pub_cache) > 4096 else None
        t = ts()
        _pub_cache[cache] = t.public(t.secret1(k, node, uid) if old else t.secret(k, node, uid))
    return _pub_cache[cache]


def _secret_for(k, node, uid, R):
    """The secret of the kind a seal's R calls for."""
    t = ts()
    return t.secret(k, node, uid) if t.is_v2(R) else t.secret1(k, node, uid)


def public(node, uid, old=False):
    """The account's public key on this node, hex, made from its own key,
    or "" with no install key: an install with none has nothing to seal
    with, and keeps its sign-ins as plain files."""
    k = accountkeys.key_of(uid)
    return _pub(k, node, uid, old) if k else ""


def _candidates(uid):
    """Every key a seal of this account's may have been made under, today's
    own first: its own, the one before it, and the install key and the one
    before that, which sealed every sign-in before accounts had their own."""
    out = [accountkeys.key_of(uid), accountkeys.previous_of(uid)] + keys()
    seen, keep = set(), []
    for k in out:
        if k and k not in seen:
            seen.add(k)
            keep.append(k)
    return keep


def made_under(node, uid, v):
    """The key a reported seal was made under, from the public half it names
    (K), or None when it names none or none of the account's fits."""
    K = str((v or {}).get("K") or "")
    for k in (_candidates(uid) if K else ()):
        if K in (ts().rid(_pub(k, node, uid)), ts().rid(_pub(k, node, uid, old=True))):
            return k
    return None


def pubs(node, uids, old=False):
    """{uid: public} for these accounts on this node, for its hello: the
    X25519 publics a 0.9 agent seals with, or with `old` the ones before,
    which a 0.8.x agent still reads."""
    out = {}
    for u in uids:
        p = public(node, u, old)
        if p:
            out[u] = p
    return out


def wrapped_for(node, uid, tokseal):
    """The `tk` a terminal's open carries for this account on this node,
    from what the node reported (its boot public E and its seals' R), or
    None when there is nothing to open: {acct, C, w}, the keys of each seal
    made with the key it names (by rid(R), and with |prev when that is not
    the account's own key today), wrapped
    to E so only the running agent can read them."""
    if not isinstance(tokseal, dict) or not tokseal.get("E"):
        return None
    seals = (tokseal.get("sealed") or {}).get(uid) or {}
    own = accountkeys.key_of(uid)
    if not seals or not own:
        return None
    t = ts()
    out = {}
    for v in seals.values():
        R = str((v or {}).get("R") or "")
        # The key the seal names, as the node's first try when it is today's
        # own and as |prev otherwise, which the node opens and then seals
        # again under the account's public key (R154). One naming none is
        # from before K: today's own key, then the install key as |prev.
        k = made_under(node, uid, v)
        # A seal of the format before under today's own key is |prev too:
        # opened with that, the node seals it again the vetted way.
        pairs = ([(k, "" if t.is_v2(R) else "|prev")] if k == own else [(k, "|prev")]) if k else [(own, ""), (keys()[0], "|prev")]
        for key, slot in pairs:
            try:
                out[t.rid(R) + slot] = t.key_for(_secret_for(key, node, uid, R), R)
            except t.Refused:
                continue
    if not out:
        return None
    try:
        C, blob = t.wrap(tokseal["E"], out)
    except t.Refused:
        return None
    return {"acct": uid, "C": C, "w": base64.urlsafe_b64encode(blob).decode().rstrip("=")}


def under_previous(node, tokseal):
    """How many of this node's seals were made under a key other than the
    account's own today: each moves to it when its person next opens a
    terminal there."""
    if not isinstance(tokseal, dict) or not keys():
        return 0
    n = 0
    for uid, agents in (tokseal.get("sealed") or {}).items():
        want = ts().rid(public(node, uid)) if public(node, uid) else ""
        n += sum(1 for v in (agents or {}).values() if (v or {}).get("K") and v["K"] != want)
    return n


def sealed_under(censuses, key, uid=None):
    """How many seals on these nodes ({node: tokseal}) were made under this
    key, for one account or every one: what keeps a key before today's
    needed. A seal naming no key counts, since it may be any."""
    n = 0
    for node, tk in (censuses or {}).items():
        for u, agents in ((tk or {}).get("sealed") or {}).items() if isinstance(tk, dict) else ():
            if uid and u != uid:
                continue
            for v in (agents or {}).values():
                K = str((v or {}).get("K") or "")
                if not K or K in (ts().rid(_pub(key, node, u)), ts().rid(_pub(key, node, u, old=True))):
                    n += 1
    return n
