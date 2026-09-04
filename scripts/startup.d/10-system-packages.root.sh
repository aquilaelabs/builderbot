#!/usr/bin/env bash
#
# roles: controller node
#
# Install any extra apt packages requested via EXTRA_APT_PACKAGES.
# Runs as root, before the unprivileged hooks.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

[ -n "${EXTRA_APT_PACKAGES:-}" ] || exit 0

log "installing extra apt packages: ${EXTRA_APT_PACKAGES}"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# shellcheck disable=SC2086 # deliberate word splitting: space-separated list
apt-get install -y --no-install-recommends ${EXTRA_APT_PACKAGES}
rm -rf /var/lib/apt/lists/*
