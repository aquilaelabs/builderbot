"""bb doctor, cached, for the Doctor card.

The checks take up to half a minute of network timeouts when something is
down, which rules out running them on the status poll. So a background thread
keeps a cached verdict warm and the poll just carries it, and the card's
refresh button re-runs it on demand for the "did my fix work" moment.
"""
import re
import threading
import time

# Injected by configure(): the server's subprocess runner, the wait that
# holds the first run until the container has finished starting, and what a
# runner token's node id and slot are in a person's words (B71).
run = None
wait_for_boot = None
runner_named = None

# Half an hour, a constant (R29): the card's own button re-runs it on demand,
# which is the control anybody actually reached for.
EVERY = 1800

_lock = threading.Lock()
_verdict = {"when": 0, "checks": [], "failed": False, "running": True}

# bb doctor's own line shape: "  [ok]   claude on PATH". Indented lines that
# carry no tag are elaboration on the check above them (the ssh diagnosis
# hint, the GPU capability note) and travel with it as detail.
LINE = re.compile(r"^\s*\[(ok|FAIL|skip|warn)\]\s+(.*\S)")


# bb doctor's runner token line: it knows the token store's node id and
# slot, which name nothing a person can find on screen.
RUNNER = re.compile(r"^runner token for (\S+) on (n_[0-9a-f]{8}): (.*)$")


def configure(*, run, wait_for_boot, runner_named=None):
    globals().update(run=run, wait_for_boot=wait_for_boot, runner_named=runner_named)


def _runner_line(check):
    """A runner token's line with its node by name and its runner by the
    repository it serves, and for a failure the way to the page a new token
    is given on (B71): `href` and `act` the panel draws as a link."""
    m = RUNNER.match(check["text"])
    if not m or runner_named is None:
        return check
    slot, nid, rest = m.groups()
    try:
        node, repo = runner_named(nid, slot)
    except Exception:                                                 # noqa: BLE001
        return check
    out = dict(check, text=f"the CI runner token for {repo or slot} on {node or nid}: {rest}")
    if check["level"] == "FAIL":
        out.update(href=f"#/build/runner/{nid}", act="Open its CI runner",
                   detail=(check["detail"] + "\n" if check["detail"] else "")
                   + "Add runner there with the same address and a new token from the git host")
    return out


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
    checks = [_runner_line(c) for c in checks]
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
