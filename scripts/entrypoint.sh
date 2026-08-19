#!/usr/bin/env bash
#
# BuilderBot entrypoint.
#
#   1. remap the `builder` user to PUID/PGID so files written into your Unraid
#      shares come out owned by the right account
#   2. seed the home volume from the image skeleton
#   3. run every startup hook in scripts/startup.d and /config/startup.d
#   4. hand off to the supervisor (GitHub runner in the background, container
#      stays alive so you can `docker exec` in and run Claude Code)
#
set -euo pipefail

# shellcheck source=lib/common.sh
. /opt/builderbot/scripts/lib/common.sh

PUID="${PUID:-99}"
PGID="${PGID:-100}"

# Shield secrets from the builder user (and therefore from Claude sessions).
#
# Values may arrive as container env vars or as /secrets/*.env files (a
# root-owned mount — the fully shielded path, since env vars remain visible
# to `docker exec`'d processes no matter what we do here). Either way they
# are stashed into a root-only file for the mint-runner-token helper, turned
# into log-redaction rules, and — when SHIELD_SECRETS is on — scrubbed from
# the environment every builder process inherits.
# Values stashed for the root helper and registered for log redaction.
# GIT_PAT is deliberately NOT in the scrub list below: git and gh must be able
# to use it from inside a session, and any credential a session's git can
# authenticate with is a credential that session can read. Scope GIT_PAT to
# repository Contents only — Claude already has read/write on the mounted
# working trees, so a contents-scoped token grants it nothing new, while the
# Administration scope that manages runners stays shielded in GITHUB_PAT.
SECRET_VARS=(GITHUB_PAT GIT_PAT RUNNER_TOKEN ANTHROPIC_API_KEY NPM_TOKEN UV_PUBLISH_TOKEN)

stash_secrets() {
    mkdir -p /run/builderbot
    chmod 700 /run/builderbot

    # /secrets/*.env can define or override any secret var.
    if [ -d /secrets ]; then
        local f
        for f in /secrets/*.env; do
            [ -e "$f" ] || continue
            set -a
            # shellcheck disable=SC1090
            . "$f"
            set +a
        done
    fi

    local stash=/run/builderbot/secrets.env redact=/run/builderbot/redact.sed
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
    for var in "${SECRET_VARS[@]}" GITHUB_URL; do
        val="${!var:-}"
        [ -n "$val" ] || continue
        printf '%s=%q\n' "$var" "$val" >> "$stash"
        # Literal-value redaction rule (skip short strings and the non-secret
        # GITHUB_URL).
        if [ "$var" != "GITHUB_URL" ] && [ "${#val}" -ge 8 ]; then
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
    elif [ -d /secrets ]; then
        warn "secrets: /secrets is mounted but no values loaded — expected files named *.env containing e.g. GITHUB_PAT=..."
    else
        log "secrets: no /secrets mount and no secret variables set"
    fi

    if is_true "${SHIELD_SECRETS:-true}"; then
        # The runner gets tokens through the sudo helper; nothing running as
        # builder needs the raw PAT. Claude-facing tools DO need their own
        # credentials (ANTHROPIC_API_KEY, NPM_TOKEN), so those stay.
        unset GITHUB_PAT RUNNER_TOKEN
        log "secrets shielded: GITHUB_PAT/RUNNER_TOKEN removed from the session environment"
    fi
}

# Shielded SSH keys: private keys dropped in /secrets/ssh (root-only mount)
# are loaded into a root-owned ssh-agent. Builder processes get only the
# agent socket (SSH_AUTH_SOCK is baked into the image env), so git/ssh can
# *use* the keys — the agent signs on their behalf — but no session can ever
# read the private key material itself.
setup_ssh_agent() {
    local keydir=/secrets/ssh
    local user_sock="${SSH_AUTH_SOCK:-/run/ssh-agent.sock}"
    local root_sock=/run/builderbot/ssh-agent.sock
    local k added=0

    [ -d "$keydir" ] || return 0
    command -v ssh-agent >/dev/null 2>&1 || { warn "ssh-agent not available"; return 0; }

    mkdir -p /run/builderbot
    chmod 700 /run/builderbot
    rm -f "$root_sock" "$user_sock"

    # The agent itself lives in the root-only directory and holds the keys.
    ssh-agent -a "$root_sock" >/dev/null

    for k in "$keydir"/*; do
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

    if [ "$added" -eq 0 ]; then
        warn "no usable keys in ${keydir}; ssh-agent left empty"
        rm -f "$root_sock"
        return 0
    fi

    # ssh-agent rejects any client whose uid differs from its own (root is the
    # sole exception), so the builder user cannot talk to it directly no matter
    # how the socket is chowned — sessions would see an empty agent while the
    # keys sat loaded and usable only by root.
    #
    # Bridge it with a root-owned socat proxy. The agent sees root as the peer
    # and accepts; the builder-facing socket carries only agent-protocol
    # requests, which can sign but by design can never export a private key.
    # Because the proxy runs as root, the builder user cannot ptrace it to read
    # key material out of memory either.
    if ! command -v socat >/dev/null 2>&1; then
        warn "socat is missing — sessions cannot reach the root-owned agent, so"
        warn "the shielded keys will be unusable. Set GIT_PAT or use ~/.ssh instead."
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
        log "ssh-agent: ${added} shielded key(s) loaded — sessions can use them, not read them"
    else
        warn "ssh-agent proxy failed to start; shielded keys will be unusable"
    fi
}

# Mirror everything this container prints into a persistent file on the
# /config volume, so startup output survives container recreation (which
# happens on every image update — exactly when you want yesterday's log).
# Docker's own `docker logs` keeps working: tee passes output through.
# rotate_log FILE — shift generations down and leave FILE free for a new one.
# Rotating per start rather than per size means one file equals one container
# lifetime, so "what happened on that boot" is answerable by opening a file
# instead of hunting for the boundary in an appended stream. The cost is that a
# crash loop burns through generations quickly; BB_LOG_KEEP buys headroom.
rotate_log() {
    local logfile="$1" keep="${BB_LOG_KEEP:-5}" i
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
    local logdir logfile
    logdir="$(bb_log_dir)"
    logfile="$logdir/builderbot.log"
    mkdir -p "$logdir" 2>/dev/null || return 0
    rotate_log "$logfile"
    # All output — the persistent file AND the docker-logs passthrough —
    # flows through the redaction rules built by stash_secrets.
    if [ -s /run/builderbot/redact.sed ]; then
        exec > >(sed -u -f /run/builderbot/redact.sed | tee -a "$logfile") 2>&1
    else
        exec > >(tee -a "$logfile") 2>&1
    fi
    log "===== container start $(date -Is) — logging to ${logfile} ====="
}

banner() {
    cat <<'EOF'
  ___      _ _   _         ___      _
 | _ )_  _(_) |_| |___ _ _| _ ) ___| |_
 | _ \ || | | / _` / -_) '_| _ \/ _ \  _|
 |___/\_,_|_|_\__,_\___|_| |___/\___/\__|
  Claude Code workstation + GitHub Actions runner
EOF
}

setup_timezone() {
    if [ -n "${TZ:-}" ] && [ -f "/usr/share/zoneinfo/${TZ}" ]; then
        ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime
        echo "${TZ}" > /etc/timezone
        log "timezone set to ${TZ}"
    fi
}

remap_user() {
    local cur_uid cur_gid
    cur_uid="$(id -u builder)"
    cur_gid="$(id -g builder)"

    if [ "$cur_gid" != "$PGID" ]; then
        log "remapping group builder: ${cur_gid} -> ${PGID}"
        groupmod -o -g "$PGID" builder
    fi
    if [ "$cur_uid" != "$PUID" ]; then
        log "remapping user builder: ${cur_uid} -> ${PUID}"
        usermod -o -u "$PUID" -g "$PGID" builder
    fi

    # Give the builder access to the host Docker socket when one is mounted.
    if [ -S /var/run/docker.sock ]; then
        local sock_gid sock_group
        sock_gid="$(stat -c '%g' /var/run/docker.sock)"
        if ! getent group "$sock_gid" >/dev/null; then
            groupadd -g "$sock_gid" hostdocker
        fi
        sock_group="$(getent group "$sock_gid" | cut -d: -f1)"
        usermod -aG "$sock_group" builder
        log "builder added to '${sock_group}' for the host Docker socket (gid ${sock_gid})"
    fi

    # Same dance for /dev/kvm, which the Android emulator needs for hardware
    # acceleration (pass it in with --device=/dev/kvm).
    if [ -e /dev/kvm ]; then
        local kvm_gid kvm_group
        kvm_gid="$(stat -c '%g' /dev/kvm)"
        if [ "$kvm_gid" != "0" ]; then
            if ! getent group "$kvm_gid" >/dev/null; then
                groupadd -g "$kvm_gid" hostkvm
            fi
            kvm_group="$(getent group "$kvm_gid" | cut -d: -f1)"
            usermod -aG "$kvm_group" builder
            log "builder added to '${kvm_group}' for /dev/kvm (gid ${kvm_gid})"
        else
            chmod 666 /dev/kvm 2>/dev/null || true
            log "/dev/kvm opened for the emulator"
        fi
    fi
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
        "$WORKSPACE" \
        "${RUNNER_WORKDIR:-$WORKSPACE/_work}"
    chmod 700 "$BUILDER_HOME/.ssh"

    if is_true "${CHOWN_HOME:-true}"; then
        chown -R "$PUID:$PGID" "$BUILDER_HOME"
    fi
    # Make the persistent log readable/rotatable from the share.
    chown -R "$PUID:$PGID" "$(bb_log_dir)" 2>/dev/null || true
    # The workspace root is only ours to chown when it is a directory this
    # container made. Mounted, it is the host's projects share, and quietly
    # changing the ownership of somebody's share because a container started is
    # not a repair — it is a surprise. The Projects card reports it instead.
    if is_mountpoint "$WORKSPACE"; then
        run_as_builder test -w "$WORKSPACE" \
            || warn "$WORKSPACE is not writable by ${PUID}:${PGID} — new projects cannot be created there (chown it on the host)"
    else
        chown "$PUID:$PGID" "$WORKSPACE" 2>/dev/null || true
    fi
    chown "$PUID:$PGID" "${RUNNER_WORKDIR:-$WORKSPACE/_work}" 2>/dev/null || true
    chown -R "$PUID:$PGID" "$RUNNER_DIR" 2>/dev/null || true

    # Project mounts are deliberately left alone — a recursive chown across a
    # share is slow and hard to undo. Set CHOWN_PROJECTS=true to opt in.
    if is_true "${CHOWN_PROJECTS:-false}"; then
        local d
        for d in "$WORKSPACE"/*/; do
            [ -d "$d" ] || continue
            [ "$d" = "${RUNNER_WORKDIR:-$WORKSPACE/_work}/" ] && continue
            log "chown -R ${PUID}:${PGID} ${d}"
            chown -R "$PUID:$PGID" "$d"
        done
    fi
}

# The Android SDK lives in the image at /opt, so anything sdkmanager installs
# at runtime is thrown away by the next image update — and with a weekly
# rebuild that means re-downloading gigabytes of system images on a schedule.
# Move the expensive, purely-downloaded parts of the tree onto the home volume
# and symlink them back into place. Tools and build-tools stay in the image, so
# updates still deliver them.
persist_android_downloads() {
    local sdk="${ANDROID_HOME:-/opt/android-sdk}"
    local base="$BUILDER_HOME/.android/sdk"
    local sub store dir name adopted=0

    [ -d "$sdk" ] || return 0

    for sub in system-images platforms; do
        store="$base/$sub"
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
        log "android sdk downloads persist at ${base}"
    fi

    chown -R "$PUID:$PGID" "$base" 2>/dev/null || true
}

run_hooks() {
    local dir script
    for dir in /opt/builderbot/scripts/startup.d /config/startup.d; do
        [ -d "$dir" ] || continue
        for script in "$dir"/*.sh; do
            [ -e "$script" ] || continue
            case "$script" in
                *.disabled.sh)
                    log "skipping $(basename "$script") (disabled)"
                    continue
                    ;;
            esac
            chmod +x "$script" 2>/dev/null || true
            if [ "$(id -u)" -ne 0 ]; then
                log "hook: $(basename "$script")"
                "$script" || warn "hook $(basename "$script") exited $?"
            elif [[ "$script" == *.root.sh ]]; then
                log "hook (root): $(basename "$script")"
                "$script" || warn "hook $(basename "$script") exited $?"
            else
                log "hook: $(basename "$script")"
                gosu builder env HOME="$BUILDER_HOME" "$script" \
                    || warn "hook $(basename "$script") exited $?"
            fi
        done
    done
}

# Build the command that main() will exec, honoring the container CMD.
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

main() {
    local privileged=0
    [ "$(id -u)" -eq 0 ] && privileged=1

    # Stash + scrub before anything is logged or spawned.
    [ "$privileged" -eq 1 ] && stash_secrets
    setup_logging
    banner

    if [ "$privileged" -eq 1 ]; then
        setup_timezone
        remap_user
        seed_home
        persist_android_downloads
        setup_ssh_agent
    else
        warn "not running as root — skipping user remap, ownership fixes and root hooks"
    fi

    run_hooks

    local -a cmd=()
    mapfile -d '' -t cmd < <(resolve_command "$@")

    log "starting: ${cmd[*]}"
    if [ "$privileged" -eq 1 ]; then
        exec gosu builder env HOME="$BUILDER_HOME" USER=builder "${cmd[@]}"
    else
        exec env HOME="$BUILDER_HOME" "${cmd[@]}"
    fi
}

main "$@"
