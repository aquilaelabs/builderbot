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

# git_branch DIR — current branch name, or '?'. Handles a freshly-init'd repo
# with no commits, where `rev-parse --abbrev-ref HEAD` both prints and fails.
git_branch() {
    git -C "$1" symbolic-ref --short -q HEAD 2>/dev/null \
        || git -C "$1" rev-parse --short HEAD 2>/dev/null \
        || echo '?'
}

# github_api METHOD PATH — authenticated call against the GitHub REST API.
# Requires GITHUB_PAT. Prints the response body.
github_api() {
    local method="$1" path="$2"
    [ -n "${GITHUB_PAT:-}" ] || die "GITHUB_PAT is required for '$path'"
    curl -fsSL -X "$method" \
        -H "Accept: application/vnd.github+json" \
        -H "Authorization: Bearer ${GITHUB_PAT}" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "${GITHUB_API_URL:-https://api.github.com}${path}"
}
