#!/usr/bin/env bash
# The toolchain manager: everything behind `bb toolchains` and the dashboard's Library and Installed page.
#
# Sourced by bb, which keeps the rest of the CLI. It is a file of its own
# because it is a third of that script and answers a question none of the rest
# of it asks: what can be installed here, what is installed, what upstream
# has, and how to put it there or take it away.
#
# The recipes are not in here either. config/toolchains.json holds every URL,
# branch, flag, argument and archive layout, lib/sdkmeta.py reads it, and what
# is left below is the five shapes those values are poured into plus the
# bookkeeping around them: where a thing lands, what it weighs, whether it is
# already there, and what to undo when an install dies half way.
#
# The primitives it stands on (sdk_root, sdk_have, sdk_find) are in
# common.sh, because a startup hook and `bb status` need to know where the SDK
# root is without pulling in a toolchain manager to ask.

# bb toolchains: the toolchains that are too big to live in the image.
#
# Everything here installs into the toolchain store root (a mapped share, or the home
# volume when there is none) and is symlinked or PATH-ed into place, so an
# image update never re-downloads it. The image carries only what is needed
# to bootstrap: sdkmanager, adb, and this command.
#
# Each recipe unpacks into its own directory under the root and is undone by
# deleting that directory: no system packages, nothing outside the root, so
# `bb toolchains remove` is a plain rm and a container rebuild changes nothing.
SDK_TOOLCHAINS="android node jdk playwright flutter dotnet swift go rust zig"

# What `bb toolchains check` and `bb toolchains versions` answer for when asked for nothing
# in particular: the same catalog the dashboard renders, read from the file
# rather than repeated here, so adding a toolchain is one edit and not two that
# can drift. config/toolchains.json sits at the same place relative to this
# script in the image and in a checkout.
# The catalog, at the one place it sits relative to this file in both the
# image and a checkout.
sdk_meta_file() {
    printf '%s' "$(dirname "$(readlink -f "$0")")/../config/toolchains.json"
}

sdk_checkable() {
    local f names; f="$(sdk_meta_file)"
    [ -f "$f" ] || die "no toolchain catalog at ${f}: is this an older image?"
    # ...with the tool packs added beside it (R77), through sdkmeta's reader.
    names="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[2]); import sdkmeta
print(" ".join(r["name"] for r in sdkmeta.catalog_at(sys.argv[1])))' "$f" "$BB_LIB" 2>/dev/null)"
    # Empty means the file is there and unreadable, which is worth saying:
    # returning nothing quietly turns `bb toolchains check` into a command that
    # succeeds and does nothing at all.
    [ -n "$names" ] || die "could not read the toolchain catalog at ${f}"
    printf '%s' "$names"
}

sdk_dir() { printf '%s/%s' "$(sdk_root)" "$1"; }

# Where sdkmanager is told the toolchain store root is, and it has to be TOLD.
#
# sdkmanager works <sdk> out from where it is installed, expecting to sit at
# <sdk>/cmdline-tools/latest/bin, and refuses rather than guessing when it
# cannot: "Could not determine SDK root". In this container it is there. On a
# node it is not: `bb toolchains install android-tools` unpacks the tools into
# <store>/android-tools and links <store>/android/cmdline-tools/latest at
# them, and the wrapper resolves that link PHYSICALLY, landing outside the
# SDK tree entirely. ANDROID_HOME and ANDROID_SDK_ROOT are both set for the
# job and both ignored; measured on bb-sandbox on 4 Sep, where the bare call
# refused and the same call with this flag listed the store.
#
# That is why `bb toolchains install android:platform-tools` failed on a node with a
# message naming neither the toolchain nor the store, and why every android:*
# toolchain (and every system image) could not be installed there. So the
# root is passed on every call, and nothing here invokes sdkmanager without
# it. The flag lives in one function so the two forms below cannot drift.
# ANDROID_HOME when it is set, the store's android/ directory otherwise. On
# a node the agent sets ANDROID_HOME to that directory for every job and
# session; on the controller nothing sets it since the image stopped
# carrying /opt/android-sdk (10c), and the store is the only root there is;
# sdk_relink_android, which points an image-side SDK tree onto the share,
# finds no such tree and does nothing. One value, correct in both
# places, and sdkmanager never runs without it.
sdk_root_flag() { printf -- '--sdk_root=%s' "${ANDROID_HOME:-$(sdk_dir android)}"; }
sdkmgr() {
    # Every install goes past the licenses first; see below for why that is
    # here rather than at each call site.
    if [ "${1:-}" = --install ]; then sdk_android_licenses; fi
    # Taking a package off needs no sdkmanager: without the command-line
    # tools (removed, or never installed) the trash bin on an Android row
    # could not remove it (the operator, 12 Oct). Its directory is the
    # package; deleted directly.
    if [ "${1:-}" = --uninstall ] && ! command -v sdkmanager >/dev/null 2>&1; then
        local root d
        root="${ANDROID_HOME:-$(sdk_dir android)}"
        d="$root/${2//;//}"
        case "$d" in */../*|*/..) die "not a package path: ${2:-}" ;; esac
        log "no sdkmanager here (the Android command-line tools are not installed): removing ${d} directly"
        rm -rf "${d:?}"
        return 0
    fi
    sdkmanager "$(sdk_root_flag)" "$@"
}

# The android SDK licenses, once per toolchain store root.
#
# sdkmanager installs nothing into a root whose licenses have not been
# accepted, and the refusal names the package rather than the license. They
# are Google's terms, and a person accepts them: the Library names
# them, links them and asks before it queues the install, and the server
# keeps who accepted. The job that page queues then records that acceptance
# here, in the store, the way sdkmanager keeps it.
#
# Never a session's to accept: a Claude session that runs `bb toolchains
# install android:...` on a store nobody has accepted the terms for is
# refused, and sent to the page, rather than accepting them for a person.
#
# Skipped when the directory is there: accepting is a JVM start, and a store
# that has been through this once does not need it again. If Google ships a
# new license the install refuses with sdkmanager's message, which at least
# names what to do.
sdk_android_licenses() {
    local root; root="${ANDROID_HOME:-$(sdk_dir android)}"
    [ ! -d "$root/licenses" ] || return 0
    [ -z "${CLAUDECODE:-}${BB_AGENT:-}" ] \
        || die "the Android SDK installs under Google's terms, which a person accepts: install it from the Library, which asks"
    log "recording the android SDK licenses accepted in the Library, for ${root}"
    mkdir -p "$root"
    # `yes` dies of SIGPIPE when sdkmanager stops reading. Expected, not a
    # failure; hence the || true inside the pipeline's first stage.
    (yes || true) | sdkmanager "$(sdk_root_flag)" --licenses >/dev/null 2>&1 || true
}

# The PATH additions for whatever is installed, regenerated on demand rather
# than stored: an install or a removal changes it, and a stale file would
# point at a directory that is not there.
# The PATH and the variables every installed toolchain wants, generated from
# the catalog's `layout` rather than from a list here.
#
# There were three copies of this answer (these lines, and the agent's
# STORE_TOOLS and STORE_PATHS) that had to agree about where every toolchain
# lands. They drifted three times in one day: node/bin missing from one, the
# android-tools probe reading the wrong directory, the census disagreeing
# with the inventory. The catalog says it once now; the node is told at
# hello, and this reads the same field.
sdk_env_snippet() {
    local root d; root="$(sdk_root)"
    printf '# Generated by `bb toolchains env`; do not edit, run the command instead.\n'
    SDK_ROOT="$root" python3 - "$(sdk_meta_file)" "$root" "$BB_LIB" <<'PY'
import os, sys
sys.path.insert(0, sys.argv[3])
import sdkmeta
# The tool packs beside the catalog are rows like any other (R77).
rows = sdkmeta.catalog_at(sys.argv[1])
root = sys.argv[2]


def where(entry_dir, rel):
    if rel.startswith("root:"):
        return os.path.join(root, rel[5:])
    return os.path.join(root, entry_dir, rel) if rel else os.path.join(root, entry_dir)


for p in rows:
    lay = p.get("layout") or {}
    d = "android" if p["name"].startswith("android:") else p["name"]
    for var, rel in (lay.get("env") or {}).items():
        # `=VALUE` is the value itself, as the agent's sdk_env reads it (B548).
        if rel.startswith("="):
            print(f'export {var}="{rel[1:]}"')
            continue
        path = where(d, rel)
        if os.path.exists(path):
            print(f'export {var}="{path}"')
    for rel in (lay.get("bin") or []):
        path = where(d, rel)
        if os.path.isdir(path):
            print(f'export PATH="{path}:$PATH"')
PY
    # Flutter needs to be told where the Android SDK is when ANDROID_HOME is
    # not already in the environment of whatever spawned it.
    if sdk_find flutter >/dev/null && [ -n "${ANDROID_HOME:-}" ]; then
        printf 'export ANDROID_SDK_ROOT="%s"\n' "$ANDROID_HOME"
    fi
    if sdk_have "$root" tizen; then
        printf 'export PATH="%s/tizen/tools/ide/bin:%s/tizen/tools:$PATH"\n' "$root" "$root"
    fi
}

# Rewrite the file every shell sources, so a toolchain installed a minute ago
# is on PATH in the next terminal rather than after the next container
# restart. The startup hook writes the same file from the same generator;
# this is the other half: installs happen at runtime, and without it only
# boot would notice them.
# Where the generated env file lives. NOT in the toolchain store root, which is a share
# two machines mount at different paths: every line in it is absolute
# (/sdk/flutter/bin, RUSTUP_HOME=/sdk/rust/rustup), so a copy written here is
# wrong for the sandbox that mounts the same bytes at /mnt/SDK, and whichever
# machine generated it last won. It was the one piece of machine-specific
# data in a store that is otherwise identical for everybody, the operator's
# own test for what may be shared, and the only thing that failed it.
#
# The home volume instead: container-local, survives a restart, and
# regenerated on every boot and every install anyway.
sdk_env_file() {
    printf '%s/.cache/builderbot/machine/sdk-env.sh' "${BUILDER_HOME:-$HOME}"
}

sdk_write_env() {
    local root file tmp
    root="$(sdk_root)"
    [ -d "$root" ] || return 0
    file="$(sdk_env_file)"
    mkdir -p "$(dirname "$file")" 2>/dev/null || return 0
    tmp="$file.new.$$"
    if sdk_env_snippet > "$tmp" 2>/dev/null; then
        mv -f "$tmp" "$file"
    else
        rm -f "$tmp"
    fi
}

# `bb toolchains` answers for the store the project actually builds with.
#
# A project bound to a node compiles THERE (bb build, bb test, bb run and
# bb emu all go to it), so answering with this container's store told a
# session about a machine its project does not use. Worse on this box, where
# this toolchain store and the node's toolchain store are ONE store under two names
# (/sdk here through the host's user-share layer, /mnt/SDK there over NFS, the same
# store id): the two listings read like two machines' toolchains and were the
# same bytes.
#
# Read from the node's census rather than run as a job there: everything
# below is already in it, so this stays the instant command it has always
# been. `bb toolchains --local` is this container's own store, and BB_NODE_TOOLCHAINS
# means we ARE the node, where local is the right answer.
#
# Only the bare status routes. `bb toolchains versions|check|root|env` are
# what the dashboard shells out to for its own store, and a node's answer
# there would be a silent wrong one.
sdk_status() {
    if [ "${1:-}" != --local ] && [ -z "${BB_NODE_TOOLCHAINS:-}" ] && ! on_node; then
        local node; node="$(project_node 2>/dev/null)"
        if [ -n "$node" ] && sdk_status_node "$node"; then return 0; fi
        # No node: nothing installs on a controller (roadmap #26), so the
        # honest list is empty rather than this container's own store,
        # which holds the browsers its boot put there and is --local's.
        if [ -z "$node" ]; then
            log "this project has no node: toolchains are installed on a node (the Nodes page), and a project with none cannot compile here"
            log "bb toolchains --local lists this container's own store: what its boot keeps for bb capture shot, nothing to install"
            return 0
        fi
    fi
    sdk_status_local
}

# The project's node's store, from the census the agent last sent. Non-zero
# when there is nothing on record, so the caller falls back to the local
# listing: a node that has never dialed in has told us nothing, and inventing
# an inventory for it would be worse than showing this container's.
sdk_status_node() {
    local py; py="$(dirname "$(readlink -f "$0")")/dashboard/nodes.py"
    [ -f "$py" ] || return 1
    DASHBOARD_STATE="${DASHBOARD_STATE:-/config}" python3 - "$py" "$1" <<'NODESTAT'
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("nodes", sys.argv[1])
nodes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nodes)
try:
    nodes.db.open_readonly(os.environ["DASHBOARD_STATE"])
    n = nodes.node(sys.argv[2])
except Exception:
    raise SystemExit(1) from None
rep = (n or {}).get("reported") or {}
store = (rep.get("stores") or {}).get("toolchains") or {}
if not n or not store.get("path"):
    raise SystemExit(1)


def gb(mb):
    return f"{mb / 1024:.0f}G" if mb < 1024 * 1024 else f"{mb / 1048576:.1f}T"


live = "" if n.get("live") else "  (quiet; this is its last census)"
print("== toolchain store root ==")
print(f"  {store['path']}  on {n['name']}, this project's node, "
      f"where its builds run{live}")
if store.get("free_mb"):
    print(f"  {'space':<14} {gb(store['free_mb'])} free")
print("\n== toolchains ==")
vers = rep.get("toolchain_versions") or {}
# The store listing is a listdir, so it carries things that are not
# toolchains: `android` is the SDK tree and has its own section below, and
# env.sh is the generated PATH snippet. Dotted names are already out.
top = [d for d in (rep.get("store_dirs") or {}).get("top") or []
       if not d.startswith(".") and d != "android" and "." not in d]
if not top:
    print("  (the node has not reported what its store holds yet)")
wide = max((len(d) for d in top), default=0)
for name in sorted(top):
    # "installed" where the node could not probe a version: `bb toolchains versions`
    # runs there from a cached bundle, so a store written before any toolchain
    # job has directories and no versions. Present is still the answer.
    print(f"  {name:<{wide}}  {vers.get(name, 'installed')}")
print("\n== android packages ==")
andr = sorted(d for d in (rep.get("store_dirs") or {}).get("android") or []
              if not d.startswith("."))
print("  " + (", ".join(andr) if andr else "none"))
for im in rep.get("images") or []:
    avds = f"  (AVDs: {', '.join(im['avds'])})" if im.get("avds") else ""
    print(f"  {im.get('api', '?'):<24} {im.get('kind', '')} {im.get('abi', '')}{avds}")
print("\nthis container's own store: bb toolchains --local")
NODESTAT
}

sdk_status_local() {
    local root; root="$(sdk_root)"
    printf '== toolchain store root ==\n'
    # Asked about the STORE, not this machine's directory inside it: the
    # mount is the share, and one scope down is never a mountpoint, so a
    # perfectly good share reported itself as the home volume.
    if is_mountpoint "$(sdk_store_root)"; then
        printf '  %s  (mapped share; outside the image, kept across updates)\n' "$root"
    else
        printf '  %s  (home volume; map a share to SDK_ROOT to keep SDKs off it)\n' "$root"
    fi
    # A root that is not there is said out loud rather than left to be
    # inferred from a list of nothing. SDK_ROOT is taken at its word and the
    # scope is appended to it, so pointing it at a store's SCOPED directory
    # resolves one level too deep and every toolchain reads as missing,
    # which looks exactly like an empty store and is not one.
    if [ ! -d "$root" ]; then
        printf '  %s\n' "this directory does not exist, so nothing below is installed here."
        case "$root" in
            */"$(sdk_scope)"/"$(sdk_scope)")
                printf '  %s\n' "SDK_ROOT names the store's $(sdk_scope) directory; it wants the store itself, one level up." ;;
            *)  printf '  %s\n' "SDK_ROOT is ${SDK_ROOT:-unset}; check it names the store, not a directory inside it." ;;
        esac
    fi
    # The root may not exist yet, so ask about the filesystem that will hold it.
    local probe="$root"; [ -d "$probe" ] || probe="$(dirname "$probe")"
    printf '  %-14s %s free\n' "space" "$(df -h "$probe" 2>/dev/null | awk 'NR==2{print $4}')"
    printf '\n== toolchains ==\n'
    # Paths, not sizes: `du` on these walks tens of GB (a system-image tree
    # alone took this command from instant to seven seconds), and the size of
    # a toolchain is a question for `du` on the day you ask it, not something
    # to pay for on every status.
    local t d
    for t in $SDK_TOOLCHAINS; do
        d="$(sdk_dir "$t")"
        if [ "$t" = android ]; then
            # Android is the one that also lives in the image: the bootstrap
            # tools ship there, the packages are what moved out.
            # Asked of the STORE and not only of PATH: the tools can be
            # installed and unreachable, since a link left pointing at the
            # flat store the scope was moved out of takes the PATH entry with
            # it (B105), while "no cmdline-tools" beside a store that has them
            # sends somebody to install what is already there.
            printf '  %-11s %s\n' android "$(
                if command -v sdkmanager >/dev/null 2>&1; then
                    printf 'sdkmanager ready; packages in %s' "$d"
                elif [ -x "$d/cmdline-tools/latest/bin/sdkmanager" ]; then
                    printf 'cmdline-tools are in the store but not on PATH; packages in %s' "$d"
                else
                    echo 'no cmdline-tools'
                fi)"
            continue
        fi
        if d="$(sdk_find "$t")"; then
            printf '  %-11s %s%s%s\n' "$t" "$d" \
                "$([ "${d#"$root"}" = "$d" ] && printf ' (home volume, not the share)')" \
                "$(sdk_verified_said "$d")"
        else
            printf '  %-11s not installed (bb toolchains install %s)\n' "$t" "$t"
        fi
    done
    # ...and every other toolchain of the catalog this store holds, with the
    # program it is used through. The list above is the build toolchains
    # by name; ffmpeg, the document readers or pytorch installed from the
    # Library were on PATH and in the store and missing from here,
    # so a session asking what this machine has was told they were not
    # (B435, a session that went looking for PyTorch).
    local meta; meta="$(sdk_meta_file)"
    if [ -f "$meta" ]; then
        SDK_ROOT_NOW="$root" SDK_LISTED="$SDK_TOOLCHAINS android-tools" python3 - "$meta" "$BB_LIB" <<'PY' 2>/dev/null || true
import os, sys
sys.path.insert(0, sys.argv[2])
import sdkmeta
root, listed = os.environ["SDK_ROOT_NOW"], set(os.environ["SDK_LISTED"].split())
for t in sdkmeta.catalog_at(sys.argv[1]):
    name = t.get("name", "")
    if not name or ":" in name or name in listed:
        continue
    d = os.path.join(root, name)
    if not os.path.isdir(d):
        continue
    tool = (t.get("layout") or {}).get("tool") or ""
    run = os.path.basename(tool) if tool else ""
    print(f"  {name:<11} {d}" + (f"  (run as {run})" if run else ""))
PY
    fi
    printf '\n== android packages ==\n'
    if command -v sdkmanager >/dev/null 2>&1; then
        sdkmgr --list_installed 2>/dev/null | sed -n '/^  /p' | head -20 \
            || printf '  (sdkmanager could not list them)\n'
    else
        printf '  cmdline-tools are missing from this image\n'
    fi
    sdk_builds_with "$(sdk_dir android)"
}

# Where the NVIDIA driver stands on this machine, in a line, or nothing
# with no NVIDIA card (R102). The machine's and not the store's, so read
# here from sysfs and modinfo: which driver has the card, the version
# loaded, the version installed for this kernel. BB_SYS_ROOT is the tests'.
sdk_nvidia_line() {
    local sys="${BB_SYS_ROOT:-/sys}" dev bound="" card="" loaded="" inst="" m
    for dev in "$sys"/bus/pci/devices/*; do
        [ "$(cat "$dev/vendor" 2>/dev/null)" = 0x10de ] || continue
        case "$(cat "$dev/class" 2>/dev/null)" in 0x03*) ;; *) continue ;; esac
        card=1
        [ -L "$dev/driver" ] && bound="$(basename "$(readlink "$dev/driver")")"
        break
    done
    [ -n "$card" ] || return 0
    loaded="$(cat "$sys/module/nvidia/version" 2>/dev/null)"
    for m in modinfo /sbin/modinfo /usr/sbin/modinfo; do
        command -v "$m" >/dev/null 2>&1 || continue
        inst="$("$m" -F version nvidia 2>/dev/null | head -1)"
        break
    done
    if [ "$bound" = nvidia ] || [ -n "$loaded" ]; then
        if [ -z "$inst" ]; then echo "removed; it keeps the card until the machine restarts"
        elif [ -n "$loaded" ] && [ "$inst" != "$loaded" ]; then echo "$loaded running the card; $inst takes over when the machine restarts"
        else echo "$inst, running the card: nvidia-smi says how much of its memory is free"
        fi
    elif [ -n "$inst" ]; then echo "$inst installed; it takes the card when the machine restarts"
    else echo "not installed: nouveau has the card; the operator installs the driver from the Library"
    fi
}

# Whether a container on this machine can be given the card, for `bb
# toolchains` beside the driver's line: the NVIDIA container toolkit by its
# own tool, which is on the machine and not the store. Nothing with no
# card. BB_SYS_ROOT is the tests'.
sdk_nvidia_container_line() {
    local sys="${BB_SYS_ROOT:-/sys}" dev card="" v
    for dev in "$sys"/bus/pci/devices/*; do
        [ "$(cat "$dev/vendor" 2>/dev/null)" = 0x10de ] || continue
        case "$(cat "$dev/class" 2>/dev/null)" in 0x03*) card=1; break ;; esac
    done
    [ -n "$card" ] || return 0
    if command -v nvidia-ctk >/dev/null 2>&1; then
        v="$(nvidia-ctk --version 2>/dev/null | sed -n 's/.*version \([^ ]*\).*/\1/p' | head -1)"
        echo "toolkit ${v:-installed}: a compose file reserves the card with deploy.resources.reservations.devices (driver: nvidia)"
    else
        echo "no container toolkit: a container here cannot reserve the card; the operator installs it from the Library"
    fi
}

# The names in a directory, one per line, or nothing: what the listings
# below read, without ls's word-splitting.
sdk_names_in() {
    [ -d "$1" ] || return 0
    find "$1" -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null
}

# What a build here can use, said as a build reads it (R100): the newest
# platform is the compileSdk ceiling, and a library that wants a newer one
# fails checkDebugAarMetadata before anything compiles; and what the Gradle
# cache already holds, since a build offline or in a hurry uses that. A
# session dug through platforms/ and ~/.gradle by hand for these, asked
# dl.google.com for versions, and hit the ceiling anyway (Shebang-DevBoard,
# 30 Sep). Read from the directories, never from sdkmanager or Gradle: a
# status is instant.
sdk_builds_with() {
    local sdk="$1" plats tools newest
    plats="$(sdk_names_in "$sdk/platforms" | sed -n 's/^android-//p' | sort -n | tr '\n' ' ')"
    plats="${plats% }"
    tools="$(sdk_names_in "$sdk/build-tools" | sort -V | tr '\n' ' ')"
    printf '\n== builds with ==\n'
    if [ -n "$plats" ]; then
        newest="${plats##* }"
        printf '  %-14s %s\n' platforms "$plats"
        printf '  %-14s %s\n' compileSdk "up to ${newest}: a library that wants a newer platform fails checkDebugAarMetadata; the operator adds one from the Library"
    else
        printf '  %-14s %s\n' platforms "none: nothing compiles here until the operator adds one from the Library"
    fi
    [ -n "$tools" ] && printf '  %-14s %s\n' build-tools "${tools% }"
    local nv; nv="$(sdk_nvidia_line)"
    [ -z "$nv" ] || printf '  %-14s %s\n' "nvidia driver" "$nv"
    nv="$(sdk_nvidia_container_line)"
    [ -z "$nv" ] || printf '  %-14s %s\n' "  containers" "$nv"
    local gh="${GRADLE_USER_HOME:-$HOME/.gradle}" m dists k v
    m="$gh/caches/modules-2/files-2.1"
    printf '  %-14s %s\n' "gradle cache" "$gh"
    dists="$(sdk_names_in "$gh/wrapper/dists" | sed -n 's/^gradle-\(.*\)-\(bin\|all\)$/\1/p' | sort -V | tr '\n' ' ')"
    [ -n "$dists" ] && printf '  %-14s %s\n' "  gradle" "${dists% } (wrapper distributions, no download)"
    if [ -d "$m" ]; then
        for k in "AGP:com.android.tools.build/gradle" "kotlin:org.jetbrains.kotlin/kotlin-gradle-plugin" \
                 "compose BOM:androidx.compose/compose-bom"; do
            v="$(sdk_names_in "$m/${k#*:}" | sort -V | tr '\n' ' ')"
            [ -n "$v" ] && printf '  %-14s %s\n' "  ${k%%:*}" "${v% }"
        done
    else
        printf '  %-14s %s\n' "  modules" "none cached yet: the first build fetches them"
    fi
    return 0
}

# sdk_fetch URL DEST: download with a progress line, into a temp file first.
# A download that stops receiving (under 1 kB/s for two minutes) fails
# rather than holding the job until its step's hour is up, and a server
# that never answers fails in thirty seconds; two retries for a blip.
sdk_fetch() {
    curl -fL --progress-bar --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
        --retry 2 --retry-delay 5 -o "$2" "$1"
}

# sdkmanager --list is a network round trip wrapped in a JVM start, and a full
# check asks it once per android:* toolchain, six of them in the dashboard's
# catalog, which was six identical two-second waits.
#
# Cached in a file rather than a variable because every caller reads it inside
# $(...), where an assignment dies with the subshell; and shared between
# processes rather than kept per-run because the dashboard checks by running
# `bb toolchains check <name>` once per toolchain, so a per-process memo would still
# have asked six times. Two minutes is long enough for one sweep to ask once
# and short enough that pressing "check for updates" again means what it says.
SDK_LIST_CACHE_TTL=120
sdk_android_list() {
    local f="${TMPDIR:-/tmp}/bb-sdk-list.cache" age
    if [ -s "$f" ]; then
        age=$(( $(date +%s) - $(stat -c %Y "$f" 2>/dev/null || echo 0) ))
        if [ "$age" -lt "$SDK_LIST_CACHE_TTL" ]; then cat "$f"; return 0; fi
    fi
    # Written aside and moved into place, so a reader never sees half a table,
    # and nothing is printed at all when sdkmanager cannot answer: a stale
    # snapshot would be a wrong answer to the one question this is asked for.
    # timeout cannot run a shell function, so this one names the binary
    # and takes the root from the same place sdkmgr does.
    if timeout 120 sdkmanager "$(sdk_root_flag)" --list 2>/dev/null > "$f.$$"; then
        mv -f "$f.$$" "$f"; cat "$f"
    else
        rm -f "$f.$$"
    fi
}
# After anything that changes what is installed: the table is a statement
# about both halves, and the installed half just moved.
sdk_android_list_forget() { rm -f "${TMPDIR:-/tmp}/bb-sdk-list.cache"; }

# The newest package sdkmanager offers for a bare name, as `id<TAB>version`.
# ndk and cmake ship as versioned ids (ndk;30.0.15729638) and a bare name
# installs nothing, so both the installer and the version check have to
# resolve one, from what the repository offers rather than from a table here
# that would go stale within a release. One function, so the version a row
# promises is by construction the one an install lands.
#
# Release candidates are skipped when anything stable is on offer: the NDK
# publishes them into the same channel, marked only in the version column
# ("30.0.15729638 rc2"), so sorting on the id alone would have installed one
# without ever saying so.
sdk_android_newest() {
    local pkg="$1" all stable
    # A platform is named by its level, and the newest level's base is what
    # a compileSdk names: platforms;android-37.0 for compileSdk 37 (Google
    # spells a level with its minor since 37). Its later minors (37.1, a
    # quarterly release) and the extension levels (36-ext19) are left to
    # be asked for by id, so "the newest platform" is one a build can use.
    all="$(sdk_android_list | sed -n '/Available Packages/,$p' \
           | awk -F'|' -v p="$pkg" '
               { id=$1; v=$2; gsub(/^ +| +$/,"",id); gsub(/^ +| +$/,"",v) }
               p == "platforms;android" && id ~ /^platforms;android-[0-9]+(\.0)?$/ { print id "\t" v; next }
               p != "platforms;android" && id ~ ("^" p "(;[0-9][^;]*)?$") { print id "\t" v }' | sort -V)"
    stable="$(printf '%s\n' "$all" | grep -viE '(rc|beta|alpha|preview)[0-9]*$' || true)"
    if [ -n "$stable" ]; then all="$stable"; fi
    printf '%s\n' "$all" | tail -1
}

# bb toolchains check [NAME...]: what is installed, and whether it is current.
#
# One TSV line per toolchain: name, installed, latest, status. Every probe is
# bounded by a timeout (most of them reach the network, and a package list
# that hangs would take the dashboard's job with it), and a probe that cannot
# answer says "unknown" rather than guessing "current", because a wrong
# "current" is the one answer nobody would check.
#
# Upstream is asked for absent toolchains too. "What would this install" and
# "what is upstream" are the same question, and the row that has never been
# installed is exactly where somebody wants the answer before spending the
# gigabytes; those come back as `-  <version>  absent`.
sdk_check_one() {
    local what="$1" local_only="${2:-}" d inst="-" latest="-" status=unknown
    # local_only: answer "what is installed" without asking anybody. That
    # half is a directory read or a --version away, and it is what the
    # toolchain list wants on every draw; the other half is a round trip to a
    # different service per toolchain and belongs behind a button.
    case "$what" in
        flutter)
            d="$(sdk_find flutter)" || d=""
            # A git clone on the stable branch: the honest question is whether
            # our HEAD is the branch head, and ls-remote answers it without
            # fetching an object. Against the clone's origin when there is a
            # clone and against the upstream URL when there is not: the same
            # answer either way, and the second form is what lets a row that
            # has never been installed say what it would get.
            [ -z "$d" ] || inst="$(git -C "$d" rev-parse --short=8 HEAD 2>/dev/null || echo -)"
            if [ -z "$local_only" ]; then
                if [ -n "$d" ]; then
                    latest="$(timeout 30 git -C "$d" ls-remote origin refs/heads/stable 2>/dev/null | cut -c1-8)"
                else
                    latest="$(timeout 30 git ls-remote https://github.com/flutter/flutter.git refs/heads/stable 2>/dev/null | cut -c1-8)"
                fi
            fi
            [ -n "$latest" ] || latest="-"
            ;;
        swift)
            d="$(sdk_find swift)" || d=""
            [ -z "$d" ] || inst="$("$d/usr/bin/swift" --version 2>/dev/null | sed -n 's/.*Swift version \([0-9.]*\).*/\1/p' | head -1)"
            if [ -z "$local_only" ]; then
                latest="$(timeout 30 curl -fsSLI -o /dev/null -w '%{url_effective}' \
                          https://github.com/swiftlang/swift/releases/latest 2>/dev/null)"
                latest="${latest##*/swift-}"; latest="${latest%-RELEASE}"
            fi
            case "$latest" in ''|*[!0-9.]*) latest="-" ;; esac
            ;;
        dotnet)
            d="$(sdk_find dotnet)" || d=""
            [ -z "$d" ] || inst="$("$d/dotnet" --list-sdks 2>/dev/null | tail -1 | awk '{print $1}')"
            # The installer itself knows what the channel currently holds, so
            # ask it rather than parsing a release feed that changes shape.
            # The dry-run echoes the exact invocation it would make, version
            # and all (a more stable thing to read than the payload URL), and
            # it needs nothing installed to say so.
            [ -n "$local_only" ] || latest="$(timeout 60 bash -c 'curl -fsSL https://dot.net/v1/dotnet-install.sh \
                      | bash -s -- --channel LTS --dry-run' 2>/dev/null \
                      | sed -n 's/.*--version "\([^"]*\)".*/\1/p' | head -1)"
            [ -n "$latest" ] || latest="-"
            ;;
        go)
            d="$(sdk_find go)" || d=""
            [ -z "$d" ] || inst="$("$d/bin/go" version 2>/dev/null | awk '{print $3}')"
            [ -n "$local_only" ] || latest="$(timeout 30 curl -fsS 'https://go.dev/VERSION?m=text' 2>/dev/null | head -1)"
            [ -n "$latest" ] || latest="-"
            ;;
        jdk)
            # java -version prints to STDERR, which is why the redirect is a
            # merge rather than a discard; read the other way this reported
            # every installed JDK as absent.
            d="$(sdk_find jdk)" || d=""
            [ -z "$d" ] || inst="$("$d/bin/java" -version 2>&1 | sed -n 's/.*version "\([^"]*\)".*/\1/p' | head -1)"
            [ -n "$local_only" ] || latest="$(timeout 30 curl -fsS \
                'https://api.adoptium.net/v3/info/release_names?release_type=ga&version=%5B21%2C22%29&page_size=1&sort_order=DESC' \
                2>/dev/null | python3 -c 'import json,sys
print((json.load(sys.stdin).get("releases") or [""])[0].removeprefix("jdk-"))' 2>/dev/null)"
            [ -n "$latest" ] || latest="-"
            ;;
        android-tools)
            # sdkmanager --version needs a JDK, so this reads the package file
            # the tools ship instead: no java, no subprocess, and an answer
            # even on a node whose JDK is not installed yet.
            # Where the SDK really keeps it first (<sdk>/cmdline-tools/latest
            # is both what the run step symlinks into and what a hand install
            # produces), then the unpack directory, which is where it sits
            # before that symlink exists. Reading only the second reported no
            # version at all for a node whose tools were put in by hand, while
            # the census beside it said android-sdk was present.
            local props=""
            for props in "$(sdk_dir android)/cmdline-tools/latest/source.properties" \
                         "$(sdk_dir android-tools)/cmdline-tools/source.properties"; do
                [ -f "$props" ] && break
                props=""
            done
            [ -z "$props" ] || inst="$(sed -n 's/^Pkg.Revision=//p' "$props" 2>/dev/null | head -1)"
            ;;
        node)
            d="$(sdk_find node)" || d=""
            [ -z "$d" ] || inst="$("$d/bin/node" --version 2>/dev/null | head -1)"
            [ -n "$local_only" ] || latest="$(timeout 30 curl -fsS https://nodejs.org/dist/index.json 2>/dev/null \
                      | python3 -c 'import json,sys
print(next((r["version"] for r in json.load(sys.stdin) if r.get("lts")), ""))' 2>/dev/null)"
            [ -n "$latest" ] || latest="-"
            ;;
        zig)
            d="$(sdk_find zig)" || d=""
            [ -z "$d" ] || inst="$("$d/zig" version 2>/dev/null | head -1)"
            [ -n "$local_only" ] || latest="$(timeout 30 curl -fsS https://ziglang.org/download/index.json 2>/dev/null \
                      | python3 -c 'import json,sys
d = json.load(sys.stdin)
print(next(k for k in d if k != "master"))' 2>/dev/null)"
            [ -n "$latest" ] || latest="-"
            ;;
        rust)
            d="$(sdk_find rust)" || d=""
            [ -z "$d" ] || inst="$(RUSTUP_HOME="$d/rustup" CARGO_HOME="$d/cargo" "$d/cargo/bin/rustc" --version 2>/dev/null | awk '{print $2}')"
            if [ -z "$local_only" ] && [ -n "$d" ]; then
                # rustup already knows how to ask; its answer names the
                # version it would move to, which is the only interesting half.
                local line=""
                line="$(RUSTUP_HOME="$d/rustup" CARGO_HOME="$d/cargo" timeout 60 \
                        "$d/cargo/bin/rustup" check 2>/dev/null | grep -i 'stable' | head -1 || true)"
                # Lower case, and a colon rather than an arrow:
                #   stable-x86_64-unknown-linux-gnu - up to date: 1.97.1 (...)
                #   stable-x86_64-unknown-linux-gnu - update available: 1.97.1 -> 1.98.0
                case "$line" in
                    *"up to date"*)      latest="$inst" ;;
                    *"update available"*)
                        latest="$(printf '%s' "$line" | sed -n 's/.*-> *\([0-9][0-9.]*\).*/\1/p')"
                        [ -n "$latest" ] || latest="newer" ;;
                    *) latest="-" ;;
                esac
            elif [ -z "$local_only" ]; then
                # No rustup here to ask, so ask GitHub: the release tags are
                # the same numbers rustc reports.
                latest="$(timeout 30 curl -fsSLI -o /dev/null -w '%{url_effective}' \
                          https://github.com/rust-lang/rust/releases/latest 2>/dev/null)"
                latest="${latest##*/}"
                case "$latest" in ''|*[!0-9.]*) latest="-" ;; esac
            fi
            ;;
        playwright)
            d="$(sdk_find playwright)" || d=""
            # The module decides which browser revisions it wants; --dry-run
            # names the directories it would use, and names them whether or
            # not any of them exist. So one probe answers both shapes of the
            # question: for an installed set, every directory present means
            # current; for an absent one, the chromium revision it names is
            # what an install would land.
            local want missing=0 rev="" base
            [ -z "$d" ] || inst="$(basename "$(find "$d" -maxdepth 1 -name 'chromium-*' | head -1)" 2>/dev/null)"
            if [ -z "$local_only" ]; then
                for want in $(PLAYWRIGHT_BROWSERS_PATH="${d:-$(sdk_dir playwright)}" timeout 60 \
                              playwright install --dry-run chromium firefox webkit 2>/dev/null \
                              | sed -n 's/.*Install location: *//p'); do
                    base="$(basename "$want")"
                    case "$base" in chromium-*) rev="$base" ;; esac
                    [ -d "$want" ] || missing=1
                done
                if [ -z "$d" ]; then latest="${rev:--}"
                elif [ "$missing" = 1 ]; then latest="newer revisions"
                else latest="$inst"
                fi
            fi
            ;;
        android:*)
            local pkg="${what#android:}"
            # A versioned row (the NDK, CMake, build-tools, the SDK platform)
            # is a family of packages side by side, and a newer one is a new
            # package rather than an update to the one installed: so the
            # question is whether the newest the repository offers is on
            # the store, not whether sdkmanager lists a revision update
            # (which never showed platform 37 to a store holding 36).
            local vpkg; vpkg="$(sdk_meta field "$what" source.package 2>/dev/null)"
            if [ -n "$(sdk_meta field "$what" source.versioned 2>/dev/null)" ] && [ -n "$vpkg" ]; then
                local fam="${ANDROID_HOME:-/opt/android-sdk}/${vpkg%%;*}" newest nid
                inst="$(find "$fam/" -mindepth 1 -maxdepth 1 -type d ! -name '.*' -printf '%f\n' 2>/dev/null | sort -V | tail -1)"
                [ -n "$inst" ] || inst="-"
                if [ -z "$local_only" ]; then
                    newest="$(sdk_android_newest "$vpkg")"; nid="${newest%%	*}"
                    if [ -n "$nid" ]; then
                        latest="${nid#*;}"
                        if [ "$inst" = "-" ]; then status=absent
                        elif [ -d "$fam/${nid#*;}" ]; then status=current
                        else status=update; fi
                    fi
                fi
            else
            # Non-empty, not merely present: every one of these is a
            # symlink onto the store, and the store has a directory per
            # package kind whether or not anything was installed into it.
            # `-d` alone called an empty ndk directory "installed and
            # current", which is exactly the reassuring answer nobody
            # re-checks.
            d="${ANDROID_HOME:-/opt/android-sdk}/$pkg"
            if [ -d "$d" ] && [ -n "$(ls -A "$d" 2>/dev/null)" ]; then
                # Trimmed, not stripped of spaces: the version column
                # is where a release candidate says so ("30.0.15729638
                # rc2"), and squeezing it out hid that.
                inst="$(timeout 120 sdkmanager "$(sdk_root_flag)" --list_installed 2>/dev/null \
                        | awk -F'|' -v p="$pkg" '$1 ~ "^ *"p"(;|  *$)" {v=$2; gsub(/^ +| +$/,"",v); print v; exit}')"
                [ -n "$inst" ] || inst="installed"
            fi
            if [ -z "$local_only" ] && [ "$inst" != "-" ]; then
                # sdkmanager prints an Available Updates table, and prints
                # nothing under it when there is nothing to do.
                if sdk_android_list | sed -n '/Available Updates/,$p' \
                   | grep -qE "^ *${pkg}(;|  *\|)"; then
                    latest="newer"; status=update
                else
                    latest="$inst"
                fi
            elif [ -z "$local_only" ]; then
                # Absent: whatever an install would resolve to, asked the
                # same way the installer asks.
                latest="$(sdk_android_newest "$pkg" | cut -f2)"
                [ -n "$latest" ] || latest="-"
            fi
            fi
            ;;
        *) printf '%s\t-\t-\tunknown\n' "$what"; return 0 ;;
    esac
    [ -n "$inst" ] || inst="-"
    # A local probe knows what is installed and nothing about what exists
    # elsewhere, so it must not answer the other question. "current" from a
    # directory listing would be a claim nobody checked.
    if [ -n "$local_only" ]; then
        if [ "$inst" = "-" ]; then
            printf '%s\t-\t-\tabsent\n' "$what"
        else
            printf '%s\t%s\t-\tlocal\n' "$what" "$inst"
        fi
        return 0
    fi
    if [ "$status" = unknown ]; then
        if [ "$inst" = "-" ]; then status=absent
        elif [ "$latest" = "-" ]; then status=unknown
        # The same release written with and without its build (Temurin's
        # 21.0.12.1+1 against java's own 21.0.12.1) is the same release, and
        # so is one written with and without its trailing zero (Swift 6.4
        # as the compiler prints it against swift-6.4.0-RELEASE, the tag the
        # resolver reads: the row offered that update forever, B715).
        elif [ "$(sdk_vnorm "${inst%%+*}")" = "$(sdk_vnorm "${latest%%+*}")" ]; then status=current
        else status=update
        fi
    fi
    # A fifth column: what the download weighs. Most recipes answer from their
    # own URL or a dry run; the android ones answer from sdkmanager's
    # repository index, which is keyed by package id, so the id is resolved
    # here, by the same code that would install it, rather than guessed at
    # from the index's newest entry.
    local dlid=""
    [ "$(sdk_meta field "$what" source.kind)" != sdkmanager ] || dlid="$(sdk_android_id "$what" 2>/dev/null)"
    printf '%s\t%s\t%s\t%s\t%s\n' "$what" "$inst" "$latest" "$status" \
        "$(sdk_meta size "$what" "$dlid" 2>/dev/null)"
}

# bb toolchains versions: installed versions only, nothing asked of the network.
sdk_versions() {
    local names="$*"
    [ -n "$names" ] || names="$(sdk_checkable)"
    local n
    for n in $names; do sdk_check_one "$n" local; done
}

# A version with its trailing zero components off (6.4.0 and 6.4 are one
# release), for the one comparison the check makes.
sdk_vnorm() {
    local v="$1"
    while [ "${v%.0}" != "$v" ]; do v="${v%.0}"; done
    printf '%s' "$v"
}

sdk_check() {
    local names="$*"
    [ -n "$names" ] || names="$(sdk_checkable)"
    local n
    # Each recipe's answer is its own: one whose probe fails under set -e
    # (rust's grep finding no "stable" line in rustup's answer) ended the
    # run there, so every row after it went unasked and the node's check
    # job failed, exit 1 or git's 128, and was queued again (B549). In an
    # || its probe runs to its row whatever one command in it says.
    for n in $names; do sdk_check_one "$n" || true; done
}

# bb toolchains update NAME: bring an installed toolchain up to date, each the way
# its own tooling expects rather than by deleting and starting again.
sdk_update() {
    sdk_operator_only update "$@"
    local what="${1:-}" d
    case "$what" in
        flutter)
            d="$(sdk_find flutter)" || die "flutter is not installed"
            # Half of a clone an install cut short (no .git, or no
            # bin/flutter) has nothing to fetch into: git stopped at the
            # share's edge with "not a git repository". Installed again
            # instead, as an install clears the same half.
            if [ ! -e "$d/.git" ] || [ ! -x "$d/bin/flutter" ]; then
                warn "flutter at ${d} is not a whole checkout: an earlier install did not finish; installing it again"
                rm -rf "${d:?}"
                sdk_install flutter
                return
            fi
            log "updating flutter to the head of stable"
            # The clone is shallow, so fetch the branch tip and move onto it;
            # `flutter upgrade` refuses to work in a shallow checkout.
            git -C "$d" fetch --depth 1 origin stable
            git -C "$d" reset --hard FETCH_HEAD
            "$d/bin/flutter" --version
            ;;
        dotnet)
            d="$(sdk_find dotnet)" || die "dotnet is not installed"
            log "installing the current LTS .NET SDK alongside what is there"
            sdk_fetch https://dot.net/v1/dotnet-install.sh /tmp/dotnet-install.sh
            bash /tmp/dotnet-install.sh --channel LTS --install-dir "$d" --no-path
            rm -f /tmp/dotnet-install.sh
            ;;
        swift|playwright)
            # Both are "unpack the current thing": swift is a tarball with the
            # version in its path, and playwright fetches whatever revisions
            # the module now wants, leaving the old ones alone.
            [ "$what" = swift ] && sdk_remove swift
            sdk_install "$what"
            ;;
        android:*)
            command -v sdkmanager >/dev/null 2>&1 || die "no sdkmanager here: every android:*
   toolchain installs through it, and it comes from android-tools. On a node, install
   Android command-line tools from the Library with that node picked; an android:*
   toolchain should bring it along, and if it did not then this store has a
   cmdline-tools directory with nothing in it, which is not the same thing."
            # A versioned row updates by installing the newest beside what is
            # there: a project pinned to the older one keeps building.
            if [ -n "$(sdk_meta field "$what" source.versioned 2>/dev/null)" ]; then
                sdk_install_android "$what"
                sdk_relink_android
                return 0
            fi
            log "updating ${what#android:}"
            sdkmgr --update
            ;;
        *) die "usage: bb toolchains update playwright|flutter|dotnet|swift|android:<package>" ;;
    esac
}

# Installing an SDK is the operator's call, not a session's.
#
# CLAUDECODE is in the environment of anything a Claude session runs, and
# BB_AGENT in anything any coding agent's session runs (bb-tty's launcher,
# R95), and both are absent from the dashboard's, which is the whole
# distinction: these are
# gigabytes on somebody else's disk, and the decision belongs to the person
# who pays for it. The CLAUDE.md template has always said "offer the command,
# do not run it". This is that rule with teeth.
#
# It is a guardrail, not a boundary: a session has a shell and could call
# sdkmanager directly. The point is to make the right thing easy and the
# wrong thing deliberate, and the message says exactly how to override it for
# the human who is holding the keyboard.
sdk_operator_only() {
    [ -n "${CLAUDECODE:-}${BB_AGENT:-}" ] || return 0
    die "installing SDKs is the operator's decision, and this is an agent's session.
Ask them to do it from the dashboard's Library, or to
run: bb toolchains $*
If you ARE the operator at this keyboard: env -u CLAUDECODE -u BB_AGENT bb toolchains $*"
}

# Put back any package directory sdkmanager turned into a real directory.
#
# It does not write through a symlink for every package: installing the
# emulator replaced ANDROID_HOME/emulator (a link onto the share) with a
# real directory, which put 821MB back inside the image layer where the next
# image update would throw it away and re-download it. Nothing warns about
# this; the directory simply stops being a link. Checked after every install,
# which is the only moment it can happen.

# sdkmanager records an operation in progress in <package>/.installer/, in a
# file naming a working directory under $ANDROID_HOME/.temp. That record
# outlives the operation: a container restart, or a package moved onto the
# share by relink, leaves it pointing at a directory that is gone, and every
# later install or uninstall of that package then fails with `"Uninstall
# Android Emulator v.37.1.11" failed` and exit 1 and nothing else. It cost an
# afternoon to find, because the failure names neither the file nor the path.
#
# Cleared only when what it names is really missing. A record pointing at a
# directory that exists means something genuinely is mid-flight, and that is
# the one case where sdkmanager is right to refuse.
sdk_android_pkg_dir() {
    printf '%s/%s' "${ANDROID_HOME:-/opt/android-sdk}" "$(printf '%s' "$1" | tr ';' '/')"
}
sdk_android_clear_stale_installer() {
    local dir data path
    dir="$(sdk_android_pkg_dir "$1")"
    data="$dir/.installer/.installData"
    [ -f "$data" ] || return 0
    path="$(sed -n 's/^path=//p' "$data" | head -1)"
    if [ -n "$path" ] && [ -e "$path" ]; then return 0; fi
    log "clearing stale installer state in ${dir}: it points at ${path:-nothing}, which is gone"
    rm -rf "${dir:?}/.installer"
}

sdk_relink_android() {
    local store sub src
    store="$(sdk_dir android)"
    # On a node the store IS the SDK home: ANDROID_HOME points at the store's
    # android/ directory and sdkmanager writes there directly, so there is no
    # image-side directory to point back at the share, and the moves below
    # would be a directory onto itself.
    [ "$(readlink -f "$store")" != "$(readlink -f "${ANDROID_HOME:-/opt/android-sdk}")" ] || return 0
    for sub in system-images platforms build-tools emulator ndk cmake \
               extras add-ons sources skins; do
        src="${ANDROID_HOME:-/opt/android-sdk}/$sub"
        if [ -L "$src" ]; then continue; fi           # already onto the store
        mkdir -p "$store"
        if [ -d "$src" ]; then
            log "relinking ${sub} onto the toolchain store: sdkmanager replaced the link"
            if [ -d "$store/$sub" ] && [ -z "$(ls -A "$store/$sub" 2>/dev/null)" ]; then
                rmdir "$store/$sub"
            fi
            if [ -e "$store/$sub" ]; then
                cp -a "$src/." "$store/$sub/" && rm -rf "$src"
            else
                mv "$src" "$store/$sub"
            fi
        elif [ ! -e "$src" ]; then
            # Gone entirely, which is what an uninstall leaves behind: the
            # package directory here IS the link, so sdkmanager deletes it.
            # Left missing, the next install would create a real directory in
            # its place and put gigabytes inside the image instead of on the
            # share, quietly, and only noticed at the next image update.
            log "restoring the ${sub} link: an uninstall removed it"
            mkdir -p "$store/$sub"
        else
            continue                                  # a file, not a package
        fi
        ln -sfn "$store/$sub" "$src"
    done
}

# What this run created, so that a failure can undo it.
#
# Every probe here calls a non-empty directory installed, which is precisely
# what a download interrupted half way leaves behind: the tab says installed,
# `bb toolchains check` agrees, and the first thing to actually use it fails in some
# stranger way. Only ever set to a directory this run made: an install onto
# an existing one is a repair, and deleting what was already working because
# the repair failed would be worse than the failure.
SDK_PARTIAL=""
sdk_mark_partial() {
    local d="$1"
    if [ -L "$d" ]; then d="$(readlink -f "$d")"; fi
    if [ ! -d "$d" ] || [ -z "$(ls -A "$d" 2>/dev/null)" ]; then
        SDK_PARTIAL="$d"
        # ...and a marker beside it until the install has finished, which no
        # kill can leave unsaid: an Abort that cut the cleanup short left half
        # of flutter on the share, and a directory read as installed (the
        # operator, 12 Oct). The agent does not list a directory with its
        # marker, and the next install clears what the marker names.
        mkdir -p "$(dirname "$d")" && : > "$(sdk_partial_marker "$d")"
    fi
}
sdk_partial_marker() { printf '%s/.bb-installing.%s' "$(dirname "$1")" "$(basename "$1")"; }
# What an interrupted install left: its directory and its marker, cleared
# before this one begins, so a half toolchain is never mistaken for a whole one.
sdk_clear_interrupted() {
    local d="$1" m
    m="$(sdk_partial_marker "$d")"
    [ -e "$m" ] || return 0
    warn "an earlier install of $(basename "$d") did not finish; clearing what it left in ${d}"
    rm -rf "${d:?}"
    rm -f "$m"
}
# ...and a directory without the tool its layout runs, which an install cut
# short before the marker existed left behind: half of flutter with no
# bin/flutter, listed as installed until the census asked for the tool, and
# then refused by a fresh-only install as "already installed" (diagnostics
# #124). Nothing in it can run, so nothing in it is kept.
sdk_clear_toolless() {
    local what="$1" d="$2" tool
    [ -d "$d" ] && [ -n "$(ls -A "$d" 2>/dev/null)" ] || return 0
    # A layout that names `needs` is filled in by its recipe (playwright's
    # module beside the browsers it keeps), so it is not this one's to clear.
    [ -z "$(sdk_meta field "$what" layout.needs 2>/dev/null)" ] || return 0
    tool="$(sdk_meta field "$what" layout.tool 2>/dev/null)" || tool=""
    case "$tool" in ""|root:*) return 0 ;; esac
    [ ! -e "$d/$tool" ] || return 0
    warn "${what} at ${d} has no ${tool}: an earlier install did not finish; clearing what it left"
    rm -rf "${d:?}"
}
# Interrupted rather than failed: the dashboard's Abort sends the whole
# process group a TERM, so the download dies with it. Handled explicitly
# because bash runs its EXIT trap on a signal with $? still zero: the
# cleanup would look at that and conclude nothing had gone wrong, leaving a
# half-unpacked toolchain behind.
sdk_install_aborted() {
    trap - EXIT
    if [ -n "${SDK_PARTIAL:-}" ]; then
        warn "aborted; removing the partial ${SDK_PARTIAL}"
        rm -rf "${SDK_PARTIAL:?}" && rm -f "$(sdk_partial_marker "$SDK_PARTIAL")"
        SDK_PARTIAL=""
    else
        warn "aborted"
    fi
    exit 143
}

sdk_install_cleanup() {
    local rc=$?
    if [ "$rc" = 0 ] || [ -z "${SDK_PARTIAL:-}" ]; then return 0; fi
    warn "install failed (exit ${rc}); removing the partial ${SDK_PARTIAL}"
    rm -rf "${SDK_PARTIAL:?}" && rm -f "$(sdk_partial_marker "$SDK_PARTIAL")"
    SDK_PARTIAL=""
    # Android packages leave a record of the operation behind as well, and a
    # stale one blocks every later install and uninstall of that package.
    sdk_relink_android >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# Installing, from the catalog.
#
# Every URL, branch, flag, archive layout and environment variable lives in
# config/toolchains.json; what is left here is the five shapes those values are
# poured into. A toolchain that fits one of them is a data edit and nothing else.
#
# The shapes stay code because they are genuinely different jobs: a shallow
# clone the tool then updates in place, a tarball with a version in its top
# directory, a vendor installer that wants its own arguments, a tool already in
# the image pointed at a new directory, and sdkmanager, which resolves its own
# package ids. A table that could express all five would be a language.
SDK_META="$(dirname "$(readlink -f "$0")")/lib/sdkmeta.py"
sdk_meta() { python3 "$SDK_META" "$@"; }

# Read a NUL-separated list from the catalog into an array named by $1.
sdk_meta_into() {
    local -n _out="$1"; shift
    _out=()
    while IFS= read -r -d '' item; do _out+=("$item"); done < <(sdk_meta "$@")
}

# `bb toolchains plan NAME`: what an install would do, without doing any of it.
#
# The recipes are data, and data can be wrong in ways that only show up three
# gigabytes into a download. This asks every upstream what it currently offers
# and prints the commands, so a catalog edit can be checked before it is
# trusted.
sdk_plan() {
    local what="${1:-}" d kind url version rest
    [ -n "$what" ] || die "usage: bb toolchains plan <toolchain>"
    kind="$(sdk_meta field "$what" source.kind 2>/dev/null)" || kind=""
    [ -n "$kind" ] || { sdk_image_flavor "$what" >/dev/null && kind=sdkmanager; }
    [ -n "$kind" ] || case "$what" in android:*\;*) kind=sdkmanager ;; esac
    [ -n "$kind" ] || die "no source in the catalog for ${what}"
    d="$(sdk_dir "${what#android:}")"
    case "$what" in android:*) d="$(sdk_dir android)" ;; esac
    printf 'toolchain %s\n' "$what"
    printf 'kind      %s\n' "$kind"
    printf 'directory %s\n' "$d"
    if [ "$kind" = sdkmanager ]; then
        local pkg; pkg="$(sdk_android_id "$what")" || pkg="(cannot resolve; is sdkmanager here?)"
        printf 'sdkmanager %s --install %s\n' "$(sdk_root_flag)" "$pkg"
        return 0
    fi
    rest="$(sdk_meta resolve "$what")"
    version="${rest%%	*}"; url="${rest#*	}"
    [ -z "$version" ] || printf 'version   %s\n' "$version"
    [ -z "$url" ] || printf 'url       %s\n' "$url"
    # The machine's packages the recipe needs, installed by the agent on a
    # node it administers and by hand anywhere else, so the plan says them.
    local -a sysapt sysdnf
    sdk_meta_into sysapt argv "$what" system.apt 2>/dev/null || sysapt=()
    [ "${#sysapt[@]}" = 0 ] || printf 'system    apt: %s\n' "${sysapt[*]}"
    sdk_meta_into sysdnf argv "$what" system.dnf 2>/dev/null || sysdnf=()
    [ "${#sysdnf[@]}" = 0 ] || printf 'system    dnf: %s\n' "${sysdnf[*]}"
    local -a cmd
    sdk_meta_into cmd argv "$what" source.run "dir=$d" "version=$version" "script=<downloaded>"
    [ "${#cmd[@]}" = 0 ] || printf 'run       %s\n' "${cmd[*]}"
    sdk_meta_into cmd argv "$what" source.verify "dir=$d" "version=$version"
    [ "${#cmd[@]}" = 0 ] || printf 'verify    %s\n' "${cmd[*]}"
}

# The android package id an install would resolve to: a bare name, a versioned
# one, or the newest image of a flavor.
# flavor -> the sdkmanager id prefix, out of the catalog's android_images
# section. Empty when the name is not one of them. One section rather than a
# catalog row per flavor, because a row can only ever name the newest level;
# every caller that wants an image id asks this, never a row.
sdk_image_flavor() {
    local want="${1#android:}" name abi rest
    case "$want" in
        # The short names the CLI has always taken, and the section's own keys.
        tv) want=android-tv ;; wear) want=android-wear ;;
        playstore) want=google_apis_playstore ;;
    esac
    while IFS=$'\t' read -r name abi rest; do
        [ "$name" = "$want" ] || continue
        printf '%s\t%s' "$name" "$abi"
        return 0
    done < <(sdk_meta flavors 2>/dev/null)
    return 1
}

sdk_android_id() {
    local pkg="${1#android:}" kind
    # A full sdkmanager id, the shape `bb emu images` prints. No catalog row
    # names one, because which images exist is not a fixed list, so the id is
    # its own answer.
    case "$1" in android:*\;*) printf '%s' "$pkg"; return 0 ;; esac
    local abi rest
    if rest="$(sdk_image_flavor "$1")"; then
        kind="${rest%%	*}"; abi="${rest#*	}"
        # The newest plain API level of that flavor. From the catalog's index
        # rather than sdkmanager's listing: same answer, no round trip through
        # a thousand rows, and the sizes come along for free.
        sdk_meta images 2>/dev/null | cut -f1 \
            | grep -E "^system-images;android-[0-9]+;${kind};${abi}$" | sort -V | tail -1
        return 0
    fi
    pkg="$(sdk_meta field "$1" source.package)"
    if [ -n "$(sdk_meta field "$1" source.versioned)" ]; then
        sdk_android_newest "$pkg" | cut -f1
    else
        printf '%s' "$pkg"
    fi
}

sdk_install_android() {
    local what="$1" pkg
    command -v sdkmanager >/dev/null 2>&1 || die "no sdkmanager here: every android:*
   toolchain installs through it, and it comes from android-tools. On a node, install
   Android command-line tools from the Library with that node picked; an android:*
   toolchain should bring it along, and if it did not then this store has a
   cmdline-tools directory with nothing in it, which is not the same thing."
    pkg="$(sdk_android_id "$what")"
    [ -n "$pkg" ] || die "could not find a ${what#android:} package to install"
    log "installing ${pkg} into $(sdk_dir android)"
    sdk_android_clear_stale_installer "$pkg"
    sdk_mark_partial "$(sdk_android_pkg_dir "$pkg")"
    sdkmgr --install "$pkg"
    sdk_android_list_forget
    sdk_relink_android
}

# sdk_verified_said DIR: how the toolchain in DIR was checked when it was
# installed (R137), as a few words after its row: "; checked: sha256 matched
# go.dev's download index", "; not checked: why", nothing for one installed
# before BuilderBot checked.
sdk_verified_said() {
    local f="$1/.bb-verified" algo rest
    [ -r "$f" ] || return 0
    IFS=$'\t' read -r algo rest < "$f" || return 0
    case "$algo" in
        none) printf '; not checked: %s' "$rest" ;;
        sha1|sha256|sha512) printf '; checked: %s matched %s' "$algo" "${rest#*$'\t'}" ;;
        gpg) printf '; checked: %s' "${rest#*$'\t'}" ;;
    esac
}

# sdk_verify_download WHAT FILE URL VERSION DIR: the download held to what
# its publisher says it is (R137), before anything unpacks or runs it: the
# catalog row's source.checksum, answered by sdkmeta.py. A mismatch removes
# the file and stops the install, naming both digests. A row whose publisher
# states nothing says so on the install, and DIR keeps how it was checked
# (.bb-verified), which the Installed page reads.
sdk_verify_download() {
    local what="$1" file="$2" url="$3" version="$4" d="$5" said algo want where got
    said="$(sdk_meta checksum "$what" "$url" "$version")" \
        || { rm -f "$file"; die "could not learn what ${what}'s download should be: ${said:-no answer}"; }
    algo="${said%%$'\t'*}"; said="${said#*$'\t'}"; want="${said%%$'\t'*}"; where="${said#*$'\t'}"
    if [ "$algo" = gpg ]; then
        # The publisher signs the download itself (Swift): its signature
        # checked with the publisher's keys shipped beside the catalog.
        local sig keyring signer
        sig="$(mktemp "${TMPDIR:-/tmp}/bb-sig.XXXXXX")"
        sdk_fetch "$want" "$sig" >/dev/null 2>&1 || { rm -f "$file" "$sig"; die "could not fetch ${what}'s signature (${want})"; }
        keyring="$(sdk_meta keyring "$where")" || { rm -f "$file" "$sig"; die "${what}: no keys to check its signature with"; }
        if ! signer="$(gpgv --keyring "$keyring" "$sig" "$file" 2>&1)"; then
            rm -f "$file" "$sig"
            die "${what}'s download does not carry its publisher's signature: $(printf '%s' "$signer" | tail -2 | tr '\n' ' ')nothing was installed"
        fi
        rm -f "$sig"
        signer="$(printf '%s' "$signer" | sed -n 's/.*Good signature from "\([^"]*\)".*/\1/p' | head -1)"
        [ -n "$signer" ] || signer="a key of its publisher"
        log "verified: signed by ${signer}"
        printf 'gpg\t\tsigned by %s\n' "$signer" > "$d/.bb-verified" 2>/dev/null || true
        return 0
    fi
    if [ "$algo" = none ]; then
        log "not verified: ${where}"
        printf 'none\t%s\n' "$where" > "$d/.bb-verified" 2>/dev/null || true
        return 0
    fi
    case "$algo" in sha1|sha256|sha512) ;; *) rm -f "$file"; die "${what}: unknown checksum kind ${algo}" ;; esac
    got="$("${algo}sum" "$file" | cut -d' ' -f1)"
    if [ "$got" != "$want" ]; then
        rm -f "$file"
        die "${what}'s download is not what ${where} says it is (${algo} ${got}, expected ${want}): nothing was installed"
    fi
    log "verified: ${algo} matches ${where}"
    printf '%s\t%s\t%s\n' "$algo" "$want" "$where" > "$d/.bb-verified" 2>/dev/null || true
}

# Fetch source.url into the directory, unpacking it there. `strip` drops the
# tarball's top directory, which is named for the release and would otherwise
# pin the version into every PATH that points at it.
sdk_install_tarball() {
    local what="$1" d rest version url strip tmp
    d="$(sdk_dir "$what")"
    sdk_mark_partial "$d"
    [ -z "$(sdk_meta field "$what" source.fresh_only)" ] || [ ! -d "$d" ] \
        || die "${what} is already installed at ${d} (bb toolchains remove ${what} first)"
    rest="$(sdk_meta resolve "$what")"
    version="${rest%%	*}"; url="${rest#*	}"
    [ -n "$url" ] || die "could not resolve a download URL for ${what}"
    strip="$(sdk_meta field "$what" source.strip)"; strip="${strip:-0}"
    log "installing ${what}${version:+ }${version} into ${d}"
    mkdir -p "$d"
    tmp="$(mktemp "${TMPDIR:-/tmp}/bb-${what}.XXXXXX")"
    sdk_fetch "$url" "$tmp" || { rm -f "$tmp"; die "could not download ${url}"; }
    sdk_verify_download "$what" "$tmp" "$url" "$version" "$d"
    # -a: tar picks the decompressor from the file, so the catalog does not
    # have to say whether a release ships .gz or .xz this year.
    tar -xaf "$tmp" -C "$d" --strip-components="$strip" || { rm -f "$tmp"; die "could not unpack ${url}"; }
    rm -f "$tmp"
    sdk_install_verify "$what" "$d" "$version"
}

# Fetch an installer and run it. The URL here is a script, not the payload;
# it goes and gets that itself, with the arguments the catalog gives.
sdk_install_script() {
    local what="$1" d url tmp tmpdir
    d="$(sdk_dir "$what")"
    sdk_mark_partial "$d"
    [ -z "$(sdk_meta field "$what" source.fresh_only)" ] || [ ! -d "$d" ] \
        || die "${what} is already installed at ${d} (bb toolchains remove ${what} first)"
    url="$(sdk_meta field "$what" source.url)"
    [ -n "$url" ] || die "no installer URL in the catalog for ${what}"
    log "installing ${what} into ${d}"
    mkdir -p "$d"
    # Kept under the name upstream gave it, in a directory of its own.
    # rustup-init decides what it is by the name it was invoked as: downloaded
    # as bb-rust.XXXXXX it refused with "unknown proxy name: 'bb-rust'", having
    # taken its own filename for an instruction. An installer's name is part of
    # its interface, so it keeps the one from the URL.
    tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/bb-${what}.XXXXXX")"
    tmp="$tmpdir/$(basename "${url%%\?*}")"
    sdk_fetch "$url" "$tmp" || { rm -rf "$tmpdir"; die "could not download ${url}"; }
    sdk_verify_download "$what" "$tmp" "$url" "" "$d"
    [ -z "$(sdk_meta field "$what" source.chmod)" ] || chmod +x "$tmp"
    local -a cmd env
    sdk_meta_into cmd argv "$what" source.run "dir=$d" "script=$tmp"
    [ "${#cmd[@]}" != 0 ] || { rm -f "$tmp"; die "no run command in the catalog for ${what}"; }
    sdk_meta_into env env "$what" source.env "dir=$d"
    env "${env[@]}" "${cmd[@]}" || { rm -rf "$tmpdir"; die "${what} installer failed"; }
    rm -rf "$tmpdir"
    sdk_install_steps "$what" "$d"
    sdk_install_verify "$what" "$d" ""
}

# A shallow clone. The tool updates itself in place from here, which a tarball
# cannot do, and it is the form its own tooling expects.
sdk_install_git() {
    local what="$1" d url branch depth commit
    d="$(sdk_dir "$what")"
    sdk_mark_partial "$d"
    [ -z "$(sdk_meta field "$what" source.fresh_only)" ] || [ ! -d "$d" ] \
        || die "${what} is already installed at ${d} (bb toolchains remove ${what} first)"
    url="$(sdk_meta field "$what" source.url)"
    branch="$(sdk_meta field "$what" source.branch)"
    depth="$(sdk_meta field "$what" source.depth)"
    commit="$(sdk_meta field "$what" source.commit)"
    [ -n "$url" ] || die "no clone URL in the catalog for ${what}"
    if [ -n "$commit" ]; then
        # Pinned (a tool pack, R77): exactly the commit somebody approved,
        # whatever the branch has moved on to since, and checked to be it.
        # safe.directory for this command alone: a store on a share that
        # maps every owner to one account (a node's NFS mount) is another
        # user's to git, which then refuses the directory it just made.
        log "fetching ${what} at ${commit:0:12} into ${d}"
        local -a g=(git -c "safe.directory=$d" -C "$d")
        git init -q "$d"
        "${g[@]}" fetch --progress --depth 1 "$url" "$commit"
        "${g[@]}" checkout -q --detach FETCH_HEAD
        [ "$("${g[@]}" rev-parse HEAD)" = "$commit" ] \
            || die "${what}: ${url} answered $("${g[@]}" rev-parse --short HEAD) where ${commit:0:12} was approved"
        # The commit's hash is the check on what was fetched (R137): what the
        # Installed page says of a pack's row.
        printf 'sha1\t%s\tthe git commit an administrator approved\n' "$commit" > "$d/.bb-verified" 2>/dev/null || true
        sdk_mark_exec "$what" "$d"
    else
        log "cloning ${what} (${branch:-default}) into ${d}"
        # --progress: git prints none unless stderr is a terminal, and this runs
        # from the dashboard's job runner, where it is a pipe.
        git clone --progress ${depth:+--depth "$depth"} ${branch:+-b "$branch"} "$url" "$d"
    fi
    [ -z "$(sdk_meta field "$what" source.safe_directory)" ] \
        || git config --global --add safe.directory "$d"
    local -a warm
    sdk_meta_into warm argv "$what" source.warm "dir=$d"
    if [ "${#warm[@]}" != 0 ]; then
        log "$(sdk_meta field "$what" source.warm_note)"
        # Bounded, and asked of nobody: flutter's first --version sat for half
        # an hour on bb-sandbox with nothing written (12 Oct) and held every
        # toolchain queued behind it. CI=true is how its tool knows no person
        # is there to answer; a warm-up that does not finish in the limit
        # fails this toolchain alone, saying so, and the job goes on.
        if ! CI=true FLUTTER_SUPPRESS_ANALYTICS=true DOTNET_CLI_TELEMETRY_OPTOUT=1 \
                timeout --kill-after=30 "${BB_WARM_TIMEOUT:-900}" "${warm[@]}" < /dev/null; then
            die "${what}: warming did not finish within ${BB_WARM_TIMEOUT:-900}s (${warm[*]}); this install is taken off again, and Install retries it"
        fi
    fi
    # A repository that installs more than itself (a tool pack's install
    # steps fetching its binaries) runs them as the script kind does.
    sdk_install_steps "$what" "$d"
    [ -z "$commit" ] || sdk_mark_exec "$what" "$d"
    sdk_install_verify "$what" "$d" ""
}

# The programs a tool pack runs by path, marked executable (B83): what its
# verbs, steps and verify name and what is in its bin directories
# (toolpacks.recipe lists them). A file committed through a forge's web
# editor carries no executable bit, and every run of it was 'Permission
# denied'. Run after the checkout and again after the steps, which may have
# downloaded into bin/. A path the pack does not have yet is passed over.
sdk_mark_exec() {
    local what="$1" d="$2" p
    local -a files dirs
    sdk_meta_into files argv "$what" source.exec "dir=$d"
    sdk_meta_into dirs argv "$what" source.exec_dirs "dir=$d"
    for p in "${files[@]}"; do
        [ ! -f "$p" ] || [ -x "$p" ] || { log "marking ${p#"$d"/} executable"; chmod a+x "$p"; }
    done
    for p in "${dirs[@]}"; do
        [ ! -d "$p" ] || find "$p" -maxdepth 1 -type f ! -perm -u+x -exec chmod a+x {} +
    done
}

# Something already in the image, pointed at the install directory.
sdk_install_command() {
    local what="$1" d need
    d="$(sdk_dir "$what")"
    sdk_mark_partial "$d"
    need="$(sdk_meta field "$what" source.requires)"
    [ -z "$need" ] || command -v "$need" >/dev/null 2>&1 \
        || die "${need} is not in this image"
    mkdir -p "$d"
    local -a cmd env
    sdk_meta_into cmd argv "$what" source.run "dir=$d"
    sdk_meta_into env env "$what" source.env "dir=$d"
    log "installing ${what} into ${d}"
    env "${env[@]}" "${cmd[@]}"
    # A stable path to whatever the run produced under a revisioned name, so
    # that everything pointing at it survives the next release.
    local find_at link_at exe
    find_at="$(sdk_meta field "$what" source.link.find)"
    link_at="$(sdk_meta field "$what" source.link.as)"
    if [ -n "$find_at" ] && [ -n "$link_at" ]; then
        exe="$(find "$d" -path "$find_at" -type f 2>/dev/null | head -1)"
        # RELATIVE to the link's own directory (B170): the store is mounted at
        # /sdk in the controller and at /mnt/... on a node, so an absolute
        # target written by one is a dangling link on the other. realpath -s
        # does not resolve links on the way; where it has no --relative-to
        # (macOS) the absolute form is the one machine's answer, as before.
        local at rel
        at="${link_at//\{dir\}/$d}"
        if [ -n "$exe" ]; then
            rel="$(realpath -s --relative-to="$(dirname "$at")" "$exe" 2>/dev/null)" || rel="$exe"
            ln -sfn "${rel:-$exe}" "$at"
        fi
    fi
    log "${what} ready at ${d}"
}

# The optional extra commands a recipe runs after its installer: .NET's
# workload, and anything like it. `optional` carries the warning to print when
# one fails, because a workload that will not install does not undo an SDK
# that did.
sdk_install_steps() {
    local what="$1" d="$2" i=0 note soft
    while :; do
        local -a cmd env
        sdk_meta_into cmd argv "$what" "source.then.${i}.run" "dir=$d"
        [ "${#cmd[@]}" != 0 ] || break
        note="$(sdk_meta field "$what" "source.then.${i}.note")"
        soft="$(sdk_meta field "$what" "source.then.${i}.optional")"
        [ -z "$note" ] || log "$note"
        sdk_meta_into env env "$what" "source.then.${i}.env" "dir=$d"
        if ! env "${env[@]}" "${cmd[@]}"; then
            [ -n "$soft" ] || die "${what}: a required step failed"
            warn "$soft"
        fi
        i=$((i + 1))
    done
}

# Run after installing, so a broken unpack fails here rather than the first
# time somebody tries to use the thing.
sdk_install_verify() {
    local what="$1" d="$2" version="$3"
    local -a cmd env
    sdk_meta_into cmd argv "$what" source.verify "dir=$d" "version=$version"
    [ "${#cmd[@]}" != 0 ] || return 0
    sdk_meta_into env env "$what" source.env "dir=$d"
    # Captured rather than piped into head: a pipeline reports head's exit
    # status, so a verify that failed would have read as passing, and closing
    # the pipe early can kill the producer with SIGPIPE, which pipefail then
    # reports as a failure that never happened.
    local out
    out="$(env "${env[@]}" "${cmd[@]}" 2>&1)" \
        || die "${what} installed but ${cmd[0]} does not run: ${out}"
    printf '%s\n' "${out%%$'\n'*}"
}

sdk_install() {
    sdk_operator_only install "$@"
    local what="${1:-}" root kind; root="$(sdk_root)"
    [ -n "$what" ] || die "usage: bb toolchains install <toolchain> (bb toolchains list names them)"
    if [ "$what" = tizen ]; then sdk_install_tizen; return 0; fi
    kind="$(sdk_meta field "$what" source.kind 2>/dev/null)" || kind=""
    # The same full-id escape hatch removal has: `bb emu images` prints ids the
    # catalog does not list, and what can be removed by id has to be
    # reinstallable by id, or the warning a removal prints names a command
    # that does not work. An image flavor by name lands here too. Both reach
    # this through `bb emu image add`; `bb toolchains` refuses them first.
    [ -n "$kind" ] || case "$what" in android:*\;*) kind=sdkmanager ;; esac
    [ -n "$kind" ] || { sdk_image_flavor "$what" >/dev/null && kind=sdkmanager; }
    [ -n "$kind" ] || die "unknown toolchain: ${what} (bb toolchains list names them)"
    # The internet before anything is touched (R82): a machine with none was
    # told by a urllib traceback, or curl's "Could not resolve host", cut
    # short in the row's red line. A versioned android id has no catalog row
    # to ask, and its host is sdkmanager's, which the row for it names.
    # Reach answers 1 exactly when it has the sentence, which set -e took for
    # a failure and ended the install on, silently (B144).
    local why=""
    case "$what" in android:*\;*) why="$(sdk_meta reach android:platform-tools 2>/dev/null)" || true ;;
                    *)            why="$(sdk_meta reach "$what" 2>/dev/null)" || true ;; esac
    [ -z "$why" ] || die "${what} cannot be installed here: ${why}"
    mkdir -p "$root"
    [ "$kind" = sdkmanager ] || sdk_clear_interrupted "$(sdk_dir "$what")"
    [ "$kind" = sdkmanager ] || sdk_clear_toolless "$what" "$(sdk_dir "$what")"
    # EXIT rather than RETURN: a failing step here reaches `die`, which exits
    # the process, and a RETURN trap never fires on that path.
    trap sdk_install_cleanup EXIT
    trap sdk_install_aborted TERM INT
    case "$kind" in
        sdkmanager) sdk_install_android "$what" ;;
        tarball)    sdk_install_tarball "$what" ;;
        script)     sdk_install_script  "$what" ;;
        git)        sdk_install_git     "$what" ;;
        command)    sdk_install_command "$what" ;;
        *) die "the catalog gives ${what} an unknown source kind: ${kind}" ;;
    esac
    local -a after=()
    # A versioned android id (a platform a project pins, an emulator image)
    # has no catalog row to carry an `after`, and asking printed "no
    # toolchain named ... in the catalog" into the job's log after a
    # successful install (B712).
    case "$what" in android:*\;*) ;; *) sdk_meta_into after argv "$what" source.after ;; esac
    local line; for line in "${after[@]}"; do log "$line"; done
    case "$kind" in
        tarball|script|git) log "${what} ready: new shells pick it up; this one: eval \"\$(bb toolchains env)\"" ;;
    esac
    [ -z "${SDK_PARTIAL:-}" ] || rm -f "$(sdk_partial_marker "$SDK_PARTIAL")"
    SDK_PARTIAL=""
    # Cleared here rather than up front: an install that fails leaves the
    # toolchain absent, and a marker cleared on the way in would have let the
    # next restart quietly fetch what the operator had removed.
    rm -f "$(sdk_removed_marker "$what")"
}

# Not in the catalog: everything there installs, and this cannot. Kept because
# the question keeps coming up and the honest answer has two halves.
sdk_install_tizen() {
    cat <<'EOF'
Tizen is Samsung's OS, and where it runs decides whether you want it:

  TVs, signage and appliances   alive and current. Samsung ships Tizen on
                                every smart TV, and licenses it to other TV
                                makers. This is the reason to install it.
  Watches                       over. Samsung moved Galaxy Watch to Wear OS
                                with the Watch 4 in 2021, so for a watch app:
                                    bb emu image add wear
  Phones                        discontinued in 2017.

There is no headless installer worth automating (Samsung ships a GUI Java
bundle), so putting it on the toolchain store is a manual job:

  1. Download the Ubuntu package from
     https://developer.tizen.org/development/tizen-studio/download
  2. Install it with its --accept-license flag into  $(bb toolchains root)/tizen
  3. bb toolchains env   (picks up tools/ide/bin for tizen and tools for sdb)
EOF
}

sdk_remove() {
    sdk_operator_only remove "$@"
    local what="${1:-}" d marker
    # What the catalog says it is, so that adding a toolchain really is one edit:
    # a list of names repeated here is a toolchain that installs and will not
    # come off again.
    local kind; kind="$(sdk_meta field "$what" source.kind 2>/dev/null)" || kind=""
    [ -n "$kind" ] || { sdk_image_flavor "$what" >/dev/null && kind=sdkmanager; }
    if [ -z "$kind" ]; then
        case "$what" in
            # A full sdkmanager id (system-images;android-30;google_apis;x86_64
            # and the like). No catalog row names one, because they are not a
            # fixed list: which exist here depends on what has been installed.
            # `bb emu images` lists them.
            android:*\;*)
                kind=sdkmanager
                # A typo'd id would otherwise reach sdkmanager, which fetches
                # the whole remote repository before deciding it has nothing to
                # uninstall: a minute of network for a misspelling. Every id
                # of this shape maps to a directory, so ask the disk first.
                [ -d "${ANDROID_HOME:-/opt/android-sdk}/$(printf '%s' "${what#android:}" | tr ';' '/')" ] \
                    || die "${what} is not installed (bb emu images lists what is)"
                ;;
            # tizen is not in the catalog (nothing there can install it), but
            # it is a directory on the share like any other, so it comes off
            # like one.
            tizen) ;;
            *) die "unknown toolchain: ${what} (bb toolchains list names them)" ;;
        esac
    fi
    # Then the marker, before anything is deleted, so an uninstall that dies
    # half way still counts as one having been asked for: a hook re-fetching
    # 1.3GB behind a failed removal is the surprise this exists to stop. After
    # the name is checked, though: a typo used to leave a marker behind for a
    # toolchain that does not exist.
    marker="$(sdk_removed_marker "$what")"
    mkdir -p "$(dirname "$marker")" 2>/dev/null && : > "$marker" || true
    if [ "$kind" != sdkmanager ]; then
        d="$(sdk_find "$what")" || die "${what} is not installed"
        log "removing ${d}"
        rm -rf "$d"
        return 0
    fi
    case "$kind" in
        sdkmanager)
            # No refusal here without sdkmanager: removing needs only the
            # package's directory, which sdkmgr deletes itself when the
            # command-line tools are not there.
            local pkg="${what#android:}" v image="" rest
            if rest="$(sdk_image_flavor "$what")"; then
                image="${rest%%	*}"; pkg="$image"
            fi
            sdk_android_list_forget
            if [ -n "$image" ]; then
                local dir api abi
                for dir in "${ANDROID_HOME:-/opt/android-sdk}/system-images"/*/"$image"; do
                    [ -d "$dir" ] || continue
                    api="$(basename "$(dirname "$dir")")"
                    for abi in "$dir"/*/; do
                        [ -d "$abi" ] || continue
                        log "removing system-images;${api};${image};$(basename "$abi")"
                        sdk_android_clear_stale_installer "system-images;${api};${image};$(basename "$abi")"
                        sdkmgr --uninstall "system-images;${api};${image};$(basename "$abi")"
                    done
                    # The flavor directory is left behind by the uninstall,
                    # empty, and an empty directory with the right name is what
                    # made a removed image keep answering "installed".
                    rmdir "$dir" 2>/dev/null || true
                done
                sdk_relink_android
                return 0
            fi
            if [ -n "$(sdk_meta field "$what" source.versioned 2>/dev/null)" ]; then
                    # Versioned the same way going out: uninstall every version
                    # that is actually present, from the directory rather than
                    # from a guess about which one was installed.
                    for v in "${ANDROID_HOME:-/opt/android-sdk}/$pkg"/*/; do
                        [ -d "$v" ] || continue
                        log "removing ${pkg};$(basename "$v")"
                        sdk_android_clear_stale_installer "${pkg};$(basename "$v")"
                        sdkmgr --uninstall "${pkg};$(basename "$v")"
                    done
                    sdk_relink_android
                    return 0
            fi
            # A top-level package whose directory under ANDROID_HOME is one of
            # our symlinks (the emulator is the only one in the catalog) is
            # deleted by sdkmanager as *the link*, leaving the payload sitting
            # on the share: 820MB reported as removed and still spent. So
            # resolve where it really lives before asking, and clear that.
            # (ndk, cmake, platforms and the system images are directories
            # *below* a link, so sdkmanager deletes the real bytes itself.)
            local store=""
            if [ -L "${ANDROID_HOME:-/opt/android-sdk}/$pkg" ]; then
                store="$(readlink -f "${ANDROID_HOME:-/opt/android-sdk}/$pkg")"
            fi
            sdk_android_clear_stale_installer "$pkg"
            sdkmgr --uninstall "$pkg"
            if [ -n "$store" ] && [ -d "$store" ] && [ -n "$(ls -A "$store" 2>/dev/null)" ]; then
                log "clearing ${store}: sdkmanager removed the link, not the files"
                rm -rf "${store:?}"
            fi
            # The directories above a removed image: sdkmanager takes the abi
            # and leaves android-30/google_apis/ standing, and an empty
            # directory with the right name is what makes a removed image keep
            # answering "installed".
            case "$pkg" in
                system-images\;*)
                    local left
                    left="${ANDROID_HOME:-/opt/android-sdk}/$(printf '%s' "$pkg" | tr ';' '/')"
                    rmdir "$left" 2>/dev/null || true
                    rmdir "$(dirname "$left")" 2>/dev/null || true
                    rmdir "$(dirname "$(dirname "$left")")" 2>/dev/null || true
                    ;;
            esac
            sdk_relink_android
            return 0 ;;
    esac
}

# bb emu images: the android system images actually installed here.
#
# Not a catalog matter: which exist depends on what has been installed, and an
# image lands there by a choice on the Emulator tab or bb emu create, never by
# a baseline. One TSV line each (id, API level, flavor, size, the AVDs built
# on it) so the tab can offer to remove the ones nobody is using. Forty-four
# gigabytes of them accumulated here before there was any way to see them.
# Which AVDs are built on a given image. An AVD names one exactly, in a line
# like `image.sysdir.1=system-images/android-36/google_apis/x86_64/`, and
# will not boot without it, which is the difference between an image that is
# spare and one that something depends on. Two flavors at the same API level
# are not interchangeable here: an AVD asking for google_apis does not accept
# google_apis_playstore, however alike they look on the shelf.
sdk_avd_users() {
    local home="${ANDROID_AVD_HOME:-$HOME/.android/avd}" cfg dir want="$1"
    [ -d "$home" ] || return 0
    for cfg in "$home"/*.avd/config.ini; do
        [ -f "$cfg" ] || continue
        # Spaces around the = are allowed: avdmanager writes them, the
        # emulator's own rewrites do not, and both turn up in one directory.
        dir="$(sed -n 's|^[[:space:]]*image\.sysdir\.1[[:space:]]*=[[:space:]]*||p' "$cfg" | head -1)"
        dir="${dir%/}"
        [ "$(printf '%s' "$dir" | tr '/' ';')" = "$want" ] || continue
        printf '%s\n' "$(basename "$(dirname "$cfg")" .avd)"
    done
}

sdk_images() {
    local base d api kind abi id users
    base="${ANDROID_HOME:-/opt/android-sdk}/system-images"
    [ -d "$base" ] || return 0
    while IFS= read -r d; do
        [ -n "$(ls -A "$d" 2>/dev/null)" ] || continue
        abi="$(basename "$d")"; kind="$(basename "$(dirname "$d")")"
        api="$(basename "$(dirname "$(dirname "$d")")")"
        id="system-images;${api};${kind};${abi}"
        users="$(sdk_avd_users "$id" | paste -sd, -)"
        printf '%s\t%s\t%s\t%s\t%s\n' \
            "$id" "$api" "$kind" \
            "$(du -sk "$d" 2>/dev/null | cut -f1)" "$users"
    done < <(find -L "$base" -mindepth 3 -maxdepth 3 -type d 2>/dev/null | sort -V)
}

cmd_toolchains() {
    local sub="${1:-status}"; shift || true
    case "$sub" in
        status|"")  sdk_status "$@" ;;
        # `bb toolchains --local` reads as a flag on the bare command, which is
        # how anyone would type it; the dispatch would otherwise take it
        # for a subcommand and print the usage line.
        --local)    sdk_status --local ;;
        root)       printf '%s\n' "$(sdk_root)" ;;
        env)        sdk_env_snippet ;;
        list)       sdk_meta names ;;
        plan)       sdk_plan "$@" ;;
        install)    sdk_not_image install "$@"; sdk_install "$@"; sdk_write_env ;;
        check)      sdk_check "$@" ;;
        versions)   sdk_versions "$@" ;;
        relink)     sdk_relink_android ;;
        update)     sdk_not_image update "$@"; sdk_update "$@"; sdk_write_env ;;
        remove)     sdk_not_image remove "$@"; sdk_remove "$@"; sdk_write_env ;;
        images|flavors)
            die "system images are the emulator's, not a toolchain: bb emu ${sub} $*" ;;
        *) die "usage: bb toolchains [status [--local]|root|env|list|plan X|versions|check|relink|install X|update X|remove X]" ;;
    esac
}

# Whether a name is a system image: a full sdkmanager id, or a flavor by its
# catalog key or its short name (tv, wear, playstore).
sdk_is_image() {
    case "${1#android:}" in system-images\;*) return 0 ;; esac
    sdk_image_flavor "$1" >/dev/null
}

# A system image is not a toolchain: it exists at every API level at once, and
# which one to have is a question about what is being tested. So it has a
# verb of its own under bb emu, and this one says where that is rather than
# quietly doing the same thing under a second name.
sdk_not_image() {
    local verb="$1" x; shift
    for x in "$@"; do
        sdk_is_image "$x" || continue
        case "$verb" in
            remove) die "${x#android:} is a system image, not a toolchain: bb emu image remove ${x#android:}" ;;
            *)      die "${x#android:} is a system image, not a toolchain: bb emu image add ${x#android:}" ;;
        esac
    done
}

# bb emu images|flavors|image add|remove: the system images on this machine's
# toolchain store, which is where they live even though they are not
# toolchains. The operator's, like bb toolchains install: sdk_install and
# sdk_remove refuse inside a Claude session on their own.
cmd_emu_images() {
    local sub="$1"; shift || true
    case "$sub" in
        images)
            if [ "${1:-}" = --available ]; then sdk_meta images; else sdk_images; fi ;;
        flavors) sdk_meta flavors ;;
        image)
            local verb="${1:-}" id="${2:-}"
            [ -n "$id" ] || die "usage: bb emu image add|remove ID (bb emu images --available lists them, bb emu flavors names the short ones)"
            sdk_is_image "$id" || die "${id} is not a system image: bb emu images --available lists them"
            [ -z "${CLAUDECODE:-}${BB_AGENT:-}" ] || die "a system image is the operator's to add or remove, and this is an agent's session.
Ask them to do it from the dashboard's Emulator page, or to
run: bb emu image ${verb} ${id}
If you ARE the operator at this keyboard: env -u CLAUDECODE -u BB_AGENT bb emu image ${verb} ${id}"
            case "$verb" in
                add)    sdk_install "android:${id#android:}"; sdk_write_env ;;
                remove) sdk_remove "android:${id#android:}"; sdk_write_env ;;
                *) die "usage: bb emu image add|remove ID" ;;
            esac ;;
    esac
}
