#!/usr/bin/env bash
# Healthy = the supervisor is alive and `claude` is on PATH. When the runner is
# enabled we also want its process present.
set -uo pipefail

. /opt/builderbot/scripts/lib/common.sh

pgrep -f 'supervisor\.sh' >/dev/null || { echo "supervisor not running"; exit 1; }

command -v claude >/dev/null 2>&1 || {
    su builder -c 'command -v claude' >/dev/null 2>&1 || { echo "claude not on PATH"; exit 1; }
}

if is_true "${ENABLE_RUNNER:-true}" && [ -n "${GITHUB_URL:-}" ]; then
    pgrep -f 'runner\.sh' >/dev/null || { echo "runner supervisor not running"; exit 1; }
fi

echo "ok"
