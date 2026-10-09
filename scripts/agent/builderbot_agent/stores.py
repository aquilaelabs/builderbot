"""The node's stores: where data, cache, artifacts and the toolchains live, the rules for a store's path, and node.json."""
import contextlib
import json
import os
import platform
import subprocess
from .base import DEFAULT_STORES, NODE_JSON, STORE_DENY_EXACT, STORE_DENY_UNDER, _run, log


def _can_chown(path):
    """Whether this filesystem lets root change a file's owner.

    The discriminator between a local disk and a squashed NFS export, asked
    rather than guessed from the mount type: squashing is the server's
    policy and does not show in fstab. A chown to root:root is the test
    because it is a no-op locally and refused wherever ownership is the
    export's to decide.
    """
    probe = os.path.join(path, f".bb-chown-probe.{os.getpid()}")
    try:
        with open(probe, "w"):
            pass
    except OSError:
        return True          # cannot even write: the copy will say so itself
    try:
        os.chown(probe, 0, 0)
        return True
    except OSError:
        return False
    finally:
        with contextlib.suppress(OSError):
            os.remove(probe)


def store_path_ok(path):
    """"" if this is a safe place for a store, else why not. A bare
    top-level directory is refused as well as a system one: /mnt is where
    mounts live, not a store, and putting one there scatters directories
    across the mount root."""
    p = str(path or "").rstrip("/") or "/"
    if not p.startswith("/"):
        return f"{path!r} is not an absolute path"
    if " " in p or ".." in p.split("/"):
        return f"{path!r} must be a plain absolute path, with no spaces or .."
    if p in STORE_DENY_EXACT:
        return (f"{p} is a system directory (or the root of the mounts): "
                "a store is a directory of its own, like /var/lib/builderbot/x "
                "or /mnt/<share>/<dir>")
    for bad in STORE_DENY_UNDER:
        if (p + "/").startswith(bad):
            return f"{p} is inside {bad.rstrip('/')}, which this agent will not write to"
    return ""
def make_store(path):
    """Create a store directory, and say which directories that actually
    brought into being.

    The list is the whole point. A store at /mnt/tank/bb/toolchains may have
    made two directories or none, and there is no way to tell afterwards:
    an empty /mnt/tank/bb could be ours or could be the operator's. So it is
    recorded at the moment of creation, and nothing outside that record is
    ever removed.
    """
    p = os.path.abspath(str(path))
    made, probe = [], p
    while probe and probe != "/" and not os.path.exists(probe):
        made.append(probe)
        probe = os.path.dirname(probe)
    os.makedirs(p, exist_ok=True)
    made.reverse()                      # shallowest first: the order they appeared
    return made


def prune_made(made):
    """Remove the directories in `made` that are now empty, deepest first.

    rmdir rather than a check-then-delete: it fails with ENOTEMPTY by
    itself, so there is no window between deciding a directory is empty and
    removing it. The first one that will not go stops the walk (a parent of
    something that is still there cannot be empty either), and a mountpoint
    is never touched, because removing the directory a share is mounted on
    is how you delete the thing you meant to detach.

    Returns (removed, [(path, why)]).
    """
    removed, kept = [], []
    for d in reversed(list(made or [])):
        if os.path.ismount(d):
            kept.append((d, "it is a mountpoint"))
            break
        try:
            os.rmdir(d)
            removed.append(d)
        except OSError as e:
            kept.append((d, e.strerror or "it would not go"))
            break
    return removed, kept


def mount_covering(path, mounts):
    """The bb-sandbox mount this path would live inside, or None.

    The deepest match wins, so /mnt/tank/builderbot/toolchains is answered by
    /mnt/tank rather than by /mnt if both are configured. This is what makes
    an unmounted share detectable: the mount is in fstab, the directory
    under it is not, and mkdir would quietly make a local one.
    """
    p = str(path or "").rstrip("/")
    best = None
    for m in mounts or []:
        mp = str(m.get("path") or "").rstrip("/")
        if not mp:
            continue
        if p == mp or p.startswith(mp + "/"):
            if best is None or len(mp) > len(str(best.get("path") or "").rstrip("/")):
                best = m
    return best


def dir_bytes(path):
    """What is in there, in bytes, or None if it cannot be told quickly.
    `du` rather than a walk: one C process instead of a stat per file, which
    matters on the far end of an NFS link."""
    try:
        out = subprocess.run(["du", "-sb", path], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=180, check=False)
        return int(out.stdout.split()[0]) if out.returncode == 0 else None
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


STORE_ID_FILE = ".bb-store-id"


# ---------------------------------------------------------------------------
# the toolchain store, scoped by platform (roadmap R19)
#
# One share can serve a Linux box, a Mac and a Windows machine only if their
# binaries do not land on top of each other: the store's root is therefore
# <store>/<os>-<arch> (linux-x86_64, darwin-arm64), and everything else
# (the layout, the probes, the census, the bundle) is relative to that. The
# operator's setting stays the share; the scope is this machine's own fact.
# What is the same bytes on every host (the Android system images, tens of
# gigabytes) lives once under <store>/shared and each scope's android tree
# links to it, because sdkmanager and Gradle want one ANDROID_HOME and
# would otherwise fetch a second copy per platform. (The one-time move of a
# flat store into its scope ran on 9 Sep 2026 and was taken out again.)


def tc_scope():
    """This machine's scope directory name: <os>-<arch> as uname spells them."""
    return f"{platform.system().lower()}-{platform.machine() or 'unknown'}"


def tc_root(state):
    """Where THIS machine's toolchains live: the toolchain store's scope
    directory, or "" when the node has no toolchain store."""
    store = (state.get("stores") or {}).get("toolchains") or ""
    return os.path.join(store, tc_scope()) if store else ""


def store_id(path):
    """A stable id for a store, from a marker inside it: the same file the
    controller reads for its own (nodes.store_id).

    Two machines mounting one share cannot recognize each other by path: the
    controller reaches the toolchain store through Unraid's FUSE layer while this
    node reaches the same bytes over NFS, and neither mount string can be
    derived from the other. The file answers exactly, whatever the transport.
    Read-only here: the controller creates it, so a node with a read-only
    store still reports the right id and never writes to one it should not.
    """
    try:
        with open(os.path.join(path, STORE_ID_FILE)) as f:
            return f.read().strip()[:64]
    except OSError:
        return ""


def _stores(stores, used=False):
    out = {}
    for role, path in (stores or {}).items():
        try:
            st = os.statvfs(path)
            out[role] = {"path": path, "id": store_id(path),
                         "free_mb": st.f_bavail * st.f_frsize // (1024 * 1024),
                         "total_mb": st.f_blocks * st.f_frsize // (1024 * 1024)}
            if role == "toolchains":
                out[role]["scope"] = tc_scope()      # where THIS machine's toolchains are, under path
        except OSError:
            # Not there is a different fact from full: reported as null so
            # the row says "missing" rather than "0MB free".
            out[role] = {"path": path, "free_mb": None, "total_mb": None}
            continue
        if used:
            # What the store itself holds; the cache's size is the number
            # the row shows beside its Clear (docs/nodes.md §6). du, at the
            # census only: a walk of a big cache is not a per-poll cost.
            n = _run(["du", "-sm", path], timeout=60).split()
            out[role]["used_mb"] = int(n[0]) if n and n[0].isdigit() else None
    return out


# Where a toolchain installed into the toolchain store keeps its command,
# relative to the store (bb toolchains's layout), for the census to find without
# PATH knowing about it. `android` is a directory, not a command.
def _lay_path(store, entry, rel):
    """A layout path against the store. `root:` means the store itself;
    anything else is under the toolchain's own directory."""
    if rel.startswith("root:"):
        return os.path.join(store, rel[5:])
    return os.path.join(store, entry["dir"], rel) if rel else \
        os.path.join(store, entry["dir"])


def store_layout(state):
    """What the controller last told us about where toolchains land, or the
    built-in answer for a controller too old to say.

    The fallback is deliberately the old tables: a node whose controller
    predates this must keep working, and a node whose controller is newer
    must follow it rather than a copy of its own that can drift.
    """
    got = state.get("layout")
    return got if isinstance(got, list) and got else BUILTIN_LAYOUT


# The answer this agent shipped with, used only when the controller does not
# send one. Kept short and honest: it is a fallback, not a second authority.
BUILTIN_LAYOUT = [
    {"name": "jdk", "dir": "jdk", "bin": ["bin"], "env": {"JAVA_HOME": ""},
     "tool": "bin/java", "reports": "java"},
    {"name": "flutter", "dir": "flutter", "bin": ["bin"], "env": {},
     "tool": "bin/flutter", "reports": "flutter"},
    {"name": "dotnet", "dir": "dotnet", "bin": ["", "tools"],
     "env": {"DOTNET_ROOT": ""}, "tool": "dotnet", "reports": "dotnet"},
    {"name": "go", "dir": "go", "bin": ["bin"], "env": {}, "tool": "bin/go",
     "reports": "go"},
    {"name": "lint-tools", "dir": "lint-tools", "bin": ["bin"], "env": {},
     "tool": "bin/shellcheck", "reports": "shellcheck"},
    {"name": "node", "dir": "node", "bin": ["bin"], "env": {}, "tool": "bin/node",
     "reports": "node"},
    {"name": "swift", "dir": "swift", "bin": ["usr/bin"], "env": {},
     "tool": "usr/bin/swift", "reports": "swift"},
    {"name": "rust", "dir": "rust", "bin": ["cargo/bin"],
     "env": {"RUSTUP_HOME": "rustup", "CARGO_HOME": "cargo"},
     "tool": "cargo/bin/cargo", "reports": "rust"},
    {"name": "zig", "dir": "zig", "bin": [""], "env": {}, "tool": "zig", "reports": ""},
    {"name": "android-tools", "dir": "android-tools",
     "bin": ["root:android/cmdline-tools/latest/bin", "root:android/platform-tools"],
     "env": {}, "tool": "cmdline-tools/bin/sdkmanager", "reports": ""},
    {"name": "android:emulator", "dir": "android", "bin": ["root:android/emulator"],
     "env": {}, "tool": "root:android/emulator/emulator", "reports": "emulator"},
]

STORE_TOOLS = {"java": ("jdk/bin/java",), "flutter": ("flutter/bin/flutter",),
               "dotnet": ("dotnet/dotnet",), "go": ("go/bin/go",),
               "node": ("node/bin/node",), "swift": ("swift/usr/bin/swift",),
               "cargo": ("rust/cargo/bin/cargo",),
               # The BINARIES, not the directories they sit in. Checking the
               # directories called android-sdk present on a node whose
               # cmdline-tools was an empty folder and whose platform-tools
               # did not exist, so toolchain_gap admitted a job needing adb
               # and it failed there instead of being refused here.
               "android-sdk": ("android/platform-tools/adb",
                               "android/cmdline-tools/latest/bin/sdkmanager",
                               "android/cmdline-tools/bin/sdkmanager"),
               "emulator": ("android/emulator/emulator",),
               # adb on its own: a phone is driven from whichever node has
               # it, and the Phone tab's picker reads this.
               "adb": ("android/platform-tools/adb",),
               # web-ext beside it: pushing a Firefox extension to the phone
               # is web-ext driving that adb, on the same node.
               "web-ext": ("node/bin/web-ext",)}


def store_dirs(state):
    """What is actually IN the toolchain store, as directory names.

    The census's `toolchains` above is a placement summary (six names, so a
    job can select on them), and it was being read as an inventory of the
    whole catalog, which called four installed toolchains missing on a store
    the controller could see for itself. `bb toolchains` puts each toolchain in
    <root>/<name>, and android's parts under <root>/android/, so the names
    ARE the inventory and this is one listdir.
    """
    store = tc_root(state)
    out = {"top": [], "android": []}
    if not store:
        return out
    with contextlib.suppress(OSError):
        out["top"] = sorted(x for x in os.listdir(store) if not x.startswith("."))[:64]
    with contextlib.suppress(OSError):
        out["android"] = sorted(os.listdir(os.path.join(store, "android")))[:64]
    # A directory is not a toolchain: an install that stopped part-way leaves
    # one without the file that completes it (playwright's module beside its
    # browsers). A layout that names that file (`needs`) is checked here, and
    # the controller reads a name in this list as not installed.
    for entry in store_layout(state):
        need = entry.get("needs")
        if not need or entry.get("dir", "").startswith("android"):
            continue
        d = os.path.join(store, entry["dir"])
        if os.path.isdir(d) and not os.path.exists(os.path.join(d, need)):
            out.setdefault("incomplete", []).append(entry["name"])
    return out


# ---------------------------------------------------------------------------
# node.json

def load_state():
    try:
        with open(NODE_JSON) as f:
            return json.load(f)
    except OSError as e:
        raise SystemExit(f"{NODE_JSON} is missing; enroll this node first: "
                         "builderbot-agent enroll --controller URL --token …") from e
    except ValueError as e:
        raise SystemExit(f"{NODE_JSON} is not JSON ({e}); enroll again") from e


def fill_default_stores(state):
    """Give an already-enrolled node a store role it predates; True if it
    gained one.

    The store list is written at ENROLMENT and never revisited, so a node
    enrolled before `appdata` existed would never have one and the controller
    would answer its fallback forever. A role added to DEFAULT_STORES has to
    reach the nodes that are already out there or it only ever works on the
    next machine somebody enrols.

    Placed BESIDE the store this node already keeps its data in, never at the
    hard-coded default: a guest node keeps everything under one directory in
    its owner's home (R23), and handing it /var/lib/builderbot would be a
    path it has no root to make. Where data sits is where the rest belongs.
    """
    have = state.get("stores") if isinstance(state.get("stores"), dict) else {}
    base = os.path.dirname(str(have.get("data") or "")) if have.get("data") else ""
    added = False
    for role, default in DEFAULT_STORES.items():
        if have.get(role):
            continue
        have[role] = os.path.join(base, role) if base else default
        # MADE, not just recorded. A store that exists only in node.json
        # reports null free space and the row calls it missing, which is the
        # true answer and a useless one for a directory nothing else is ever
        # going to create: enrolment makes the four it knows about, so
        # adoption makes the one it did not. Best effort, the same as there:
        # a store that cannot be made is reported rather than fatal.
        try:
            made = state.setdefault("store_made", {})
            if isinstance(made, dict):
                made[role] = make_store(have[role])
        except OSError as e:
            log(f"stores: {role} at {have[role]} could not be created "
                f"({e.strerror}); it will report no space until it exists")
        log(f"stores: {role} was not set; using {have[role]}")
        added = True
    if added:
        state["stores"] = have
    return added


def save_state(state):
    d = os.path.dirname(NODE_JSON)
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = NODE_JSON + ".tmp"
    with open(tmp, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        json.dump(state, f, indent=2)
    os.replace(tmp, NODE_JSON)
