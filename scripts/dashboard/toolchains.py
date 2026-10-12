#!/usr/bin/env python3
"""Everything behind the dashboard's Tools tab.

The catalog, where a toolchain's files land, what it weighs, what version it is
and what version upstream has, and the one-job-at-a-time worker that installs,
updates, removes and checks. The server imports this and hands it two helpers;
nothing here reaches back into the server.

The division of labor with bb is the point. This module decides *when* to ask
and remembers the answers; bb decides *how*, out of config/toolchains.json,
which holds every URL, flag and argument any of it needs. Neither of them has
a toolchain name written into it.
"""
import contextlib
import hashlib
import json
import os
import platform
import re
import signal
import sqlite3
import sys
import threading
import time
from pathlib import Path

# The request-field reader verb() shares with the server, found beside this
# file however it was loaded: a test loads it by path, where a plain sibling
# import finds nothing.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fields import field  # noqa: E402

HERE = Path(__file__).resolve().parent

# The two the server owns: running a command and writing a state file
# atomically. Injected rather than imported, because importing the server from
# a module the server imports is a circle.
run = None
write_json = None
STATE = None
nodes = None          # the node store, once the server has opened it (phase 6)
claudecode = None     # claudecode.py, set by the server: Claude Code as a node's toolchain (R145)
CLAUDE = "claude-code"


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
        # ...and the two source flags the installer's verb is chosen by
        # (UPDATE_VERBS, the agent's tc_verbs): a recipe that refuses an
        # existing directory, and an Android package that installs beside.
        src = r.get("source") if isinstance(r.get("source"), dict) else {}
        if src.get("fresh_only") or src.get("versioned"):
            row["source"] = {k: True for k in ("fresh_only", "versioned") if src.get(k)}
        reqs = [x for x in (r.get("requires") or []) if isinstance(x, str) and x]
        if reqs:
            row["requires"] = reqs[:4]
        # The tool it adds under `bb tool`, projected like the rest: one plain
        # word, since it is drawn on the row and matched against bb's case.
        tool = r.get("tool")
        if isinstance(tool, str) and tool and tool.replace("-", "").isalnum():
            row["tool"] = tool
        # What installing it is under (the operator, 7 Oct): each license or
        # agreement with its link, drawn on the row, an agreement Install
        # accepts (Google's, NVIDIA's, Apple's) marked so the row says so.
        terms = [{"label": str(t["label"])[:120], "url": str(t["url"]), "accept": bool(t.get("accept"))}
                 for t in (r.get("terms") or []) if isinstance(t, dict)
                 and isinstance(t.get("label"), str) and str(t.get("url") or "").startswith("https://")]
        if terms:
            row["terms"] = terms[:8]
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
                      "terms": p.get("terms") or [],
                      # The tool this recipe adds under `bb tool`, one name
                      # per recipe, so a row says what installing it adds to
                      # a session and the suite holds two from claiming one.
                      "tool": p.get("tool") or "",
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


# The recipes `bb toolchains update` knows, as the agent's tc_verbs has them.
UPDATE_VERBS = ("flutter", "dotnet", "swift", "playwright")


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
            # The same rule as the agent's (tc_verbs): `update` only for a
            # recipe that verb knows, since it dies on its usage line for the
            # rest whatever the catalog's `updatable` says (12 Oct: thirteen
            # recipes are updatable and fresh_only both).
            src = row.get("source") or {}
            has = _tc_path(probe) and not src.get("versioned")
            verb = ("update" if has and (name in UPDATE_VERBS or name.startswith("android:"))
                    else "install")
            # ...and one installed that cannot install over itself is
            # removed first (R193), where install alone dies with "already
            # installed": a remove that fails leaves the old one as it was.
            if verb == "install" and has and (src.get("fresh_only") or not row.get("updatable")):
                r = run([BB, "toolchains", "remove", name], timeout=1800, register=_hold_child)
                if r["code"] != 0:
                    with _tc_lock:
                        _tc_job["errors"][name] = " · ".join(
                            _job_tail(r["out"], keep=4) + [f"remove before the install failed (exit {r['code']})"])[-400:]
                        _tc_job["failed"].append(name)
                    continue
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
    parts, cur, refused = {}, None, ""
    for line in (nodes.job_tail(job_id, 20000) or "").splitlines():
        # An install's section is bb's header; a system-packages job's is the
        # agent's own (sysdeps), which this did not read, so that row said
        # only that it failed.
        m = (re.match(r"== bb toolchains \S+ (\S+)", line)
             or re.match(r"== system packages for (\S+?):", line))
        if m:
            cur = m.group(1)
            parts[cur] = []
            continue
        if line.startswith("refused:") and not refused:
            refused = line.strip()
        if line.startswith("== "):
            cur = None
            continue
        if cur is not None:
            parts[cur].append(line)
    out = {}
    for name in failed:
        if name in (DRIVER, TOOLKIT):
            # bb-sandbox says why on a line of its own ("!! ..."), and the
            # agent's refusal begins "refused:"; its sections are not bb's.
            # apt's own first complaint ("E: ...") is the reason; bb-sandbox's
            # last line only says apt had one (the dev node's lock, 30 Sep).
            # Each of the machine's two rows reads its own part of the log,
            # from the agent's header for it to the header of the other.
            # A log with no such header is all one row's.
            mine = "gpu-container" if name == TOOLKIT else "gpu-driver"
            whole = [x.strip() for x in (nodes.job_tail(job_id, 20000) or "").splitlines()]
            log, on = [], not any(x.startswith("== bb-sandbox gpu-") for x in whole)
            for x in whole:
                if x.startswith("== bb-sandbox gpu-"):
                    on = x.startswith(f"== bb-sandbox {mine} ")
                if x.startswith("refused:"):
                    if (TOOLKIT in x) == (name == TOOLKIT):
                        log.append(x)
                elif on:
                    log.append(x)
            apt = next((x[3:].strip() for x in log if x.startswith("E: ")), "")
            why = next((x.lstrip("! ") for x in reversed(log) if x.startswith(("!!", "refused:"))), "")
            out[name] = " · ".join([w for w in (apt or why,) if w] + [f"{verb} failed on the node"])[-400:]
            continue
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
        said = _job_tail("\n".join(lines), keep=4) or ([refused] if refused else [])
        out[name] = " · ".join(said + [f"{verb} failed on the node"])[-400:]
    _node_errors_seen[key] = out
    # The newest few jobs' answers: it was kept for every job ever read.
    while len(_node_errors_seen) > 64:
        _node_errors_seen.pop(next(iter(_node_errors_seen)))
    return out


def finished(act, names, here, rep, state):
    """(done, failed) for a node's last toolchain job, from what is true now.

    An install is done where the toolchain is in the store, a removal where
    it is not. A system-packages job is neither: the recipe is in the store
    before and after, so that test called every one failed, the ones that
    worked too. What the census still finds unmet is its answer (the agent
    reports again as the job ends), and no names is every held recipe."""
    if act == "sysdeps":
        unmet = (rep.get("sysdeps") or {}).get("unmet") or {}
        names = names or sorted(unmet)
        failed = [x for x in names if x in unmet]
        if state != "succeeded" and not failed:
            failed = names or ["system packages"]
        return [x for x in names if x not in failed], failed
    done = [x for x in names if (x in here) == (act == "install")]
    return done, [x for x in names if x not in done]


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


def store_known(n):
    """Whether a node's listing of its store is the whole truth about it: a
    store named, and the agent has reported what is in it (every agent
    since store_dirs, an empty listing included). Then a toolchain not in
    the listing is not installed whatever the last check said, and a store
    emptied by hand reads as nothing installed rather than nothing known
    (B671, the operator, 12 Oct: the store wiped, every row still current)."""
    rep = (n or {}).get("reported") or {}
    return bool(((rep.get("stores") or {}).get("toolchains") or {}).get("path")) \
        and isinstance(rep.get("store_dirs"), dict)


def last_check(nid):
    """What the last check on a node said, {name: {installed, latest,
    status}}, and when it ended (0 for never): the tab's state column and
    the bell's update row read the same answer (the operator, 9 Oct). What
    the node's own listing no longer holds is absent, whatever the check
    or an install since it said (B671): the listing comes with every
    hello, so a directory deleted by hand is read within one."""
    recent = nodes.jobs_for(node_id=nid, type="toolchain", n=6) if nodes else []
    n = nodes.node(nid) if nodes else None
    gone = (set(p["name"] for p in TOOLCHAINS) - node_has(n)) if n and store_known(n) else set()
    for j in recent:
        if (j.get("spec") or {}).get("action") != "check":
            continue
        if j.get("state") not in ("succeeded", "failed"):
            continue
        # What was installed since that check, by a job that succeeded: the
        # check's "update" or "absent" for it is the answer from before, and
        # the row kept offering an update it had just taken until somebody
        # checked again (the operator, 6 Oct).
        since = {str(x) for k in recent
                 if (k.get("spec") or {}).get("action") == "install" and k.get("state") == "succeeded"
                 and int(k.get("ended") or 0) > int(j.get("ended") or 0)
                 for x in ((k.get("spec") or {}).get("names") or [])}
        rows = {name: (dict(r, status="absent", installed="") if name in gone
                       else dict(r, status="current") if name in since else r)
                for name, r in _check_rows(j["id"]).items()}
        return rows, int(j.get("ended") or 0)
    return {}, 0


def attention(project_nodes):
    """Bell rows, one per live agent node with a toolchain behind what is
    out: every toolchain its last check found an update for, and Claude
    Code beside them (claudecode.behind), each as {name, label, from, to}.
    One shape for all of them, with Open on that node's Toolchains tab,
    which is where each is updated (the operator, 9 Oct). Computed on every
    poll, so a row leaves the moment its update lands. `project_nodes` is
    {project: node id}."""
    labels = {p["name"]: p["label"] for p in TOOLCHAINS}
    out = []
    for n in nodes.node_list() if nodes else []:
        if n.get("kind") != "agent" or not n.get("live"):
            continue
        running = set()
        for j in nodes.jobs_for(node_id=n["id"], type="toolchain", active=True, n=1):
            running |= {str(x) for x in ((j.get("spec") or {}).get("names") or [])}
        rows, _ = last_check(n["id"])
        tools = [{"name": name, "label": labels[name], "from": r["installed"], "to": r["latest"]}
                 for name, r in sorted(rows.items(), key=lambda kv: labels.get(kv[0], kv[0]).lower())
                 if r["status"] == "update" and name in labels and name not in running]
        if claudecode and claudecode.behind(n) and not claudecode.updating(n["id"]):
            tools.insert(0, {"name": CLAUDE, "label": "Claude Code",
                             "from": claudecode.installed(n), "to": claudecode.latest()["version"]})
        if tools:
            out.append({"kind": "toolchain", "node": n["name"], "id": n["id"], "tools": tools,
                        "projects": sorted(p for p, nid in project_nodes.items() if nid == n["id"])})
    return out


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
    # An empty listing from an agent that sends one is an empty store, and
    # every row is there to install again (B671); only a node that has not
    # listed its store at all is unknown.
    known = store_known(n) or bool(top or andr)
    for p in TOOLCHAINS:
        probe, name = p["probe"], p["name"]
        if probe.startswith("android:"):
            here = probe.split(":", 1)[1] in andr
        elif probe == "android-tools":
            here = "cmdline-tools" in andr
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
                      "terms": p.get("terms") or [],
                      # The tool this recipe adds under `bb tool`, one name
                      # per recipe, so a row says what installing it adds to
                      # a session and the suite holds two from claiming one.
                      "tool": p.get("tool") or "",
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
    # A toolchain another one needs, missing on this node: diagrams can be
    # installed while the jdk it runs on was removed since, or never
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
            names = [DRIVER if str(x).startswith(DRIVER + ":") else str(x)
                     for x in (j.get("spec") or {}).get("names", [])]
            # How far through the batch it is, from the name the agent says
            # it is on (step): the ones before it are behind it, the ones
            # after it still to come. Every name sat in the queue for the
            # whole job, and the tab read "1 of 10" from start to end (the
            # operator, 12 Oct).
            cur = j.get("step", "")
            at = names.index(cur) if cur in names else -1
            job = {"running": True, "action": (j.get("spec") or {}).get("action", ""),
                   "queue": names[at + 1:] if at >= 0 else names,
                   "passed": names[:at] if at >= 0 else [],
                   "current": cur,
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
                names = [DRIVER if str(x).startswith(DRIVER + ":") else str(x) for x in (sp.get("names") or [])]
                act = sp.get("action") or "install"
                here = {i["name"] for i in items if i["installed"]}
                here |= {r["name"] for r in (driver_row(n), container_row(n)) if r and r["here"]}
                done, failed = finished(act, names, here, rep, j.get("state"))
                job = {"running": False, "action": act, "queue": [], "current": "",
                       "done": done, "failed": failed,
                       "errors": _node_errors(j["id"], failed, act),
                       "aborting": False, "node": nid, "id": j["id"]}
                break
    # What the last check on this node said, if there has been one. Read from
    # the job's log the first time and kept: a check is a round trip per
    # recipe on the node, so the answer is worth holding on to until somebody
    # asks for a fresh one.
    rows, checked = last_check(nid)
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
    machine = [r for r in (driver_row(n), container_row(n)) if r]
    for m in machine:
        # The census after a job that touched the driver or the toolkit is
        # what says where it stands now; until it has arrived the tab keeps
        # asking, two minutes at most for an agent gone quiet.
        ended = 0
        for j in nodes.jobs_for(node_id=nid, type="toolchain", n=1) if nodes else []:
            sp = j.get("spec") or {}
            # ...and after a check, which reads apt's lists again on the node.
            if j.get("state") in ("succeeded", "failed", "canceled") and (
                    sp.get("action") == "check"
                    or any(str(x).startswith(DRIVER) or str(x) == TOOLKIT for x in sp.get("names") or [])):
                ended = int(j.get("ended") or 0)
        # The agent's hello at the end of a job lands a moment before the
        # job's result does, so a census from the job's last seconds counts.
        m["settling"] = bool(ended) and int(rep.get("at") or 0) < ended - 5 and time.time() - ended < 120
    # Claude Code, the session account's (R145), drawn with the machine's
    # rows; its own job says where it stands, not the toolchain jobs.
    cl = claude_row(n)
    if cl:
        machine.append(cl)
    return {"node": nid, "name": n["name"], "live": bool(n.get("live")),
            # What is this machine's rather than the store's: the NVIDIA
            # driver and the container toolkit, where the node has the card
            # (R102).
            "machine": machine,
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
            # What on the store no node runs from any more (R196).
            "cleanable": cleanable(nid),
            "items": items, "job": job or {"running": False}}


DRIVER = "nvidia-driver"


def driver_row(n):
    """The NVIDIA driver as a row of the node's Toolchains tab (R102), or
    None where the node reports no NVIDIA card. A row like the store's, with
    a tick box, in the same batch and the same check, but the machine's own:
    built for its kernel, installed as root, taking the card at the next
    boot. Its state is read from the census the agent sends: installed for
    this kernel, loaded now, which driver has the card, the package apt
    holds and what apt would move it to, and the branches on offer."""
    rep = n.get("reported") or {}
    card = rep.get("gpu_card")
    if not card:
        return None
    gd = rep.get("gpu_driver")
    known = isinstance(gd, dict)
    gd = gd if known else {}
    inst, loaded, bound = gd.get("installed") or "", gd.get("loaded") or "", gd.get("bound") or ""
    has = bound == "nvidia" or bool(loaded)
    state = ("unknown" if not known
             else "update" if has and inst and loaded and inst != loaded
             else "loaded" if has and inst
             else "leaving" if has
             else "waiting" if inst
             else "absent")
    pv, cand = gd.get("pkg_version") or "", gd.get("candidate") or ""
    return {"name": DRIVER, "label": "NVIDIA driver", "card": str(card),
            "gpu": str(rep.get("gpu") or ""), "installed": inst, "loaded": loaded,
            "bound": bound, "state": state, "managed": bool(rep.get("sandbox")),
            # On the machine, whether or not it has the card yet: what a
            # tick means and what Remove is offered on.
            "here": state in ("waiting", "loaded", "update"),
            "package": gd.get("package") or "",
            # What apt would move the installed package to, when that is not
            # what is installed: the row's "update available".
            "newer": cand.split("-", 1)[0] if pv and cand and cand != pv else "",
            "recommended": gd.get("recommended") or "",
            "options": [o for o in (gd.get("options") or []) if isinstance(o, dict)][:16]}


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
    own directory of the store."""
    out = {}
    if not nodes:
        return out
    for j in nodes.jobs_for(node_id=nid, type="toolchain", n=50):
        sp = j.get("spec") or {}
        if j.get("state") != "succeeded" or sp.get("action") not in ("install", "update"):
            continue
        for name in sp.get("names") or []:
            out[str(name)] = max(out.get(str(name), 0), int(j.get("ended") or 0))
    return out


def names_in(dirs):
    """The recipes a store listing ({top, android}, store_dirs' shape) holds,
    by the same reading the Toolchains tab's rows make of a node's own."""
    top = set((dirs or {}).get("top") or [])
    andr = set((dirs or {}).get("android") or [])
    out = []
    for p in TOOLCHAINS:
        probe = p["probe"]
        if probe.startswith("android:"):
            here = probe.split(":", 1)[1] in andr
        elif probe == "android-tools":
            here = "cmdline-tools" in andr
        else:
            here = probe in top
        if here:
            out.append(p["name"])
    return out


def cleanable(nid):
    """[{dir, what}] at the top of this node's toolchain store that no node
    runs from any more (R196): a directory named for a node that is retired
    or unknown here (a node enrolled again starts afresh under its new id,
    and leaves its old one behind). Never a live node's, and never anything
    not named for a node: `shared`, and the controller's own <os>-<arch>."""
    if not nodes:
        return []
    n = nodes.node(nid)
    rep = (n or {}).get("reported") or {}
    roots = list((rep.get("store_dirs") or {}).get("roots") or [])
    if not roots:
        return []
    share = _store_share(n)
    peers = [o for o in nodes.node_list(all=True) if o.get("kind") == "agent" and _store_share(o) == share] if share else [n]
    in_use = {_scope_of(o) for o in peers if o.get("state") != "retired"}
    names = {o["id"]: o.get("name") or o["id"] for o in nodes.node_list(all=True)}
    retired = {o["id"] for o in nodes.node_list(all=True) if o.get("state") == "retired"}
    out = []
    for d in roots:
        if d in in_use or not re.fullmatch(r"n_[0-9a-f]{4,32}", d):
            continue
        if d in retired or d not in names:
            out.append({"dir": d, "what": f"{names[d]}'s, a node since retired" if d in names
                        else "a node's no longer enrolled here"})
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
    # Each keeps its own directory in it (<store>/<node id>), so what they
    # can collide on is what store_areas says: the Android system images.
    return [n for n in nodes.node_list()
            if n["id"] != node_id and n["state"] != "retired" and _store_share(n) == mine]


def _scope_of(n):
    """The directory under its toolchain store a node's toolchains are in."""
    return str((((n or {}).get("reported") or {}).get("stores") or {}).get("toolchains", {}).get("scope") or "")


def _dir_of(n):
    """The directory a node's toolchain jobs write under the store: its
    node id (R196), and this controller's own <os>-<arch>."""
    if nodes and (n or {}).get("id") == nodes.LOCAL:
        return f"{platform.system().lower()}-{platform.machine() or 'unknown'}"
    return _scope_of(n) or str((n or {}).get("id") or "")


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
            here = "cmdline-tools" in andr \
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


def store_areas(names, action="install", where=""):
    """The parts of a toolchain store these names write, as (directory,
    area), the directory being the machine's own under the store (_dir_of).

    Each toolchain unpacks into a directory of its own there, so two
    installs collide only on the same toolchain in the same directory,
    except the Android family, which sdkmanager keeps in one SDK tree. The
    driver, the container toolkit, system packages and a check write no
    store at all: they are each machine's own, or only read."""
    if action in ("check", "sysdeps"):
        return set()
    out = set()
    for x in names:
        x = str(x)
        if x == TOOLKIT or x == DRIVER or x.startswith(DRIVER + ":"):
            continue
        out.add((where, "android" if x == "android-tools" or x.startswith("android:") else x))
    return out


def _image_areas(where):
    # The SDK tree an image job's sdkmanager runs in, and the system images,
    # which every machine on the store shares (<store>/shared).
    return {(where, "android"), ("", "android system images")}


def _job_areas(j, where):
    sp = j.get("spec") or {}
    if j.get("type") == "image":
        return _image_areas(where)
    return store_areas(sp.get("names") or [], sp.get("action") or "install", where)


def store_busy(nid, names=None, action="install"):
    """Why this node's toolchain store cannot take this job now, or "".

    On the node itself, one toolchain or image job at a time: its tab shows
    one job. Across machines that share the store, a job waits only for one
    writing the same directory (store_areas): each keeps its toolchains in
    its own, so that is the Android system images under <store>/shared.
    `names` None is any write to the store (an image job: the Android SDK)."""
    n = nodes.node(nid)
    if _store_job_on(nid):
        return f"a toolchain or image job is already running on {n['name']}. One at a time on a node."
    mine = (store_areas(names, action, _dir_of(n)) if names is not None
            else _image_areas(_dir_of(n)))
    if not mine:
        return ""
    for other in store_sharers(nid):
        for t in STORE_JOBS:
            for j in nodes.jobs_for(node_id=other["id"], type=t, active=True, n=4):
                both = sorted(a for _, a in mine & _job_areas(j, _dir_of(other)))
                if both:
                    return (f"{other['name']} is installing {', '.join(both)} into the toolchain store "
                            f"it shares with {n['name']}; this waits for it, since two machines "
                            "unpacking one toolchain into one directory is a broken install")
    # ...and this container's own installer, which is not a job and so is
    # invisible to the loop above. The store is mounted by the controller and
    # by the sandbox at once.
    if _tc_job["running"] and any(o["id"] == nodes.LOCAL for o in store_sharers(nid)):
        local = nodes.node(nodes.LOCAL)
        theirs = store_areas(list(_tc_job["queue"]) + [_tc_job["current"]] if _tc_job["current"]
                             else list(_tc_job["queue"]), _tc_job["action"], _dir_of(local))
        both = sorted(a for _, a in mine & theirs)
        if both:
            return (f"this container is installing {', '.join(both)} into the toolchain store "
                    f"it shares with {n['name']}; this waits for it")
    return ""


TOOLKIT = "nvidia-container-toolkit"


def container_row(n):
    """The NVIDIA container toolkit as a row of the node's Toolchains tab
    (R102), or None where the node reports no NVIDIA card or no Docker: what
    lets a container there reserve the card. The machine's own like the
    driver it needs, and from NVIDIA's package source, which its install
    adds and its removal takes away; Docker reloads its configuration for
    it, and no container stops."""
    rep = n.get("reported") or {}
    if not rep.get("gpu_card") or not rep.get("docker"):
        return None
    gc = rep.get("gpu_container")
    known = isinstance(gc, dict)
    gc = gc if known else {}
    inst, cand = gc.get("installed") or "", gc.get("candidate") or ""
    drv = driver_row(n) or {}
    state = ("unknown" if not known
             else "absent" if not inst
             else "ready" if gc.get("runtime")
             else "unconfigured")
    return {"name": TOOLKIT, "label": "NVIDIA container toolkit", "installed": inst,
            "state": state, "managed": bool(rep.get("sandbox")), "here": bool(inst),
            "newer": cand if inst and cand and cand != inst else "",
            # The driver on the machine, which the toolkit hands to a
            # container: without it an install is refused, by name.
            "driver": bool(drv.get("here")),
            # ...and running the card, which is when a container sees it.
            "driver_loaded": drv.get("state") in ("loaded", "update")}


def claude_row(n):
    """Claude Code as a row of the node's Toolchains tab (R145), or None on
    a node that runs no session account: what a Claude session there runs,
    installed on purpose rather than by the provisioner, checked and updated
    like the rest. The version is the census's (claude --version as the
    session account); the latest is claudecode's check; the job behind
    install, update and remove is claudecode's, which ends the node's Claude
    sessions first, since the binary is swapped under nothing."""
    se = (n.get("reported") or {}).get("session") or {}
    # A hosting-only node runs no session, so nothing there runs Claude
    # Code: no row, whatever its census says (the operator, 11 Oct).
    if not claudecode or n.get("kind") != "agent" or not se.get("up") or (n.get("config") or {}).get("host_only"):
        return None
    inst = claudecode.installed(n)
    cur = claudecode.latest()
    job = next(iter(nodes.jobs_for(node_id=n["id"], type=claudecode.JOB, n=1) or []), None) if nodes else None
    running = claudecode.updating(n["id"])
    failed = (job or {}).get("state") == "failed" and not running
    return {"name": CLAUDE, "label": "Claude Code", "installed": inst, "latest": cur.get("version") or "",
            "state": ("absent" if not inst else "update" if claudecode.behind(n) else "current"),
            "managed": bool((n.get("reported") or {}).get("sandbox")), "here": bool(inst),
            "running": running, "action": ((job or {}).get("spec") or {}).get("action") or "install",
            "error": str((job or {}).get("error") or "")[:200] if failed else "",
            "checked": int(cur.get("at") or 0), "check_error": cur.get("error") or ""}


def container_why(n):
    """Why a container on this node cannot be given its NVIDIA card, in
    words for the row that asked, or "" when it can: the card, the driver
    running it, the toolkit, and Docker listing the runtime."""
    if not n:
        return "there is no node with an NVIDIA card behind it"
    row = container_row(n)
    name = n.get("name") or "its node"
    if not (n.get("reported") or {}).get("gpu_card"):
        return f"{name} has no NVIDIA card"
    if not row:
        return f"{name} reports no Docker"
    if row["state"] == "unknown":
        return f"{name}'s agent does not report the NVIDIA container toolkit yet: update it on the Nodes tab"
    if row["state"] == "absent":
        return (f"{name} has no NVIDIA container toolkit, which is what hands the card to a container: "
                "an administrator installs it from that node's Toolchains tab")
    if row["state"] == "unconfigured":
        return (f"Docker on {name} does not list the nvidia runtime, though the toolkit is installed: "
                "install the toolkit again from that node's Toolchains tab, which configures it")
    if not row["driver_loaded"]:
        return f"NVIDIA's driver is not running the card on {name}: its Toolchains tab says where it stands"
    return ""


def _machine_name(n, action, name, also):
    """(the name the job carries, error) for the container toolkit, by the
    machine's own rules as the driver's are: a sandbox's, an agent that
    reports it, not a locked node, and the driver there first (or in the
    same batch, which installs it first)."""
    row = container_row(n)
    if not row:
        return "", f"{n['name']} reports no NVIDIA card with Docker beside it"
    if not row["managed"]:
        return "", (f"{n['name']} is its owner's machine, not a BuilderBot sandbox: the container toolkit "
                    "is installed or removed there, the way NVIDIA's guide does it")
    if row["state"] == "unknown":
        return "", f"{n['name']}'s agent does not report the container toolkit yet: update it on the Nodes tab first"
    if (n.get("config") or {}).get("lock"):
        return "", f"{n['name']} is locked to its console: nothing on it is installed from here"
    if action == "install" and not row["driver"] and DRIVER not in also:
        return "", (f"the NVIDIA driver is not installed on {n['name']}, and the toolkit hands its libraries "
                    "to a container: tick the driver as well, or install it first")
    return name, ""


def _driver_name(n, action, pkg):
    """(the name the job carries for the driver, error): nvidia-driver, or
    nvidia-driver:PACKAGE for a branch picked on the row. The machine's own
    rules, said before anything is queued: a guest machine's driver is its
    owner's, an agent that does not report the driver cannot be asked, a
    branch is one apt offers there, and one branch at a time."""
    row = driver_row(n)
    if not row:
        return "", f"{n['name']} reports no NVIDIA card"
    if not row["managed"]:
        return "", (f"{n['name']} is its owner's machine, not a BuilderBot sandbox: its driver is "
                    "installed or removed there, the way its distribution does it")
    if row["state"] == "unknown":
        return "", f"{n['name']}'s agent does not report the driver yet: update it on the Nodes tab first"
    if (n.get("config") or {}).get("lock"):
        return "", f"{n['name']} is locked to its console: nothing on it is installed from here"
    if action != "install" or not pkg:
        return DRIVER, ""
    if pkg not in {o.get("pkg") for o in row["options"]}:
        return "", f"{pkg} is not a driver apt offers on {n['name']}"
    if row["here"] and row["package"] and pkg != row["package"]:
        return "", (f"{row['package']} is installed on {n['name']}: remove it first, then install "
                    f"{pkg}. One branch at a time")
    return f"{DRIVER}:{pkg}", ""


def node_job(principal, nid, action, names, driver=""):
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
    # The driver leaves the list for the store's checks and joins it again
    # at the end, since it is the machine's and ends at a restart.
    drv = ctk = ""
    if TOOLKIT in names:
        ctk, why = _machine_name(n, action, TOOLKIT, names)
        if why:
            return {"error": why}
    if DRIVER in names:
        drv, why = _driver_name(n, action, driver)
        if why:
            return {"error": why}
    names = [x for x in names if x not in (DRIVER, TOOLKIT)]
    if action == "install" and names:
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
    busy = store_busy(nid, names + [x for x in (drv, ctk) if x], action)
    if busy:
        return {"error": busy}
    # Two architectures on one store used to be refused here, because a flat
    # store could not hold both. It is scoped by platform now: each machine
    # installs under <store>/<os>-<arch> (roadmap R19), so a Mac and a Linux
    # box sharing a share is the design, not a mistake.
    r = nodes.job_add(principal, {"node": nid}, "toolchain",
                      {"action": action, "names": names + [x for x in (drv, ctk) if x], "timeout": 3600})
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

    The libraries a toolchain needs are the machine's own, outside the
    store, so they can be missing while the toolchain is there (a package
    removed since, a machine rebuilt under its store). Those packages were
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
            try:
                me = nodes.node(nodes.LOCAL)
                mine = store_areas(list(names), action, _dir_of(me))
                for other in store_sharers(nodes.LOCAL):
                    for t in STORE_JOBS:
                        for j in nodes.jobs_for(node_id=other["id"], type=t, active=True, n=4):
                            if mine & _job_areas(j, _dir_of(other)):
                                return False
            except sqlite3.Error as e:
                print(f"dashboard: toolchains: store sharers unread, going ahead: {e}",
                      file=sys.stderr, flush=True)
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
        with contextlib.suppress(Exception):
            node_checks_due()
        time.sleep(300)


def node_checks_due(now=None):
    """Each node's own weekly check (the operator, 6 Oct: a node's tab said
    its versions were checked twelve days ago). The loop above checked only
    this controller's store, and a node's answers are its last check job's,
    so they aged until somebody pressed Check. A live node with a toolchain
    store whose last check ended a week ago or more, and that has no
    toolchain job waiting or running, is queued one, as is one that has just
    started, whatever its last check. The node ids queued."""
    if not nodes or not TOOLCHAINS:
        return []
    now = time.time() if now is None else now
    queued = []
    for n in nodes.node_list():
        if n.get("kind") != "agent" or n.get("state") != "online" or n.get("live") is False:
            continue
        if not (((n.get("reported") or {}).get("stores") or {}).get("toolchains")):
            continue
        jobs = nodes.jobs_for(node_id=n["id"], type="toolchain", n=20) or []
        if any(j.get("state") in ("queued", "assigned", "running") for j in jobs):
            continue
        last = max((int(j.get("ended") or 0) for j in jobs
                    if (j.get("spec") or {}).get("action") == "check"), default=0)
        # ...or sooner, for a node that has just started (nodes.checks_wanted).
        wanted = n["id"] in getattr(nodes, "checks_wanted", ())
        if last and now - last < TC_CHECK_EVERY and not wanted:
            continue
        r = node_job("system", n["id"], "check", [])
        if r.get("ok") or r.get("job"):
            queued.append(n["id"])
            getattr(nodes, "checks_wanted", set()).discard(n["id"])
    # Claude Code on the same clock (R145): asked once for every node, since
    # what is out is one answer, when any node was due or a week has passed.
    if claudecode and (queued or now - int(claudecode.latest().get("at") or 0) >= TC_CHECK_EVERY):
        with contextlib.suppress(Exception):
            claudecode.check()
    return queued


# ---- the Tools card's verbs, one call from the dashboard ---------------------

def verb(action, req, principal):
    """Queue installs or removals of the toolchains the Tools card offers,
    once server.py has let an administrator ask: here, or on another node
    as a job against that node's store. Names are checked against
    TOOLCHAINS rather than passed through: what reaches a command line is a
    string this server chose, which is the rule every other executing
    endpoint here follows. (payload, status)."""
    nid = field(req, "node")
    if nid and nid != "local":
        # On another node the install is a job against that node's
        # toolchain store (docs/nodes.md §6): same catalog, same names,
        # audited, one at a time there, and gated on the store's
        # headroom before a byte is downloaded.
        if nodes is None:
            return {"error": "the node store did not open"}, 500
        if action == "clean":
            # What the store holds that no node runs from (cleanable), taken
            # off by a job on this node; only the names offered, never a path.
            offered = {c["dir"] for c in cleanable(nid)}
            want = [d for d in (req.get("names") or []) if d in offered]
            if not want:
                return {"error": "nothing on this store is waiting to be taken off"}, 400
            if (why := store_busy(nid, None)):
                return {"error": why}, 409
            r = nodes.job_add(principal, {"node": nid}, "toolchain", {"action": "clean", "names": want,
                                                                     "timeout": 3600})
            return (r, 400) if r.get("error") else ({"ok": True, "job": r.get("job"), "queued": want}, 200)
        if action not in ("install", "remove", "sysdeps", "check"):
            return {"error": "a node takes install, remove, sysdeps or check"}, 400
        node = nodes.node(nid)
        if not node:
            return {"error": "no such node"}, 400
        known = {p["name"] for p in TOOLCHAINS}
        # The NVIDIA driver is a name like the others on a node that has
        # the card (R102); node_job decides whether it may be touched.
        if (node.get("reported") or {}).get("gpu_card"):
            known = known | {DRIVER, TOOLKIT}
        # Claude Code is its own job (claudecode.py): an install or an update
        # runs the installer as the session account and ends the node's
        # Claude sessions first; a removal takes the copy off (R145). Ticked
        # with the store's recipes, it is queued beside their job rather
        # than refused (the operator, 11 Oct: "why does claude have to be on
        # its own"); the node runs the two one after the other.
        want = [str(x) for x in (req.get("names") or [])]
        claude_r = None
        if CLAUDE in want and action in ("install", "remove") and claudecode:
            claude_r = claudecode.update(principal, nid) if action == "install" else claudecode.remove(principal, nid)
            rest = [x for x in want if x != CLAUDE]
            if not rest or claude_r.get("error"):
                return claude_r, (400 if claude_r.get("error") else 200)
            req = dict(req, names=rest)
        # A press of Check for updates asks Claude Code's latest too, in the
        # same answer, like the store's recipes (R145).
        claude_said = claudecode.check() if action == "check" and claudecode else None
        if action == "check":
            # Every row, or the ones named: the question a check answers
            # is "is any of this out of date", and an uninstalled row's
            # answer is what it would fetch, which is half the reason to
            # press it (R67).
            names = [n for n in (req.get("names") or []) if n in known]
        elif action == "sysdeps":
            # The system packages the held recipes need, installed
            # without the recipes (roadmap R51): named ones, or every
            # held one when none are named.
            names = [n for n in (req.get("names") or []) if n in known][:8]
        else:
            names = [n for n in (req.get("names") or []) if n in known][:8]
            if not names:
                return {"error": "nothing selected"}, 400
        r = node_job(principal, nid, action, names, driver=field(req, "driver"))
        if claude_said is not None:
            r = r | {"claude": {"version": claude_said.get("version") or "", "error": claude_said.get("error") or ""}}
        if claude_r is not None:
            # Both jobs queued: the recipes' and Claude Code's, said together.
            r = r | {"claude_job": claude_r.get("job") or "", "note": "Claude Code is its own job beside this one"}
        return r, (400 if r.get("error") else 200)
    if action == "abort":
        return {"ok": abort_job()}, 200
    if action not in ("install", "remove", "update", "check"):
        return {"error": "unknown action"}, 400
    known = {p["name"] for p in TOOLCHAINS}
    names = [n for n in (req.get("names") or []) if n in known]
    # Checking is about everything, not a selection: the question it
    # answers is "is any of this out of date, and what would the rest of
    # it install". The uninstalled rows are half the reason to press it:
    # a version you can read before spending the gigabytes.
    if action == "check" and not names:
        names = [p["name"] for p in TOOLCHAINS]
    if not names:
        return {"error": "nothing selected"}, 400
    if not start_job(action, names):
        # Which one, because the automatic version check holds the queue
        # too and being told "an install is already running" when nobody
        # started an install is the kind of answer that wastes an evening.
        return {"error": "a version check is running; try again in a moment"
                if job_is_automatic() else "an install is already running"}, 409
    return {"ok": True, "queued": names}, 200
