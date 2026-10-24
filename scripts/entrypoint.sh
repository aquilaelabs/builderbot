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
# The steps themselves are lib/boot.sh's, which a controller installed bare
# metal runs too (host-boot.sh, R90 step 3); remapping `builder`, the
# timezone and gosu are the container's, and stay here.
#
set -euo pipefail

# shellcheck source=lib/common.sh
. /opt/builderbot/scripts/lib/common.sh

PUID="${PUID:-99}"
PGID="${PGID:-100}"

# The container's account is the image's `builder`, reached through gosu.
export BB_ACCOUNT=builder
export BB_DROP=gosu
# shellcheck source=lib/boot.sh
. /opt/builderbot/scripts/lib/boot.sh

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

main() {
    local privileged=0
    [ "$(id -u)" -eq 0 ] && privileged=1

    # Stash + scrub before anything is logged or spawned.
    [ "$privileged" -eq 1 ] && stash_secrets
    # Before anything can read it: this boot is not ready yet, and the file may
    # be last boot's (see BOOT_READY_FILE in lib/common.sh). Tolerant of a
    # failure, here and at the other end: /run is root's, this script has a
    # documented unprivileged path, and `set -e` would turn "could not write a
    # hint file" into "the container does not start". What reads the marker
    # falls back to the container's age when it is missing.
    rm -f "$BOOT_READY_FILE" 2>/dev/null || true
    # /config's state version, before anything writes to it (R79).
    state_gate
    setup_logging
    banner

    if [ "$privileged" -eq 1 ]; then
        setup_timezone
        remap_user
        seed_home
        persist_android_downloads
        setup_ssh_agent
    else
        warn "not running as root; skipping user remap, ownership fixes and root hooks"
    fi

    # After the timezone, so the ledger's stamps read as local time like every
    # other timestamp this container prints, and before the hooks, so a hook
    # that wants to know what it is running on can read it.
    record_image

    run_hooks
    log "hooks done (+${SECONDS}s from start)"
    boot_ready

    local -a cmd=()
    mapfile -d '' -t cmd < <(resolve_command "$@")

    log "starting: ${cmd[*]}"
    # The shield, at last: the secrets were stashed for the root helper and
    # turned into redaction rules at the top, and the hooks that needed one
    # (npm publishing) have run. Nothing started from here may inherit them:
    # this is the environment of the dashboard, ttyd and every process under
    # the builder account, and it carried every one of them until the review
    # of 26 Sep read this file.
    # The one secret the dashboard itself needs, as a file only it reads
    # (lib/boot.sh), written before the rest go from the environment.
    signing_secret_file
    unset "${SECRET_VARS[@]}"
    if [ "$privileged" -eq 1 ]; then
        exec gosu builder env HOME="$BUILDER_HOME" USER=builder "${cmd[@]}"
    else
        exec env HOME="$BUILDER_HOME" "${cmd[@]}"
    fi
}

main "$@"
