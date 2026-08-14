#!/usr/bin/env bash
#
# Register and run the GitHub Actions self-hosted runner.
#
# Configuration comes from the environment:
#   GITHUB_URL          https://github.com/OWNER/REPO  or  https://github.com/ORG
#   GITHUB_PAT          PAT used to mint registration tokens (repo admin scope,
#                       or admin:org for an org-level runner). Optional if you
#                       supply RUNNER_TOKEN yourself.
#   RUNNER_TOKEN        Pre-minted registration token (expires after 1 hour).
#   RUNNER_NAME         Defaults to the container hostname.
#   RUNNER_LABELS       Comma-separated labels.
#   RUNNER_GROUP        Runner group (org-level runners).
#   RUNNER_EPHEMERAL    true (default) = fresh registration per job.
#   RUNNER_WORKDIR      Where jobs check code out.
#
set -euo pipefail

# shellcheck source=lib/common.sh
. /opt/builderbot/scripts/lib/common.sh

RUNNER_NAME="${RUNNER_NAME:-$(hostname)}"
RUNNER_LABELS="${RUNNER_LABELS:-builderbot,self-hosted,linux}"
RUNNER_WORKDIR="${RUNNER_WORKDIR:-$WORKSPACE/_work}"
CURRENT_TOKEN=""

cd "$RUNNER_DIR"

if [ -z "${GITHUB_URL:-}" ]; then
    warn "GITHUB_URL is not set — the runner will not start."
    warn "Set ENABLE_RUNNER=false to silence this, or configure GITHUB_URL + GITHUB_PAT."
    exit 0
fi

if [ -z "${GITHUB_PAT:-}" ] && [ -z "${RUNNER_TOKEN:-}" ]; then
    warn "neither GITHUB_PAT nor RUNNER_TOKEN is set — the runner will not start."
    exit 0
fi

# ---------------------------------------------------------------------------
# Work out whether GITHUB_URL points at a repo or an org, and build the API
# path used for registration/removal tokens.
# ---------------------------------------------------------------------------
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

mint_token() {
    local kind="$1"
    if [ "$kind" = "registration" ] && [ -n "${RUNNER_TOKEN:-}" ]; then
        printf '%s' "$RUNNER_TOKEN"
        return
    fi
    github_api POST "$(scope_path "$kind")" | jq -r .token
}

configure() {
    CURRENT_TOKEN="$(mint_token registration)"
    [ -n "$CURRENT_TOKEN" ] && [ "$CURRENT_TOKEN" != "null" ] \
        || die "failed to obtain a runner registration token"

    local -a args=(
        --unattended
        --replace
        --url "$GITHUB_URL"
        --token "$CURRENT_TOKEN"
        --name "$RUNNER_NAME"
        --labels "$RUNNER_LABELS"
        --work "$RUNNER_WORKDIR"
    )
    [ -n "${RUNNER_GROUP:-}" ] && args+=(--runnergroup "$RUNNER_GROUP")
    is_true "${RUNNER_EPHEMERAL:-true}" && args+=(--ephemeral)

    log "registering runner '${RUNNER_NAME}' with ${GITHUB_URL} [${RUNNER_LABELS}]"
    ./config.sh "${args[@]}"
}

deregister() {
    [ -f "${RUNNER_DIR}/.runner" ] || return 0
    log "deregistering runner '${RUNNER_NAME}'"
    local token
    # A removal token is preferred; fall back to the registration token, which
    # config.sh also accepts.
    token="$(mint_token remove 2>/dev/null || true)"
    if [ -z "$token" ] || [ "$token" = "null" ]; then
        token="$CURRENT_TOKEN"
    fi
    ./config.sh remove --token "$token" >/dev/null 2>&1 \
        || warn "could not deregister cleanly; remove the runner in GitHub settings if it lingers"
}

RUN_PID=""
on_term() {
    log "runner: stop signal received"
    if [ -n "$RUN_PID" ] && kill -0 "$RUN_PID" 2>/dev/null; then
        # run.sh traps SIGTERM and drains the in-flight job before exiting.
        kill -TERM "$RUN_PID" 2>/dev/null || true
        wait "$RUN_PID" 2>/dev/null || true
    fi
    deregister
    exit 0
}
trap on_term TERM INT

mkdir -p "$RUNNER_WORKDIR"

# The runner writes its diagnostic logs to $RUNNER_DIR/_diag, which lives in
# the ephemeral container layer. Point it at the persistent work volume so
# runner crashes can be diagnosed after a container recreation.
mkdir -p "$RUNNER_WORKDIR/_diag"
ln -sfn "$RUNNER_WORKDIR/_diag" "$RUNNER_DIR/_diag"

# Clear any registration left behind by a previous container; the old
# credentials are useless after a restart.
[ -f "${RUNNER_DIR}/.runner" ] && deregister

log "actions-runner $(cat "${RUNNER_DIR}/.runner-version" 2>/dev/null || echo '?')"

while :; do
    configure

    ./run.sh &
    RUN_PID=$!
    wait "$RUN_PID" 2>/dev/null || true
    RUN_PID=""

    if is_true "${RUNNER_EPHEMERAL:-true}"; then
        # An ephemeral runner exits after one job by design — re-register so
        # the next workflow run has somewhere to land.
        log "job finished (ephemeral); re-registering in ${RUNNER_RESTART_DELAY:-5}s"
    else
        warn "runner exited unexpectedly; restarting in ${RUNNER_RESTART_DELAY:-5}s"
    fi
    sleep "${RUNNER_RESTART_DELAY:-5}"
done
