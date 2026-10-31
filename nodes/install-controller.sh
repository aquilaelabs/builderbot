#!/usr/bin/env bash
#
# Install BuilderBot's controller on a machine of its own, without the
# container (R90), and make that machine a node of itself.
#
# The container install is the image: compose or the Unraid template, tini
# and the entrypoint. This is the same controller laid out the way the image
# lays it out (/opt/builderbot, from the Dockerfile's own COPY lines), with
# systemd (or OpenRC, or runit) in place of tini and an env file in place of
# compose's; the dashboard, the state, the verbs and the updates are the
# same. It is built on the node provisioner, not beside it: it sources
# provision-linux.sh's core and the same family files (the package manager,
# docker, the init system's services, the pre-flight), so every system
# Enroll node vets is a system a controller installs on, and the node half
# is provision-linux.sh run as it is.
#
# From a checkout or an unpacked release, as root:
#
#   sudo bash nodes/install-controller.sh --check      can this machine take one
#   sudo bash nodes/install-controller.sh --install    the controller, and its own node
#   sudo bash /opt/builderbot/nodes/install-controller.sh --update     the newest release
#   sudo bash /opt/builderbot/nodes/install-controller.sh --remove     take it away
#
# What it lays down, and who owns it:
#
#   /opt/builderbot                  -> /opt/builderbot-releases/VERSION, root's
#   /etc/builderbot-controller/      root:builderbot 0750
#     controller.env                 the settings, root:builderbot 0640
#     secrets/                       *.env and ssh/, root's alone (0700)
#   /var/lib/builderbot-controller/  root:builderbot 0750
#     config/ home/ sdk/             the state, the home, the toolchain store: the account's, 0700
#   /srv/builderbot/projects         the projects (--workspace), the account's
#   builderbot-controller            the service: scripts/host-boot.sh, as root, which
#                                    drops to the account for good
#   /usr/local/bin/bb                bb as the account, for anybody who may sudo
#   /etc/bb-session.wall             what a session on this machine's node never sees
#
# The controller's own node (--no-node leaves it out) is provision-linux.sh
# run with --beside-controller: its job account (bb) and its session
# account (builder) are other accounts, out of the docker group and out of
# everything above, and a session there runs behind the wall
# (docs/decisions.md, "A controller installed bare metal, and its own node").
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TREE="$(cd "$HERE/.." && pwd)"

# Where everything goes. One prefix, empty on a real install, so the unit
# tests lay a release out under a scratch folder and read what landed.
P="${BB_INSTALL_ROOT:-}"
OPT="$P/opt/builderbot"
RELEASES="$P/opt/builderbot-releases"
ETC="$P/etc/builderbot-controller"
ENV_FILE="$ETC/controller.env"
VAR="$P/var/lib/builderbot-controller"
SHIM="$P/usr/local/lib/builderbot-controller/bin"
WALL_FILE="$P/etc/bb-session.wall"
SUDOERS="$P/etc/sudoers.d/builderbot-controller"
BB_BIN="$P/usr/local/bin/bb"
SERVICE=builderbot-controller
REPO=aquilaelabs/builderbot
# How many releases are kept beside the one in use: the one before is what
# an update that does not come up goes back to by itself.
KEEP_RELEASES=3

ACCOUNT=builderbot
WORKSPACE_DIR=/srv/builderbot/projects
PORT=7680
JOBS_USER=bb
SESSION_USER=builder
NODE=1
DOCKER_GROUP=0
ACTION=""
FROM=""
RELEASE=""
ASSUME_YES=""
PURGE=0
DEV=0

say()  { printf '\n== %s\n' "$*"; }
warn() { printf '\n!! %s\n' "$*" >&2; }
die()  { printf '\n!! %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
usage: sudo bash install-controller.sh ACTION [options]

Install BuilderBot's controller on this machine, without the container, and
make the machine a node of itself. With no arguments this prints the help and
changes nothing.

Actions:
  --check        the pre-flight alone: this machine's family, its tools, its
                 init, its python, the ports; changes nothing. Exit 0 when
                 it can take a controller, 1 when not.
  --install      the controller, from the tree this script is in: the
                 packages (config/controller-packages.tsv), the account, the
                 release under /opt/builderbot, the env file, the service,
                 and then this machine as a node of itself. Safe to run
                 again: what is there is kept, an env file you edited above all.
  --update       the newest release (or --release TAG, or --from DIR, a
                 checkout or an unpacked release), put in place the way an
                 image update is: checked against the state first, so a
                 release that would refuse it changes nothing, then switched
                 to and started; the one before is kept, and a new
                 release that does not answer goes back to it by itself,
                 the state copy it took first put back. There is no going
                 back by hand: a release moves forward only.
  --remove       stop the controller and take its release, service, bb and
                 wall away, and this machine's node with them. The state,
                 the env file, the secrets, the account and the projects
                 stay; --purge takes all but the projects too. Says what
                 will go and asks; --yes does not ask.
  --stage        inside the appliance image's root as it is built
                 (image/mkosi.postinst): what --install does up to the
                 service, which is enabled and not started; the packages are
                 the image's. The node half waits for the first boot.
  --firstboot    the first boot of an appliance disk, from its unit: the
                 controller is up by its own service, the wall goes up, and
                 this machine enrolls as its node, once.

Options:
  --workspace PATH   the projects folder (default /srv/builderbot/projects);
                     never /workspace, which is this machine's node's synced copy
  --port N           the dashboard's port (default 7680)
  --account NAME     the account the controller runs as (default builderbot);
                     a name already taken, and not by this installer, is refused
  --docker           the account in the docker group, so containers can run on
                     this machine's daemon from the controller, as a container
                     install with the socket mounted does; docker is root here
  --no-node          the controller alone, without this machine as a node
  --jobs-user NAME   the node's job account (bb), as provision-linux.sh's --user
  --session-user NAME  the node's session account (builder)
  --dev              go ahead on a family the provisioner has not run for real
  --release TAG      with --update: that release (v0.7.0)
  --from DIR         with --update: that tree
  --yes              with --remove: do not ask
  --purge            with --remove: the state, env file, secrets and account too
EOF
}

# ---- the provisioner's core -------------------------------------------------
# The family (pkg_refresh, pkg, pkg_names, docker_install), the init
# (svc_install, svc_enable, svc_stop, svc_restart, svc_active), the
# pre-flight and in_container, from the provisioner beside this script.
# Read, not run: nothing of it asks for options or installs anything.
load_core() {
    local prov="$HERE/provision-linux.sh"
    [ -r "$prov" ] || die "provision-linux.sh is not beside this script ($HERE): run it from a checkout or a release"
    BB_PROVISION_LIB=1
    # shellcheck source=nodes/provision-linux.sh
    . "$prov"
    unset BB_PROVISION_LIB
}

# ---- what this tree is ------------------------------------------------------
# tree_stamp TREE: "VERSION REV" the way CI stamps an image: a tag's own
# version, else VERSION-dev.N+SHORT from the checkout, else VERSION alone
# with the commit a release archive names in its header, else unstamped.
tree_stamp() {
    local t="$1" target ordinal short tag rev=""
    target="$(head -1 "$t/VERSION" 2>/dev/null | tr -d '[:space:]')"
    if [ -d "$t/.git" ] || [ -f "$t/.git" ]; then
        ordinal="$(git -C "$t" rev-list --count HEAD 2>/dev/null || echo 0)"
        short="$(git -C "$t" rev-parse --short=7 HEAD 2>/dev/null || true)"
        rev="$(git -C "$t" rev-parse HEAD 2>/dev/null || true)"
        if tag="$(git -C "$t" describe --tags --exact-match HEAD 2>/dev/null)"; then
            printf '%s %s' "${tag#v}" "${rev:-unstamped}"
        else
            printf '%s %s' "${target:-0.0.0}-dev.${ordinal}+${short}" "${rev:-unstamped}"
        fi
        return 0
    fi
    [ -r "$t/.release-rev" ] && rev="$(tr -d '[:space:]' < "$t/.release-rev")"
    printf '%s %s' "${target:-unstamped}" "${rev:-unstamped}"
}

# dockerfile_arg NAME [TREE]: an ARG's default in the tree's Dockerfile, the
# one place the image's pins are kept (noVNC and its checksum).
dockerfile_arg() {
    sed -n "s/^ARG $1=//p" "${2:-$TREE}/Dockerfile" | head -1
}

# ---- the release, laid out as the image lays it out -------------------------
# copy_as_copy TREE SRC DEST: one Dockerfile COPY line, done here: a folder
# (SRC/) is its contents into DEST/, a glob each file into DEST/, a file to
# DEST (or into it, when DEST ends in /).
copy_as_copy() {
    local t="$1" src="$2" dest="$3" f
    case "$src" in
        */)
            install -d -m 0755 "$dest"
            cp -a "$t/$src." "$dest/" ;;
        *'*'*)
            install -d -m 0755 "$dest"
            for f in "$t"/$src; do
                [ -e "$f" ] && cp -a "$f" "$dest/"
            done ;;
        *)
            case "$dest" in
                */) install -d -m 0755 "$dest"; cp -a "$t/$src" "$dest" ;;
                *)  install -d -m 0755 "$(dirname "$dest")"; cp -a "$t/$src" "$dest" ;;
            esac ;;
    esac
}

# lay_out TREE DIR VERSION REV: the release in DIR, from TREE, by the
# Dockerfile's COPY lines (every one that lands under /opt/builderbot), so
# what the image carries and what is laid out here cannot drift; then what
# the image's RUN lines add there (noVNC, the scripts made executable) and
# the stamp the image carries in its ENV (build.env).
lay_out() {
    local t="$1" dir="$2" ver="$3" rev="$4" src dest n=0 nv sha
    rm -rf "$dir.partial"
    install -d -m 0755 "$dir.partial"
    while read -r src dest; do
        case "$dest" in /opt/builderbot/*|/opt/builderbot) ;; *) continue ;; esac
        copy_as_copy "$t" "$src" "$dir.partial${dest#/opt/builderbot}"
        n=$((n + 1))
    done < <(sed -n 's/^COPY \([^ ]*\) \([^ ]*\)$/\1 \2/p' "$t/Dockerfile")
    [ "$n" -gt 5 ] || die "the Dockerfile in $t names nothing to lay out ($n COPY lines)"
    # ...and what a machine of its own needs that the image does not: the
    # installer itself (for --update and --remove from here), its
    # env file's template and the Dockerfile's pins.
    install -m 0755 "$t/nodes/install-controller.sh" "$dir.partial/nodes/install-controller.sh"
    install -m 0644 "$t/config/controller.env" "$dir.partial/config/controller.env"
    install -m 0644 "$t/Dockerfile" "$dir.partial/Dockerfile"
    chmod -R a+rX "$dir.partial"
    chmod -R +x "$dir.partial/scripts"
    # noVNC: a VM's screen in the dock (R99), the image's pinned release,
    # checked by the image's digest.
    if [ "${NO_FETCH:-0}" != 1 ]; then
        nv="$(dockerfile_arg NOVNC_VERSION "$t")"; sha="$(dockerfile_arg NOVNC_SHA256 "$t")"
        if [ -n "$nv" ] && curl -fsSL -o "$dir.partial/novnc.tar.gz" \
                "https://github.com/novnc/noVNC/archive/refs/tags/v${nv}.tar.gz" \
           && echo "${sha}  $dir.partial/novnc.tar.gz" | sha256sum -c - >/dev/null 2>&1; then
            install -d -m 0755 "$dir.partial/novnc"
            tar xzf "$dir.partial/novnc.tar.gz" -C "$dir.partial/novnc" --strip-components=1 \
                "noVNC-${nv}/core" "noVNC-${nv}/vendor" "noVNC-${nv}/vnc_lite.html" "noVNC-${nv}/LICENSE.txt"
        else
            warn "noVNC ${nv:-?} did not download or did not match its checksum: a VM's screen will not draw until an update brings it"
        fi
        rm -f "$dir.partial/novnc.tar.gz"
    fi
    {
        printf '# Written by install-controller.sh: which build this release is, as the image says it in its ENV.\n'
        printf 'BB_VERSION=%s\nBB_IMAGE_REV=%s\nBB_IMAGE_BUILT=%s\n' "$ver" "$rev" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf 'NODE_PATH=%s\n' "$( (npm root -g 2>/dev/null) || echo /usr/lib/node_modules)"
    } > "$dir.partial/build.env"
    chown -R 0:0 "$dir.partial" 2>/dev/null || true
    rm -rf "$dir"
    mv "$dir.partial" "$dir"
}

# release_name VERSION: the folder a release is laid out in.
release_name() { printf '%s' "$1" | tr -c 'A-Za-z0-9._+-' '_'; }

# flip DIR: /opt/builderbot is DIR from now, in one rename; the release it
# was is remembered as the one before.
flip() {
    local dir="$1" was=""
    [ -L "$OPT" ] && was="$(readlink "$OPT")"
    [ -e "$OPT" ] && [ ! -L "$OPT" ] && die "$OPT is there and is not this installer's: take it away first"
    ln -sfn "$dir" "$OPT.new"
    mv -T "$OPT.new" "$OPT"
    if [ -n "$was" ] && [ "$was" != "$dir" ]; then
        ln -sfn "$was" "$RELEASES/.previous"
    fi
}

# prune: the newest releases kept, the one in use and the one before always.
prune() {
    local cur prev d n=0
    cur="$(readlink "$OPT" 2>/dev/null || true)"
    prev="$(readlink "$RELEASES/.previous" 2>/dev/null || true)"
    while read -r d; do
        [ -n "$d" ] || continue
        n=$((n + 1))
        [ "$d" = "$cur" ] || [ "$d" = "$prev" ] || [ "$n" -le "$KEEP_RELEASES" ] || rm -rf "$d"
    done < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d ! -name '*.partial' -printf '%T@ %p\n' 2>/dev/null \
             | sort -rn | cut -d' ' -f2-)
}

# ---- the packages -------------------------------------------------------------
# entry_install ENTRY: one cell's entry, "a|b" being the first that installs.
entry_install() {
    local alt
    for alt in ${1//|/ }; do
        pkg "$alt" >/dev/null 2>&1 && return 0
    done
    return 1
}

# packages: the list's rows for this family. Core and host rows must
# install, or nothing more happens; tools and vendor rows install where they
# can, and what did not is said once. Docker's rows are the node half's:
# provision-linux.sh brings the daemon and its CLI (docker_install).
packages() {
    local e missing=() soft=() reader="$TREE/scripts/lib/controller-packages.sh"
    say "packages: ${FAMILY_NAME:-$FAMILY}"
    pkg_refresh
    # A RHEL rebuild's tools are EPEL's (ripgrep, fzf, ShellCheck, gh).
    declare -F epel_here >/dev/null && epel_here
    while read -r e; do
        [ -n "$e" ] || continue
        entry_install "$e" || missing+=("$e")
    done < <(bash "$reader" "$FAMILY" core host)
    [ "${#missing[@]}" -eq 0 ] || die "these did not install, and the controller does not run without them: ${missing[*]}"
    while read -r e; do
        [ -n "$e" ] || continue
        case "$e" in @*) continue ;; esac
        entry_install "$e" || soft+=("$e")
    done < <(bash "$reader" "$FAMILY" tools vendor)
    [ "${#soft[@]}" -eq 0 ] || warn "not installed, which a shell on the controller will miss and the controller will not: ${soft[*]}"
    # The image's own touches: fd under its short name, git-lfs's hooks.
    if command -v fdfind >/dev/null 2>&1 && ! command -v fd >/dev/null 2>&1; then
        ln -sf "$(command -v fdfind)" /usr/local/bin/fd
    fi
    command -v git-lfs >/dev/null 2>&1 && git lfs install --system >/dev/null 2>&1 || true
}

# pick_python: the python the controller reads (3.12 or newer, what the
# image ships and ruff holds it to). Where the machine's python3 is older
# and a newer one is installed beside it (a RHEL 9 rebuild's python3.12), a
# python3 in the controller's own PATH folder points at that one.
PY_MIN=12
py_minor() { "$1" -c 'import sys; print(sys.version_info[1] if sys.version_info[0] == 3 else 0)' 2>/dev/null || echo 0; }
find_python() {
    local c
    for c in python3 python3.14 python3.13 python3.12; do
        command -v "$c" >/dev/null 2>&1 || continue
        if [ "$(py_minor "$c")" -ge "$PY_MIN" ]; then command -v "$c"; return 0; fi
    done
    return 1
}
pick_python() {
    local best
    best="$(find_python)" || return 1
    install -d -m 0755 "$SHIM"
    if [ "$(command -v python3 2>/dev/null)" = "$best" ]; then
        rm -f "$SHIM/python3"
    else
        ln -sfn "$best" "$SHIM/python3"
    fi
    printf '%s' "$best"
}

# extras: what the image fetches from each vendor beside the packages, the
# same way and as best it can: the linters `bb lint` runs, uv and mise,
# Playwright and web-ext through npm, the home tunnel's cloudflared. Each
# one that does not land is said, and nothing waits on it. The terminals
# need none of them: each is a pty of the dashboard's own.
extras() {
    local arch miss=() bin
    arch="$(uname -m)"
    say "the image's other tools"
    # Each from its vendor's GitHub release, held to the digest GitHub
    # states for it (gh-fetch, B335), never taken on trust.
    local ghf="$TREE/scripts/lib/gh-fetch" t
    t="$(mktemp -d)"
    if [ "$arch" = x86_64 ]; then
        bash "$ghf" hadolint/hadolint latest 'hadolint-linux-x86_64' /usr/local/bin/hadolint >/dev/null \
            && chmod +x /usr/local/bin/hadolint || miss+=(hadolint)
        bash "$ghf" mikefarah/yq latest 'yq_linux_amd64' /usr/local/bin/yq >/dev/null \
            && chmod +x /usr/local/bin/yq || miss+=(yq)
        { bash "$ghf" rhysd/actionlint latest 'actionlint_*_linux_amd64.tar.gz' "$t/actionlint.tar.gz" >/dev/null \
            && tar -xzf "$t/actionlint.tar.gz" -C /usr/local/bin actionlint; } || miss+=(actionlint)
    else
        miss+=(hadolint yq actionlint)
    fi
    if command -v pipx >/dev/null 2>&1; then
        PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install ruff >/dev/null 2>&1 \
            || command -v ruff >/dev/null 2>&1 || miss+=(ruff)
    else
        miss+=(ruff)
    fi
    local uvarch misearch
    uvarch="$([ "$arch" = x86_64 ] && echo x86_64 || echo aarch64)"; misearch="$([ "$arch" = x86_64 ] && echo x64 || echo arm64)"
    command -v uv >/dev/null 2>&1 || { bash "$ghf" astral-sh/uv latest "uv-${uvarch}-unknown-linux-gnu.tar.gz" "$t/uv.tar.gz" >/dev/null \
        && tar -xzf "$t/uv.tar.gz" -C /usr/local/bin --strip-components=1 "uv-${uvarch}-unknown-linux-gnu/uv" "uv-${uvarch}-unknown-linux-gnu/uvx"; } || true
    command -v uv >/dev/null 2>&1 || miss+=(uv)
    command -v mise >/dev/null 2>&1 || { bash "$ghf" jdx/mise latest "mise-v*-linux-${misearch}" /usr/local/bin/mise >/dev/null \
        && chmod +x /usr/local/bin/mise; } || true
    command -v mise >/dev/null 2>&1 || miss+=(mise)
    if command -v npm >/dev/null 2>&1; then
        for bin in playwright web-ext; do
            command -v "$bin" >/dev/null 2>&1 || npm install -g --foreground-scripts "$bin" >/dev/null 2>&1 || miss+=("$bin")
        done
        command -v corepack >/dev/null 2>&1 && corepack enable >/dev/null 2>&1 || true
        # Playwright's system libraries are an apt list of its own; the
        # browsers themselves go on the toolchain store at the first start
        # (46-playwright.root.sh), as in the image.
        if command -v playwright >/dev/null 2>&1 && [ "$FAMILY" = deb ]; then
            playwright install-deps chromium firefox webkit >/dev/null 2>&1 || miss+=("playwright's libraries")
        fi
    else
        miss+=(playwright web-ext)
    fi
    case "$arch" in
        x86_64|aarch64)
            command -v cloudflared >/dev/null 2>&1 || {
                bash "$ghf" cloudflare/cloudflared latest "cloudflared-linux-$( [ "$arch" = x86_64 ] && echo amd64 || echo arm64)" \
                    /usr/local/bin/cloudflared >/dev/null && chmod +x /usr/local/bin/cloudflared; } || miss+=(cloudflared) ;;
        *) miss+=(cloudflared) ;;
    esac
    rm -rf "$t"
    [ "${#miss[@]}" -eq 0 ] || warn "not here, which the image carries: ${miss[*]} (the dashboard runs without them; bb lint says [skip] for a missing linter)"
}

# ---- the account and its folders ---------------------------------------------
# ours: the accounts this installer made, so --remove takes those and never
# one that was here before.
MADE="$ETC/made-accounts"
make_account() {
    say "account ${ACCOUNT}"
    if id -u "$ACCOUNT" >/dev/null 2>&1; then
        grep -qx "$ACCOUNT" "$MADE" 2>/dev/null \
            || die "${ACCOUNT} is already an account on this machine, and not one this installer made: run again with --account NAME, a name that is not taken"
        printf '   there already, made by an earlier run\n'
    else
        useradd --system --user-group --home-dir "$VAR/home" --no-create-home --shell /bin/bash "$ACCOUNT"
        install -d -m 0750 -o root -g "$ACCOUNT" "$ETC"
        grep -qx "$ACCOUNT" "$MADE" 2>/dev/null || echo "$ACCOUNT" >> "$MADE"
    fi
    passwd -l "$ACCOUNT" >/dev/null 2>&1 || true
    # The image's kvm dance, for the emulator a controller never runs now
    # but a shell on it may still ask for.
    getent group kvm >/dev/null 2>&1 && usermod -aG kvm "$ACCOUNT"
    if [ "$DOCKER_GROUP" = 1 ]; then
        getent group docker >/dev/null 2>&1 || groupadd docker
        usermod -aG docker "$ACCOUNT"
        printf '   in the docker group (--docker): containers can run on this machine'"'"'s daemon\n'
    elif id -nG "$ACCOUNT" | tr ' ' '\n' | grep -qx docker; then
        gpasswd -d "$ACCOUNT" docker >/dev/null 2>&1 || true
        printf '   taken out of the docker group (no --docker this run)\n'
    fi
}

# folders: each with its owner and mode; a workspace that is already there
# (a share) is left as it is and only checked.
folders() {
    local g
    g="$(id -gn "$ACCOUNT")"
    install -d -m 0750 -o root -g "$g" "$ETC" "$VAR"
    install -d -m 0700 -o root -g root "$ETC/secrets"
    install -d -m 0700 -o "$ACCOUNT" -g "$g" "$VAR/config" "$VAR/home" "$VAR/sdk"
    if [ -d "$P$WORKSPACE_DIR" ]; then
        setpriv --reuid="$ACCOUNT" --regid="$g" --init-groups test -w "$P$WORKSPACE_DIR" 2>/dev/null \
            || warn "$WORKSPACE_DIR is not writable by ${ACCOUNT}: new projects cannot be made there until it is"
    else
        # The parent made if missing and never changed if it is there: install
        # -d sets a folder's mode and owner even when it exists, and the
        # parent of --workspace /projects is / (B498).
        mkdir -p "$(dirname "$P$WORKSPACE_DIR")"
        install -d -m 0750 -o "$ACCOUNT" -g "$g" "$P$WORKSPACE_DIR"
    fi
}

# env_file: written once, from the release's template with this run's
# answers; an existing one is the operator's and is left as it is, but for
# a setting a newer template has that it lacks, which is added (commented
# out at its default) so it is there to find.
env_file() {
    local tmpl="$TREE/config/controller.env" k line
    if [ ! -f "$ENV_FILE" ]; then
        sed -e "s|^WORKSPACE=.*|WORKSPACE=${WORKSPACE_DIR}|" \
            -e "s|^DASHBOARD_PORT=.*|DASHBOARD_PORT=${PORT}|" \
            -e "s|^BB_ACCOUNT=.*|BB_ACCOUNT=${ACCOUNT}|" \
            -e "s|^TZ=.*|TZ=$(host_tz)|" "$tmpl" > "$ENV_FILE.new"
        mv -f "$ENV_FILE.new" "$ENV_FILE"
        printf '   %s written; it is yours to edit\n' "$ENV_FILE"
    else
        while IFS= read -r line; do
            k="${line%%=*}"
            case "$line" in [A-Z]*=*) ;; *) continue ;; esac
            grep -Eq "^#?[[:space:]]*${k}=" "$ENV_FILE" || printf '# Added by an update, at its default:\n# %s\n' "$line" >> "$ENV_FILE"
        done < "$tmpl"
    fi
    chown "root:$(id -gn "$ACCOUNT")" "$ENV_FILE"
    chmod 0640 "$ENV_FILE"
}

# host_tz: the machine's own timezone, for the env file's TZ.
host_tz() {
    local z=""
    z="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
    [ -n "$z" ] || z="$(cat /etc/timezone 2>/dev/null || true)"
    [ -n "$z" ] || z="$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||')"
    printf '%s' "${z:-Etc/UTC}"
}

# env_get KEY: a value from the env file, as the controller will read it.
env_get() {
    # shellcheck disable=SC1090  # the operator's file, read as the service reads it
    (set -a; . "$ENV_FILE" >/dev/null 2>&1; set +a; printf '%s' "${!1:-}")
}

# state_dir: the controller's state as the service finds it, with the same
# default host-env.sh gives when the env file names none; an empty answer
# had the update's gate and the rollback read the current directory (B499).
state_dir() {
    local v; v="$(env_get DASHBOARD_STATE)"
    v="${v:-$VAR/config}"
    case "$v" in /?*) printf '%s' "$v" ;; *) die "DASHBOARD_STATE in ${ENV_FILE} is not a path from /: ${v}" ;; esac
}

# bb_wrapper: bb on the machine's PATH, as the controller's account, with
# the environment the service has (scripts/lib/host-env.sh). What `docker
# exec -it BuilderBot bb` is on a container install.
bb_wrapper() {
    install -d -m 0755 "$(dirname "$BB_BIN")"
    cat > "$BB_BIN" <<EOF
#!/usr/bin/env bash
# Written by BuilderBot's install-controller.sh: bb as the controller's
# account (${ACCOUNT}), with the controller's environment. Anybody who may
# sudo may run it; root runs it as the account.
set -euo pipefail
if [ "\$(id -un)" != "${ACCOUNT}" ]; then
    exec sudo -u "${ACCOUNT}" -- "\$0" "\$@"
fi
. /opt/builderbot/scripts/lib/host-env.sh
export HOME="\$BUILDER_HOME" USER="${ACCOUNT}"
exec /opt/builderbot/scripts/bb "\$@"
EOF
    chmod 0755 "$BB_BIN"
}

# sudoers: the two root helpers the account may run, the image's rule.
sudoers() {
    install -d -m 0750 "$(dirname "$SUDOERS")"
    printf '%s\n' "# Written by BuilderBot's install-controller.sh: the two root helpers, as in the image." \
        "${ACCOUNT} ALL=(root) NOPASSWD: /opt/builderbot/scripts/mint-runner-token" \
        "${ACCOUNT} ALL=(root) NOPASSWD: /opt/builderbot/scripts/deploy-key" > "$SUDOERS.new"
    chmod 0440 "$SUDOERS.new"
    if command -v visudo >/dev/null 2>&1 && ! visudo -cf "$SUDOERS.new" >/dev/null 2>&1; then
        rm -f "$SUDOERS.new"; die "the sudo rule did not check out (visudo -c), so it was not put in place"
    fi
    mv -f "$SUDOERS.new" "$SUDOERS"
}

# service: the controller under this machine's init, by the provisioner's
# own service writer. systemd's stop reaches the supervisor first and the
# rest after it is done (KillMode=mixed), which is the order `docker stop`
# gives the container: the terminals are saved before tmux goes.
service() {
    # On BuilderBot OS the boot's own settings (builderbot-os-env.service)
    # are read beside the env file; elsewhere the file is simply not there.
    svc_install "$SERVICE" "BuilderBot controller" "/opt/builderbot/scripts/host-boot.sh supervise" \
        "KillMode=mixed
TimeoutStopSec=30
EnvironmentFile=-/run/builderbot-os/env"
}

# wait_up: the dashboard answering on its port, or why not.
wait_up() {
    local i code
    for i in $(seq 1 60); do
        code="$(curl -s -o /dev/null -m 3 -w '%{http_code}' "http://127.0.0.1:${PORT}/" 2>/dev/null || true)"
        case "$code" in 000|"") sleep 2 ;; *) return 0 ;; esac
        [ "$i" -lt 60 ] || break
    done
    return 1
}

# lan_ip: this machine's address on its network, the one a remote node
# would reach the controller at.
lan_ip() {
    ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit }}'
}

# ---- the actions ------------------------------------------------------------
checks() {
    load_core
    if in_container; then
        die "this is a container, and install-controller.sh installs a controller on a machine of its own: the container install is the image (docs/install.md)"
    fi
    [ "${BB_INSTALL_ROOT:-}" = "" ] || die "BB_INSTALL_ROOT is for the unit tests"
    [ "$(id -u)" -eq 0 ] || die "run this as root: sudo bash $0 $ACTION"
    preflight
    say "checking this machine as a controller"
    local py fail=0
    case "$INIT" in systemd|openrc|runit) chk ok "a service manager the controller runs under: ${INIT}" ;; esac
    if py="$(find_python)"; then chk ok "python: $py (3.$(py_minor "$py"))"
    elif command -v python3 >/dev/null 2>&1; then
        chk warn "python3 here is 3.$(py_minor python3) and the controller reads 3.${PY_MIN} or newer: the packages step installs one where the family has it, and stops when it does not"
    else chk warn "no python3 yet: the packages step installs it"; fi
    case "$WORKSPACE_DIR" in
        /workspace|/workspace/*) chk fail "--workspace ${WORKSPACE_DIR}: /workspace is this machine's node's synced copy of the projects"; fail=1 ;;
        /*) chk ok "projects: ${WORKSPACE_DIR}" ;;
        *) chk fail "--workspace ${WORKSPACE_DIR} is not a path from /"; fail=1 ;;
    esac
    local who
    who="$(ss -ltnpH "sport = :$PORT" 2>/dev/null | head -1)"
    if [ -z "$who" ] || printf '%s' "$who" | grep -q python3; then chk ok "port $PORT is free, or the controller's own"
    else chk fail "port $PORT is taken: ${who}"; fail=1; fi
    if id -u "$ACCOUNT" >/dev/null 2>&1 && ! grep -qx "$ACCOUNT" "$MADE" 2>/dev/null; then
        chk fail "${ACCOUNT} is an account here already, and not one this installer made: --account NAME"; fail=1
    fi
    [ "$fail" = 0 ] || { warn "this machine cannot take a controller as asked; nothing was changed"; exit 1; }
}

cmd_check() {
    checks
    printf '\n   %s can take a BuilderBot controller.\n' "${PRETTY_NAME:-$ID}"
}

cmd_install() {
    local stamp ver rev dir py
    checks
    packages
    py="$(pick_python)" || die "no python 3.${PY_MIN} or newer installed here, and the controller reads nothing older: install one (python3.${PY_MIN}) and run this again"
    printf '   python: %s\n' "$py"
    extras
    make_account
    folders
    read -r ver rev <<<"$(tree_stamp "$TREE")"
    dir="$RELEASES/$(release_name "$ver")"
    say "release ${ver}"
    install -d -m 0755 "$RELEASES"
    lay_out "$TREE" "$dir" "$ver" "$rev"
    flip "$dir"
    prune
    env_file
    bb_wrapper
    sudoers
    say "service: ${SERVICE}"
    service
    wait_up || die "the controller did not answer on port ${PORT}: journalctl -u ${SERVICE} (or $(state_dir)/logs/builderbot.log) says why"
    printf '   up: http://%s:%s\n' "$(lan_ip || echo localhost)" "$PORT"
    if [ "$NODE" = 1 ]; then
        # The wall before the node: its first hello asks bb-session whether
        # a session may start, and the answer has to be this one.
        wall_write
        own_node
    fi
    stamp="$(lan_ip || echo localhost)"
    cat <<EOF

== done

The controller is at http://${stamp}:${PORT}. Open it and make the owner
account: until somebody does, it serves that page and nothing else.

  sudo bb status                  what it is running, as the container's bb says it
  sudo systemctl status ${SERVICE}
  ${ENV_FILE}   its settings

Its state is $(state_dir), its projects $(env_get WORKSPACE).
EOF
}

# ---- the appliance image (R160 step 1) ----------------------------------------
# cmd_stage: inside the image's root while mkosi builds it: root, the
# packages in, no service manager running, the checkout at $TREE. What
# --install does up to the service, enabled for the first boot and not
# started; the version is the build's (BB_STAGE_VERSION and BB_STAGE_REV from
# image/build.sh), since the checkout's git is another user's in the chroot.
cmd_stage() {
    local ver rev dir py
    load_core
    [ "$(id -u)" -eq 0 ] || die "--stage runs as root inside the image's root"
    [ -d /usr/lib/builderbot-os ] || die "--stage is for the appliance image's tree (image/), which carries /usr/lib/builderbot-os"
    INIT=systemd
    py="$(pick_python)" || die "the image has no python 3.${PY_MIN} or newer: image/mkosi.conf"
    printf '   python: %s\n' "$py"
    extras
    make_account
    folders
    if [ -n "${BB_STAGE_VERSION:-}" ]; then ver="$BB_STAGE_VERSION"; rev="${BB_STAGE_REV:-unstamped}"
    else read -r ver rev <<<"$(tree_stamp "$TREE")"; fi
    dir="$RELEASES/$(release_name "$ver")"
    say "release ${ver}, staged"
    install -d -m 0755 "$RELEASES"
    lay_out "$TREE" "$dir" "$ver" "$rev"
    flip "$dir"
    env_file
    bb_wrapper
    sudoers
    say "service: ${SERVICE}, enabled for the first boot"
    BB_SVC_NO_START=1 service
}

# cmd_firstboot: the first boot of an appliance disk
# (builderbot-os-firstboot.service): the controller is up by its own
# service, so this is --install's last step, the wall and this machine as
# the controller's node. own_node writes the marker the unit's condition
# reads, so it runs once; a boot that fails it (no network yet) runs it
# again at the next.
cmd_firstboot() {
    load_core
    [ "$(id -u)" -eq 0 ] || die "--firstboot runs as root, from its unit"
    [ -f "$ENV_FILE" ] || die "no staged controller here ($ENV_FILE): --firstboot is the appliance image's"
    INIT=systemd
    say "first boot: waiting for the controller on port ${PORT}"
    wait_up || die "the controller did not answer on port ${PORT}: journalctl -u ${SERVICE} says why"
    wall_write
    local f
    if [ -r "$OS_FEATURES_FILE" ]; then
        while read -r f; do
            case "$f" in vmhost|firewall|iommu) OS_FEATURES+=(--feature "$f") ;; "") ;; *) warn "not a feature the installer offers: $f (left out)" ;; esac
        done < "$OS_FEATURES_FILE"
        [ "${#OS_FEATURES[@]}" -eq 0 ] || printf '   features asked for at install: %s\n' "$(tr '\n' ' ' < "$OS_FEATURES_FILE")"
    fi
    own_node || die "this machine did not become its controller's node (above): the unit runs again at the next boot"
}

# ---- updates: the release fetched and put in place as an image pull is -----
# fetch_tree [TAG]: the release's tree, unpacked in a folder of its own,
# printed. The newest release when no tag is named, read from the releases
# page's redirect the way the Dockerfile reads its tools' (no API budget).
# fetch_tree [TAG]: the release's controller bundle (R90 step 5), which the
# release workflow publishes as builderbot-controller-X.Y.Z.tar.gz with its
# sha256 beside it and a build attestation from GitHub: the archive checked
# against the sha256, and against the attestation where gh is here to ask;
# a release from before the bundle falls back to the tag's source archive,
# said as such. The tree's directory is printed.
fetch_tree() {
    local tag="${1:-}" d url base ver sum
    if [ -z "$tag" ]; then
        tag="$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/${REPO}/releases/latest" 2>/dev/null || true)"
        tag="${tag##*/}"
        case "$tag" in v[0-9]*) ;; *) die "could not tell which release is the newest (https://github.com/${REPO}/releases/latest)" ;; esac
    fi
    d="$(mktemp -d /tmp/builderbot-release.XXXXXX)"
    ver="${tag#v}"
    base="https://github.com/${REPO}/releases/download/${tag}/builderbot-controller-${ver}.tar.gz"
    if curl -fsSL -o "$d/release.tar.gz" "$base" 2>/dev/null; then
        curl -fsSL -o "$d/release.tar.gz.sha256" "${base}.sha256" || die "the bundle has no sha256 beside it at ${base}.sha256, so it is not taken"
        sum="$(awk '{print $1}' "$d/release.tar.gz.sha256")"
        echo "${sum}  $d/release.tar.gz" | sha256sum -c - >/dev/null 2>&1 \
            || die "the bundle does not match its sha256 (${base}): not taken"
        printf '   bundle %s, sha256 %s\n' "$(basename "$base")" "${sum:0:12}" >&2
        if command -v gh >/dev/null 2>&1; then
            if gh attestation verify "$d/release.tar.gz" --repo "$REPO" >/dev/null 2>&1; then
                printf '   build attestation: verified by gh\n' >&2
            else
                die "gh attestation verify refused the bundle: not taken (a build not made by the release workflow)"
            fi
        else
            printf '   build attestation: gh is not here to check it; the sha256 is what held\n' >&2
        fi
    else
        url="https://github.com/${REPO}/archive/refs/tags/${tag}.tar.gz"
        printf '   %s publishes no controller bundle (a release from before 0.9.0); its source archive is taken instead, unverified\n' "$tag" >&2
        curl -fsSL -o "$d/release.tar.gz" "$url" || die "could not download ${url}"
    fi
    tar -xzf "$d/release.tar.gz" -C "$d"
    local top
    top="$(find "$d" -mindepth 1 -maxdepth 1 -type d | head -1)"
    [ -f "$top/Dockerfile" ] && [ -f "$top/nodes/install-controller.sh" ] || die "${tag}'s archive is not a BuilderBot tree that installs bare metal"
    # The commit, from the header git writes on every archive.
    python3 -c 'import sys, tarfile; print(tarfile.open(sys.argv[1]).pax_headers.get("comment", ""))' \
        "$d/release.tar.gz" > "$top/.release-rev" 2>/dev/null || true
    printf '%s' "$top"
}

# gate TREE VERSION: whether that build would start on this state, asked of
# its own stateversion.py before anything is changed.
gate() {
    local t="$1" ver="$2" state
    state="$(state_dir)"
    [ -n "$state" ] || die "the controller's state folder could not be told: nothing changed"
    BB_VERSION="$ver" PATH="$SHIM:$PATH" python3 "$t/scripts/dashboard/stateversion.py" check "$state"
}

cmd_update() {
    local t ver rev dir cur
    [ -L "$OPT" ] || die "no controller is installed here by this script (no $OPT link): --install first"
    load_core
    [ "$(id -u)" -eq 0 ] || die "run this as root: sudo bash $0 --update"
    if [ -n "$FROM" ]; then
        t="$(cd "$FROM" && pwd)"
    else
        say "fetching ${RELEASE:-the newest release}"
        t="$(fetch_tree "$RELEASE")"
    fi
    # The new release's own installer lays the new release out, the way the
    # new image's own entrypoint is what starts it.
    if [ "${BB_UPDATE_HANDOFF:-}" != 1 ] && [ "$(cd "$t/nodes" && pwd)" != "$HERE" ]; then
        [ -f "$t/nodes/install-controller.sh" ] || die "$t is not a BuilderBot tree that installs bare metal"
        if [ "$DEV" = 1 ]; then
            BB_UPDATE_HANDOFF=1 exec bash "$t/nodes/install-controller.sh" --update --from "$t" --dev
        fi
        BB_UPDATE_HANDOFF=1 exec bash "$t/nodes/install-controller.sh" --update --from "$t"
    fi
    read -r ver rev <<<"$(tree_stamp "$t")"
    cur="$(sed -n 's/^BB_VERSION=//p' "$OPT/build.env" 2>/dev/null || true)"
    say "update: ${cur:-?} to ${ver}"
    if [ "$ver" = "$cur" ] && [ "$(sed -n 's/^BB_IMAGE_REV=//p' "$OPT/build.env")" = "$rev" ]; then
        printf '   already on it\n'; return 0
    fi
    # The state version gate, before anything moves: a release that would
    # refuse this state changes nothing here.
    gate "$t" "$ver" || die "${ver} will not start on this state (above), so nothing was changed"
    packages
    pick_python >/dev/null || die "no python 3.${PY_MIN} or newer here"
    dir="$RELEASES/$(release_name "$ver")"
    lay_out "$t" "$dir" "$ver" "$rev"
    flip "$dir"
    prune
    # The env file keeps its values, and gains what the release's template
    # added; the service is written again, then restarted on the new release.
    TREE="$t" env_file
    bb_wrapper
    # The wall again, for the folders the env file may name now.
    if [ -f "$OWN_MARK" ]; then
        wall_write
    fi
    service
    if wait_up; then
        printf '   %s is up\n' "$ver"
    else
        # Not answering: back by itself (R90 step 5), the state the newer
        # build may have moved on put back from the copy it took, so the
        # machine is never left on a build that does not come up.
        warn "${ver} did not answer on port ${PORT}: journalctl -u ${SERVICE} says why; going back to ${cur:-the one before} now"
        if [ -L "$RELEASES/.previous" ] && back_to_previous; then
            warn "back on ${cur:-the one before}; ${ver} is kept beside it for a look"
        else
            warn "going back did not go through either: journalctl -u ${SERVICE} says why"
        fi
        exit 1
    fi
}

# back_to_previous: the release before, put back by an update whose new
# release did not answer (R90 step 5). Boot safety, not a downgrade: it is
# never a verb of its own (the operator, 28 Oct: no roll back).
back_to_previous() {
    local prev newver oldver state
    [ -L "$RELEASES/.previous" ] || die "there is no release before this one to go back to"
    prev="$(readlink "$RELEASES/.previous")"
    [ -d "$prev" ] || die "the release before ($prev) is gone"
    newver="$(sed -n 's/^BB_VERSION=//p' "$OPT/build.env" 2>/dev/null || true)"
    oldver="$(sed -n 's/^BB_VERSION=//p' "$prev/build.env" 2>/dev/null || true)"
    state="$(state_dir)"
    [ -n "$state" ] || die "the controller's state folder could not be told: nothing changed"
    say "back: ${newver:-?} to ${oldver:-?}"
    svc_stop "$SERVICE"
    # The newer build may have moved the state on, which the older one
    # refuses; then the copy the newer one took before it migrated is put
    # back, and what the state held is kept beside it.
    # The restore is the newer release's own (an older one may predate it).
    if ! gate "$prev" "$oldver" 2>/dev/null; then
        PATH="$SHIM:$PATH" python3 "$OPT/scripts/dashboard/stateversion.py" restore "$state" "$newver" \
            || { svc_restart "$SERVICE" || true; die "the state could not be put back to what ${oldver} reads, so ${newver} is started again"; }
        chown -R "$ACCOUNT:$(id -gn "$ACCOUNT")" "$state" 2>/dev/null || true
    fi
    flip "$prev"
    service
    wait_up || die "${oldver} did not answer on port ${PORT}: journalctl -u ${SERVICE} says why"
    printf '   %s is up again\n' "$oldver"
}

cmd_remove() {
    local what
    load_core
    [ "$(id -u)" -eq 0 ] || die "run this as root: sudo bash $0 --remove"
    what="the ${SERVICE} service, ${OPT} and ${RELEASES}, ${BB_BIN}, the sudo rule and the wall"
    [ -f /etc/builderbot/node.json ] && [ -f "$ETC/own-node" ] && what="${what}, and this machine's node (provision-linux.sh --remove)"
    if [ "$PURGE" = 1 ]; then
        what="${what}; and with --purge: $(state_dir), ${VAR}, ${ETC} and the account ${ACCOUNT}. The projects in $(env_get WORKSPACE 2>/dev/null || echo "$WORKSPACE_DIR") stay"
    fi
    printf 'This takes away: %s.\n' "$what"
    if [ -z "$ASSUME_YES" ]; then
        read -r -p "Go ahead? [y/N] " ans
        case "$ans" in y|Y|yes) ;; *) echo "nothing was changed"; exit 0 ;; esac
    fi
    if [ -f /etc/builderbot/node.json ] && [ -f "$ETC/own-node" ]; then
        say "this machine's node"
        bash "$OPT/nodes/provision-linux.sh" --remove --yes || warn "the node's own uninstall did not finish: sudo bb-sandbox uninstall"
    fi
    say "the controller"
    svc_stop "$SERVICE"
    case "$INIT" in
        systemd) systemctl disable "$SERVICE" >/dev/null 2>&1 || true
                 rm -f "/etc/systemd/system/${SERVICE}.service"; systemctl daemon-reload ;;
        openrc)  rc-update del "$SERVICE" default >/dev/null 2>&1 || true; rm -f "/etc/init.d/${SERVICE}" ;;
        runit)   rm -f "/var/service/${SERVICE}"; rm -rf "/etc/sv/${SERVICE}" ;;
    esac
    wall_remove
    rm -f "$BB_BIN" "$SUDOERS"
    rm -rf "$RELEASES" "$SHIM"
    rm -f "$OPT"
    if [ "$PURGE" = 1 ]; then
        rm -rf "$VAR" "$ETC"
        if grep -qx "$ACCOUNT" "$MADE" 2>/dev/null || ! id -u "$ACCOUNT" >/dev/null 2>&1; then
            userdel "$ACCOUNT" >/dev/null 2>&1 || true
        fi
        printf '   the state, the env file, the secrets and %s are gone; the projects stay\n' "$ACCOUNT"
    else
        printf '   the state (%s), the env file, the secrets and %s stay: --install puts the controller back on them\n' \
            "$VAR/config" "$ACCOUNT"
    fi
}

# ---- the controller's own node --------------------------------------------------
# own_node: this machine as an ordinary agent node of its own controller,
# made the way any node is: a token minted from a shell on the controller
# (bb nodes enroll-token --own), then provision-linux.sh run as it is, from
# the release, with --beside-controller. It dials the controller at the
# address a remote node would (this machine's own on its network), so a
# session there reaches it by that address and port and by nothing else.
# A machine that is a node already is left as it is: of this controller,
# provisioned again for a newer agent and bb-session; of another, said.
OWN_MARK="$ETC/own-node"
# The features the installer on the ISO was asked for (R160 step 2), turned
# on with the node at the first boot: one id per line, on the data partition.
OS_FEATURES_FILE="$P/var/lib/builderbot-os/features"
declare -a OS_FEATURES=()
own_node() {
    local ip name tok ctl prov="$OPT/nodes/provision-linux.sh"
    local -a dev=()
    [ "$DEV" = 1 ] && dev=(--dev)
    say "this machine as a node of its own controller"
    ip="$(lan_ip)" || true
    [ -n "$ip" ] || { warn "this machine has no address on a network, so it cannot be a node of itself: --install again once it has one"; return 1; }
    ctl="http://${ip}:${PORT}"
    if [ -f /etc/builderbot/node.json ]; then
        if [ -f "$OWN_MARK" ]; then
            bash "$prov" --session-user "$SESSION_USER" --user "$JOBS_USER" --beside-controller "${dev[@]}" \
                || warn "provisioning this machine's node again did not finish (above)"
        else
            warn "this machine is a node already, enrolled by another run or another controller: left as it is (provision-linux.sh --remove takes it away, and --install then makes it this controller's)"
        fi
        return 0
    fi
    name="$(hostname -s 2>/dev/null || hostname)"
    tok="$("$BB_BIN" nodes enroll-token "$name" --user "$JOBS_USER" --own)" \
        || { warn "the controller would not mint this machine a token (above)"; return 1; }
    bash "$prov" --controller "$ctl" --token "$tok" --user "$JOBS_USER" --session-user "$SESSION_USER" \
        --beside-controller "${dev[@]}" "${OS_FEATURES[@]}" || { warn "this machine did not enroll as a node (above); --install again tries again"; return 1; }
    printf '%s\n' "$ctl" > "$OWN_MARK"
    printf '   enrolled as %s, at %s\n' "$name" "$ctl"
    printf '   Give this machine a fixed address: the node reaches its controller at %s.\n' "$ip"
}

# ---- the wall ---------------------------------------------------------------------
# What a session on this machine's node never reaches (docs/decisions.md, "A
# controller installed bare metal, and its own node"): /etc/bb-session.wall
# names the controller's folders, which bb-session covers in every view and
# holds to their owners and modes before it starts a session. The
# controller keeps no port on the loopback that answers without a sign-in
# (its terminals are the dashboard's own, R133), so the wall names none, and
# the port table an earlier install wrote is taken away.
# The name of that table (bb-session's WALL_TABLE).
WALL_TABLE=builderbot_wall
WALL_NFT="$P/etc/builderbot-controller/wall.nft"

# wall_cover: the folders, from the env file as the controller reads it,
# each once and none inside another.
wall_cover() {
    local p out=() kept=()
    for p in "$VAR" "$ETC" /run/builderbot /run/builderbot-key "$(dirname "$(env_get SSH_AUTH_SOCK)")" \
             "$(env_get DASHBOARD_STATE)" "$(env_get BUILDER_HOME)" "$(env_get SDK_ROOT)" \
             "$(env_get WORKSPACE)" "$(env_get BB_SECRETS_DIR)"; do
        case "$p" in /?*) out+=("${p%/}") ;; esac
    done
    while read -r p; do
        local inside=0 k
        for k in "${kept[@]}"; do
            case "$p" in "$k"|"$k"/*) inside=1 ;; esac
        done
        [ "$inside" = 1 ] || kept+=("$p")
    done < <(printf '%s\n' "${out[@]}" | awk '{print length, $0}' | sort -n | cut -d' ' -f2- | awk '!seen[$0]++')
    (IFS=:; printf '%s' "${kept[*]}")
}

wall_write() {
    say "the wall: what a session on this machine never reaches"
    {
        printf '# Written by BuilderBot'"'"'s install-controller.sh (R90): this machine is a BuilderBot\n'
        printf '# controller, and a session on its node is kept out of what follows. bb-session\n'
        printf '# covers every folder in COVER in a session'"'"'s view and starts none unless the\n'
        printf '# session and job accounts reach none of it.\n'
        printf 'ACCOUNT=%s\nJOBS_USER=%s\nCOVER=%s\nPORTS=\n' "$ACCOUNT" "$JOBS_USER" "$(wall_cover)"
    } > "$WALL_FILE.new"
    chmod 0644 "$WALL_FILE.new"
    mv -f "$WALL_FILE.new" "$WALL_FILE"
    rm -f "$WALL_NFT"
    if [ -z "$P" ]; then
        command -v nft >/dev/null 2>&1 && nft delete table inet "${WALL_TABLE}" >/dev/null 2>&1 || true
        boot_oneshot_remove builderbot-wall wall.nft
    fi
    printf '   %s: %s\n' "$WALL_FILE" "$(wall_cover)"
}

# boot_oneshot NAME DESC CMD: run once now and at every boot, the way this
# init runs a one-shot (the provisioner's session ports, the same three).
boot_oneshot() {
    local name="$1" desc="$2" cmd="$3"
    case "$INIT" in
        systemd)
            cat > "/etc/systemd/system/${name}.service" <<EOF
[Unit]
Description=${desc}
After=network-pre.target
Wants=network-pre.target
Before=network.target ${SERVICE}.service builderbot-agent.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=${cmd}

[Install]
WantedBy=multi-user.target
EOF
            systemctl daemon-reload
            systemctl enable "$name" >/dev/null 2>&1 || true ;;
        openrc)
            install -d -m 0755 /etc/local.d
            printf '#!/bin/sh\n# %s\n%s\n' "$desc" "$cmd" > "/etc/local.d/${name}.start"
            chmod 0755 "/etc/local.d/${name}.start"
            rc-update add local default >/dev/null 2>&1 || true ;;
        runit)
            touch /etc/rc.local; chmod 0755 /etc/rc.local
            grep -qF "$cmd" /etc/rc.local || printf '%s\n' "$cmd" >> /etc/rc.local ;;
    esac
}

# boot_oneshot_remove NAME MATCH: a one-shot boot_oneshot made, taken away
# (MATCH: what its line in rc.local names).
boot_oneshot_remove() {
    case "$INIT" in
        systemd) systemctl disable "$1" >/dev/null 2>&1 || true
                 rm -f "/etc/systemd/system/$1.service" ;;
        openrc)  rm -f "/etc/local.d/$1.start" ;;
        runit)   [ -f /etc/rc.local ] && sed -i "\\|$2|d" /etc/rc.local ;;
    esac
}

wall_remove() {
    rm -f "$WALL_FILE" "$WALL_NFT"
    command -v nft >/dev/null 2>&1 && nft delete table inet "${WALL_TABLE}" >/dev/null 2>&1 || true
    boot_oneshot_remove builderbot-wall wall.nft
}

main() {
    [ $# -gt 0 ] || { usage; exit 0; }
    while [ $# -gt 0 ]; do
        case "$1" in
            --check|--install|--update|--remove|--stage|--firstboot)
                [ -z "$ACTION" ] || die "one action at a time: ${ACTION} and $1"
                ACTION="$1"; shift ;;
            --workspace) WORKSPACE_DIR="${2:?--workspace needs a path}"; shift 2 ;;
            --port) PORT="${2:?--port needs a number}"; shift 2 ;;
            --account) ACCOUNT="${2:?--account needs a name}"; shift 2 ;;
            --jobs-user) JOBS_USER="${2:?}"; shift 2 ;;
            --session-user) SESSION_USER="${2:?}"; shift 2 ;;
            --docker) DOCKER_GROUP=1; shift ;;
            --no-node) NODE=0; shift ;;
            --dev) DEV=1; shift ;;
            --release) RELEASE="${2:?--release needs a tag}"; shift 2 ;;
            --from) FROM="${2:?--from needs a folder}"; shift 2 ;;
            --yes) ASSUME_YES=1; shift ;;
            --purge) PURGE=1; shift ;;
            -h|--help) usage; exit 0 ;;
            *) echo "unknown option: $1" >&2; usage >&2; exit 1 ;;
        esac
    done
    case "$PORT" in ''|*[!0-9]*) die "--port takes a number" ;; esac
    case "$ACCOUNT" in [a-z_][a-z0-9_-]*) ;; *) die "--account takes an account name" ;; esac
    # An install that is here already keeps its own answers.
    if [ -f "$ENV_FILE" ]; then
        ACCOUNT="$(env_get BB_ACCOUNT)"; ACCOUNT="${ACCOUNT:-builderbot}"
        PORT="$(env_get DASHBOARD_PORT)"; PORT="${PORT:-7680}"
    fi
    case "$ACTION" in
        --check) cmd_check ;;
        --install) cmd_install ;;
        --update) cmd_update ;;
        --remove) cmd_remove ;;
        --stage) cmd_stage ;;
        --firstboot) cmd_firstboot ;;
        *) usage; exit 1 ;;
    esac
}

# Sourced by the unit tests for its functions: nothing runs.
[ "${BB_CONTROLLER_LIB:-0}" = 1 ] && return 0
main "$@"
