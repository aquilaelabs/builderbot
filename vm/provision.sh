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
#   sudo bash provision.sh --key "ssh-ed25519 AAAA..."
#
# With --controller URL --token bbe_… (the Nodes tab mints the token) it also
# enrolls the machine as a node: the agent is fetched from the controller and
# left running under systemd, dialing out.
#
# It makes two accounts. `bb` runs Docker and answers ssh — the one BuilderBot
# uses, and the one a Claude session reaches — with no sudo and no bb-sandbox.
# `admin` has sudo and is the only account bb-sandbox runs for, so the mounts
# this machine has are a decision made by a person at a console.
#
# It is safe to run again: every step checks before it acts, and a mount whose
# source has CHANGED since last time is rewritten rather than left alone.
set -euo pipefail

USER_NAME="bb"
ADMIN_NAME="admin"
ADMIN_KEY=""
SSH_KEY=""
CONTROLLER=""
TOKEN=""
STORE_DATA=/var/lib/builderbot/data
STORE_PACKAGES=/var/lib/builderbot/packages
STORE_CACHE=/var/lib/builderbot/cache
STORE_ARTIFACTS=/var/lib/builderbot/artifacts
declare -a SHARES=() NFS=()

usage() {
    cat <<'EOF'
usage: provision.sh [options]

  --user NAME          the account Docker runs under and ssh lands on. The
                       default is bb, and BuilderBot assumes bb — so changing
                       it means writing the account out in the node's address. It gets
                       NO sudo and cannot run bb-sandbox: this is the account a
                       Claude session reaches, and reconfiguring the machine's
                       mounts is not what it is for.
  --admin NAME|none    the account that administers this machine (admin), or
                       `none` to make no such account — nothing here requires
                       one. It
                       gets sudo and bb-sandbox. Left without a password and
                       without a key unless you give it one — set a password
                       from the console, or pass --admin-key.
  --admin-key "ssh-…"  a PUBLIC key for the admin account, so it can be reached
                       over ssh the way the docker account is.
  --key "ssh-ed25519 …"  a PUBLIC key, appended to this machine's
                       authorized_keys, for reaching it over ssh yourself.
                       BuilderBot no longer needs one: an enrolled node dials
                       OUT and every job arrives down that connection, so the
                       controller holds no key that logs in anywhere. Nothing
                       here opens a Docker port either.
  --share TAG:PATH[:ro]  a virtiofs/9p share the HYPERVISOR passes in, mounted
                       at PATH. Requires one — on bare metal there is nothing
                       to pass a share in, so use --nfs instead. Repeatable.
                       PATH MUST match the path BuilderBot uses. `:ro` mounts it read-only — right for the projects
                       share: nothing on this machine needs to WRITE source
                       code, so a wild container cannot either. Leave it off a
                       share containers keep their data on.
  --nfs HOST:EXPORT:PATH[:ro]   the same thing over NFS, when a share
                       cannot be passed directly. Repeatable, same `:ro`. EXPORT is the exported
                       share path — on Unraid /mnt/user/<share>/... — and not
                       a pool path like /mnt/cache/...: that spelling is for
                       bind mounts and is not what the server offers, so the
                       mount fails, quietly, because of nofail.
  --controller URL     BuilderBot's dashboard, and --token the one-time
  --token bbe_…        enrollment token its Nodes tab minted. Given together,
                       this machine also becomes a NODE: the agent is
                       downloaded from the controller, enrolled, and left
                       running under systemd, dialing out — nothing here is
                       opened for it. It runs jobs as the docker account
                       (--user, bb), never as root. Re-run with a fresh token to enroll again; a
                       re-run without either leaves the enrollment alone.
  --data PATH          the four stores, all defaulting under
  --packages PATH      /var/lib/builderbot/: a job's working tree and AVDs,
  --cache PATH         the toolchains installed on this node, the build
  --artifacts PATH     caches, and this node's copy of what projects built
                       (per project underneath, so one VM can be several
                       projects' node). A store may be a mount — point it at
                       one of the --share paths — and its free space is what
                       the Nodes tab reports for it. A system path is refused:
                       a store is a directory of its own, since the agent
                       creates, fills and (for the cache) empties it.

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
        --admin) ADMIN_NAME="$2"; shift 2 ;;
        --admin-key) ADMIN_KEY="$2"; shift 2 ;;
        --key)   SSH_KEY="$2"; shift 2 ;;
        --share) SHARES+=("$2"); shift 2 ;;
        --nfs)   NFS+=("$2"); shift 2 ;;
        --controller) CONTROLLER="$2"; shift 2 ;;
        --token) TOKEN="$2"; shift 2 ;;
        --data)  STORE_DATA="$2"; shift 2 ;;
        --packages) STORE_PACKAGES="$2"; shift 2 ;;
        --cache) STORE_CACHE="$2"; shift 2 ;;
        --artifacts) STORE_ARTIFACTS="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done
# One without the other is a typo, and the enrollment would fail an hour of
# apt later. Said now.
if { [ -n "$CONTROLLER" ] && [ -z "$TOKEN" ]; } || { [ -z "$CONTROLLER" ] && [ -n "$TOKEN" ]; }; then
    echo "--controller and --token go together" >&2; exit 1
fi
case "$TOKEN" in
    ""|bbe_*) ;;
    *) echo "that is not an enrollment token (they start bbe_); mint one on the Nodes tab" >&2; exit 1 ;;
esac

say() { printf '\n== %s\n' "$*"; }
warn() { printf '\n!! %s\n' "$*" >&2; }

# This is for a VM, and a container is not one. BuilderBot's own base is
# Ubuntu and runs as root under `docker exec`, so both checks above pass there
# and the script would go on to install seven packages before failing on
# `systemctl enable --now docker` — a container has no systemd, and the error
# it gives ("unit docker.service does not exist") names the symptom rather
# than the mistake. Which is exactly how it went the first time somebody ran
# this in the wrong shell.
#
# So: refused at the top, before anything is installed. There is no --force,
# because provisioning a container as a Docker host has no working version to
# fall back to.
if [ -f /.dockerenv ] || [ -f /run/.containerenv ] \
   || grep -qs -E '(docker|lxc|containerd)' /proc/1/cgroup 2>/dev/null; then
    warn "this is a container, and this script provisions a VM."
    if [ -d /opt/builderbot ]; then
        printf '   You are inside BuilderBot. It is the thing that TALKS to the\n'
        printf '   sandbox; the sandbox is the separate machine BuilderBot lists as a node.\n'
        printf '   Run this in a console on that VM, not in here.\n\n'
        printf '   Nothing outside the volumes survives a restart here, so if a\n'
        printf '   run got further than this: restart the container and it is\n'
        printf '   gone. /etc, /usr and /var are all image layer.\n'
    else
        printf '   Run it in a console on the VM itself. It needs systemd, which\n'
        printf '   a container does not have, and it edits fstab.\n'
    fi
    exit 1
fi

[ "$(id -u)" -eq 0 ] || { echo "run this with sudo" >&2; exit 1; }
. /etc/os-release
case "${ID:-}" in
    debian|ubuntu) ;;
    *) echo "this expects Debian or Ubuntu, not ${ID:-unknown}" >&2; exit 1 ;;
esac

say "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# nfs-common only matters if --nfs is used, and costs nothing if not; unzip
# because a couple of the toolchains arrive as zips and a fresh install has
# no unzip, which cost one operator a 100MB download that ended in
# "unzip: not found".
apt-get install -y -qq ca-certificates curl gnupg nfs-common unzip
# ...and the guest agent only where there is a host to talk to, so Unraid can
# shut the machine down cleanly rather than pulling the plug. Nothing here is
# otherwise particular to a VM — this runs on bare metal just as well, and an
# emulator is happier there, with /dev/kvm native instead of nested.
if systemd-detect-virt --quiet --vm; then
    apt-get install -y -qq qemu-guest-agent
fi

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

# --- the stamp ----------------------------------------------------------
# A label on the daemon saying this machine is BuilderBot's sandbox.
#
# It is what BuilderBot checks before it will talk to a daemon at all, and the
# reason it checks: everything the manager does beyond compose runs a container
# as root on the far side, which is fine on a box whose whole job is being
# wrecked and reset, and is a different act entirely against a NAS, a
# workstation or the server itself. An ssh address only proves somebody typed
# one — a machine can answer Docker without being this one. So the provisioner
# says so, on the machine, and nothing else can.
#
# Written into daemon.json rather than kept beside it, because `docker info`
# reports it: BuilderBot reads the stamp over the connection it already has,
# with no second channel and nothing else on this box to keep in step.
stamp_daemon() {
    local f=/etc/docker/daemon.json label="builderbot.sandbox=1" tmp
    install -d -m 0755 /etc/docker
    if [ -s "$f" ] && grep -q "$label" "$f"; then
        return 1                      # already stamped: nothing to restart for
    fi
    if [ ! -s "$f" ]; then
        printf '{\n  "labels": ["%s"]\n}\n' "$label" > "$f"
        return 0
    fi
    # An existing file is merged rather than replaced — it may carry storage
    # or logging settings this script knows nothing about, and a sandbox that
    # came up with different storage would be a surprising way to find out.
    have_jq || apt-get install -y -qq jq >/dev/null 2>&1 || true
    if ! have_jq; then
        warn "/etc/docker/daemon.json exists and jq is not available to merge"
        warn "add \"labels\": [\"${label}\"] to it by hand, then: systemctl restart docker"
        return 1
    fi
    tmp="$(mktemp)"
    jq --arg l "$label" '.labels = ((.labels // []) - [$l] + [$l])' "$f" > "$tmp" \
        && install -m 0644 "$tmp" "$f"
    rm -f "$tmp"
    return 0
}
have_jq() { command -v jq >/dev/null 2>&1; }

if stamp_daemon; then
    # Only when it moved: a restart bounces every container on this machine,
    # and doing that on a re-run that changed nothing would be rude.
    systemctl restart docker
    say "stamped this daemon as BuilderBot's sandbox"
fi

# One implementation of "let this account in", used for both. The validation
# is the point: a key that does not parse leaves a VM nothing can ssh into,
# found from the console after the fact.
authorize() {
    local who="$1" key="$2" home
    case "$key" in
        *"-----BEGIN"*)
            echo "that is a PRIVATE key. It wants the .pub half — the private" >&2
            echo "one stays where it was made and this machine never holds it." >&2
            exit 1 ;;
    esac
    printf '%s\n' "$key" | ssh-keygen -l -f - >/dev/null 2>&1 || {
        echo "a key for ${who} does not parse as a public key. It is one line," >&2
        echo "starting ssh-ed25519 or ssh-rsa, from the .pub file." >&2
        exit 1
    }
    home="$(getent passwd "$who" | cut -d: -f6)"
    install -d -m 0700 -o "$who" -g "$who" "$home/.ssh"
    touch "$home/.ssh/authorized_keys"
    grep -qxF "$key" "$home/.ssh/authorized_keys" \
        || echo "$key" >> "$home/.ssh/authorized_keys"
    chown "$who:$who" "$home/.ssh/authorized_keys"
    chmod 0600 "$home/.ssh/authorized_keys"
}

say "user ${USER_NAME}"
id -u "$USER_NAME" >/dev/null 2>&1 || useradd -m -s /bin/bash "$USER_NAME"
usermod -aG docker "$USER_NAME"
# ...and kvm, where the host exposes it. Without this the Android emulator on
# this node runs with no hardware acceleration and is unusably slow — measured
# on bb-sandbox, where /dev/kvm is present and root:kvm 0660, and a job as the
# enrolled account got EACCES opening it. `bb emu start` warns and carries on,
# so the symptom is a boot that never finishes rather than an error naming the
# group. Absent on a host without KVM, which is why it is conditional.
getent group kvm >/dev/null 2>&1 && usermod -aG kvm "$USER_NAME"
if [ -n "$SSH_KEY" ]; then
    # Checked before it is installed, because both ways this goes wrong are
    # expensive and neither says anything at the time. A key that does not
    # parse leaves a VM nothing can ssh into, found from the console after
    # provisioning has finished and you have walked away. And a PRIVATE key
    # pasted here is a secret written onto the machine whose whole premise is
    # that it holds nothing — authorized_keys wants the .pub half, and the
    # private one never leaves BuilderBot's shielded agent.
    authorize "$USER_NAME" "$SSH_KEY"
fi

# The account that administers this machine, which is NOT the one a session
# reaches. bb runs Docker and answers ssh; admin has sudo and is the only
# account bb-sandbox will run for. Mounts, which share holds appdata, and what
# this VM is called on the network are decisions made by a person at a console,
# not side effects available to whatever is building a container this afternoon.
#
# BE CLEAR ABOUT WHAT THIS DOES NOT DO. bb is in the docker group, and the
# docker group is root on this machine to anyone who wants it — one
# `docker run -v /:/host --privileged` and the separation is over. That is not
# a hole to plug, it is the whole point of the VM: it exists to be wrecked, and
# BuilderBot needs the daemon to do its job. What the split buys is that the
# machine's OWN configuration is not one command away from a session that
# wandered — the fstab that decides whether /workspace is the projects share,
# and read-only, is behind an account nothing here logs into.
# ...and it is optional. Nothing in BuilderBot uses this account: the agent
# runs as root under systemd and drops to --user for every job, bb-sandbox
# refuses to run as anyone but root whoever invokes it, and the controller
# never names it. It is a convenience — a sudo login that is not the docker
# account — so a machine that already has one (the operator's own, a cloud
# image's ubuntu/ec2-user, or just root) should not be given a second nobody
# logs into. `--admin none` skips it, and the split it protects is unchanged:
# what matters is that the DOCKER account has no sudo.
say "admin ${ADMIN_NAME}"
if [ "$ADMIN_NAME" = none ] || [ -z "$ADMIN_NAME" ]; then
    printf '   none asked for — this machine is administered by whatever account
'
    printf '   already has root here. Nothing in BuilderBot uses one: bb-sandbox
'
    printf '   runs as root whoever calls it, and jobs run as %s.
' "$USER_NAME"
elif [ "$ADMIN_NAME" = "$USER_NAME" ]; then
    warn "--admin and --user are both ${ADMIN_NAME}: one account cannot be both"
    printf '   the split is the point — pick a different --admin\n'
else
    id -u "$ADMIN_NAME" >/dev/null 2>&1 || useradd -m -s /bin/bash "$ADMIN_NAME"
    # sudo where the distro keeps it. Debian says sudo, others say wheel, and
    # adding to a group that does not exist is an error rather than a no-op.
    for g in sudo wheel; do
        getent group "$g" >/dev/null 2>&1 && usermod -aG "$g" "$ADMIN_NAME"
    done
    [ -n "$ADMIN_KEY" ] && authorize "$ADMIN_NAME" "$ADMIN_KEY"
    # No password is set here. A provisioner that invents one has to print it,
    # and a password printed into a terminal scrollback is not a secret. Set
    # one from the console, or reach it with --admin-key.
    passwd -S "$ADMIN_NAME" 2>/dev/null | grep -q " P " || {
        [ -n "$ADMIN_KEY" ] || printf '   %s has no password and no key yet — set one from the console:\n     sudo passwd %s\n' "$ADMIN_NAME" "$ADMIN_NAME"
    }
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
# Written to a temp file and installed from it, rather than
# `install /dev/stdin` reading the heredoc directly. That form depends on
# /dev/stdin being openable BY PATH, and whether it is depends on what bash
# did with the here-document: a pipe reopens fine, a temp file that bash
# unlinked does not, and opening it then fails with exactly the message this
# produced on a real VM — "install: No such file or directory", naming
# nothing. Which of the two bash picks is a size and version question, so the
# form worked everywhere it was tried and failed on the machine it was for.
# cat reads the descriptor it was given and asks no such question.
BBSANDBOX_TMP="$(mktemp)"
cat > "$BBSANDBOX_TMP" <<'BBSANDBOX'
#!/usr/bin/env bash
#
# bb-sandbox — configure this Docker sandbox after it has been provisioned.
#
# Installed by provision.sh, which also uses it for its own mounts: this is the
# only copy of the fstab logic, so the wizard and the first run cannot drift.
#
# Root, on this machine. Run by a person at the console, and — since phase 5
# of docs/nodes.md — by the node agent, which applies the Nodes tab's desired
# mounts and stores through these same verbs as audited `system` jobs, so the
# GUI and this menu can never disagree about what the machine is configured
# to be. `sdk` is the exception to all of that: it reads the packages store
# through the controller's own bb and needs no privilege. Still deliberately NOT reachable by a session: the agent is offered
# system jobs only because it enrolled as a sandbox, and `list --json` is the
# whole of what it reads back. The docker account cannot run this at all.
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
# Everything here writes to the machine — fstab, netplan, /etc — except `sdk`,
# which only reads the packages store and needs no privilege to do it.
case "${1-}" in
    sdk) ;;
    *) [ "$(id -u)" -eq 0 ] || die "run this as root: sudo bb-sandbox" ;;
esac

# Every mount this tool manages, by mountpoint. Read from fstab rather than
# kept in a list of our own: fstab is what the machine actually boots from, and
# a second list would be a claim about it rather than a reading of it. Which
# means the type list has to hold every type a share is really mounted with,
# not only the two this tool writes — a /workspace mounted by hand with nfs4 is
# invisible to a filter that knows only nfs, and `settings` then prints a
# a path mapping with the projects share missing from it.
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

# --- the stores, read from the file the AGENT writes ---------------------
#
# One invariant, enforced from both ends: a store's path and the mount it
# sits on must agree. The agent holds the other end — it refuses to POINT a
# store at a share that is configured and not mounted, because mkdir would
# make an ordinary directory there and everything would land on this
# machine's own disk looking healthy. This end is the same failure reached
# from the console: unmounting a share a store is inside.
#
# The anti-drift is structural rather than a matching rule: there is ONE
# list of where the stores are — the agent's node.json — and this reads it
# rather than keeping a copy. A store repointed from the dashboard is
# visible here on the next command, with nothing to keep in step.
NODE_JSON=/etc/builderbot/node.json
stores_under() {
    [ -r "$NODE_JSON" ] || return 0
    python3 - "$NODE_JSON" "$1" <<'PY' 2>/dev/null || true
import json, sys
try:
    stores = json.load(open(sys.argv[1])).get("stores") or {}
except Exception:
    raise SystemExit(0)
under = sys.argv[2].rstrip("/")
for role, where in sorted(stores.items()):
    w = str(where or "").rstrip("/")
    if under and (w == under or w.startswith(under + "/")):
        print(f"{role} ({where})")
PY
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
    lineno="${hit%%:*}"
    # `#*: ` with the space, because fstab_line emits "N: LINE". Stripping only
    # "*:" left a leading space on every comparison — so an unchanged entry
    # never matched and was rewritten on every run, and "it was" printed
    # nothing, the first word of " x y" being empty.
    old="${hit#*: }"
    [ "$old" = "$line" ] && return 0
    tmp="$(mktemp)"
    awk -v n="$lineno" -v repl="$line" 'NR==n {print repl; next} {print}' \
        /etc/fstab > "$tmp"
    # cat rather than mv, so /etc/fstab keeps its own inode and permissions.
    cat "$tmp" > /etc/fstab
    rm -f "$tmp"
    # Say which half moved. A changed SOURCE is the one worth staring at — it
    # means this mountpoint now points somewhere else — and reporting an
    # options-only edit in the same words made `readonly` read as if it had
    # repointed the share.
    if [ "${old%% *}" != "${line%% *}" ]; then
        say "fstab: $path now comes from ${line%% *}"
        printf '   it was %s\n' "${old%% *}"
    else
        say "fstab: $path options are now $(awk '{print $4}' <<<"$line")"
        printf '   they were %s\n' "$(awk '{print $4}' <<<"$old")"
    fi
    # fstab changed under systemd, which caches it. Without this every later
    # mount prints "your fstab has been modified... use systemctl daemon-reload".
    have systemctl && systemctl daemon-reload 2>/dev/null || true
}

# mount_one PATH — mount it and say plainly whether it worked.
#
# `nofail` is right at boot and wrong here: it means a share that cannot mount
# does so quietly and `mount -a` still succeeds. So the SOURCE is checked, not
# merely that something is mounted — `mount -a` skips a busy mountpoint, so a
# path whose entry was just rewritten stays on the old share and looks fine.
mount_one() {
    local path="$1" want got held
    # This path only. `mount -a` mounted every entry in fstab, so one export
    # the server refuses printed its refusal on every check of every OTHER
    # mount — three copies of one unrelated failure, above the answers.
    mount "$path" 2>/dev/null || true
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
    held="$(stores_under "$path")"
    [ -n "$held" ] && printf '   %s sits inside it, so that store is on the root disk until it mounts.\n' \
        "$(printf '%s' "$held" | tr '\n' ' ')"
    printf '   On Unraid an export is a SHARE — /mnt/user/<share> — never a\n'
    printf '   pool path like /mnt/cache/<share>, which is right for a bind\n'
    printf '   mount and is not exported. Check it allows this host:\n'
    printf '     showmount -e <server>\n'
    return 1
}

# --- commands -----------------------------------------------------------
cmd_add_share() {
    local spec="${1:?usage: bb-sandbox add-share TAG:PATH[:ro]}" tag path opts=defaults
    # `:ro` mounts it read-only. The projects share wants this: the daemon
    # only ever RESOLVES bind sources there, so read-only costs nothing and a
    # container that mounts its project tree cannot scribble on the source.
    case "$spec" in *:ro) opts=defaults,ro; spec="${spec%:ro}" ;; esac
    tag="${spec%%:*}"; path="${spec#*:}"
    [ "$tag" != "$spec" ] || die "add-share wants TAG:PATH — got '$spec'"
    case "$path" in /*) ;; *) die "the mountpoint must be absolute — got '$path'" ;; esac
    add_fstab "$tag $path virtiofs $opts,nofail 0 0" "$path" && mount_one "$path"
}

cmd_add_nfs() {
    local spec="${1:?usage: bb-sandbox add-nfs HOST:EXPORT:PATH[:ro]}" host rest exp path opts=defaults
    case "$spec" in *:ro) opts=defaults,ro; spec="${spec%:ro}" ;; esac
    host="${spec%%:*}"; rest="${spec#*:}"; exp="${rest%%:*}"; path="${rest#*:}"
    # Three fields, and getting two produces nonsense rather than an error:
    # the export and the mountpoint both come out as the export.
    case "$rest" in *:*) ;; *) die "add-nfs wants HOST:EXPORT:PATH — '$spec' has no mountpoint" ;; esac
    case "$path" in /*) ;; *) die "the mountpoint must be absolute — got '$path'" ;; esac
    add_fstab "$host:$exp $path nfs $opts,nofail,_netdev 0 0" "$path" && mount_one "$path"
}

# readonly PATH [on|off] — flip an existing mount between ro and rw.
#
# The :ro suffix on add-share/add-nfs decides it when a mount is made; this
# decides it afterwards, which is what somebody actually has, and without it
# the only way to make /workspace read-only was to retype its whole spec.
#
# /workspace is the one that wants it: the daemon over here only ever RESOLVES
# bind sources in the projects share — nothing on this machine compiles or
# edits anything — so read-only costs nothing and means a container that mounts
# its project tree cannot write to your source. The data shares stay writable,
# being what they are for.
cmd_readonly() {
    local path="${1:?usage: bb-sandbox readonly PATH [on|off]}" want="${2:-on}"
    local hit line src mp fstype opts dump pass o new_opts=""
    hit="$(fstab_line "$path")"
    [ -n "$hit" ] || die "$path is not one of this machine's mounts"
    line="${hit#*:}"
    # shellcheck disable=SC2034  # mp is the field being skipped over
    read -r src mp fstype opts dump pass <<<"$line"
    # Drop whichever of ro/rw is in there and put back the one asked for, so
    # this is idempotent and cannot end up with both.
    while IFS= read -r o; do
        [ -n "$o" ] || continue
        case "$o" in ro|rw) continue ;; esac
        new_opts="${new_opts:+$new_opts,}$o"
    done < <(printf '%s\n' "${opts//,/$'\n'}")
    case "$want" in
        on)  new_opts="${new_opts:+$new_opts,}ro" ;;
        off) new_opts="${new_opts:+$new_opts,}rw" ;;
        *)   die "readonly wants on or off — got '$want'" ;;
    esac
    add_fstab "$src $path $fstype $new_opts ${dump:-0} ${pass:-0}" "$path"
    # remount first, and a full cycle only if the kernel will not take it: a
    # busy mountpoint refuses umount, and refusing to change is better than
    # leaving the share unmounted because something had a file open.
    mount -o "remount,$want" "$path" 2>/dev/null \
        || mount -o remount "$path" 2>/dev/null \
        || { umount "$path" 2>/dev/null && mount "$path" 2>/dev/null; } \
        || warn "fstab says $want, but $path could not be remounted now — it will be at the next boot"
    if [ "$want" = on ] && [ -w "$path" ]; then
        warn "$path is still writable — the export itself may be rw-only"
    else
        say "$path is now mounted ${want/on/read-only}"
        [ "$want" = off ] && say "$path is writable again"
    fi
}

cmd_remove() {
    local path="${1:?usage: bb-sandbox remove PATH [--force]}" tmp held
    [ -n "$(fstab_line "$path")" ] || die "$path is not one of this machine's mounts"
    # A store inside this share becomes a directory on the root disk the
    # moment the share goes, and the agent would then report it with the
    # root disk's free space and nothing would say the toolchains or the
    # built artifacts had stopped being reachable. So this is refused,
    # loudly, rather than warned about after the fact.
    held="$(stores_under "$path")"
    if [ -n "$held" ] && [ "${2:-}" != --force ]; then
        warn "$path holds $(printf '%s' "$held" | tr '\n' ' ')"
        printf "   Unmounting it would leave those on this machine's own disk,\n"
        printf '   where the agent would report them as healthy stores with the\n'
        printf '   root filesystem free space. Move them first — the Nodes tab\n'
        printf '   copies a store when you repoint it — or, if you mean it:\n'
        printf '     bb-sandbox remove %s --force\n' "$path"
        return 1
    fi
    [ -n "$held" ] && warn "removing it anyway; $(printf '%s' "$held" | tr '\n' ' ') will be on the root disk"
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

# bb-sandbox sdk [...] — the controller's own bb, for the questions that make
# sense on this machine.
#
# Not a second copy of anything. The agent unpacks the controller's bb into
# the packages store to run jobs with, and it has been sitting there
# unreachable: a person at this console could not ask what toolchains the
# store holds, though the tool that answers was already on the disk. This
# hands it over, with the same environment a job gets.
#
# READ-ONLY verbs only. Installing from here would go around the arbitration
# the controller keeps across every machine that shares this store — one
# install at a time, or two unpackings land in one directory — so those are
# refused with the place that does it properly.
BB_READONLY_VERBS="status root list versions images flavors env plan"

cmd_sdk() {
    local verb="${1:-status}" store user bb newest
    case " $BB_READONLY_VERBS " in
        *" $verb "*) ;;
        *) die "bb-sandbox sdk reads; it does not install. '$verb' changes the store, and
   doing it from here would go around the one-install-at-a-time rule the
   controller keeps across every machine sharing it — use the dashboard's
   Tools tab, with this node picked. Readable: $BB_READONLY_VERBS" ;;
    esac
    [ -r "$NODE_JSON" ] || die "this machine is not enrolled ($NODE_JSON is not readable) — there is no store to read"
    store="$(python3 -c 'import json,sys
print(((json.load(open(sys.argv[1])).get("stores") or {}).get("packages")) or "")' "$NODE_JSON" 2>/dev/null)"
    user="$(python3 -c 'import json,sys
print(json.load(open(sys.argv[1])).get("user") or "")' "$NODE_JSON" 2>/dev/null)"
    [ -n "$store" ] || die "this node has no packages store"
    # The newest bundle the agent has unpacked. It appears the first time a
    # package job runs here, so before that there is honestly nothing to run.
    newest="$(ls -1dt "$store"/.bb/*/scripts/bb 2>/dev/null | head -1 || true)"
    [ -n "$newest" ] || die "no bb on this machine yet — the controller unpacks one into
   ${store}/.bb the first time a package job runs on this node. Install
   something from the dashboard's Tools tab and it will be here."
    bb="$newest"
    local -a env=(env
        "SDK_ROOT=$store" "BUILDER_HOME=$store" "BB_NODE_PACKAGES=1"
        "ANDROID_HOME=$store/android" "ANDROID_SDK_ROOT=$store/android"
        "JAVA_HOME=$store/jdk"
        "PATH=$store/jdk/bin:$store/android/cmdline-tools/latest/bin:$store/android/platform-tools:$store/android/emulator:$PATH")
    # As the enrolled account when we are root, so what this reads is what a
    # job would read rather than whatever root can see.
    if [ "$(id -u)" -eq 0 ] && [ -n "$user" ] && id -u "$user" >/dev/null 2>&1; then
        exec setpriv --reuid "$user" --regid "$user" --init-groups \
            "${env[@]}" bash "$bb" sdk "$@"
    fi
    exec "${env[@]}" bash "$bb" sdk "$@"
}

cmd_list() {
    local path src state real held
    printf '\n%-24s %-34s %s\n' MOUNTPOINT SOURCE STATE
    while read -r path; do
        [ -n "$path" ] || continue
        src="$(fstab_line "$path")"; src="${src#*: }"; src="${src%% *}"
        real="$(findmnt -rno SOURCE -- "$path" 2>/dev/null || true)"
        if [ -z "$real" ]; then state="NOT MOUNTED"
        elif [ ! -w "$path" ]; then state="mounted, read-only"
        else state="mounted"; fi
        [ "$APPDATA" = "$path" ] && state="$state · container appdata"
        held="$(stores_under "$path")"
        [ -n "$held" ] && state="$state · holds $(printf '%s' "$held" | tr '\n' ' ')"
        # Where it is REALLY mounted from, not what fstab claims. Those two
        # disagree exactly when something needs attention — an entry rewritten
        # under a mount that was busy at the time — and printing fstab's
        # version called that healthy.
        if [ -n "$real" ] && [ "$real" != "$src" ]; then
            state="$state — fstab says $src"
            src="$real"
        fi
        printf '%-24s %-34s %s\n' "$path" "$src" "$state"
    done < <(ours)
    [ -n "$(ours)" ] || printf '(none yet)\n'
}

# list --json — the same facts as a machine reads them: the agent's census
# carries this, and the Nodes tab draws the operator's desired mounts against
# it. Escaped by hand, since jq may not be here.
json_str() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
cmd_list_json() {
    local path line src type opts real ro mounted first=1
    printf '['
    while read -r path; do
        [ -n "$path" ] || continue
        line="$(fstab_line "$path")"; line="${line#*: }"
        src="$(awk '{print $1}' <<<"$line")"; type="$(awk '{print $3}' <<<"$line")"
        opts="$(awk '{print $4}' <<<"$line")"
        real="$(findmnt -rno SOURCE -- "$path" 2>/dev/null || true)"
        case ",$opts," in *,ro,*) ro=true ;; *) ro=false ;; esac
        if [ -n "$real" ]; then mounted=true; else mounted=false; fi
        [ "$first" = 1 ] || printf ','
        first=0
        printf '{"path":"%s","source":"%s","type":"%s","opts":"%s","ro":%s,"mounted":%s,"real":"%s","appdata":%s}' \
            "$(json_str "$path")" "$(json_str "$src")" "$(json_str "$type")" \
            "$(json_str "$opts")" "$ro" "$mounted" "$(json_str "$real")" \
            "$([ "$APPDATA" = "$path" ] && echo true || echo false)"
    done < <(ours)
    printf ']\n'
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
    local ip pairs="" path setting
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    # BuilderBot fills in ssh:// and the bb account, so the address alone is
    # the setting unless this machine runs docker as somebody else.
    if [ "$DOCKER_USER" = bb ]; then setting="${ip:-<this-vm>}"
    else setting="ssh://${DOCKER_USER}@${ip:-<this-vm>}"; fi
    while read -r path; do
        [ -n "$path" ] || continue
        # Parity: BuilderBot mounts the same share at the same path, so the
        # mapping is an identity and the translation falls silent. A path this
        # VM has and BuilderBot does not still belongs in neither list.
        pairs="${pairs:+$pairs,}$path:$path"
    done < <(ours)
    cat <<EOF

On BuilderBot's dashboard, Nodes tab:

  Add ssh node, address:      ${setting}
  Path mapping on its row:    ${pairs:-<none yet>}

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
            remove   "take a mount out of fstab (refused if a store is in it)" \
            appdata  "choose which mount holds container appdata" \
            readonly "make a mount read-only (right for /workspace)" \
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
            readonly) ask "which mountpoint to make read-only" "/workspace" \
                       && cmd_readonly "$REPLY" on; pause ;;
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
  2) add an NFS mount            6) make a mount read-only
  3) add a virtiofs share        7) check every mount
  4) remove a mount              8) the lines to paste into BuilderBot
                                 q) quit
EOF
        read -r -p "> " n || return 0
        case "$n" in
            1) cmd_list ;;
            2) ask "HOST:EXPORT:PATH" "" && cmd_add_nfs "$REPLY" ;;
            3) ask "TAG:PATH" "" && cmd_add_share "$REPLY" ;;
            4) ask "which mountpoint" "" && cmd_remove "$REPLY" ;;
            5) ask "which mountpoint holds container appdata" "${APPDATA:-}" && cmd_appdata "$REPLY" ;;
            6) ask "which mountpoint to make read-only" "/workspace" && cmd_readonly "$REPLY" on ;;
            7) cmd_check || true ;;
            8) cmd_settings ;;
            q|Q) return 0 ;;
        esac
    done
}

case "${1-}" in
    "")          if have whiptail; then menu_whiptail; else menu_plain; fi ;;
    list)        shift; if [ "${1-}" = "--json" ]; then cmd_list_json; else cmd_list; fi ;;
    add-nfs)     shift; cmd_add_nfs "${1-}" ;;
    add-share)   shift; cmd_add_share "${1-}" ;;
    remove)      shift; cmd_remove "${1-}" ;;
    check)       cmd_check ;;
    appdata)     shift; cmd_appdata "${1-}" ;;
    readonly)    shift; cmd_readonly "${1-}" "${2-on}" ;;
    settings)    cmd_settings ;;
    sdk)         shift; cmd_sdk "$@" ;;
    -h|--help|help)
        sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) die "unknown command: $1 — try: bb-sandbox --help" ;;
esac
BBSANDBOX
install -m 0750 "$BBSANDBOX_TMP" /usr/local/sbin/bb-sandbox
rm -f "$BBSANDBOX_TMP"
# Readable and runnable by root and by the admin account's group, and by
# nothing else. The docker account cannot read it, let alone run it — which is
# most of what "bb cannot reconfigure this machine" means in practice, since
# the script refuses to run as anyone but root anyway.
if id -u "$ADMIN_NAME" >/dev/null 2>&1 && [ "$ADMIN_NAME" != "$USER_NAME" ]; then
    chgrp "$(id -gn "$ADMIN_NAME")" /usr/local/sbin/bb-sandbox 2>/dev/null || true
fi
# Checked rather than assumed: this is the step that failed silently enough to
# leave an old copy in place and a new one nowhere.
[ -s /usr/local/sbin/bb-sandbox ] \
    || { warn "bb-sandbox did not install"; exit 1; }

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
    p="${spec%:ro}"; MOUNTED+=("${p#*:}")
done
for spec in "${NFS[@]:-}"; do
    [ -n "$spec" ] || continue
    /usr/local/sbin/bb-sandbox add-nfs "$spec" || warn "$spec did not mount — see the check below"
    p="${spec%:ro}"; MOUNTED+=("${p##*:}")
done
# Checked rather than assumed, which is the difference between finding out now
# and finding out from an app that came up with no data. bb-sandbox owns the
# check for the same reason it owns the writing — one implementation — and the
# operator can run it again any day with `bb-sandbox check`.
if [ "${#MOUNTED[@]}" -gt 0 ]; then
    /usr/local/sbin/bb-sandbox check || true
fi

# Docker listens on its socket and nothing else. An open 2375 is root on this
# machine to anyone who can reach it, and BuilderBot will not talk to one
# anyway — ssh is the only way in, which is why no port has to be opened here.
if [ -f /etc/systemd/system/docker.service.d/tcp.conf ]; then
    say "closing tcp/2375, which an earlier run opened"
    rm -f /etc/systemd/system/docker.service.d/tcp.conf
    systemctl daemon-reload
    systemctl restart docker
fi

# --- the agent ------------------------------------------------------------
# With --controller and --token this machine also becomes a node: it dials
# the controller, takes jobs, and reports what it has. The agent is one
# Python file the controller itself serves — fetched with the enroll token,
# so nothing else has to be published or kept in step — and it runs under
# systemd as root ONLY so that it can drop to ${USER_NAME} for every job it
# runs, and so that phase 5's system jobs (mounts, network) have somewhere to
# run. The credential it ends up holding (/etc/builderbot/node.json, 0600)
# opens that node's own row and nothing else.
AGENT=/usr/local/sbin/builderbot-agent
UNIT=/etc/systemd/system/builderbot-agent.service
if [ -n "$CONTROLLER" ]; then
    say "agent: enrolling with ${CONTROLLER}"
    apt-get install -y -qq python3
    hdr="$(mktemp)"
    curl -fsSL -D "$hdr" -H "Authorization: Bearer ${TOKEN}" \
         "${CONTROLLER%/}/api/v1/agent/download" -o "${AGENT}.new" \
        || { warn "could not download the agent from ${CONTROLLER} — is that the dashboard's address, and is the token unused?"; rm -f "$hdr" "${AGENT}.new"; exit 1; }
    # The digest the controller says it served, against what arrived. The
    # same check the agent makes of its own updates, made once by hand here.
    want="$(tr -d '\r' < "$hdr" | awk 'tolower($1)=="x-agent-digest:"{print $2}')"
    got="sha256:$(sha256sum "${AGENT}.new" | cut -d' ' -f1)"
    rm -f "$hdr"
    if [ -n "$want" ] && [ "$want" != "$got" ]; then
        warn "the agent that arrived does not match the digest the controller sent (${got} vs ${want})"
        rm -f "${AGENT}.new"; exit 1
    fi
    chmod 755 "${AGENT}.new"; mv -f "${AGENT}.new" "$AGENT"
    systemctl stop builderbot-agent 2>/dev/null || true
    "$AGENT" enroll --controller "$CONTROLLER" --token "$TOKEN" --user "$USER_NAME" \
        --store "data=${STORE_DATA}" --store "packages=${STORE_PACKAGES}" \
        --store "cache=${STORE_CACHE}" --store "artifacts=${STORE_ARTIFACTS}"
    cat > "$UNIT" <<EOF
[Unit]
Description=BuilderBot node agent — dials in to the controller and runs its jobs
After=network-online.target docker.service
Wants=network-online.target

[Service]
ExecStart=${AGENT} run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now builderbot-agent
elif [ -f /etc/builderbot/node.json ] && [ -x "$AGENT" ]; then
    # Enrolled on an earlier run. The agent does NOT keep itself current —
    # the dashboard's Update button queues that as a job, and nothing runs
    # it unasked — so a re-run here is the console path to the same thing:
    # fetch what the controller ships with this node's own token, check it
    # against the digest the controller sends, and swap it in only when it
    # differs. The token never leaves this shell; the same check the agent
    # makes of its own updates, made here by hand.
    say "agent: already enrolled; checking the controller for a newer agent"
    ctl=""; tok=""
    read -r ctl tok < <(python3 -c 'import json; d = json.load(open("/etc/builderbot/node.json")); print(d.get("controller", ""), d.get("token", ""))' 2>/dev/null || true)
    if [ -n "$ctl" ] && [ -n "$tok" ]; then
        hdr="$(mktemp)"
        if curl -fsSL -D "$hdr" -H "Authorization: Bearer ${tok}" \
                "${ctl%/}/api/v1/agent/download" -o "${AGENT}.new" 2>/dev/null; then
            want="$(tr -d '\r' < "$hdr" | awk 'tolower($1)=="x-agent-digest:"{print $2}')"
            got="sha256:$(sha256sum "${AGENT}.new" | cut -d' ' -f1)"
            have="sha256:$(sha256sum "$AGENT" | cut -d' ' -f1)"
            if [ -n "$want" ] && [ "$want" != "$got" ]; then
                warn "the agent that arrived does not match the digest the controller sent (${got} vs ${want}); leaving the installed one"
                rm -f "${AGENT}.new"
            elif [ "$got" = "$have" ]; then
                say "agent: already current (${got:7:12})"
                rm -f "${AGENT}.new"
            else
                chmod 755 "${AGENT}.new"; mv -f "${AGENT}.new" "$AGENT"
                systemctl restart builderbot-agent 2>/dev/null || true
                say "agent: updated ${have:7:12} -> ${got:7:12} and restarted"
            fi
        else
            warn "could not fetch the agent from ${ctl} — is the controller up? The installed agent is left as it is"
            rm -f "${AGENT}.new"
        fi
        rm -f "$hdr"
    else
        warn "/etc/builderbot/node.json carries no controller or token — re-enroll with a fresh token to update"
    fi
    systemctl start builderbot-agent 2>/dev/null || true
fi

ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
# What to paste. BuilderBot fills in the scheme and the bb account, so on a
# default install the address IS the whole setting; the account is spelled out
# only when it is not the one BuilderBot would assume.
if [ "$USER_NAME" = bb ]; then SETTING="${ip:-<this-vm>}"
else SETTING="ssh://${USER_NAME}@${ip:-<this-vm>}"; fi

cat <<EOF

== done

Add it on BuilderBot's dashboard — Nodes tab, Add ssh node — with the address:

  ${SETTING}

A web UI a container here publishes is reachable at http://${ip:-<this-vm>}:<port>
directly, because this VM has its own address on your network.

What this machine mounts:
EOF

# Asked of bb-sandbox rather than echoed back from the arguments. Re-running
# with no --share and no --nfs is the ordinary way to pick up a newer
# bb-sandbox, and the old summary then printed a heading with nothing under it
# on a machine with three mounts — which reads as "none", on the exact question
# this whole design turns on.
/usr/local/sbin/bb-sandbox list || true

if [ -f /etc/builderbot/node.json ]; then
    cat <<EOF

As a node: the agent is running (systemctl status builderbot-agent) and the
Nodes tab should show this machine live within a minute. It dials out, so
nothing was opened here for it. Jobs run as ${USER_NAME}.

  sudo builderbot-agent status    what this node is, and does the controller answer
EOF
fi

cat <<EOF

Those paths have to be the ones BuilderBot uses. A compose file resolves a
relative bind against whoever runs the container, so a path that means
something different on each side is an app that comes up with no data.

Two accounts, and the split is deliberate:

  ${USER_NAME}   runs Docker and answers ssh. This is the one BuilderBot uses
        and the one a Claude session reaches. No sudo, and it cannot run
        bb-sandbox — reconfiguring this machine is not what it is for.
  ${ADMIN_NAME}  administers the machine. sudo, and the account bb-sandbox
        is readable by. Log in here to change mounts. (Optional — nothing
        here requires it; --admin none makes no such account and root, or
        whatever account you already administer this box from, does the same
        job.)

Worth knowing rather than discovering: ${USER_NAME} is in the docker group, and
that group is root on this machine to anyone who wants it. This VM exists to be
wrecked, so that is the arrangement and not a hole in it. What the split buys
is that the machine's own configuration — the fstab deciding whether /workspace
is the projects share, and read-only — is not one command away from a session
that wandered.

  sudo bb-sandbox settings     the lines to paste into BuilderBot
  sudo bb-sandbox check        is every mount really there
EOF
