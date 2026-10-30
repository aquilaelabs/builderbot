"""Update checks on one clock, adjustable (R176, the operator, 28 Oct).

Each check BuilderBot makes by itself has a cadence under Controller
settings, Update checks: the release (a newer BuilderBot), the container
images, nginx, the scanners, and the catalog (the toolchains, the coding
agents and the vetted index this controller offers), each daily, weekly
(the default), monthly or off, with Check now beside it. A node's own
version check (what its store holds against what is out) is that node's
setting on its page, read by toolchains.node_checks_due. Each loop asks
due() in place of the constant it had; an environment switch that turns a
check off (BB_IMAGE_AUTOCHECK=0 and the like) still does, for the suite.

What a check last ran at is its own module's to say (last()); the release's
and the catalog's, which kept theirs in memory, are stamped here in
STATE/checks.json so a restart is not a reason to ask again.
"""
import json
import threading
import time
from pathlib import Path

CADENCE = {"daily": 86400, "weekly": 7 * 86400, "monthly": 30 * 86400, "off": None}
KINDS = ("release", "images", "nginx", "scanners", "catalog")
STATE = Path("/config")
settings = None
_last = {}       # kind -> fn returning the epoch it last ran, or 0
_run = {}        # kind -> fn running it now
_lock = threading.Lock()


def configure(*, state, settings_mod, last=None, run=None):
    globals().update(STATE=Path(state), settings=settings_mod)
    _last.update(last or {})
    _run.update(run or {})


def cadence(kind):
    v = settings.get(f"check_{kind}") if settings else "weekly"
    return v if v in CADENCE else "weekly"


def every(kind):
    """Seconds between checks of `kind`, or None when it is off."""
    return CADENCE[cadence(kind)]


def due(kind, last_at, now=None):
    e = every(kind)
    return e is not None and (time.time() if now is None else now) >= int(last_at or 0) + e


def _file():
    return STATE / "checks.json"


def stamped(kind):
    try:
        return int(json.loads(_file().read_text()).get(kind) or 0)
    except (OSError, ValueError, AttributeError):
        return 0


def stamp(kind, at=None):
    with _lock:
        try:
            d = json.loads(_file().read_text())
        except (OSError, ValueError):
            d = {}
        d[kind] = int(at or time.time())
        tmp = _file().with_suffix(".tmp")
        tmp.write_text(json.dumps(d))
        tmp.replace(_file())


def view():
    """What Controller settings draws: each check's cadence and when it last
    ran, those this install has."""
    out = {}
    for k in KINDS:
        if k not in _run:
            continue
        try:
            at = int(_last[k]() or 0) if k in _last else stamped(k)
        except Exception:                                   # noqa: BLE001 (a reading, never the page's failure)
            at = 0
        out[k] = {"cadence": cadence(k), "at": at}
    return out


def run_now(kind):
    """Check now: the check on a thread of its own, the answer on the page's
    next poll. {ok} or {error}."""
    fn = _run.get(kind)
    if not fn:
        return {"error": f"no {kind} check on this install"}
    threading.Thread(target=fn, name=f"check-{kind}", daemon=True).start()
    return {"ok": True}
