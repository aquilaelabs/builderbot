"""A newer BuilderBot release, for a controller installed bare metal (R90
step 5): the newest published release asked of GitHub a while after the
start and then daily, kept in memory, said on the bell and under Controller
settings when it is newer than the build running, and applied when pressed
as a system job on the controller's own node (its root agent runs the
installer's --update; the controller's account never does).

The container edition has its own path (the image, pulled by the host), so
nothing here is drawn for it: `attention` and `status` answer nothing when
the install is not bare metal.
"""
import json
import os
import re
import threading
import time
import urllib.request

RELEASES_URL = (os.environ.get("BB_APPS_RELEASES_URL")
                or "https://api.github.com/repos/aquilaelabs/builderbot/releases")
BOOT_DELAY = float(os.environ.get("BB_RELEASE_BOOT_DELAY") or 120)
EVERY = 24 * 3600
TIMEOUT = 30
VER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

_lock = threading.Lock()
_latest = {"version": "", "tag": "", "at": 0, "error": "", "checking": False, "url": ""}
_version = lambda: ""       # noqa: E731 (configured)
_bare = lambda: False       # noqa: E731
_window = lambda: ("", 4)   # noqa: E731 (the update window: day, hour)
_apply = lambda v: None     # noqa: E731 (queue the update to version v)
_applied = {"version": ""}  # the version the window last queued, so one window queues once
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def configure(*, version, bare_metal, window=None, apply=None):
    globals().update(_version=version, _bare=bare_metal, _window=window or _window, _apply=apply or _apply)


def in_window(now=None):
    """Whether this hour is the update window the person set (R160 step 4):
    daily or one weekday, at the hour named; "" is no window, the default,
    and nothing is applied by itself then."""
    day, hour = _window()
    if not day:
        return False
    t = time.localtime(now if now is not None else time.time())
    if day != "daily" and DAYS[t.tm_wday] != day:
        return False
    return t.tm_hour == int(hour)


def window_pass(now=None):
    """One look, every few minutes from the loop: in the window with a
    newer release not yet queued, the update is queued once (the own node's
    job: the image on BuilderBot OS, the installer elsewhere), and said
    where the job's log and the bell say the rest. Returns what it queued."""
    v = newer() if _bare() else ""
    if not v or not in_window(now) or _applied["version"] == v:
        return ""
    _applied["version"] = v
    try:
        _apply(v)
    except Exception as e:                                          # noqa: BLE001 (said, and the next window tries again)
        print(f"[dashboard] update window: {type(e).__name__}: {e}", flush=True)
        _applied["version"] = ""
        return ""
    return v


def parse(v):
    """(major, minor, patch) of a released version, or None for anything
    else (a dev build, unstamped)."""
    m = VER.match(str(v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def check():
    """Ask what the newest published release is, now. The record."""
    with _lock:
        if _latest["checking"]:
            return dict(_latest)
        _latest["checking"] = True
    version, tag, url, error = "", "", "", ""
    try:
        req = urllib.request.Request(RELEASES_URL, headers={"Accept": "application/json", "User-Agent": "builderbot-release"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:   # noqa: S310 (our releases, or a test's file://)  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            rows = json.loads(r.read(8 << 20) or b"[]")
        live = [x for x in rows if isinstance(x, dict) and not x.get("draft") and not x.get("prerelease") and parse(x.get("tag_name"))]
        live.sort(key=lambda x: parse(x.get("tag_name")), reverse=True)
        if live:
            tag = str(live[0].get("tag_name") or "")
            version = ".".join(str(n) for n in parse(tag))
            url = str(live[0].get("html_url") or "")
        else:
            error = "no published release"
    except (OSError, ValueError) as e:
        error = f"the releases did not answer: {e}"[:200]
    with _lock:
        _latest.update(checking=False, at=int(time.time()), error=error)
        if version:
            _latest.update(version=version, tag=tag, url=url)
        return dict(_latest)


def latest():
    with _lock:
        return dict(_latest)


def newer():
    """The newest release's version when it is newer than the build running
    (a released version; a dev build compares by its target), else ""."""
    lt = latest()
    now = parse(_version()) or parse(str(_version() or "").split("-")[0])
    want = parse(lt.get("version"))
    return lt["version"] if want and now and want > now else ""


def status():
    """What the page draws: nothing on a container install."""
    if not _bare():
        return {}
    lt = latest()
    return {"running": _version(), "latest": lt.get("version", ""), "newer": newer(), "at": lt.get("at", 0),
            "error": lt.get("error", ""), "url": lt.get("url", "")}


def attention(own_node_id):
    """The bell's row (kind release), for a bare-metal install behind the
    newest release, keyed on the version it would move to, so a dismissal
    holds until the next one."""
    v = newer() if _bare() else ""
    if not v or not own_node_id:
        return []
    return [{"kind": "release", "id": own_node_id, "from": _version(), "to": v, "key": f"release:{v}"}]


def start():
    """The daily check on a thread, a while after the start, and the window
    looked at every ten minutes between checks."""
    def loop():
        time.sleep(BOOT_DELAY)
        last = 0
        while True:
            try:
                if time.time() - last >= EVERY:
                    check()
                    last = time.time()
                window_pass()
            except Exception as e:                                  # noqa: BLE001 (the loop outlives one bad pass)
                print(f"[dashboard] release check: {type(e).__name__}: {e}", flush=True)
            time.sleep(600)
    threading.Thread(target=loop, name="release-check", daemon=True).start()
