"""bb doctor, cached, for the Doctor card.

The checks take up to half a minute of network timeouts when something is
down, which rules out running them on the status poll. So a background thread
keeps a cached verdict warm and the poll just carries it, and the card's
refresh button re-runs it on demand for the "did my fix work" moment.
"""
import re
import threading
import time

# Injected by configure(): the server's subprocess runner, and the wait that
# holds the first run until the container has finished starting.
run = None
wait_for_boot = None

# Half an hour, a constant (R29): the card's own button re-runs it on demand,
# which is the control anybody actually reached for.
EVERY = 1800

_lock = threading.Lock()
_verdict = {"when": 0, "checks": [], "failed": False, "running": True}

# bb doctor's own line shape: "  [ok]   claude on PATH". Indented lines that
# carry no tag are elaboration on the check above them (the ssh diagnosis
# hint, the GPU capability note) and travel with it as detail.
LINE = re.compile(r"^\s*\[(ok|FAIL|skip|warn)\]\s+(.*\S)")


def configure(*, run, wait_for_boot):
    globals().update(run=run, wait_for_boot=wait_for_boot)


def refresh():
    """Run bb doctor and cache the parsed result. False if one is mid-run:
    two at once would double every network probe for the same answer, so
    the ask is kept and that run goes again when it ends. Dropped, a node
    that dialed in while the first run after a restart was out left that
    run's "not dialing in" on the card for the half hour (19 Oct)."""
    with _lock:
        if _verdict.get("busy"):
            _verdict["again"] = True
            return False
        _verdict["busy"] = True
        _verdict["running"] = True
    again = True
    try:
        while again:
            _run_once()
            with _lock:
                again = _verdict.pop("again", False)
    finally:
        with _lock:
            _verdict.update(running=False, busy=False)
    return True


def _run_once():
    r = run(["bb", "doctor"], timeout=180)
    checks = []
    for line in r["out"].splitlines():
        m = LINE.match(line)
        if m:
            checks.append({"level": m.group(1), "text": m.group(2), "detail": ""})
        elif checks and line.strip() and not line.startswith("=="):
            checks[-1]["detail"] = (checks[-1]["detail"] + "\n" + line.strip()).strip()
    with _lock:
        _verdict.update(when=int(time.time()), checks=checks, failed=r["code"] != 0)


def payload():
    with _lock:
        return {k: _verdict[k] for k in ("when", "checks", "failed", "running")}


def _loop():
    wait_for_boot()
    while True:
        refresh()
        time.sleep(EVERY)


def start():
    threading.Thread(target=_loop, name="doctor", daemon=True).start()
