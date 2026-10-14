#!/usr/bin/env bash
# shellcheck disable=SC2034  # the FAMILY_* names are read by the core that sources this
# The Gentoo family of nodes/provision-linux.sh: what differs by
# package manager, where docker comes from, and what the packages are
# called. The core sources this file from beside it (the enroll script
# puts the picked system's there) and calls nothing of a distribution's
# by name. Written to the family's documentation and never run for real (dev).
FAMILY_PICKED=gentoo
FAMILY_NAME="Gentoo"
# The os-release IDs (ID and ID_LIKE) this file is for.
FAMILY_IDS="gentoo"
# The tools the family implies, checked before anything lands.
FAMILY_NEED="emerge"

# pkg_refresh: the package index, once, before the first install.
pkg_refresh() {
    :
}
# pkg NAME...: install what is named, quietly.
pkg() {
    emerge --quiet --noreplace "$@"
}
# pkg_names KEY: what a package is called here, for the handful the core
# installs itself. A recipe's system packages are the recipe's business,
# per family, in config/toolchains.json.
pkg_names() {
    case "$1" in
        base) echo "app-misc/ca-certificates net-misc/curl app-crypt/gnupg net-fs/nfs-utils" ;;
        guest) echo "qemu-guest-agent" ;;
        guestsvc) echo "qemu-guest-agent" ;;
        python) echo "dev-lang/python" ;;
        session) echo "app-misc/tmux app-misc/jq dev-vcs/git" ;;
        ttyd) echo "" ;;
        reel) echo "x11-base/xorg-server x11-misc/xdotool x11-apps/xdpyinfo" ;;
        wg) echo "net-vpn/wireguard-tools" ;;
        nft) echo "net-firewall/nftables" ;;
        docker) echo "app-containers/docker app-containers/docker-cli app-containers/docker-buildx app-containers/docker-compose" ;;
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
