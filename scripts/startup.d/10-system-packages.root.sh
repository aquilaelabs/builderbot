#!/usr/bin/env bash
#
# roles: controller node
#
# Install any extra apt packages from the Settings tab's packages-at-boot
# field (roadmap R29; EXTRA_APT_PACKAGES is read for one release). Runs as
# root, before the unprivileged hooks.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

EXTRA_APT_PACKAGES="$(bb_setting packages_apt EXTRA_APT_PACKAGES "")"
[ -n "${EXTRA_APT_PACKAGES:-}" ] || exit 0

log "installing extra apt packages: ${EXTRA_APT_PACKAGES}"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# shellcheck disable=SC2086 # deliberate word splitting: space-separated list
apt-get install -y --no-install-recommends ${EXTRA_APT_PACKAGES}
rm -rf /var/lib/apt/lists/*
