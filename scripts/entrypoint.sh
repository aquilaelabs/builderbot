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
    chown "$PUID:$PGID" "$WORKSPACE" "${RUNNER_WORKDIR:-$WORKSPACE/_work}" 2>/dev/null || true
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

# Build the command that main() will exec, honouring the container CMD.
resolve_command() {
    case "${1:-supervise}" in
        supervise) printf '%s\0' /opt/builderbot/scripts/supervisor.sh ;;
        shell|bash) printf '%s\0' bash -l ;;
        *)          printf '%s\0' "$@" ;;
    esac
}

main() {
    banner

    local privileged=0
    [ "$(id -u)" -eq 0 ] && privileged=1

    if [ "$privileged" -eq 1 ]; then
        setup_timezone
        remap_user
        seed_home
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
