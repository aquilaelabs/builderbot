#!/usr/bin/env bash
# Shared helpers for BuilderBot startup scripts.
# shellcheck shell=bash

BUILDER_HOME="${BUILDER_HOME:-/home/builder}"
WORKSPACE="${WORKSPACE:-/workspace}"

# Boot's finish line, as a file rather than a log line.
#
# The dashboard is started BY a hook (15-dashboard.sh) and the hooks after it
# keep running. So anything the dashboard measures in that window is measuring
# a half-built container, and `bb doctor`'s answer there is not just early, it
# is wrong, and it is cached for half an hour, so it stays wrong.
#
# In /run rather than /run/builderbot, which is 0700 root because it holds the
# redaction table; the marker is meant to be read by the builder user. Cleared
# at the top of every boot: neither /run nor /tmp is a mount of its own here,
# so both survive a `docker restart` and a marker left from last time would say
# "ready" before this boot had done anything. server.py names the same path.
BOOT_READY_FILE="${BOOT_READY_FILE:-/run/builderbot-ready}"

# Which half of BuilderBot this process is running on (roadmap #21, #24).
#
# `controller` is the management instance: the dashboard, the notebook, the
# queue and the record. `node` is a machine that enrolled with a controller
# and runs its jobs and, since roadmap #24, its SESSIONS: the same bb-tty
# starts Claude there, in the node's synced copy of the project, with this
# library answering for a machine that keeps no /config and has no owner.
#
# BUILDERBOT_ROLE is not a setting on this image: the AGENT sets it, in the
# environment every session it starts on a node inherits. This container is
# always a controller. Read here rather than only in the entrypoint because
# bb, bb-tty and the account helpers below all have a node answer that
# differs, and all three run on a node out of the bundle.
bb_role() {
    case "$(printf '%s' "${BUILDERBOT_ROLE:-controller}" | tr '[:upper:]' '[:lower:]')" in
        node|worker|agent) printf 'node' ;;
        *)                 printf 'controller' ;;
    esac
}

# on_node: true on a node. The four account helpers, bb's notebook verbs
# and bb-tty all branch on it, so it is one word rather than a case each.
on_node() { [ "$(bb_role)" = node ]; }

log()  { printf '[builderbot] %s\n'      "$*"; }
warn() { printf '[builderbot] WARN: %s\n' "$*" >&2; }
die()  { printf '[builderbot] ERROR: %s\n' "$*" >&2; exit 1; }

# is_true VALUE: accepts true/1/yes/on in any case.
# bb_setting KEY [DEFAULT]: a Settings-tab value (roadmap R29) out of
# /config/settings.json, else the default. Booleans come out as the words
# true/false, so is_true reads them. jq is in the image; without it, or without
# the file, the answer is the default, never a crash at boot.
bb_setting() {
    local f="${DASHBOARD_STATE:-/config}/settings.json" v=""
    if [ -r "$f" ] && command -v jq >/dev/null 2>&1; then
        v="$(jq -r --arg k "$1" \
              'if has($k) and .[$k] != null then (.[$k] | tostring) else empty end' \
              "$f" 2>/dev/null || true)"
    fi
    printf '%s' "${v:-${2:-}}"
}

is_true() {
    case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
        true|1|yes|y|on) return 0 ;;
        *) return 1 ;;
    esac
}

# is_mountpoint PATH: is this path a bind mount from the host?
#
# Used to tell a directory this container owns from one that belongs to the
# server: the projects folder is mounted whole now, so /workspace is somebody's
# share rather than a scratch directory we made, and changing its ownership is
# not ours to do.
is_mountpoint() {
    local p="${1%/}"
    [ -n "$p" ] || return 1
    awk -v p="$p" '$5 == p { found = 1 } END { exit !found }' /proc/self/mountinfo
}

# sdk_root: where downloadable SDKs live.
#
# The image is the wrong home for them: /opt is discarded on every update, so
# anything installed there is downloaded again on a weekly schedule, and the
# toolchains are large enough (a system image is a couple of GB, the emulator
# 800MB) for that to be the dominant cost of an update. A mounted share keeps
# them outside the image entirely: installed once, kept forever, shared by
# every toolchain that can be told where to unpack.
#
# SDK_ROOT is that share, /sdk by default. Without one (nobody mapped it),
# this falls back to the home volume, which also persists but is the
# operator's own directory rather than a place to put 30GB.
# sdk_store_root: the toolchain store as the operator mapped it (the share,
# or the home volume's .sdk). What the marker and the settings name.
sdk_store_root() {
    local root="${SDK_ROOT:-/sdk}"
    # ...and the one place the name means something else. The agent on a node
    # exports SDK_ROOT as the SCOPE directory (<store>/linux-x86_64), because
    # that is also what it sets BUILDER_HOME and ANDROID_HOME from, and a CI
    # runner's .env carries the same (agent.mjs asserts it). Here SDK_ROOT is
    # the store, which sdk_root then scopes, so taking the agent's at its word
    # scoped it twice: /mnt/SDK/linux-x86_64/linux-x86_64, a directory that
    # does not exist, and every toolchain on the node read as not installed
    # while it sat there (B89). One name, two meanings; this is where they
    # meet, so this is where it is settled. Guarded on the scope directory NOT
    # containing another of the same name, so a store somebody really did call
    # linux-x86_64 is still taken at its word.
    if [ "$(basename "$root")" = "$(sdk_scope)" ] && [ ! -d "$root/$(sdk_scope)" ]; then
        root="$(dirname "$root")"
    fi
    if [ -d "$root" ] && [ -w "$root" ]; then
        # /sdk is the image's own default and exists in the image whether or
        # not anybody mapped a share there, so it has to prove it is a mount
        # before anything large is written to it. Any other path is one the
        # operator chose (a subdirectory of another share, say) and is
        # taken at its word; silently ignoring it and using the home volume
        # instead is the behavior this branch exists to avoid.
        if [ "$root" != /sdk ] || is_mountpoint "$root"; then
            printf '%s' "$root"
            return 0
        fi
    fi
    printf '%s' "${BUILDER_HOME:-${HOME:-/home/builder}}/.sdk"
}

# sdk_scope: this machine's directory in the store, <os>-<arch> as uname
# spells them (linux-x86_64). One share serves a Linux box, a Mac and a
# Windows machine only if their binaries do not land on top of each other,
# so everything installed lives one level down from the share (roadmap
# R19); the agent on a node keeps the same rule, in the same words.
# On a node the agent names it (BB_SDK_SCOPE): since R196 each node keeps its
# own directory, its node id, and a platform's name is only the fallback for
# this container and a node whose agent predates that.
sdk_scope() {
    if [ -n "${BB_SDK_SCOPE:-}" ]; then printf '%s' "$BB_SDK_SCOPE"; return; fi
    printf '%s-%s' "$(uname -s | tr '[:upper:]' '[:lower:]')" "$(uname -m)"
}

# sdk_root: where THIS machine's toolchains are, the store's scope directory.
# Every install, probe and PATH entry is relative to this.
sdk_root() { printf '%s/%s' "$(sdk_store_root)" "$(sdk_scope)"; }

# sdk_share_images [STORE] applies the layout's standing rule: the Android
# system images live once under <store>/shared/android/system-images, and
# this scope's android/system-images is a link to them. A real directory that
# grew there (a first install on a fresh store) is moved under shared and
# linked. Run at boot (45-sdk.sh). (The one-time move of a flat store into
# its scope ran on 9 Sep 2026 and was taken out again.)
sdk_share_images() {
    local store="${1:-$(sdk_store_root)}" scoped e
    [ -d "$store" ] || return 0
    scoped="$store/$(sdk_scope)"
    # The system images, shared.
    local mine="$scoped/android/system-images" shared="$store/shared/android/system-images"
    if [ -d "$mine" ] && [ ! -L "$mine" ]; then
        if [ ! -d "$shared" ]; then
            mkdir -p "$(dirname "$shared")" && mv "$mine" "$shared" \
                && log "toolchain store: the android system images are shared across platforms"
        else
            for e in "$mine"/*; do
                [ -e "$e" ] || continue
                [ -e "$shared/$(basename "$e")" ] || mv "$e" "$shared/"
            done
            rmdir "$mine" 2>/dev/null || log "toolchain store: $mine still holds images the shared copy also has; remove it by hand"
        fi
    fi
    if [ -d "$shared" ] && [ -d "$scoped/android" ] && [ ! -e "$mine" ] && [ ! -L "$mine" ]; then
        ln -s "../../shared/android/system-images" "$mine" 2>/dev/null || true
    fi
    return 0
}

# sdk_have ROOT NAME: is a toolchain installed under the toolchain store root?
sdk_have() {
    [ -d "$1/$2" ] && [ -n "$(ls -A "$1/$2" 2>/dev/null)" ]
}

# sdk_find NAME: where a toolchain actually is, the share if it holds it,
# otherwise the home volume's root, otherwise nothing.
#
# The two can both be real. Anything installed before a share was mapped sits
# on the home volume, and mapping one must not make it vanish, which it did:
# PATH lost three toolchains and the dashboard called them uninstalled while
# 8GB of them sat on disk. Same rule the Android package directories follow,
# for the same reason: a thing that exists is never hidden behind an empty
# directory somewhere else. Installs still go to the share; this is only
# about finding what is already there.
# A toolchain the operator deliberately removed.
#
# Two startup hooks fetch things on a fresh share (the browsers, the
# emulator) because a container that comes up "ready" with `bb capture shot` broken
# is worse than a slow first boot. But a fresh share and a share somebody just
# cleared look identical, so an uninstall used to last until the next restart
# and no further. This is how the intent outlives it: `bb toolchains remove` leaves a
# marker, `bb toolchains install` clears it, and a hook that finds one keeps its
# hands off. On the share, because an image update must not forget it.
sdk_removed_marker() {
    printf '%s/.removed/%s' "$(sdk_root)" "$(printf '%s' "$1" | tr ':/' '--')"
}

sdk_find() {
    local name="$1" root fallback
    root="$(sdk_root)"
    fallback="${BUILDER_HOME:-${HOME:-/home/builder}}/.sdk"
    if sdk_have "$root" "$name"; then printf '%s/%s' "$root" "$name"; return 0; fi
    if [ "$fallback" != "$root" ] && sdk_have "$fallback" "$name"; then
        printf '%s/%s' "$fallback" "$name"; return 0
    fi
    return 1
}

# run_as_builder CMD...: drop privileges when we happen to be root.
run_as_builder() {
    if [ "$(id -u)" -eq 0 ]; then
        gosu builder "$@"
    else
        "$@"
    fi
}

# bb_log_dir: where the persistent log lives. Priority: explicit BB_LOG_DIR
# env, then a mounted /logs volume (the optional template/compose mapping),
# then the default inside /config.
bb_log_dir() {
    if [ -n "${BB_LOG_DIR:-}" ]; then
        printf '%s' "$BB_LOG_DIR"
    elif [ -d /logs ]; then
        printf '%s' /logs
    else
        printf '%s' /config/logs
    fi
}

# bb_image_log: the ledger of images this container has actually run.
#
# The one fact nothing else here keeps. The container is recreated on every
# image update, so its own stamp answers only "what is running now"; the boot
# log rotates away after a few starts; and with no PAT there is no registry to
# ask. That leaves "which build was the box on when I saw that?", the first
# question whenever a fix appears not to have landed, with nothing to read.
#
# /config, because the file has to survive the update it exists to record.
bb_image_log() {
    printf '%s' "${BB_IMAGE_LOG:-/config/image-log.tsv}"
}

# git_branch DIR: current branch name, or '?'. Handles a freshly-init'd repo
# with no commits, where `rev-parse --abbrev-ref HEAD` both prints and fails.
git_branch() {
    git -C "$1" symbolic-ref --short -q HEAD 2>/dev/null \
        || git -C "$1" rev-parse --short HEAD 2>/dev/null \
        || echo '?'
}

# scope_path KIND: API path for runner registration/removal tokens, derived
# from RUNNER_URL (repo URL vs org URL).
scope_path() {
    local kind="$1" path
    path="${RUNNER_URL#*://}"      # strip scheme
    path="${path#*/}"              # strip host
    path="${path%/}"
    path="${path%.git}"
    case "$path" in
        */*) printf '/repos/%s/actions/runners/%s-token' "$path" "$kind" ;;
        "")  die "could not parse RUNNER_URL='${RUNNER_URL}'" ;;
        *)   printf '/orgs/%s/actions/runners/%s-token' "$path" "$kind" ;;
    esac
}

# github_api METHOD PATH: authenticated call against the GitHub REST API.
# Requires RUNNER_TOKEN. Prints the response body on success; on failure it
# explains what the status code means for *this* call rather than leaving a
# bare "curl: (22) ... error: 403" in the log.
github_api() {
    local method="$1" path="$2" resp code body scope_hint
    [ -n "${RUNNER_TOKEN:-}" ] || die "RUNNER_TOKEN is required for '$path'"

    case "$path" in
        /orgs/*) scope_hint="an ORG-level call: the token needs Organization permissions -> 'Self-hosted runners': Read and write (fine-grained), or the admin:org scope (classic), and its resource owner must be the organization" ;;
        *)       scope_hint="a REPO-level call: the token needs Repository permissions -> 'Administration': Read and write on that repository" ;;
    esac

    resp="$(curl -sS -w $'\n%{http_code}' -X "$method" \
        -H "Accept: application/vnd.github+json" \
        -H "Authorization: Bearer ${RUNNER_TOKEN}" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "${GITHUB_API_URL:-https://api.github.com}${path}" 2>&1)" \
        || die "could not reach the GitHub API for ${path} (network/DNS?)"

    code="${resp##*$'\n'}"
    body="${resp%$'\n'*}"

    case "$code" in
        2*) printf '%s' "$body" ;;
        401) die "GitHub rejected the token (401) on ${path}: it is invalid, revoked, or expired." ;;
        403) die "GitHub denied the request (403) on ${path}. This is ${scope_hint}." ;;
        404) die "GitHub returned 404 on ${path}. Either RUNNER_URL points somewhere that does not exist, or the token cannot see it: GitHub answers 404 rather than 403 for resources a token has no access to. This is ${scope_hint}." ;;
        *)   die "GitHub API returned ${code} on ${path}: $(printf '%s' "$body" | tr -d '\n' | head -c 200)" ;;
    esac
}

# Is anything actually listening on :0?
#
# The socket FILE outliving the server is the case this exists for. Xorg leaves
# /tmp/.X11-unix/X0 behind when it dies, so `[ -S ... ]` answers yes for a
# display nothing is behind, and every check downstream then blames EGL for a
# missing X server. Observed on 27 Aug: the doctor said "nvidia EGL is
# installed but gave no vendor driver on the X display" while the truth was
# that Xorg had exited hours before, which cost a diagnosis working outwards
# from the driver rather than inwards from the process.
#
# So connect to it rather than stat it. Python because it is guaranteed here
# and bash cannot open a unix socket.
#
# Here rather than in `bb` because the GPU startup hook asks the same question
# before deciding whether to start a server, and two spellings of "is X up"
# that can disagree is exactly how a dead display kept looking like a live one.
# Where the GPU display hook records what happened to its server: `up`,
# `restarted N times`, or `down: <why>`. In /run, so it describes THIS boot and
# nothing else: a state file that outlived its server would be the same kind
# of lie as the stale socket that made this bug expensive.
#
# Read by `bb emu gpu` and `bb doctor`. Named here because the hook writes it
# and both of those read it, which is three files that must agree on one path.
# A SIBLING of /run/builderbot, not a file inside it: the same shape
# BOOT_READY_FILE above uses, and for the same reason. That directory is
# 0700 root because it holds the secrets stash, so a state file inside it is
# unreadable by the builder account, which is what `bb emu gpu` and
# `bb doctor` run as: gpu_display_note() returned empty for everyone but
# root, and the whole point of writing the state was that the drop to
# software should be STATED rather than silent. Measured on the box 3 Sep:
# the supervisor was running and had written 'up', and both commands printed
# nothing.
GPU_DISPLAY_STATE="${GPU_DISPLAY_STATE:-/run/builderbot-gpu-display}"

# What the hook last said about the display, or "" when it has said nothing.
gpu_display_note() {
    [ -r "$GPU_DISPLAY_STATE" ] || return 0
    head -1 "$GPU_DISPLAY_STATE" 2>/dev/null
}

x_display_up() {
    [ -S /tmp/.X11-unix/X0 ] || return 1
    python3 - <<'XPY' 2>/dev/null
import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(2)
try:
    s.connect("/tmp/.X11-unix/X0")
except OSError:
    sys.exit(1)
XPY
}

# ---- per-account homes (roadmap #26) ---------------------------------------
#
# The dashboard has accounts, and each of them gets a home: own shell history,
# own Claude login, own memories. What it is NOT is a second OS user: every
# session still runs as `builder`, so everything written to the projects
# stays PUID:PGID exactly as it always has. A second uid would write files the
# rest of the array does not expect, which is the one part of this that can
# spoil somebody's data, and the operator ruled it out.
#
# What that buys and what it does not:
#   * own history, own Claude login, own memories, and a tab strip nobody else
#     is offered;
#   * NOT kernel isolation. One uid means one tmux server and one filesystem
#     view, so a member with a shell can still reach another's home if they go
#     looking. Same bargain as the sibling-project deny list. The Users tab
#     says so rather than implying more.
#
# THE OWNER KEEPS /home/builder. Not asymmetry for its own sake: that
# directory already holds a working Claude login and every transcript this box
# has ever produced, and the safe way to hand it to somebody is not to move
# it. The owner is undeletable and there is exactly one, so the mapping is
# stable. Everybody else gets a directory of their own beside it.
BUILDER_USERS="${BUILDER_USERS:-${BUILDER_HOME}/users}"

# What belongs to the BOX rather than to the person, and is therefore shared by
# every home rather than copied into it. Getting this list wrong is the
# expensive mistake in either direction: copy .gradle and each account
# re-downloads gigabytes; copy .android and the phone pairing key and the AVDs
# are duplicated, or worse, diverge. Copy .ssh and the shielded keys stop being
# shielded.
BB_SHARED_DOTFILES="
.android .gradle .npm .m2 .nuget .pub-cache .cache .dotnet .docker .nv
.npm-global .local .config .ssh .gnupg .npmrc .dart-tool .templateengine
.tmux.conf .tmux.builderbot.conf .emulator_console_auth_token
"

# The account that keeps /home/builder, read from the store rather than passed
# in: every caller of user_home would otherwise have to know it, and one that
# forgot would quietly give the owner a second home and an empty Claude login.
owner_uid() {
    # NO OWNER ON A NODE (roadmap #24). The owner keeps /home/builder and the
    # bare names because that directory is the controller's precious
    # original: the login, every transcript. Nothing on a node is anyone's
    # original, so every account there is prefixed and homed under users/,
    # the owner included; a node's users.json would not be readable anyway.
    on_node && return 0
    local f="${DASHBOARD_STATE:-/config}/users.json"
    [ -r "$f" ] || return 0
    jq -r 'first((.users // {}) | to_entries[] | select(.value.role == "owner")
                 | .value.uid) // ""' "$f" 2>/dev/null
}

# tmux_prefix UID: what that account's shell sessions are named with.
#
# Empty for the owner and for no account at all. The rule is the same one
# user_home applies and users.tmux_prefix mirrors on the server: the owner
# keeps the bare names, because a box with one operator is every box until
# somebody adds a second account.
tmux_prefix() {
    local uid="${1:-}"
    case "$uid" in
        u_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
        *) return 0 ;;
    esac
    [ "$uid" = "${BB_OWNER_UID:-$(owner_uid)}" ] && return 0
    printf '%s~' "$uid"
}

# unshare_dotfiles HOME: an account's links into the base home, taken down on
# a node (see user_home). The base home's own launchers first: one that
# reached its target THROUGH this home's .local link (a claude installed while
# this account's HOME was set, measured on bb-sandbox as B169) is pointed at
# the base home's own copy, or every account's claude would break the moment
# this link goes. Only links that point exactly at the base home's copy are
# removed; anything else in the home is the account's.
unshare_dotfiles() {
    local home="$1" d f t
    for f in "$BUILDER_HOME"/.local/bin/*; do
        [ -L "$f" ] || continue
        t="$(readlink "$f")"
        case "$t" in
            "$home/.local/"*)
                [ -e "$BUILDER_HOME/.local/${t#"$home"/.local/}" ] \
                    && ln -sfn "$BUILDER_HOME/.local/${t#"$home"/.local/}" "$f" 2>/dev/null ;;
        esac
    done
    for d in $BB_SHARED_DOTFILES; do
        [ -L "$home/$d" ] && [ "$(readlink "$home/$d")" = "$BUILDER_HOME/$d" ] \
            && rm -f "$home/$d"
    done
    return 0
}

# user_home UID: where that account's home is, made if it is missing.
#
# Prints the path and nothing else, so a caller can use it directly. An empty
# or unrecognizable id answers the box's own home, which is what every path
# that has no account behind it (a boot hook, `bb` on the command line) should
# get.
user_home() {
    local uid="${1:-}" home d target
    case "$uid" in
        u_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
        *) printf '%s' "$BUILDER_HOME"; return 0 ;;
    esac
    if [ "$uid" = "${BB_OWNER_UID:-$(owner_uid)}" ]; then
        claude_projects_link "$BUILDER_HOME" "$uid"
        printf '%s' "$BUILDER_HOME"; return 0
    fi
    home="$BUILDER_USERS/$uid"
    if [ ! -d "$home" ]; then
        mkdir -p "$home" || { printf '%s' "$BUILDER_HOME"; return 0; }
        # 0700 stops an accident, not a determined look: one uid owns them all
        # and can chmod any of them back. It is worth doing anyway: a Claude
        # credential should not be world-readable inside the container even to
        # something that could take it a harder way.
        chmod 700 "$home" 2>/dev/null || true
        for d in /opt/builderbot/skel/. "$BUILDER_HOME/.bashrc" "$BUILDER_HOME/.profile"; do
            if [ -e "${d%/.}" ]; then
                cp -rn "$d" "$home/" 2>/dev/null || true
            fi
        done
    fi
    # Linked every time rather than only at creation: the list grows as the
    # image does, and an account made before a name was added to it would
    # otherwise never get the link.
    #
    # NOT ON A NODE (B157). There every account's session runs in a view and
    # the base home is read-only in it, so a shared dotfile was either
    # unwritable (a build cache) or a way into the next account's session (a
    # .gradle distribution or jar its build runs, a .local/bin on PATH, a
    # .config or .tmux.conf that runs commands). Each account keeps its own
    # there, and a link made before this is taken down so the tool makes the
    # account's own directory on its next run. The operator chose the cost,
    # 18 Sep: each person's first build on a node downloads its own
    # dependencies.
    if on_node; then
        unshare_dotfiles "$home"
    else
        for d in $BB_SHARED_DOTFILES; do
            target="$BUILDER_HOME/$d"
            [ -e "$target" ] || continue
            [ -e "$home/$d" ] || [ -L "$home/$d" ] || ln -s "$target" "$home/$d" 2>/dev/null || true
        done
    fi
    claude_projects_link "$home" "$uid"
    printf '%s' "$home"
}

# ---- one place for an account's transcripts and memories (roadmap #24) ------
#
# Claude Code keeps everything about a conversation under
# ~/.claude/projects/<slug>/: the transcript, the resume chooser's list, the
# auto-memory files the notebook's Memory tab reads. A home is per MACHINE
# (the login in it must be), so a project bound to a node would leave its
# conversations on whichever box ran them, and unbinding it would strand the
# node's. This is what keeps them one: the projects directory of every
# account's home, on every machine, is a link to one directory at the same
# path: the controller's own under /workspace/.claude, and on a node the
# node's own there, which its agent mirrors with the controller's (B613).
# The slug is the working directory with `/` turned into `-`, and path parity
# (/workspace/<project> on both sides, worktrees included) makes it the same
# string wherever the session ran, so the controller's Memory tab and
# resume chooser read a node's sessions without knowing they were there.
#
# NOT the login: ~/.claude/.credentials.json stays in the home. A share is
# the wrong place for a credential; the login follows the account another
# way (bb login on a node fetches it with the session's token).
#
# The directory is the account's: /workspace/.claude/<uid>/projects, 0700.
# Other accounts' are walled off in a session by bb-tty exactly as sibling
# projects are, and the tree carries a .bbignore so it is never a project.
BB_CLAUDE_SHARE="${BB_CLAUDE_SHARE:-${WORKSPACE:-/workspace}/.claude}"

# claude_projects_link HOME UID: point HOME/.claude/projects at the account's
# directory on the share, making it if it is missing.
#
# A real directory already there is MOVED across: a copy into the shared
# directory (merging with whatever a session on the other machine left), the
# original renamed beside it rather than deleted. That is somebody's
# conversation history, and the one time this runs on the operator's own
# home it is every transcript this box ever produced. Nothing is removed by
# this function; the renamed original is the operator's to delete once they
# have seen the link work. Quietly does nothing when the share is not there
# to link to (a node whose mount is missing): the home then keeps its own
# directory, which is the state it was in before.
claude_projects_link() {
    local home="$1" uid="$2" share="$BB_CLAUDE_SHARE" target link keep
    [ -n "$home" ] && [ -n "$uid" ] && [ -d "$home" ] || return 0
    target="$share/$uid/projects"
    link="$home/.claude/projects"
    # A node holding its projects as a synced copy has no share: its agent
    # makes $share on the node's own /workspace, the session account's,
    # and mirrors it with the controller's (claudesync.py, B613). /workspace
    # itself is root's there, so the share being writable is enough.
    if ! { [ -d "$share" ] && [ -w "$share" ]; } \
            && ! { [ -d "${share%/*}" ] && [ -w "${share%/*}" ]; }; then
        # Nowhere to link to. A link left from when there was (a node that
        # mounted the projects share before R163) points at nothing, and Claude Code then
        # saves no conversation at all: taken down, so the home keeps its
        # own folder until the share is there again (B613).
        if [ -L "$link" ] && [ ! -e "$link" ]; then
            rm -f "$link"
        fi
        return 0
    fi
    if [ -L "$link" ]; then
        if [ "$(readlink "$link")" = "$target" ]; then
            # The folder it names may be gone though the link is right: a
            # node's /workspace made new when it moved to a synced copy.
            [ -d "$target" ] || { mkdir -p "$target" && chmod 700 "$share/$uid"; } 2>/dev/null || true
            return 0
        fi
        rm -f "$link"
    fi
    if [ ! -d "$share" ]; then
        mkdir -p "$share" 2>/dev/null || return 0
        printf 'BuilderBot: each account'"'"'s Claude transcripts and memories, shared by the controller and its nodes. Not a project.\n' \
            > "$share/.bbignore" 2>/dev/null || true
    fi
    mkdir -p "$target" 2>/dev/null || return 0
    chmod 700 "$share/$uid" 2>/dev/null || true
    mkdir -p "$home/.claude" 2>/dev/null || return 0
    if [ -d "$link" ]; then
        if [ -n "$(ls -A "$link" 2>/dev/null)" ]; then
            # Copy first, and only rename the original once the copy is
            # whole: a failure part-way leaves the home exactly as it was.
            cp -a "$link/." "$target/" 2>/dev/null || return 0
            keep="$link.moved-$(date +%Y%m%d-%H%M%S)"
            mv "$link" "$keep" 2>/dev/null || return 0
            # Nothing is printed: user_home's callers capture its output as
            # the home path (the server's home_for reads stdout and stderr
            # together), and a line here became part of the path: the login
            # could not be found in "…/home\n[builderbot] claude: …". The
            # renamed original beside the link is the record, and the docs
            # say what it is.
        else
            rmdir "$link" 2>/dev/null || return 0
        fi
    fi
    ln -s "$target" "$link" 2>/dev/null || true
}

# ---- a working tree per session (roadmap #24) -------------------------------
#
# Two Claude sessions in ONE directory is the thing this avoids, and file-level
# coordination cannot: /workspace/<project> is one working tree, so `git add -A
# && git commit` commits the other session's half-finished work, checkout and
# stash delete it, and both share one dist/ and one dev instance. Those are the
# failures that lose work. A worktree each makes them impossible (separate
# files, separate commits, separate builds) and puts the conflicts where git
# is actually good at them, which is the merge.
#
# THE OWNER KEEPS THE PROJECT DIRECTORY. Same rule as their home and their
# session names, and for the same reason: a box with one operator is every box
# until somebody adds a second account, and it should be untouched by this.
# It also makes the answer STATIC: a session's directory never depends on who
# happened to start first, which a first-come rule would have made a race.
#
# What a worktree session does not get, and the UI says so: its dist/ is its
# own, so the Artifacts tab (which reads the project directory) does not show
# its builds, and the dev instance belongs to the project rather than to it.
BB_WORKTREES="${BB_WORKTREES:-${WORKSPACE:-/workspace}/.worktrees}"

# A dot directory on purpose: project_list and both its siblings skip those, so
# a worktree can never be mistaken for a project, land on the sibling deny list
# or appear in the picker.

# session_dir PROJECT UID: where that account's session on that project works.
#
# Prints the path. The project's own directory for the owner and for no account
# at all; a worktree for anybody else, made on first use and reused after, so
# somebody coming back to a project finds the branch they left.
session_dir() {
    local proj="${1:-}" uid="${2:-}" src="${WORKSPACE:-/workspace}/$1" wt branch
    [ -d "$src" ] || { printf '%s' "$src"; return 0; }
    case "$uid" in
        u_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
        *) printf '%s' "$src"; return 0 ;;
    esac
    # THE TREE RULE IS THE SAME ON BOTH MACHINES, unlike the home and the
    # session names: the project directory is on the share, so the owner
    # working in it from the node is the owner working in it, and, since a
    # bound project's sessions run on one machine at a time, nobody is in
    # it from the other. It has to be the same, or the transcript slug (the
    # directory's path) would differ per machine and roadmap #24's shared
    # transcripts would not line up. A node has no users.json to say who the
    # owner is, so the controller says it in the terminal's URL (owner:1)
    # and bb-tty exports BB_TREE_OWNER.
    if [ "$uid" = "${BB_OWNER_UID:-$(owner_uid)}" ] \
       || { on_node && [ "${BB_TREE_OWNER:-}" = 1 ] && [ "${BB_ACCOUNT_UID:-}" = "$uid" ]; }; then
        printf '%s' "$src"; return 0
    fi
    # Not a git repo: there is no worktree to make, and refusing would be worse
    # than sharing: a directory nobody can branch is one nobody can conflict
    # in through git either.
    git -C "$src" rev-parse --git-dir >/dev/null 2>&1 || { printf '%s' "$src"; return 0; }
    wt="$BB_WORKTREES/$proj/$uid"
    if [ -d "$wt" ]; then printf '%s' "$wt"; return 0; fi
    branch="claude/$(account_name "$uid" || printf '%s' "$uid")"
    mkdir -p "$(dirname "$wt")" 2>/dev/null || { printf '%s' "$src"; return 0; }
    # An existing branch is checked out rather than recreated: this is somebody
    # returning to work they left, and -b on a branch that exists fails.
    if git -C "$src" show-ref --verify --quiet "refs/heads/$branch"; then
        git -C "$src" worktree add "$wt" "$branch" >/dev/null 2>&1 \
            || { printf '%s' "$src"; return 0; }
    else
        git -C "$src" worktree add -b "$branch" "$wt" >/dev/null 2>&1 \
            || { printf '%s' "$src"; return 0; }
    fi
    printf '%s' "$wt"
}

# account_name UID: the account's name, for a branch a person has to read.
account_name() {
    # On a node there is no store to ask, so bb-tty exports the name the
    # controller stamped into the terminal's argument beside the id
    # (BB_ACCOUNT_NAME), and that is the answer for that one account. Any
    # other id (there should be none) falls back to the id itself.
    if [ -n "${BB_ACCOUNT_NAME:-}" ] && [ "${BB_ACCOUNT_UID:-}" = "$1" ]; then
        printf '%s' "$BB_ACCOUNT_NAME"; return 0
    fi
    local f="${DASHBOARD_STATE:-/config}/users.json"
    [ -r "$f" ] || return 1
    jq -er --arg u "$1" 'first((.users // {}) | to_entries[]
                         | select(.value.uid == $u) | .key)' "$f" 2>/dev/null
}
