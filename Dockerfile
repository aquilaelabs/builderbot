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
ARG TARGETARCH

# Several steps below pipe curl into a shell or into gpg. Under the default
# /bin/sh the exit status of a pipeline is only its *last* command, so a failed
# download would be silently baked into the image. Fail on any stage instead.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Etc/UTC \
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
# Unprivileged user. UID/GID are remapped at startup from PUID/PGID, so the
# build-time numbers here are only a placeholder. Ubuntu 24.04 ships a stock
# "ubuntu" user on 1000 — drop it so 1000 is free.
# ---------------------------------------------------------------------------
RUN set -eux; \
    userdel -r ubuntu 2>/dev/null || true; \
    groupadd -g 1000 builder; \
    useradd -m -u 1000 -g 1000 -s /bin/bash builder; \
    echo 'builder ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/builder; \
    chmod 0440 /etc/sudoers.d/builder; \
    mkdir -p "${WORKSPACE}" "${RUNNER_DIR}" /opt/builderbot; \
    chown -R builder:builder "${WORKSPACE}" "${RUNNER_DIR}"

# ---------------------------------------------------------------------------
# Claude Code + friends, installed globally so a brand-new (empty) home volume
# still has a working `claude` on PATH. Runtime updates install into
# ~/.npm-global, which precedes /usr/local on PATH.
# ---------------------------------------------------------------------------
RUN set -eux; \
    npm install -g npm@latest; \
    npm install -g @anthropic-ai/claude-code; \
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
COPY scripts/ /opt/builderbot/scripts/
COPY config/skel/ /opt/builderbot/skel/

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
