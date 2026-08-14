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
