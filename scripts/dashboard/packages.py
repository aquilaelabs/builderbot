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
import contextlib
import json
import os
import re
import signal
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
nodes = None          # the node store, once the server has opened it (phase 6)


def configure(*, run, write_json, state):
    """Hand over the server's helpers and read what is on disk."""
    globals().update(run=run, write_json=write_json, STATE=Path(state))
    globals()["VERSIONS_FILE"] = Path(state) / "pkg-versions.json"
    globals().update(zip(("_pkg_versions", "_pkg_checked", "_pkg_remembered"),
                         load_versions()))


# The catalog lives beside the code rather than in it: config/packages.json,
# which ships to /opt/builderbot/config/ and so sits at the same place relative
# to this file in the image and in a checkout.
#
# Adding a package is an entry there and nothing else, as long as it fits one
# of the five kinds sdk_install dispatches on (tarball, script, git, command,
# sdkmanager) — plus a version resolver in sdkmeta.py when upstream publishes
# its releases in a shape none of the existing ones read. Node.js was exactly
# that: one catalog row, one resolver, no install code.
#
# What is NOT in the catalog, and is worth knowing before adding one: where a
# package LANDS is written down in several places that must agree — the
# version probe in sdk.sh's sdk_check_one, sdk_env_snippet's PATH lines, and
# the agent's own STORE_TOOLS and STORE_PATHS. They have drifted (roadmap
# #18).
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
        row = {k: r[k] for k in ("name", "label", "probe", "about")}
        # ...and the platforms it works on, when the catalog says. A list of
        # "<os>/<arch>", `*` allowed in the arch position. Projected here
        # like the four above rather than taken whole, so a field the page
        # does not render cannot arrive through this — and checked, because
        # a malformed one would otherwise refuse every install silently.
        plats = [x for x in (r.get("platforms") or []) if isinstance(x, str) and "/" in x]
        if plats:
            row["platforms"] = plats[:8]
        reqs = [x for x in (r.get("requires") or []) if isinstance(x, str) and x]
        if reqs:
            row["requires"] = reqs[:4]
        lay = r.get("layout")
        if isinstance(lay, dict):
            row["layout"] = {
                "bin": [str(x) for x in (lay.get("bin") or [])][:8],
                "env": {str(k)[:40]: str(v) for k, v in (lay.get("env") or {}).items()},
                "tool": str(lay.get("tool") or ""),
                "reports": str(lay.get("reports") or ""),
            }
        out.append(row)
    # Sorted here rather than trusted from the file, so a package added at the
    # end of the catalog still lands where somebody would look for it. Leading
    # punctuation is ignored: ".NET" belongs under N, not above everything.
    out.sort(key=lambda p: re.sub(r"^[^0-9a-z]+", "", p["label"].lower()))
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
        if isinstance(row.get("bytes"), str) and row["bytes"].lstrip("~").isdigit():
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
# `errors` rather than a log: the tab used to end in a scrolling box of every
# line every command printed, which was ninety-nine parts progress frames to
# one part the sentence that mattered. What mattered was always *which package
# failed and why*, so that is what is kept — per package, on its own row.
_pkg_job = {"running": False, "queue": [], "current": "", "action": "",
            "errors": {}, "done": [], "failed": [], "auto": False,
            "aborting": False}
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
    if probe.startswith("android:"):
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

    Usually one. A system-image flavor is the exception — it can be installed
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
        if out:
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


# The android system images on disk, cached like the sizes are: `du` over
# forty gigabytes is not something to do on a poll.
_images = {"at": 0.0, "rows": []}
IMAGES_TTL = 300


def installed_images(refresh=True):
    """One row per android system image actually installed here.

    Not catalog packages: which exist depends on what has been installed, and
    the ANDROID_SYSTEM_IMAGES baseline puts them there without anyone choosing
    them one at a time. They accumulate — several API levels' worth were on
    this box, most of them for versions nobody had configured in months — and
    until now the tab could neither show nor remove one.

    refresh=False serves what is cached without going back to disk, which is
    what a running job wants: the tree is being written to and a size read
    from it mid-install describes the moment rather than the package. The
    first version of this returned nothing at all while a job ran, and since
    the section is only rebuilt when the tab redraws, the images stayed gone
    afterwards until something unrelated forced one.
    """
    if not refresh or time.monotonic() - _images["at"] < IMAGES_TTL:
        return _images["rows"]
    rows = []
    r = run([BB, "sdk", "images"], timeout=300)
    if r["code"] == 0:
        for line in r["out"].splitlines():
            f = line.rstrip("\n").split("\t")
            if len(f) >= 4 and f[0].startswith("system-images;") and f[3].isdigit():
                rows.append({"id": f[0], "api": f[1], "kind": f[2],
                             "size": human_kb(int(f[3])),
                             # Which AVDs are built on it. An image nothing
                             # names is one that can go; an image an AVD names
                             # is one that AVD cannot boot without.
                             "avds": [a for a in (f[4].split(",") if len(f) > 4 else [])
                                      if a]})
    _images.update(at=time.monotonic(), rows=rows)
    return rows


_choices = {"at": 0.0, "rows": [], "flavors": [], "loading": False}
_choices_lock = threading.Lock()
CHOICES_TTL = 3600            # the index changes when Google ships a level


def image_choices():
    """Every system image that could be installed, and what each flavor is for.

    Two questions the operator cannot answer from here otherwise: which API
    levels exist, and what one weighs before it is fetched. Both come out of
    sdkmanager's own index, which is the only place a download size lives
    before the download — bb reads it, this asks bb.

    An hour's cache. The answer changes when Google ships an API level, and
    the rows are also what the picker is drawn from, so it must not be a
    network round trip per redraw.
    """
    if time.monotonic() - _choices["at"] < CHOICES_TTL and _choices["rows"]:
        return _choices
    # Off the request. Four XML indexes on a cold cache is a second or two of
    # network, and doing it inline made the first draw of the whole tab wait
    # for Google — for a picker most visits never touch. The tab says it is
    # reading, and the picker arrives on the next poll.
    with _choices_lock:
        if _choices["loading"]:
            return _choices
        _choices["loading"] = True
    threading.Thread(target=_load_choices, daemon=True).start()
    return _choices


def _load_choices():
    rows, flavors = [], []
    r = run([BB, "sdk", "images", "--available"], timeout=120)
    if r["code"] == 0:
        for line in r["out"].splitlines():
            f = line.rstrip().split("\t")
            if len(f) == 4 and f[0].startswith("system-images;") and f[3].isdigit():
                rows.append({"id": f[0], "api": f[1], "kind": f[2],
                             "size": human_kb(int(f[3]) // 1024)})
    r = run([BB, "sdk", "flavors"], timeout=30)
    if r["code"] == 0:
        for line in r["out"].splitlines():
            f = line.rstrip().split("\t")
            if len(f) >= 3:
                flavors.append({"kind": f[0], "label": f[2],
                                "about": f[3] if len(f) > 3 else ""})
    with _choices_lock:
        if rows:
            _choices.update(at=time.monotonic(), rows=rows, flavors=flavors)
        _choices["loading"] = False


def is_choosable_image(name):
    """Is this one of the image ids the picker offered? Same rule as every
    executing endpoint here: the server acts only on names it handed out."""
    want = name.removeprefix("android:")
    return any(r["id"] == want for r in image_choices()["rows"])


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
        # A check answer about a package that has since been installed or
        # removed describes a state that no longer holds, so it is not an
        # answer any more. The worker drops these as it goes; this catches the
        # ones already on disk from before it did.
        if bool(path) != ((v.get("installed") or "-") != "-"):
            v = {}
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
            about = dl.startswith("~")
            size = ("~" if about else "") + human_kb(int(dl.lstrip("~")) // 1024) + " download"
            origin = ("an approximation — a git clone has no size to ask for"
                      if about else "the size of the download, from upstream")
        else:
            origin = ""
        items.append({**{k: p[k] for k in ("name", "label", "about")},
                      "installed": bool(path), "path": path,
                      "size": size, "size_from": origin,
                      # The version is local knowledge and always shown; the
                      # state, and what it would move to, are only ever what a
                      # check said.
                      # A dash is how a check writes "nothing installed", and
                      # it is a truthy string: it stood in front of the local
                      # reading and left an installed row claiming no version.
                      "version": (v.get("installed") or "").strip("-")
                                 and v["installed"] or local.get(p["name"], ""),
                      "latest": v.get("latest", ""),
                      "state": v.get("status", "")})
    with _pkg_lock:
        job = {k: (list(v) if isinstance(v, list) else v)
               for k, v in _pkg_job.items()}
    choices = image_choices()
    here = {i["id"] for i in installed_images(refresh=not busy)}
    return {"images": installed_images(refresh=not busy),
            # What could be added, minus what is already here.
            "addable": [c for c in choices["rows"] if c["id"] not in here],
            "flavors": choices["flavors"],
            "images_loading": bool(choices["loading"]),
            "root": sdk_root_path(),
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


def job_rev():
    """A token for "the install job moved", for the revisions poll. All in
    memory: the job's state, what it is on, and how far through it is."""
    j = _pkg_job
    return f"{j['running']}:{j['action']}:{j['current']}:{len(j['done'])}:{len(j['failed'])}"


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
            # Whatever it said last time is about a state that no longer holds;
            # this run is the new answer.
            _pkg_job["errors"].pop(name, None)

        # The child, so that an abort can reach it. bb's own EXIT trap removes
        # whatever the install had created, which is why this kills the process
        # rather than tearing the directory out from under it.
        #
        # Nothing is read out of the output while it runs. Every recipe meters
        # differently and several mislead by accident — one fraction across a
        # whole operation, a count that parks for minutes, five files metered
        # from zero apiece, the word "download" sitting inside the noun
        # "installer" — and a row reporting any of it faithfully still read as
        # broken. The row says what it is doing and animates. The output is
        # looked at only when the thing fails, which is the only time anybody
        # wanted it.
        r = run([BB, "sdk", verb, name], timeout=3600, register=_hold_child)
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
                        # A leading tilde is the catalog saying this one is
                        # an approximation rather than a measurement, and it
                        # travels all the way to the row.
                        if len(f) > 4 and f[4].lstrip("~").isdigit():
                            row["bytes"] = f[4]
                        _pkg_versions[f[0]] = row
                pass
            elif r["code"] != 0:
                # The end of what it said, plus the exit code in words: a
                # killed sdkmanager prints nothing at all, and a tail of
                # progress bars reads exactly like a run that simply stopped.
                # 137 is the OOM killer, 124 a timeout.
                said = _job_tail(r["out"], keep=4)
                _pkg_job["errors"][name] = " · ".join(
                    said + [f"{verb} failed (exit {r['code']})"])[-400:]
            (_pkg_job["done"] if r["code"] == 0 else _pkg_job["failed"]).append(name)
        if action in ("install", "remove", "update"):
            _images["at"] = 0.0           # an image may have just gone
            _pkg_local["key"] = None      # whatever just happened moved a version
            _pkg_sized_at[0] = 0.0        # ...and changed what is on the disk
            # ...and made the last check's answer about this package a
            # statement about a state that no longer holds. An unchecked row
            # says nothing, which is the honest thing for it to say until
            # somebody asks again.
            with _pkg_lock:
                _pkg_versions.pop(name, None)
                save_versions()


# The process a job is running right now, so that Abort has something to
# interrupt. A list rather than a value because it is written from the worker
# thread and read from a request thread.
_pkg_child = [None]


def _hold_child(proc):
    with _pkg_lock:
        _pkg_child[0] = proc


def is_installed_image(name):
    """Whether a name is one of the images this server just listed.

    The rule everything executing here follows: what reaches a command line is
    a string this server chose. The page posts back an id out of the list it
    was given, and it is checked against that list again before it is used.
    """
    return name.startswith("android:") and any(
        r["id"] == name[len("android:"):] for r in installed_images())


def abort_job():
    """Stop the running job after the package it is on.

    The queue is emptied so nothing further starts, and the child is asked to
    stop: bb removes the half-installed directory on its way out, which is the
    same cleanup a failed install gets, because a killed install and a failed
    one leave exactly the same mess. Everything already installed stays — the
    abort is for the rest of the queue, not for undoing what worked.
    """
    with _pkg_lock:
        if not _pkg_job["running"]:
            return False
        _pkg_job["queue"] = []
        _pkg_job["aborting"] = True
        pass
        proc = _pkg_child[0]
    if proc is not None:
        try:
            # The group, not the process: bb is waiting on a curl or a tar, and
            # killing only the shell leaves the download running.
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass                       # it finished between the check and here
    return True


# ---------------------------------------------------------------------------
# packages on another node (docs/nodes.md §6)
#
# The catalog is this one; the state is the node's. Its census reports the
# toolchains it has (`reported.toolchains`, probed by the agent the way `bb
# sdk` probes here) and its packages store's headroom, and an install there
# is a `package` job the agent runs with the bundle this controller ships —
# bb and its library — against that store. Nothing here guesses what a node
# has from what it was asked to install.

def payload_for_node(nid):
    n = nodes.node(nid) if nodes else None
    if not n:
        return {"error": "no such node"}
    rep = n.get("reported") or {}
    tc = rep.get("toolchains") or {}
    pv = rep.get("packages_versions") or {}
    if not isinstance(pv, dict):
        pv = {}
    plat = platform_of(n)
    store = (rep.get("stores") or {}).get("packages") or {}
    items = []
    # What is IN the store, by directory, which is where bb sdk puts things:
    # <root>/<name>, and android's parts under <root>/android/. The census's
    # `toolchains` is a six-name placement summary and reading it as an
    # inventory called the emulator, the NDK, Playwright and Zig missing on
    # a share that held all four. Directory names first, the summary only
    # for the version string it happens to carry.
    top = set(((rep.get("store_dirs") or {}).get("top")) or [])
    andr = set(((rep.get("store_dirs") or {}).get("android")) or [])
    known = bool(top or andr)
    for p in PACKAGES:
        probe, name = p["probe"], p["name"]
        if probe.startswith("android:"):
            here = probe.split(":", 1)[1] in andr
        elif probe == "android-tools":
            here = bool({"cmdline-tools", "platform-tools"} & andr)
        else:
            here = probe in top
        # A node that has not reported its store yet is not evidence of
        # absence, so say nothing rather than "not installed".
        # The node's own `bb sdk versions` first — the same generator this
        # controller runs for its own list, so one store is described one
        # way. The census's toolchains dict is the fallback for an agent too
        # old to report it, and it is a placement summary rather than an
        # inventory: it answers for six names, says "present" where it cannot
        # parse, and hands back an unstripped "go version go1.27.0
        # linux/amd64". That difference is what the operator was looking at.
        have = pv.get(name) or tc.get(
            {"jdk": "java", "android:emulator": "emulator"}.get(probe, probe))
        kb = _pkg_remembered.get(name)
        items.append({**{k: p[k] for k in ("name", "label", "about")},
                      # Said on the row, so a package this node cannot have
                      # reads that way rather than offering an install that
                      # is refused at the press.
                      "wrong_platform": "" if supports(p, plat) else
                          ", ".join(p.get("platforms") or ["linux/amd64"]),
                      "installed": here, "unknown": not known,
                      "path": "", "version": (have if isinstance(have, str) else "") or "",
                      "size": human_kb(kb) if kb else "",
                      "size_from": "measured the last time it was installed here" if kb else "",
                      "latest": "", "state": ""})
    items.sort(key=lambda x: (not x["installed"], x["label"].lower()))
    job = None
    if nodes:
        for j in nodes.jobs_for(node_id=nid, type="package", active=True, n=1):
            job = {"running": True, "action": (j.get("spec") or {}).get("action", ""),
                   "queue": (j.get("spec") or {}).get("names", []), "current": j.get("step", ""),
                   "log": nodes.job_tail(j["id"], 1200).splitlines()[-16:], "done": [],
                   "failed": [], "aborting": bool(j.get("cancel")), "node": nid, "id": j["id"]}
            break
        if job is None:
            # The last FINISHED one, so the tab can clear what it selected.
            # Nothing did, on a node: done and failed were hardcoded empty
            # and the row vanished the moment the job ended, so every tick
            # survived and the next press re-sent packages that had already
            # landed — "installing 2" with one left to do.
            #
            # Both lists come from the census rather than from the job's log:
            # what is in the store now is the only thing actually true, and
            # it is self-correcting — a job that half-worked reports exactly
            # the packages that did land as done, whatever its exit code was.
            for j in nodes.jobs_for(node_id=nid, type="package", n=1):
                if j.get("state") not in ("succeeded", "failed", "canceled"):
                    break
                sp = j.get("spec") or {}
                names = [str(x) for x in (sp.get("names") or [])]
                act = sp.get("action") or "install"
                here = {i["name"] for i in items if i["installed"]}
                done = [x for x in names if (x in here) == (act == "install")]
                job = {"running": False, "action": act, "queue": [], "current": "",
                       "done": done, "failed": [x for x in names if x not in done],
                       "aborting": False, "node": nid, "id": j["id"]}
                break
    shared = [x["name"] for x in store_sharers(nid)]
    return {"node": nid, "name": n["name"], "live": bool(n.get("live")),
            "shared_with": shared,
            "root": store.get("path") or "", "free_mb": store.get("free_mb"),
            "shared": False, "checked": 0, "sizing": False,
            "images": [], "addable": [], "flavors": [], "images_loading": False,
            "items": items, "job": job or {"running": False}}


def _store_share(n):
    """What identifies this node's packages store, or None.

    Two machines pointing `packages` at one share ARE one store, and the
    controller has to know which pairs those are: the same path STRING says
    nothing — /var/lib/builderbot/packages is every node's default and is a
    different disk on each.

    The store's own id first (nodes.store_id — a marker file inside it),
    because it is the only answer that survives the transport differing. On
    this box the SDK share is reached through Unraid's FUSE layer by the
    controller (fstype fuse.shfs, source "shfs") and over NFS by the sandbox
    (192.168.1.15:/mnt/user/development/SDK); neither string can be derived
    from the other, so the pair was invisible and the one-install-at-a-time
    arbitration never engaged for it.

    The mount source stays as the fallback, for a node whose store has no
    marker yet — a read-only share, or an agent too old to report the id.
    """
    rep = n.get("reported") or {}
    store = (rep.get("stores") or {}).get("packages") or {}
    path = store.get("path") or ""
    if store.get("id"):
        return ("id", store["id"])
    if not path:
        return None
    best = None
    for m in rep.get("mounts") or []:
        mp = str(m.get("path") or "").rstrip("/")
        if mp and (path == mp or path.startswith(mp + "/")):
            if best is None or len(mp) > len(best[0]):
                best = (mp, str(m.get("source") or ""))
    if not best or not best[1]:
        return None                      # a path of the node's own
    return (best[1], path[len(best[0]):])


def store_sharers(node_id):
    """Every other node whose packages store is the same share as this
    one's. Empty for the ordinary arrangement, one store per node."""
    if not nodes:
        return []
    me = nodes.node(node_id)
    mine = _store_share(me) if me else None
    if not mine:
        return []
    return [n for n in nodes.node_list()
            if n["id"] != node_id and n["state"] != "retired"
            and _store_share(n) == mine]


# The census spells an arch the way uname does; the catalog uses the
# Docker/Go spelling, because that is what upstream download URLs are named
# with. One mapping, here.
_ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64",
         "armv7l": "arm", "arm": "arm"}


def layout_for_node():
    """Every package's layout, as the agent needs it: what to put on PATH,
    what variables to set, and which file proves a package is there.

    Sent at hello rather than duplicated in the agent. It used to be three
    hand-written tables — sdk_env_snippet here, STORE_TOOLS and STORE_PATHS
    on the node — that had to agree about where every package lands and did
    not: node/bin was missing from one, the android-tools probe read the
    wrong directory, and the census disagreed with the inventory, all in one
    day. The catalog is the one place that knows, and this is how a machine
    with no catalog of its own finds out.

    `dir` is where the package lives relative to the store: android's
    packages share one tree, so theirs is `android`.
    """
    out = []
    for p in PACKAGES:
        lay = p.get("layout")
        if not lay:
            continue
        name = p["name"]
        out.append({"name": name,
                    "dir": "android" if name.startswith("android:") else name,
                    "bin": lay["bin"], "env": lay["env"],
                    "tool": lay["tool"], "reports": lay["reports"]})
    return out


def node_has(n):
    """The package names already in this node's packages store, by the
    directories bb sdk puts them in. Empty when the node has not reported
    its store — which is not evidence of absence, so a caller must treat it
    as "unknown" rather than "nothing"."""
    rep = n.get("reported") or {}
    top = set(((rep.get("store_dirs") or {}).get("top")) or [])
    andr = set(((rep.get("store_dirs") or {}).get("android")) or [])
    if not (top or andr):
        return set()
    out = set()
    for p in PACKAGES:
        probe = p["probe"]
        if probe.startswith("android:"):
            here = probe.split(":", 1)[1] in andr
        elif probe == "android-tools":
            here = bool({"cmdline-tools", "platform-tools"} & andr)
        else:
            here = probe in top
        if here:
            out.add(p["name"])
    return out


def with_requires(names, have):
    """`names`, with anything they declare a requirement on put in front.

    A recipe that needed another package used to say so only in its `env`
    block: android-tools points JAVA_HOME at a sibling jdk that may not be
    there, and sdkmanager then fails with "Could not determine SDK root",
    naming neither Java nor the package that would have supplied it. The
    catalog says it now, and the requirement is pulled in rather than
    discovered.

    Requirements already in the store are left out — this adds what is
    missing, ahead of what needs it, and never re-installs. Returns
    (ordered names, what was added).
    """
    by = {p["name"]: p for p in PACKAGES}
    out, seen = [], set()

    def add(n, depth=0):
        if n in seen or depth > 4:      # a cycle in the catalog is not fatal
            return
        seen.add(n)
        for r in (by.get(n, {}).get("requires") or []):
            if r in by and r not in have:
                add(r, depth + 1)
        out.append(n)

    for n in names:
        add(n)
    return out, [n for n in out if n not in names]


def platform_of(n):
    """"<os>/<arch>" for a node, or "" when it has not said."""
    os_ = str((n or {}).get("os") or "").strip().lower()
    arch = _ARCH.get(str((n or {}).get("arch") or "").strip().lower(), "")
    return f"{os_}/{arch}" if os_ and arch else ""


def supports(pkg, plat):
    """Whether this recipe works on that platform. Absent list means the
    historical truth — this catalog only ever served linux/amd64."""
    want = pkg.get("platforms") or ["linux/amd64"]
    if not plat:
        return True                     # a node that has not said is not judged
    o, _, a = plat.partition("/")
    return any(x == plat or x == f"{o}/*" for x in want)


def unsupported(names, plat):
    """[(name, platforms)] for the ones this platform cannot have."""
    by = {p["name"]: p for p in PACKAGES}
    return [(x, ", ".join(by[x].get("platforms") or ["linux/amd64"]))
            for x in names if x in by and not supports(by[x], plat)]


def node_job(principal, nid, action, names):
    """Queue the package job. Refused, with numbers, when the store cannot
    hold what is asked — measured here the last time it was installed, so a
    package this controller never had is not gated, and the log says so."""
    if not nodes:
        return {"error": "no node store"}
    n = nodes.node(nid)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": f"{n['name']} runs no agent — toolchains are installed there by hand"}
    store = ((n.get("reported") or {}).get("stores") or {}).get("packages") or {}
    added = []
    if action == "install":
        # What these need, ahead of them. android-tools without a jdk fails
        # inside sdkmanager with a message that names neither.
        names, added = with_requires(names, node_has(n))
        # Seven of these recipes name linux-x86_64 in their URL and one names
        # ubuntu24.04, so a node of another platform would download a couple
        # of hundred megabytes and fail on exec — or install and fail later.
        # Refused by name instead. arm64 Linux needs no new agent to reach
        # this, which is why it is a live wrong answer rather than a future
        # one (roadmap #18).
        plat = platform_of(n)
        no = unsupported(names, plat)
        if no:
            return {"error": f"{n['name']} is {plat}, and "
                             + "; ".join(f"{x} is packaged for {p}" for x, p in no)
                             + ". The catalog names the platform each recipe works on; "
                               "adding another is a URL per row, not a code change."}
        need_kb = sum(_pkg_remembered.get(x, 0) for x in names)
        free = store.get("free_mb")
        if need_kb and free is not None and free * 1024 < need_kb * 1.2:
            return {"error": f"{n['name']}'s packages store has {human_kb(free * 1024)} free "
                             f"and this needs about {human_kb(int(need_kb * 1.2))} — "
                             "point the store somewhere bigger first"}
    # One install at a time — across every node that shares this store, not
    # just this one. docs/nodes.md §6 names the trap: two agents unpacking
    # into one NFS directory, or one upgrading a toolchain under another
    # mid-build, is version skew nobody can debug. The rule is enforced
    # across a shared store or it is not enforced at all.
    sharers = store_sharers(nid)
    for other in [n] + sharers:
        for j in nodes.jobs_for(node_id=other["id"], type="package", active=True, n=1):
            where = ("" if other["id"] == nid
                     else f" — it shares this packages store with {n['name']}")
            return {"error": f"a package job is already running on {other['name']}"
                             f"{where}. One at a time."}
    # ...and this container's own installer, which is not a job and so is
    # invisible to the loop above. It is the sharer that matters most here:
    # the SDK share is mounted by the controller and by the sandbox at once.
    if _pkg_job["running"] and any(o["id"] == nodes.LOCAL for o in sharers):
        return {"error": "this container is installing into the same packages store "
                         f"right now — it shares it with {n['name']}. One at a time."}
    # Installing x86-64 binaries into a store an arm64 machine reads is
    # silently wrong: the store's path carries no architecture, so nothing
    # else would catch it and the failure surfaces later as a toolchain that
    # will not execute.
    bad = [o for o in sharers if (o.get("arch") or "") and (n.get("arch") or "")
           and o["arch"] != n["arch"]]
    if bad:
        return {"error": f"{n['name']} is {n.get('arch')} and shares this packages store with "
                         f"{', '.join(o['name'] + ' (' + str(o.get('arch')) + ')' for o in bad)}"
                         " — one store cannot hold both architectures. Give it a store of its own."}
    r = nodes.job_add(principal, {"node": nid}, "package",
                      {"action": action, "names": names, "timeout": 3600})
    if r.get("ok") and added:
        r["added"] = added
    return r


def start_job(action, names, auto=False):
    """Queue a package job, unless one is already going. False if it is."""
    with _pkg_lock:
        if _pkg_job["running"]:
            return False
        # The other half of the shared-store rule: a node unpacking into the
        # store this container is about to write is the same collision, seen
        # from the other side.
        if nodes:
            with contextlib.suppress(Exception):
                for other in store_sharers(nodes.LOCAL):
                    if nodes.jobs_for(node_id=other["id"], type="package", active=True, n=1):
                        return False
        if action == "install":
            here = {p["name"] for p in PACKAGES if _pkg_path(p["probe"])}
            names, _added = with_requires(list(names), here)
        _pkg_job.update(running=True, queue=list(names), action=action,
                        current="", log=[], done=[], failed=[], auto=auto,
                        aborting=False,
                        # Fixed in phase 1 — toolchains install here — and a
                        # seam on purpose: phase 6 makes this a job placed on
                        # any node's packages store, and this call site is
                        # where the node picker's answer lands.
                        node="local")
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
