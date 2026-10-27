"""Where the controller keeps what grows, as the Settings page sets it.

Everything BuilderBot keeps lives in its state directory (/config) by
default. The directories here are the ones that grow with use, and each can
be put somewhere else on the controller's disks, where there is room: the
operator's ask of 10 Oct. What stays in /config whatever is set: the JSON
records and the database (small, and what a backup of /config is for), and
the signing keys and git credentials, which belong with the rest of the
container's secrets rather than wherever there happened to be space.

A path is changed in one step from the page: the new directory is made, what
is in the old one is moved across (a rename on one filesystem, a copy and a
removal across two, in the background), and until the move has finished the
old place is the one in use, so nothing reads a half-moved directory.
Reset BuilderBot moves the state directory aside and with it this file,
so a directory kept elsewhere is left where it is, and found by nothing,
until it is named here again.
"""
import json
import os
import shutil
import threading
import time
from pathlib import Path

STATE = Path("/config")
WORKSPACE = Path("/workspace")
FILE = "paths.json"
_lock = threading.Lock()
_moving = {}              # name -> {"to", "started", "error"}

# name -> (directory under STATE by default, what it holds, as the page says it)
KINDS = {
    "project-snapshots": ("project-snapshots",
                          "each project's daily snapshots (R165): one copy of every file that changed"),
    "job-snapshots": ("snapshots", "the trees jobs are run from, kept a few per project"),
    "images": ("images", "dev-instance images on their way from the node that built them to the one they run on"),
    "gitrelay": ("gitrelay", "a bare repository per project, through which a node pushes and fetches"),
    "gitview": ("gitview", "the Git view's working area per repository"),
    "logs": ("logs", "this controller's own logs (boot, dashboard, docker, terminal) and the kept CI runs; job logs are in its database"),
}


def configure(*, state, workspace):
    globals().update(STATE=Path(state), WORKSPACE=Path(workspace))


def _load():
    try:
        d = json.loads((STATE / FILE).read_text())
        return {k: str(v) for k, v in d.items() if k in KINDS and isinstance(v, str)}
    except (OSError, ValueError, AttributeError):
        return {}


def _save(d):
    tmp = STATE / f".{FILE}.{os.getpid()}"
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True))
    os.replace(tmp, STATE / FILE)


def default(name):
    return STATE / KINDS[name][0]


def of(name):
    """The directory in use for `name`: the one set, else its default."""
    got = _load().get(name)
    return Path(got) if got else default(name)


def pinned(name):
    """Why `name` cannot be set here, or "": the logs follow BB_LOG_DIR or a
    /logs mount when the container is given one, which wins over this."""
    if name == "logs" and (os.environ.get("BB_LOG_DIR") or Path("/logs").is_dir()):
        return "set by the container (BB_LOG_DIR or a /logs mount), which wins over this"
    return ""


def view():
    """For the Settings page: each kind, where it is, whether it is the default,
    and a move in progress or the last one's error."""
    set_ = _load()
    with _lock:
        moving = {k: dict(v) for k, v in _moving.items()}
    return {"paths": [{"name": k, "what": KINDS[k][1], "path": str(of(k)), "default": str(default(k)),
                       "set": k in set_, "pinned": pinned(k), **({"moving": moving[k]} if k in moving else {})}
                      for k in KINDS]}


def problem(name, path):
    """Why `path` cannot hold `name`, or ""."""
    if name not in KINDS:
        return f"not a kind of storage: {name}"
    if pinned(name):
        return f"{name} is {pinned(name)}"
    p = str(path or "").strip()
    if not p:
        return ""
    if not p.startswith("/") or "\0" in p or any(x in ("..", ".") for x in p.split("/")):
        return f"an absolute path, not {p!r}"
    real = os.path.realpath(p)
    ws = os.path.realpath(WORKSPACE)
    if real == ws or real.startswith(ws + "/"):
        # Nodes reach the projects through their synced copies; nothing kept
        # here belongs where a node's writes land (B618, R165).
        return f"{p} is inside the projects at {WORKSPACE}, where nodes' writes land"
    if real in ("/", "/etc", "/usr", "/bin", "/sbin", "/lib", "/proc", "/sys", "/dev", "/boot"):
        return f"{p} is the system's"
    for other in KINDS:
        if other != name and os.path.realpath(of(other)) == real:
            return f"{p} already holds {other}"
    return ""


def set_path(name, path):
    """Point `name` somewhere else ("" for its default), moving what is there.
    Returns {"ok", "moving"} or {"error"}."""
    if (why := problem(name, path)):
        return {"error": why}
    want = Path(str(path).strip()) if str(path or "").strip() else default(name)
    cur = of(name)
    if os.path.realpath(want) == os.path.realpath(cur):
        return {"ok": True, "moving": False}
    with _lock:
        if name in _moving and not _moving[name].get("error"):
            return {"error": f"{name} is still moving to {_moving[name]['to']}"}
    try:
        made = not want.exists()
        want.mkdir(parents=True, exist_ok=True)
        # The controller's alone (R90 step 15): a session or job account on
        # the same machine, beside a controller installed bare metal, enters
        # nothing it keeps, wherever on the machine it is kept.
        if made or (want.stat().st_uid == os.getuid() and not any(want.iterdir())):
            os.chmod(want, 0o700)
    except OSError as e:
        return {"error": f"cannot make {want}: {e.strerror or e}"}
    if not os.access(want, os.W_OK):
        return {"error": f"{want} is not writable by the controller"}
    if want.exists() and any(want.iterdir()):
        return {"error": f"{want} is not empty; name an empty or new directory"}
    if not cur.is_dir() or not any(cur.iterdir()):
        _commit(name, want)
        return {"ok": True, "moving": False}
    with _lock:
        _moving[name] = {"to": str(want), "started": int(time.time()), "error": ""}
    threading.Thread(target=_move, args=(name, cur, want), name=f"paths-{name}", daemon=True).start()
    return {"ok": True, "moving": True}


def _commit(name, want):
    with _lock:
        d = _load()
        if os.path.realpath(want) == os.path.realpath(default(name)):
            d.pop(name, None)
        else:
            d[name] = str(want)
        _save(d)


def _move(name, cur, want):
    """Each entry across: a rename where both are on one filesystem, else a
    copy and then the original's removal. The setting flips only once all of
    it is there; an error leaves the old place in use and says what."""
    try:
        for entry in list(cur.iterdir()):
            dest = want / entry.name
            try:
                os.rename(entry, dest)
            except OSError:
                if entry.is_dir() and not entry.is_symlink():
                    shutil.copytree(entry, dest, symlinks=True)
                else:
                    shutil.copy2(entry, dest, follow_symlinks=False)
        _commit(name, want)
        for entry in list(cur.iterdir()):
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
        with _lock:
            _moving.pop(name, None)
    except OSError as e:
        with _lock:
            _moving[name] = {**_moving.get(name, {}), "error": f"{type(e).__name__}: {e}"[:300]}
