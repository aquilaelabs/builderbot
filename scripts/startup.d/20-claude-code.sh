#!/usr/bin/env bash
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

if is_true "${AUTO_UPDATE_CLAUDE:-true}"; then
    log "updating Claude Code (AUTO_UPDATE_CLAUDE=true)"
    # --allow-scripts: newer npm majors block postinstall scripts by default,
    # which would silently skip Claude Code's native installer.
    if npm install -g --no-fund --no-audit \
        --allow-scripts=@anthropic-ai/claude-code \
        "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION:-latest}"; then
        log "claude $(claude --version 2>/dev/null || echo '?')"
    else
        warn "Claude Code update failed — keeping the version baked into the image"
    fi
else
    log "claude $(claude --version 2>/dev/null || echo 'not found')"
fi

# Extra global npm packages (e.g. "typescript pnpm @biomejs/biome").
if [ -n "${EXTRA_NPM_PACKAGES:-}" ]; then
    log "installing extra npm packages: ${EXTRA_NPM_PACKAGES}"
    # shellcheck disable=SC2086 # deliberate word splitting
    npm install -g --no-fund --no-audit ${EXTRA_NPM_PACKAGES} \
        || warn "some npm packages failed to install"
fi

# Extra Python tools, installed isolated via pipx (e.g. "ruff black httpie").
if [ -n "${EXTRA_PIPX_PACKAGES:-}" ]; then
    log "installing extra pipx packages: ${EXTRA_PIPX_PACKAGES}"
    for pkg in ${EXTRA_PIPX_PACKAGES}; do
        pipx install "$pkg" >/dev/null 2>&1 || pipx upgrade "$pkg" >/dev/null 2>&1 \
            || warn "pipx install ${pkg} failed"
    done
fi
