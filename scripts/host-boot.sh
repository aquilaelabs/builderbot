#!/usr/bin/env bash
#
# A controller installed bare metal starts here (R90 step 3).
#
# What the container's entrypoint is under tini, this is under systemd: the
# unit nodes/install-controller.sh writes (builderbot-controller.service)
# runs it as root with the env file the installer wrote in place of
# compose's, and it takes the same steps in the same order (lib/boot.sh):
# the secrets stash, the state gate, the log, the home seed, the deploy-key
# agent, the image ledger, the hooks. Then it hands off to the supervisor as
# the controller's own account, for good.
#
# What it does not do, because the container's reasons for them do not hold
# on a machine of its own: no user is remapped (the installer made the
# account with the ids it keeps), the machine's timezone is the machine's
# (TZ still reaches every process the controller starts), and gosu is not
# needed (setpriv, from util-linux, drops privileges the same way).
#
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "host-boot.sh runs as root, from the builderbot-controller service" >&2; exit 1; }
# The environment the image's ENV gives the container, the release's stamp
# and the env file, before anything reads a path.
# shellcheck source=lib/host-env.sh
. /opt/builderbot/scripts/lib/host-env.sh
# shellcheck source=lib/common.sh
. /opt/builderbot/scripts/lib/common.sh

BB_ACCOUNT="${BB_ACCOUNT:-builderbot}"
# Exported with the ids below: a root hook (46-playwright.root.sh) is a
# process of its own, and drops to the account through common.sh with them.
BB_DROP=setpriv
export BB_DROP
BB_SECRETS_DIR="${BB_SECRETS_DIR:-/etc/builderbot-controller/secrets}"
export BOOT_WHAT="controller"
id -u "$BB_ACCOUNT" >/dev/null 2>&1 \
    || die "there is no account ${BB_ACCOUNT} on this machine: run nodes/install-controller.sh again"
PUID="$(id -u "$BB_ACCOUNT")"
PGID="$(id -g "$BB_ACCOUNT")"
export PUID PGID BB_ACCOUNT
# shellcheck source=lib/boot.sh
. /opt/builderbot/scripts/lib/boot.sh

# The folder the deploy-key agent's socket for the account lives in: the
# account's group may enter it and nobody else (the node's session and job
# accounts above all, R90's wall), where the container's sits in /run.
sock_dir() {
    local d
    d="$(dirname "${SSH_AUTH_SOCK:-/run/builderbot-controller/ssh-agent.sock}")"
    install -d -m 0750 -o root -g "$PGID" "$d"
}

main() {
    stash_secrets
    rm -f "$BOOT_READY_FILE" 2>/dev/null || true
    state_gate
    setup_logging
    banner
    seed_home
    sock_dir
    setup_ssh_agent
    record_image
    run_hooks
    log "hooks done (+${SECONDS}s from start)"
    boot_ready

    local -a cmd=()
    mapfile -d '' -t cmd < <(resolve_command "$@")
    log "starting: ${cmd[*]} as ${BB_ACCOUNT}"
    unset "${SECRET_VARS[@]}"
    exec setpriv --reuid="$BB_ACCOUNT" --regid="$PGID" --init-groups \
        env HOME="$BUILDER_HOME" USER="$BB_ACCOUNT" LOGNAME="$BB_ACCOUNT" "${cmd[@]}"
}

main "$@"
