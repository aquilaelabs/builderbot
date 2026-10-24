#!/usr/bin/env bash
# shellcheck shell=bash
#
# The controller's boot, as steps (R90 step 3).
#
# Two things start a controller: scripts/entrypoint.sh in the container, under
# tini, and scripts/host-boot.sh on a machine installed bare metal, under
# systemd. Both run as root, do the same steps in the same order, and then
# hand off to the supervisor as the controller's account. The steps are
# here, once; what only the container does (remapping `builder` to
# PUID/PGID, the timezone, gosu) stays in the entrypoint, and what only a
# bare-metal install does (its account, setpriv) in host-boot.sh.
#
# What a step takes from its caller, set before this is sourced:
#   BB_ACCOUNT    the controller's account (builder in the image)
#   PUID / PGID   that account's ids
#   BB_DROP       how a step runs something as that account: gosu (the
#                 image's) or setpriv (util-linux, on any distribution)
#   BB_SECRETS_DIR  the root-only folder of *.env files and ssh/ keys
#                 (/secrets, a mount, in the container)
# and the paths every script reads: BUILDER_HOME, WORKSPACE, DASHBOARD_STATE.
#
# Sourced after lib/common.sh, whose log, warn and die these use.

BB_ACCOUNT="${BB_ACCOUNT:-builder}"
BB_DROP="${BB_DROP:-gosu}"
BB_SECRETS_DIR="${BB_SECRETS_DIR:-/secrets}"
# Root's own: the stash, the redaction table, the agent that holds the keys.
# The same folder on both installs, since deploy-key names it; another one
# only for the unit tests, which run as nobody's root.
BB_RUN_DIR="${BB_RUN_DIR:-/run/builderbot}"

# Shield secrets from the builder user (and therefore from Claude sessions).
#
# Values arrive as $BB_SECRETS_DIR/*.env files (a root-owned mount), or as
# container variables someone set by hand. Either way they are turned into
# log-redaction rules and scrubbed from the environment every builder process
# inherits, always: there is no switch (SHIELD_SECRETS went with b218077).
# The publishing tokens a shell on the controller uses; a git token is a
# project's own, and a runner's is typed on the Nodes tab.
# INSTALL_KEY seals at rest what the install keeps that would open something
# (R135; R111 began it with the signing keys): handed to the dashboard as a
# file of its own in /run below, never kept in /config. SIGNING_SECRET, its
# name before 0.8.0, is read when it is not set, for this release.
SECRET_VARS=(NPM_TOKEN UV_PUBLISH_TOKEN INSTALL_KEY SIGNING_SECRET)

# The one secret the dashboard itself needs, the install key, as a file only
# the controller's account reads, in /run (never the state, so a copy of the
# state holds nothing that opens what is sealed there), written fresh each
# start. On a bare-metal install it is among what the wall covers (R90).
install_key_file() {
    local f=/run/builderbot-key key="${INSTALL_KEY:-}"
    rm -f "$f" /run/builderbot-signing
    if [ -z "$key" ] && [ -n "${SIGNING_SECRET:-}" ]; then
        key="$SIGNING_SECRET"
        warn "SIGNING_SECRET is INSTALL_KEY now: rename it in your secrets folder, since the old name is read for this release only"
    fi
    [ -n "$key" ] || return 0
    if [ "${#key}" -lt 16 ]; then
        warn "INSTALL_KEY is shorter than 16 characters, so nothing is sealed: openssl rand -hex 32 makes one"
        return 0
    fi
    ( umask 077; printf '%s' "$key" > "$f" )
    chown "$BB_ACCOUNT" "$f" 2>/dev/null || true
}

# as_account CMD...: CMD as the controller's account, with its groups. gosu
# where the image has it; setpriv, which every distribution's util-linux
# carries, on a machine installed bare metal.
as_account() {
    if [ "$BB_DROP" = setpriv ]; then
        setpriv --reuid="$BB_ACCOUNT" --regid="$PGID" --init-groups "$@"
    else
        gosu "$BB_ACCOUNT" "$@"
    fi
}

stash_secrets() {
    mkdir -p "$BB_RUN_DIR"
    chmod 700 "$BB_RUN_DIR"

    # $BB_SECRETS_DIR/*.env can define or override any secret var.
    if [ -d "$BB_SECRETS_DIR" ]; then
        local f
        for f in "$BB_SECRETS_DIR"/*.env; do
            [ -e "$f" ] || continue
            set -a
            # shellcheck disable=SC1090
            . "$f"
            set +a
        done
    fi

    local stash="$BB_RUN_DIR/secrets.env" redact="$BB_RUN_DIR/redact.sed"
    : > "$stash";  chmod 600 "$stash"
    : > "$redact"; chmod 600 "$redact"

    # Pattern rules: catch well-known token shapes wherever they appear.
    cat >> "$redact" <<'SED'
s/gh[pousr]_[A-Za-z0-9]\{8,\}/[REDACTED]/g
s/github_pat_[A-Za-z0-9_]\{20,\}/[REDACTED]/g
s/sk-ant-[A-Za-z0-9_-]\{8,\}/[REDACTED]/g
s/npm_[A-Za-z0-9]\{16,\}/[REDACTED]/g
s/eyJ[A-Za-z0-9_-]\{20,\}\.[A-Za-z0-9._-]\{10,\}/[REDACTED]/g
SED

    local var val esc found=0 names=""
    for var in "${SECRET_VARS[@]}"; do
        val="${!var:-}"
        [ -n "$val" ] || continue
        printf '%s=%q\n' "$var" "$val" >> "$stash"
        # Literal-value redaction rule (skip short strings).
        if [ "${#val}" -ge 8 ]; then
            found=$((found + 1))
            names="${names:+$names,}${var}"
            esc="$(printf '%s' "$val" | sed -e 's/[&/\]/\\&/g' -e 's/[][^$.*]/\\&/g')"
            printf 's/%s/[REDACTED]/g\n' "$esc" >> "$redact"
        fi
    done

    # Say plainly what was and wasn't found: a missing /secrets mount or a
    # misnamed file used to fail silently, leaving "no runner credential" in
    # bb doctor with nothing in the log to explain it.
    if [ "$found" -gt 0 ]; then
        log "secrets: loaded ${found} value(s) [${names}]"
    elif [ -d "$BB_SECRETS_DIR" ]; then
        warn "secrets: ${BB_SECRETS_DIR} is there but no values loaded: expected files named *.env containing e.g. NPM_TOKEN=..."
    else
        log "secrets: no ${BB_SECRETS_DIR} and no secret variables set"
    fi
}

# Shielded SSH keys: private keys dropped in $BB_SECRETS_DIR/ssh (root-only),
# and the deploy keys made or pasted in a project's settings (deploy-key,
# under the state's deploy-keys), are loaded into a root-owned ssh-agent.
# Builder processes get only the agent socket (SSH_AUTH_SOCK, baked into the
# image's env and set by a bare-metal install's env file), so git/ssh can
# *use* the keys (the agent signs on their behalf), but no session can ever
# read the private key material itself.
setup_ssh_agent() {
    local keydir="$BB_SECRETS_DIR/ssh"
    local user_sock="${SSH_AUTH_SOCK:-/run/ssh-agent.sock}"
    local root_sock="$BB_RUN_DIR/ssh-agent.sock"
    local k added=0

    # Started whether or not the ssh folder is there: a deploy key made in a
    # project's settings needs the agent running to be loaded into.
    command -v ssh-agent >/dev/null 2>&1 || { warn "ssh-agent not available"; return 0; }

    mkdir -p "$BB_RUN_DIR"
    chmod 700 "$BB_RUN_DIR"
    rm -f "$root_sock" "$user_sock"

    # The agent itself lives in the root-only directory and holds the keys.
    ssh-agent -a "$root_sock" >/dev/null

    for k in "$keydir"/*; do
        [ -d "$keydir" ] || break
        [ -f "$k" ] || continue
        grep -q 'PRIVATE KEY' "$k" 2>/dev/null || continue
        # ssh-add refuses group/world-readable keys; the mount is root-only
        # but a sloppy chmod on the host shouldn't break startup silently.
        if SSH_AUTH_SOCK="$root_sock" ssh-add "$k" >/dev/null 2>&1; then
            added=$((added + 1))
        else
            warn "could not load ssh key $(basename "$k") (bad perms or passphrase-protected?)"
        fi
    done

    added=$((added + $(/opt/builderbot/scripts/deploy-key --load 2>/dev/null || echo 0)))

    # ssh-agent rejects any client whose uid differs from its own (root is the
    # sole exception), so the builder user cannot talk to it directly no matter
    # how the socket is chowned; sessions would see an empty agent while the
    # keys sat loaded and usable only by root.
    #
    # Bridge it with a root-owned socat proxy. The agent sees root as the peer
    # and accepts; the builder-facing socket carries only agent-protocol
    # requests, which can sign but by design can never export a private key.
    # Because the proxy runs as root, the builder user cannot ptrace it to read
    # key material out of memory either.
    if ! command -v socat >/dev/null 2>&1; then
        warn "socat is missing: sessions cannot reach the root-owned agent, so"
        warn "the shielded keys will be unusable. Use ~/.ssh, or give the"
        warn "project a token in the dashboard's clone dialog instead."
        return 0
    fi

    socat "UNIX-LISTEN:${user_sock},fork,unlink-early,mode=0600,user=${PUID},group=${PGID}" \
          "UNIX-CONNECT:${root_sock}" >/dev/null 2>&1 &

    # Give socat a moment to create the socket so the first hook that uses git
    # does not race it.
    local waited=0
    while [ ! -S "$user_sock" ] && [ "$waited" -lt 50 ]; do
        sleep 0.1
        waited=$((waited + 1))
    done

    if [ -S "$user_sock" ]; then
        log "ssh-agent: ${added} shielded key(s) loaded; sessions can use them, not read them; a project's settings can add a deploy key"
    else
        warn "ssh-agent proxy failed to start; shielded keys will be unusable"
    fi
}

# Mirror everything this boot prints into a persistent file in the state's
# logs, so startup output survives container recreation (which happens on
# every image update, exactly when you want yesterday's log). Docker's own
# `docker logs`, and the journal on a bare-metal install, keep working: tee
# passes output through.
# rotate_log FILE: shift generations down and leave FILE free for a new one.
# Rotating per start rather than per size means one file equals one container
# lifetime, so "what happened on that boot" is answerable by opening a file
# instead of hunting for the boundary in an appended stream. The cost is that a
# crash loop burns through generations quickly, which is what the ceiling of
# 60 is for (logs.MAX_GENERATIONS, the same number): not the policy. How long logs are actually kept is a
# number of DAYS, set in the dashboard's settings menu and applied by
# dashboard/logs.py: a count is the wrong unit for "was that this week?", and
# five generations of a crash loop is five minutes.
rotate_log() {
    local logfile="$1" keep=60 i             # a ceiling, constant since R29
    case "$keep" in
        ''|*[!0-9]*) keep=5 ;;
    esac
    if [ "$keep" -lt 1 ]; then
        keep=1
    fi
    [ -f "$logfile" ] || return 0

    rm -f "${logfile}.${keep}"
    i=$((keep - 1))
    while [ "$i" -ge 1 ]; do
        if [ -f "${logfile}.${i}" ]; then
            mv -f "${logfile}.${i}" "${logfile}.$((i + 1))"
        fi
        i=$((i - 1))
    done
    mv -f "$logfile" "${logfile}.1"
}

setup_logging() {
    local logdir logfile f
    logdir="$(bb_log_dir)"
    logfile="$logdir/builderbot.log"
    mkdir -p "$logdir" 2>/dev/null || return 0
    # All four, so one file means one container lifetime for every stream
    # rather than only for this one. The other three used to be appended to
    # forever, which made "what did docker do on that boot" unanswerable and
    # left dashboard.log growing without limit.
    for f in builderbot.log dashboard.log docker.log ttyd.log; do
        rotate_log "$logdir/$f"
    done
    # All output (the persistent file AND the docker-logs passthrough)
    # flows through the redaction rules built by stash_secrets.
    if [ -s "$BB_RUN_DIR/redact.sed" ]; then
        exec > >(sed -u -f "$BB_RUN_DIR/redact.sed" | tee -a "$logfile") 2>&1
    else
        exec > >(tee -a "$logfile") 2>&1
    fi
    log "===== ${BOOT_WHAT:-container} start $(date -Is), logging to ${logfile} ====="
}

# Append this build to the ledger, unless it is already the last line.
#
# Deduplicated on the stamp rather than written per boot: a restart is not
# news, a different image is. A rollback appends too, which is the point: the
# question this answers is "what was the box running on Tuesday", and pointing
# the Repository field back at an older tag is one of the ways the answer
# stops being obvious.
#
# Best-effort throughout: a container started without a /config volume should
# lose the ledger, not the boot.
record_image() {
    local f rev ver built line last
    f="$(bb_image_log)"
    rev="${BB_IMAGE_REV:-unstamped}"
    ver="${BB_VERSION:-unstamped}"
    built="${BB_IMAGE_BUILT:--}"
    mkdir -p "$(dirname "$f")" 2>/dev/null || return 0
    line="$(date -Is)"$'\t'"$rev"$'\t'"$ver"$'\t'"$built"
    if [ -s "$f" ]; then
        # Fields 2-4 only: field 1 is when this image was FIRST seen, and
        # comparing it would append a line on every boot.
        last="$(tail -1 "$f" 2>/dev/null || true)"
        [ "$(printf '%s' "$last" | cut -f2-4)" = "$(printf '%s' "$line" | cut -f2-4)" ] \
            && return 0
    else
        printf '# first-seen\trev\tversion\tbuilt\n' > "$f" 2>/dev/null || return 0
    fi
    printf '%s\n' "$line" >> "$f" 2>/dev/null || return 0
    # The newest 500 images, which is years of updates: it was never trimmed.
    if [ "$(wc -l < "$f")" -gt 501 ]; then
        { head -1 "$f"; tail -n 500 "$f"; } > "$f.tmp" 2>/dev/null && mv -f "$f.tmp" "$f"
    fi
    # Everything else in /config belongs to the builder; keep this the same so
    # a later reader is not the one to find out it is root's.
    chown "${PUID:-99}:${PGID:-100}" "$f" 2>/dev/null || true
    log "image changed: ${rev:0:7} (${ver}), recorded in ${f}"
}

banner() {
    cat <<'EOF'
  ___        _  _     _            ___       _
 | _ ) _  _ (_)| | __| | ___  _ _ | _ ) ___ | |_
 | _ \| || || || |/ _` |/ -_)| '_|| _ \/ _ \|  _|
 |___/ \_,_||_||_|\__,_|\___||_|  |___/\___/ \__|
  Claude Code workstation + GitHub Actions runner
EOF
}

seed_home() {
    mkdir -p "$BUILDER_HOME"
    # Copy skeleton entries the (usually volume-mounted) home is missing.
    # -n means existing files are never clobbered, so your Claude Code
    # credentials and settings survive an image upgrade.
    if [ -d /opt/builderbot/skel ]; then
        cp -rn /opt/builderbot/skel/. "$BUILDER_HOME"/ 2>/dev/null || true
    fi

    mkdir -p \
        "$BUILDER_HOME/.claude" \
        "$BUILDER_HOME/.npm-global" \
        "$BUILDER_HOME/.local/bin" \
        "$BUILDER_HOME/.ssh" \
        "$BUILDER_HOME/.cache" \
        "$WORKSPACE"
    chmod 700 "$BUILDER_HOME/.ssh"

    # Recursed only when the top of the tree is not already the account's:
    # a home of gigabytes was walked on every start (B283). That check is
    # the whole switch; the CHOWN_HOME variable that also skipped it is gone.
    # A share that will not let root change owners (NFS squashing root, some
    # NAS shares) is said and survived: under set -e this chown restarted
    # the container forever with nothing in the log saying why (B122).
    if [ "$(stat -c %u:%g "$BUILDER_HOME" 2>/dev/null)" != "$PUID:$PGID" ]; then
        chown -R "$PUID:$PGID" "$BUILDER_HOME" 2>/dev/null \
            || warn "$BUILDER_HOME could not be made ${PUID}:${PGID}: chown the folder mounted there on the host"
    fi
    # ...and what this function made itself, always: a home already the
    # account's (a folder chowned as the install says, whose owner is the
    # image's own 1000:1000) skipped the recursion, and these stayed root's,
    # so no hook could write ~/.ssh or ~/.cache on a first start (B120).
    chown "$PUID:$PGID" "$BUILDER_HOME/.claude" "$BUILDER_HOME/.npm-global" \
        "$BUILDER_HOME/.local" "$BUILDER_HOME/.local/bin" "$BUILDER_HOME/.ssh" \
        "$BUILDER_HOME/.cache" 2>/dev/null || true
    for f in "$BUILDER_HOME"/.bashrc "$BUILDER_HOME"/.profile; do
        [ "$(stat -c %u "$f" 2>/dev/null)" = 0 ] && { chown "$PUID:$PGID" "$f" 2>/dev/null || true; }
    done
    # /config is BuilderBot's own state, never a share: one Docker made for a
    # missing host path, or a new named volume, is root's, and the dashboard,
    # which runs as the account, could keep nothing in it (B120). Only its
    # top: what root keeps in it on purpose (runner tokens, signing keys,
    # git credentials) stays root's.
    local state="${DASHBOARD_STATE:-/config}"
    [ "$(stat -c %u:%g "$state" 2>/dev/null)" = "$PUID:$PGID" ] \
        || chown "$PUID:$PGID" "$state" 2>/dev/null || true
    run_as_builder test -w "$state" \
        || warn "$state is not writable by ${PUID}:${PGID}: nothing can be saved, not even the first account, until the folder mounted there is chowned ${PUID}:${PGID} on the host"
    # Make the persistent log readable/rotatable from the share.
    [ "$(stat -c %u:%g "$(bb_log_dir)" 2>/dev/null)" = "$PUID:$PGID" ] \
        || chown -R "$PUID:$PGID" "$(bb_log_dir)" 2>/dev/null || true
    # The workspace root is only ours to chown when it is a directory this
    # container made. Mounted, it is the host's projects share, and quietly
    # changing the ownership of somebody's share because a container started is
    # not a repair; it is a surprise. The Projects card reports it instead.
    if is_mountpoint "$WORKSPACE"; then
        run_as_builder test -w "$WORKSPACE" \
            || warn "$WORKSPACE is not writable by ${PUID}:${PGID}: new projects cannot be created there (chown it on the host)"
    else
        chown "$PUID:$PGID" "$WORKSPACE" 2>/dev/null || true
    fi
    # Project folders are left alone: a recursive chown across a share is
    # slow and hard to undo, and the Projects card names a folder whose
    # ownership is wrong. (CHOWN_PROJECTS, which did it on every boot, is gone.)
}

# The Android SDK lives in the image at /opt, so anything sdkmanager installs
# at runtime is thrown away by the next image update, and with a weekly
# rebuild that means re-downloading gigabytes on a schedule. Every directory
# that is purely downloaded content moves out to a store that persists and is
# symlinked back into place, so sdkmanager, Gradle and Android Studio all
# install to the store without knowing it.
#
# Which store: the toolchain store when one is mapped, the home volume otherwise.
# The choice is made per directory, and deliberately conservative: a
# directory that already holds gigabytes on the home volume keeps pointing
# there, because silently retargeting the link would make an existing 30GB
# library vanish from every tool that uses it. New directories, and empty
# ones, go straight to the share. Consolidating the two is a host-side move
# of the folder, which needs no cooperation from in here.
persist_android_downloads() {
    local sdk="${ANDROID_HOME:-/opt/android-sdk}"
    local home_root="$BUILDER_HOME/.sdk"
    local share; share="$(sdk_root)/android"
    local sub store cand dir name adopted=0 nudge=0

    [ -d "$sdk" ] || return 0
    mkdir -p "$share" 2>/dev/null || true

    # build-tools and the emulator join the list the moment they stop being
    # baked into the image: they are downloads like any other, and the
    # emulator alone is 800MB of every pull.
    for sub in system-images platforms build-tools emulator ndk cmake \
               extras add-ons sources skins; do
        # The share first, then the home volume's own toolchain store root (where packages
        # land when no share is mapped). Whichever actually holds packages
        # wins, so a library that exists is never hidden behind an empty
        # directory somewhere else, the one failure mode that matters here,
        # because "hidden" looks exactly like "gone" to Gradle.
        store=""
        for cand in "$share/$sub" "$home_root/android/$sub"; do
            if [ -d "$cand" ] && [ -n "$(ls -A "$cand" 2>/dev/null)" ]; then
                store="$cand"; break
            fi
        done
        [ -n "$store" ] || store="$share/$sub"   # nothing anywhere yet
        [ "$store" = "$share/$sub" ] || nudge=1
        mkdir -p "$store"

        # Adopt whatever the image shipped before replacing the directory, or
        # the baked-in system image disappears the moment the symlink lands.
        # -e rather than a copy each time: these are immutable once downloaded.
        if [ -d "$sdk/$sub" ] && [ ! -L "$sdk/$sub" ]; then
            for dir in "$sdk/$sub"/*/; do
                [ -d "$dir" ] || continue
                name="$(basename "$dir")"
                if [ -e "$store/$name" ]; then
                    continue
                fi
                # Gigabytes, on the first start after an image ships a new one.
                # Announce it rather than looking hung.
                log "adopting ${sub}/${name} onto the home volume"
                cp -a "$dir" "$store/$name"
                adopted=1
            done
            rm -rf "${sdk:?}/$sub"
        fi

        if ! ln -sfn "$store" "$sdk/$sub"; then
            warn "could not link ${sdk}/${sub} to ${store}"
            warn "runtime sdkmanager installs will not survive the next image update"
        fi
    done

    if [ "$adopted" -eq 1 ]; then
        log "android sdk downloads persist outside the image"
    fi
    if [ "$nudge" -eq 1 ]; then
        # Nothing is broken (the links point at the packages wherever they
        # are), so this is information, not an instruction. Moving them is a
        # host-side `mv` into the toolchain store and a restart; the container has
        # no better way to do it than the operator does, and doing tens of GB
        # of copying from in here without being asked would be worse.
        log "some SDK packages still live on the home volume rather than the share."
        log "They work as they are. To consolidate: stop the container, move"
        log "them into the toolchain store on the host, and start it again."
    fi

    chown -R "$PUID:$PGID" "$share" 2>/dev/null || true
    return 0
}

# How long each hook took, and how far into the boot it started.
#
# The dashboard is a hook like any other, so everything before it is time the
# operator spends looking at a browser that will not connect, and until this,
# the log said which hooks ran and nothing about which one was the wait. A
# guess about that is worth nothing; nine hooks run before the web UI and any
# of them could be the one.
#
# SECONDS is bash's own counter, reset at the top of the boot, so both numbers
# come free.
run_hooks() {
    local dir script started took name
    for dir in /opt/builderbot/scripts/startup.d "${DASHBOARD_STATE:-/config}/startup.d"; do
        [ -d "$dir" ] || continue
        for script in "$dir"/*.sh; do
            [ -e "$script" ] || continue
            name="$(basename "$script")"
            case "$script" in
                *.disabled.sh)
                    log "skipping $name (disabled)"
                    continue
                    ;;
            esac
            # A root hook needs root: started as another user they ran
            # anyway and failed, while the start said root hooks were
            # skipped (diag report #120). Now skipped, as said.
            if [ "$(id -u)" -ne 0 ] && [[ "$script" == *.root.sh ]]; then
                log "skipping $name (needs root, and this container is not)"
                continue
            fi
            chmod +x "$script" 2>/dev/null || true
            started=$SECONDS
            if [ "$(id -u)" -ne 0 ]; then
                log "hook: $name (+${started}s)"
                "$script" || warn "hook $name exited $?"
            elif [[ "$script" == *.root.sh ]]; then
                log "hook (root): $name (+${started}s)"
                "$script" || warn "hook $name exited $?"
            else
                log "hook: $name (+${started}s)"
                as_account env HOME="$BUILDER_HOME" "$script" \
                    || warn "hook $name exited $?"
            fi
            took=$(( SECONDS - started ))
            # Only when it is worth reading. A hook that finishes inside a
            # second is not the one anybody is waiting for, and a line per
            # hook saying "0s" is noise over the ones that matter.
            [ "$took" -ge 1 ] && log "  ...$name took ${took}s"
        done
    done
}

# The finish line, for anything a hook started that is now measuring a
# controller it was itself part of building, the dashboard's doctor above
# all. World-readable: it is read by the builder user.
# Braced: bash performs the redirections left to right and reports a failed
# one itself, so `: > file 2>/dev/null` still prints "Permission denied".
boot_ready() {
    if { : > "$BOOT_READY_FILE"; } 2>/dev/null; then
        chmod 644 "$BOOT_READY_FILE" 2>/dev/null || true
    fi
}

# The state's version, before anything writes to it (R79): a state a newer
# build wrote, or one older than this build migrates from, stops the boot
# here with the one sentence saying what to do, and the logs it would rotate
# are left as they are. The dashboard asks again.
state_gate() {
    python3 /opt/builderbot/scripts/dashboard/stateversion.py check "${DASHBOARD_STATE:-/config}" \
        || die "${DASHBOARD_STATE:-/config} is not one this build may start on; nothing was changed"
}

# Build the command the boot will exec, honoring the container CMD.
resolve_command() {
    case "${1:-supervise}" in
        supervise) printf '%s\0' /opt/builderbot/scripts/supervisor.sh ;;
        shell|bash)
            # Bare `bash`/`shell` means "give me a login shell"; anything with
            # arguments (e.g. `bash -c '...'`) must run verbatim.
            if [ "$#" -le 1 ]; then
                printf '%s\0' bash -l
            else
                printf '%s\0' "$@"
            fi
            ;;
        *) printf '%s\0' "$@" ;;
    esac
}
