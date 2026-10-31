"""The node's stores: where data, cache, artifacts and the toolchains live, the rules for a store's path, and node.json."""
import contextlib
import json
import os
import re
import subprocess
from .base import NODE_JSON, STORE_DENY_EXACT, STORE_DENY_UNDER, _run, log


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


def store_path_ok(path, what="a store"):
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
                f"{what} is a directory of its own, like /var/lib/builderbot/x "
                "or /mnt/<share>/<dir>")
    for bad in STORE_DENY_UNDER:
        if (p + "/").startswith(bad):
            return f"{p} is inside {bad.rstrip('/')}, which this agent will not write to"
    # ...and where it really is, held to the same: a link on a share that
    # points at /etc passed as text, and root then copied a store's tree
    # into /etc. A link to somewhere a store may be (macOS's /tmp) is fine.
    real = os.path.realpath(p)
    if real != p and (why := store_path_ok(real, what)):
        return f"{p} is a link to {real}, and {why}"
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
# the toolchain store, a directory per node (R196)
#
# One share can serve any number of machines only if their binaries do not
# land on top of each other: a node's root is therefore <store>/<node id>,
# and everything else (the layout, the probes, the census, the bundle) is
# relative to that. The operator's setting stays the share. What is the same
# bytes on every host (the Android system images, tens of gigabytes) lives
# once under <store>/shared and each node's android tree links to it,
# because sdkmanager and Gradle want one ANDROID_HOME and would otherwise
# fetch a second copy per node.


# This node's own directory under the toolchain store (R196, the operator, 12
# Oct): its node id, so no two machines share a directory of toolchains,
# whatever distro each runs, and an id is never renamed or reused. Set by the
# agent from its state at start and on every hello (use_scope). An agent that
# has no id has no toolchain directory: tc_root is "" and every toolchain
# job says the node has no store.
_SCOPE = {"name": ""}
_ID = re.compile(r"n_[0-9a-f]{4,32}")


def tc_scope():
    """This node's directory name under the toolchain store, its node id,
    or "" before it has one."""
    return _SCOPE["name"]


def use_scope(store, node_id):
    """Make <store>/<node id> this node's directory. Returns the name in use."""
    node_id = str(node_id or "")
    if not _ID.fullmatch(node_id):
        return tc_scope()
    if store and os.path.isdir(store):
        try:
            os.makedirs(os.path.join(store, node_id), exist_ok=True)
        except OSError as e:
            log(f"toolchains: could not make {os.path.join(store, node_id)} ({e})")
            return tc_scope()
    _SCOPE["name"] = node_id
    return node_id


def noexec(path):
    """True when `path` is on a filesystem mounted noexec: nothing in it can
    run, the bb bundle and its terminals included (a tmpfs Docker made is
    noexec unless told otherwise)."""
    try:
        return bool(os.statvfs(path).f_flag & os.ST_NOEXEC)
    except (OSError, AttributeError):
        return False


def tc_root(state):
    """Where THIS machine's toolchains live: <store>/<node id>, or "" when
    the node has no toolchain store or no id yet."""
    store = (state.get("stores") or {}).get("toolchains") or ""
    return os.path.join(store, tc_scope()) if store and tc_scope() else ""


def store_id(path):
    """A stable id for a store, from a marker inside it: the same file the
    controller reads for its own (nodes.store_id).

    Two machines mounting one share cannot recognize each other by path: the
    controller reaches the toolchain store through the host's user-share layer while this
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
    built-in answer before it has said (the census a first hello carries)
    or when its catalog did not open.

    The controller's answer wins whenever there is one: a node follows it
    rather than a copy of its own that can drift.
    """
    got = state.get("layout")
    return got if isinstance(got, list) and got else BUILTIN_LAYOUT


# The answer this agent shipped with, used only when the controller has not
# sent one. Kept short and honest: it is a fallback, not a second authority.
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


def _own_tool(entry):
    """The layout's tool when it lives in the toolchain's own directory
    (`root:` names one elsewhere in the store)."""
    t = str(entry.get("tool") or "")
    return "" if t.startswith("root:") else t


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
    # An empty directory is no toolchain: a delete that could not finish
    # (a file still open over NFS) or a mount point leaves one, and listed,
    # an empty android/platform-tools read as two Android rows installed on
    # a store wiped to start over (the operator, 12 Oct).
    def full(d):
        # ...nor one an install has not finished (its marker beside it,
        # sdk.sh sdk_mark_partial): half a toolchain left by an Abort read
        # as installed (the operator, 12 Oct).
        if os.path.exists(os.path.join(os.path.dirname(d), ".bb-installing." + os.path.basename(d))):
            return False
        with contextlib.suppress(OSError):
            if not os.path.isdir(d):
                return False
            with os.scandir(d) as entries:
                return any(True for _ in entries)
        return False
    with contextlib.suppress(OSError):
        out["top"] = sorted(x for x in os.listdir(store) if not x.startswith(".")
                            and full(os.path.join(store, x)))[:64]
    with contextlib.suppress(OSError):
        out["android"] = sorted(x for x in os.listdir(os.path.join(store, "android"))
                                if x.startswith(".") or full(os.path.join(store, "android", x)))[:64]
    # ...and the versions under android's versioned families (B712): what a
    # project pins (ndkVersion, buildToolsVersion, compileSdk) is a directory
    # here, one listdir each, and the controller says which pins this store
    # lacks. The key is sent even when empty: it is absent only where there
    # is no toolchain store, which the controller reads as "cannot say".
    vers = {}
    for sub in ("ndk", "build-tools", "platforms", "cmake"):
        d = os.path.join(store, "android", sub)
        with contextlib.suppress(OSError):
            vers[sub] = sorted(x for x in os.listdir(d)
                               if not x.startswith(".") and full(os.path.join(d, x)))[:64]
    out["versions"] = vers
    # A directory is not a toolchain: an install that stopped part-way leaves
    # one without the file that completes it (playwright's module beside its
    # browsers). A layout that names that file (`needs`) is checked here, and
    # the controller reads a name in this list as not installed.
    # Where none is named, the tool the layout runs is that file: a flutter
    # left with no bin/flutter (an install cut short before the marker
    # existed) was listed installed and `flutter` was not found (diagnostics
    # #124).
    for entry in store_layout(state):
        need = entry.get("needs") or _own_tool(entry)
        if not need or entry.get("dir", "").startswith("android"):
            continue
        d = os.path.join(store, entry["dir"])
        if os.path.isdir(d) and not os.path.exists(os.path.join(d, need)):
            out.setdefault("incomplete", []).append(entry["name"])
    # ...and the directories at the top of the store, whose names say whose
    # they are (a node's id, `shared`, the controller's own): a retired
    # node's is the controller's to offer for removal (R196).
    base = (state.get("stores") or {}).get("toolchains") or ""
    if base:
        with contextlib.suppress(OSError):
            out["roots"] = sorted(x for x in os.listdir(base)
                                  if not x.startswith(".") and os.path.isdir(os.path.join(base, x)))[:64]
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


def save_state(state):
    d = os.path.dirname(NODE_JSON)
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = NODE_JSON + ".tmp"
    with open(tmp, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        json.dump(state, f, indent=2)
    os.replace(tmp, NODE_JSON)
