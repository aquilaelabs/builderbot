#!/usr/bin/env bash
#
# Wire up package-publishing credentials, when they're provided.
#
#   NPM_TOKEN         -> ~/.npmrc auth for registry.npmjs.org (npm publish)
#   GITHUB_PAT        -> docker login ghcr.io (docker push), when the host
#                        Docker socket is mounted
#   UV_PUBLISH_TOKEN  -> nothing to configure; `uv publish` reads it directly
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

if [ -n "${NPM_TOKEN:-}" ]; then
    npm config set "//registry.npmjs.org/:_authToken" "$NPM_TOKEN"
    log "npm publish auth configured for registry.npmjs.org"
fi

# A registry login needs a daemon to log in TO, which is the sandbox VM now
# rather than a socket mounted here.
if [ -n "${GITHUB_PAT:-}" ] && [ -n "${DOCKER_HOST:-}" ] && command -v docker >/dev/null; then
    # ghcr wants a username with the token; ask gh (already authenticated by
    # the 30- hook) who the PAT belongs to.
    gh_user="$(gh api user -q .login 2>/dev/null || echo "${GITHUB_USER:-}")"
    if [ -n "$gh_user" ]; then
        if printf '%s' "$GITHUB_PAT" | docker login ghcr.io -u "$gh_user" --password-stdin >/dev/null 2>&1; then
            log "docker authenticated to ghcr.io as ${gh_user}"
        else
            warn "docker login ghcr.io failed (PAT may lack read/write:packages)"
        fi
    fi
fi
