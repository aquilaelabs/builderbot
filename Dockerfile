# syntax=docker/dockerfile:1
# SecretsUsedInArgOrEnv fires on ENV SSH_AUTH_SOCK, whose value is a socket
# PATH — the rule pattern-matches names containing AUTH/KEY/TOKEN/SECRET. The
# reasoning lives at the line itself; the directive has to be up here, because
# BuildKit only reads check= before the first instruction.
# check=skip=SecretsUsedInArgOrEnv
# DS-0002 (image runs as root) suppressed: no USER on purpose. The entrypoint
# must start as root to load shielded secrets into a root-owned agent and set
# up the runner, and only then hands sessions to `builder`; a USER here would
# break exactly the privilege separation the finding is asking for.
#trivy:ignore:AVD-DS-0002

##############################################################################
# BuilderBot — a Claude Code workstation and the controller for build nodes:
# the machines where builds, tests, CI and the Android emulator actually run.
##############################################################################
FROM ubuntu:24.04

LABEL org.opencontainers.image.title="BuilderBot" \
      org.opencontainers.image.description="Claude Code workstation and build-node controller" \
      org.opencontainers.image.source="https://github.com/Stencil-Projects/BuilderBot" \
      org.opencontainers.image.licenses="Apache-2.0"

ARG DEBIAN_FRONTEND=noninteractive
ARG NODE_MAJOR=22
# ttyd serves the dashboard's terminal. Ubuntu packages it, but the static
# release is a single self-contained binary and pins to a known version.
ARG TTYD_VERSION=1.7.7
ARG TARGETARCH

# --- Playwright build knob -------------------------------------------------
# "false" for a slimmer image without the module and its libraries. There is
# no Android knob any more: the SDK is a node's, from its store (10c).
ARG INSTALL_PLAYWRIGHT=true

# Several steps below pipe curl into a shell or into gpg. Under the default
# /bin/sh the exit status of a pipeline is only its *last* command, so a failed
# download would be silently baked into the image. Fail on any stage instead.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# NPM_CONFIG_FUND / PIP_DISABLE_PIP_VERSION_CHECK drop banners that carry no
# information: the funding appeal and the "a new pip is available" nag. Set as
# container env rather than in the shell profile, because that profile is
# guarded on an interactive shell and a Claude session's commands are not one.
# Deliberately NOT disabling `npm audit` — that one is a real signal.
# PYTHONDONTWRITEBYTECODE: a session that runs `python3 -m py_compile` (or any
# script) in a mounted project should not leave __pycache__ litter in the
# repo. NODE_PATH: the image's global modules — Playwright above all — resolve
# from a `require()` in any directory, instead of every session symlinking
# them into a scratch node_modules first. (ESM `import` ignores NODE_PATH;
# use createRequire, as scripts/dashboard/test/lib.mjs does.)
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Etc/UTC \
    NPM_CONFIG_FUND=false \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NODE_PATH=/usr/lib/node_modules \
    BUILDER_HOME=/home/builder \
    WORKSPACE=/workspace \
    PATH=/opt/builderbot/bin:/home/builder/.npm-global/bin:/home/builder/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

# ---------------------------------------------------------------------------
# Base system + build toolchain
# ---------------------------------------------------------------------------
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates curl wget gnupg lsb-release apt-transport-https \
        git git-lfs openssh-client \
        build-essential pkg-config make cmake \
        python3 python3-pip python3-venv python3-dev pipx \
        jq unzip zip xz-utils bzip2 tar rsync \
        tmux \
        ripgrep fd-find fzf \
        less nano vim tini gosu sudo procps psmisc file lsof strace tree \
        iproute2 iputils-ping dnsutils netcat-openbsd socat \
        shellcheck \
        locales tzdata \
        libicu74 libssl3 libkrb5-3 zlib1g liblttng-ust1 \
        sqlite3 imagemagick ffmpeg; \
    ln -sf /usr/bin/fdfind /usr/local/bin/fd; \
    git lfs install --system; \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Node.js (NodeSource), GitHub CLI, Docker CLI + compose plugin
#   The Docker CLI talks to the host daemon through a mounted
#   /var/run/docker.sock — no daemon runs inside this container.
# ---------------------------------------------------------------------------
RUN set -eux; \
    install -m 0755 -d /etc/apt/keyrings; \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg; \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list; \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /etc/apt/keyrings/githubcli.gpg; \
    chmod 0644 /etc/apt/keyrings/githubcli.gpg; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list; \
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        nodejs gh docker-ce-cli docker-compose-plugin docker-buildx-plugin; \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Linters for the file types every project here carries: Dockerfiles, GitHub
# workflows, YAML, Python. shellcheck came from apt above; these three are
# static single binaries with no Ubuntu package worth having. Resolved to the
# newest release at build time, same policy as the runner and bundletool —
# the weekly rebuild is what keeps them current. `ruff` installs via pipx so
# it is isolated from both the system Python and any project venv.
#
# Resolved WITHOUT api.github.com, deliberately: the API allows 60 anonymous
# calls per hour per IP, and CI builds run from shared Actions egress
# addresses that have usually spent that budget already — the "latest release"
# JSON comes back as a rate-limit error, jq reads a null tag, and the build
# dies on a 404. The releases/latest/download/ endpoint and the /releases/
# latest redirect carry the same information with no such limit.
#
# The point of having them *in the image* rather than only in CI: a session
# (or a person) can run the same checks CI will run, before the push — that
# is what `bb lint` does.
# ---------------------------------------------------------------------------
RUN set -eux; \
    curl -fsSL -o /usr/local/bin/hadolint \
        https://github.com/hadolint/hadolint/releases/latest/download/hadolint-Linux-x86_64; \
    curl -fsSL -o /usr/local/bin/yq \
        https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64; \
    chmod +x /usr/local/bin/hadolint /usr/local/bin/yq; \
    tag="$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/rhysd/actionlint/releases/latest)"; \
    tag="${tag##*/}"; \
    curl -fsSL "https://github.com/rhysd/actionlint/releases/download/${tag}/actionlint_${tag#v}_linux_amd64.tar.gz" \
        | tar -xz -C /usr/local/bin actionlint; \
    PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install ruff; \
    hadolint --version; \
    actionlint --version >/dev/null; \
    yq --version; \
    ruff --version

# ---------------------------------------------------------------------------
# Language/version tooling that lives outside apt: uv (Python) and mise.
#
# Both vendors' install scripts take a destination env var, but they have
# changed names before — so after each install we also sweep the usual drop
# points and relocate anything we find. The final `--version` calls make a
# silently-missing tool a build failure rather than a runtime surprise.
# ---------------------------------------------------------------------------
RUN set -eux; \
    relocate() { \
        bin="$1"; \
        command -v "$bin" >/dev/null 2>&1 && return 0; \
        for candidate in "/root/.local/bin/$bin" "/root/.cargo/bin/$bin" "$HOME/.local/bin/$bin"; do \
            if [ -x "$candidate" ]; then mv "$candidate" "/usr/local/bin/$bin"; return 0; fi; \
        done; \
        return 1; \
    }; \
    curl -fsSL https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh; \
    relocate uv; \
    curl -fsSL https://mise.run | env MISE_INSTALL_PATH=/usr/local/bin/mise sh; \
    relocate mise; \
    chmod +x /usr/local/bin/uv /usr/local/bin/mise 2>/dev/null || true; \
    uv --version; \
    mise --version

# ---------------------------------------------------------------------------
# Playwright: the module and the system libraries here, the browsers on the
# SDK share.
#
# The three browsers are 1.3GB of pure download — the largest thing left that
# /opt would throw away on every image update — so `install-deps` (apt
# packages, which have to be in the image because they integrate with the
# system) is split from `install` (the browser bundles, which do not). The
# startup hook fetches those into the share on first boot and symlinks
# PLAYWRIGHT_BROWSERS_PATH at them, so every path the image has always
# promised — /opt/pw-browsers/chromium above all — still resolves.
#
# The env var keeps its value for the same reason: every project's playwright,
# the dashboard's tests and `bb shot` name that directory, and it is now a
# link rather than a directory.
# ---------------------------------------------------------------------------
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

# DS-0017 suppressed: the apt-get update below feeds `playwright
# install-deps`, which runs apt-get install itself in this same layer; the
# scanner only recognizes a literal install and reports the update as alone.
#trivy:ignore:AVD-DS-0017
RUN set -eux; \
    if [ "${INSTALL_PLAYWRIGHT}" != "true" ]; then echo "skipping Playwright"; exit 0; fi; \
    npm install -g --foreground-scripts playwright; \
    apt-get update; \
    playwright install-deps chromium firefox webkit; \
    npm cache clean --force; \
    rm -rf /var/lib/apt/lists/*; \
    playwright --version

# ---------------------------------------------------------------------------
# No JDK and no Android SDK in the image (roadmap #24, phase 10c). Builds,
# tests, CI and the emulator run on a node; what a node needs comes from its
# packages store through the catalog's recipes (jdk, android-tools,
# android:*), installed from the Tools tab. A nodeless project's session
# here reads, edits, commits and pushes, and cannot compile — that is the
# design, not a gap (docs/nodes.md §18, §20).
#
# What stays is the small runtime half a CONTAINER in the node role needs
# and cannot install for itself, since its agent is not root: the libraries
# the emulator loads (audio, GL), and the X server the GPU path needs —
# NVIDIA's EGL will not hand out a display without one carrying its own GLX
# module, which the container runtime injects when NVIDIA_DRIVER_CAPABILITIES
# includes `display`; scripts/startup.d/48-gpu-display starts it, node role
# only. A VM node gets the same from the recipe (android:emulator's
# system.apt) and vm/provision.sh.
# ---------------------------------------------------------------------------
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        libpulse0 libgl1 libglu1-mesa libasound2t64 libegl1 libvulkan1 \
        xserver-xorg-core xkb-data; \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Unprivileged user. UID/GID are remapped at startup from PUID/PGID, so the
# build-time numbers here are only a placeholder. Ubuntu 24.04 ships a stock
# "ubuntu" user on 1000 — drop it so 1000 is free.
# ---------------------------------------------------------------------------
RUN set -eux; \
    userdel -r ubuntu 2>/dev/null || true; \
    groupadd -g 1000 builder; \
    useradd -m -u 1000 -g 1000 -s /bin/bash builder; \
    # No general sudo: with blanket root access, shielding secrets from the
    # builder user (i.e. from Claude sessions) would be theater. The one
    # sanctioned privilege is minting short-lived runner tokens from the
    # root-only secret stash. System packages install via EXTRA_APT_PACKAGES,
    # which runs as root during startup.
    echo 'builder ALL=(root) NOPASSWD: /opt/builderbot/scripts/mint-runner-token' > /etc/sudoers.d/builder; \
    chmod 0440 /etc/sudoers.d/builder; \
    # Explicitly lock both accounts' passwords: password auth must never be a
    # path to privilege in this container — there is nothing to brute-force,
    # which is stronger than any lockout policy. (They are created locked;
    # this pins the guarantee against future drift.)
    passwd -l root; \
    passwd -l builder; \
    mkdir -p "${WORKSPACE}" /opt/builderbot; \
    chown -R builder:builder "${WORKSPACE}"

# ---------------------------------------------------------------------------
# Claude Code is NOT in this image. It is Anthropic's proprietary binary
# ("all rights reserved"), and this image is published: baking it in would be
# redistributing it. The first boot installs it into the home volume
# (scripts/startup.d/20-claude-code.sh, into ~/.npm-global, which precedes
# /usr/local on PATH), where every later update also lands — so the container
# self-updates without a rebuild, and the image ships only what it may.
#
# web-ext (MPL) is here: the controller carries what it needs in the image,
# and there is no package list at boot (R29, then the operator's call:
# everything else comes from the package manager on a node).
# ---------------------------------------------------------------------------
RUN set -eux; \
    npm install -g --foreground-scripts web-ext; \
    corepack enable; \
    npm cache clean --force

# ---------------------------------------------------------------------------
# BuilderBot scripts + home skeleton
# ---------------------------------------------------------------------------
# ttyd: fetched rather than apt-installed so the version is pinned and the
# binary is static — nothing to keep in step with the base image.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) tarch=x86_64 ;; \
        arm64) tarch=aarch64 ;; \
        *) echo "no ttyd build for ${arch}; dashboard terminal unavailable"; exit 0 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/ttyd \
        "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${tarch}"; \
    chmod +x /usr/local/bin/ttyd; \
    ttyd --version

COPY scripts/ /opt/builderbot/scripts/
COPY config/skel/ /opt/builderbot/skel/
COPY config/templates/ /opt/builderbot/templates/
# The package catalog the Tools tab renders and `bb sdk` walks. Under config/
# so that the path relative to both bb and server.py is the same here as it is
# in a checkout, which is what lets `bb dashboard dev` and the tests read it.
COPY config/packages.json /opt/builderbot/config/packages.json
# Carried in the image so the container can seed Unraid's icon cache itself
# rather than depending on a URL Unraid can reach — see
# scripts/startup.d/05-unraid-icon.root.sh.
COPY config/icon.png /opt/builderbot/icon.png

RUN set -eux; \
    chmod -R +x /opt/builderbot/scripts; \
    ln -sf /opt/builderbot/scripts/bb /usr/local/bin/bb; \
    # /opt/builderbot/bin sits first on PATH and holds privilege-dropping
    # wrappers, so `docker exec -it builderbot claude` runs as `builder`
    # (correct HOME, correct file ownership) instead of as root.
    mkdir -p /opt/builderbot/bin; \
    ln -sf /opt/builderbot/scripts/as-builder /opt/builderbot/bin/claude; \
    ln -sf /opt/builderbot/scripts/as-builder /opt/builderbot/bin/bb; \
    chown -R builder:builder /opt/builderbot/skel

# Baked in so `docker exec` sessions also see it: when the entrypoint has
# loaded shielded keys from /secrets/ssh into the root-owned agent, every
# session's ssh/git picks them up through this socket. Harmless when no
# agent is running — ssh falls back to ~/.ssh key files.
# Two scanners flag this and both are wrong in the same way: the value is a
# PATH, and the rules pattern-match names containing AUTH/KEY/TOKEN/SECRET.
# Nothing sensitive is in the image — `docker history` shows a string — and
# the keys it leads to are root-owned in /secrets, mounted at runtime and
# unreadable to sessions by design. The socket being public is the point:
# everyone needs to reach an agent nobody can extract from.
# trivy: AVD-DS-0031. buildkit: SecretsUsedInArgOrEnv.
#trivy:ignore:AVD-DS-0031
ENV SSH_AUTH_SOCK=/run/ssh-agent.sock

# Where the SDK share is. Runtime-only, so it lives down here: an ENV in the
# top block invalidates every layer below it, and the host then re-pulls the lot.
ENV SDK_ROOT=/sdk

ENV PUID=99 \
    PGID=100 \
    AUTO_UPDATE_CLAUDE=true \
    CHOWN_HOME=true

# Which build of the image this is, readable from inside it.
#
# "Does this container have that fix yet?" had no answer from the running
# system: /opt is the image's, an Unraid container keeps serving whatever it
# last pulled, and the only clue was the uptime — which is how three rounds of
# one bug went by with the fix already published and the box still on the build
# before it. CI passes the commit and the time it built; an image built any
# other way carries neither, and the dashboard says `unstamped` rather than
# inventing something.
#
# Last, deliberately. These change on every single build, and an ARG or ENV
# invalidates every layer below it — down here that is nothing but metadata, so
# the host's pull is unaffected. In the top block this would re-download the
# whole toolchain for every commit.
# Named apart from the ENVs they fill, the way the Android baseline above is:
# `ENV X=${X}` is the same variable on both sides of one statement, which is a
# thing linters have opinions about and this file has no need to argue with.
ARG IMAGE_REV
ARG IMAGE_BUILT
ARG IMAGE_VERSION
ENV BB_IMAGE_REV=${IMAGE_REV} \
    BB_IMAGE_BUILT=${IMAGE_BUILT} \
    BB_VERSION=${IMAGE_VERSION}

WORKDIR /workspace

HEALTHCHECK --interval=60s --timeout=10s --start-period=90s --retries=3 \
    CMD ["/opt/builderbot/scripts/healthcheck.sh"]

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/builderbot/scripts/entrypoint.sh"]
CMD ["supervise"]
