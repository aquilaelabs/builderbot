#!/usr/bin/env bash
#
# roles: controller
#
# Install Claude Code, and keep it current. The image does not carry it —
# it is Anthropic's proprietary binary and the image is published — so the
# first boot on a fresh home volume installs it into ~/.npm-global (persisted,
# ahead of /usr/local on PATH), and every boot after that updates it when the
# Settings tab says to. The container self-updates without a rebuild either
# way.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

npm config set prefix "${HOME}/.npm-global" >/dev/null 2>&1 || true

# Both from the Settings tab (roadmap R29): whether to update at boot, and
# which channel — an npm dist-tag: stable, latest or next.
if ! command -v claude >/dev/null 2>&1; then
    # A fresh home: nothing to update, something to install. Not gated on
    # the setting — a box with no claude at all is not a box with a choice.
    log "installing Claude Code into the home volume — the image does not carry it"
    if install_claude_code "$(bb_setting claude_channel latest)"; then
        log "claude $(claude --version 2>/dev/null || echo '?')"
    else
        warn "Claude Code did not install — sessions cannot start until it does; check the network and restart the container"
    fi
elif is_true "$(bb_setting claude_auto_update true)"; then
    log "updating Claude Code (auto-update is on — the Settings tab)"
    if install_claude_code "$(bb_setting claude_channel latest)"; then
        log "claude $(claude --version 2>/dev/null || echo '?')"
    else
        warn "Claude Code update failed — keeping the version already in the home"
    fi
else
    log "claude $(claude --version 2>/dev/null || echo 'not found')"
fi

