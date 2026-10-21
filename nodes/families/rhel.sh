#!/usr/bin/env bash
# shellcheck disable=SC2034  # the FAMILY_* names are read by the core that sources this
# The RHEL, Rocky Linux, AlmaLinux, CentOS Stream and Fedora family of nodes/provision-linux.sh: what differs by
# package manager, where docker comes from, and what the packages are
# called. The core sources this file from beside it (the enroll script
# puts the picked system's there) and calls nothing of a distribution's
# by name. Vetted: Rocky Linux 9.8 on the dev pair, 13 Oct 2026.
FAMILY_PICKED=rhel
FAMILY_NAME="RHEL, Rocky Linux, AlmaLinux, CentOS Stream and Fedora"
# The os-release IDs (ID and ID_LIKE) this file is for.
FAMILY_IDS="rhel fedora centos rocky almalinux"
# The tools the family implies, checked before anything lands.
FAMILY_NEED="dnf rpm"

# pkg_refresh: the package index, once, before the first install.
pkg_refresh() {
    dnf -y -q makecache >/dev/null 2>&1 || true
}
# pkg NAME...: install what is named, quietly. xdotool (the capture tools)
# is EPEL's on RHEL 9 and its rebuilds, and never installed there without it
# (R97's walk, AlmaLinux 9, 21 Oct); Fedora carries it itself.
pkg() {
    case " $* " in *" xdotool "*) epel_here ;; esac
    dnf -y -q install "$@"
}
# epel_here: EPEL's release package, on a RHEL rebuild that lacks it.
epel_here() {
    [ "${ID:-}" = fedora ] && return 0
    rpm -q epel-release >/dev/null 2>&1 && return 0
    dnf -y -q install epel-release >/dev/null 2>&1 || true
}
# pkg_names KEY: what a package is called here, for the handful the core
# installs itself. A recipe's system packages are the recipe's business,
# per family, in config/toolchains.json.
pkg_names() {
    case "$1" in
        base) echo "ca-certificates gnupg2 nfs-utils" ;;
        guest) echo "qemu-guest-agent" ;;
        guestsvc) echo "qemu-guest-agent" ;;
        python) echo "python3" ;;
        session) echo "tmux jq git" ;;
        ttyd) echo "" ;;
        reel) echo "xorg-x11-server-Xvfb xdotool xorg-x11-utils" ;;
        wg) echo "wireguard-tools" ;;
        nft) echo "nftables" ;;
        docker) echo "docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin" ;;
    esac
}
# docker_install: docker, where this family gets it from.
docker_install() {

            # Docker's own repository here too: fedora's, rhel's, and the
            # centos one that serves CentOS Stream, Rocky and Alma alike.
            # The repo file is fetched as a file rather than through `dnf
            # config-manager`, which dnf4 and dnf5 spell differently; the
            # file is the same for both. podman-docker, if the image came
            # with it, would answer `docker` with podman: taken out.
            case "$ID" in fedora) repo=fedora ;; rhel) repo=rhel ;; *) repo=centos ;; esac
            dnf -y -q remove podman-docker >/dev/null 2>&1 || true
            curl -fsSL "https://download.docker.com/linux/${repo}/docker-ce.repo" -o /etc/yum.repos.d/docker-ce.repo
            # shellcheck disable=SC2046
            pkg $(pkg_names docker)
}
