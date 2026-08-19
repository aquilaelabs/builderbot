#!/usr/bin/env bash
# Shared helpers for BuilderBot startup scripts.
# shellcheck shell=bash

BUILDER_HOME="${BUILDER_HOME:-/home/builder}"
WORKSPACE="${WORKSPACE:-/workspace}"
RUNNER_DIR="${RUNNER_DIR:-/opt/actions-runner}"

log()  { printf '[builderbot] %s\n'      "$*"; }
warn() { printf '[builderbot] WARN: %s\n' "$*" >&2; }
die()  { printf '[builderbot] ERROR: %s\n' "$*" >&2; exit 1; }

# is_true VALUE — accepts true/1/yes/on in any case.
is_true() {
    case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
        true|1|yes|y|on) return 0 ;;
        *) return 1 ;;
    esac
}

# is_mountpoint PATH — is this path a bind mount from the host?
#
# Used to tell a directory this container owns from one that belongs to the
# server: the projects folder is mounted whole now, so /workspace is somebody's
# share rather than a scratch directory we made, and changing its ownership is
# not ours to do.
is_mountpoint() {
    local p="${1%/}"
    [ -n "$p" ] || return 1
    awk -v p="$p" '$5 == p { found = 1 } END { exit !found }' /proc/self/mountinfo
}

# sdk_root — where downloadable SDKs live.
#
# The image is the wrong home for them: /opt is discarded on every update, so
# anything installed there is downloaded again on a weekly schedule, and the
# packages are large enough (a system image is a couple of GB, the emulator
# 800MB) for that to be the dominant cost of an update. A mounted share keeps
# them outside the image entirely — installed once, kept forever, shared by
# every toolchain that can be told where to unpack.
#
# SDK_ROOT is that share, /sdk by default. Without one — nobody mapped it —
# this falls back to the home volume, which also persists but is the
# operator's own directory rather than a place to put 30GB.
sdk_root() {
    local root="${SDK_ROOT:-/sdk}"
    if [ -d "$root" ] && [ -w "$root" ]; then
        # /sdk is the image's own default and exists in the image whether or
        # not anybody mapped a share there, so it has to prove it is a mount
        # before anything large is written to it. Any other path is one the
        # operator chose — a subdirectory of another share, say — and is
        # taken at its word; silently ignoring it and using the home volume
        # instead is the behaviour this branch exists to avoid.
        if [ "$root" != /sdk ] || is_mountpoint "$root"; then
            printf '%s' "$root"
            return 0
        fi
    fi
    printf '%s' "${BUILDER_HOME:-${HOME:-/home/builder}}/.sdk"
}

# sdk_have ROOT NAME — is a toolchain installed under the SDK root?
sdk_have() {
    [ -d "$1/$2" ] && [ -n "$(ls -A "$1/$2" 2>/dev/null)" ]
}

# sdk_find NAME — where a toolchain actually is: the share if it holds it,
# otherwise the home volume's root, otherwise nothing.
#
# The two can both be real. Anything installed before a share was mapped sits
# on the home volume, and mapping one must not make it vanish — which it did:
# PATH lost three toolchains and the dashboard called them uninstalled while
# 8GB of them sat on disk. Same rule the Android package directories follow,
# for the same reason: a thing that exists is never hidden behind an empty
# directory somewhere else. Installs still go to the share; this is only
# about finding what is already there.
sdk_find() {
    local name="$1" root fallback
    root="$(sdk_root)"
    fallback="${BUILDER_HOME:-${HOME:-/home/builder}}/.sdk"
    if sdk_have "$root" "$name"; then printf '%s/%s' "$root" "$name"; return 0; fi
    if [ "$fallback" != "$root" ] && sdk_have "$fallback" "$name"; then
        printf '%s/%s' "$fallback" "$name"; return 0
    fi
    return 1
}

# run_as_builder CMD... — drop privileges when we happen to be root.
run_as_builder() {
    if [ "$(id -u)" -eq 0 ]; then
        gosu builder "$@"
    else
        "$@"
    fi
}

# bb_log_dir — where the persistent log lives. Priority: explicit BB_LOG_DIR
# env, then a mounted /logs volume (the optional template/compose mapping),
# then the default inside /config.
bb_log_dir() {
    if [ -n "${BB_LOG_DIR:-}" ]; then
        printf '%s' "$BB_LOG_DIR"
    elif [ -d /logs ]; then
        printf '%s' /logs
    else
        printf '%s' /config/logs
    fi
}

# clear_npm_staging — remove half-finished npm upgrade directories.
#
# npm upgrades a package by renaming the installed directory to a hidden
# sibling before unpacking the replacement. A container killed mid-update
# leaves that sibling behind, and every install from then on fails with
# ENOTEMPTY — permanently, because nothing removes it on its own. The symptom
# is a container that silently stops picking up Claude Code updates.
clear_npm_staging() {
    local scope="${HOME}/.npm-global/lib/node_modules/@anthropic-ai"
    [ -d "$scope" ] || return 0
    find "$scope" -maxdepth 1 -type d -name '.claude-code-*' \
        -exec rm -rf {} + 2>/dev/null || true
}

# install_claude_code [VERSION] — install or upgrade Claude Code into the home
# volume. Retries once from a clean package directory, which is safe to do:
# ~/.npm-global precedes /usr/local on PATH, so the worst case falls back to
# the copy baked into the image.
install_claude_code() {
    local version="${1:-latest}"
    local pkg="${HOME}/.npm-global/lib/node_modules/@anthropic-ai/claude-code"

    clear_npm_staging
    # --allow-scripts: newer npm majors block postinstall by default, which
    # would silently skip Claude Code's native installer.
    if npm install -g --no-fund --no-audit \
        --allow-scripts=@anthropic-ai/claude-code \
        "@anthropic-ai/claude-code@${version}"; then
        return 0
    fi

    warn "npm install failed — clearing the package directory and retrying once"
    clear_npm_staging
    rm -rf "$pkg"
    npm install -g --no-fund --no-audit \
        --allow-scripts=@anthropic-ai/claude-code \
        "@anthropic-ai/claude-code@${version}"
}

# git_branch DIR — current branch name, or '?'. Handles a freshly-init'd repo
# with no commits, where `rev-parse --abbrev-ref HEAD` both prints and fails.
git_branch() {
    git -C "$1" symbolic-ref --short -q HEAD 2>/dev/null \
        || git -C "$1" rev-parse --short HEAD 2>/dev/null \
        || echo '?'
}

# scope_path KIND — API path for runner registration/removal tokens, derived
# from GITHUB_URL (repo URL vs org URL).
scope_path() {
    local kind="$1" path
    path="${GITHUB_URL#*://}"      # strip scheme
    path="${path#*/}"              # strip host
    path="${path%/}"
    path="${path%.git}"
    case "$path" in
        */*) printf '/repos/%s/actions/runners/%s-token' "$path" "$kind" ;;
        "")  die "could not parse GITHUB_URL='${GITHUB_URL}'" ;;
        *)   printf '/orgs/%s/actions/runners/%s-token' "$path" "$kind" ;;
    esac
}

# github_api METHOD PATH — authenticated call against the GitHub REST API.
# Requires GITHUB_PAT. Prints the response body on success; on failure it
# explains what the status code means for *this* call rather than leaving a
# bare "curl: (22) ... error: 403" in the log.
github_api() {
    local method="$1" path="$2" resp code body scope_hint
    [ -n "${GITHUB_PAT:-}" ] || die "GITHUB_PAT is required for '$path'"

    case "$path" in
        /orgs/*) scope_hint="an ORG-level call: the token needs Organization permissions -> 'Self-hosted runners': Read and write (fine-grained), or the admin:org scope (classic), and its resource owner must be the organization" ;;
        *)       scope_hint="a REPO-level call: the token needs Repository permissions -> 'Administration': Read and write on that repository" ;;
    esac

    resp="$(curl -sS -w $'\n%{http_code}' -X "$method" \
        -H "Accept: application/vnd.github+json" \
        -H "Authorization: Bearer ${GITHUB_PAT}" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "${GITHUB_API_URL:-https://api.github.com}${path}" 2>&1)" \
        || die "could not reach the GitHub API for ${path} (network/DNS?)"

    code="${resp##*$'\n'}"
    body="${resp%$'\n'*}"

    case "$code" in
        2*) printf '%s' "$body" ;;
        401) die "GitHub rejected the token (401) on ${path} — it is invalid, revoked, or expired." ;;
        403) die "GitHub denied the request (403) on ${path}. This is ${scope_hint}." ;;
        404) die "GitHub returned 404 on ${path}. Either GITHUB_URL points somewhere that does not exist, or the token cannot see it — GitHub answers 404 rather than 403 for resources a token has no access to. This is ${scope_hint}." ;;
        *)   die "GitHub API returned ${code} on ${path}: $(printf '%s' "$body" | tr -d '\n' | head -c 200)" ;;
    esac
}
