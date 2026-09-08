#!/usr/bin/env bash
#
# roles: controller
#
# Keep Claude Code current and make sure the CLI is usable by `builder`.
#
# Updates install into ~/.npm-global (persisted on the home volume), which
# precedes /usr/local on PATH — so the container can self-update without
# rebuilding the image.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

npm config set prefix "${HOME}/.npm-global" >/dev/null 2>&1 || true

# Both from the Settings tab (roadmap R29): whether to update at boot, and
# which channel — an npm dist-tag: stable, latest or next.
if is_true "$(bb_setting claude_auto_update true)"; then
    log "updating Claude Code (auto-update is on — the Settings tab)"
    if install_claude_code "$(bb_setting claude_channel latest)"; then
        log "claude $(claude --version 2>/dev/null || echo '?')"
    else
        warn "Claude Code update failed — keeping the version baked into the image"
    fi
else
    log "claude $(claude --version 2>/dev/null || echo 'not found')"
fi

