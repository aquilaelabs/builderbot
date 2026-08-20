#!/usr/bin/env python3
"""Everything behind the dashboard's Tools tab.

The catalog, where a package's files land, what it weighs, what version it is
and what version upstream has, and the one-job-at-a-time worker that installs,
updates, removes and checks. The server imports this and hands it two helpers;
nothing here reaches back into the server.

The division of labour with bb is the point. This module decides *when* to ask
and remembers the answers; bb decides *how*, out of config/packages.json,
which holds every URL, flag and argument any of it needs. Neither of them has
a package name written into it.
"""
import json
import os
import re
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The two the server owns: running a command and writing a state file
# atomically. Injected rather than imported, because importing the server from
# a module the server imports is a circle.
run = None
write_json = None
STATE = None


def configure(*, run, write_json, state):
    """Hand over the server's helpers and read what is on disk."""
    globals().update(run=run, write_json=write_json, STATE=Path(state))
    globals()["VERSIONS_FILE"] = Path(state) / "pkg-versions.json"
    globals().update(zip(("_pkg_versions", "_pkg_checked", "_pkg_remembered"),
                         load_versions()))


# The catalog lives beside the code rather than in it: config/packages.json,
# which ships to /opt/builderbot/config/ and so sits at the same place relative
# to this file in the image and in a checkout. Adding a package is an entry
# there plus a recipe in bb's sdk_install — the recipes are the half that
# cannot be a table, since every one of them installs differently.
PACKAGES_FILE = HERE.parent.parent / "config" / "packages.json"


def load_packages():
    """The package catalog, or an empty one.

    Empty rather than an exception: this runs at import, and a missing or
    malformed file must leave a dashboard that says the tab is empty, not one
    that will not start. Every field is checked because the page renders them.
    """
    try:
        doc = json.loads(PACKAGES_FILE.read_text())
        rows = doc["packages"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        if not all(isinstance(r.get(k), str) and r.get(k)
                   for k in ("name", "label", "probe", "about")):
            continue
        out.append({k: r[k] for k in ("name", "label", "probe", "about")})
    return out


PACKAGES = load_packages()

# What the last check found, kept on the state volume. Held only in memory
# until now, which meant a dashboard restart — or a container update — wiped
# every version the tab had been told, and the rows for things that are not
# installed went back to saying nothing at all. The answers are a network
# round trip each and they do not go stale quickly; the tab says how old they
# are and the button refreshes them.
VERSIONS_FILE = None                  # set by configure()


def load_versions():
    try:
        v = json.loads(VERSIONS_FILE.read_text())
    except (OSError, ValueError):
        return {}, 0, {}
    if not isinstance(v, dict) or not isinstance(v.get("items"), dict):
        return {}, 0, {}
    known = {p["name"] for p in PACKAGES}
    out = {}
    for name, row in v["items"].items():
        # Shape-checked like every other stored file: it is read into a page
        # that renders it, and a hand edit must not become a rendered value.
        if name not in known or not isinstance(row, dict):
            continue
        if not all(isinstance(row.get(k), str) for k in ("installed", "latest", "status")):
            continue
        out[name] = {k: row[k][:64] for k in ("installed", "latest", "status")}
        if isinstance(row.get("bytes"), str) and row["bytes"].isdigit():
            out[name]["bytes"] = row["bytes"][:20]
    sizes = {}
    for name, kb in (v.get("sizes") or {}).items():
        if name in known and isinstance(kb, int) and kb >= 0:
            sizes[name] = kb
    at = v.get("at")
    return out, at if isinstance(at, int) and at > 0 else 0, sizes


# One install at a time, in a worker thread, because these are minutes long
# and megabytes wide: a request that waited for them would time out, and two
# at once would fight over the same sdkmanager lock.
_pkg_lock = threading.Lock()
# What `bb sdk check` last reported: {name: {installed, latest, status}}.
# Filled only when asked — every probe in it reaches the network, so doing it
# on the fifteen-second poll would be a background service nobody requested —
# and reloaded from disk at startup, so what it found outlives this process.
# ...and what it last weighed on disk, which is the honest answer to "how big
# is this" for a package that has been installed here before — better than any
# number typed into a file, and better than the download, which for Swift is a
# gigabyte that unpacks to three.
_pkg_versions, _pkg_checked, _pkg_remembered = {}, 0, {}
_pkg_job = {"running": False, "queue": [], "current": "", "action": "",
            "log": [], "done": [], "failed": [], "auto": False}
_sdk_root_cache = []


# The bb that ships with this server.py: /opt/builderbot/scripts/bb in the
# image, the checkout's copy under `bb dashboard dev`. Same relative position
# either way, and it keeps the pair in step — a page offering a subcommand
# the bb beside it does not have would be a button that cannot work.
# BB_BIN exists for the test harness, which points it at a stub: the suite
# must be able to drive install and remove without downloading gigabytes.
BB = os.environ.get("BB_BIN") or str(HERE.parent / "bb")


def sdk_root_path():
    """Where bb decided the SDK root is — asked once, since it cannot change
    without a container restart."""
    if not _sdk_root_cache:
        r = run([BB, "sdk", "root"], timeout=15)
        _sdk_root_cache.append(r["out"].strip() if r["code"] == 0 else "")
    return _sdk_root_cache[0]


def _pkg_cands(probe):
    """Where a package could be, in the order worth looking."""
    if probe.startswith("android-image:"):
        # A system-image flavour, not a package directory: they all live under
        # system-images/android-NN/<kind>/, so "is a TV image installed" is a
        # question about the kind, not about the tree existing. Sharing one
        # probe made every flavour claim to be installed the moment any image
        # was — the reassuring wrong answer again.
        kind = probe.split(":", 1)[1]
        base = Path(os.environ.get("ANDROID_HOME", "/opt/android-sdk")) / "system-images"
        cands = []
        try:
            cands = sorted(d / kind for d in base.iterdir() if d.is_dir())
        except OSError:
            pass
    elif probe.startswith("android:"):
        cands = [Path(os.environ.get("ANDROID_HOME", "/opt/android-sdk")) / probe.split(":", 1)[1]]
    else:
        root = sdk_root_path()
        # The share first, then the home volume — anything installed before a
        # share was mapped lives there, and calling it uninstalled while 8GB
        # of it sits on disk is how this went wrong once already.
        home = Path(os.environ.get("BUILDER_HOME", str(Path.home()))) / ".sdk"
        cands = [Path(root) / probe] if root else []
        if str(home) != root:
            cands.append(home / probe)
    return cands


def _pkg_paths(probe):
    """Every directory a package actually occupies.

    Resolved rather than assumed: the android directories are symlinks into
    the share, and the whole point of the card is showing where a thing
    actually landed.

    Usually one. A system-image flavour is the exception — it can be installed
    at several API levels at once, all of them real directories and all of
    them its footprint — which is why this returns a list and the size adds
    them up."""
    out = []
    for p in _pkg_cands(probe):
        try:
            if p.is_dir() and any(p.iterdir()):
                out.append(str(p.resolve()))
        except OSError:
            continue
        # The share and the home volume are two places to look for one
        # installation, not two installations to add together.
        if out and not probe.startswith("android-image:"):
            break
    return out


def _pkg_path(probe):
    """The directory a package occupies, or "" when it is not installed."""
    paths = _pkg_paths(probe)
    return paths[0] if paths else ""


# The installed versions, cached against the set of installed paths: reading
# them costs a couple of seconds across every toolchain (dotnet and swift are
# slow to say their own name), and they cannot change while nothing is being
# installed. Re-read when that set does.
_pkg_local = {"key": None, "versions": {}}


def local_versions():
    key = tuple(sorted((p["name"], _pkg_path(p["probe"])) for p in PACKAGES))
    if _pkg_local["key"] == key:
        return _pkg_local["versions"]
    out = {}
    r = run([BB, "sdk", "versions"], timeout=180)
    for ln in r["out"].splitlines():
        f = ln.rstrip().split("\t")
        if len(f) == 4 and f[1] not in ("", "-"):
            out[f[0]] = f[1]
    _pkg_local.update(key=key, versions=out)
    return out


# Measured sizes in KB, {name: kb}. The catalog's "~3 GB" is a download
# estimate written by hand; once something is on disk there is a real number,
# and it is not the estimate — a toolchain grows after installation (a pub
# cache, a .NET workload, an NDK unpacked bigger than it shipped).
#
# du walks the tree to get it, which is instant on a warm share and seconds on
# a cold one (a system-image tree here is 30GB), so it never runs on a request
# thread: the payload serves the last measurement and says whether one is in
# flight, and the page asks again shortly when it is. Re-measured on a TTL
# rather than cached forever, because "it grew" is exactly what this is for.
# How long a percentage may sit unchanged before the row stops quoting it.
#
PKG_SIZE_TTL = 120
_pkg_sizes = {}
_pkg_sized_at = [0.0]
_pkg_sizing = [False]


def save_versions():
    write_json(VERSIONS_FILE, {"at": _pkg_checked, "items": _pkg_versions,
                               "sizes": _pkg_remembered})


def _measure_sizes():
    out = {}
    for p in PACKAGES:
        total, answered = 0, False
        for path in _pkg_paths(p["probe"]):
            r = run(["du", "-sk", path], timeout=300)
            head = r["out"].split("\t")[0].strip() if r["code"] == 0 else ""
            if head.isdigit():
                total += int(head)
                answered = True
        # `answered`, not a non-zero total: du rounds a nearly-empty tree to
        # 0 KB on some filesystems, and "0 KB" is a measurement while a du
        # that failed is not one. Falling back to the estimate on a zero would
        # quietly show the catalog's guess for something that is on the disk.
        if answered:
            out[p["name"]] = total
    _pkg_sizes.clear()
    _pkg_sizes.update(out)
    # Remembered past the removal: having installed a thing once is how this
    # box knows what it costs, and that knowledge should outlive it.
    if out:
        _pkg_remembered.update(out)
        save_versions()
    _pkg_sized_at[0] = time.monotonic()
    _pkg_sizing[0] = False


def _size_refresh():
    """Kick a measurement if what we have is older than the TTL. One at a
    time: du on thirteen trees twice over would fight itself for the disk."""
    if _pkg_sizing[0] or time.monotonic() - _pkg_sized_at[0] < PKG_SIZE_TTL:
        return
    _pkg_sizing[0] = True
    threading.Thread(target=_measure_sizes, daemon=True).start()


def human_kb(kb):
    if kb >= 1024 * 1024:
        return f"{kb / 1048576:.1f} GB"
    if kb >= 1024:
        return f"{kb / 1024:.0f} MB"
    return f"{kb} KB"


def payload():
    items = []
    with _pkg_lock:
        busy = _pkg_job["running"]
    # Nothing is probed while a job runs. The package being installed has a
    # directory that is filling up, and every probe here reads a non-empty
    # directory as a finished install: a half-written NDK reported itself
    # version "installed" at 1.2GB of what turned out to be a 3.3GB tree.
    # Both were true of the moment and false about the package. The worker
    # invalidates these caches when it finishes, so the first draw afterwards
    # is a fresh reading.
    local = _pkg_local["versions"] if busy else local_versions()
    if not busy:
        _size_refresh()
    for p in PACKAGES:
        path = _pkg_path(p["probe"])
        v = _pkg_versions.get(p["name"], {})
        # Where a size comes from, in order of how much it is worth: what it
        # takes on this disk now, what it took the last time it was here, and
        # — for a package this box has never had — what the download weighs.
        # Nothing is typed into the catalog, because a number typed there is
        # wrong the next time upstream ships.
        kb = _pkg_sizes.get(p["name"]) if path else None
        origin = "measured on disk"
        if kb is None:
            kb = _pkg_remembered.get(p["name"])
            origin = "measured the last time it was installed"
        size, dl = "", v.get("bytes")
        if kb is not None:
            size = human_kb(kb)
        elif dl:
            # The download, not the footprint: a gigabyte of Swift unpacks to
            # three. Said as a download, so it does not read as one.
            size = human_kb(int(dl) // 1024) + " download"
            origin = "the size of the download, from upstream"
        else:
            origin = ""
        items.append({**{k: p[k] for k in ("name", "label", "about")},
                      "installed": bool(path), "path": path,
                      "size": size, "size_from": origin,
                      # The version is local knowledge and always shown; the
                      # state, and what it would move to, are only ever what a
                      # check said.
                      "version": v.get("installed") or local.get(p["name"], ""),
                      "latest": v.get("latest", ""),
                      "state": v.get("status", "")})
    with _pkg_lock:
        job = {k: (list(v) if isinstance(v, list) else v)
               for k, v in _pkg_job.items()}
    return {"root": sdk_root_path(),
            "shared": is_mount(sdk_root_path()),
            "checked": _pkg_checked,
            "sizing": _pkg_sizing[0],
            "items": items, "job": job}


def is_mount(path):
    """Whether the SDK root is a mapped share rather than a directory on the
    home volume — the difference between "kept outside the image" and "kept
    alongside everything else"."""
    if not path:
        return False
    try:
        with open("/proc/self/mountinfo") as f:
            return any(line.split()[4] == path for line in f)
    except OSError:
        return False


# A progress-bar frame, dropped from the log tail. Nothing reads these for
# meaning any more; they are simply noise that would otherwise fill the sixteen
# lines kept from a job, since sdkmanager redraws its bar with carriage returns
# and playwright draws its own with box characters.
_PROGRESS_FRAME = re.compile(r"^(\[[=\s]*\]\s*\d+%|\|[\u25a0\s]*\|\s*\d+%)")

# The decimal matters: on "100.0%" a bare \d{1,3} match lands on the 0 after
# the point and reports nought percent for a finished download.
def _job_tail(out, keep=16):
    """The useful end of a command's output — the frames dropped."""
    lines = [ln.strip() for ln in out.splitlines()]
    return [ln for ln in lines if ln and not _PROGRESS_FRAME.match(ln)][-keep:]


def job_is_automatic():
    """Whether the job in the way is the daily check rather than a person's.

    The refusal an operator sees depends on it, and being told "an install is
    already running" when nobody started an install wastes an evening.
    """
    with _pkg_lock:
        return bool(_pkg_job.get("auto"))


def _pkg_worker():
    """Run the queued work one item at a time, keeping a tail of the output.

    Everything it can do is `bb sdk <verb> <name>` for a name that came out of
    PACKAGES — the page posts an index into the table, never a command, which
    is the same rule the macro buttons follow. The verb is decided here rather
    than by the page: "install" on something already present means update it,
    and one button that does the obvious thing beats two that need explaining.
    """
    while True:
        with _pkg_lock:
            if not _pkg_job["queue"]:
                # Stored once the whole check is done rather than after each
                # package: thirteen rewrites of the same file, each a temp file
                # and a rename, to record one answer at a time.
                if _pkg_job["action"] == "check":
                    globals()["_pkg_checked"] = int(time.time())
                    save_versions()
                _pkg_job["running"] = False
                _pkg_job["current"] = ""
                return
            name = _pkg_job["queue"].pop(0)
            action = _pkg_job["action"]
            _pkg_job["current"] = name
        verb = action
        if action == "install":
            probe = next((p["probe"] for p in PACKAGES if p["name"] == name), name)
            verb = "update" if _pkg_path(probe) else "install"
        with _pkg_lock:
            _pkg_job["log"].append(f"$ bb sdk {verb} {name}")

        # Nothing is read out of the output beyond the log. Every recipe
        # meters differently and several mislead by accident — one fraction
        # across a whole operation, a count that parks for minutes, five files
        # metered from zero apiece, the word "download" sitting inside the noun
        # "installer" — and a row reporting any of it faithfully still read as
        # broken. The row says what it is doing and animates; the output goes
        # to the log, where it can be read afterwards.
        r = run([BB, "sdk", verb, name], timeout=3600)
        with _pkg_lock:
            if action == "check":
                # TSV out: name, installed, latest, status.
                for ln in r["out"].splitlines():
                    f = ln.rstrip().split("\t")
                    if len(f) >= 4 and f[3] != "local":
                        row = {"installed": f[1], "latest": f[2], "status": f[3]}
                        # The download, when the catalog names a URL that is
                        # the payload. It is not the footprint — a gigabyte of
                        # Swift unpacks to three — so it is only ever used for
                        # a package this box has never had.
                        if len(f) > 4 and f[4].isdigit():
                            row["bytes"] = f[4]
                        _pkg_versions[f[0]] = row
                _pkg_job["log"].append(f"{name}: {_pkg_versions.get(name, {}).get('status', '?')}")
            else:
                _pkg_job["log"].extend(_job_tail(r["out"]))
                if r["code"] != 0:
                    # The exit code, in words, because the output above may not
                    # say anything: a killed sdkmanager prints nothing at all
                    # and a tail of progress bars reads exactly like a run that
                    # simply stopped. 137 is the OOM killer, 124 a timeout.
                    _pkg_job["log"].append(f"{name}: {verb} failed (exit {r['code']})")
            _pkg_job["log"] = _pkg_job["log"][-60:]
            (_pkg_job["done"] if r["code"] == 0 else _pkg_job["failed"]).append(name)
        if action in ("install", "remove", "update"):
            _pkg_local["key"] = None      # whatever just happened moved a version
            _pkg_sized_at[0] = 0.0        # ...and changed what is on the disk


def start_job(action, names, auto=False):
    """Queue a package job, unless one is already going. False if it is."""
    with _pkg_lock:
        if _pkg_job["running"]:
            return False
        _pkg_job.update(running=True, queue=list(names), action=action,
                        current="", log=[], done=[], failed=[], auto=auto)
    threading.Thread(target=_pkg_worker, daemon=True).start()
    return True


# A version check on the way up, and once a day after that.
#
# The answers are a network round trip apiece and they do not go stale in
# minutes, so this is a slow background errand rather than anything the poll
# does: eight seconds of it, a while after boot so that a container coming up
# is not doing this alongside everything else it does at start. It steps aside
# for anything the operator started — a check that queued itself behind an
# install would hold the tab hostage — and tries again later.
PKG_CHECK_EVERY = 86400
# Late enough that the startup hooks have finished. 50-android.sh can be
# running sdkmanager when the dashboard comes up, and two of those on one SDK
# root is a fight over the same lock.
PKG_CHECK_DELAY = int(os.environ.get("PKG_CHECK_DELAY", "180"))
AUTOCHECK = os.environ.get("PKG_AUTOCHECK", "1") != "0"


def versions_loop():
    time.sleep(PKG_CHECK_DELAY)
    due = 0                       # the first pass always checks: a container
    while True:                   # that has just come up gets fresh answers
        if PACKAGES and time.time() >= due and not _pkg_job["running"]:
            if start_job("check", [p["name"] for p in PACKAGES], auto=True):
                due = time.time() + PKG_CHECK_EVERY
        time.sleep(300)
