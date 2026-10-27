#!/usr/bin/env bash
# shellcheck disable=SC2034  # the FAMILY_* names are read by the core that sources this
# The Debian and Ubuntu family of nodes/provision-linux.sh: what differs by
# package manager, where docker comes from, and what the packages are
# called. The core sources this file from beside it (the enroll script
# puts the picked system's there) and calls nothing of a distribution's
# by name. Vetted: Ubuntu 24.04 and 26.04 sandboxes, in daily use.
FAMILY_PICKED=deb
FAMILY_NAME="Debian and Ubuntu"
# The os-release IDs (ID and ID_LIKE) this file is for.
FAMILY_IDS="debian ubuntu raspbian"
# The tools the family implies, checked before anything lands.
FAMILY_NEED="apt-get dpkg"

# apt_waiting CMD...: CMD, run again while another apt holds its lock (B320).
# A machine just booted from a cloud image runs its own apt-get (cloud-init,
# unattended-upgrades) for a few minutes, and an install started as soon as
# ssh answered failed at its first step on the lock. Up to ten minutes, said
# once; any other failure is CMD's own, at once.
apt_waiting() {
    local i out rc=0
    for i in $(seq 1 60); do
        out="$("$@" 2>&1)" && rc=0 || rc=$?
        if [ "$rc" -ne 0 ] && grep -qE 'Could not get lock|Unable to lock|is another process using it' <<<"$out"; then
            [ "$i" -gt 1 ] || echo "waiting for another apt (a machine's own first update) to let go of its lock" >&2
            sleep 10
            continue
        fi
        break
    done
    [ -z "$out" ] || printf '%s\n' "$out"
    return "$rc"
}
# pkg_refresh: the package index, once, before the first install.
pkg_refresh() {
    export DEBIAN_FRONTEND=noninteractive; apt_waiting apt-get update -qq
}
# pkg NAME...: install what is named, quietly.
pkg() {
    DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a \
                apt_waiting apt-get -o Dpkg::Use-Pty=0 -o DPkg::Lock::Timeout=600 install -y -qq "$@"
}
# pkg_names KEY: what a package is called here, for the handful the core
# installs itself. A recipe's system packages are the recipe's business,
# per family, in config/toolchains.json.
pkg_names() {
    case "$1" in
        base) echo "ca-certificates curl gnupg nfs-common" ;;
        guest) echo "qemu-guest-agent" ;;
        guestsvc) echo "qemu-guest-agent" ;;
        python) echo "python3" ;;
        pycrypto) echo "python3-cryptography" ;;
        session) echo "tmux jq git" ;;
        reel) echo "xvfb xdotool x11-utils" ;;
        wg) echo "wireguard-tools" ;;
        nft) echo "nftables" ;;
        docker) echo "docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin" ;;
    esac
}
# docker_install: docker, where this family gets it from.
docker_install() {

            # Which of Docker's two Debian-family repositories, and which
            # suite in it. A derivative uses its parent's: Mint and Pop!_OS
            # carry UBUNTU_CODENAME for exactly this; Kali's own codename
            # is nothing Docker publishes, and Raspberry Pi OS is Debian's
            # stable; both fall through docker_suite to it.
            case " ${ID} ${ID_LIKE:-} " in
                *" ubuntu "*) DOCKER_DEB=ubuntu; code="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"; fall="noble jammy" ;;
                *)            DOCKER_DEB=debian; code="${VERSION_CODENAME:-}"; fall="bookworm bullseye" ;;
            esac
            # shellcheck disable=SC2086  # the fallbacks are meant to split
            suite="$(docker_suite "$code" $fall)" || true
            [ -n "${suite:-}" ] || {
                echo "docker publishes nothing this machine can use (tried ${code:-no codename}, ${fall})" >&2
                exit 1
            }
            [ "$suite" = "$code" ] \
                || echo "note: docker has no ${code:-$ID} suite; using ${suite}, which is the same build"
            install -m 0755 -d /etc/apt/keyrings
            curl -fsSL "https://download.docker.com/linux/${DOCKER_DEB}/gpg" \
                | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
            chmod a+r /etc/apt/keyrings/docker.gpg
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg]" \
                 "https://download.docker.com/linux/${DOCKER_DEB} ${suite} stable" \
                > /etc/apt/sources.list.d/docker.list
            apt_waiting apt-get update -qq
            # shellcheck disable=SC2046
            pkg $(pkg_names docker)
}
