#!/usr/bin/env bash
# A stand-in cloudflared for the dashboard suite (R176): what the real one
# prints as it registers, then it waits to be stopped. It never dials out.
# The token it was handed is read from the environment, as cloudflared's is,
# and never printed; a token of "die" ends it at once, so a suite can see the
# tunnel come back.
case "$1" in
    --version) echo "cloudflared stub 0.0"; exit 0 ;;
esac
[ -n "${TUNNEL_TOKEN:-}" ] || { echo "no TUNNEL_TOKEN in the environment" >&2; exit 1; }
echo "stub: starting tunnel"
[ "$TUNNEL_TOKEN" != die ] || { echo "stub: dying as asked"; exit 1; }
echo "INF Registered tunnel connection connIndex=0 location=stub"
trap 'echo "stub: stopped"; exit 0' TERM INT
while :; do sleep 1; done
