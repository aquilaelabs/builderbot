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
# what to pin it to. The variables they replaced are read for one release.
if is_true "$(bb_setting claude_auto_update AUTO_UPDATE_CLAUDE true)"; then
    log "updating Claude Code (auto-update is on — the Settings tab)"
    if install_claude_code "$(bb_setting claude_version CLAUDE_CODE_VERSION latest)"; then
        log "claude $(claude --version 2>/dev/null || echo '?')"
    else
        warn "Claude Code update failed — keeping the version baked into the image"
    fi
else
    log "claude $(claude --version 2>/dev/null || echo 'not found')"
fi

# Extra global npm packages (e.g. "typescript pnpm @biomejs/biome") — the
# Settings tab's packages-at-boot field, re-applied on every start because
# /opt is discarded on every image update.
EXTRA_NPM="$(bb_setting packages_npm EXTRA_NPM_PACKAGES "")"
if [ -n "$EXTRA_NPM" ]; then
    log "installing extra npm packages: ${EXTRA_NPM}"
    # shellcheck disable=SC2086 # deliberate word splitting
    npm install -g --no-fund --no-audit ${EXTRA_NPM} \
        || warn "some npm packages failed to install"
fi

# Extra Python tools, installed isolated via pipx (e.g. "ruff black httpie").
EXTRA_PIPX="$(bb_setting packages_pipx EXTRA_PIPX_PACKAGES "")"
if [ -n "$EXTRA_PIPX" ]; then
    log "installing extra pipx packages: ${EXTRA_PIPX}"
    for pkg in ${EXTRA_PIPX}; do
        pipx install "$pkg" >/dev/null 2>&1 || pipx upgrade "$pkg" >/dev/null 2>&1 \
            || warn "pipx install ${pkg} failed"
    done
fi
