#!/usr/bin/env bash
#
# Wire up package-publishing credentials, when they're provided.
#
#   NPM_TOKEN         -> ~/.npmrc auth for registry.npmjs.org (npm publish)
#   UV_PUBLISH_TOKEN  -> nothing to configure; `uv publish` reads it directly
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

if [ -n "${NPM_TOKEN:-}" ]; then
    npm config set "//registry.npmjs.org/:_authToken" "$NPM_TOKEN"
    log "npm publish auth configured for registry.npmjs.org"
fi
