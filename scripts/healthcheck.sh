#!/usr/bin/env bash
# Healthy = the supervisor is alive and `claude` is on PATH. When the runner is
# enabled we also want its process present.
set -uo pipefail

. /opt/builderbot/scripts/lib/common.sh

# Path-anchored, same reason as everywhere else in this repo: a bare
# 'supervisor\.sh' also matches any process that merely mentions the string —
# an editor open on the file, a grep — and a match like that reports a dead
# supervisor as healthy.
pgrep -f '/opt/builderbot/scripts/supervisor\.sh' >/dev/null \
    || { echo "supervisor not running"; exit 1; }

command -v claude >/dev/null 2>&1 || {
    su builder -c 'command -v claude' >/dev/null 2>&1 || { echo "claude not on PATH"; exit 1; }
}

if is_true "${ENABLE_RUNNER:-true}" && [ -n "${GITHUB_URL:-}" ]; then
    pgrep -f '/opt/builderbot/scripts/runner\.sh' >/dev/null \
        || { echo "runner supervisor not running"; exit 1; }
fi

echo "ok"
