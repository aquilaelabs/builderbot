#!/usr/bin/env python3
"""Everything behind the dashboard's Tools tab.

The catalog, where a toolchain's files land, what it weighs, what version it is
and what version upstream has, and the one-job-at-a-time worker that installs,
updates, removes and checks. The server imports this and hands it two helpers;
nothing here reaches back into the server.

The division of labour with bb is the point. This module decides *when* to ask
and remembers the answers; bb decides *how*, out of config/toolchains.json,
which holds every URL, flag and argument any of it needs. Neither of them has
a toolchain name written into it.
"""
import contextlib
import hashlib
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
    globals()["VERSIONS_FILE"] = Path(state) / "toolchain-versions.json"
    globals().update(zip(("_tc_versions", "_tc_checked", "_tc_remembered",
                          "_tc_local"), load_versions(), strict=True))


# The catalog lives beside the code rather than in it: config/toolchains.json,
# which ships to /opt/builderbot/config/ and so sits at the same place relative
# to this file in the image and in a checkout.
#
# Adding a toolchain is an entry there and nothing else, as long as it fits one
# of the five kinds sdk_install dispatches on (tarball, script, git, command,
# sdkmanager), plus a version resolver in sdkmeta.py when upstream publishes
# its releases in a shape none of the existing ones read. Node.js was exactly
# that: one catalog row, one resolver, no install code.
#
# What is NOT in the catalog, and is worth knowing before adding one: where a
# toolchain LANDS is written down in several places that must agree: the
# version probe in sdk.sh's sdk_check_one, sdk_env_snippet's PATH lines, and
# the agent's own STORE_TOOLS and STORE_PATHS. They have drifted (roadmap
# #18).
TOOLCHAINS_FILE = HERE.parent.parent / "config" / "toolchains.json"


def load_toolchains():
    """The toolchain catalog, or an empty one.

    Empty rather than an exception: this runs at import, and a missing or
    malformed file must leave a dashboard that says the tab is empty, not one
    that will not start. Every field is checked because the page renders them.
    """
    try:
        doc = json.loads(TOOLCHAINS_FILE.read_text())
        rows = doc["toolchains"]
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
        # does not render cannot arrive through this, and checked, because
        # a malformed one would otherwise refuse every install silently.
        plats = [x for x in (r.get("platforms") or []) if isinstance(x, str) and "/" in x]
        if plats:
            row["platforms"] = plats[:8]
        # Whether `bb toolchains update` has a case for this recipe. Five do (a git
        # clone, two installers and sdkmanager's own), and the rest are a
        # tarball fetched and unpacked whole, where getting a newer one means
        # removing this one first. Declared rather than inferred from the
        # source kind, the same way platforms is (bug #43).
        if r.get("updatable"):
            row["updatable"] = True
        reqs = [x for x in (r.get("requires") or []) if isinstance(x, str) and x]
        if reqs:
            row["requires"] = reqs[:4]
        # The bb verbs it enables, projected like the rest: plain words only,
        # since they are drawn on the row and matched against bb's dispatch.
        verbs = [x for x in (r.get("verbs") or []) if isinstance(x, str) and x.replace("-", "").isalnum()]
        if verbs:
            row["verbs"] = verbs[:4]
        lay = r.get("layout")
        if isinstance(lay, dict):
            row["layout"] = {
                "bin": [str(x) for x in (lay.get("bin") or [])][:8],
                "env": {str(k)[:40]: str(v) for k, v in (lay.get("env") or {}).items()},
                "tool": str(lay.get("tool") or ""),
                "reports": str(lay.get("reports") or ""),
                # A file that has to exist for the toolchain to count as
                # installed, when the directory alone does not prove it.
                "needs": str(lay.get("needs") or ""),
            }
        # The machine's own packages it needs, per package manager: said on
        # the row, so what a tool pulls onto a node is known before Install,
        # not discovered in a job log.
        sysd = r.get("system")
        if isinstance(sysd, dict):
            row["system"] = {str(k)[:12]: [str(x)[:80] for x in (v or [])][:64]
                             for k, v in sysd.items() if isinstance(v, list)}
        out.append(row)
    # Sorted here rather than trusted from the file, so a toolchain added at the
    # end of the catalog still lands where somebody would look for it. Leading
    # punctuation is ignored: ".NET" belongs under N, not above everything.
    out.sort(key=lambda p: re.sub(r"^[^0-9a-z]+", "", p["label"].lower()))
    return out


TOOLCHAINS = load_toolchains()

# What the catalog says, as one short string. It is the other half of every
# cache key here: a remembered answer describes a recipe, and editing that
# recipe (a probe path, a version command, a new toolchain) makes the answer
# about something that no longer exists. Digested rather than compared whole
# so the key stays a line rather than the file.
CATALOG_DIGEST = hashlib.sha256(
    json.dumps(TOOLCHAINS, sort_keys=True, default=str).encode()).hexdigest()[:16]

# What the last check found, kept on the state volume. Held only in memory
# until now, which meant a dashboard restart (or a container update) wiped
# every version the tab had been told, and the rows for things that are not
# installed went back to saying nothing at all. The answers are a network
# round trip each and they do not go stale quickly; the tab says how old they
# are and the button refreshes them.
VERSIONS_FILE = None                  # set by configure()


def load_versions():
    try:
        v = json.loads(VERSIONS_FILE.read_text())
    except (OSError, ValueError):
        return {}, 0, {}, {"key": None, "versions": {}}
    if not isinstance(v, dict) or not isinstance(v.get("items"), dict):
        return {}, 0, {}, {"key": None, "versions": {}}
    known = {p["name"] for p in TOOLCHAINS}
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
    # The local read, which is what made the tab slow after a restart. Kept
    # only when its key still describes this box: a different set of installed
    # paths, or an edited catalog, and it is an answer about something else.
    loc = v.get("local")
    if not (isinstance(loc, dict) and isinstance(loc.get("key"), str)
            and isinstance(loc.get("versions"), dict)
            and all(isinstance(x, str) for x in loc["versions"].values())):
        loc = {"key": None, "versions": {}}
    at = v.get("at")
    # A check answers a RECIPE. Edit config/toolchains.json (a new toolchain, a
    # moved probe, a different version command) and the stored answers are
    # about something that is no longer there, so the clock is reset and the
    # loop asks again rather than waiting out the week on stale ones.
    if v.get("catalog") != CATALOG_DIGEST:
        at = 0
    return out, at if isinstance(at, int) and at > 0 else 0, sizes, loc


# One install at a time, in a worker thread, because these are minutes long
# and megabytes wide: a request that waited for them would time out, and two
# at once would fight over the same sdkmanager lock.
_tc_lock = threading.Lock()
# What `bb toolchains check` last reported: {name: {installed, latest, status}}.
# Filled only when asked: every probe in it reaches the network, so doing it
# on the fifteen-second poll would be a background service nobody requested.
# Reloaded from disk at startup, so what it found outlives this process.
# ...and what it last weighed on disk, which is the honest answer to "how big
# is this" for a toolchain that has been installed here before, better than any
# number typed into a file, and better than the download, which for Swift is a
# gigabyte that unpacks to three.
_tc_versions, _tc_checked, _tc_remembered = {}, 0, {}
# `errors` rather than a log: the tab used to end in a scrolling box of every
# line every command printed, which was ninety-nine parts progress frames to
# one part the sentence that mattered. What mattered was always *which toolchain
# failed and why*, so that is what is kept: per toolchain, on its own row.
_tc_job = {"running": False, "queue": [], "current": "", "action": "",
            "errors": {}, "done": [], "failed": [], "auto": False,
            "aborting": False}
_sdk_root_cache = []


# The bb that ships with this server.py: /opt/builderbot/scripts/bb in the
# image, the checkout's copy under `bb dashboard dev`. Same relative position
# either way, and it keeps the pair in step: a page offering a subcommand
# the bb beside it does not have would be a button that cannot work.
# BB_BIN exists for the test harness, which points it at a stub: the suite
# must be able to drive install and remove without downloading gigabytes.
BB = os.environ.get("BB_BIN") or str(HERE.parent / "bb")


def sdk_root_path():
    """Where bb decided the toolchain store root is: asked once, since it cannot change
    without a container restart."""
    if not _sdk_root_cache:
        r = run([BB, "toolchains", "root"], timeout=15)
        _sdk_root_cache.append(r["out"].strip() if r["code"] == 0 else "")
    return _sdk_root_cache[0]


def _tc_cands(probe):
    """Where a toolchain could be, in the order worth looking."""
    if probe.startswith("android:"):
        cands = [Path(os.environ.get("ANDROID_HOME", "/opt/android-sdk")) / probe.split(":", 1)[1]]
    else:
        root = sdk_root_path()
        # The share first, then the home volume: anything installed before a
        # share was mapped lives there, and calling it uninstalled while 8GB
        # of it sits on disk is how this went wrong once already.
        home = Path(os.environ.get("BUILDER_HOME", str(Path.home()))) / ".sdk"
        cands = [Path(root) / probe] if root else []
        if str(home) != root:
            cands.append(home / probe)
    return cands


def _tc_paths(probe):
    """Every directory a toolchain actually occupies.

    Resolved rather than assumed: the android directories are symlinks into
    the share, and the whole point of the card is showing where a thing
    actually landed.

    Usually one. A system-image flavor is the exception: it can be installed
    at several API levels at once, all of them real directories and all of
    them its footprint, which is why this returns a list and the size adds
    them up."""
    out = []
    for p in _tc_cands(probe):
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


def _tc_path(probe):
    """The directory a toolchain occupies, or "" when it is not installed."""
    paths = _tc_paths(probe)
    return paths[0] if paths else ""


# The installed versions, cached against the set of installed paths: reading
# them costs a couple of seconds across every toolchain (dotnet and swift are
# slow to say their own name), and they cannot change while nothing is being
# installed. Re-read when that set does.
#
# ON DISK as well as in memory, since it is what made the Toolchains tab slow to
# open after every container restart: the answer had not changed (the same
# toolchains on the same share) and the tab paid four seconds to hear it
# again. The key is what makes that safe rather than stale. It is the set of
# (toolchain, path), so anything installed or removed changes it, PLUS the
# catalog's own digest, so editing config/toolchains.json changes it too: a
# recipe whose probe or version command moved would otherwise be answered from
# a cache of what the old one said.
_tc_local = {"key": None, "versions": {}}


def _local_key():
    return "\n".join([CATALOG_DIGEST]
                      + sorted(f"{p['name']}={_tc_path(p['probe'])}"
                               for p in TOOLCHAINS))


def local_versions():
    key = _local_key()
    if _tc_local["key"] == key:
        return _tc_local["versions"]
    out = {}
    r = run([BB, "toolchains", "versions"], timeout=180)
    for ln in r["out"].splitlines():
        f = ln.rstrip().split("\t")
        if len(f) == 4 and f[1] not in ("", "-"):
            out[f[0]] = f[1]
    _tc_local.update(key=key, versions=out)
    save_versions()
    return out


# Measured sizes in KB, {name: kb}. The catalog's "~3 GB" is a download
# estimate written by hand; once something is on disk there is a real number,
# and it is not the estimate: a toolchain grows after installation (a pub
# cache, a .NET workload, an NDK unpacked bigger than it shipped).
#
# du walks the tree to get it, which is instant on a warm share and seconds on
# a cold one (a system-image tree here is 30GB), so it never runs on a request
# thread: the payload serves the last measurement and says whether one is in
# flight, and the page asks again shortly when it is. Re-measured on a TTL
# rather than cached forever, because "it grew" is exactly what this is for.
# How long a percentage may sit unchanged before the row stops quoting it.
#
TC_SIZE_TTL = 120
_tc_sizes = {}
_tc_sized_at = [0.0]
_tc_sizing = [False]


def save_versions():
    write_json(VERSIONS_FILE, {"at": _tc_checked, "items": _tc_versions,
                               "sizes": _tc_remembered,
                               "local": _tc_local,
                               # What the answers above are answers ABOUT.
                               "catalog": CATALOG_DIGEST})


def _measure_sizes():
    out = {}
    for p in TOOLCHAINS:
        total, answered = 0, False
        for path in _tc_paths(p["probe"]):
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
    _tc_sizes.clear()
    _tc_sizes.update(out)
    # Remembered past the removal: having installed a thing once is how this
    # box knows what it costs, and that knowledge should outlive it.
    if out:
        _tc_remembered.update(out)
        save_versions()
    _tc_sized_at[0] = time.monotonic()
    _tc_sizing[0] = False


def _size_refresh():
    """Kick a measurement if what we have is older than the TTL. One at a
    time: du on thirteen trees twice over would fight itself for the disk."""
    if _tc_sizing[0] or time.monotonic() - _tc_sized_at[0] < TC_SIZE_TTL:
        return
    _tc_sizing[0] = True
    threading.Thread(target=_measure_sizes, daemon=True).start()


def human_kb(kb):
    if kb >= 1024 * 1024:
        return f"{kb / 1048576:.1f} GB"
    if kb >= 1024:
        return f"{kb / 1024:.0f} MB"
    return f"{kb} KB"


def payload():
    items = []
    with _tc_lock:
        busy = _tc_job["running"]
    # Nothing is probed while a job runs. The toolchain being installed has a
    # directory that is filling up, and every probe here reads a non-empty
    # directory as a finished install: a half-written NDK reported itself
    # version "installed" at 1.2GB of what turned out to be a 3.3GB tree.
    # Both were true of the moment and false about the toolchain. The worker
    # invalidates these caches when it finishes, so the first draw afterwards
    # is a fresh reading.
    local = _tc_local["versions"] if busy else local_versions()
    if not busy:
        _size_refresh()
    for p in TOOLCHAINS:
        path = _tc_path(p["probe"])
        # The directory is there but the file that completes the toolchain is
        # not (layout.needs): not installed, so Install is offered; the
        # recipe fills the directory in rather than starting over.
        need = (p.get("layout") or {}).get("needs")
        if path and need and not os.path.exists(os.path.join(path, need)):
            path = ""
        v = _tc_versions.get(p["name"], {})
        # A check answer about a toolchain that has since been installed or
        # removed describes a state that no longer holds, so it is not an
        # answer any more. The worker drops these as it goes; this catches the
        # ones already on disk from before it did.
        if bool(path) != ((v.get("installed") or "-") != "-"):
            v = {}
        # Where a size comes from, in order of how much it is worth: what it
        # takes on this disk now, what it took the last time it was here, and
        # (for a toolchain this box has never had) what the download weighs.
        # Nothing is typed into the catalog, because a number typed there is
        # wrong the next time upstream ships.
        kb = _tc_sizes.get(p["name"]) if path else None
        origin = "measured on disk"
        if kb is None:
            kb = _tc_remembered.get(p["name"])
            origin = "measured the last time it was installed"
        size, dl = "", v.get("bytes")
        if kb is not None:
            size = human_kb(kb)
        elif dl:
            # The download, not the footprint: a gigabyte of Swift unpacks to
            # three. Said as a download, so it does not read as one.
            about = dl.startswith("~")
            size = ("~" if about else "") + human_kb(int(dl.lstrip("~")) // 1024) + " download"
            origin = ("an approximation: a git clone has no size to ask for"
                      if about else "the size of the download, from upstream")
        else:
            origin = ""
        items.append({**{k: p[k] for k in ("name", "label", "about")},
                      # The bb verbs this recipe enables, one root per recipe,
                      # so a row says what installing it adds to a session
                      # and the suite holds two recipes from claiming one.
                      "verbs": list(p.get("verbs") or []),
                      # Whether a newer version can be fetched in place, or
                      # whether getting one means removing this first.
                      "updatable": bool(p.get("updatable")),
                      # What it needs, and what needs it, so a toolchain that
                      # exists to serve another says so rather than looking
                      # like an unexplained independent choice.
                      "needs": list(p.get("requires") or []),
                      "needed_by": sorted(o["name"] for o in TOOLCHAINS
                                          if p["name"] in (o.get("requires") or [])),
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
    with _tc_lock:
        job = {k: (list(v) if isinstance(v, list) else v)
               for k, v in _tc_job.items()}
    return {"root": sdk_root_path(),
            "shared": is_mount(sdk_root_path()),
            "checked": _tc_checked,
            "sizing": _tc_sizing[0],
            "items": items, "job": job}


def is_mount(path):
    """Whether the toolchain store root is a mapped share rather than a directory on the
    home volume: the difference between "kept outside the image" and "kept
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
    """The useful end of a command's output, with the frames dropped."""
    lines = [ln.strip() for ln in out.splitlines()]
    return [ln for ln in lines if ln and not _PROGRESS_FRAME.match(ln)][-keep:]


def job_rev():
    """A token for "anything this tab draws has moved", for the revisions poll.

    Everything the Toolchains tab used to keep its own timer for. It polled at
    half a second while a job ran and at eight seconds otherwise, and the
    eight-second half was there for the one fact this used to leave out: the
    version check. It is in memory here and costs nothing to report, so the
    tab watches this instead of holding a third clock.

    The store root's mtime is the one stat, and it is the case none of the
    in-memory state can see: `bb toolchains install` run in a terminal is
    another process entirely, and what it changes is a directory under the
    root. Nothing else here would notice it at all.
    """
    j = _tc_job
    try:
        store = int(Path(sdk_root_path()).stat().st_mtime_ns)
    except (OSError, TypeError, ValueError):
        store = 0
    return (f"{j['running']}:{j['action']}:{j['current']}:{len(j['done'])}"
            f":{len(j['failed'])}"
            f":{_tc_checked}:{_tc_sizing[0]}:{store}")


def job_is_automatic():
    """Whether the job in the way is the daily check rather than a person's.

    The refusal an operator sees depends on it, and being told "an install is
    already running" when nobody started an install wastes an evening.
    """
    with _tc_lock:
        return bool(_tc_job.get("auto"))


def _tc_worker():
    """Run the queued work one item at a time, keeping a tail of the output.

    Everything it can do is `bb toolchains <verb> <name>` for a name that came out of
    TOOLCHAINS: the page posts an index into the table, never a command, which
    is the same rule the macro buttons follow. The verb is decided here rather
    than by the page: "install" on something already present means update it,
    and one button that does the obvious thing beats two that need explaining.
    """
    while True:
        with _tc_lock:
            if not _tc_job["queue"]:
                # Stored once the whole check is done rather than after each
                # toolchain: thirteen rewrites of the same file, each a temp file
                # and a rename, to record one answer at a time.
                if _tc_job["action"] == "check":
                    globals()["_tc_checked"] = int(time.time())
                    save_versions()
                _tc_job["running"] = False
                _tc_job["current"] = ""
                return
            name = _tc_job["queue"].pop(0)
            action = _tc_job["action"]
            _tc_job["current"] = name
        verb = action
        if action == "install":
            row = next((p for p in TOOLCHAINS if p["name"] == name), {})
            probe = row.get("probe", name)
            # Only where the recipe HAS an update. Sending the rest to
            # `bb toolchains update` earned a usage line naming five toolchains the
            # operator had not asked about (bug #43); they go to install now,
            # which refuses with a sentence about the one they did.
            verb = ("update" if _tc_path(probe) and row.get("updatable")
                    else "install")
        with _tc_lock:
            # Whatever it said last time is about a state that no longer holds;
            # this run is the new answer.
            _tc_job["errors"].pop(name, None)

        # The child, so that an abort can reach it. bb's own EXIT trap removes
        # whatever the install had created, which is why this kills the process
        # rather than tearing the directory out from under it.
        #
        # Nothing is read out of the output while it runs. Every recipe meters
        # differently and several mislead by accident (one fraction across a
        # whole operation, a count that parks for minutes, five files metered
        # from zero apiece, the word "download" sitting inside the noun
        # "installer"), and a row reporting any of it faithfully still read as
        # broken. The row says what it is doing and animates. The output is
        # looked at only when the thing fails, which is the only time anybody
        # wanted it.
        r = run([BB, "toolchains", verb, name], timeout=3600, register=_hold_child)
        with _tc_lock:
            if action == "check":
                # TSV out: name, installed, latest, status.
                for ln in r["out"].splitlines():
                    f = ln.rstrip().split("\t")
                    if len(f) >= 4 and f[3] != "local":
                        row = {"installed": f[1], "latest": f[2], "status": f[3]}
                        # The download, when the catalog names a URL that is
                        # the payload. It is not the footprint (a gigabyte of
                        # Swift unpacks to three), so it is only ever used for
                        # a toolchain this box has never had.
                        # A leading tilde is the catalog saying this one is
                        # an approximation rather than a measurement, and it
                        # travels all the way to the row.
                        if len(f) > 4 and f[4].lstrip("~").isdigit():
                            row["bytes"] = f[4]
                        _tc_versions[f[0]] = row
                pass
            elif r["code"] != 0:
                # The end of what it said, plus the exit code in words: a
                # killed sdkmanager prints nothing at all, and a tail of
                # progress bars reads exactly like a run that simply stopped.
                # 137 is the OOM killer, 124 a timeout.
                said = _job_tail(r["out"], keep=4)
                _tc_job["errors"][name] = " · ".join(
                    said + [f"{verb} failed (exit {r['code']})"])[-400:]
            (_tc_job["done"] if r["code"] == 0 else _tc_job["failed"]).append(name)
        if action in ("install", "remove", "update"):
            _tc_local["key"] = None      # whatever just happened moved a version
            _tc_sized_at[0] = 0.0        # ...and changed what is on the disk
            # ...and made the last check's answer about this toolchain a
            # statement about a state that no longer holds. An unchecked row
            # says nothing, which is the honest thing for it to say until
            # somebody asks again.
            with _tc_lock:
                _tc_versions.pop(name, None)
                save_versions()


# The process a job is running right now, so that Abort has something to
# interrupt. A list rather than a value because it is written from the worker
# thread and read from a request thread.
_tc_child = [None]


def _hold_child(proc):
    with _tc_lock:
        _tc_child[0] = proc


def abort_job():
    """Stop the running job after the toolchain it is on.

    The queue is emptied so nothing further starts, and the child is asked to
    stop: bb removes the half-installed directory on its way out, which is the
    same cleanup a failed install gets, because a killed install and a failed
    one leave exactly the same mess. Everything already installed stays: the
    abort is for the rest of the queue, not for undoing what worked.
    """
    with _tc_lock:
        if not _tc_job["running"]:
            return False
        _tc_job["queue"] = []
        _tc_job["aborting"] = True
        pass
        proc = _tc_child[0]
    if proc is not None:
        try:
            # The group, not the process: bb is waiting on a curl or a tar, and
            # killing only the shell leaves the download running.
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass                       # it finished between the check and here
    return True


# ---------------------------------------------------------------------------
# toolchains on another node (docs/nodes.md §6)
#
# The catalog is this one; the state is the node's. Its census reports the
# toolchains it has (`reported.toolchains`, probed by the agent the way `bb
# sdk` probes here) and its toolchain store's headroom, and an install there
# is a `toolchain` job the agent runs with the bundle this controller ships
# (bb and its library) against that store. Nothing here guesses what a node
# has from what it was asked to install.

# What a node's last check said, parsed out of that job's log and kept by the
# job's id (R67). Not a file: a check is a question about this moment, the
# answer ages like a weather report, and a controller restart is a good reason
# to ask again rather than to show yesterday's.
_node_checks = {}


_node_errors_seen = {}


def _node_errors(job_id, failed, verb):
    """{name: why} for the toolchains a node job did not land, in the words
    the controller's own path puts on a row: the end of what that
    toolchain's section of the log said, minus the progress frames, and
    the verb. The section is what `bb toolchains install` prints between
    its own `== bb toolchains install NAME` line and the next `==` line.
    Without this a failed install on a node ended with the row simply
    unticked: the reason was in the job's log and nowhere the tab draws
    (the graphics recipe's 404 was found with bb jobs, not on the tab)."""
    if not failed:
        return {}
    key = (job_id, tuple(failed))
    if key in _node_errors_seen:
        return _node_errors_seen[key]
    parts, cur = {}, None
    for line in (nodes.job_tail(job_id, 20000) or "").splitlines():
        m = re.match(r"== bb toolchains \S+ (\S+)", line)
        if m:
            cur = m.group(1)
            parts[cur] = []
            continue
        if line.startswith("== "):
            cur = None
            continue
        if cur is not None:
            parts[cur].append(line)
    out = {}
    for name in failed:
        lines = []
        for ln in parts.get(name) or []:
            # The run's own footer, not this toolchain's; and curl's meter
            # shares its last line with the error it ends on.
            if re.match(r"^\d+ of \d+ did not install$", ln.strip()):
                continue
            if "curl: (" in ln:
                ln = ln[ln.index("curl: ("):]
            # ...and the meter's own frames, which are made of these alone.
            if ln.strip() and not ln.strip().strip("#=O- "):
                continue
            lines.append(ln)
        said = _job_tail("\n".join(lines), keep=4)
        out[name] = " · ".join(said + [f"{verb} failed on the node"])[-400:]
    _node_errors_seen[key] = out
    return out


def _check_rows(job_id):
    """{name: {installed, latest, status}} from a finished check job's log.

    `bb toolchains check` prints one TSV line per recipe: name, what is
    installed, what upstream has, and a word for the difference. The log is
    the transport because the job channel carries a log and not a payload,
    and this is the same shape the controller's own checker writes into its
    versions file.
    """
    if job_id in _node_checks:
        return _node_checks[job_id]
    rows = {}
    for line in (nodes.job_tail(job_id, 20000) or "").splitlines():
        f = line.rstrip("\n").split("\t")
        if len(f) < 4 or f[0].startswith("=="):
            continue
        name, inst, latest, status = f[0].strip(), f[1].strip(), f[2].strip(), f[3].strip()
        if not name or status not in ("current", "update", "absent", "local", "unknown"):
            continue
        rows[name] = {"installed": "" if inst == "-" else inst,
                      "latest": "" if latest == "-" else latest, "status": status}
    _node_checks[job_id] = rows
    # One answer per node is what the tab draws; the rest are last week's.
    if len(_node_checks) > 40:
        for k in list(_node_checks)[:20]:
            _node_checks.pop(k, None)
    return rows


def payload_for_node(nid):
    n = nodes.node(nid) if nodes else None
    if not n:
        return {"error": "no such node"}
    rep = n.get("reported") or {}
    tc = rep.get("toolchains") or {}
    pv = rep.get("toolchain_versions") or {}
    if not isinstance(pv, dict):
        pv = {}
    plat = platform_of(n)
    store = (rep.get("stores") or {}).get("toolchains") or {}
    items = []
    # What is IN the store, by directory, which is where bb toolchains puts things:
    # <root>/<name>, and android's parts under <root>/android/. The census's
    # `toolchains` is a six-name placement summary and reading it as an
    # inventory called the emulator, the NDK, Playwright and Zig missing on
    # a share that held all four. Directory names first, the summary only
    # for the version string it happens to carry.
    top = set(((rep.get("store_dirs") or {}).get("top")) or [])
    andr = set(((rep.get("store_dirs") or {}).get("android")) or [])
    known = bool(top or andr)
    for p in TOOLCHAINS:
        probe, name = p["probe"], p["name"]
        if probe.startswith("android:"):
            here = probe.split(":", 1)[1] in andr
        elif probe == "android-tools":
            here = bool({"cmdline-tools", "platform-tools"} & andr)
        else:
            here = probe in top
        if name in set((rep.get("store_dirs") or {}).get("incomplete") or []):
            here = False                    # the directory without what completes it
        # A node that has not reported its store yet is not evidence of
        # absence, so say nothing rather than "not installed".
        # The node's own `bb toolchains versions` first: the same generator this
        # controller runs for its own list, so one store is described one
        # way. The census's toolchains dict is the fallback for a node that
        # has not run it yet, and it is a placement summary rather than an
        # inventory: it answers for six names, says "present" where it cannot
        # parse, and hands back an unstripped "go version go1.27.0
        # linux/amd64". That difference is what the operator was looking at.
        have = pv.get(name) or tc.get(
            {"jdk": "java", "android:emulator": "emulator"}.get(probe, probe))
        kb = _tc_remembered.get(name)
        items.append({**{k: p[k] for k in ("name", "label", "about")},
                      # The bb verbs this recipe enables, one root per recipe,
                      # so a row says what installing it adds to a session
                      # and the suite holds two recipes from claiming one.
                      "verbs": list(p.get("verbs") or []),
                      # Whether a newer version can be fetched in place, or
                      # whether getting one means removing this first.
                      "updatable": bool(p.get("updatable")),
                      # Said on the row, so a toolchain this node cannot have
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
    checked = 0
    # A toolchain that puts something on PATH (or sets a variable) reaches a
    # session only when the session starts: one open since before the
    # install still has the old PATH, and the plugin or build that wanted
    # the new tool says "not found" with nothing on screen saying why. So a
    # row that changes a session's environment counts this node's sessions
    # that started before it last landed on the store.
    # What each row pulls onto THIS machine, in its package manager's names,
    # and for one the store already holds, which of those are missing here.
    # Known per family from the census; a node that has not said its family
    # gets no list rather than another family's.
    fam = str((rep.get("sysdeps") or {}).get("family") or "")
    unmet = (rep.get("sysdeps") or {}).get("unmet") or {}
    sysl = {p["name"]: (p.get("system") or {}).get(fam) or [] for p in TOOLCHAINS} if fam else {}
    for i in items:
        names = sysl.get(i["name"]) or []
        if names:
            i["system"] = {"manager": fam, "names": names,
                           "missing": list(unmet.get(i["name"]) or []) if i["installed"] else None}
    # A toolchain another one needs, missing on this node: the store is
    # shared, so diagrams can be installed from one node and be on every
    # node, while the jdk it runs on was removed from this one, or never
    # arrived. The row says which, and offers that row's own install.
    here = {i["name"] for i in items if i["installed"]}
    for i in items:
        if i["installed"]:
            i["needs_missing"] = [r for r in (i.get("needs") or []) if r not in here]
    landed = _landed_at(nid)
    started = [int(x.get("created") or 0) for x in rep.get("sessions") or [] if isinstance(x, dict)]
    shapes = {p["name"]: p.get("layout") or {} for p in TOOLCHAINS}
    for i in items:
        lay = shapes.get(i["name"]) or {}
        at = landed.get(i["name"], 0)
        if i["installed"] and at and (lay.get("bin") or lay.get("env")):
            i["reopen"] = sum(1 for c in started if 0 < c < at)
    job = None
    if nodes:
        for j in nodes.jobs_for(node_id=nid, type="toolchain", active=True, n=1):
            job = {"running": True, "action": (j.get("spec") or {}).get("action", ""),
                   "queue": (j.get("spec") or {}).get("names", []), "current": j.get("step", ""),
                   "log": nodes.job_tail(j["id"], 1200).splitlines()[-16:], "done": [],
                   "failed": [], "aborting": bool(j.get("cancel")), "node": nid, "id": j["id"]}
            break
        if job is None:
            # The last FINISHED one, so the tab can clear what it selected.
            # Nothing did, on a node: done and failed were hardcoded empty
            # and the row vanished the moment the job ended, so every tick
            # survived and the next press re-sent toolchains that had already
            # landed: "installing 2" with one left to do.
            #
            # Both lists come from the census rather than from the job's log:
            # what is in the store now is the only thing actually true, and
            # it is self-correcting: a job that half-worked reports exactly
            # the toolchains that did land as done, whatever its exit code was.
            for j in nodes.jobs_for(node_id=nid, type="toolchain", n=1):
                if j.get("state") not in ("succeeded", "failed", "canceled"):
                    break
                sp = j.get("spec") or {}
                names = [str(x) for x in (sp.get("names") or [])]
                act = sp.get("action") or "install"
                here = {i["name"] for i in items if i["installed"]}
                done = [x for x in names if (x in here) == (act == "install")]
                failed = [x for x in names if x not in done]
                job = {"running": False, "action": act, "queue": [], "current": "",
                       "done": done, "failed": failed,
                       "errors": _node_errors(j["id"], failed, act),
                       "aborting": False, "node": nid, "id": j["id"]}
                break
    # What the last check on this node said, if there has been one. Read from
    # the job's log the first time and kept: a check is a round trip per
    # recipe on the node, so the answer is worth holding on to until somebody
    # asks for a fresh one.
    for j in nodes.jobs_for(node_id=nid, type="toolchain", n=6) if nodes else []:
        if (j.get("spec") or {}).get("action") != "check":
            continue
        if j.get("state") not in ("succeeded", "failed"):
            continue
        rows = _check_rows(j["id"])
        for i in items:
            r = rows.get(i["name"])
            if not r:
                continue
            i["latest"] = r["latest"]
            # Said as the check found it. The controller's own list drops an
            # answer that disagrees with its probe, because there both
            # readings are of the same directory a moment apart. Here they
            # are two different readings: the census sees a directory in the
            # store, the check ran on the node and asked the binary. When
            # they disagree the check is the one that looked properly, and a
            # row that reads installed while the check says absent is a
            # disagreement worth seeing rather than hiding.
            i["state"] = r["status"]
        checked = int(j.get("ended") or 0)
        break
    return {"node": nid, "name": n["name"], "live": bool(n.get("live")),
            # Held recipes whose system packages this machine lacks, and
            # whether the agent may install them there (roadmap R51).
            "sysdeps": rep.get("sysdeps") or {}, "sandbox": bool(rep.get("sandbox")),
            # Locked to its console: nothing on it is installed by itself.
            "locked": bool((n.get("config") or {}).get("lock")),
            # Whether the agent there installs system packages itself.
            "administers": bool(rep.get("administers")),
            # The node's own scope under the store (roadmap R19), where its
            # toolchains actually are. The share itself where the node has not
            # reported one yet.
            "root": (store.get("path") or "") + ("/" + store["scope"] if store.get("scope") else ""),
            "free_mb": store.get("free_mb"),
            "shared": False, "checked": checked, "sizing": False,
            "items": items, "job": job or {"running": False}}


def _store_share(n):
    """What identifies this node's toolchain store, or None.

    Two machines pointing `toolchains` at one share ARE one store, and the
    controller has to know which pairs those are: the same path STRING says
    nothing: /var/lib/builderbot/toolchains is every node's default and is a
    different disk on each.

    The store's own id first (nodes.store_id, a marker file inside it),
    because it is the only answer that survives the transport differing. On
    this box the toolchain store is reached through Unraid's FUSE layer by the
    controller (fstype fuse.shfs, source "shfs") and over NFS by the sandbox
    (192.168.1.10:/mnt/user/development/SDK); neither string can be derived
    from the other, so the pair was invisible and the one-install-at-a-time
    arbitration never engaged for it.

    The mount source stays as the fallback, for a node whose store has no
    marker yet: a read-only share is the case that has to keep working.
    """
    rep = n.get("reported") or {}
    store = (rep.get("stores") or {}).get("toolchains") or {}
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


def _landed_at(nid):
    """{toolchain: when a job last installed or updated it} on this node's
    store, which is also every node sharing it: installed from one, it is on
    all of them, and so are the sessions it has not reached."""
    out = {}
    if not nodes:
        return out
    for x in [nid] + [o["id"] for o in store_sharers(nid)]:
        for j in nodes.jobs_for(node_id=x, type="toolchain", n=50):
            sp = j.get("spec") or {}
            if j.get("state") != "succeeded" or sp.get("action") not in ("install", "update"):
                continue
            for name in sp.get("names") or []:
                out[str(name)] = max(out.get(str(name), 0), int(j.get("ended") or 0))
    return out


def store_sharers(node_id):
    """Every other node whose toolchain store is the same share as this
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
    """Every toolchain's layout, as the agent needs it: what to put on PATH,
    what variables to set, and which file proves a toolchain is there.

    Sent at hello rather than duplicated in the agent. It used to be three
    hand-written tables (sdk_env_snippet here, STORE_TOOLS and STORE_PATHS
    on the node) that had to agree about where every toolchain lands and did
    not: node/bin was missing from one, the android-tools probe read the
    wrong directory, and the census disagreed with the inventory, all in one
    day. The catalog is the one place that knows, and this is how a machine
    with no catalog of its own finds out.

    `dir` is where the toolchain lives relative to the store: android's
    toolchains share one tree, so theirs is `android`.
    """
    out = []
    for p in TOOLCHAINS:
        lay = p.get("layout")
        if not lay:
            continue
        name = p["name"]
        out.append({"name": name,
                    "dir": "android" if name.startswith("android:") else name,
                    "bin": lay["bin"], "env": lay["env"],
                    "tool": lay["tool"], "reports": lay["reports"],
                    "needs": lay.get("needs") or ""})
    return out


def node_has(n):
    """The toolchain names already in this node's toolchain store, by the
    directories bb toolchains puts them in. Empty when the node has not reported
    its store, which is not evidence of absence, so a caller must treat it
    as "unknown" rather than "nothing"."""
    rep = n.get("reported") or {}
    top = set(((rep.get("store_dirs") or {}).get("top")) or [])
    andr = set(((rep.get("store_dirs") or {}).get("android")) or [])
    if not (top or andr):
        return set()
    tc = rep.get("toolchains") if isinstance(rep.get("toolchains"), dict) else {}
    out = set()
    for p in TOOLCHAINS:
        probe = p["probe"]
        if probe.startswith("android:"):
            here = probe.split(":", 1)[1] in andr
        elif probe == "android-tools":
            # A directory called cmdline-tools is not sdkmanager. On the
            # operator's node it held nothing but a symlink pointing at a
            # directory a failed install had removed, so this said installed,
            # the requirement was never pulled in, and the android:* package
            # that needed it died on "no sdkmanager". The census answers from
            # the binaries, so it corroborates; where a node has reported no
            # toolchains at all there is nothing to corroborate with and the
            # directory is all there is to go on.
            here = bool({"cmdline-tools", "platform-tools"} & andr) \
                and (bool(tc.get("android-sdk")) if tc else True)
        else:
            here = probe in top
        if here:
            out.add(p["name"])
    return out


def with_requires(names, have):
    """`names`, with anything they declare a requirement on put in front.

    A recipe that needed another toolchain used to say so only in its `env`
    block: android-tools points JAVA_HOME at a sibling jdk that may not be
    there, and sdkmanager then fails with "Could not determine SDK root",
    naming neither Java nor the toolchain that would have supplied it. The
    catalog says it now, and the requirement is pulled in rather than
    discovered.

    Requirements already in the store are left out: this adds what is
    missing, ahead of what needs it, and never re-installs. Returns
    (ordered names, what was added).
    """
    by = {p["name"]: p for p in TOOLCHAINS}
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


def supports(tc, plat):
    """Whether this recipe works on that platform. Absent list means the
    historical truth: this catalog only ever served linux/amd64."""
    want = tc.get("platforms") or ["linux/amd64"]
    if not plat:
        return True                     # a node that has not said is not judged
    o, _, a = plat.partition("/")
    return any(x == plat or x == f"{o}/*" for x in want)


def unsupported(names, plat):
    """[(name, platforms)] for the ones this platform cannot have."""
    by = {p["name"]: p for p in TOOLCHAINS}
    return [(x, ", ".join(by[x].get("platforms") or ["linux/amd64"]))
            for x in names if x in by and not supports(by[x], plat)]


def _need_kb(name):
    """What installing this will cost the store, in KB: measured here the
    last time it was installed, or 0 for one this controller never had."""
    return _tc_remembered.get(name, 0)


# The jobs that write into a toolchain store: a toolchain's, and an Android
# system image's (emulator.py), which lives there without being one.
STORE_JOBS = ("toolchain", "image")


def _store_job_on(node_id):
    return any(nodes.jobs_for(node_id=node_id, type=t, active=True, n=1) for t in STORE_JOBS)


def store_busy(nid):
    """Why this node's toolchain store cannot take another job now, or "".

    One at a time across every node that shares the store, not just this
    one. docs/nodes.md section 6 names the trap: two agents unpacking into
    one NFS directory, or one upgrading a toolchain under another mid-build,
    is version skew nobody can debug. The rule is enforced across a shared
    store or it is not enforced at all."""
    n = nodes.node(nid)
    sharers = store_sharers(nid)
    for other in [n] + sharers:
        if _store_job_on(other["id"]):
            where = ("" if other["id"] == nid
                     else f"; it shares this toolchain store with {n['name']}")
            return f"a toolchain or image job is already running on {other['name']}{where}. One at a time."
    # ...and this container's own installer, which is not a job and so is
    # invisible to the loop above. It is the sharer that matters most here:
    # the toolchain store is mounted by the controller and by the sandbox at once.
    if _tc_job["running"] and any(o["id"] == nodes.LOCAL for o in sharers):
        return ("this container is installing into the same toolchain store "
                f"right now; it shares it with {n['name']}. One at a time.")
    return ""


def node_job(principal, nid, action, names):
    """Queue the toolchain job. Refused, with numbers, when the store cannot
    hold what is asked, measured here the last time it was installed, so a
    toolchain this controller never had is not gated, and the log says so."""
    if not nodes:
        return {"error": "no node store"}
    n = nodes.node(nid)
    if not n:
        return {"error": "no such node"}
    if n["kind"] != "agent":
        return {"error": f"{n['name']} runs no agent; toolchains are installed there by hand"}
    store = ((n.get("reported") or {}).get("stores") or {}).get("toolchains") or {}
    added = []
    if action not in ("install", "remove", "sysdeps", "check"):
        return {"error": f"a node takes install, remove, sysdeps or check, not {action!r}"}
    if action == "sysdeps" and not (n.get("reported") or {}).get("sandbox"):
        return {"error": f"{n['name']} was not provisioned as a BuilderBot sandbox, so its "
                         "system packages are its owner's to install; the row names them"}
    if action == "install":
        # What these need, ahead of them. android-tools without a jdk fails
        # inside sdkmanager with a message that names neither.
        have = node_has(n)
        ordered, _ = with_requires(names, have)
        names, added = ordered, [x for x in ordered if x not in names]
        # Seven of these recipes name linux-x86_64 in their URL and one names
        # ubuntu24.04, so a node of another platform would download a couple
        # of hundred megabytes and fail on exec, or install and fail later.
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
        need_kb = sum(_need_kb(x) for x in names)
        free = store.get("free_mb")
        if need_kb and free is not None and free * 1024 < need_kb * 1.2:
            return {"error": f"{n['name']}'s toolchain store has {human_kb(free * 1024)} free "
                             f"and this needs about {human_kb(int(need_kb * 1.2))}: "
                             "point the store somewhere bigger first"}
    busy = store_busy(nid)
    if busy:
        return {"error": busy}
    # Two architectures on one store used to be refused here, because a flat
    # store could not hold both. It is scoped by platform now: each machine
    # installs under <store>/<os>-<arch> (roadmap R19), so a Mac and a Linux
    # box sharing a share is the design, not a mistake.
    r = nodes.job_add(principal, {"node": nid}, "toolchain",
                      {"action": action, "names": names, "timeout": 3600})
    if r.get("ok") and added:
        r["added"] = added
    return r


# The unmet set each node was last sent a system-packages job for, so one
# that did not fix it is not sent again every hello: a failing apt would
# otherwise be retried every ten minutes forever. In memory: a restart is
# one more try, which is the right amount.
_auto_sysdeps = {}


def auto_sysdeps(nid):
    """Install the system packages a node lacks for what its store holds,
    without anybody pressing Install system packages.

    The store is shared, so a toolchain installed from one node is on every
    node that mounts it, while the libraries it needs are each machine's
    own: the install job installs them only on the node it ran on, and every
    other one showed a banner asking for a second press. Those packages were
    already chosen when the recipe was installed, so a node BuilderBot
    manages (the sandbox stamp) installs them itself when its census says
    they are missing. Not on a guest node, whose system is its owner's, and
    not while the node's system changes are locked to its console. The
    banner stays for those, and for a job that did not fix it.

    Called on every hello; a no-op unless something is missing. The queued
    job, or None."""
    if not nodes:
        return None
    n = nodes.node(nid)
    if not n or n["kind"] != "agent" or n.get("state") != "online":
        return None
    rep = n.get("reported") or {}
    unmet = (rep.get("sysdeps") or {}).get("unmet") or {}
    # The agent's own word that it may (root and the stamp), not the stamp
    # alone: a stamped node whose agent is not root refuses the job, and
    # queueing it anyway held the store against the next real install.
    if not unmet or not rep.get("administers") or nodes.node_locked(n):
        return None
    sig = json.dumps(unmet, sort_keys=True)
    if _auto_sysdeps.get(nid) == sig:
        return None
    r = node_job("system", nid, "sysdeps", sorted(unmet)[:8])
    # Only a job actually queued counts as tried: one refused because
    # another toolchain job holds the store is tried again on a later hello.
    if r.get("ok"):
        _auto_sysdeps[nid] = sig
    return r


def start_job(action, names, auto=False):
    """Queue a toolchain job, unless one is already going. False if it is."""
    with _tc_lock:
        if _tc_job["running"]:
            return False
        # The other half of the shared-store rule: a node unpacking into the
        # store this container is about to write is the same collision, seen
        # from the other side.
        if nodes:
            with contextlib.suppress(Exception):
                for other in store_sharers(nodes.LOCAL):
                    if _store_job_on(other["id"]):
                        return False
        if action == "install":
            here = {p["name"] for p in TOOLCHAINS if _tc_path(p["probe"])}
            names, _added = with_requires(list(names), here)
        _tc_job.update(running=True, queue=list(names), action=action,
                        current="", log=[], done=[], failed=[], auto=auto,
                        aborting=False,
                        # Fixed in phase 1 (toolchains install here) and a
                        # seam on purpose: phase 6 makes this a job placed on
                        # any node's toolchain store, and this call site is
                        # where the node picker's answer lands.
                        node="local")
    threading.Thread(target=_tc_worker, daemon=True).start()
    return True


# A version check on the way up, and once a day after that.
#
# The answers are a network round trip apiece and they do not go stale in
# minutes, so this is a slow background errand rather than anything the poll
# does: eight seconds of it, a while after boot so that a container coming up
# is not doing this alongside everything else it does at start. It steps aside
# for anything the operator started and tries again later: a check that
# queued itself behind an install would hold the tab hostage.
# Weekly. It was daily, and a check is one network round trip per toolchain to
# somebody else's servers, for answers that move on a release cadence, not a
# daily one. The manual button is what a person presses when they actually
# want to know now.
TC_CHECK_EVERY = 7 * 86400
# Late enough that the startup hooks have finished. A hook installing into
# the store can be running sdkmanager when the dashboard comes up, and two of
# those on one toolchain store root is a fight over the same lock.
TC_CHECK_DELAY = int(os.environ.get("TC_CHECK_DELAY", "180"))
AUTOCHECK = os.environ.get("TC_AUTOCHECK", "1") != "0"


def versions_loop():
    time.sleep(TC_CHECK_DELAY)
    # From when the last check actually happened, not from zero. A container
    # restart used to mean a full round of upstream requests three minutes
    # later, so an afternoon of image updates was an afternoon of checking,
    # for answers that had not moved. The timestamp is on the state volume and
    # outlives the container, which is the whole reason it is written there.
    #
    # A catalog edit still forces one, and that is decided when the file is
    # read: load_versions zeroes the timestamp when the digest it was saved
    # against is not the one running now.
    due = _tc_checked + TC_CHECK_EVERY if _tc_checked else 0
    while True:
        if TOOLCHAINS and time.time() >= due and not _tc_job["running"]:
            if start_job("check", [p["name"] for p in TOOLCHAINS], auto=True):
                due = time.time() + TC_CHECK_EVERY
        time.sleep(300)
