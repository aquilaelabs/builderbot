#!/usr/bin/env bash
#
# PID 1 payload (running as `builder`).
#
# Keeps the container alive as a long-lived Claude Code workstation, and — when
# ENABLE_RUNNER is true — supervises the GitHub Actions runner alongside it.
#
set -euo pipefail

# shellcheck source=lib/common.sh
. /opt/builderbot/scripts/lib/common.sh

RUNNER_PID=""

shutdown() {
    log "shutdown requested"
    if [ -n "$RUNNER_PID" ] && kill -0 "$RUNNER_PID" 2>/dev/null; then
        log "stopping GitHub Actions runner (pid ${RUNNER_PID})"
        kill -TERM "$RUNNER_PID" 2>/dev/null || true
        # Give the runner time to finish its job and deregister itself.
        local waited=0 limit="${RUNNER_SHUTDOWN_TIMEOUT:-120}"
        while kill -0 "$RUNNER_PID" 2>/dev/null && [ "$waited" -lt "$limit" ]; do
            sleep 1
            waited=$((waited + 1))
        done
        kill -KILL "$RUNNER_PID" 2>/dev/null || true
    fi
    log "bye"
    exit 0
}
trap shutdown TERM INT

if is_true "${ENABLE_RUNNER:-true}"; then
    log "GitHub Actions runner: enabled"
    /opt/builderbot/scripts/runner.sh &
    RUNNER_PID=$!
else
    log "GitHub Actions runner: disabled (ENABLE_RUNNER=${ENABLE_RUNNER:-})"
fi

cat <<EOF
[builderbot] ready.

  Open a Claude Code session:
      docker exec -it ${HOSTNAME} claude
  Or a plain shell:
      docker exec -it ${HOSTNAME} bash -l

  Projects are mounted under ${WORKSPACE}:
$(find "$WORKSPACE" -maxdepth 1 -mindepth 1 -type d -not -name '_work' -printf '      %p\n' 2>/dev/null || true)
EOF

# Stay in the foreground. If the runner is supervised, exiting when it dies for
# good would take the workstation down with it, so we just idle and let the
# runner script handle its own restarts.
while :; do
    if [ -n "$RUNNER_PID" ] && ! kill -0 "$RUNNER_PID" 2>/dev/null; then
        wait "$RUNNER_PID" 2>/dev/null || true
        warn "runner supervisor exited; container stays up as a workstation"
        RUNNER_PID=""
    fi
    sleep 5 &
    wait $! 2>/dev/null || true
done
