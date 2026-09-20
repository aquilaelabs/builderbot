#!/usr/bin/env bash
# Healthy = the supervisor is alive. Claude is not checked because it is not
# here: this container keeps the dashboard, the notebook and the record, and
# sessions run on a node, which carries its own.
set -uo pipefail

. /opt/builderbot/scripts/lib/common.sh

# Path-anchored, same reason as everywhere else in this repo: a bare
# 'supervisor\.sh' also matches any process that merely mentions the string
# (an editor open on the file, a grep), and a match like that reports a dead
# supervisor as healthy.
pgrep -f '/opt/builderbot/scripts/supervisor\.sh' >/dev/null \
    || { echo "supervisor not running"; exit 1; }

echo "ok"
