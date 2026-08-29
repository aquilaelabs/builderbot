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
# It is safe to run again: every step checks before it acts, and a mount whose
# source has CHANGED since last time is rewritten rather than left alone.
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
warn() { printf '\n!! %s\n' "$*" >&2; }

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
    # Checked before it is installed, because both ways this goes wrong are
    # expensive and neither says anything at the time. A key that does not
    # parse leaves a VM nothing can ssh into, found from the console after
    # provisioning has finished and you have walked away. And a PRIVATE key
    # pasted here is a secret written onto the machine whose whole premise is
    # that it holds nothing — authorized_keys wants the .pub half, and the
    # private one never leaves BuilderBot's shielded agent.
    case "$SSH_KEY" in
        *"-----BEGIN"*)
            echo "--key is a PRIVATE key. It wants the .pub half — the private" >&2
            echo "one stays on BuilderBot and this machine never holds it." >&2
            exit 1 ;;
    esac
    printf '%s\n' "$SSH_KEY" | ssh-keygen -l -f - >/dev/null 2>&1 || {
        echo "--key does not parse as a public key. It is one line, starting" >&2
        echo "ssh-ed25519 or ssh-rsa, from BuilderBot's own .pub file." >&2
        exit 1
    }
    home="$(getent passwd "$USER_NAME" | cut -d: -f6)"
    install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" "$home/.ssh"
    touch "$home/.ssh/authorized_keys"
    grep -qxF "$SSH_KEY" "$home/.ssh/authorized_keys" \
        || echo "$SSH_KEY" >> "$home/.ssh/authorized_keys"
    chown "$USER_NAME:$USER_NAME" "$home/.ssh/authorized_keys"
    chmod 0600 "$home/.ssh/authorized_keys"
fi

say "bb-sandbox"
# The tool that configures this machine after today: mounts, which one holds
# container appdata, and the lines to paste into BuilderBot. Installed here and
# then USED below, so the fstab logic has one implementation rather than a copy
# in each entry point — its comments were paid for one silent failure at a time
# and are not worth writing twice.
#
# Embedded rather than fetched: provision.sh is one file you curl onto a fresh
# VM, and a second download is a second thing that can be unreachable at the
# moment you are standing in front of a machine with no shares.
#
# Root-only, and deliberately not reachable from BuilderBot. The point of this
# VM is that a session can build and destroy containers without touching
# anything that matters, and a path from the container into the VM's own
# configuration would hand back exactly what the arrangement buys.
install -m 0755 /dev/stdin /usr/local/sbin/bb-sandbox <<'BBSANDBOX'
#!/usr/bin/env bash
#
# bb-sandbox — configure this Docker sandbox after it has been provisioned.
#
# Installed by provision.sh, which also uses it for its own mounts: this is the
# only copy of the fstab logic, so the wizard and the first run cannot drift.
#
# Root, on this machine, by a person. Deliberately NOT reachable from
# BuilderBot: the whole reason this VM exists is that a session can build and
# destroy containers without touching anything that matters, and a path from
# the container into the VM's own configuration would hand back what the
# arrangement was buying. The dashboard can see what is mounted; changing it
# is a decision made here.
set -euo pipefail

CONF=/etc/bb-sandbox.conf
# shellcheck source=/dev/null
[ -f "$CONF" ] && . "$CONF"
APPDATA="${APPDATA:-}"
# The account BuilderBot ssh's in as, recorded by provision.sh because this is
# the one thing here it knows and the tool cannot work out. `logname` was the
# guess before, and it answers with whoever ran sudo — a different name the
# moment the operator administers this box from an account of their own, and
# an empty one where there is no controlling terminal at all.
DOCKER_USER="${DOCKER_USER:-bb}"

say()  { printf '\n== %s\n' "$*"; }
warn() { printf '\n!! %s\n' "$*" >&2; }
die()  { warn "$*"; exit 1; }
[ "$(id -u)" -eq 0 ] || die "run this as root: sudo bb-sandbox"

# Every mount this tool manages, by mountpoint. Read from fstab rather than
# kept in a list of our own: fstab is what the machine actually boots from, and
# a second list would be a claim about it rather than a reading of it. Which
# means the type list has to hold every type a share is really mounted with,
# not only the two this tool writes — a /workspace mounted by hand with nfs4 is
# invisible to a filter that knows only nfs, and `settings` then prints a
# DOCKER_HOST_PATHS with the projects share missing from it.
ours() {
    awk '$1 !~ /^#/ && $3 ~ /^(virtiofs|9p|nfs|nfs4|cifs)$/ {print $2}' \
        /etc/fstab 2>/dev/null | sort -u
}

# The fstab line for a mountpoint, as "N:the whole line" — empty if there is
# none. On field TWO, and skipping comments, because every caller below either
# rewrites or deletes what this finds: matching ` $path ` anywhere on the line
# also hits a comment that mentions the path, and `# /workspace comes from the
# NAS` has it in field two of a line that is not a mount. Measured: add-nfs
# against exactly that comment overwrote the comment and left fstab with TWO
# entries for /workspace, and remove deleted the comment along with the mount.
fstab_line() {
    awk -v p="$1" '$1 !~ /^#/ && $2 == p {print NR": "$0; exit}' \
        /etc/fstab 2>/dev/null || true
}

# --- the one copy of the fstab logic ------------------------------------
add_fstab() {
    local line="$1" path="$2" hit lineno old tmp
    # A mountpoint whose export has gone away answers every syscall with
    # ESTALE — including the stat that `mkdir -p` begins with.
    if ! mkdir -p "$path" 2>/dev/null; then
        if findmnt -rno TARGET -- "$path" >/dev/null 2>&1; then
            warn "$path is mounted but unreadable — a stale handle, left by a share that moved or stopped being exported."
            printf '   Clear it and try again:\n     umount -l %s\n' "$path"
        else
            warn "could not create the mountpoint $path"
        fi
        return 1
    fi
    # Matched on the MOUNTPOINT and then compared in full, so re-adding one
    # whose SOURCE has changed rewrites it rather than silently doing nothing.
    hit="$(fstab_line "$path")"
    if [ -z "$hit" ]; then
        echo "$line" >> /etc/fstab
        return 0
    fi
    lineno="${hit%%:*}"; old="${hit#*:}"
    [ "$old" = "$line" ] && return 0
    tmp="$(mktemp)"
    awk -v n="$lineno" -v repl="$line" 'NR==n {print repl; next} {print}' \
        /etc/fstab > "$tmp"
    # cat rather than mv, so /etc/fstab keeps its own inode and permissions.
    cat "$tmp" > /etc/fstab
    rm -f "$tmp"
    say "fstab: $path now comes from ${line%% *}"
    printf '   it was %s\n' "${old%% *}"
}

# mount_one PATH — mount it and say plainly whether it worked.
#
# `nofail` is right at boot and wrong here: it means a share that cannot mount
# does so quietly and `mount -a` still succeeds. So the SOURCE is checked, not
# merely that something is mounted — `mount -a` skips a busy mountpoint, so a
# path whose entry was just rewritten stays on the old share and looks fine.
mount_one() {
    local path="$1" want got
    mount -a || true
    want="$(fstab_line "$path")"; want="${want#*: }"; want="${want%% *}"
    got="$(findmnt -rno SOURCE -- "$path" 2>/dev/null || true)"
    if [ -n "$got" ] && [ "$got" = "$want" ]; then
        say "$path is mounted from $got"
        return 0
    fi
    if [ -n "$got" ]; then
        warn "$path is mounted from $got, but fstab now says $want."
        printf '   It was already mounted, so mount -a left it alone:\n'
        printf '     umount -l %s && mount -a\n' "$path"
        return 1
    fi
    warn "$path did NOT mount, and nofail means nothing said so."
    printf '   On Unraid an export is a SHARE — /mnt/user/<share> — never a\n'
    printf '   pool path like /mnt/cache/<share>, which is right for a bind\n'
    printf '   mount and is not exported. Check it allows this host:\n'
    printf '     showmount -e <server>\n'
    return 1
}

# --- commands -----------------------------------------------------------
cmd_add_share() {
    local spec="${1:?usage: bb-sandbox add-share TAG:PATH}" tag path
    tag="${spec%%:*}"; path="${spec#*:}"
    [ "$tag" != "$spec" ] || die "add-share wants TAG:PATH — got '$spec'"
    case "$path" in /*) ;; *) die "the mountpoint must be absolute — got '$path'" ;; esac
    add_fstab "$tag $path virtiofs defaults,nofail 0 0" "$path" && mount_one "$path"
}

cmd_add_nfs() {
    local spec="${1:?usage: bb-sandbox add-nfs HOST:EXPORT:PATH}" host rest exp path
    host="${spec%%:*}"; rest="${spec#*:}"; exp="${rest%%:*}"; path="${rest#*:}"
    # Three fields, and getting two produces nonsense rather than an error:
    # the export and the mountpoint both come out as the export.
    case "$rest" in *:*) ;; *) die "add-nfs wants HOST:EXPORT:PATH — '$spec' has no mountpoint" ;; esac
    case "$path" in /*) ;; *) die "the mountpoint must be absolute — got '$path'" ;; esac
    add_fstab "$host:$exp $path nfs defaults,nofail,_netdev 0 0" "$path" && mount_one "$path"
}

cmd_remove() {
    local path="${1:?usage: bb-sandbox remove PATH}" tmp
    [ -n "$(fstab_line "$path")" ] || die "$path is not one of this machine's mounts"
    umount -l "$path" 2>/dev/null || true
    tmp="$(mktemp)"
    awk -v p="$path" '$1 ~ /^#/ || $2 != p' /etc/fstab > "$tmp" || true
    cat "$tmp" > /etc/fstab
    rm -f "$tmp"
    # The mountpoint itself stays. It is empty now, and removing a directory
    # that a share was mounted over is how you delete the thing you meant to
    # detach if the umount above did not take.
    say "$path is no longer mounted at boot; the empty directory is left behind"
    # And it cannot still be where containers keep their data. Left set, `list`
    # marks a mount that is gone and `settings` tells you to mirror a share
    # this machine no longer has.
    if [ "$APPDATA" = "$path" ]; then
        write_conf ""
        say "it was the container appdata mount, so that is unset too"
    fi
}

cmd_list() {
    local path src state
    printf '\n%-24s %-34s %s\n' MOUNTPOINT SOURCE STATE
    while read -r path; do
        [ -n "$path" ] || continue
        src="$(fstab_line "$path")"; src="${src#*: }"; src="${src%% *}"
        if ! findmnt -rno TARGET -- "$path" >/dev/null 2>&1; then state="NOT MOUNTED"
        elif [ ! -w "$path" ]; then state="mounted, read-only"
        else state="mounted"; fi
        [ "$APPDATA" = "$path" ] && state="$state · container appdata"
        printf '%-24s %-34s %s\n' "$path" "$src" "$state"
    done < <(ours)
    [ -n "$(ours)" ] || printf '(none yet)\n'
}

cmd_check() {
    local bad=0 path
    while read -r path; do
        [ -n "$path" ] || continue
        mount_one "$path" || bad=1
    done < <(ours)
    [ "$bad" -eq 0 ] && say "every configured mount is present and comes from where fstab says"
    return "$bad"
}

# The only writer of $CONF. Quoted, because a mountpoint with a space in it
# would otherwise be sourced back as a value and a command.
write_conf() {
    APPDATA="$1"
    { printf '# written by bb-sandbox\n'
      printf 'APPDATA=%q\n' "$APPDATA"
      printf 'DOCKER_USER=%q\n' "$DOCKER_USER"; } > "$CONF"
}

cmd_appdata() {
    local path="${1-}"
    if [ -z "$path" ]; then
        printf '%s\n' "${APPDATA:-(not set)}"
        return 0
    fi
    ours | grep -qxF "$path" || die "$path is not one of this machine's mounts — add it first"
    write_conf "$path"
    say "$path is where containers keep their data"
}

# The lines to put in BuilderBot's own template. This machine cannot set them —
# they are the CONTAINER's environment, on the other box — so it prints them
# rather than pretending. Derived from what is actually mounted here, which is
# the half that is easy to get wrong by hand.
cmd_settings() {
    local ip pairs="" path
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    while read -r path; do
        [ -n "$path" ] || continue
        # Parity: BuilderBot mounts the same share at the same path, so the
        # mapping is an identity and the translation falls silent. A path this
        # VM has and BuilderBot does not still belongs in neither list.
        pairs="${pairs:+$pairs,}$path:$path"
    done < <(ours)
    cat <<EOF

Put these in BuilderBot's container template:

  DOCKER_HOST=ssh://${DOCKER_USER}@${ip:-<this-vm>}
  DOCKER_HOST_PATHS=${pairs:-<none yet>}

Only for the paths BuilderBot ALSO mounts at the same place — a share that is
this machine's alone belongs in neither list, and BuilderBot will say so.
${APPDATA:+
Container appdata is ${APPDATA}. Mount that same share in BuilderBot at that
same path, and set its /devdata to it.}
EOF
}

# --- the menu -----------------------------------------------------------
# whiptail where the distro has it, plain prompts where it does not. Both ask
# the same questions in the same order, so a screenshot of one explains the
# other.
menu_whiptail() {
    local choice
    while :; do
        choice="$(whiptail --title "BuilderBot sandbox" --menu \
            "This VM's Docker sandbox" 18 68 8 \
            list     "what is mounted, and from where" \
            nfs      "add an NFS mount" \
            share    "add a virtiofs share" \
            remove   "take a mount out of fstab" \
            appdata  "choose which mount holds container appdata" \
            check    "verify every mount is really there" \
            settings "the lines to paste into BuilderBot" \
            quit     "" 3>&1 1>&2 2>&3)" || return 0
        case "$choice" in
            list)  cmd_list; pause ;;
            nfs)   ask "HOST:EXPORT:PATH" "192.168.1.15:/mnt/user/media:/auxiliary" \
                       && cmd_add_nfs "$REPLY"; pause ;;
            share) ask "TAG:PATH" "workspace:/workspace" \
                       && cmd_add_share "$REPLY"; pause ;;
            remove) ask "which mountpoint" "" && cmd_remove "$REPLY"; pause ;;
            appdata) ask "which mountpoint holds container appdata" "${APPDATA:-/devdata}" \
                       && cmd_appdata "$REPLY"; pause ;;
            check) cmd_check || true; pause ;;
            settings) cmd_settings; pause ;;
            quit|"") return 0 ;;
        esac
    done
}

ask() {
    local prompt="$1" default="${2-}"
    if have whiptail; then
        REPLY="$(whiptail --inputbox "$prompt" 10 68 "$default" 3>&1 1>&2 2>&3)" || return 1
    else
        read -r -p "$prompt [${default}]: " REPLY || return 1
        REPLY="${REPLY:-$default}"
    fi
    [ -n "$REPLY" ]
}
pause() { printf '\n'; read -r -p "press enter " _ || true; }
have() { command -v "$1" >/dev/null 2>&1; }

menu_plain() {
    local n
    while :; do
        cat <<'EOF'

  1) list what is mounted        5) choose the container appdata mount
  2) add an NFS mount            6) check every mount
  3) add a virtiofs share        7) the lines to paste into BuilderBot
  4) remove a mount              q) quit
EOF
        read -r -p "> " n || return 0
        case "$n" in
            1) cmd_list ;;
            2) ask "HOST:EXPORT:PATH" "" && cmd_add_nfs "$REPLY" ;;
            3) ask "TAG:PATH" "" && cmd_add_share "$REPLY" ;;
            4) ask "which mountpoint" "" && cmd_remove "$REPLY" ;;
            5) ask "which mountpoint holds container appdata" "${APPDATA:-}" && cmd_appdata "$REPLY" ;;
            6) cmd_check || true ;;
            7) cmd_settings ;;
            q|Q) return 0 ;;
        esac
    done
}

case "${1-}" in
    "")          if have whiptail; then menu_whiptail; else menu_plain; fi ;;
    list)        cmd_list ;;
    add-nfs)     shift; cmd_add_nfs "${1-}" ;;
    add-share)   shift; cmd_add_share "${1-}" ;;
    remove)      shift; cmd_remove "${1-}" ;;
    check)       cmd_check ;;
    appdata)     shift; cmd_appdata "${1-}" ;;
    settings)    cmd_settings ;;
    -h|--help|help)
        sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) die "unknown command: $1 — try: bb-sandbox --help" ;;
esac
BBSANDBOX
# The account BuilderBot will ssh in as. Recorded now because it is decided
# here and nowhere else: bb-sandbox prints it back in `settings`, and guessing
# it from whoever ran sudo is wrong the moment this box is administered from
# an account of its own.
if [ -f /etc/bb-sandbox.conf ] \
   && grep -q '^DOCKER_USER=' /etc/bb-sandbox.conf 2>/dev/null; then
    sed -i "s|^DOCKER_USER=.*|DOCKER_USER=${USER_NAME}|" /etc/bb-sandbox.conf
else
    printf 'DOCKER_USER=%s\n' "$USER_NAME" >> /etc/bb-sandbox.conf
fi
printf '   /usr/local/sbin/bb-sandbox — run it as root to add mounts later\n'

say "shares"
# Written to fstab rather than mounted once, because a sandbox that comes back
# from a reboot without the projects share is a sandbox that builds the wrong
# thing rather than failing. bb-sandbox does the writing, and keeps doing it
# every time a share is added after today — one implementation, not a copy per
# entry point.
declare -a MOUNTED=()
# A share that will not mount is reported, not fatal. set -e would otherwise
# abandon the rest of provisioning — the tcp option, the closing summary — over
# an NFS export that is not ready yet, which is the most ordinary way for this
# to fail and the one the check below exists to report.
for spec in "${SHARES[@]:-}"; do
    [ -n "$spec" ] || continue
    /usr/local/sbin/bb-sandbox add-share "$spec" || warn "$spec did not mount — see the check below"
    MOUNTED+=("${spec#*:}")
done
for spec in "${NFS[@]:-}"; do
    [ -n "$spec" ] || continue
    /usr/local/sbin/bb-sandbox add-nfs "$spec" || warn "$spec did not mount — see the check below"
    MOUNTED+=("${spec##*:}")
done
# Checked rather than assumed, which is the difference between finding out now
# and finding out from an app that came up with no data. bb-sandbox owns the
# check for the same reason it owns the writing — one implementation — and the
# operator can run it again any day with `bb-sandbox check`.
if [ "${#MOUNTED[@]}" -gt 0 ]; then
    /usr/local/sbin/bb-sandbox check || true
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
