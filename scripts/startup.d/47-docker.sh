#!/usr/bin/env bash
#
# Say at boot whether the docker daemon is reachable, and which one it is.
#
# The log said nothing about docker at all. Every other capability announces
# itself here — the GPU says whether X came up, the SDK says how many
# toolchains it found, the dashboard prints its URL — and the daemon that the
# dev-instance controls are built on was the one that did not, so "is the
# sandbox up" was a question you could only answer by opening the dashboard or
# running `bb doctor`. The boot log is where you look when something is wrong,
# and a capability that is silent there looks like one that is absent.
#
# Both arrangements answer here, which is the point: a socket proxy on this box
# and a sandbox VM over ssh are the same question with different addresses, and
# the probe names which one it found rather than assuming.
#
# Never fatal. A daemon that is down is a feature that is off, not a container
# that should refuse to start — the dev-instance controls grey out and say why,
# and everything else in here works without it.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

PROBE=/opt/builderbot/scripts/lib/docker-probe.py
DEVAPP=/opt/builderbot/scripts/dashboard/devapp.py
[ -f "$PROBE" ] && [ -f "$DEVAPP" ] || exit 0

# Bounded: available() gives its `docker version` ten seconds, and an ssh
# address spends some of that on the connection. Worth it once at boot, and
# capped so a VM that is switched off costs a moment rather than the start.
while read -r state rest; do
    [ -n "$state" ] || continue
    case "$state" in
        ok)   log "docker: ${rest#docker daemon: } — ready" ;;
        FAIL) warn "docker: ${rest#docker daemon: }" ;;
        warn) warn "docker: $rest" ;;
        # Configured off, or `auto` with nothing answering. Said plainly rather
        # than warned about: it is the shipped default.
        skip) log "docker: ${rest#docker daemon: }" ;;
    esac
done < <(timeout 30 python3 "$PROBE" "$DEVAPP" 2>/dev/null || true)
