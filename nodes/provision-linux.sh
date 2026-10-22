#!/usr/bin/env bash
#
# Turn a fresh Linux machine into a BuilderBot node: the Debian, RHEL, Arch and
# SUSE families, Alpine, Void and Gentoo; see "the machine's own tools" below.
#
# The sandbox exists so that a Claude session can build, run and destroy
# containers without any of that reaching the server's real ones. BuilderBot
# itself stays the container it is; this box is only ever a Docker host, and
# keeping it only that is what makes it disposable.
#
# Run it inside the VM, once:
#
#   curl -fsSLO https://raw.githubusercontent.com/aquilaelabs/builderbot/main/nodes/provision-linux.sh
#   sudo bash provision-linux.sh --key "ssh-ed25519 AAAA..."
#
# With --controller URL --token bbe_… (the Nodes tab mints the token) it also
# enrolls the machine as a node: the agent is fetched from the controller and
# left running under systemd, dialing out.
#
# It makes two accounts. `bb` runs Docker and answers ssh (the one jobs
# run as) with no sudo and no bb-sandbox, so the mounts this machine has
# stay a decision made by a person with root at a console. And `builder` is
# the one a Claude SESSION
# works as (roadmap #24): the agent runs ttyd for it, and it is in no docker
# group, because docker is root on any machine with a daemon and the account
# a session edits files as is the one thing here to keep away from that.
#
# It is safe to run again: every step checks before it acts, and a mount whose
# source has CHANGED since last time is rewritten rather than left alone.
set -euo pipefail

USER_NAME="bb"
# The session account (roadmap #24), with the uid:gid the CONTROLLER writes
# files as (Unraid's nobody:users, the container template's PUID:PGID
# defaults), so a file a session saves in its synced copy goes up to the
# controller owned exactly as one saved there is. A different uid here
# would leave the controller's tree with files the rest of the array does
# not expect, which is the one part of this that can spoil somebody's data. `none` makes no such account,
# and then this node runs no sessions.
SESSION_NAME="builder"
SESSION_UID=99
SESSION_GID=100
SSH_KEY=""
CONTROLLER=""
TOKEN=""
STORE_DATA=/var/lib/builderbot/data
STORE_TOOLCHAINS=/var/lib/builderbot/toolchains
STORE_CACHE=/var/lib/builderbot/cache
STORE_ARTIFACTS=/var/lib/builderbot/artifacts
# What a dev instance KEEPS on this node: its databases, its uploads, the
# caches its containers write. A store like the other four (R17 step 2), so
# the node reports its headroom and the Storage section edits it here.
STORE_APPDATA=/var/lib/builderbot/appdata
# --remove and its --yes, off unless asked; read before the checks run.
REMOVE=0; YES=""
declare -a SHARES=() NFS=()
CHECK_ONLY=0
# --wg-conf FILE: the node reaches the controller through WireGuard (R161),
# with the config the Nodes tab's enroll script carries.
WG_CONF=""
# --reach public: the controller is a hostname a tunnel from home publishes
# (R170); the agent verifies it by the system's CAs.
REACH=""
# --door cloudflared|tailscale: a door in for SSH (R174), switched on and
# off from the node's row: cloudflared publishing port 22 at --door-host
# with the tunnel token in --door-secret, or Tailscale joining a tailnet
# with the auth key in it and answering ssh there. --door-close22 drops
# public port 22 once the door is up.
DOOR=""; DOOR_HOST=""; DOOR_SECRET=""; DOOR_CLOSE22=0
# --firewall: a hosting-only box takes in 80 and 443 and nothing else
# (R93), its containers' published ports included; port 22 as the door
# leaves it. --feature ID (R91): one of bb-sandbox's features installed
# once the node is enrolled; --firewall is --feature firewall.
FIREWALL=0
declare -a FEATURES_WANT=()
# --machine HASH: the script was made for a node that enrolled from one
# machine (R177), and runs on that one alone.
MACHINE=""

usage() {
    cat <<'EOF'
usage: sudo bash provision-linux.sh [options]
       sudo bash provision-linux.sh --check

With no arguments this prints the help and changes nothing. With options it
provisions the machine (safe to run again: every step checks before it
acts); --check runs only the pre-flight.

The command to run is the one the dashboard's Nodes page gives you: Enroll
node mints a token and prints this line with the address and the token in
it, which is a paste rather than a questionnaire.

  --user NAME          the account Docker runs under and ssh lands on, bb by
                       default, made fresh: a name already taken on the machine
                       is refused, never taken over. Enroll node asks for it too, so the row says
                       the right one before this runs; the agent reports it
                       at enrollment either way. It gets NO sudo and cannot
                       run bb-sandbox: this is the account a session's JOBS
                       run as, and reconfiguring the machine's mounts is not
                       what it is for.
  --session-user NAME|none   the account a Claude SESSION works as on this
                       node (builder; a name already taken is refused), made with --session-uid/--session-gid
                       (99:100, the controller's PUID:PGID, so files it saves
                       are owned as the controller's are). In kvm for the emulator, in NO docker group. The
                       agent runs ttyd for it and the dashboard's terminals
                       reach it; Claude Code is installed into its home.
                       `none` makes no such account, and no sessions run here.
  --remove             take BuilderBot off this machine: the agent, the
                       accounts, the mounts it used, its stores on this disk,
                       the firewall rule, bb-sandbox itself. Docker and the
                       packages stay, so does everything on the shares. It
                       says what will go and asks; --remove --yes does not.
  --guest              provision this machine as a GUEST node: somebody's own
                       machine rather than a sandbox built to be a node.
                       Everything BuilderBot puts here is one directory
                       (~/.builderbot) and one systemd user unit, and the
                       controller changes nothing outside them: no accounts,
                       no docker, no fstab, no netplan, no firewall, and
                       Storage and Network are not offered for it. Run it as
                       yourself, with no sudo. --guest --remove takes exactly
                       that away and nothing else, because nothing else was
                       added.
  --check              only the pre-flight: say whether this machine is one
                       the script can provision (its family, its tools, its
                       init, a writable root) and change nothing. Exit 0 when
                       it is, 1 when it is not. The same checks run first on
                       every real run, before anything is installed.
  --dev                go ahead on a family this script has never been run
                       on for real (Arch, SUSE, Alpine, Void, Gentoo). Debian's
                       and RHEL's need no flag. Say how it went: a run that
                       works is what makes the next one need no flag.
  --key "ssh-ed25519 …"  a PUBLIC key, appended to this machine's
                       authorized_keys, for reaching it over ssh yourself.
                       Nothing here needs one: an enrolled node dials OUT and
                       every job arrives down that connection, so the
                       controller holds no key that logs in anywhere, and
                       nothing opens a Docker port.
  --share TAG:PATH[:ro]  a virtiofs/9p share the HYPERVISOR passes in, mounted
                       at PATH. Requires one: on bare metal there is nothing
                       to pass a share in, so use --nfs instead. Repeatable.
                       PATH MUST match the path BuilderBot uses. `:ro` mounts
                       it read-only. Never /workspace: a node's projects are
                       a synced copy there, not a share. Leave it off a share containers keep their
                       data on.
  --nfs HOST:EXPORT:PATH[:ro]   the same thing over NFS, when a share
                       cannot be passed directly. Repeatable, same `:ro`. EXPORT is the exported
                       share path (on Unraid /mnt/user/<share>/...) and not
                       a pool path like /mnt/cache/...: that spelling is for
                       bind mounts and is not what the server offers, so the
                       mount fails, quietly, because of nofail.
  --controller URL     BuilderBot's dashboard, and --token the one-time
  --token bbe_…        enrollment token its Nodes page minted. Given together,
                       this machine also becomes a NODE: the agent is
                       downloaded from the controller, enrolled, and left
                       running under systemd, dialing out; nothing here is
                       opened for it. It runs jobs as the docker account
                       (--user, bb), never as root. Re-run with a fresh token to enroll again; a
                       re-run without either leaves the enrollment alone.
  --wg-conf FILE       reach the controller through WireGuard: the config
                       (from the Nodes page's enroll script, which carries
                       it) goes in as wg-quick@bb before anything else, the
                       controller is checked through it, and the session
                       ports listen on the tunnel's address alone.
  --reach public       the controller is a hostname a tunnel publishes from
                       home (https://bb.example.com; Cloudflare Tunnel,
                       Tailscale Funnel or another): checked before
                       enrolling, and verified by the system's CAs on every
                       call rather than pinned. Such a node is hosting only,
                       with no sessions.
  --machine HASH       made for one machine (the Nodes page's Enroll script
                       on a node's row): runs there and nowhere else.
  --door cloudflared   a door in for SSH, switched on and off from the
  --door tailscale     node's row on the Nodes page. cloudflared publishes
                       this machine's port 22 at --door-host HOST (a
                       public hostname set on the tunnel in Zero Trust,
                       with the tunnel's token in --door-secret FILE);
                       Tailscale joins the tailnet with the auth key in
                       --door-secret FILE and answers ssh there (tailscale
                       ssh), with no public name. --door-close22 drops
                       port 22 from anywhere but the loopback afterwards:
                       off unless asked, since the person running this is
                       usually on that port.
  --firewall           for a hosting-only node (--session-user none): drop
                       everything coming in but 80 and 443, a container's
                       published port included (Docker's ports pass the
                       host's input rules, so its forward path is held
                       too), and port 22 unless a door closed it. Going
                       out is left alone: the box pulls images, renews
                       certificates and dials the controller.
  --feature vmhost     a VM host: KVM through libvirt, for the VMs page
                       (needs /dev/kvm; on a VM, its host passes
                       virtualization through). Each feature is bb-sandbox
                       feature install ID, run once the node has enrolled,
                       and its Features section on the Nodes page installs
                       and removes it later.
  --data PATH          the four stores, all defaulting under
  --toolchains PATH      /var/lib/builderbot/: a job's working tree and AVDs,
  --cache PATH         the toolchains installed on this node, the build
  --artifacts PATH     caches, and this node's copy of what projects built
                       (per project underneath, so one VM can be several
                       projects' node). A store may be a mount (point it at
                       one of the --share paths), and its free space is what
                       the Nodes page reports for it. A system path is refused:
                       a store is a directory of its own, since the agent
                       creates, fills and (for the cache) empties it.

Path parity is not a style preference. A compose file's bind mounts are
resolved by whatever runs the container, so a share this VM mounts at the
path BuilderBot uses means the same directory on both sides and nothing has
to translate between them. Mount it anywhere else and every compose file
naming it becomes wrong in a way that fails silently: docker creates the
missing directory and mounts it empty. The projects themselves are not a
share: each node holds a synced copy at /workspace, as BuilderBot does.
EOF
}

# --remove: the machine's own copy of bb-sandbox does the work, since it
# holds what was put here; a machine that never had one has nothing to take.
remove_if_asked() {
    [ "$REMOVE" = 1 ] || return 0
    [ "$(id -u)" -eq 0 ] || { echo "run this as root: sudo bash $0 --remove" >&2; exit 1; }
    if [ -x /usr/local/sbin/bb-sandbox ]; then
        # The copy this script carries goes in first: the machine's may
        # predate the uninstall verb (it did on the first node this was
        # tried on), and this script is the newer of the two by definition.
        tmp="$(mktemp)"
        sed -n "/^cat > \"\$BBSANDBOX_TMP\" <<'BBSANDBOX'\$/,/^BBSANDBOX\$/p" "$0" | sed '1d;$d' > "$tmp"
        if [ -s "$tmp" ] && head -1 "$tmp" | grep -q '^#!'; then
            install -m 0750 -o root -g root "$tmp" /usr/local/sbin/bb-sandbox
        fi
        rm -f "$tmp"
        exec /usr/local/sbin/bb-sandbox uninstall "$@"
    fi
    echo "nothing of BuilderBot's is installed here (no /usr/local/sbin/bb-sandbox)"
    exit 0
}

# No arguments: the help, and nothing changed. Provisioning a machine is
# what the options ask for, not what a bare invocation should do.
if [ $# -eq 0 ]; then
    usage
    exit 0
fi
while [ $# -gt 0 ]; do
    case "$1" in
        --user)  USER_NAME="$2"; shift 2 ;;
        --session-user) SESSION_NAME="$2"; shift 2 ;;
        --session-uid) SESSION_UID="$2"; shift 2 ;;
        --session-gid) SESSION_GID="$2"; shift 2 ;;
        --key)   SSH_KEY="$2"; shift 2 ;;
        --share) SHARES+=("$2"); shift 2 ;;
        --nfs)   NFS+=("$2"); shift 2 ;;
        --controller) CONTROLLER="$2"; shift 2 ;;
        --token) TOKEN="$2"; shift 2 ;;
        --wg-conf) WG_CONF="$2"; shift 2 ;;
        --reach) REACH="$2"; shift 2 ;;
        --door) DOOR="$2"; shift 2 ;;
        --door-host) DOOR_HOST="$2"; shift 2 ;;
        --door-secret) DOOR_SECRET="$2"; shift 2 ;;
        --door-close22) DOOR_CLOSE22=1; shift ;;
        --firewall) FIREWALL=1; FEATURES_WANT+=(firewall); shift ;;
        --feature) FEATURES_WANT+=("$2"); shift 2 ;;
        --machine) MACHINE="$2"; shift 2 ;;
        --data)  STORE_DATA="$2"; STORE_DATA_SET=1; shift 2 ;;
        --toolchains) STORE_TOOLCHAINS="$2"; STORE_TOOLCHAINS_SET=1; shift 2 ;;
        --cache) STORE_CACHE="$2"; STORE_CACHE_SET=1; shift 2 ;;
        --artifacts) STORE_ARTIFACTS="$2"; STORE_ARTIFACTS_SET=1; shift 2 ;;
        --appdata) STORE_APPDATA="$2"; STORE_APPDATA_SET=1; shift 2 ;;
        --guest) GUEST=1; shift ;;
        --check) CHECK_ONLY=1; shift ;;
        --remove) REMOVE=1; shift ;;
        --yes)   YES=1; shift ;;
        --dev)   DEV=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done
# ...but not a GUEST's: that footprint is one directory and one user unit in
# somebody's own home, taken away by guest_run below without root. The managed
# remove asks for root and would refuse here, which is what it did when this
# was walked (R23 step 2).
[ "${GUEST:-0}" = 1 ] || remove_if_asked ${YES:+--yes}
# One without the other is a typo, and the enrollment would fail an hour of
# apt later. Said now.
if { [ -n "$CONTROLLER" ] && [ -z "$TOKEN" ]; } || { [ -z "$CONTROLLER" ] && [ -n "$TOKEN" ]; }; then
    echo "--controller and --token go together" >&2; exit 1
fi
if [ -n "$WG_CONF" ]; then
    [ -n "$CONTROLLER" ] || { echo "--wg-conf is the tunnel an enrollment dials through: it goes with --controller and --token" >&2; exit 1; }
    [ "${GUEST:-0}" != 1 ] || { echo "--wg-conf needs root to bring a tunnel up, and a guest node runs without it" >&2; exit 1; }
    [ -r "$WG_CONF" ] || { echo "cannot read the WireGuard config ${WG_CONF}" >&2; exit 1; }
fi
if [ -n "$REACH" ]; then
    [ "$REACH" = public ] || { echo "--reach takes public" >&2; exit 1; }
    [ -z "$WG_CONF" ] || { echo "--reach public and --wg-conf are two ways to the controller: one or the other" >&2; exit 1; }
    [ -n "$CONTROLLER" ] || { echo "--reach goes with --controller and --token" >&2; exit 1; }
    case "$CONTROLLER" in https://*) ;; *) echo "through a public hostname the controller is an https hostname, not ${CONTROLLER}" >&2; exit 1 ;; esac
fi
for f in "${FEATURES_WANT[@]}"; do
    case "$f" in vmhost|firewall) ;; *) echo "--feature takes vmhost or firewall, not ${f}" >&2; exit 1 ;; esac
    [ "${GUEST:-0}" != 1 ] || { echo "--feature ${f} needs root, and a guest node runs without it" >&2; exit 1; }
done
if [ "$FIREWALL" = 1 ]; then
    [ "${GUEST:-0}" != 1 ] || { echo "--firewall needs root, and a guest node runs without it" >&2; exit 1; }
    [ "$SESSION_NAME" = none ] || { echo "--firewall is for a hosting-only node (--session-user none): it would shut the session ports the controller reaches" >&2; exit 1; }
fi
if [ -n "$DOOR" ]; then
    case "$DOOR" in cloudflared|tailscale) ;; *) echo "--door takes cloudflared or tailscale" >&2; exit 1 ;; esac
    [ "${GUEST:-0}" != 1 ] || { echo "--door installs a service, which needs root, and a guest node runs without it" >&2; exit 1; }
    [ "$DOOR" != cloudflared ] || [ -n "$DOOR_HOST" ] || { echo "--door cloudflared needs --door-host HOST, the public hostname set on the tunnel" >&2; exit 1; }
fi
# The machine this script was made for (R177): the same fingerprint the
# agent reports, so a script copied to another box stops here, before it
# changes anything there.
machine_id() {
    local v=""
    for f in /etc/machine-id /sys/class/dmi/id/product_uuid; do
        [ -r "$f" ] || continue
        v="$(tr -d ' \n\r\t' < "$f" 2>/dev/null || true)"
        [ -n "$v" ] && { printf '%s' "$v" | sha256sum | cut -c1-32; return 0; }
    done
    return 1
}
if [ -n "$MACHINE" ]; then
    here="$(machine_id || true)"
    if [ -z "$here" ]; then
        echo "this script was made for one machine and this one has no machine id to compare: make a new script on the Nodes page (Enroll node)" >&2; exit 1
    elif [ "$here" != "$MACHINE" ]; then
        echo "this script was made for another machine (the node that enrolled with it): it does nothing here. Enroll this machine with a script of its own from the Nodes page" >&2; exit 1
    fi
fi
case "$TOKEN" in
    ""|bbe_*) ;;
    *) echo "that is not an enrollment token (they start bbe_); mint one on the Nodes tab" >&2; exit 1 ;;
esac

say() { printf '\n== %s\n' "$*"; }
warn() { printf '\n!! %s\n' "$*" >&2; }

# ---- a GUEST node: somebody's own machine (roadmap R23) ---------------------
#
# The managed shape below owns the box: it makes accounts, installs docker,
# writes fstab and netplan and a firewall rule, and the controller edits all
# of them afterwards through the config plane. That is right for a sandbox VM
# built to be one and wrong for a laptop somebody also works on.
#
# A guest is the other class. Everything BuilderBot puts here lives in ONE
# directory and ONE service unit, both removable in a line, and the controller
# changes nothing outside them: Storage and Network refuse on a guest node and
# say why (the per-verb gate, 6 Sep). No root is used or asked for, which is
# also what stops this reaching anything it should not.
#
# Deliberately the same footprint provision-macos.sh lays down, in systemd's
# words rather than launchd's, so "what is on my machine" has one answer
# whichever kind of machine it is.
guest_foot() { printf '%s' "${BUILDERBOT_HOME:-$HOME/.builderbot}"; }
GUEST_UNIT_NAME="builderbot-agent.service"

guest_unit() { printf '%s' "$HOME/.config/systemd/user/$GUEST_UNIT_NAME"; }

guest_remove() {
    local foot unit
    foot="$(guest_foot)"; unit="$(guest_unit)"
    if [ -z "${YES:-}" ]; then
        printf 'This takes off %s (its stores included) and %s.\nNothing else was put on this machine. Continue? [y/N] ' \
               "$foot" "$unit"
        read -r a < /dev/tty || a=""
        case "$a" in y|Y|yes|YES) ;; *) echo "nothing changed"; exit 0 ;; esac
    fi
    systemctl --user disable --now "$GUEST_UNIT_NAME" 2>/dev/null || true
    rm -f "$unit"
    systemctl --user daemon-reload 2>/dev/null || true
    rm -rf "$foot"
    say "gone: $foot and $unit"
    echo "Nothing else was added, so nothing else has to be taken away."
    exit 0
}

guest_run() {
    local foot unit agent node_json toolchains py
    foot="$(guest_foot)"; unit="$(guest_unit)"
    [ "$(id -u)" != 0 ] || {
        warn "do not run --guest as root: the whole point is a footprint your own account owns, in your own home. Run it as yourself, with no sudo."
        exit 1; }
    [ "${REMOVE:-0}" = 1 ] && guest_remove

    say "checking this machine"
    local bad=0
    for t in python3 curl systemctl; do
        command -v "$t" >/dev/null 2>&1 || { warn "$t is not on PATH, and a guest node needs it"; bad=1; }
    done
    systemctl --user show-environment >/dev/null 2>&1 \
        || { warn "systemd --user is not running for this account, so there is nowhere to put the agent's unit. On a server, 'sudo loginctl enable-linger $(id -un)' and log in again."; bad=1; }
    [ "$bad" = 0 ] || exit 1
    [ "${CHECK_ONLY:-0}" = 0 ] || { say "this machine can be a guest node"; exit 0; }
    [ -n "$CONTROLLER" ] && [ -n "$TOKEN" ] \
        || { warn "--guest needs --controller and --token, from Enroll node on the Nodes page"; exit 1; }

    say "the footprint: $foot"
    mkdir -p "$foot/bin" "$foot/log" "$foot/runner"
    chmod 700 "$foot"
    # The four store paths default to /var/lib/builderbot for the MANAGED
    # shape, which a guest has no root to make and no business making. So a
    # guest keeps them in the footprint unless a flag actually named one,
    # which is what the _SET vars are for: `${STORE_X:-...}` never falls back
    # here, because the default is not empty. Found by running this for real,
    # where the agent said it could not create /var/lib/builderbot/artifacts.
    local s_data s_cache s_art s_app
    s_data="${STORE_DATA_SET:+$STORE_DATA}";           s_data="${s_data:-$foot/data}"
    s_cache="${STORE_CACHE_SET:+$STORE_CACHE}";        s_cache="${s_cache:-$foot/cache}"
    s_art="${STORE_ARTIFACTS_SET:+$STORE_ARTIFACTS}";  s_art="${s_art:-$foot/artifacts}"
    s_app="${STORE_APPDATA_SET:+$STORE_APPDATA}";      s_app="${s_app:-$foot/appdata}"
    toolchains="${STORE_TOOLCHAINS_SET:+$STORE_TOOLCHAINS}"; toolchains="${toolchains:-$foot/toolchains}"
    mkdir -p "$toolchains" "$s_data" "$s_cache" "$s_art" "$s_app"
    agent="$foot/bin/builderbot-agent"
    node_json="$foot/node.json"

    say "the agent, from ${CONTROLLER}"
    local hdr want got
    hdr="$(mktemp)"
    curl -fsSL -D "$hdr" -H "Authorization: Bearer ${TOKEN}" \
         "${CONTROLLER%/}/api/v1/agent/download" -o "${agent}.new" \
        || { warn "could not download the agent from ${CONTROLLER}: is that the dashboard's address, and is the token unused?"
             rm -f "$hdr" "${agent}.new"; exit 1; }
    want="$(tr -d '\r' < "$hdr" | awk 'tolower($1)=="x-agent-digest:"{print $2}')"
    got="sha256:$(sha256sum "${agent}.new" | cut -d' ' -f1)"
    rm -f "$hdr"
    if [ -n "$want" ] && [ "$want" != "$got" ]; then
        warn "the agent that arrived does not match the digest the controller sent (${got} vs ${want})"
        rm -f "${agent}.new"; exit 1
    fi
    chmod 755 "${agent}.new"; mv -f "${agent}.new" "$agent"

    # Enrolled as this account, with every store under the footprint unless a
    # flag pointed one somewhere else. The credential it keeps is this node's
    # own row and nothing more.
    say "enrolling as $(id -un)"
    systemctl --user stop "$GUEST_UNIT_NAME" 2>/dev/null || true
    BUILDERBOT_NODE_JSON="$node_json" python3 "$agent" enroll \
        --controller "$CONTROLLER" --token "$TOKEN" --user "$(id -un)" \
        --store "data=$s_data" --store "toolchains=$toolchains" \
        --store "cache=$s_cache" --store "artifacts=$s_art" \
        --store "appdata=$s_app" \
        || { warn "enrolment failed: the token is good once and for a day, so mint a fresh one if this is a second try"; exit 1; }

    say "the user unit: $GUEST_UNIT_NAME"
    py="$(command -v python3)"
    mkdir -p "$(dirname "$unit")"
    cat > "$unit" <<EOF
[Unit]
Description=BuilderBot node agent (guest footprint)
After=network-online.target

[Service]
ExecStart=${py} ${agent} run
Environment=BUILDERBOT_NODE_JSON=${node_json}
Environment=BUILDERBOT_RUNNER_DIR=${foot}/runner
Restart=always
RestartSec=5
StandardOutput=append:${foot}/log/agent.log
StandardError=append:${foot}/log/agent.log

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now "$GUEST_UNIT_NAME"
    # Without lingering the unit stops at logout, which on a machine somebody
    # uses is most of the time. Asked for, never forced: it wants root or a
    # polkit rule, and a guest run has neither by design.
    if ! loginctl show-user "$(id -un)" -p Linger 2>/dev/null | grep -q 'Linger=yes'; then
        loginctl enable-linger "$(id -un)" 2>/dev/null \
            || warn "this account does not linger, so the agent stops when you log out. 'sudo loginctl enable-linger $(id -un)' fixes that, and is the only root this ever wants."
    fi

    say "done"
    echo "The whole of it is $foot and $unit."
    echo "Take it away with: bash $0 --guest --remove"
    echo "Storage and Network are not offered for a guest node: this machine's"
    echo "mounts and addresses stay yours."
    exit 0
}

[ "${GUEST:-0}" = 1 ] && guest_run

# This is for a VM, and a container is not one. BuilderBot's own base is
# Ubuntu and runs as root under `docker exec`, so both checks above pass there
# and the script would go on to install seven packages before failing on
# `systemctl enable --now docker`: a container has no systemd, and the error
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
        printf '   Run it in a console on the VM itself. It needs an init system,\n'
        printf '   which a container does not have, and it edits fstab.\n'
    fi
    exit 1
fi

[ "$(id -u)" -eq 0 ] || { echo "run this with sudo" >&2; exit 1; }
ID=""; ID_LIKE=""; PRETTY_NAME=""; VERSION_ID=""; VERSION_CODENAME=""; UBUNTU_CODENAME=""
[ -r /etc/os-release ] && . /etc/os-release
: "$VERSION_ID" "$VERSION_CODENAME" "$UBUNTU_CODENAME"   # the family file's to read
# --- the machine's own tools -------------------------------------------------
# One script, many distributions. Everything BuilderBot's own (the accounts,
# the stores, fstab, the agent) is the same on all of them, because none of
# it is the distribution's. What differs is the package manager, where Docker
# and ttyd come from, who owns the firewall, and which init system runs a
# service. FAMILY and INIT decide those, through the small functions below;
# the rest of the script calls the functions and never a distribution's tool
# by name. The families are read from ID and ID_LIKE, so a derivative lands
# with its parent: Mint, Pop!_OS and Kali with Debian; Fedora, CentOS Stream,
# Rocky and Alma with RHEL; Manjaro, EndeavourOS and CachyOS with Arch; Leap
# and Tumbleweed with SUSE. Alpine, Void and Gentoo stand on their own.
#
# What has been RUN, and what has only been written: Ubuntu and Debian are
# what this grew up on. Rocky is written against the RHEL family's documented
# commands. The rest (Arch, SUSE, Alpine, Void, Gentoo) are best effort
# from their documentation, warn rather than abort where a package is not
# where it was expected, and want a first run to shake out. Say so in the
# repository when one is proven.
#
# Nothing here exits. A machine the script cannot take is reported by the
# pre-flight below, beside everything else it found, so one run says the
# whole of what is wrong rather than the first thing.
# The families this script has been run on for real: Debian's (Ubuntu
# 24.04 and 26.04, Debian 13), RHEL's (Rocky, Alma, CentOS Stream, Fedora),
# Arch's and openSUSE's (R97's walk, 21 Oct). The others are
# written to each family's tools and never run (dev, in the dashboard's
# word), so they need --dev to proceed, and a run that works is what moves
# one onto this list.
VETTED_FAMILIES=" deb rhel arch suse "
DEV="${DEV:-0}"
FAMILY=""; FAMILY_WHY=""
_ids=" ${ID:-} ${ID_LIKE:-} "
case "$_ids" in
    *" debian "*|*" ubuntu "*|*" raspbian "*)          FAMILY=deb ;;
    *" rhel "*|*" fedora "*|*" centos "*|*" rocky "*|*" almalinux "*) FAMILY=rhel ;;
    *" arch "*|*" archlinux "*|*" manjaro "*)           FAMILY=arch ;;
    *" suse "*|*" opensuse "*|*" opensuse-leap "*|*" opensuse-tumbleweed "*|*" sles "*) FAMILY=suse ;;
    *" alpine "*)   FAMILY=alpine ;;
    *" void "*)     FAMILY=void ;;
    *" gentoo "*)   FAMILY=gentoo ;;
    *" nixos "*)
        FAMILY_WHY="NixOS is configured declaratively, and this script installs things imperatively: a docker daemon, accounts, fstab and a service dropped into /etc would not survive the next nixos-rebuild. The honest form is a NixOS module declaring the same machine, which is not written yet." ;;
    *" slackware "*)
        FAMILY_WHY="Slackware ships no Docker and no service manager this script can hand a unit to; a machine without Docker is a guest node (roadmap R23), which this does not build yet." ;;
    *)
        if [ -z "${ID:-}" ]; then
            FAMILY_WHY="/etc/os-release is missing or names no ID, so there is nothing to tell what this is."
        else
            FAMILY_WHY="${PRETTY_NAME:-$ID} is not a family this knows (ID=${ID} ID_LIKE=${ID_LIKE:-none}). It handles the Debian, RHEL, Arch and SUSE families, and Alpine, Void and Gentoo; a derivative of one of those is recognized by its ID_LIKE. A new family is a case in this script's 'the machine's own tools' block."
        fi ;;
esac
# The family's own file: the one beside this script, which the enroll script
# built from the dashboard puts there for the system picked there (R204),
# else this repository's for the detected family, for a hand run from a
# checkout. A picked family that is not this machine's is refused by name:
# a script built for Ubuntu does nothing to a Rocky machine but say so.
_here="$(cd "$(dirname "$0")" && pwd)"
FAMILY_PICKED=""; FAMILY_NAME=""; FAMILY_IDS=""; FAMILY_NEED=""
if [ -f "$_here/provision-family.sh" ]; then
    # shellcheck source=/dev/null
    . "$_here/provision-family.sh"
elif [ -n "$FAMILY" ] && [ -f "$_here/families/$FAMILY.sh" ]; then
    # shellcheck source=/dev/null
    . "$_here/families/$FAMILY.sh"
fi
# The family file says which os-release IDs it is for; the machine's ID and
# ID_LIKE must name one of them. A match makes it the family whatever the
# table above said (a derivative the table has not met); a miss is refused.
if [ -n "$FAMILY_PICKED" ]; then
    _mine=0
    for _i in ${ID:-} ${ID_LIKE:-}; do
        case " $FAMILY_IDS " in *" $_i "*) _mine=1 ;; esac
    done
    if [ "$_mine" = 1 ]; then
        FAMILY="$FAMILY_PICKED"; FAMILY_WHY=""
    else
        FAMILY_WHY="this script was built for ${FAMILY_NAME}, and this machine is ${PRETTY_NAME:-${ID:-unknown}}${FAMILY:+ (the ${FAMILY} family)}: build it again from Enroll node with the machine's system picked"
        FAMILY=""
    fi
elif [ -n "$FAMILY" ]; then
    FAMILY_WHY="no family file for ${FAMILY} is beside this script (nodes/families/${FAMILY}.sh): a script built from Enroll node carries it"
    FAMILY=""
fi
INIT=""
if [ -d /run/systemd/system ]; then INIT=systemd
elif command -v rc-service >/dev/null 2>&1; then INIT=openrc
elif [ -d /etc/sv ] && command -v sv >/dev/null 2>&1; then INIT=runit
fi

is_vm() {
    if command -v systemd-detect-virt >/dev/null 2>&1; then systemd-detect-virt --quiet --vm
    else grep -qi hypervisor /proc/cpuinfo 2>/dev/null; fi
}
# The services, whichever init runs this machine: the core's, never a family
# file's, since every family has one of these three (B166: the split into
# family files took them out and put them nowhere).
# svc_enable NAME: a service the DISTRIBUTION ships (docker, the guest
# agent), started now and at boot, whichever init runs this machine.
svc_enable() {
    case "$INIT" in
        systemd) systemctl enable --now "$1" ;;
        openrc)  rc-update add "$1" default >/dev/null 2>&1 || true; rc-service "$1" start >/dev/null 2>&1 || rc-service "$1" restart ;;
        runit)   [ -d "/etc/sv/$1" ] || { echo "no runit service /etc/sv/$1" >&2; return 1; }
                 ln -sfn "/etc/sv/$1" "/var/service/$1"
                 # runsvdir scans /var/service every five seconds; until it
                 # has, sv cannot reach the service and every verb fails.
                 for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
                     [ -e "/var/service/$1/supervise/ok" ] && break; sleep 1
                 done
                 sv start "$1" >/dev/null 2>&1 || true ;;
    esac
}
svc_restart() {
    case "$INIT" in
        systemd) systemctl restart "$1" ;;
        openrc)  rc-service "$1" restart ;;
        runit)   sv restart "$1" ;;
    esac
}
svc_stop() {
    case "$INIT" in
        systemd) systemctl stop "$1" 2>/dev/null || true ;;
        openrc)  rc-service "$1" stop 2>/dev/null || true ;;
        runit)   sv stop "$1" 2>/dev/null || true ;;
    esac
}
svc_active() {
    case "$INIT" in
        systemd) systemctl is-active --quiet "$1" ;;
        openrc)  rc-service "$1" status >/dev/null 2>&1 ;;
        runit)   sv status "$1" 2>/dev/null | grep -q '^run' ;;
    esac
}
# svc_install NAME DESCRIPTION COMMAND: a service of OUR OWN (the agent),
# written the way this init wants one: a unit, an OpenRC script under
# supervise-daemon, or a runit directory. Rewritten on every run, then
# enabled and (re)started. Ordered after the network mounts (remote-fs,
# netmount): a store on a share is there before the agent's first census.
# svc_install NAME DESC CMD [EXTRA]: the service, whichever init this is.
# EXTRA is extra [Service] lines for systemd, where a unit's settings decide
# what a stop reaches; the other inits take the command and nothing else.
svc_install() {
    local name="$1" desc="$2" cmd="$3" extra="${4:-}"
    case "$INIT" in
        systemd)
            cat > "/etc/systemd/system/${name}.service" <<EOF
[Unit]
Description=${desc}
After=network-online.target remote-fs.target docker.service
Wants=network-online.target

[Service]
ExecStart=${cmd}
Restart=always
RestartSec=5
${extra}

[Install]
WantedBy=multi-user.target
EOF
            systemctl daemon-reload
            systemctl enable "$name" >/dev/null 2>&1
            systemctl restart "$name" ;;
        openrc)
            cat > "/etc/init.d/${name}" <<EOF
#!/sbin/openrc-run
# ${desc}
description="${desc}"
supervisor=supervise-daemon
command="${cmd%% *}"
command_args="${cmd#* }"
# Kept, where OpenRC has no journal: supervise-daemon sent it to /dev/null.
# The agent keeps the file to its size (cap_logs) and bb logs --node reads it.
output_log="/var/log/${name}.log"
error_log="/var/log/${name}.log"
respawn_delay=5
depend() { need net; use netmount; after docker; }
EOF
            chmod 0755 "/etc/init.d/${name}"
            rc-update add "$name" default >/dev/null 2>&1 || true
            rc-service "$name" restart >/dev/null 2>&1 || rc-service "$name" start ;;
        runit)
            install -d -m 0755 "/etc/sv/${name}"
            cat > "/etc/sv/${name}/run" <<EOF
#!/bin/sh
# ${desc}
# Kept, where runit has no journal and no log service here: it went to
# runsvdir and nowhere. The agent keeps the file to its size (cap_logs).
exec ${cmd} >> "/var/log/${name}.log" 2>&1
EOF
            chmod 0755 "/etc/sv/${name}/run"
            ln -sfn "/etc/sv/${name}" "/var/service/${name}"
            sv restart "$name" >/dev/null 2>&1 || sv start "$name" >/dev/null 2>&1 || true ;;
    esac
}

# pkg_refresh, pkg and pkg_names are the family's (nodes/families/*.sh),
# sourced below once the machine's family is known.

# --- pre-flight: is this machine one this script can provision? -------------
# Before a single package lands. The family says what the machine CLAIMS to
# be; these check what it actually has, because the variants that go wrong
# are the ones whose os-release looks fine: an immutable Fedora whose dnf
# refuses, a MicroOS whose /usr is read-only, an Ubuntu Core with snaps and
# no apt, a Debian that dropped systemd, a live image running from RAM. A
# FAIL stops the run here with every finding printed, so one run says the
# whole of what is wrong; a WARN is something the run can survive but the
# operator should know, and is repeated at the end.
say "checking this machine"
CHECK_FAILED=0
declare -a WARNINGS=()
chk() {
    case "$1" in
        ok)   printf '   ok    %s\n' "$2" ;;
        warn) printf '   WARN  %s\n' "$2"; WARNINGS+=("$2") ;;
        fail) printf '   FAIL  %s\n' "$2"; CHECK_FAILED=1 ;;
    esac
}
# 1. what it is, and whether that is a family this handles
if [ -n "$FAMILY" ]; then chk ok "${PRETTY_NAME:-$ID}: the ${FAMILY} family"
else chk fail "$FAMILY_WHY"; fi
# 2. the tools the family implies are really here: a derivative can claim a
#    parent whose package manager it replaced (Ubuntu Core has no apt;
#    Silverblue's dnf is a stub that refuses)
if [ -n "$FAMILY" ]; then
    need="$FAMILY_NEED"
    missing=""
    for t in $need; do command -v "$t" >/dev/null 2>&1 || missing="${missing} ${t}"; done
    if [ -z "$missing" ]; then chk ok "package manager: ${need%% *}"
    else chk fail "the ${FAMILY} family's package manager is not here (missing:${missing}): a variant that replaced it, which this script cannot install onto"; fi
fi
# 3. the immutable and image-based variants, by the marks they leave: these
#    have a package manager on PATH and still cannot be installed onto
if [ -f /run/ostree-booted ]; then
    chk fail "this is an OSTree (image-based) system, such as Fedora Silverblue/Kinoite/CoreOS/IoT or RHEL image mode: packages are layered by rpm-ostree and a reboot, not installed; use the ordinary Server/Minimal image instead"
elif command -v transactional-update >/dev/null 2>&1 && ! touch /usr/.bb-probe 2>/dev/null; then
    chk fail "this is a transactional system (openSUSE MicroOS/Aeon, SLE Micro): /usr is read-only and changes want transactional-update and a reboot; use Leap or Tumbleweed instead"
elif [ -d /snap/core ] && ! command -v apt-get >/dev/null 2>&1; then
    chk fail "this is Ubuntu Core: snaps only, no apt, no ordinary accounts; use Ubuntu Server instead"
elif [ "$FAMILY" = alpine ] && [ "$(awk '$2=="/"{print $3}' /proc/mounts 2>/dev/null)" = tmpfs ]; then
    chk fail "this Alpine runs from RAM (diskless mode: / is a tmpfs): nothing installed survives a reboot; run setup-alpine with the sys disk mode first"
else
    rm -f /usr/.bb-probe
    chk ok "an ordinary installed system, not an image-based one"
fi
# 4. a writable root: /etc and /usr/local take files, /var takes the stores
for d in /etc /usr/local /var/lib; do
    if [ -d "$d" ] && touch "$d/.bb-probe" 2>/dev/null; then rm -f "$d/.bb-probe"
    else chk fail "$d is not writable: a read-only root, a live image, or a mount this cannot change"; fi
done
# 5. an init this can hand a service to, and one that is actually running
#    (systemd's directory exists in a chroot too, where systemctl does not work)
case "$INIT" in
    systemd)
        st="$(systemctl is-system-running 2>/dev/null || true)"
        case "$st" in
            running|degraded|starting|maintenance) chk ok "init: systemd (${st})" ;;
            *) chk fail "systemd is on the disk but not running this machine (is-system-running says '${st:-nothing}'): a chroot, a container, or a rescue shell" ;;
        esac ;;
    openrc) chk ok "init: OpenRC" ;;
    runit)  if [ -d /var/service ] || [ -d /run/runit ]; then chk ok "init: runit"
            else chk fail "runit is installed but no service directory is live (/var/service)"; fi ;;
    *)      chk fail "no init this knows: not systemd, OpenRC or runit. It writes a service for the agent and would have nothing to run it" ;;
esac
# 6. the architecture: what Docker, the agent and the Actions runner build for
case "$(uname -m)" in
    x86_64|aarch64) chk ok "architecture: $(uname -m)" ;;
    armv7l) chk warn "architecture armv7l (32-bit ARM): Docker and ttyd have builds; the Actions runner, the JDK and the emulator do not, so this can be a Docker node and little else" ;;
    *) chk fail "architecture $(uname -m): nothing this installs is built for it" ;;
esac
# 7. what Docker needs from the kernel: cgroups, and the overlay filesystem
if [ -f /sys/fs/cgroup/cgroup.controllers ]; then chk ok "cgroups v2"
elif [ -d /sys/fs/cgroup/memory ]; then chk warn "cgroups v1: Docker still runs, but current distributions and the emulator's memory accounting expect v2"
else chk fail "no cgroup filesystem is mounted, so Docker cannot start containers here"; fi
if grep -qw overlay /proc/filesystems 2>/dev/null || modprobe -n overlay 2>/dev/null; then chk ok "overlay filesystem"
else chk warn "the overlay filesystem is not available, so Docker will fall back to a slower storage driver"; fi
if [ -e /dev/kvm ]; then chk ok "/dev/kvm: the emulator can be accelerated"
else chk warn "no /dev/kvm: the Android emulator would run unaccelerated (a VM needs nested virtualization on its host)"; fi
# 8. room: Docker images, the toolchain store and a build all land on / by default
avail_mb="$(df -Pm / 2>/dev/null | awk 'NR==2{print $4}')"
if [ -n "$avail_mb" ] && [ "$avail_mb" -lt 10240 ]; then chk warn "only $((avail_mb / 1024))G free on /: the toolchain store alone wants tens of gigabytes; point the stores at a share, or grow the disk"
elif [ -n "$avail_mb" ]; then chk ok "$((avail_mb / 1024))G free on /"; fi
# 9. the network: Docker's repository and the controller, if one was named.
#    Warnings, not failures: an offline node is still a node, but every
#    install below will fail and it is better said once here.
if command -v curl >/dev/null 2>&1; then
    if curl -fsI --max-time 10 https://download.docker.com/ >/dev/null 2>&1; then chk ok "internet: download.docker.com answers"
    else chk warn "download.docker.com does not answer: no package will download; an offline node needs its packages brought in by hand"; fi
    if [ -n "$CONTROLLER" ]; then
        # A failure, not a warning (11 Oct): a run that went on past this
        # closed port 22 for a door and then could not enroll, and the
        # person came back in through the KVM. Nothing below is worth doing
        # when the controller cannot be reached.
        if curl -fsk --max-time 10 -o /dev/null "${CONTROLLER%/}/api/v1/agent/download" 2>/dev/null \
           || curl -sk --max-time 10 -o /dev/null -w '%{http_code}' "${CONTROLLER%/}/" 2>/dev/null | grep -q '^[234]'; then
            chk ok "controller: ${CONTROLLER} answers"
        else chk fail "controller ${CONTROLLER} does not answer from here, so enrollment would fail: check the address and that the dashboard is up"; fi
    fi
else
    chk warn "no curl yet; it is installed below, and the network is untested until then"
fi
# 10. the accounts: what the script uses to make them
if command -v useradd >/dev/null 2>&1 && command -v groupadd >/dev/null 2>&1; then chk ok "useradd/groupadd"
elif [ "$FAMILY" = alpine ]; then chk ok "useradd: from the shadow package, installed below"
else chk warn "no useradd/groupadd: the shadow tools are missing and the accounts step will fail"; fi
if [ "$CHECK_FAILED" = 1 ]; then
    printf '\n'
    warn "this machine is not one this script can provision; nothing was changed"
    exit 1
fi
case "$VETTED_FAMILIES" in
    *" $FAMILY "*) ;;
    *)  if [ "$DEV" = 1 ]; then
            chk warn "the $FAMILY family has not been provisioned for real before: --dev given, so trying it"
        else
            printf '\n'
            warn "the $FAMILY family has not been provisioned for real before; run again with --dev to try it, and say how it went; nothing was changed"
            exit 1
        fi ;;
esac
if [ "$CHECK_ONLY" = 1 ]; then
    printf '\n   %s can be provisioned by this script' "${PRETTY_NAME:-$ID}"
    [ "${#WARNINGS[@]}" -eq 0 ] && printf '.\n' || printf ', with %d warning(s) above.\n' "${#WARNINGS[@]}"
    exit 0
fi

say "packages"
pkg_refresh
# Only what the agent, Docker and the mounts need. The NFS client matters if
# --nfs is used and costs nothing if not. What a TOOLCHAIN needs from the
# machine (Chromium's forty libraries, say) is that toolchain's business:
# its recipe in config/toolchains.json names them under `system`, per family,
# and the agent installs them when the toolchain is.
# shellcheck disable=SC2046  # the names are meant to split
pkg $(pkg_names base)
command -v curl >/dev/null 2>&1 || pkg curl >/dev/null 2>&1 || warn "curl did not install, so every download below will fail"
# ...and the guest agent only where there is a host to talk to, so Unraid can
# shut the machine down cleanly rather than pulling the plug. Nothing here is
# otherwise particular to a VM: this runs on bare metal just as well, and an
# emulator is happier there, with /dev/kvm native instead of nested.
if is_vm; then
    # shellcheck disable=SC2046
    pkg $(pkg_names guest) 2>/dev/null && svc_enable "$(pkg_names guestsvc)" >/dev/null 2>&1 \
        || warn "the qemu guest agent did not install, so Unraid will pull the plug instead of shutting this VM down"
fi

# --- the tunnel to the controller (R161) ------------------------------------
# Before anything that has to reach the controller, and before an hour of
# Docker: a tunnel that does not come up is said now. The config is the one
# the person's router made, narrowed by the Nodes tab to route the
# controller's address alone, so this machine's own traffic is untouched.
# The home end (the router) is what keeps it one-way; nothing done here
# could, since root here could undo it.
WG_ADDR=""
if [ -n "$WG_CONF" ]; then
    say "tunnel: WireGuard to the controller"
    [ "$INIT" = systemd ] || { warn "the tunnel is brought up by wg-quick@ under systemd, and this machine runs ${INIT:-no init this knows}"; exit 1; }
    # shellcheck disable=SC2046
    command -v wg-quick >/dev/null 2>&1 || pkg $(pkg_names wg) \
        || { warn "wireguard-tools did not install, so there is no tunnel to enroll through"; exit 1; }
    install -d -m 0700 /etc/wireguard
    install -m 0600 "$WG_CONF" /etc/wireguard/bb.conf
    WG_ADDR="$(awk -F= 'tolower($1) ~ /^ *address *$/ {gsub(/ /, "", $2); n = split($2, a, ","); for (i = 1; i <= n; i++) if (a[i] !~ /:/) { sub(/\/.*/, "", a[i]); print a[i]; exit }}' /etc/wireguard/bb.conf)"
    systemctl enable wg-quick@bb >/dev/null 2>&1 || true
    systemctl restart wg-quick@bb || { warn "wg-quick@bb did not start: journalctl -u wg-quick@bb says why"; exit 1; }
    # Through the tunnel or not at all: any HTTP answer is the controller
    # answering. A handshake can take a few seconds after the interface.
    reached=""
    for _ in $(seq 1 15); do
        code="$(curl -s -o /dev/null -m 4 -w '%{http_code}' "${CONTROLLER%/}/api/v1/agent/download" || true)"
        case "$code" in 000|"") sleep 2 ;; *) reached=1; break ;; esac
    done
    if [ -z "$reached" ]; then
        warn "the tunnel is up (${WG_ADDR}) but ${CONTROLLER} does not answer through it. On the router: is this peer enabled, does it route the tunnel to the LAN, and is TCP to the controller's port allowed from ${WG_ADDR}? \`wg show bb\` says whether a handshake happened"
        exit 1
    fi
    printf '   up as %s; %s answers through it\n' "$WG_ADDR" "$CONTROLLER"
fi
# Through a public hostname (R170): nothing to bring up here, since the
# tunnel is at home; that the hostname answers, with a certificate the
# system trusts, is checked now rather than after an hour of Docker.
if [ "$REACH" = public ]; then
    say "reach: ${CONTROLLER} through its public hostname"
    # The agent's own download with the enrollment token, which is what
    # the enrollment below will do: only a 200 means the way is open. A
    # tunnel that answers something else is said by what it said (a 502
    # was taken as an answer once, and the run went on to close port 22
    # and fail to enroll, 11 Oct).
    # The headers too: a 200 is the controller only when it carries the
    # agent's digest. A hostname whose path rule pointed somewhere else
    # answered 200 with nothing in it, the run installed an empty agent,
    # and the enrollment "succeeded" without reaching home (11 Oct).
    rhdr="$(mktemp)"
    code="$(curl -s -o /dev/null -D "$rhdr" -m 15 -H "Authorization: Bearer ${TOKEN}" -w '%{http_code}' "${CONTROLLER%/}/api/v1/agent/download" || true)"
    rdig="$(tr -d '\r' < "$rhdr" | awk 'tolower($1)=="x-agent-digest:"{print $2}')"
    rm -f "$rhdr"
    if [ "$code" = 200 ] && [ -z "$rdig" ]; then
        warn "${CONTROLLER} answers 200 on the agent's API, but not as BuilderBot does (no X-Agent-Digest, nothing in the body): the hostname's rule for /api/v1/agent/ goes somewhere other than the controller. In Zero Trust its service is http://localhost:7680 when the controller runs the tunnel itself, or the controller's LAN address and port (http://ADDRESS:7680) when cloudflared runs elsewhere at home; curl -sI ${CONTROLLER%/}/api/v1/agent/nosuch should answer 404"
        exit 1
    fi
    case "$code" in
        200) ;;
        000|"") warn "${CONTROLLER} does not answer with a certificate this machine trusts. Is the tunnel at home up (the Settings page's Public hostname line says connected), and does the hostname resolve here? curl -v ${CONTROLLER%/}/api/v1/agent/download says more"; exit 1 ;;
        404) warn "${CONTROLLER} answers 404 on the agent's API: the tunnel at home does not forward /api/v1/agent/ to the controller yet (Apply on Controller settings with an API token writes the rule, or add the public hostname in Zero Trust)"; exit 1 ;;
        502|530) warn "${CONTROLLER} answers ${code}: the tunnel at home is up but what it forwards to does not answer. The hostname's service must be http://localhost:7680 when the controller runs the tunnel itself (Controller settings), or the controller's LAN address and port when cloudflared runs elsewhere at home"; exit 1 ;;
        401|403) warn "${CONTROLLER} refused the enrollment token (${code}): it was used already or has run out; make a new script on the Nodes page"; exit 1 ;;
        *) warn "${CONTROLLER} answers ${code} on the agent's API, not 200: enrollment would fail; curl -v ${CONTROLLER%/}/api/v1/agent/download says more"; exit 1 ;;
    esac
    printf '   %s answers\n' "$CONTROLLER"
fi

# --- a door in for SSH (R174) ------------------------------------------------
# A tunnel client of the operator's choice, installed and started here, and
# from then on the node's row switches it on and off (the agent's door
# system job). The secret goes into the service's own files, root's, and
# never into node.json; a re-run without the secret file leaves a door that
# is already installed as it is.
door_secret() { [ -n "$DOOR_SECRET" ] && [ -r "$DOOR_SECRET" ] && tr -d '\r\n' < "$DOOR_SECRET"; }
if [ "$DOOR" = cloudflared ]; then
    say "door: cloudflared, publishing port 22 at ${DOOR_HOST}"
    [ "$INIT" = systemd ] || { warn "cloudflared's service is systemd's, and this machine runs ${INIT:-no init this knows}"; exit 1; }
    if ! command -v cloudflared >/dev/null 2>&1 && [ ! -x /usr/local/bin/cloudflared ]; then
        case "$(uname -m)" in x86_64) cfarch=amd64 ;; aarch64|arm64) cfarch=arm64 ;; armv7l) cfarch=arm ;; *) warn "no cloudflared build for $(uname -m)"; exit 1 ;; esac
        # Cloudflare's own release, the latest: the client updates itself
        # from there too, so pinning here would be the one copy left behind.
        curl -fsSL -o /usr/local/bin/cloudflared.new "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${cfarch}" \
            || { warn "could not download cloudflared from its release"; rm -f /usr/local/bin/cloudflared.new; exit 1; }
        chmod 755 /usr/local/bin/cloudflared.new; mv -f /usr/local/bin/cloudflared.new /usr/local/bin/cloudflared
    fi
    cfbin="$(command -v cloudflared || echo /usr/local/bin/cloudflared)"
    install -d -m 0700 /etc/cloudflared
    if [ -n "$(door_secret)" ]; then
        # The token in a root-only env file the unit reads, never on the
        # unit's own command line, which any account here could read.
        umask 077; printf 'TUNNEL_TOKEN=%s\n' "$(door_secret)" > /etc/cloudflared/env; umask 022
    elif [ ! -s /etc/cloudflared/env ]; then
        warn "no tunnel token: the door's secret left the enroll script once it ran; make a new script on the Nodes page"; exit 1
    fi
    svc_install cloudflared "BuilderBot: the door in for SSH (cloudflared)" "${cfbin} --no-autoupdate tunnel run" "EnvironmentFile=/etc/cloudflared/env"
    printf '   up; in Zero Trust the tunnel'"'"'s public hostname %s goes to ssh://localhost:22, and Cloudflare Access decides who reaches it\n' "$DOOR_HOST"
elif [ "$DOOR" = tailscale ]; then
    say "door: Tailscale, this machine on your tailnet with ssh"
    if ! command -v tailscale >/dev/null 2>&1; then
        curl -fsSL https://tailscale.com/install.sh | sh || { warn "Tailscale did not install"; exit 1; }
    fi
    if [ -n "$(door_secret)" ]; then
        tailscale up --ssh --auth-key="$(door_secret)" || { warn "tailscale up did not join the tailnet: is the auth key still valid?"; exit 1; }
    else
        tailscale status >/dev/null 2>&1 || { warn "no auth key: the door's secret left the enroll script once it ran; make a new script on the Nodes page"; exit 1; }
    fi
    printf '   up; ssh reaches this machine on the tailnet, and its ACLs decide who\n'
fi

say "docker"
# Docker's own repository rather than the distribution's: the compose plugin
# and a current engine are the entire point of this machine, and Debian's
# docker.io lags both.
# Which suite to ask Docker for. Normally this release's own codename, but
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
            "https://download.docker.com/linux/${DOCKER_DEB}/dists/${try}/Release"; then
            printf '%s' "$try"
            return 0
        fi
    done
    return 1
}

if ! command -v docker >/dev/null 2>&1; then
    docker_install
fi
command -v docker >/dev/null 2>&1 && svc_enable docker

# --- the stamp ----------------------------------------------------------
# A label on the daemon saying this machine is BuilderBot's sandbox.
#
# It is what BuilderBot checks before it will talk to a daemon at all, and the
# reason it checks: everything the manager does beyond compose runs a container
# as root on the far side, which is fine on a box whose whole job is being
# wrecked and reset, and is a different act entirely against a NAS, a
# workstation or the server itself. An ssh address only proves somebody typed
# one, and a machine can answer Docker without being this one. So the provisioner
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
    # An existing file is merged rather than replaced: it may carry storage
    # or logging settings this script knows nothing about, and a sandbox that
    # came up with different storage would be a surprising way to find out.
    have_jq || pkg jq >/dev/null 2>&1 || true
    if ! have_jq; then
        warn "/etc/docker/daemon.json exists and jq is not available to merge"
        warn "add \"labels\": [\"${label}\"] to it by hand, then restart docker"
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
    svc_restart docker || warn "docker did not restart; restart it by hand so the label is read"
    say "stamped this daemon as BuilderBot's sandbox"
fi

# The journal kept across boots (R185): a fresh VPS keeps it in memory only,
# so after a crash `bb logs --node NAME --crash` met "No journal boot entry
# found for the specified boot (-1)" on a hosting node (11 Oct). A drop-in rather
# than an edit of journald.conf, so the distribution's own file is left as it
# was; journald restarted only when the drop-in is new.
keep_journal() {
    local f=/etc/systemd/journald.conf.d/50-builderbot.conf
    command -v journalctl >/dev/null 2>&1 || return 1
    # The same bytes as the agent's JOURNAL_DROPIN (configplane.py), and at
    # most 1G of journal: an older drop-in without the ceiling is replaced.
    local want='# Written by BuilderBot (R185): keep the journal across boots, and at most 1G of it.
[Journal]
Storage=persistent
SystemMaxUse=1G'
    [ -f "$f" ] && [ "$(cat "$f")" = "$want" ] && return 1
    install -d -m 0755 /etc/systemd/journald.conf.d /var/log/journal
    printf '%s\n' "$want" > "$f"
    command -v systemd-tmpfiles >/dev/null 2>&1 && systemd-tmpfiles --create --prefix /var/log/journal >/dev/null 2>&1
    return 0
}
if keep_journal; then
    systemctl restart systemd-journald >/dev/null 2>&1 || warn "journald did not restart; the journal is kept from the next boot"
    say "the system journal is kept across boots from now"
fi

# One implementation of "let this account in", used for both. The validation
# is the point: a key that does not parse leaves a VM nothing can ssh into,
# found from the console after the fact.
authorize() {
    local who="$1" key="$2" home
    case "$key" in
        *"-----BEGIN"*)
            echo "that is a PRIVATE key. It wants the .pub half; the private" >&2
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
# An account here before BuilderBot is somebody's own: noted, so Uninstall
# leaves it and its home where it found them.
KEPT_ACCOUNTS=/etc/builderbot/kept-accounts
keep_account() {
    install -d -m 0755 /etc/builderbot
    grep -qx "$1" "$KEPT_ACCOUNTS" 2>/dev/null || echo "$1" >> "$KEPT_ACCOUNTS"
}
# Never one that is already here and not BuilderBot's: an account is
# somebody's, and taking it over (or deleting it at Uninstall) is never
# ours to do, whatever it is called. A machine already enrolled has made its
# own, which a run again keeps using.
if id -u "$USER_NAME" >/dev/null 2>&1; then
    if [ ! -f /etc/builderbot/node.json ]; then
        keep_account "$USER_NAME"
        warn "${USER_NAME} is already an account on this machine, and not one BuilderBot made: run again with --user NAME, a name that is not taken (bbjobs, say)"; exit 1
    fi
else
    useradd -m -s /bin/bash "$USER_NAME"
fi
usermod -aG docker "$USER_NAME"
# ...and kvm, where the host exposes it. Without this the Android emulator on
# this node runs with no hardware acceleration and is unusably slow, measured
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
    # that it holds nothing: authorized_keys wants the .pub half, and the
    # private one never leaves BuilderBot's shielded agent.
    authorize "$USER_NAME" "$SSH_KEY"
fi

# WHO ADMINISTERS THIS MACHINE, which is never the account a session reaches.
# bb runs Docker and answers ssh and has no sudo; bb-sandbox runs as root and
# for nobody else. So the mounts, which share holds appdata, and what this VM
# is called on the network are decisions made by somebody with root at a
# console, not side effects available to whatever is building a container this
# afternoon.
#
# BE CLEAR ABOUT WHAT THIS DOES NOT DO. bb is in the docker group, and the
# docker group is root on this machine to anyone who wants it: one
# `docker run -v /:/host --privileged` and the separation is over. That is not
# a hole to plug, it is the whole point of the VM: it exists to be wrecked, and
# BuilderBot needs the daemon to do its job. What the split buys is that the
# machine's OWN configuration is not one command away from a session that
# wandered: the fstab that decides what this machine mounts, and read-only,
# needs root, which neither account here has.
#
# NO ADMINISTRATOR ACCOUNT IS MADE, and none is needed: the agent runs as
# root under systemd and drops to --user for every job, bb-sandbox refuses to
# run as anyone but root whoever invokes it, and the controller never names
# an administrator. Whatever account already has root here (yours, a cloud
# image's ubuntu or ec2-user, or root itself) administers this machine,
# which is the operator's business and not this script's. What is enforced
# below: the DOCKER account has no sudo, and the SESSION account is in
# neither docker nor sudo.

# --- the session account (roadmap #24) ------------------------------------
# The second account, and the one the design turns on: a Claude session on
# this node's projects runs HERE, as this account, in a tmux the agent's
# ttyd starts, with this machine's toolchains and its synced copy of the
# projects. Not bb, on purpose: bb is in the docker group, which is
# root on any machine running a daemon, and a session is exactly the thing
# to keep away from that. So: no docker, no sudo, kvm
# for the emulator, a home of its own for the Claude login and the
# transcripts, and the same uid:gid the controller writes the share as.
say "session account ${SESSION_NAME}"
if [ "$SESSION_NAME" = none ] || [ -z "$SESSION_NAME" ]; then
    printf '   none asked for; this node runs jobs and no sessions\n'
    SESSION_NAME=""
elif [ "$SESSION_NAME" = "$USER_NAME" ]; then
    warn "--session-user ${SESSION_NAME} is the docker account: a session must not be it"
    printf '   pick a different --session-user, or none\n'
    SESSION_NAME=""
elif id -u "$SESSION_NAME" >/dev/null 2>&1 && [ ! -f /etc/builderbot/node.json ]; then
    # Already an account here, and not one BuilderBot made: somebody's, and
    # maybe one that can sudo, which a session never may (a cloud image's own
    # account, R97's walk). Left as it is; sessions wait for another name.
    keep_account "$SESSION_NAME"
    warn "${SESSION_NAME} is already an account on this machine, and not one BuilderBot made"
    printf '   run again with --session-user NAME, a name that is not taken (bbsession, say), or none\n'
    SESSION_NAME=""
else
    if id -u "$SESSION_NAME" >/dev/null 2>&1; then
        :
    else
        getent group "$SESSION_GID" >/dev/null 2>&1 \
            || groupadd -g "$SESSION_GID" "$SESSION_NAME" 2>/dev/null \
            || groupadd -g "$SESSION_GID" "bbusers"
        if getent passwd "$SESSION_UID" >/dev/null 2>&1; then
            # The uid is somebody else's here. The account is still made
            # (a node without sessions is worse), but every file it saves on
            # the share will be owned by whatever uid it got, and that is
            # worth a line at provision time rather than a surprise later.
            warn "uid ${SESSION_UID} is already $(getent passwd "$SESSION_UID" | cut -d: -f1) on this machine"
            printf '   %s is made with the next free uid; files it saves for the controller\n' "$SESSION_NAME"
            printf '   will be owned by that uid rather than the controller'"'"'s %s\n' "$SESSION_UID"
            useradd -m -g "$SESSION_GID" -s /bin/bash "$SESSION_NAME"
        else
            # Below the distribution's range for people on purpose: the uid
            # is the controller's, so a file this account saves on the share
            # is owned as one saved from the controller is. useradd says so
            # in a warning that reads as a fault; the reason goes first.
            printf '   %s takes uid %s, the controller'"'"'s, so files on the shares match\n' "$SESSION_NAME" "$SESSION_UID"
            useradd -m -u "$SESSION_UID" -g "$SESSION_GID" -s /bin/bash "$SESSION_NAME" 2>/dev/null \
                || useradd -m -u "$SESSION_UID" -g "$SESSION_GID" -s /bin/bash "$SESSION_NAME"
        fi
    fi
    getent group kvm >/dev/null 2>&1 && usermod -aG kvm "$SESSION_NAME"
    # Belt and braces: an account that was in docker before this ran is
    # taken out, because being out is the whole reason it exists.
    if id -nG "$SESSION_NAME" | tr ' ' '\n' | grep -qx docker; then
        gpasswd -d "$SESSION_NAME" docker >/dev/null 2>&1 || true
        printf '   %s taken out of the docker group\n' "$SESSION_NAME"
    fi
    [ -n "$SSH_KEY" ] && authorize "$SESSION_NAME" "$SSH_KEY"
    # What a session needs on the box: tmux keeps it alive across a dropped
    # browser, ttyd is what the controller's terminal proxy dials, and jq
    # and git are what bb-tty and bb reach for. From the distribution where
    # it packages them, and ttyd, which the RHEL family, SUSE Leap and
    # Gentoo do not carry, from the static binary in ttyd's own release,
    # pinned to this machine's architecture: the one download here that
    # is not a package manager's, so an offline node copies it in by hand.
    # shellcheck disable=SC2046
    pkg $(pkg_names session) >/dev/null 2>&1 \
        || warn "tmux, jq or git did not install; sessions will not start until they do"
    # A display for bb capture reel (R95): not fatal, since a node without one still
    # builds and tests; bb capture reel --display says what is missing.
    # shellcheck disable=SC2046
    pkg $(pkg_names reel) >/dev/null 2>&1 \
        || warn "Xvfb, xdotool or xdpyinfo did not install; bb capture reel --display needs them"
    ttyd_pkg="$(pkg_names ttyd)"
    if ! command -v ttyd >/dev/null 2>&1 && [ -n "$ttyd_pkg" ]; then
        pkg "$ttyd_pkg" >/dev/null 2>&1 || true
    fi
    # Debian's package enables a unit of its own: ttyd as root on lo:7681
    # serving a login prompt, which nothing here asked for. The binary is what
    # was wanted; the agent runs its own ttyd as the session account (B136).
    # Outside the install branch on purpose: a re-provision, or a base image
    # that already carries the package, still has the unit to switch off, so
    # disabling it only when we install the binary leaves it running on every
    # run but the first.
    if [ -n "$ttyd_pkg" ] && command -v systemctl >/dev/null 2>&1; then
        systemctl disable --now ttyd.service >/dev/null 2>&1 || true
    fi
    if ! command -v ttyd >/dev/null 2>&1; then
        case "$(uname -m)" in
            x86_64) tarch=x86_64 ;;
            aarch64) tarch=aarch64 ;;
            armv7l) tarch=armhf ;;
            *) tarch="" ;;
        esac
        if [ -n "$tarch" ] && curl -fsSL -o /usr/local/bin/ttyd.new \
                "https://github.com/tsl0922/ttyd/releases/latest/download/ttyd.${tarch}"; then
            chmod 0755 /usr/local/bin/ttyd.new && mv /usr/local/bin/ttyd.new /usr/local/bin/ttyd
            printf '   ttyd %s from its GitHub release\n' "$(ttyd --version 2>/dev/null | awk '{print $NF}')"
        else
            rm -f /usr/local/bin/ttyd.new
            warn "ttyd did not install; fetch ttyd.${tarch:-x86_64} from https://github.com/tsl0922/ttyd/releases into /usr/local/bin"
        fi
    fi
    # Claude Code is not installed here: the node's Toolchains tab does it on
    # purpose, so whoever enrolls a node sees what is put on it (R145), and a
    # session refuses to start until it is there.
    # A login shell as this account gets what a dashboard session gets: the
    # role, the controller's address, and bb from the bundle the agent keeps
    # current under the toolchain store. That is what makes proving the node
    # by hand (ssh in, run bb-tty, run bb roadmap) the same path the
    # dashboard takes, rather than a second one.
    cat > /etc/profile.d/builderbot-session.sh <<EOF
# Written by BuilderBot's provision-linux.sh. A session on this node, at a console.
case "\$(id -un)" in
    ${SESSION_NAME})
        export BUILDERBOT_ROLE=node WORKSPACE=/workspace
        export BB_NODE="\$(hostname)"
        ${CONTROLLER:+export BB_CONTROLLER="${CONTROLLER%/}"}
        [ -d "${STORE_TOOLCHAINS}/.bb/current/scripts" ] \\
            && PATH="${STORE_TOOLCHAINS}/.bb/current/scripts:\$PATH"
        PATH="\$HOME/.local/bin:\$PATH"
        ;;
esac
EOF
fi

say "bb-sandbox"
# The tool that configures this machine after today: mounts, which one holds
# container appdata, and the path mapping for this machine's row. Installed here and
# then USED below, so the fstab logic has one implementation rather than a copy
# in each entry point; its comments were paid for one silent failure at a time
# and are not worth writing twice.
#
# Embedded rather than fetched: provision-linux.sh is one file you curl onto a fresh
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
# produced on a real VM: "install: No such file or directory", naming
# nothing. Which of the two bash picks is a size and version question, so the
# form worked everywhere it was tried and failed on the machine it was for.
# cat reads the descriptor it was given and asks no such question.
BBSANDBOX_TMP="$(mktemp)"
cat > "$BBSANDBOX_TMP" <<'BBSANDBOX'
#!/usr/bin/env bash
#
# bb-sandbox: configure this Docker sandbox after it has been provisioned.
#
# Installed by provision-linux.sh, which also uses it for its own mounts: this is the
# only copy of the fstab logic, so the wizard and the first run cannot drift.
#
# Root, on this machine. Run by a person at the console, and (since phase 5
# of docs/nodes.md) by the node agent, which applies the Nodes tab's desired
# mounts and stores through these same verbs as audited `system` jobs, so the
# GUI and this menu can never disagree about what the machine is configured
# to be. `sdk` is the exception to all of that: it reads the toolchain store
# through the controller's own bb and needs no privilege. Still deliberately NOT reachable by a session: the agent is offered
# system jobs only because it enrolled as a sandbox, and `list --json` is the
# whole of what it reads back. The docker account cannot run this at all.
# `gpu` installs the NVIDIA driver and a headless X server on the card, so
# an emulator here renders on it (R20); `gpu-display` is that server's unit.
set -euo pipefail

CONF=/etc/bb-sandbox.conf
# shellcheck source=/dev/null
[ -f "$CONF" ] && . "$CONF"
APPDATA="${APPDATA:-}"
# The account BuilderBot ssh's in as, recorded by provision-linux.sh because this is
# the one thing here it knows and the tool cannot work out. `logname` was the
# guess before, and it answers with whoever ran sudo: a different name the
# moment the operator administers this box from an account of their own, and
# an empty one where there is no controlling terminal at all.
DOCKER_USER="${DOCKER_USER:-bb}"

say()  { printf '\n== %s\n' "$*"; }
warn() { printf '\n!! %s\n' "$*" >&2; }
die()  { warn "$*"; exit 1; }
# Everything here writes to the machine (fstab, netplan, /etc) except `sdk`,
# which only reads the toolchain store and needs no privilege to do it.
case "${1-}" in
    sdk) ;;
    *) [ "$(id -u)" -eq 0 ] || die "run this as root: sudo bb-sandbox" ;;
esac

# Every mount this tool manages, by mountpoint. Read from fstab rather than
# kept in a list of our own: fstab is what the machine actually boots from, and
# a second list would be a claim about it rather than a reading of it. Which
# means the type list has to hold every type a share is really mounted with,
# not only the two this tool writes: a share mounted by hand with nfs4 is
# invisible to a filter that knows only nfs, and `settings` then prints a
# path mapping with it missing.
ours() {
    awk '$1 !~ /^#/ && $3 ~ /^(virtiofs|9p|nfs|nfs4|cifs)$/ {print $2}' \
        /etc/fstab 2>/dev/null | sort -u
}

# The fstab line for a mountpoint, as "N:the whole line", or empty if there
# is none. On field TWO, and skipping comments, because every caller below either
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
# sits on must agree. The agent holds the other end: it refuses to POINT a
# store at a share that is configured and not mounted, because mkdir would
# make an ordinary directory there and everything would land on this
# machine's own disk looking healthy. This end is the same failure reached
# from the console: unmounting a share a store is inside.
#
# The anti-drift is structural rather than a matching rule: there is ONE
# list of where the stores are (the agent's node.json), and this reads it
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
    raise SystemExit(0) from None
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
    # ESTALE, including the stat that `mkdir -p` begins with.
    if ! mkdir -p "$path" 2>/dev/null; then
        if findmnt -rno TARGET -- "$path" >/dev/null 2>&1; then
            warn "$path is mounted but unreadable: a stale handle, left by a share that moved or stopped being exported."
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
    # "*:" left a leading space on every comparison, so an unchanged entry
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
    # Say which half moved. A changed SOURCE is the one worth staring at (it
    # means this mountpoint now points somewhere else), and reporting an
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

# mount_one PATH: mount it and say plainly whether it worked.
#
# `nofail` is right at boot and wrong here: it means a share that cannot mount
# does so quietly and `mount -a` still succeeds. So the SOURCE is checked, not
# merely that something is mounted: `mount -a` skips a busy mountpoint, so a
# path whose entry was just rewritten stays on the old share and looks fine.
mount_one() {
    local path="$1" want got held n
    want="$(fstab_line "$path")"; want="${want#*: }"; want="${want%% *}"
    # ONLY WHEN NOTHING IS THERE. `mount /path` does not refuse a path that
    # already has something on it (for NFS it stacks another mount on top),
    # so the unconditional `mount` this used to open with added a layer every
    # time storage was applied. Two applies were enough: findmnt then printed
    # two sources, the equality test below failed on a healthy mount, and the
    # job reported a mismatch between a source and itself.
    # This path only. `mount -a` mounted every entry in fstab, so one export
    # the server refuses printed its refusal on every check of every OTHER
    # mount: three copies of one unrelated failure, above the answers.
    # findmnt exits 1 for a path that is not mounted, and under pipefail
    # that ended this function on its first line for every FIRST mount,
    # silently, before mount ran: a fresh node's Storage apply always
    # "failed" and the mounts came up later through fstab (found on the
    # second onboarding walk, 16 Sep). Its exit is not an answer here; its
    # line count is.
    n="$({ findmnt -rno SOURCE -- "$path" 2>/dev/null || true; } | wc -l)"
    # mount's own words are kept for the refusal below: swallowed, a mount
    # the server would not allow this host read the same as a client that
    # was not there, and a RedHat node's first Storage apply said only
    # that nothing mounted (B704).
    said=""
    if [ "$n" -eq 0 ]; then
        said="$(mount "$path" 2>&1 >/dev/null || true)"
        n="$({ findmnt -rno SOURCE -- "$path" 2>/dev/null || true; } | wc -l)"
    fi
    # One line PER mount at this path. The last is the one on top, and the
    # only one anything opening a file there actually reaches.
    got="$(findmnt -rno SOURCE -- "$path" 2>/dev/null | tail -1 || true)"
    if [ "$n" -gt 1 ]; then
        warn "$path is mounted ${n} times, stacked; only the top one is visible."
        printf '   Take the layers off, and this will put it back:\n'
        printf '     while mountpoint -q %s; do umount -l %s; done; mount %s\n' \
            "$path" "$path" "$path"
        return 1
    fi
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
    [ -n "$said" ] && printf '   mount said: %s\n' "$(printf '%s' "$said" | tail -3 | tr '\n' ' ')"
    held="$(stores_under "$path")"
    [ -n "$held" ] && printf '   %s sits inside it, so that store is on the root disk until it mounts.\n' \
        "$(printf '%s' "$held" | tr '\n' ' ')"
    printf '   On Unraid an export is a SHARE (/mnt/user/<share>), never a\n'
    printf '   pool path like /mnt/cache/<share>, which is right for a bind\n'
    printf '   mount and is not exported. Check it allows this host:\n'
    printf '     showmount -e <server>\n'
    return 1
}

# --- commands -----------------------------------------------------------
cmd_add_share() {
    local spec="${1:?usage: bb-sandbox add-share TAG:PATH[:ro]}" tag path opts=defaults
    # `:ro` mounts it read-only: a share containers only read from.
    case "$spec" in *:ro) opts=defaults,ro; spec="${spec%:ro}" ;; esac
    tag="${spec%%:*}"; path="${spec#*:}"
    [ "$tag" != "$spec" ] || die "add-share wants TAG:PATH, got '$spec'"
    case "$path" in /*) ;; *) die "the mountpoint must be absolute, got '$path'" ;; esac
    case "${path%/}" in /workspace|/workspace/*)
        die "/workspace holds this node's synced copy of its projects; nothing is mounted there" ;; esac
    add_fstab "$tag $path virtiofs $opts,nofail 0 0" "$path" && mount_one "$path"
}

# This machine's own address, for the settings line. hostname -I is a GNU
# extension busybox lacks; the route table is the fallback, and neither
# failing is an error: an offline box prints a placeholder.
my_ip() {
    hostname -I 2>/dev/null | awk '{print $1}' | grep . \
        || ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") print $(i+1)}' | head -1 \
        || true
}

cmd_add_nfs() {
    local spec="${1:?usage: bb-sandbox add-nfs HOST:EXPORT:PATH[:ro]}" host rest exp path opts=defaults
    case "$spec" in *:ro) opts=defaults,ro; spec="${spec%:ro}" ;; esac
    host="${spec%%:*}"; rest="${spec#*:}"; exp="${rest%%:*}"; path="${rest#*:}"
    # Three fields, and getting two produces nonsense rather than an error:
    # the export and the mountpoint both come out as the export.
    case "$rest" in *:*) ;; *) die "add-nfs wants HOST:EXPORT:PATH; '$spec' has no mountpoint" ;; esac
    case "$path" in /*) ;; *) die "the mountpoint must be absolute, got '$path'" ;; esac
    case "${path%/}" in /workspace|/workspace/*)
        die "/workspace holds this node's synced copy of its projects; nothing is mounted there" ;; esac
    add_fstab "$host:$exp $path nfs $opts,nofail,_netdev 0 0" "$path" && mount_one "$path"
}

# readonly PATH [on|off]: flip an existing mount between ro and rw.
#
# The :ro suffix on add-share/add-nfs decides it when a mount is made; this
# decides it afterwards, which is what somebody actually has, and without it
# the only way to make a share read-only was to retype its whole spec.
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
        *)   die "readonly wants on or off, got '$want'" ;;
    esac
    add_fstab "$src $path $fstype $new_opts ${dump:-0} ${pass:-0}" "$path"
    # remount first, and a full cycle only if the kernel will not take it: a
    # busy mountpoint refuses umount, and refusing to change is better than
    # leaving the share unmounted because something had a file open.
    mount -o "remount,$want" "$path" 2>/dev/null \
        || mount -o remount "$path" 2>/dev/null \
        || { umount "$path" 2>/dev/null && mount "$path" 2>/dev/null; } \
        || warn "fstab says $want, but $path could not be remounted now; it will be at the next boot"
    if [ "$want" = on ] && [ -w "$path" ]; then
        warn "$path is still writable: the export itself may be rw-only"
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
        printf '   root filesystem free space. Move them first (the Nodes page\n'
        printf '   copies a store when you repoint it), or, if you mean it:\n'
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

# bb-sandbox sdk [...]: the controller's own bb, for the questions that make
# sense on this machine.
#
# Not a second copy of anything. The agent unpacks the controller's bb into
# the toolchain store to run jobs with, and it has been sitting there
# unreachable: a person at this console could not ask what toolchains the
# store holds, though the tool that answers was already on the disk. This
# hands it over, with the same environment a job gets.
#
# READ-ONLY verbs only. Installing from here would go around the arbitration
# the controller keeps across every machine that shares this store (one
# install at a time, or two unpackings land in one directory), so those are
# refused with the place that does it properly.
BB_READONLY_VERBS="status root list versions images flavors env plan"

cmd_sdk() {
    local verb="${1:-status}" store user bb newest
    case " $BB_READONLY_VERBS " in
        *" $verb "*) ;;
        *) die "bb-sandbox sdk reads; it does not install. '$verb' changes the store, and
   doing it from here would go around the one-install-at-a-time rule the
   controller keeps across every machine sharing it. Use the dashboard's
   Tools tab, with this node picked. Readable: $BB_READONLY_VERBS" ;;
    esac
    [ -r "$NODE_JSON" ] || die "this machine is not enrolled ($NODE_JSON is not readable): there is no store to read"
    store="$(python3 -c 'import json,sys
print(((json.load(open(sys.argv[1])).get("stores") or {}).get("toolchains")) or "")' "$NODE_JSON" 2>/dev/null)"
    user="$(python3 -c 'import json,sys
print(json.load(open(sys.argv[1])).get("user") or "")' "$NODE_JSON" 2>/dev/null)"
    [ -n "$store" ] || die "this node has no toolchain store"
    # The newest bundle the agent has unpacked. It appears the first time a
    # toolchain job runs here, so before that there is honestly nothing to run.
    newest="$(ls -1dt "$store"/.bb/*/scripts/bb 2>/dev/null | head -1 || true)"
    [ -n "$newest" ] || die "no bb on this machine yet: the controller unpacks one into
   ${store}/.bb the first time a toolchain job runs on this node. Install
   something from the dashboard's Tools tab and it will be here."
    bb="$newest"
    local -a env=(env
        "SDK_ROOT=$store" "BUILDER_HOME=$store" "BB_NODE_TOOLCHAINS=1"
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
        # tail -1: one line per mount at this path, and the top one is what
        # anything opening a file there gets. See mount_one on stacking.
        real="$(findmnt -rno SOURCE -- "$path" 2>/dev/null | tail -1 || true)"
        if [ -z "$real" ]; then state="NOT MOUNTED"
        elif [ ! -w "$path" ]; then state="mounted, read-only"
        else state="mounted"; fi
        [ "$APPDATA" = "$path" ] && state="$state · container appdata"
        held="$(stores_under "$path")"
        [ -n "$held" ] && state="$state · holds $(printf '%s' "$held" | tr '\n' ' ')"
        # Where it is REALLY mounted from, not what fstab claims. Those two
        # disagree exactly when something needs attention (an entry rewritten
        # under a mount that was busy at the time), and printing fstab's
        # version called that healthy.
        if [ -n "$real" ] && [ "$real" != "$src" ]; then
            state="$state · fstab says $src"
            src="$real"
        fi
        printf '%-24s %-34s %s\n' "$path" "$src" "$state"
    done < <(ours)
    [ -n "$(ours)" ] || printf '(none yet)\n'
}

# list --json prints the same facts as a machine reads them: the agent's census
# carries this, and the Nodes tab draws the operator's desired mounts against
# it. Escaped by hand, since jq may not be here.
# Newlines stripped as well as quotes escaped. A raw newline inside a JSON
# string is not JSON, and the whole document is then unparseable, which is
# how one stacked mount (findmnt printing a source per layer) took EVERY
# mount off the Nodes tab at once: the controller read the census, could not
# parse it, and drew a node with no mounts at all, so all four read "not
# applied yet". A value that arrives with a line break in it is worth
# flattening rather than trusting.
json_str() { printf '%s' "$1" | tr '\n\r' '  ' | sed 's/\\/\\\\/g; s/"/\\"/g'; }
cmd_list_json() {
    local path line src type opts real ro mounted first=1
    printf '['
    while read -r path; do
        [ -n "$path" ] || continue
        line="$(fstab_line "$path")"; line="${line#*: }"
        src="$(awk '{print $1}' <<<"$line")"; type="$(awk '{print $3}' <<<"$line")"
        opts="$(awk '{print $4}' <<<"$line")"
        # tail -1: one line per mount at this path, and the top one is what
        # anything opening a file there gets. See mount_one on stacking.
        real="$(findmnt -rno SOURCE -- "$path" 2>/dev/null | tail -1 || true)"
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
    ours | grep -qxF "$path" || die "$path is not one of this machine's mounts; add it first"
    write_conf "$path"
    say "$path is where containers keep their data"
}

# The lines to put in BuilderBot's own template. This machine cannot set them
# (they are the CONTAINER's environment, on the other box), so it prints them
# rather than pretending. Derived from what is actually mounted here, which is
# the half that is easy to get wrong by hand.
cmd_settings() {
    local ip pairs="" path
    ip="$(my_ip || true)"
    while read -r path; do
        [ -n "$path" ] || continue
        # Parity: BuilderBot mounts the same share at the same path, so the
        # mapping is an identity and the translation falls silent. A path this
        # VM has and BuilderBot does not still belongs in neither list.
        pairs="${pairs:+$pairs,}$path:$path"
    done < <(ours)
    cat <<EOF

On BuilderBot's dashboard, Nodes page, on this machine's row (${ip:-<this-vm>}):

  Path mapping:    ${pairs:-<none yet>}

Only for the paths BuilderBot ALSO mounts at the same place: a share that is
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
            readonly "make a mount read-only" \
            check    "verify every mount is really there" \
            settings "the path mapping for this machine's row" \
            quit     "" 3>&1 1>&2 2>&3)" || return 0
        case "$choice" in
            list)  cmd_list; pause ;;
            nfs)   ask "HOST:EXPORT:PATH" "192.168.1.15:/mnt/user/media:/auxiliary" \
                       && cmd_add_nfs "$REPLY"; pause ;;
            share) ask "TAG:PATH" "" \
                       && cmd_add_share "$REPLY"; pause ;;
            remove) ask "which mountpoint" "" && cmd_remove "$REPLY"; pause ;;
            appdata) ask "which mountpoint holds container appdata" "${APPDATA:-/devdata}" \
                       && cmd_appdata "$REPLY"; pause ;;
            readonly) ask "which mountpoint to make read-only" "" \
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
  4) remove a mount              8) the path mapping for this machine's row
                                 q) quit
EOF
        read -r -p "> " n || return 0
        case "$n" in
            1) cmd_list ;;
            2) ask "HOST:EXPORT:PATH" "" && cmd_add_nfs "$REPLY" ;;
            3) ask "TAG:PATH" "" && cmd_add_share "$REPLY" ;;
            4) ask "which mountpoint" "" && cmd_remove "$REPLY" ;;
            5) ask "which mountpoint holds container appdata" "${APPDATA:-}" && cmd_appdata "$REPLY" ;;
            6) ask "which mountpoint to make read-only" "" && cmd_readonly "$REPLY" on ;;
            7) cmd_check || true ;;
            8) cmd_settings ;;
            q|Q) return 0 ;;
        esac
    done
}


# uninstall: take BuilderBot's software off this machine and leave the rest.
# What goes is what provision-linux.sh put here for BuilderBot alone: the
# agent and its unit, the session-ports rule, the two accounts and their
# homes (Claude Code, the runners' directories, caches), the mounts
# BuilderBot used (whatever a store sits on, and a /workspace share left from
# before every node held a synced copy), the stores on
# this disk, this tool. What stays is shared with the rest of the machine:
# docker and the packages the provisioner installed (nfs-common, python3,
# tmux, jq, curl, a distribution's ttyd), the empty mountpoint directories,
# and everything on the shares, which other nodes may be using. Runners are
# not deregistered on their forge here: the Nodes tab's Uninstall does that
# first, while the agent can still ask the controller for the tokens.
# What goes is in three rings (the operator, 11 Oct), the first always and
# the other two asked for: --stores takes the stores on this disk (the
# toolchains, the caches, the artifacts, a dev instance's data, the synced
# project copies) and /var/lib/builderbot; --configured undoes what was set
# up from the dashboard after enrolling (the mounts and their fstab lines,
# the runners' units, the GPU display); --doors shuts what a hosting node
# was given (cloudflared and its token, Tailscale's login, the port 22
# rule, the nginx container written for it). Without them a node can be
# enrolled again, here or on another controller, with its stores and its
# mounts as they were.
cmd_uninstall() {
    local yes=0 stores=0 configured=0 doors=0 a p u f mounts="" session_user="" store_dirs=""
    for a in "$@"; do
        case "$a" in
            --yes) yes=1 ;;
            --stores) stores=1 ;;
            --configured) configured=1 ;;
            --doors) doors=1 ;;
            "") ;;
            *) die "uninstall takes --yes, --stores, --configured and --doors" ;;
        esac
    done
    session_user="$(python3 -c 'import json; print(json.load(open("/etc/builderbot/node.json")).get("session_user", ""))' 2>/dev/null || true)"
    [ -n "$session_user" ] || session_user=builder
    store_dirs="$(python3 -c 'import json; print(" ".join(sorted(set(str(v) for v in (json.load(open("/etc/builderbot/node.json")).get("stores") or {}).values() if str(v).startswith("/")))))' 2>/dev/null || true)"
    for p in $(ours); do
        case "$p" in
            /workspace) mounts="$mounts $p" ;;
            *) [ -n "$(stores_under "$p")" ] && mounts="$mounts $p" ;;
        esac
    done
    say "uninstall BuilderBot from this machine"
    printf '   goes:  the agent and its unit, the session firewall rules and the sessions'"'"' own networks,\n'
    printf '          the accounts %s and %s with their homes, /etc/builderbot, and this tool\n' "$DOCKER_USER" "$session_user"
    [ "$stores" = 1 ] && printf '   also:  the stores on this disk (%s), /workspace, /var/lib/builderbot\n' "${store_dirs:- none}"
    [ "$configured" = 1 ] && printf '   also:  the mounts BuilderBot used (%s), the runners, the GPU display\n' "${mounts:- none}"
    [ "$doors" = 1 ] && printf '   also:  cloudflared and its token, Tailscale'"'"'s login, the port 22 rule, the hosting firewall, the nginx container\n'
    printf '   stays: docker, nfs-common, python3, tmux, jq, curl, the empty mountpoints,\n'
    printf '          everything on the shares (other nodes may use them)%s\n' "$([ "$stores" = 1 ] || printf ', the stores')"
    printf '   note:  a runner registered from here stays listed on its forge;\n'
    printf '          the Nodes page'"'"'s Un-enroll deregisters it first, this cannot\n'
    if [ "$yes" != 1 ]; then
        printf '\nType uninstall to go on: '
        read -r a
        [ "$a" = uninstall ] || die "left as it was"
    fi
    say "stopping the agent and the session ports rule"
    # The GPU display's unit too (B394): left enabled, a machine BuilderBot
    # had left still started an Xorg on the card at every boot.
    local units="builderbot-agent builderbot-session-ports"
    [ "$configured" = 1 ] && units="$units builderbot-gpu-display builderbot-gpu-nodes"
    for u in $units; do
        if have systemctl; then
            systemctl disable --now "$u" >/dev/null 2>&1 || true
            rm -f "/etc/systemd/system/$u.service"
        fi
        if have rc-update; then rc-service "$u" stop >/dev/null 2>&1 || true; rc-update del "$u" default >/dev/null 2>&1 || true; rm -f "/etc/init.d/$u"; fi
        [ -d "/etc/sv/$u" ] && { rm -f "/var/service/$u"; rm -rf "/etc/sv/$u"; }
    done
    if [ "$configured" = 1 ]; then
        for f in /var/lib/builderbot/runner/*/.service /var/lib/builderbot/runner/.service; do
            [ -f "$f" ] || continue
            u="$(cat "$f")"
            have systemctl && { systemctl disable --now "$u" >/dev/null 2>&1 || true; rm -f "/etc/systemd/system/$u"; }
        done
    fi
    have systemctl && systemctl daemon-reload >/dev/null 2>&1 || true
    # The sessions' firewall and their own networks (R79): every one of them,
    # whatever ran here, so nothing of the isolation outlives the agent.
    have nft && nft delete table inet builderbot_session >/dev/null 2>&1 || true
    have nft && nft delete table inet builderbot_sessnet >/dev/null 2>&1 || true
    if have ip; then
        for a in $(ip netns list 2>/dev/null | awk '/^bbsess/ {print $1}'); do ip netns delete "$a" >/dev/null 2>&1 || true; done
        for a in $(ip -o link show 2>/dev/null | awk -F': ' '$2 ~ /^bbs/ {print $2}' | cut -d@ -f1); do ip link delete "$a" >/dev/null 2>&1 || true; done
    fi
    if [ "$doors" = 1 ]; then
        say "shutting the doors and the proxy"
        have systemctl && { systemctl disable --now cloudflared >/dev/null 2>&1 || true; rm -f /etc/systemd/system/cloudflared.service; }
        rm -rf /etc/cloudflared
        [ -x /usr/local/bin/cloudflared ] && rm -f /usr/local/bin/cloudflared
        have tailscale && tailscale logout >/dev/null 2>&1 || true
        have systemctl && { systemctl disable --now builderbot-door-22 >/dev/null 2>&1 || true; rm -f /etc/systemd/system/builderbot-door-22.service; }
        have nft && nft delete table inet builderbot_door >/dev/null 2>&1 || true
        rm -f /etc/builderbot/door-22.nft
        have systemctl && { systemctl disable --now builderbot-hosting-fw >/dev/null 2>&1 || true; rm -f /etc/systemd/system/builderbot-hosting-fw.service; }
        have nft && nft delete table inet builderbot_hosting >/dev/null 2>&1 || true
        rm -f /etc/builderbot/hosting-fw.nft
        if have docker; then
            for a in $(docker ps -aq --filter "label=com.docker.compose.project" --format '{{.ID}} {{.Label "com.docker.compose.project"}}' 2>/dev/null | awk '$2 ~ /^nginx-/ {print $1}'); do
                docker rm -f "$a" >/dev/null 2>&1 || true
            done
        fi
        have systemctl && systemctl daemon-reload >/dev/null 2>&1 || true
    fi
    if have firewall-cmd && systemctl is-active --quiet firewalld 2>/dev/null; then
        for a in $(firewall-cmd --permanent --list-rich-rules 2>/dev/null | grep -F 'port="768' | sed 's/ /\x01/g'); do
            firewall-cmd --permanent --remove-rich-rule="$(printf '%s' "$a" | sed 's/\x01/ /g')" >/dev/null 2>&1 || true
        done
        firewall-cmd --reload >/dev/null 2>&1 || true
    fi
    say "ending the accounts' processes"
    for u in "$session_user" "$DOCKER_USER"; do
        id -u "$u" >/dev/null 2>&1 || continue
        pkill -TERM -u "$u" 2>/dev/null || true
    done
    sleep 2
    for u in "$session_user" "$DOCKER_USER"; do
        id -u "$u" >/dev/null 2>&1 && pkill -KILL -u "$u" 2>/dev/null || true
    done
    if [ "$configured" = 1 ]; then
        for p in $mounts; do
            say "$p is no longer mounted"
            umount -l "$p" 2>/dev/null || true
            f="$(mktemp)"
            awk -v p="$p" '$1 ~ /^#/ || $2 != p' /etc/fstab > "$f" || true
            cat "$f" > /etc/fstab
            rm -f "$f"
        done
    fi
    have systemctl && systemctl daemon-reload >/dev/null 2>&1 || true
    if [ -f /etc/docker/daemon.json ] && have jq && grep -q 'builderbot.sandbox' /etc/docker/daemon.json; then
        f="$(mktemp)"
        if jq 'if .labels then .labels |= map(select(. != "builderbot.sandbox=1")) else . end' /etc/docker/daemon.json > "$f" 2>/dev/null; then
            cat "$f" > /etc/docker/daemon.json
            say "the sandbox label is out of /etc/docker/daemon.json (docker keeps running; it takes at its next restart)"
        fi
        rm -f "$f"
    fi
    say "removing the accounts and their homes"
    for u in "$session_user" "$DOCKER_USER"; do
        id -u "$u" >/dev/null 2>&1 || continue
        [ "$(id -u "$u")" != 0 ] || continue
        # One that was here before BuilderBot is somebody's own: left, home
        # and all (it took the session account's name on a cloud image).
        if grep -qx "$u" /etc/builderbot/kept-accounts 2>/dev/null; then
            say "kept ${u}: it was an account here before BuilderBot"
            continue
        fi
        case "$(getent passwd "$u" | cut -d: -f6)" in
            /home/*) userdel -r "$u" >/dev/null 2>&1 || userdel "$u" >/dev/null 2>&1 || true ;;
            *) userdel "$u" >/dev/null 2>&1 || true ;;
        esac
    done
    say "removing BuilderBot's files"
    # The session account's sudo rule first: it is the one grant here that
    # reaches root, and it must not outlive the helper it names (R35).
    rm -f /etc/sudoers.d/builderbot-session /etc/bb-session.conf /usr/local/sbin/bb-session
    [ "$configured" = 1 ] && rm -f /etc/X11/builderbot-gpu.conf /run/builderbot-gpu-display
    if [ "$stores" = 1 ]; then
        say "removing the stores on this disk"
        for p in $store_dirs /workspace; do
            [ -d "$p" ] || continue
            # A mountpoint is a share's, never emptied from here.
            mountpoint -q "$p" 2>/dev/null && continue
            rm -rf "$p"
        done
        rm -rf /var/lib/builderbot
    else
        rm -rf /var/lib/builderbot/agent /var/lib/builderbot/runner
    fi
    rm -rf /etc/builderbot /etc/bb-sandbox.conf /etc/profile.d/builderbot-session.sh /usr/local/sbin/builderbot-agent
    # ttyd only when the provisioner fetched it: a package's copy is the distribution's
    if [ -x /usr/local/bin/ttyd ]; then
        if ! { have dpkg && dpkg -S /usr/local/bin/ttyd >/dev/null 2>&1; } \
           && ! { have rpm && rpm -qf /usr/local/bin/ttyd >/dev/null 2>&1; }; then
            rm -f /usr/local/bin/ttyd
        fi
    fi
    # The tunnel to the controller last (R161): an uninstall pressed on the
    # Nodes tab arrived through it, and the job reports back through it.
    if [ -f /etc/wireguard/bb.conf ]; then
        say "taking down the WireGuard tunnel to the controller"
        have systemctl && systemctl disable --now wg-quick@bb >/dev/null 2>&1 || true
        rm -f /etc/wireguard/bb.conf
    fi
    say "BuilderBot is off this machine; docker, the packages, the empty mountpoints and the shares' contents are as they were$([ "$stores" = 1 ] || printf ', and so are the stores')"
    rm -f /usr/local/sbin/bb-sandbox
    exit 0
}

# --- the GPU display (R20) -------------------------------------------------
# The emulator's -gpu host needs GLES from the host driver, and NVIDIA's EGL
# will not hand out a display without an X server carrying its own GLX
# module: Xvfb has none and falls through to Mesa's llvmpipe, software by a
# slower road than the emulator's own SwiftShader. So: the distribution's
# NVIDIA driver, a real Xorg on it with no monitor, as a unit of this
# machine's own, and one line in $GPU_STATE saying what it found, which
# `bb emu gpu`, `bb doctor` and the Nodes tab read. The driver takes the card
# only after a reboot (nouveau holds it until then), so `gpu` says when one
# is needed rather than pretending; Reboot on the node's row is that press.
GPU_STATE=/run/builderbot-gpu-display
GPU_CONF=/etc/X11/builderbot-gpu.conf
GPU_UNIT=builderbot-gpu-display
GPU_LOG=/var/log/xorg-builderbot.log
gpu_state() {
    printf '%s\n' "$1" > "$GPU_STATE" 2>/dev/null || return 0
    chmod 0644 "$GPU_STATE" 2>/dev/null || true
}
gpu_card() {
    local card dev
    card="$(lspci -nn 2>/dev/null | grep -i 'nvidia' | grep -iE 'vga compatible|3d controller' | head -1 | sed 's/^[^:]*: //')"
    [ -n "$card" ] && { printf '%s\n' "$card"; return 0; }
    # No pciutils: sysfs says the same without the name, a display-class
    # device (0x03) of NVIDIA's vendor id (0x10de).
    for dev in /sys/bus/pci/devices/*; do
        [ "$(cat "$dev/vendor" 2>/dev/null)" = "0x10de" ] || continue
        case "$(cat "$dev/class" 2>/dev/null)" in 0x03*) printf 'NVIDIA device [10de:%s] at %s\n' "$(cut -c3- "$dev/device")" "$(basename "$dev")"; return 0 ;; esac
    done
    return 0
}
# apt, waiting for its lock: the machine's own apt (the daily update, an
# unattended upgrade, a toolchain's system packages) may hold it at the
# moment a press arrives, and a removal failed on exactly that on the dev
# node (30 Sep). Up to five minutes for the holder to finish, and apt-get
# itself told to wait as long for the lock. An unattended upgrade is found
# by its command line, not its name: Ubuntu keeps a helper of nearly the
# same name (unattended-upgrade-shutdown) running from boot to shutdown,
# whose fifteen-character name is the upgrade's own, and waiting on that
# made every apt call here five minutes long (B403).
apt_idle() {
    local i
    for i in $(seq 1 100); do
        pgrep -x apt-get >/dev/null 2>&1 || pgrep -x dpkg >/dev/null 2>&1 \
            || pgrep -f '(^|/)unattended-upgrade( |$)' >/dev/null 2>&1 || return 0
        [ "$i" = 1 ] && say "waiting for the machine's own apt to finish"
        sleep 3
    done
    return 0
}
apt_get() { apt_idle; apt-get -o DPkg::Lock::Timeout=300 "$@"; }
# The distribution's NVIDIA driver, from apt: the Toolchains tab's driver
# row (R102), and nothing else installs it.
gpu_install_driver() {
    # GPU_DRIVER_PKG, where the caller set one, is the metapackage of the
    # branch to install (nvidia-driver-610-open) rather than the one the
    # distribution recommends: ubuntu-drivers takes it as nvidia:610-open,
    # which brings the kernel's prebuilt modules with it.
    local want="${GPU_DRIVER_PKG:-}"
    # shellcheck source=/dev/null
    [ -r /etc/os-release ] && . /etc/os-release
    case " ${ID:-} ${ID_LIKE:-} " in
        *" ubuntu "*)
            say "installing the NVIDIA driver${want:+ ($want)} with apt; this takes minutes"
            export DEBIAN_FRONTEND=noninteractive
            apt_get update -qq
            apt_get install -y -qq ubuntu-drivers-common pciutils
            apt_idle
            if [ -n "$want" ]; then
                # By branch through ubuntu-drivers, which brings this kernel's
                # prebuilt modules; by package name where it will not take
                # the branch, which builds them with dkms.
                ubuntu-drivers install "nvidia:${want#nvidia-driver-}" \
                    || apt_get install -y -qq "$want"
            else
                ubuntu-drivers install
            fi ;;
        *" debian "*)
            say "installing the NVIDIA driver with apt (non-free); this takes minutes"
            export DEBIAN_FRONTEND=noninteractive
            apt_get update -qq
            apt_get install -y -qq nvidia-driver firmware-misc-nonfree pciutils \
                || die "apt could not install nvidia-driver: Debian keeps it in non-free, so add 'contrib non-free non-free-firmware' to the sources on this machine first, then try again" ;;
        *)
            die "the NVIDIA driver is not installed from here on ${ID:-this family} yet: install it from NVIDIA's repository for it, then try again" ;;
    esac
}
cmd_gpu() {
    local card
    card="$(gpu_card)"
    if [ -z "$card" ]; then
        gpu_state "none: no NVIDIA card on this machine"
        say "no NVIDIA card on this machine (lspci); nothing to set up"
        return 0
    fi
    say "card: $card"
    # The display runs on NVIDIA's driver and does not install it (the
    # operator, 30 Sep): the driver is the Toolchains tab's row, the one
    # place it is installed, so a machine has it because somebody chose to.
    if [ -z "$(gpu_driver_version)" ]; then
        gpu_state "needs the driver: install the NVIDIA driver on this node's Toolchains page first"
        die "the NVIDIA driver is not installed on this machine: install it from this node's Toolchains page, then set the display up"
    fi
    if ! command -v Xorg >/dev/null 2>&1; then
        have apt-get || die "no Xorg on this machine, and it is not installed from here on this family: install an X server, then set the display up again"
        say "installing a headless X server with apt"
        export DEBIAN_FRONTEND=noninteractive
        apt_get update -qq
        apt_get install -y -qq xserver-xorg-core pciutils
    fi
    gpu_nodes_unit
    command -v Xorg >/dev/null 2>&1 || die "no Xorg on this machine after the install; the display half needs one"
    cat > "/etc/systemd/system/$GPU_UNIT.service" <<EOF
# Written by bb-sandbox gpu. A headless X server on the NVIDIA card, for the
# Android emulator's -gpu host; bounded restarts, so a card the host has
# taken back is said in $GPU_STATE rather than retried forever.
[Unit]
Description=BuilderBot GPU display: a headless X server on the NVIDIA card
After=multi-user.target
StartLimitIntervalSec=900
StartLimitBurst=3

[Service]
Type=simple
ExecStart=/usr/local/sbin/bb-sandbox gpu-display
Restart=on-failure
RestartSec=20

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "$GPU_UNIT" >/dev/null 2>&1 || true
    if nvidia-smi -L >/dev/null 2>&1; then
        systemctl restart "$GPU_UNIT" || true
        sleep 4
        say "$(head -1 "$GPU_STATE" 2>/dev/null || echo 'the display unit has not said yet')"
    else
        gpu_state "reboot: the NVIDIA driver is installed and takes the card at the next boot; Reboot on this node's row"
        say "the driver is installed and takes the card at the next boot (nouveau holds it now): Reboot on this node's row, and the display comes up on its own"
    fi
}
# The emulator off the card (R102): the display's unit stopped and
# disabled, the driver and the device nodes left as they are, so sessions
# may still compute on the card. Its state line says it was switched off,
# which is not the same as down.
cmd_gpu_off() {
    if have systemctl; then
        systemctl disable --now "$GPU_UNIT" >/dev/null 2>&1 || true
    fi
    gpu_state "off: switched off on the Nodes page; an emulator here renders in software"
    say "the GPU display is off: an emulator here renders in software from its next start"
}
cmd_gpu_display() {
    local bus b d f busid pid reason=""
    # Asked before nvidia-smi, which tries to load the driver for a card that
    # is not there (B168).
    if [ -z "$(gpu_card)" ]; then
        gpu_state "down: no NVIDIA card on this machine; the driver is installed for one that is gone (remove it on the Toolchains page)"
        return 1
    fi
    if ! nvidia-smi -L >/dev/null 2>&1; then
        gpu_state "down: the card does not answer nvidia-smi (the driver is not loaded: a reboot after the install, or the host took the card back)"
        return 1
    fi
    # Xorg wants the PCI address in its own notation: nvidia-smi gives
    # domain:bus:device.function (00000000:04:00.0), the config PCI:4:0:0.
    bus="$(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader 2>/dev/null | head -1 || true)"
    IFS=':.' read -r _ b d f <<< "$bus"
    if [ -z "${f:-}" ]; then
        gpu_state "down: could not read the card's PCI address from nvidia-smi ('${bus}')"
        return 1
    fi
    busid="PCI:$((16#${b})):$((16#${d})):$((16#${f}))"
    mkdir -p /etc/X11
    cat > "$GPU_CONF" <<EOF
# Written by bb-sandbox gpu-display. Headless by design: no monitor is
# attached, and the only client is the Android emulator asking EGL for a
# display it can render into.
Section "ServerFlags"
    Option "AutoAddDevices" "false"
    Option "AutoAddGPU"     "false"
EndSection

Section "Device"
    Identifier "nvidia"
    Driver     "nvidia"
    BusID      "${busid}"
    Option     "AllowEmptyInitialConfiguration" "true"
    Option     "UseDisplayDevice" "none"
EndSection

Section "Screen"
    Identifier "screen"
    Device     "nvidia"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
        Virtual 1920 1080
    EndSubSection
EndSection
EOF
    # A dead server's socket and lock survive it, and Xorg refuses a display
    # whose lock is present.
    rm -f /tmp/.X11-unix/X0 /tmp/.X0-lock
    gpu_state "starting"
    Xorg :0 -config "$GPU_CONF" -noreset -nolisten tcp -logfile "$GPU_LOG" >/dev/null 2>&1 &
    pid=$!
    for _ in $(seq 1 40); do
        [ -S /tmp/.X11-unix/X0 ] && break
        sleep 0.5
    done
    if [ -S /tmp/.X11-unix/X0 ]; then
        # World-enterable, so a session's account can connect; the socket is
        # bound into each session's own /tmp by bb-session.
        chmod 1777 /tmp/.X11-unix 2>/dev/null || true
        gpu_state "up"
        wait "$pid" || true
        gpu_state "down: Xorg exited; see $GPU_LOG"
        return 1
    fi
    kill "$pid" 2>/dev/null || true
    if grep -qiE "module ABI major version.*does not match|ABI.*mismatch" "$GPU_LOG" 2>/dev/null; then
        reason="the nvidia X module and this Xorg disagree about the server ABI"
    elif grep -qiE "no devices detected|no screens found" "$GPU_LOG" 2>/dev/null; then
        reason="Xorg found no device at ${busid}"
    fi
    gpu_state "down: ${reason:-Xorg did not start}; see $GPU_LOG"
    return 1
}

# --- the NVIDIA driver as a row of the Toolchains tab (R102) -------------------
# The driver alone, installed and removed from the tab, apart from the
# emulator's display. It is the machine's and not the toolchain store's: its
# kernel module is built for this machine's kernel and its libraries must
# match that module exactly, so there is one per machine, installed as root,
# and it takes the card only at the next boot, since nouveau holds it until
# then. A session runs with no-new-privileges, so the setuid nvidia-modprobe
# cannot make /dev/nvidia-uvm on a CUDA program's first use: a unit of this
# machine's own makes the device nodes as root at every boot (gpu-nodes).
GPU_NODES_UNIT=builderbot-gpu-nodes
gpu_driver_version() {
    local m v k newest
    for m in modinfo /sbin/modinfo /usr/sbin/modinfo; do
        command -v "$m" >/dev/null 2>&1 || continue
        v="$("$m" -F version nvidia 2>/dev/null | head -1 || true)"
        if [ -z "$v" ]; then
            # An update Ubuntu built for the newest kernel alone, with the
            # old version's module gone from the running one: the restart
            # boots the newest, so that is where the driver is (8 Oct).
            newest="$(for k in "${GPU_MODULES:-/lib/modules}"/*; do basename "$k"; done 2>/dev/null \
                | grep -E '^[0-9]' | sort -V | tail -1 || true)"
            if [ -n "$newest" ] && [ "$newest" != "$(uname -r)" ] \
               && [ "$(printf '%s\n%s\n' "$(uname -r)" "$newest" | sort -V | tail -1)" = "$newest" ]; then
                v="$("$m" -k "$newest" -F version nvidia 2>/dev/null | head -1 || true)"
            fi
        fi
        printf '%s\n' "$v" | sed '/^$/d'
        return 0
    done
}
gpu_nodes_unit() {
    have systemctl || return 0
    cat > "/etc/systemd/system/$GPU_NODES_UNIT.service" <<EOF
# Written by bb-sandbox. The NVIDIA device nodes a CUDA program opens, made
# at boot as root: a session runs with no-new-privileges, so the setuid
# nvidia-modprobe cannot make them on a program's first use.
[Unit]
Description=BuilderBot GPU nodes: the NVIDIA device nodes for sessions
After=systemd-modules-load.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/bb-sandbox gpu-nodes
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "$GPU_NODES_UNIT" >/dev/null 2>&1 || true
}
cmd_gpu_nodes() {
    # As NVIDIA's own install guide makes them on a machine with no X
    # server: a node per card and the control node (major 195), then the
    # unified-memory module and its two nodes. Quiet where the driver does
    # not have the card yet, which is every boot until the one after the
    # install.
    local dev n=0 i=0 major
    # No card, no module to load: every try at it writes "No NVIDIA GPU
    # found" to the console, which a machine whose card went elsewhere
    # showed at every boot (B168).
    if [ -z "$(gpu_card)" ]; then
        say "no NVIDIA card on this machine; no device nodes to make"
        return 0
    fi
    if ! modprobe nvidia 2>/dev/null; then
        say "the nvidia module is not loaded (nouveau has the card until a reboot); no device nodes to make"
        return 0
    fi
    for dev in /sys/bus/pci/devices/*; do
        [ "$(cat "$dev/vendor" 2>/dev/null)" = 0x10de ] || continue
        case "$(cat "$dev/class" 2>/dev/null)" in 0x03*) n=$((n + 1)) ;; esac
    done
    while [ "$i" -lt "$n" ]; do
        [ -e "/dev/nvidia$i" ] || mknod -m 666 "/dev/nvidia$i" c 195 "$i"
        i=$((i + 1))
    done
    [ -e /dev/nvidiactl ] || mknod -m 666 /dev/nvidiactl c 195 255
    if modprobe nvidia-uvm 2>/dev/null; then
        major="$(awk '$2 == "nvidia-uvm" {print $1}' /proc/devices)"
        if [ -n "$major" ]; then
            [ -e /dev/nvidia-uvm ] || mknod -m 666 /dev/nvidia-uvm c "$major" 0
            [ -e /dev/nvidia-uvm-tools ] || mknod -m 666 /dev/nvidia-uvm-tools c "$major" 1
        fi
    fi
    chmod 0666 /dev/nvidia[0-9]* /dev/nvidiactl /dev/nvidia-uvm /dev/nvidia-uvm-tools 2>/dev/null || true
    say "device nodes: $(printf '%s ' /dev/nvidia*)"
}
cmd_gpu_driver() {
    local card ver pkgs u want="${2-}" held
    card="$(gpu_card)"
    case "${1-}" in
        refresh)
            # apt's lists brought current, so the row's pulldown and its
            # update line say what is on offer now: Check for updates.
            have apt-get || return 0
            say "reading the package lists again"
            apt_get update -qq || warn "apt-get update did not finish; the lists are as they were" ;;
        install)
            if [ -z "$card" ]; then
                say "no NVIDIA card on this machine (lspci); nothing to install"
                return 0
            fi
            say "card: $card"
            if [ -n "$want" ] && ! printf '%s' "$want" | grep -qE '^nvidia-driver(-[0-9]{3})?(-open)?$'; then
                die "$want is not a driver package: nvidia-driver-NNN or nvidia-driver-NNN-open"
            fi
            ver="$(gpu_driver_version)"
            # The metapackage on the machine now, if any: the highest branch
            # dpkg holds installed.
            held=""
            if command -v dpkg-query >/dev/null 2>&1; then
                # shellcheck disable=SC2016
                # dpkg-query exits 1 when nothing matches, which under this
                # script's set -e and pipefail ended it without a word on a
                # machine with no driver (found on the dev node, 30 Sep).
                held="$(dpkg-query -W -f='${Package} ${db:Status-Abbrev}\n' 'nvidia-driver*' 2>/dev/null | awk '$2 ~ /^ii/ {print $1}' | sort -V | tail -1 || true)"
            fi
            if [ -n "$ver" ] && [ -n "$want" ] && [ -n "$held" ] && [ "$want" != "$held" ]; then
                die "$held is installed: remove it first, then install $want. One branch at a time, since their libraries do not mix"
            fi
            if [ -n "$ver" ] && command -v nvidia-smi >/dev/null 2>&1; then
                # Installed already: brought up to what apt has for its branch,
                # through its metapackages (the driver's, and the kernel
                # flavor's module one Ubuntu ships), which pull the rest.
                # Not every NVIDIA package by name with --only-upgrade: that
                # held the running kernel's prebuilt module, pinned to the old
                # version with no newer build for that kernel, and refused a
                # firmware package the new version names afresh, so apt
                # solved nothing and the row kept offering the update (bb-sandbox,
                # 8 Oct). Apt drops that kernel's module itself; the newest
                # kernel's is the one the restart boots.
                say "the NVIDIA driver $ver is installed; bringing it up to date"
                export DEBIAN_FRONTEND=noninteractive
                apt_get update -qq
                # shellcheck disable=SC2016
                pkgs="$(dpkg-query -W -f='${Package} ${db:Status-Abbrev}\n' 2>/dev/null \
                    | awk '$2 ~ /^ii/ && $1 ~ /^(nvidia-driver(-[0-9]+)?(-open)?|linux-(modules|objects|signatures)-nvidia-[0-9]+(-open)?-[a-z][a-z0-9-]*)$/ {print $1}' \
                    | tr '\n' ' ' || true)"
                [ -n "${pkgs// /}" ] || pkgs="$held"
                [ -n "${pkgs// /}" ] || die "no NVIDIA driver package is installed through apt here, so there is nothing for apt to update"
                # shellcheck disable=SC2086
                apt_get install -y -qq $pkgs \
                    || die "apt could not update it; its output above says why"
                say "the NVIDIA driver is $(gpu_driver_version) now"
            else
                GPU_DRIVER_PKG="$want" gpu_install_driver
                ver="$(gpu_driver_version)"
                [ -n "$ver" ] || die "the install ran, but no nvidia kernel module is there for this kernel ($(uname -r)); the apt output above says why"
                say "installed the NVIDIA driver $ver"
            fi
            gpu_nodes_unit
            if [ -d /sys/module/nvidia ] && nvidia-smi -L >/dev/null 2>&1; then
                cmd_gpu_nodes
                say "the driver has the card: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1)"
            else
                say "it takes the card at the next boot, since nouveau holds it now: Reboot on this node's row in the Nodes page, which ends every session on it"
            fi ;;
        remove)
            have dpkg-query || die "the driver was not installed from here on this family: remove it the way it was installed"
            # Every NVIDIA driver package on the machine, by name, whichever
            # of the distributions' layouts put it there: the kernel module's
            # (dkms or Ubuntu's prebuilt modules), the libraries, the X module.
            # shellcheck disable=SC2016
            pkgs="$(dpkg-query -W -f='${Package} ${db:Status-Abbrev}\n' 2>/dev/null \
                | awk '$2 ~ /^ii/ && $1 ~ /^(nvidia-|libnvidia-|linux-(modules|objects|signatures)-nvidia-|xserver-xorg-video-nvidia|libcuda1|libnvcuvid1|libegl-nvidia|libgl1-nvidia|libgles-nvidia|libglx-nvidia|glx-alternative-nvidia|firmware-nvidia-)/ {print $1}' \
                | tr '\n' ' ')"
            if [ -z "${pkgs// /}" ]; then
                say "no NVIDIA driver packages are installed here"
            else
                say "removing: $pkgs"
                export DEBIAN_FRONTEND=noninteractive
                # shellcheck disable=SC2086
                apt_get purge -y -qq $pkgs || die "apt could not remove them; its output above says why"
                apt_get autoremove -y -qq >/dev/null 2>&1 || true
            fi
            # The packages first and these after (30 Sep): a removal apt
            # refused used to leave the machine with its driver and without
            # its display. The display runs on the driver, so it goes with
            # it, and the device nodes' unit too.
            if have systemctl; then
                for u in "$GPU_UNIT" "$GPU_NODES_UNIT"; do
                    systemctl disable --now "$u" >/dev/null 2>&1 || true
                    rm -f "/etc/systemd/system/$u.service"
                done
                systemctl daemon-reload >/dev/null 2>&1 || true
            fi
            rm -f "$GPU_CONF"
            gpu_state "none: the NVIDIA driver was removed"
            # A blacklist an earlier hand install left keeps nouveau off the
            # card for good; the packages' own go with them.
            rm -f /etc/modprobe.d/blacklist-nvidia-nouveau.conf
            if have update-initramfs; then update-initramfs -u >/dev/null 2>&1 || true; fi
            if [ -d /sys/module/nvidia ]; then
                say "removed; the loaded driver keeps the card until the next boot, when nouveau takes it back: Reboot on this node's row in the Nodes page"
            elif [ -z "$card" ]; then
                say "removed; there is no NVIDIA card here, and nothing tries for one at boot now"
            else
                say "removed; nouveau has the card"
            fi ;;
        *) die "usage: bb-sandbox gpu-driver install [PACKAGE]|remove|refresh" ;;
    esac
}

# --- the NVIDIA container toolkit as a row of the Toolchains tab (R102) --------
# What lets a container on this machine use the card: NVIDIA's runtime hook,
# which hands the driver's libraries and the device nodes to a container
# that asks for a GPU. Ubuntu and Debian do not carry it, so it comes from
# NVIDIA's own package source, added here with its signing key and taken
# away again on removal; Docker is told about the runtime and reloads its
# configuration, which it takes a runtime from without stopping a container.
# A restart would stop every one, and those with no restart policy stay
# down after it (the dev node's own, 30 Sep), so it is the fallback only
# where a reload did not take. The machine's own, like the driver it needs.
NVCT_LIST=/etc/apt/sources.list.d/nvidia-container-toolkit.list
# The key as NVIDIA publishes it, armored: apt reads an .asc named by
# signed-by as it is, so nothing here needs gpg, which a minimal Ubuntu
# does not carry (the dev node, 30 Sep).
NVCT_KEY=/usr/share/keyrings/nvidia-container-toolkit-keyring.asc
NVCT_URL=https://nvidia.github.io/libnvidia-container
NVCT_DOCKER=/etc/docker/daemon.json
# Docker's note of the nvidia runtime, taken out of its configuration here
# rather than by the toolkit's own tool: `nvidia-ctk runtime configure
# --unset` left the entry in place on the dev node (30 Sep), naming a
# runtime whose binary the purge had just removed. Everything else in the
# file is kept as it is.
docker_forget_nvidia() {
    [ -s "$NVCT_DOCKER" ] || return 0
    python3 - "$NVCT_DOCKER" <<'NVCTPY'
import json
import os
import sys

f = sys.argv[1]
try:
    with open(f) as h:
        d = json.load(h)
except (OSError, ValueError):
    sys.exit(1)
rt = d.get("runtimes") if isinstance(d.get("runtimes"), dict) else {}
if "nvidia" not in rt and d.get("default-runtime") != "nvidia":
    sys.exit(0)
rt.pop("nvidia", None)
if rt:
    d["runtimes"] = rt
else:
    d.pop("runtimes", None)
if d.get("default-runtime") == "nvidia":
    d.pop("default-runtime")
with open(f + ".bb-new", "w") as h:
    json.dump(d, h, indent=4)
    h.write("\n")
os.replace(f + ".bb-new", f)
NVCTPY
}
cmd_gpu_container() {
    local pkgs
    case "${1-}" in
        install)
            have apt-get || die "the container toolkit is installed from here on Debian and Ubuntu only: on this family, from NVIDIA's repository for it"
            have docker || die "no docker on this machine, so there is no container to hand the card to"
            [ -n "$(gpu_driver_version)" ] || die "the NVIDIA driver is not installed on this machine: install it from this node's Toolchains page first; the toolkit hands its libraries to a container"
            have curl || die "curl is not on this machine, and the package source is fetched with it"
            say "adding NVIDIA's package source for the container toolkit"
            curl -fsSL "$NVCT_URL/gpgkey" > "$NVCT_KEY" \
                || { rm -f "$NVCT_KEY"; die "could not fetch the package source's signing key from $NVCT_URL"; }
            grep -q 'BEGIN PGP PUBLIC KEY BLOCK' "$NVCT_KEY" \
                || { rm -f "$NVCT_KEY"; die "what $NVCT_URL answered with is not a signing key"; }
            chmod 0644 "$NVCT_KEY"
            curl -fsSL "$NVCT_URL/stable/deb/nvidia-container-toolkit.list" \
                | sed "s#deb https://#deb [signed-by=$NVCT_KEY] https://#g" > "$NVCT_LIST" \
                || { rm -f "$NVCT_LIST" "$NVCT_KEY"; die "could not fetch the package source's list from $NVCT_URL"; }
            grep -q '^deb ' "$NVCT_LIST" || { rm -f "$NVCT_LIST" "$NVCT_KEY"; die "the package source's list came back empty from $NVCT_URL"; }
            export DEBIAN_FRONTEND=noninteractive
            apt_get update -qq
            say "installing the NVIDIA container toolkit with apt"
            apt_get install -y -qq nvidia-container-toolkit || die "apt could not install it; its output above says why"
            say "telling Docker about the runtime; it reloads its configuration and running containers keep running"
            nvidia-ctk runtime configure --runtime=docker >/dev/null || die "nvidia-ctk could not write Docker's configuration"
            if have systemctl; then
                systemctl reload docker 2>/dev/null || true
                if ! docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q '"nvidia"'; then
                    say "Docker did not take the runtime on a reload, so it is restarted: a container with no restart policy stays down until it is started again"
                    systemctl restart docker || die "Docker did not come back after the restart: journalctl -u docker says why"
                fi
            fi
            say "installed: a compose file reserves the card with deploy.resources.reservations.devices (driver: nvidia)" ;;
        remove)
            have dpkg-query || die "the toolkit was not installed from here on this family: remove it the way it was installed"
            # shellcheck disable=SC2016
            pkgs="$(dpkg-query -W -f='${Package} ${db:Status-Abbrev}\n' 2>/dev/null \
                | awk '$2 ~ /^ii/ && $1 ~ /^(nvidia-container-toolkit|nvidia-container-toolkit-base|libnvidia-container1|libnvidia-container-tools)$/ {print $1}' \
                | tr '\n' ' ' || true)"
            if [ -n "${pkgs// /}" ]; then
                say "removing: $pkgs"
                export DEBIAN_FRONTEND=noninteractive
                # shellcheck disable=SC2086
                apt_get purge -y -qq $pkgs || die "apt could not remove them; its output above says why"
                apt_get autoremove -y -qq >/dev/null 2>&1 || true
            else
                say "the NVIDIA container toolkit is not installed here"
            fi
            rm -f "$NVCT_LIST" "$NVCT_KEY"
            docker_forget_nvidia || warn "could not take the nvidia runtime out of $NVCT_DOCKER: it names a runtime that is no longer installed"
            if have systemctl && have docker; then
                systemctl reload docker 2>/dev/null || warn "Docker did not reload its configuration"
                # A reload takes a runtime on and does not take one off (the
                # dev node, 30 Sep): said, since docker info goes on naming it.
                if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q '"nvidia"'; then
                    say "Docker goes on listing the nvidia runtime until it next restarts; nothing is behind it, and its configuration no longer names it"
                fi
            fi
            say "removed, with NVIDIA's package source" ;;
        *) die "usage: bb-sandbox gpu-container install|remove" ;;
    esac
}

# --- features (R91) ---------------------------------------------------------
# What a node has beyond the base, each an install and a remove, run by the
# provisioner's flag at enrollment and by the agent's `feature` system job
# from the Nodes page: one copy, so the two ways cannot drift. A marker
# under /etc/builderbot/features says BuilderBot put it there, and lists the
# packages it added, so a remove takes those and leaves what the machine
# had before.
FEATURES_DIR=/etc/builderbot/features
os_family() {
    local ids
    ids="$(. /etc/os-release 2>/dev/null; printf ' %s %s ' "${ID:-}" "${ID_LIKE:-}")"
    case "$ids" in
        *" debian "*|*" ubuntu "*) echo deb ;;
        *" rhel "*|*" fedora "*|*" centos "*|*" rocky "*|*" almalinux "*) echo rhel ;;
        *" arch "*|*" archlinux "*) echo arch ;;
        *" suse "*|*" opensuse "*|*" opensuse-leap "*|*" opensuse-tumbleweed "*) echo suse ;;
        *" alpine "*) echo alpine ;;
        *) echo "" ;;
    esac
}
# The packages a feature needs here that are not installed yet, by family.
pkgs_missing() {
    local fam="$1"; shift
    local p
    for p in "$@"; do
        case "$fam" in
            deb) dpkg-query -W -f='${db:Status-Abbrev}' "$p" 2>/dev/null | grep -q '^ii' || printf '%s ' "$p" ;;
            rhel|suse) rpm -q "$p" >/dev/null 2>&1 || printf '%s ' "$p" ;;
            arch) pacman -Q "$p" >/dev/null 2>&1 || printf '%s ' "$p" ;;
            alpine) apk info -e "$p" >/dev/null 2>&1 || printf '%s ' "$p" ;;
        esac
    done
}
pkgs_add() {
    local fam="$1"; shift
    [ $# -gt 0 ] || return 0
    case "$fam" in
        deb) export DEBIAN_FRONTEND=noninteractive; apt_get update -qq; apt_get install -y -qq --no-install-recommends "$@" ;;
        rhel) dnf install -y -q "$@" ;;
        arch) pacman -S --noconfirm --needed --quiet "$@" ;;
        suse) zypper -n -q install --no-recommends "$@" ;;
        alpine) apk add -q "$@" ;;
    esac
}
# Exactly what is installed, one package a line: taken before and after an
# install, the difference is every package it added, dependencies included,
# so a remove takes those and no package that was orphaned before it.
pkgs_all() {
    case "$1" in
        deb) dpkg-query -W -f='${db:Status-Abbrev} ${Package}\n' 2>/dev/null | awk '$1 ~ /^ii/ {print $2}' | LC_ALL=C sort -u ;;
        rhel|suse) rpm -qa --qf '%{NAME}\n' 2>/dev/null | LC_ALL=C sort -u ;;
        arch) pacman -Qq 2>/dev/null | LC_ALL=C sort -u ;;
        alpine) apk info 2>/dev/null | LC_ALL=C sort -u ;;
    esac
}
pkgs_drop() {
    local fam="$1"; shift
    [ $# -gt 0 ] || return 0
    case "$fam" in
        deb) export DEBIAN_FRONTEND=noninteractive; apt_get purge -y -qq "$@" ;;
        rhel) dnf remove -y -q --noautoremove "$@" ;;
        arch) pacman -R --noconfirm "$@" ;;
        suse) zypper -n -q remove --clean-deps "$@" ;;
        alpine) apk del -q "$@" ;;
    esac
}
vmhost_pkgs() {
    case "$1:$(uname -m)" in
        deb:x86_64)  echo "qemu-system-x86 qemu-utils libvirt-daemon-system libvirt-clients cloud-image-utils ovmf virtiofsd" ;;
        deb:aarch64) echo "qemu-system-arm qemu-efi-aarch64 qemu-utils libvirt-daemon-system libvirt-clients cloud-image-utils virtiofsd" ;;
        rhel:*)      echo "qemu-kvm qemu-img libvirt-daemon-kvm libvirt-client edk2-ovmf xorriso virtiofsd" ;;
        arch:x86_64) echo "qemu-base libvirt dnsmasq edk2-ovmf libisoburn virtiofsd" ;;
        suse:x86_64) echo "qemu-kvm libvirt-daemon-qemu libvirt-client qemu-ovmf-x86_64 xorriso virtiofsd" ;;
        alpine:x86_64) echo "qemu-system-x86_64 qemu-img libvirt-daemon libvirt-qemu ovmf xorriso dnsmasq virtiofsd" ;;
    esac
}
# A VM's shared folder (R100) through virtiofsd, which libvirt runs as root
# and which hands the guest's uids straight through: a file root wrote in
# the VM was root's in the project, and the VM's own account could write
# nothing. libvirt starts this in its place: every uid in the VM writes as
# the folder's owner here, and the folder's files are the VM's account's
# (uid 2000, which the agent's cloud-init gives it) inside.
VIRTIOFSD_WRAP=/usr/local/libexec/builderbot-virtiofsd
vmhost_virtiofsd() {
    install -d -m 0755 /usr/local/libexec
    cat > "$VIRTIOFSD_WRAP" <<'WRAP'
#!/bin/sh
# BuilderBot's virtiofsd for a VM's shared folder: see vmhost_virtiofsd in
# provision-linux.sh. libvirt passes --shared-dir; the rest goes through.
real=$(command -v virtiofsd || ls /usr/libexec/virtiofsd /usr/lib/qemu/virtiofsd 2>/dev/null | head -n 1)
dir="" prev=""
for a in "$@"; do
    [ "$prev" = "--shared-dir" ] && dir="$a"
    case "$a" in --shared-dir=*) dir="${a#*=}" ;; esac
    prev="$a"
done
[ -n "$dir" ] || exec "$real" "$@"
u=$(stat -c %u "$dir") g=$(stat -c %g "$dir")
exec "$real" "$@" \
    --translate-uid "squash-guest:0:$u:4294967295" --translate-gid "squash-guest:0:$g:4294967295" \
    --translate-uid "squash-host:0:2000:4294967295" --translate-gid "squash-host:0:2000:4294967295"
WRAP
    chmod 0755 "$VIRTIOFSD_WRAP"
}
feature_vmhost() {
    local fam pkgs added n
    fam="$(os_family)"
    case "$1" in
        state) [ -f "$FEATURES_DIR/vmhost" ] && echo installed || echo absent ;;
        install)
            # No /dev/kvm is a machine that cannot run a VM at speed: a VM
            # whose host does not pass virtualization through, or a box with
            # it off in the firmware. Said, not emulated (tens of times slower).
            [ -e /dev/kvm ] || die "no /dev/kvm here, so VMs would run in software, tens of times slower. On a VM, its host must pass virtualization through: CPU mode host-passthrough (Unraid: CPU Mode Host Passthrough; Proxmox: CPU type host) and nested KVM on in the host's kvm_intel or kvm_amd. On a machine of its own, turn VT-x or AMD-V on in its firmware"
            [ -n "$fam" ] || die "VM host is installed on the Debian, RHEL, Arch, openSUSE and Alpine families; this machine is none of them"
            pkgs="$(vmhost_pkgs "$fam")"
            [ -n "$pkgs" ] || die "no VM host packages for $(uname -m) on this family"
            # shellcheck disable=SC2086
            added="$(pkgs_missing "$fam" $pkgs)"
            say "VM host: KVM through libvirt"
            local before
            before="$(pkgs_all "$fam")"
            # The marker first, naming what it sets out to add, so a run that
            # fails part way still leaves what it may have put here on record.
            install -d -m 0755 "$FEATURES_DIR"
            printf 'packages=%s\n' "$added" > "$FEATURES_DIR/vmhost.partial"
            # shellcheck disable=SC2086
            pkgs_add "$fam" $added || die "the packages did not install; the output above says why ($FEATURES_DIR/vmhost.partial names what it set out to add)"
            added="$(LC_ALL=C comm -13 <(printf '%s\n' "$before") <(pkgs_all "$fam") | tr '\n' ' ')"
            have systemctl && { systemctl enable --now libvirtd >/dev/null 2>&1 || systemctl enable --now virtqemud.socket >/dev/null 2>&1 || true; }
            # Alpine's OpenRC, which has no systemctl.
            have rc-update && { rc-update add libvirtd default >/dev/null 2>&1; rc-service libvirtd start >/dev/null 2>&1 || true; }
            getent group libvirt >/dev/null 2>&1 && id -u "$DOCKER_USER" >/dev/null 2>&1 && usermod -aG libvirt "$DOCKER_USER"
            # The cached cloud images and each VM's disk, the jobs account's;
            # 0755 so libvirt's own account reaches the disks it is handed.
            install -d -m 0755 -o "$DOCKER_USER" /var/lib/builderbot/vms /var/lib/builderbot/vms/images /var/lib/builderbot/vms/disks
            vmhost_virtiofsd
            # Run again on a machine that has it (a package the feature has
            # gained since, UEFI's firmware), what it added before is kept.
            [ -f "$FEATURES_DIR/vmhost" ] && added="$(sed -n 's/^packages=//p' "$FEATURES_DIR/vmhost") $added"
            printf 'packages=%s\n' "$(printf '%s\n' $added | LC_ALL=C sort -u | tr '\n' ' ')" > "$FEATURES_DIR/vmhost"
            rm -f "$FEATURES_DIR/vmhost.partial"
            say "VM host installed${added:+ ($(printf '%s' "$added" | wc -w) packages added)}; ${DOCKER_USER} runs the VMs, and no session can" ;;
        remove)
            [ -f "$FEATURES_DIR/vmhost.partial" ] && [ ! -f "$FEATURES_DIR/vmhost" ] && mv "$FEATURES_DIR/vmhost.partial" "$FEATURES_DIR/vmhost"
            [ -f "$FEATURES_DIR/vmhost" ] || { say "VM host was not installed by BuilderBot here; nothing to remove"; return 0; }
            if have virsh; then
                n="$(virsh -c qemu:///system list --all --name 2>/dev/null | grep -c . || true)"
                [ "${n:-0}" -eq 0 ] || die "${n} VM(s) are on this machine: remove them first, then VM host"
            fi
            say "taking VM host off"
            rm -f "$VIRTIOFSD_WRAP"
            getent group libvirt >/dev/null 2>&1 && gpasswd -d "$DOCKER_USER" libvirt >/dev/null 2>&1 || true
            rm -rf /var/lib/builderbot/vms
            added="$(sed -n 's/^packages=//p' "$FEATURES_DIR/vmhost")"
            # shellcheck disable=SC2086
            [ -z "${added// /}" ] || pkgs_drop "$fam" $added || warn "the packages did not all come off; the output above says why"
            rm -f "$FEATURES_DIR/vmhost"
            say "VM host removed${added:+ ($(printf '%s' "$added" | wc -w) packages it had added)}; what was here before it stays" ;;
    esac
}
# The hosting-only box closed on itself (R93): 80 and 443 in, and port 22
# as the door left it. Docker's published ports are DNAT'd in prerouting
# and never reach the input hook, so a compose that publishes 0.0.0.0:5432
# was open to the world whatever the input rules said: the forward chain
# drops any DNAT'd connection from outside the box's own bridges but on 80
# and 443. Its own table, as the door's is, re-applied at boot.
feature_firewall() {
    local ssh_rule su
    case "$1" in
        state) [ -f /etc/builderbot/hosting-fw.nft ] && echo installed || echo absent ;;
        install)
            su="$(python3 -c 'import json; print(json.load(open("/etc/builderbot/node.json")).get("session_user", ""))' 2>/dev/null || true)"
            [ -z "$su" ] || die "the firewall is for a hosting-only node: it would shut the session ports the controller reaches ${su}'s sessions on"
            have nft || pkgs_add "$(os_family)" nftables || true
            have nft || die "nft is not here and could not be installed"
            say "firewall: only 80 and 443 come in"
            ssh_rule="tcp dport 22 accept"
            if nft list table inet builderbot_door >/dev/null 2>&1; then
                ssh_rule="tcp dport 22 ip saddr 100.64.0.0/10 accept"
                printf '   port 22: through the door only, as it was closed\n'
            else
                printf '   port 22: open, as no door closed it\n'
            fi
            install -d -m 0755 /etc/builderbot
            cat > /etc/builderbot/hosting-fw.nft <<NFT
# Written by bb-sandbox feature install firewall: 80 and 443 in, and port 22 as the door left it.
table inet builderbot_hosting
delete table inet builderbot_hosting
table inet builderbot_hosting {
    chain input {
        type filter hook input priority -5; policy drop;
        iifname "lo" accept
        ct state established,related accept
        ct state invalid drop
        meta l4proto { icmp, ipv6-icmp } accept
        udp sport 67 udp dport 68 accept
        udp sport 547 udp dport 546 accept
        iifname "docker0" accept
        iifname "br-*" accept
        iifname "tailscale0" accept
        udp dport 41641 accept
        tcp dport { 80, 443 } accept
        udp dport 443 accept
        ${ssh_rule}
    }
    chain forward {
        type filter hook forward priority -5; policy accept;
        ct state established,related accept
        iifname { "lo", "docker0" } accept
        iifname "br-*" accept
        ct status dnat meta l4proto tcp ct original proto-dst { 80, 443 } accept
        ct status dnat meta l4proto udp ct original proto-dst 443 accept
        ct status dnat drop
    }
}
NFT
            nft -f /etc/builderbot/hosting-fw.nft || { rm -f /etc/builderbot/hosting-fw.nft; die "nft could not apply the firewall, so this box takes in what it did before"; }
            if have systemctl; then
                cat > /etc/systemd/system/builderbot-hosting-fw.service <<UNIT
[Unit]
Description=BuilderBot: a hosting-only box takes in 80 and 443
After=network-pre.target
Before=docker.service
[Service]
Type=oneshot
ExecStart=$(command -v nft) -f /etc/builderbot/hosting-fw.nft
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
                systemctl daemon-reload >/dev/null 2>&1 || true
                systemctl enable builderbot-hosting-fw >/dev/null 2>&1 || true
            fi
            say "firewall on: a container that publishes another port is not reached from outside; nginx in front of it is the way" ;;
        remove)
            have systemctl && { systemctl disable --now builderbot-hosting-fw >/dev/null 2>&1 || true; rm -f /etc/systemd/system/builderbot-hosting-fw.service; systemctl daemon-reload >/dev/null 2>&1 || true; }
            have nft && nft delete table inet builderbot_hosting >/dev/null 2>&1 || true
            rm -f /etc/builderbot/hosting-fw.nft
            say "firewall off: this box takes in what its other rules allow" ;;
    esac
}
FEATURE_IDS="vmhost firewall"
cmd_feature() {
    local op="${1-}" id="${2-}"
    case "$op" in install|remove|state) ;; *) die "usage: bb-sandbox feature install|remove|state ID (one of: ${FEATURE_IDS})" ;; esac
    case " $FEATURE_IDS " in *" $id "*) ;; *) die "no such feature: ${id:-none named}; one of: ${FEATURE_IDS}" ;; esac
    "feature_${id}" "$op"
}

case "${1-}" in
    # The menu only when asked for by name, and only at a terminal (the
    # operator, 11 Oct): a bare bb-sandbox reached from a run of the enroll
    # script opened it on a VPS's console, where its keys did not work and
    # the run could not go on. The enroll script and the Nodes tab are the
    # way to configure a node; this is the by-hand fallback.
    menu)        [ -t 0 ] && [ -t 1 ] || die "the menu needs a terminal: run sudo bb-sandbox menu from a shell"
                 if have whiptail; then menu_whiptail; else menu_plain; fi ;;
    "")          sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
                 printf '\nCommands: list, check, settings, add-nfs, add-share, remove, appdata, readonly, uninstall; menu for the interactive one.\n' ;;
    uninstall)   shift; cmd_uninstall "$@" ;;
    gpu)         cmd_gpu ;;
    gpu-display) cmd_gpu_display ;;
    gpu-off)     cmd_gpu_off ;;
    gpu-driver)  shift; cmd_gpu_driver "${1-}" "${2-}" ;;
    gpu-nodes)   cmd_gpu_nodes ;;
    gpu-container) shift; cmd_gpu_container "${1-}" ;;
    list)        shift; if [ "${1-}" = "--json" ]; then cmd_list_json; else cmd_list; fi ;;
    add-nfs)     shift; cmd_add_nfs "${1-}" ;;
    add-share)   shift; cmd_add_share "${1-}" ;;
    remove)      shift; cmd_remove "${1-}" ;;
    check)       cmd_check ;;
    appdata)     shift; cmd_appdata "${1-}" ;;
    readonly)    shift; cmd_readonly "${1-}" "${2-on}" ;;
    settings)    cmd_settings ;;
    sdk)         shift; cmd_sdk "$@" ;;
    feature)     shift; cmd_feature "${1-}" "${2-}" ;;
    -h|--help|help)
        sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) die "unknown command: $1. Try: bb-sandbox --help" ;;
esac
BBSANDBOX
install -m 0750 "$BBSANDBOX_TMP" /usr/local/sbin/bb-sandbox
rm -f "$BBSANDBOX_TMP"
# Root's, and nobody else's: 0750 root:root. Anyone the operator has given
# sudo reaches it as `sudo bb-sandbox`, which is how it is meant to be run;
# it refuses to run as anyone but root anyway. The docker account cannot read
# it, let alone run it, which is most of what "bb cannot reconfigure this
# machine" means in practice.
chown root:root /usr/local/sbin/bb-sandbox 2>/dev/null || true
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
printf '   /usr/local/sbin/bb-sandbox: run it as root to add mounts later\n'

say "shares"
# Written to fstab rather than mounted once, because a sandbox that comes back
# from a reboot without a share it builds from is a sandbox that builds the
# wrong thing rather than failing. bb-sandbox does the writing, and keeps doing it
# every time a share is added after today: one implementation, not a copy per
# entry point.
declare -a MOUNTED=()
# A share that will not mount is reported, not fatal. set -e would otherwise
# abandon the rest of provisioning (the tcp option, the closing summary) over
# an NFS export that is not ready yet, which is the most ordinary way for this
# to fail and the one the check below exists to report.
for spec in "${SHARES[@]:-}"; do
    [ -n "$spec" ] || continue
    /usr/local/sbin/bb-sandbox add-share "$spec" || warn "$spec did not mount; see the check below"
    p="${spec%:ro}"; MOUNTED+=("${p#*:}")
done
for spec in "${NFS[@]:-}"; do
    [ -n "$spec" ] || continue
    /usr/local/sbin/bb-sandbox add-nfs "$spec" || warn "$spec did not mount; see the check below"
    p="${spec%:ro}"; MOUNTED+=("${p##*:}")
done
# SELinux stays enforcing on the RHEL family (nothing here needs it off),
# but by default it stops a container from reading an NFS mount, which is
# exactly what a dev instance's bind of a share is. One boolean,
# persistent, says containers may; the mounts themselves are unaffected.
# Set whenever SELinux enforces, not only when --nfs was given on this
# run: a share added later through the Nodes tab goes through bb-sandbox,
# which does not know this, and the boolean costs nothing with no NFS.
if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce 2>/dev/null)" = Enforcing ]; then
    setsebool -P virt_use_nfs 1 2>/dev/null \
        || warn "could not set virt_use_nfs, so containers will be refused the NFS shares until it is on"
fi
# Checked rather than assumed, which is the difference between finding out now
# and finding out from an app that came up with no data. bb-sandbox owns the
# check for the same reason it owns the writing (one implementation), and the
# operator can run it again any day with `bb-sandbox check`.
if [ "${#MOUNTED[@]}" -gt 0 ]; then
    /usr/local/sbin/bb-sandbox check || true
fi

# Docker listens on its socket and nothing else. An open 2375 is root on this
# machine to anyone who can reach it, and BuilderBot will not talk to one
# anyway: ssh is the only way in, which is why no port has to be opened here.
if [ -f /etc/systemd/system/docker.service.d/tcp.conf ]; then
    say "closing tcp/2375, which an earlier run opened"
    rm -f /etc/systemd/system/docker.service.d/tcp.conf
    systemctl daemon-reload
    systemctl restart docker
fi

# --- the agent ------------------------------------------------------------
# With --controller and --token this machine also becomes a node: it dials
# the controller, takes jobs, and reports what it has. The agent is one
# Python file the controller itself serves, fetched with the enroll token,
# so nothing else has to be published or kept in step, and it runs under
# systemd as root ONLY so that it can drop to ${USER_NAME} for every job it
# runs, and so that phase 5's system jobs (mounts, network) have somewhere to
# run. The credential it ends up holding (/etc/builderbot/node.json, 0600)
# opens that node's own row and nothing else.
AGENT=/usr/local/sbin/builderbot-agent
# THE SESSIONS ARE NOT THIS UNIT'S TO KILL. systemd's default KillMode is
# control-group: a stop takes every process in the cgroup with it, and the
# agent's cgroup holds the ttyds it starts, the tmux servers under them and
# the Claude sessions inside those. So pressing Update agent ended every
# conversation on the machine, mid-work, with nothing said (B107). The
# agent's own shutdown already stops what is its to stop: its ttyds, and now
# its jobs. KillMode=process makes systemd's half match that.
AGENT_KILLMODE='KillMode=process'

AGENT_DESC="BuilderBot node agent - dials in to the controller and runs its jobs"
if [ -n "$CONTROLLER" ]; then
    say "agent: enrolling with ${CONTROLLER}"
    # shellcheck disable=SC2046
    pkg $(pkg_names python)
    hdr="$(mktemp)"
    curl -fsSL -D "$hdr" -H "Authorization: Bearer ${TOKEN}" \
         "${CONTROLLER%/}/api/v1/agent/download" -o "${AGENT}.new" \
        || { warn "could not download the agent from ${CONTROLLER}. Is that the dashboard's address, and is the token unused?"; rm -f "$hdr" "${AGENT}.new"; exit 1; }
    # The digest the controller says it served, against what arrived. The
    # same check the agent makes of its own updates, made once by hand here.
    want="$(tr -d '\r' < "$hdr" | awk 'tolower($1)=="x-agent-digest:"{print $2}')"
    got="sha256:$(sha256sum "${AGENT}.new" | cut -d' ' -f1)"
    rm -f "$hdr"
    if [ -n "$want" ] && [ "$want" != "$got" ]; then
        warn "the agent that arrived does not match the digest the controller sent (${got} vs ${want})"
        rm -f "${AGENT}.new"; exit 1
    fi
    # Nothing, or no digest to check it by, is not the controller's agent:
    # an empty file ran as an empty script, said nothing, exited 0, and the
    # node never enrolled (11 Oct).
    if [ -z "$want" ] || [ ! -s "${AGENT}.new" ]; then
        warn "what ${CONTROLLER} sent for the agent is not BuilderBot's ($(stat -c %s "${AGENT}.new" 2>/dev/null || echo 0) bytes, ${want:-no digest}): the address does not reach the controller's agent API"
        rm -f "${AGENT}.new"; exit 1
    fi
    chmod 755 "${AGENT}.new"; mv -f "${AGENT}.new" "$AGENT"
    svc_stop builderbot-agent
    "$AGENT" enroll --controller "$CONTROLLER" --token "$TOKEN" --user "$USER_NAME" \
        ${SESSION_NAME:+--session-user "$SESSION_NAME"} ${REACH:+--reach "$REACH"} \
        ${DOOR:+--door "$DOOR"} ${DOOR_HOST:+--door-host "$DOOR_HOST"} \
        --store "data=${STORE_DATA}" --store "toolchains=${STORE_TOOLCHAINS}" \
        --store "cache=${STORE_CACHE}" --store "artifacts=${STORE_ARTIFACTS}" \
        --store "appdata=${STORE_APPDATA}"
    # The tunnel into the node's own record (R161): the agent binds the
    # session ports to its address there, and reports it.
    if [ -n "$WG_ADDR" ]; then
        python3 - "$WG_ADDR" <<'PY'
import json, sys
p = "/etc/builderbot/node.json"
d = json.load(open(p))
d["tunnel"] = {"kind": "wireguard", "iface": "bb", "addr": sys.argv[1]}
json.dump(d, open(p, "w"), indent=2)
PY
    fi
    svc_install builderbot-agent "$AGENT_DESC" "${AGENT} run" "$AGENT_KILLMODE"
# Public port 22 shut only now, with the node enrolled and the door's client
# up: a run that closed it first and then could not enroll left the person
# coming back in through the KVM (11 Oct). The loopback (cloudflared's
# path) and a tailnet address are left alone; its own table, re-applied at
# boot by a unit where this machine has systemd.
door_up=""
case "$DOOR" in
    cloudflared) systemctl is-active --quiet cloudflared 2>/dev/null && door_up=1 ;;
    tailscale)   tailscale status >/dev/null 2>&1 && door_up=1 ;;
esac
if [ -n "$DOOR" ] && [ "$DOOR_CLOSE22" = 1 ] && [ -z "$door_up" ]; then
    warn "port 22 stays open: the door (${DOOR}) is not up yet, and closing 22 without it would lock this machine"
fi
if [ -n "$DOOR" ] && [ "$DOOR_CLOSE22" = 1 ] && [ -n "$door_up" ]; then
    say "port 22: closed to the internet (the door is the way in)"
    printf '   a connection already open on it, this one included, stays up; a new one comes through the door\n'
    # shellcheck disable=SC2046
    command -v nft >/dev/null 2>&1 || pkg $(pkg_names nft) >/dev/null 2>&1 || true
    install -d -m 0755 /etc/builderbot
    cat > /etc/builderbot/door-22.nft <<'NFT'
# Written by BuilderBot's provision-linux.sh: port 22 from the loopback and the tailnet only.
table inet builderbot_door
delete table inet builderbot_door
table inet builderbot_door {
    chain input {
        type filter hook input priority -10; policy accept;
        tcp dport 22 iifname "lo" accept
        tcp dport 22 ip saddr 100.64.0.0/10 accept
        tcp dport 22 ct state established,related accept
        tcp dport 22 drop
    }
}
NFT
    if nft -f /etc/builderbot/door-22.nft 2>/dev/null; then
        if [ "$INIT" = systemd ]; then
            cat > /etc/systemd/system/builderbot-door-22.service <<UNIT
[Unit]
Description=BuilderBot: port 22 reachable through the door only
After=network-pre.target
[Service]
Type=oneshot
ExecStart=$(command -v nft) -f /etc/builderbot/door-22.nft
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
            systemctl enable builderbot-door-22 >/dev/null 2>&1 || true
        fi
    else
        warn "nft could not apply the port 22 rule, so port 22 stays as it was"
    fi
fi
elif [ -f /etc/builderbot/node.json ] && [ -x "$AGENT" ]; then
    # Enrolled on an earlier run. The agent does NOT keep itself current
    # (the dashboard's Update button queues that as a job, and nothing runs
    # it unasked), so a re-run here is the console path to the same thing:
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
                svc_restart builderbot-agent 2>/dev/null || true
                say "agent: updated ${have:7:12} -> ${got:7:12} and restarted"
            fi
        else
            warn "could not fetch the agent from ${ctl}. Is the controller up? The installed agent is left as it is"
            rm -f "${AGENT}.new"
        fi
        rm -f "$hdr"
    else
        warn "/etc/builderbot/node.json carries no controller or token; re-enroll with a fresh token to update"
    fi
    # The session account is part of the enrollment record, and a node
    # enrolled before there was one carries none, so a re-run that made
    # the account has to say so in the record too, or the agent keeps
    # reporting "no session account" and the dashboard keeps the button
    # dead. Written here rather than by re-enrolling: a re-enrollment is a
    # NEW node row, and every project bound to the old one would lose it.
    if [ -n "$(python3 - "${SESSION_NAME:-}" <<'PY'
import json, sys
p = "/etc/builderbot/node.json"
d = json.load(open(p))
want = sys.argv[1]
if d.get("session_user", "") != want:
    d["session_user"] = want
    json.dump(d, open(p, "w"), indent=2)
    print("changed")
PY
    )" ]; then
        say "agent: sessions now run as ${SESSION_NAME:-nobody}; restarting the agent"
        svc_restart builderbot-agent 2>/dev/null || true
    fi
    svc_active builderbot-agent || svc_install builderbot-agent "$AGENT_DESC" "${AGENT} run" "$AGENT_KILLMODE"
fi

# --- the features asked for (R91) -------------------------------------------
# Each through bb-sandbox's own install, the one the Nodes page's Features
# section runs later: after the enrollment, so a run that cannot enroll
# leaves the machine as it found it, and a feature that cannot go on here
# (no /dev/kvm for a VM host) is said without failing the enrollment.
for f in "${FEATURES_WANT[@]}"; do
    /usr/local/sbin/bb-sandbox feature install "$f" \
        || warn "${f} did not install; the node is enrolled without it, and its Features section on the Nodes page can try again"
done

# --- the session ports, to the controller only (roadmap #24, phase 10b) ----
# The agent binds ttyd on this machine's LAN address so the controller's
# terminal proxy can dial it, and a ttyd on the LAN with no credential of
# its own is a shell for anyone who can reach the port, cookie or no cookie
# (the proxy is the gate, and it is on the other machine). The third is the
# container terminal (R218 step 4), as the docker account. So the three ports
# are opened to the controller's address and nothing else, with nftables,
# in a table of this script's own that leaves whatever else the machine
# filters alone. Re-applied at boot by a unit, and rewritten here on every
# run, so a controller that moved is one re-run away.
ctl_url="$CONTROLLER"
[ -n "$ctl_url" ] || ctl_url="$(python3 -c 'import json; print(json.load(open("/etc/builderbot/node.json")).get("controller", ""))' 2>/dev/null || true)"
if [ -n "$SESSION_NAME" ] && [ -n "$ctl_url" ]; then
    say "session ports: 7681, 7682, 7683 (a container's shell) and 7684 (a VM's screen) open to the controller only"
    ctl_host="${ctl_url#*://}"; ctl_host="${ctl_host%%/*}"; ctl_host="${ctl_host%%:*}"
    ctl_host="${ctl_host#\[}"; ctl_host="${ctl_host%\]}"
    ctl_ip="$(getent ahosts "$ctl_host" 2>/dev/null | awk 'NR==1{print $1}' || true)"
    if [ -z "$ctl_ip" ]; then
        warn "could not resolve the controller's host ${ctl_host}, so the session ports are NOT filtered"
    elif systemctl is-active --quiet firewalld 2>/dev/null; then
        # firewalld owns nftables here (the RHEL family, or a Debian that
        # chose it): a table of our own beside it would be flushed on its
        # next reload. Its rich rules say the same thing (the two ports to
        # the controller and to nobody else), and the default zone already
        # drops what no rule allows. Rewritten on every run, like the table.
        case "$ctl_ip" in *:*) fam=ipv6 ;; *) fam=ipv4 ;; esac
        for r in $(firewall-cmd --permanent --list-rich-rules 2>/dev/null | grep -F 'port="768' | sed 's/ /\x01/g'); do
            firewall-cmd --permanent --remove-rich-rule="$(printf '%s' "$r" | sed 's/\x01/ /g')" >/dev/null 2>&1 || true
        done
        for port in 7681 7682 7683 7684; do
            firewall-cmd --permanent --add-rich-rule="rule family=\"${fam}\" source address=\"${ctl_ip}\" port port=\"${port}\" protocol=\"tcp\" accept" >/dev/null
        done
        firewall-cmd --reload >/dev/null
        printf '   firewalld: from %s (%s); everything else dropped\n' "$ctl_host" "$ctl_ip"
    else
        # shellcheck disable=SC2046
        command -v nft >/dev/null 2>&1 || pkg $(pkg_names nft) >/dev/null 2>&1 || true
        case "$ctl_ip" in *:*) fam=ip6 ;; *) fam=ip ;; esac
        install -d -m 0755 /etc/builderbot
        cat > /etc/builderbot/session-ports.nft <<EOF
# Written by BuilderBot's provision-linux.sh: the session ttyds, reachable from the
# controller (${ctl_host}) and the loopback, and from nowhere else.
table inet builderbot_session
delete table inet builderbot_session
table inet builderbot_session {
    chain input {
        type filter hook input priority -10; policy accept;
        tcp dport { 7681, 7682, 7683, 7684 } iifname "lo" accept
        tcp dport { 7681, 7682, 7683, 7684 } ${fam} saddr ${ctl_ip} accept
        tcp dport { 7681, 7682, 7683, 7684 } drop
    }
}
EOF
        if nft -f /etc/builderbot/session-ports.nft 2>/dev/null; then
            # ...and again at every boot, the way this init runs a one-shot:
            # a unit, an OpenRC local.d script, or a line in rc.local.
            nft_cmd="$(command -v nft) -f /etc/builderbot/session-ports.nft"
            case "$INIT" in
                systemd)
                    cat > /etc/systemd/system/builderbot-session-ports.service <<EOF
[Unit]
Description=BuilderBot: the session ports open to the controller only
After=network-pre.target
Wants=network-pre.target
Before=network.target builderbot-agent.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=${nft_cmd}

[Install]
WantedBy=multi-user.target
EOF
                    systemctl daemon-reload
                    systemctl enable builderbot-session-ports >/dev/null 2>&1 || true ;;
                openrc)
                    install -d -m 0755 /etc/local.d
                    printf '#!/bin/sh\n# BuilderBot: the session ports open to the controller only\n%s\n' "$nft_cmd" \
                        > /etc/local.d/builderbot-session-ports.start
                    chmod 0755 /etc/local.d/builderbot-session-ports.start
                    rc-update add local default >/dev/null 2>&1 || true ;;
                runit)
                    touch /etc/rc.local; chmod 0755 /etc/rc.local
                    grep -qF "$nft_cmd" /etc/rc.local || printf '%s\n' "$nft_cmd" >> /etc/rc.local ;;
            esac
            printf '   from %s (%s); everything else dropped\n' "$ctl_host" "$ctl_ip"
        else
            warn "nft could not apply the rule, so the session ports are NOT filtered"
        fi
    fi
fi

ip="$(my_ip || true)"
if [ "${#WARNINGS[@]}" -gt 0 ]; then
    say "the pre-flight warned about ${#WARNINGS[@]} thing(s), still true:"
    for w in "${WARNINGS[@]}"; do printf '   - %s\n' "$w"; done
fi
# Where the machine is, which is all anybody needs from here: an enrolled
# node dials OUT, so the controller is told the address by the agent rather
# than given one.
cat <<EOF

== done

This machine is at ${ip:-<this-vm>}. A web UI a container here publishes is
reachable at http://${ip:-<this-vm>}:<port> directly, because this VM has its
own address on your network.

What this machine mounts:
EOF

# Asked of bb-sandbox rather than echoed back from the arguments. Re-running
# with no --share and no --nfs is the ordinary way to pick up a newer
# bb-sandbox, and the old summary then printed a heading with nothing under it
# on a machine with three mounts, which reads as "none", on the exact question
# this whole design turns on.
/usr/local/sbin/bb-sandbox list || true

if [ -f /etc/builderbot/node.json ]; then
    cat <<EOF

As a node: the agent is running ($(case "$INIT" in systemd) echo "systemctl status builderbot-agent" ;; openrc) echo "rc-service builderbot-agent status" ;; runit) echo "sv status builderbot-agent" ;; esac)) and the
Nodes page should show this machine live within a minute. It dials out, so
nothing was opened here for it. Jobs run as ${USER_NAME}.

  sudo builderbot-agent status    what this node is, and does the controller answer
EOF
    if [ -n "$SESSION_NAME" ]; then
        cat <<EOF

Sessions run here too, as ${SESSION_NAME}: the agent keeps a ttyd up on this
machine's LAN address (port 7681, read-only twin on 7682, and on 7683 a
container's shell as the docker account) running bb-tty from the bb the
controller ships, so a Claude session on a project bound to this
node lives on this machine, in its synced copy of the project at
/workspace, which the agent makes and keeps in step with the controller's.
It needs the account signed in to Claude once, from a shell here:

  su - ${SESSION_NAME}              then: claude login

bb itself is not on this account's PATH: it is the controller's, fetched
into the toolchain store by the agent (<store>/<scope>/.bb/current/scripts/bb)
and put on PATH for ${USER_NAME} and ${SESSION_NAME} by
/etc/profile.d/builderbot-session.sh. A shell as either account has it;
this one does not, and needs none.
EOF
    fi
fi

cat <<EOF

Those paths have to be the ones BuilderBot uses. A compose file resolves a
relative bind against whoever runs the container, so a path that means
something different on each side is an app that comes up with no data.

Two accounts, and the split is deliberate:

  ${USER_NAME}   runs Docker and answers ssh. This is the one jobs run as.
        No sudo, and it cannot run bb-sandbox: reconfiguring this machine
        is not what it is for.
  ${SESSION_NAME:-(none)}  is the one a Claude SESSION works as. In kvm for
        the emulator and in NO docker group: docker is root on a machine
        with a daemon, and this is the account that edits your source.

This script makes no administrator account. Whatever already has root here
(your own account, a cloud image's ubuntu or ec2-user, or root) runs
sudo bb-sandbox menu to change what this machine mounts (or the verbs below).

Worth knowing rather than discovering: ${USER_NAME} is in the docker group, and
that group is root on this machine to anyone who wants it. This VM exists to be
wrecked, so that is the arrangement and not a hole in it. What the split buys
is that the machine's own configuration (the fstab deciding what it mounts,
and read-only) is not one command away from a session that wandered.

  sudo bb-sandbox settings     the path mapping for this machine's row
  sudo bb-sandbox check        is every mount really there
EOF
