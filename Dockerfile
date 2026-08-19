# syntax=docker/dockerfile:1
# DS-0002 (image runs as root) suppressed: no USER on purpose. The entrypoint
# must start as root to load shielded secrets into a root-owned agent and set
# up the runner, and only then hands sessions to `builder`; a USER here would
# break exactly the privilege separation the finding is asking for.
#trivy:ignore:AVD-DS-0002

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
# Kept for compatibility with existing build commands: the emulator is a
# runtime install now, so this only seeds ENABLE_ANDROID_EMULATOR's default.
ARG INSTALL_ANDROID_EMULATOR=true
# Bootstrap build of Google's commandline-tools zip; sdkmanager then manages
# everything else, so this pin only has to exist, not be current.
ARG ANDROID_CMDLINE_TOOLS_BUILD=11076708
ARG ANDROID_PLATFORM=36
ARG ANDROID_BUILD_TOOLS=36.0.0
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
# Java (needed for Android builds, Gradle/Maven publishing, bundletool)
# ---------------------------------------------------------------------------
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends openjdk-21-jdk-headless; \
    rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64

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
# Android SDK: cmdline-tools, platform-tools, build-tools, one platform, and
# (by default) the emulator with a Google-APIs x86_64 system image.
#
# Only the bootstrap lives in the image: cmdline-tools (sdkmanager), the
# platform-tools (adb) and bundletool — about 170MB. Everything downloadable
# on top of that — platforms, build-tools, the 800MB emulator, system images
# — is installed at runtime into the SDK root, which is a mounted share or
# the home volume, and is symlinked back into this tree. That is the whole
# point: /opt is discarded on every image update, so a package baked in here
# is re-downloaded weekly forever, while one on the share is downloaded once.
# The startup hook installs the baseline on first boot; `bb sdk` manages the
# rest. The tree is left world-writable so sdkmanager can write to it.
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
    # platform-tools only: adb has to work before anything else can, and it
    # is 22MB. The platform and build-tools the baseline needs are installed
    # on first boot, onto the share, by scripts/startup.d/50-android.sh.
    "$sdkm" --install "platform-tools" >/dev/null; \
    # bundletool for building/installing from .aab bundles. Version comes from
    # the /releases/latest redirect, not api.github.com — the API rate-limits
    # anonymous callers per IP and Actions egress IPs are shared, so a CI
    # build can 403 where a local one sails through.
    bt_ver="$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/google/bundletool/releases/latest)"; \
    bt_ver="${bt_ver##*/}"; \
    curl -fsSL -o "${ANDROID_HOME}/bundletool.jar" \
        "https://github.com/google/bundletool/releases/download/${bt_ver}/bundletool-all-${bt_ver}.jar"; \
    printf '#!/bin/sh\nexec java -jar %s/bundletool.jar "$@"\n' "${ANDROID_HOME}" \
        > /usr/local/bin/bundletool; \
    chmod +x /usr/local/bin/bundletool; \
    chmod -R a+rwX "${ANDROID_HOME}"; \
    rm -rf /var/lib/apt/lists/* /tmp/clt; \
    "${ANDROID_HOME}/platform-tools/adb" --version | head -1

ENV PATH=${PATH}:${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/emulator
# What the runtime scripts fall back to when ANDROID_SYSTEM_IMAGES is unset.
# Derived from the platform this image actually shipped, so a build with a
# different ANDROID_PLATFORM does not leave `bb emu` defaulting to an API
# level that is not there.
ENV ANDROID_DEFAULT_API=${ANDROID_PLATFORM}

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
# DS-0017 suppressed, same as Playwright above: the update feeds the
# runner's own installdependencies.sh, which apt-get installs in this layer.
#trivy:ignore:AVD-DS-0017
RUN set -eux; \
    case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
        amd64) RUNNER_ARCH=x64 ;; \
        arm64) RUNNER_ARCH=arm64 ;; \
        *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    version="${RUNNER_VERSION}"; \
    if [ "$version" = "latest" ]; then \
        # /releases/latest redirect, not api.github.com — anonymous API calls
        # are rate-limited per IP and shared Actions egress addresses have
        # usually exhausted the budget, which kills exactly the unattended
        # weekly rebuild this "latest" exists for.
        version="$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/actions/runner/releases/latest)"; \
        version="${version##*/}"; version="${version#v}"; \
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
# DS-0031 suppressed: a socket path, not a secret; the name trips the
# scanner's credential-shaped-variable heuristic.
#trivy:ignore:AVD-DS-0031
ENV SSH_AUTH_SOCK=/run/ssh-agent.sock

# RUNNER_LABELS here must be the full set runner.sh, the template and the docs
# agree on. It used to say builderbot,self-hosted,linux — which silently
# overrode the richer default in runner.sh for anyone running the image bare,
# because an ENV always exists and a ${VAR:-fallback} therefore never fires.
# The Android baseline the first boot installs onto the SDK share, and where
# that share is. Runtime-only, so they live down here: an ENV in the top
# block invalidates every layer below it, and the host then re-pulls the lot.
ENV ANDROID_BASELINE_PLATFORM=${ANDROID_PLATFORM} \
    ANDROID_BASELINE_BUILD_TOOLS=${ANDROID_BUILD_TOOLS} \
    ANDROID_BASELINE_EMULATOR=${INSTALL_ANDROID_EMULATOR} \
    SDK_ROOT=/sdk

ENV PUID=99 \
    PGID=100 \
    ENABLE_RUNNER=true \
    RUNNER_EPHEMERAL=true \
    RUNNER_LABELS=builderbot,self-hosted,linux,x64,unraid \
    RUNNER_WORKDIR=/workspace/_work \
    AUTO_UPDATE_CLAUDE=true \
    CHOWN_HOME=true

WORKDIR /workspace

HEALTHCHECK --interval=60s --timeout=10s --start-period=90s --retries=3 \
    CMD ["/opt/builderbot/scripts/healthcheck.sh"]

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/builderbot/scripts/entrypoint.sh"]
CMD ["supervise"]
