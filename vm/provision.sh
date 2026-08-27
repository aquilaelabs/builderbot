#!/usr/bin/env bash
#
# Turn a fresh Debian or Ubuntu VM into BuilderBot's Docker sandbox.
#
# The sandbox exists so that a Claude session can build, run and destroy
# containers without any of that reaching the server's real ones. BuilderBot
# itself stays the container it is — this box is only ever a Docker host, and
# keeping it only that is what makes it disposable.
#
# Run it inside the VM, once:
#
#   curl -fsSLO https://raw.githubusercontent.com/<org>/BuilderBot/main/vm/provision.sh
#   sudo bash provision.sh --user bb --key "ssh-ed25519 AAAA..."
#
# It is safe to run again: every step checks before it acts.
set -euo pipefail

USER_NAME="bb"
SSH_KEY=""
TCP_ON=""
declare -a SHARES=() NFS=()

usage() {
    cat <<'EOF'
usage: provision.sh [options]

  --user NAME          the account Docker runs under and ssh lands on (bb)
  --key "ssh-ed25519 …"  a PUBLIC key, appended to this machine's
                       authorized_keys. It is the .pub half and nothing else:
                       the private key stays on BuilderBot, shielded in
                       /secrets/ssh where no session can read it, and this
                       machine never holds it and never connects out. This is
                       how BuilderBot reaches the daemon, and the reason no
                       Docker port has to be opened at all.
  --share TAG:PATH     a virtiofs/9p share Unraid passes in, mounted at PATH.
                       Repeatable. PATH MUST match the path BuilderBot uses.
  --nfs HOST:EXPORT:PATH   the same thing over NFS, when a share cannot be
                       passed directly. Repeatable. EXPORT is the exported
                       share path — on Unraid /mnt/user/<share>/... — and not
                       a pool path like /mnt/cache/...: that spelling is for
                       bind mounts and is not what the server offers, so the
                       mount fails, quietly, because of nofail.
  --tcp                also listen on 2375, unauthenticated, for hosts that
                       cannot use ssh. Off by default and worth leaving off.

Path parity is not a style preference. A compose file's bind mounts are
resolved by whatever runs the container, so if this VM calls the projects
share /workspace exactly as BuilderBot does, a relative bind means the same
directory on both sides and nothing has to translate between them. Mount it
anywhere else and every project's compose file becomes wrong in a way that
fails silently — docker creates the missing directory and mounts it empty.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --user)  USER_NAME="$2"; shift 2 ;;
        --key)   SSH_KEY="$2"; shift 2 ;;
        --share) SHARES+=("$2"); shift 2 ;;
        --nfs)   NFS+=("$2"); shift 2 ;;
        --tcp)   TCP_ON=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

[ "$(id -u)" -eq 0 ] || { echo "run this with sudo" >&2; exit 1; }
. /etc/os-release
case "${ID:-}" in
    debian|ubuntu) ;;
    *) echo "this expects Debian or Ubuntu, not ${ID:-unknown}" >&2; exit 1 ;;
esac

say() { printf '\n== %s\n' "$*"; }

say "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# qemu-guest-agent so Unraid can shut it down cleanly rather than pulling the
# plug; nfs-common only matters if --nfs is used, and costs nothing if not.
apt-get install -y -qq ca-certificates curl gnupg qemu-guest-agent nfs-common

say "docker"
# Docker's own repository rather than the distribution's: the compose plugin
# and a current engine are the entire point of this machine, and Debian's
# docker.io lags both.
# Which suite to ask Docker for. Normally this release's own codename — but
# Docker's repository can lag a brand-new Ubuntu or Debian by weeks, and the
# symptom is an apt 404 that names a URL and not a reason. So the suite is
# checked before it is committed to, and falls back to the newest stable one
# that exists: the packages are the same build, only the suite name differs.
docker_suite() {
    local try
    for try in "$@"; do
        [ -n "$try" ] || continue
        # -fs and not -fsS: a miss here is the normal path into the fallback,
        # and curl announcing its own 404 first would read as the failure.
        if curl -fs -o /dev/null --max-time 15 \
            "https://download.docker.com/linux/${ID}/dists/${try}/Release"; then
            printf '%s' "$try"
            return 0
        fi
    done
    return 1
}

if ! command -v docker >/dev/null 2>&1; then
    case "$ID" in
        ubuntu) suite="$(docker_suite "$VERSION_CODENAME" noble jammy)" || true ;;
        *)      suite="$(docker_suite "$VERSION_CODENAME" bookworm bullseye)" || true ;;
    esac
    [ -n "${suite:-}" ] || {
        echo "docker publishes nothing this machine can use (tried ${VERSION_CODENAME})" >&2
        exit 1
    }
    [ "$suite" = "$VERSION_CODENAME" ] \
        || echo "note: docker has no ${VERSION_CODENAME} suite yet — using ${suite}, which is the same build"

    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/${ID}/gpg" \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg]" \
         "https://download.docker.com/linux/${ID} ${suite} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

say "user ${USER_NAME}"
id -u "$USER_NAME" >/dev/null 2>&1 || useradd -m -s /bin/bash "$USER_NAME"
usermod -aG docker "$USER_NAME"
if [ -n "$SSH_KEY" ]; then
    home="$(getent passwd "$USER_NAME" | cut -d: -f6)"
    install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" "$home/.ssh"
    touch "$home/.ssh/authorized_keys"
    grep -qxF "$SSH_KEY" "$home/.ssh/authorized_keys" \
        || echo "$SSH_KEY" >> "$home/.ssh/authorized_keys"
    chown "$USER_NAME:$USER_NAME" "$home/.ssh/authorized_keys"
    chmod 0600 "$home/.ssh/authorized_keys"
fi

say "shares"
# Written to fstab rather than mounted once, because a sandbox that comes back
# from a reboot without the projects share is a sandbox that builds the wrong
# thing rather than failing.
add_fstab() {
    local line="$1" path="$2"
    mkdir -p "$path"
    grep -qsF " $path " /etc/fstab || echo "$line" >> /etc/fstab
}
for s in "${SHARES[@]:-}"; do
    [ -n "$s" ] || continue
    tag="${s%%:*}"; path="${s#*:}"
    add_fstab "$tag $path virtiofs defaults,nofail 0 0" "$path"
done
for n in "${NFS[@]:-}"; do
    [ -n "$n" ] || continue
    host="${n%%:*}"; rest="${n#*:}"; export_="${rest%%:*}"; path="${rest#*:}"
    add_fstab "$host:$export_ $path nfs defaults,nofail,_netdev 0 0" "$path"
done
if [ "${#SHARES[@]}" -gt 0 ] || [ "${#NFS[@]}" -gt 0 ]; then
    mount -a || echo "one of the mounts did not come up — see 'mount -a' above" >&2
fi

if [ -n "$TCP_ON" ]; then
    say "docker on tcp/2375 (unauthenticated)"
    # Deliberately awkward to reach for. An open Docker port is root on this
    # machine to anyone who can reach it — tolerable ONLY because this machine
    # is the sandbox and holds nothing. Keep it off the LAN.
    mkdir -p /etc/systemd/system/docker.service.d
    cat > /etc/systemd/system/docker.service.d/tcp.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd -H fd:// -H tcp://0.0.0.0:2375 --containerd=/run/containerd/containerd.sock
EOF
    systemctl daemon-reload
    systemctl restart docker
fi

ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
cat <<EOF

== done

Point BuilderBot at it by setting, in the container's template:

  DOCKER_HOST=ssh://${USER_NAME}@${ip:-<this-vm>}
$([ -n "$TCP_ON" ] && echo "  ...or, if ssh is awkward:  DOCKER_HOST=tcp://${ip:-<this-vm>}:2375")

A web UI a container here publishes is reachable at http://${ip:-<this-vm>}:<port>
directly, because this VM has its own address on your network.

Mounted for parity:
$( { for s in "${SHARES[@]:-}"; do [ -n "$s" ] && echo "  ${s#*:}  (virtiofs ${s%%:*})"; done
     for n in "${NFS[@]:-}"; do [ -n "$n" ] && echo "  ${n##*:}  (nfs)"; done; } || true)
EOF
