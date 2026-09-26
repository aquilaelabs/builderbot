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

# The supervisor is a sleep loop, so its being alive said nothing about the
# dashboard, which is what a person reaches: a container whose dashboard had
# died stayed healthy for as long as it ran. Any HTTP answer counts, 401
# included: the question is whether the server is there, not whether this
# check is signed in.
code="$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${DASHBOARD_PORT:-7680}/" 2>/dev/null || true)"
case "$code" in
    2*|3*|401|403) ;;
    *) echo "dashboard not answering on ${DASHBOARD_PORT:-7680} (${code:-no answer})"; exit 1 ;;
esac

echo "ok"
