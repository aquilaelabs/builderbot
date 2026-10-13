#!/usr/bin/env bash
# shellcheck disable=SC2034  # the FAMILY_* names are read by the core that sources this
# The Arch Linux family of nodes/provision-linux.sh: what differs by
# package manager, where docker comes from, and what the packages are
# called. The core sources this file from beside it (the enroll script
# puts the picked system's there) and calls nothing of a distribution's
# by name. Written to the family's documentation and never run for real (dev).
FAMILY_PICKED=arch
FAMILY_NAME="Arch Linux"
# The os-release IDs (ID and ID_LIKE) this file is for.
FAMILY_IDS="arch archlinux manjaro"
# The tools the family implies, checked before anything lands.
FAMILY_NEED="pacman"

# pkg_refresh: the package index, once, before the first install.
pkg_refresh() {
    pacman -Syu --noconfirm --needed >/dev/null
}
# pkg NAME...: install what is named, quietly.
pkg() {
    pacman -S --noconfirm --needed --quiet "$@" >/dev/null
}
# pkg_names KEY: what a package is called here, for the handful the core
# installs itself. A recipe's system packages are the recipe's business,
# per family, in config/toolchains.json.
pkg_names() {
    case "$1" in
        base) echo "ca-certificates curl gnupg nfs-utils" ;;
        guest) echo "qemu-guest-agent" ;;
        guestsvc) echo "qemu-guest-agent" ;;
        python) echo "python" ;;
        session) echo "tmux jq git" ;;
        ttyd) echo "ttyd" ;;
        reel) echo "xorg-server-xvfb xdotool xorg-xdpyinfo" ;;
        wg) echo "wireguard-tools" ;;
        nft) echo "nftables" ;;
        docker) echo "docker docker-buildx docker-compose" ;;
    esac
}
# docker_install: docker, where this family gets it from.
docker_install() {

            # Arch, SUSE, Alpine, Void and Gentoo package a current Docker
            # themselves, which is the point of using theirs.
            # shellcheck disable=SC2046
            pkg $(pkg_names docker) \
                || warn "docker did not install from the distribution's packages, so this machine is not a Docker host until it does"
}
