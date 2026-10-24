"""The controller's half of the coding agents' sealed sign-ins (R126).

Each account's key pair on each node is made here from the install key
(R135) and kept nowhere: the node is handed the public half to seal with
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


def public(node, uid):
    """The account's public key on this node, hex, or "" with no install
    key: an install with none has nothing to seal with, and keeps its
    sign-ins as plain files."""
    k = keys()
    if not k:
        return ""
    cache = (k[0], node, uid)
    if cache not in _pub_cache:
        _pub_cache.clear() if len(_pub_cache) > 4096 else None
        _pub_cache[cache] = ts().public(ts().secret(k[0], node, uid))
    return _pub_cache[cache]


def pubs(node, uids):
    """{uid: public} for these accounts on this node, for its hello."""
    out = {}
    for u in uids:
        p = public(node, u)
        if p:
            out[u] = p
    return out


def wrapped_for(node, uid, tokseal):
    """The `tk` a terminal's open carries for this account on this node,
    from what the node reported (its boot public E and its seals' R), or
    None when there is nothing to open: {acct, C, w}, the keys of each seal
    made with the install key and the one before it (by rid(R), and with
    |prev), wrapped
    to E so only the running agent can read them."""
    if not isinstance(tokseal, dict) or not tokseal.get("E"):
        return None
    seals = (tokseal.get("sealed") or {}).get(uid) or {}
    ks = keys()
    if not seals or not ks:
        return None
    t = ts()
    out = {}
    for v in seals.values():
        R = str((v or {}).get("R") or "")
        for i, k in enumerate(ks[:2]):
            try:
                out[t.rid(R) + ("|prev" if i else "")] = t.key_for(t.secret(k, node, uid), R)
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
    """How many of this node's seals were made under a key other than
    today's install key: what keeps INSTALL_KEY_PREVIOUS needed."""
    if not isinstance(tokseal, dict) or not keys():
        return 0
    n = 0
    for uid, agents in (tokseal.get("sealed") or {}).items():
        want = ts().rid(public(node, uid))
        n += sum(1 for v in (agents or {}).values() if (v or {}).get("K") and v["K"] != want)
    return n
