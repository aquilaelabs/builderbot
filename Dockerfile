# syntax=docker/dockerfile:1

##############################################################################
# BuilderBot — a single container that is both a Claude Code workstation and
# a self-hosted GitHub Actions runner.
##############################################################################
FROM ubuntu:24.04

LABEL org.opencontainers.image.title="BuilderBot" \
      org.opencontainers.image.description="Claude Code environment + GitHub Actions self-hosted runner" \
      org.opencontainers.image.source="https://github.com/Stencil-Projects/BuilderBot" \
      org.opencontainers.image.licenses="Apache-2.0"

ARG DEBIAN_FRONTEND=noninteractive
ARG NODE_MAJOR=22
# "latest" resolves the newest actions/runner release at build time.
ARG RUNNER_VERSION=latest
# ttyd serves the dashboard's terminal. Ubuntu packages it, but the static
# release is a single self-contained binary and pins to a known version.
ARG TTYD_VERSION=1.7.7
ARG TARGETARCH

# --- Playwright / Android build knobs --------------------------------------
# Set INSTALL_* to "false" for a slimmer image without that toolchain.
ARG INSTALL_PLAYWRIGHT=true
ARG INSTALL_ANDROID=true
ARG INSTALL_ANDROID_EMULATOR=true
# Bootstrap build of Google's commandline-tools zip; sdkmanager then manages
# everything else, so this pin only has to exist, not be current.
ARG ANDROID_CMDLINE_TOOLS_BUILD=11076708
ARG ANDROID_PLATFORM=35
ARG ANDROID_BUILD_TOOLS=35.0.0
ARG ANDROID_SYSTEM_IMAGE_VARIANT="google_apis;x86_64"

# Several steps below pipe curl into a shell or into gpg. Under the default
# /bin/sh the exit status of a pipeline is only its *last* command, so a failed
# download would be silently baked into the image. Fail on any stage instead.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# NPM_CONFIG_FUND / PIP_DISABLE_PIP_VERSION_CHECK drop banners that carry no
# information: the funding appeal and the "a new pip is available" nag. Set as
# container env rather than in the shell profile, because that profile is
# guarded on an interactive shell and a Claude session's commands are not one.
# Deliberately NOT disabling `npm audit` — that one is a real signal.
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Etc/UTC \
    NPM_CONFIG_FUND=false \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BUILDER_HOME=/home/builder \
    WORKSPACE=/workspace \
    RUNNER_DIR=/opt/actions-runner \
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
        less nano vim tini gosu sudo procps psmisc file \
        iproute2 iputils-ping dnsutils netcat-openbsd socat \
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
# Java (needed for Android builds, Gradle/Maven publishing, bundletool)
# ---------------------------------------------------------------------------
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends openjdk-21-jdk-headless; \
    rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64

# ---------------------------------------------------------------------------
# Playwright + browsers (chromium, firefox, webkit), shared system-wide.
#
# PLAYWRIGHT_BROWSERS_PATH makes every project's playwright resolve browsers
# from the same directory instead of per-project caches; the dir is left
# world-writable so a project pinning a different playwright version can
# `npx playwright install` its own revisions into it at runtime.
# ---------------------------------------------------------------------------
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

RUN set -eux; \
    if [ "${INSTALL_PLAYWRIGHT}" != "true" ]; then echo "skipping Playwright"; exit 0; fi; \
    npm install -g --foreground-scripts playwright; \
    apt-get update; \
    playwright install --with-deps chromium firefox webkit; \
    chmod -R a+rwX "${PLAYWRIGHT_BROWSERS_PATH}"; \
    npm cache clean --force; \
    rm -rf /var/lib/apt/lists/*; \
    playwright --version

# ---------------------------------------------------------------------------
# Android SDK: cmdline-tools, platform-tools, build-tools, one platform, and
# (by default) the emulator with a Google-APIs x86_64 system image.
#
# The SDK lives in the image so a fresh pull is ready to build APKs/AABs with
# zero setup; AVDs live in ~/.android on the persistent home volume. The tree
# is left world-writable so `sdkmanager --install` works at runtime for any
# extra platforms a project needs.
# ---------------------------------------------------------------------------
ENV ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk

RUN set -eux; \
    if [ "${INSTALL_ANDROID}" != "true" ]; then echo "skipping Android SDK"; exit 0; fi; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    if [ "$arch" != "amd64" ]; then echo "skipping Android SDK on ${arch}"; exit 0; fi; \
    apt-get update; \
    # libegl1/libvulkan1 are the GLVND + Vulkan dispatch layers. They are inert
    # on their own, but without them the vendor drivers that the NVIDIA
    # container runtime injects have no loader, so -gpu host cannot work.
    apt-get install -y --no-install-recommends \
        libpulse0 libgl1 libglu1-mesa libasound2t64 libegl1 libvulkan1; \
    mkdir -p "${ANDROID_HOME}/cmdline-tools"; \
    curl -fsSL -o /tmp/clt.zip \
        "https://dl.google.com/android/repository/commandlinetools-linux-${ANDROID_CMDLINE_TOOLS_BUILD}_latest.zip"; \
    unzip -q /tmp/clt.zip -d /tmp/clt; \
    rm /tmp/clt.zip; \
    mv /tmp/clt/cmdline-tools "${ANDROID_HOME}/cmdline-tools/latest"; \
    sdkm="${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager"; \
    # `yes` dies of SIGPIPE when sdkmanager stops reading — expected, and not
    # a failure, hence the || true inside the pipeline's first stage.
    (yes || true) | "$sdkm" --licenses >/dev/null; \
    "$sdkm" --install \
        "platform-tools" \
        "platforms;android-${ANDROID_PLATFORM}" \
        "build-tools;${ANDROID_BUILD_TOOLS}" \
        >/dev/null; \
    if [ "${INSTALL_ANDROID_EMULATOR}" = "true" ]; then \
        "$sdkm" --install \
            "emulator" \
            "system-images;android-${ANDROID_PLATFORM};${ANDROID_SYSTEM_IMAGE_VARIANT}" \
            >/dev/null; \
    fi; \
    # bundletool for building/installing from .aab bundles
    bt_ver="$(curl -fsSL https://api.github.com/repos/google/bundletool/releases/latest | jq -r '.tag_name')"; \
    curl -fsSL -o "${ANDROID_HOME}/bundletool.jar" \
        "https://github.com/google/bundletool/releases/download/${bt_ver}/bundletool-all-${bt_ver}.jar"; \
    printf '#!/bin/sh\nexec java -jar %s/bundletool.jar "$@"\n' "${ANDROID_HOME}" \
        > /usr/local/bin/bundletool; \
    chmod +x /usr/local/bin/bundletool; \
    chmod -R a+rwX "${ANDROID_HOME}"; \
    rm -rf /var/lib/apt/lists/* /tmp/clt; \
    "${ANDROID_HOME}/platform-tools/adb" --version | head -1

ENV PATH=${PATH}:${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/emulator

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
    mkdir -p "${WORKSPACE}" "${RUNNER_DIR}" /opt/builderbot; \
    chown -R builder:builder "${WORKSPACE}" "${RUNNER_DIR}"

# ---------------------------------------------------------------------------
# Claude Code + friends, installed globally so a brand-new (empty) home volume
# still has a working `claude` on PATH. Runtime updates install into
# ~/.npm-global, which precedes /usr/local on PATH.
# ---------------------------------------------------------------------------
# Node 22's bundled npm 10 is kept deliberately: newer npm majors block
# postinstall scripts by default, which silently skips Claude Code's native
# installer (install.cjs). The --allow-scripts flag covers the day an npm
# upgrade sneaks in anyway; on npm 10 it is an ignored config key.
RUN set -eux; \
    npm install -g --foreground-scripts \
        --allow-scripts=@anthropic-ai/claude-code \
        @anthropic-ai/claude-code; \
    corepack enable; \
    npm cache clean --force; \
    claude --version

# ---------------------------------------------------------------------------
# GitHub Actions runner
# ---------------------------------------------------------------------------
RUN set -eux; \
    case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
        amd64) RUNNER_ARCH=x64 ;; \
        arm64) RUNNER_ARCH=arm64 ;; \
        *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    version="${RUNNER_VERSION}"; \
    if [ "$version" = "latest" ]; then \
        version="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \
                   | jq -r .tag_name | sed 's/^v//')"; \
    fi; \
    echo "installing actions-runner ${version} (${RUNNER_ARCH})"; \
    curl -fsSL -o /tmp/runner.tar.gz \
        "https://github.com/actions/runner/releases/download/v${version}/actions-runner-linux-${RUNNER_ARCH}-${version}.tar.gz"; \
    tar xzf /tmp/runner.tar.gz -C "${RUNNER_DIR}"; \
    rm /tmp/runner.tar.gz; \
    apt-get update; \
    "${RUNNER_DIR}/bin/installdependencies.sh"; \
    echo "${version}" > "${RUNNER_DIR}/.runner-version"; \
    chown -R builder:builder "${RUNNER_DIR}"; \
    rm -rf /var/lib/apt/lists/*

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
ENV SSH_AUTH_SOCK=/run/ssh-agent.sock

ENV PUID=99 \
    PGID=100 \
    ENABLE_RUNNER=true \
    RUNNER_EPHEMERAL=true \
    RUNNER_LABELS=builderbot,self-hosted,linux \
    RUNNER_WORKDIR=/workspace/_work \
    AUTO_UPDATE_CLAUDE=true \
    CHOWN_HOME=true

WORKDIR /workspace

HEALTHCHECK --interval=60s --timeout=10s --start-period=90s --retries=3 \
    CMD /opt/builderbot/scripts/healthcheck.sh

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/builderbot/scripts/entrypoint.sh"]
CMD ["supervise"]
