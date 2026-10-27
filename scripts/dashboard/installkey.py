"""The install key, made by the install and changed from the page (R154).

With INSTALL_KEY not set, the boot makes a key in a folder only the
controller's account reads (lib/boot.sh install_key_made): the secrets
folder's install-key/ when root may write there, else .install-key beside
the state, which the page warns of since a copy of /config then carries it.
This module reads and writes that folder (BB_INSTALL_KEY_DIR):

  key           today's key, 64 hex characters
  key-previous  the one before it, while anything is still sealed under it
  about.json    when it was made and changed, and the fingerprint of the
                one a person said they saved; nothing in it opens anything

A change seals everything kept under the install key again under the new
one at once (the passes handed to configure()); the previous goes when no
node holds a sign-in sealed under it any more. A key set in the environment
is the environment's: shown, never changed here.
"""
import contextlib
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

import signing

_lock = threading.Lock()
# Set by configure(): the passes that seal again what is kept under the
# install key, each (again=True) -> how many; and () -> how many sign-ins on
# the nodes are still sealed under a key before today's (tokenkeys).
reseal = ()
on_nodes_previous = None


def configure(*, passes, nodes_previous):
    globals().update(reseal=tuple(passes), on_nodes_previous=nodes_previous)


def _dir():
    d = os.environ.get("BB_INSTALL_KEY_DIR") or ""
    return Path(d) if d else None


def where():
    """"env", "secrets", "state", or "" when the install has no key."""
    w = os.environ.get("BB_INSTALL_KEY_IN") or ""
    if w == "env" or (w in ("secrets", "state") and _dir()):
        return w if signing.MASTER is not None else ""
    return ""


def fingerprint(key):
    """Eight hex characters in two groups that name a key and open nothing."""
    h = hashlib.sha256(b"builderbot install key fingerprint\0" + key).hexdigest()[:8]
    return f"{h[:4]} {h[4:]}"


def _about():
    d = _dir()
    try:
        a = json.loads((d / "about.json").read_text()) if d else {}
    except (OSError, ValueError):
        a = {}
    return a if isinstance(a, dict) else {}


def _write(path, data, mode=0o600):
    tmp = path.with_name(path.name + ".new")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _save_about(a):
    _write(_dir() / "about.json", json.dumps(a).encode())


def _drop_previous():
    """The key before today's gone once nothing is sealed under it."""
    d = _dir()
    if not d or signing.PREVIOUS is None or where() == "env":
        return False
    if on_nodes_previous and on_nodes_previous():
        return False
    with contextlib.suppress(OSError):
        (d / "key-previous").unlink()
    signing.load_master()
    return True


def status():
    """What the page shows of the install key: nothing that opens anything."""
    w = where()
    out: dict = {"where": w, "folder": str(_dir() or "") if w in ("secrets", "state") else ""}
    if not w:
        return out
    with _lock:
        _drop_previous()
    a = _about()
    fp = fingerprint(signing.MASTER)
    out.update(fingerprint=fp, changeable=w != "env", made=a.get("made", 0), changed=a.get("changed", 0),
               saved=a.get("saved") == fp, previous=signing.PREVIOUS is not None,
               previous_on_nodes=int(on_nodes_previous() if on_nodes_previous and signing.PREVIOUS else 0))
    return out


def reveal():
    """Today's key, to save, for an administrator: the page shows it only
    when asked and says to keep it apart from /config."""
    if where() not in ("secrets", "state"):
        return {"error": "this install's key is set in its environment, which is where it is kept"}, 409
    return {"key": signing.MASTER.decode(), "fingerprint": fingerprint(signing.MASTER)}, 200


def saved(fp):
    """A person says they saved the key with this fingerprint."""
    if where() not in ("secrets", "state"):
        return {"error": "nothing to save: the key is set in the environment"}, 409
    if fp != fingerprint(signing.MASTER):
        return {"error": "that is not today's key: show it again and save that one"}, 409
    with _lock:
        a = _about()
        a["saved"] = fp
        _save_about(a)
    return {"ok": True}, 200


KEY_RE = re.compile(r"[0-9A-Za-z+/=_.-]{32,256}")


def change(new=""):
    """A new install key, made or pasted, and everything kept under the one
    before sealed again under it at once; the one before is kept while
    nodes still hold sign-ins sealed under it."""
    w = where()
    if w == "env":
        return {"error": "this install's key is set in its environment (INSTALL_KEY): change it there and restart"}, 409
    if w not in ("secrets", "state"):
        return {"error": "this install has no key folder: it is made at start when INSTALL_KEY is not set"}, 409
    new = (new or "").strip()
    if new and not KEY_RE.fullmatch(new):
        return {"error": "a key is 32 to 256 letters, digits or + / = _ . - with no spaces"}, 400
    with _lock:
        if signing.PREVIOUS is not None and not _drop_previous():
            n = on_nodes_previous() if on_nodes_previous else 0
            return {"error": f"the key before this one still opens {n} sign-in{'' if n == 1 else 's'} on the nodes: "
                             "each opens, and moves to today's key, when its person next opens a terminal there"}, 409
        key = (new or secrets.token_hex(32)).encode()
        if key == signing.MASTER:
            return {"error": "that is today's key"}, 400
        d = _dir()
        _write(d / "key-previous", signing.MASTER)
        _write(d / "key", key)
        signing.load_master()
        moved = 0
        for p in reseal:
            moved += p(again=True) or 0
        a = _about()
        a.pop("saved", None)
        a["changed"] = int(time.time())
        a.setdefault("made", a["changed"])
        _save_about(a)
        _drop_previous()
    return {"ok": True, "fingerprint": fingerprint(key), "resealed": moved}, 200


def note_made():
    """At start: the day a key the install made was first seen, so the page
    can say it was made, and has not been saved yet."""
    if where() not in ("secrets", "state"):
        return
    with _lock:
        a = _about()
        if not a.get("made"):
            a["made"] = int(time.time())
            with contextlib.suppress(OSError):
                _save_about(a)
