"""A held start (R56 step 9): on a controller installed bare metal, the
dashboard, its agent and the network come up, and nothing else runs (no
agent session starts; the pools, shares, apps, VMs and containers the
installed OS adds are held by their own modules reading this) until a
person presses Start on This machine. Not by default: held only after an
unclean shutdown (a clean-shutdown marker written on the way down and
missing on the way up), or when the next start was asked to hold (This
machine's Hold the next start, that one boot). Safe mode at the boot menu
and a disk the array names gone missing are the installed OS's reasons
(R161, R162), added here as they land.

The record is STATE/held.json; the markers beside it are the install's
own: clean-shutdown (the last stop was clean), booted (this install has
come up before, so a missing clean-shutdown means an unclean stop rather
than a first boot), hold-next (the next start is to hold).
"""
import json
import threading
import time
from pathlib import Path

STATE = Path("/config")
_lock = threading.Lock()
_bare = lambda: False       # noqa: E731
write_json = None


def configure(*, state, bare_metal, write_json_fn):
    globals().update(STATE=Path(state), _bare=bare_metal, write_json=write_json_fn)


def _file():
    return STATE / "held.json"


def _load():
    try:
        with open(_file()) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def _save(d):
    write_json(_file(), d)


def _marker(name):
    return STATE / name


def boot():
    """At the controller's start: whether this start is held, and why. On a
    container install nothing is held and the markers are left alone."""
    if not _bare():
        return status()
    why = []
    if _marker("hold-next").exists():
        why.append("asked at the last restart (Hold the next start)")
        with _lock:
            _marker("hold-next").unlink(missing_ok=True)
    if _marker("booted").exists() and not _marker("clean-shutdown").exists():
        why.append("the last shutdown was not clean")
    with _lock:
        _marker("clean-shutdown").unlink(missing_ok=True)
        try:
            _marker("booted").touch()
        except OSError:
            pass
        d = _load()
        if why:
            d.update(held=True, why=why, since=int(time.time()))
        else:
            d.update(held=False, why=[], since=0)
        _save(d)
    return status()


def shutdown_clean():
    """On the way down, cleanly: the marker the next start reads."""
    if not _bare():
        return
    with _lock:
        try:
            _marker("clean-shutdown").touch()
        except OSError:
            pass


def is_held():
    return bool(_load().get("held")) if _bare() else False


def said():
    """The sentence a refusal carries while the start is held."""
    d = _load()
    return ("the start is held" + (f" ({'; '.join(d.get('why') or [])})" if d.get("why") else "")
            + ": press Start on This machine, and sessions run again")


def status():
    """What the page draws: {held, why, since, armed}; held false and armed
    false on a container install."""
    if not _bare():
        return {"held": False, "why": [], "since": 0, "armed": False}
    d = _load()
    return {"held": bool(d.get("held")), "why": list(d.get("why") or []), "since": int(d.get("since") or 0),
            "armed": _marker("hold-next").exists()}


def start(principal=""):
    """Start pressed: the hold lifted, said once in the record."""
    if not _bare():
        return {"error": "nothing is held on a container install"}
    with _lock:
        d = _load()
        if not d.get("held"):
            return {"ok": True, "held": False, "note": "the start was not held"}
        d.update(held=False, why=[], since=0, started_at=int(time.time()), started_by=str(principal)[:80])
        _save(d)
    return {"ok": True, "held": False}


def arm_next(on=True):
    """The next start held (or not), for a restart a person wants to come
    back held: the marker the next boot reads once."""
    if not _bare():
        return {"error": "a held start is a bare-metal install's"}
    with _lock:
        try:
            if on:
                _marker("hold-next").touch()
            else:
                _marker("hold-next").unlink(missing_ok=True)
        except OSError as e:
            return {"error": f"could not write the marker: {e}"}
    return {"ok": True, "armed": bool(on)}
