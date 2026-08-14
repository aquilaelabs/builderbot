#!/usr/bin/env bash
#
# Report on the mounted projects and, optionally, run each project's own
# bootstrap.
#
# If a mounted project contains `.builderbot/setup.sh`, it is executed on every
# container start when PROJECT_BOOTSTRAP=true. That is the seam for installing
# per-project dependencies (npm ci, uv sync, …) without baking them into this
# image.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

shopt -s nullglob

for dir in "$WORKSPACE"/*/; do
    name="$(basename "$dir")"
    [ "$name" = "_work" ] && continue

    if [ -d "$dir/.git" ]; then
        log "project: ${name} (branch $(git_branch "$dir"))"
    else
        log "project: ${name}"
    fi

    if is_true "${PROJECT_BOOTSTRAP:-false}" && [ -x "$dir/.builderbot/setup.sh" ]; then
        log "running ${name}/.builderbot/setup.sh"
        (cd "$dir" && ./.builderbot/setup.sh) || warn "${name} bootstrap exited $?"
    fi
done
