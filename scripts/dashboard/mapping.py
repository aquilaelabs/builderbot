"""The code map, built for a project the moment the project exists.

A session's first questions about a tree it has never seen are the map's
(`bb map find`, `who-calls`, `sections`: roadmap R75), and the first
question builds the index if nothing has, which on a large checkout is
the first minute of the conversation spent waiting. So the build starts
in the background the moment a project is created (a fresh repo, a clone,
an unpacked archive), the dialog closes as it always did, and the row says
"mapping the code" until it is done. The one thing that waits for it is a
Claude session on that project: the button is ghosted with the reason and
bb-tty refuses with the same sentence, so the session's first map question
is answered from an index rather than by building one.

The build is `scripts/lib/codemap.py --root <project> build` as a
subprocess, the same command a session runs by hand, and it writes
.bb-map/ under the tree. That directory is this container's, never the
project's: it is added to the repository's own .git/info/exclude rather
than to the project's .gitignore, which is theirs.

Nothing here survives a restart, and nothing needs to: a build that was
running is simply not recorded, the gate is down, and the session's first
question builds it as before.
"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

WORKSPACE = None
CODEMAP = None             # scripts/lib/codemap.py, beside this dashboard
_jobs = {}                 # name -> {running, at, took, files, error}
_lock = threading.Lock()
KEEP_DONE = 30             # seconds a finished build stays in the payload
TIMEOUT = 1800


def configure(*, workspace, codemap):
    globals().update(WORKSPACE=Path(workspace), CODEMAP=Path(codemap))


def start(name):
    """Build the map for one project in the background. False when one is
    already building for it, or nothing here is configured."""
    if not WORKSPACE or not CODEMAP or not name:
        return False
    with _lock:
        if _jobs.get(name, {}).get("running"):
            return False
        _jobs[name] = {"running": True, "at": time.time(), "took": 0,
                       "files": 0, "error": ""}
    # Out of git first, here, before anything writes .bb-map/: every create
    # path (a fresh repo, a clone, an archive) comes through this, and a
    # clone whose build did not get the line in had its map committed.
    exclude(WORKSPACE / name)
    threading.Thread(target=_build, args=(name,), daemon=True).start()
    return True


def _build(name):
    dest = WORKSPACE / name
    files, error = 0, ""
    try:
        # The build keeps .bb-map/ out of git itself (codemap.exclude).
        # A test-only pause, so a suite can see the gate up: the build of a
        # fixture project is over in a tenth of a second otherwise.
        slow = float(os.environ.get("BB_MAP_SLOW") or 0)
        if slow:
            time.sleep(slow)
        r = subprocess.run([sys.executable, str(CODEMAP), "--root", str(dest), "build"],
                           capture_output=True, text=True, timeout=TIMEOUT)
        first = (r.stdout or "").strip().split("\n")[0] if r.stdout else ""
        if r.returncode != 0:
            error = (r.stderr or r.stdout or "").strip()[-400:] or f"exit {r.returncode}"
        else:
            try:
                files = int(first.split(" ", 1)[0])
            except ValueError:
                files = 0
    except subprocess.TimeoutExpired:
        error = f"gave up after {TIMEOUT // 60} minutes"
    except Exception as e:                                   # noqa: BLE001
        # A worker that dies silently would leave the gate up forever, so
        # broad is right here; the job records it and the log says it once.
        error = f"unexpected failure: {e}"
        print(f"dashboard: mapping {name}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    with _lock:
        j = _jobs.get(name)
        if j:
            j.update(running=False, took=round(time.time() - j["at"], 1),
                     files=files, error=error)


def exclude(dest):
    """`.bb-map/` out of git for a project whose repository was just made:
    the Git view's Init, since a map built before there was a repository
    had nothing to write the line into and went into the first commit. The
    map's own `exclude` verb, which every build also runs (codemap.exclude),
    so there is one place that knows how."""
    if not CODEMAP:
        return
    try:
        subprocess.run([sys.executable, str(CODEMAP), "--root", str(dest), "exclude"],
                       capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass                     # the map still builds; only the exclude is lost


def exclude_all():
    """`.bb-map/` out of git in every project under the workspace, once at
    start: a project made before its create path wrote the line, linked,
    or moved in by hand gets it too. Quiet where it already is."""
    if not WORKSPACE:
        return
    try:
        trees = [d for d in WORKSPACE.iterdir()
                 if not d.name.startswith(".") and (d / ".git").exists()]
    except OSError:
        return
    for d in trees:
        exclude(d)


def held(name):
    """The sentence a Claude session on this project is refused with while
    its map is building, or ""."""
    with _lock:
        j = _jobs.get(name)
        if not j or not j["running"]:
            return ""
        secs = int(time.time() - j["at"])
    return (f"{name} is being mapped for its first session ({secs}s so far): the code map "
            "a session asks before grepping is built once, now, rather than on its first "
            "question. The button comes back when it is done.")


def payload():
    """What the status poll carries: every build running, and every one
    finished in the last half minute, so the row can say what happened."""
    now = time.time()
    out = {}
    with _lock:
        for name, j in list(_jobs.items()):
            if j["running"]:
                out[name] = dict(j, **{"for": int(now - j["at"])})
            elif now - j["at"] - j["took"] < KEEP_DONE:
                out[name] = dict(j)
            else:
                del _jobs[name]
    return out
