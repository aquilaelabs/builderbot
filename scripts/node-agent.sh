#!/usr/bin/env bash
#
# The node role's command: enroll this container with a controller once, then
# run the agent (roadmap #21).
#
# The counterpart of supervisor.sh — where that keeps a controller's services
# up, this keeps one long-lived process going and lets Docker's restart policy
# be the supervisor. A VM node has systemd for that; a container does not need
# it, because `builderbot-agent run` is an ordinary foreground loop.
#
# One image, two roles, so a node is the same template with BUILDERBOT_ROLE=node
# rather than a second thing to keep in step. What differs is only what boots:
# the entrypoint's `# roles:` filter drops the dashboard, the runner, Claude and
# the project hooks, and keeps the SDK, the browsers, the Android packages and
# the GPU display — which is the whole of what a build-and-emulate node needs.
#
# What this deliberately does NOT set up is a Docker daemon. dockerd inside a
# container wants --privileged, which is root on the server, and the sandbox VM
# already does that job with real isolation. Enroll a container node without the
# docker-host capability and placement sends dev instances to the VM by itself.
set -euo pipefail

# Resolved beside this script rather than under /opt, so the checkout's copy
# runs the checkout's agent — which is what the test suite drives, and what
# `bash scripts/node-agent.sh` does when trying a change before an image.
BB_DIR="$(dirname "$(readlink -f "$0")")"
# shellcheck source=lib/common.sh
. "${BB_DIR}/lib/common.sh"

AGENT="${BB_DIR}/agent/builderbot-agent.py"

# Everything the agent keeps has to be on a volume: /etc and /var are image
# layer here and go with the next update, which for a node would mean losing
# its identity and re-enrolling on every pull. /config is mapped by the
# template, so that is where its record and its stores live.
# Paths, not settings. A store you want somewhere else — an NFS export, a
# different disk — is a volume mapped onto these, which is how a container is
# told where its data lives; a variable per store would be the same decision
# taken twice. NODE_STORE_ROOT stays as a seam the test suite drives, not as
# something the template asks about.
NODE_HOME="${NODE_STORE_ROOT:-/config/node}"
export BUILDERBOT_NODE_JSON="${BUILDERBOT_NODE_JSON:-${NODE_HOME}/node.json}"
mkdir -p "$NODE_HOME" "${NODE_HOME}/data" "${NODE_HOME}/cache" "${NODE_HOME}/artifacts"

# The packages store defaults to the package store, which is the arrangement that
# already works: the toolchains a node builds with are the ones `bb sdk` puts
# there, and a node container mapped to the same share as the controller is
# one store under two names — which the controller recognizes by its marker
# file and arbitrates installs across.
PACKAGES="${NODE_PACKAGES_STORE:-${SDK_ROOT:-/sdk}}"

if [ ! -f "$BUILDERBOT_NODE_JSON" ]; then
    if [ -z "${CONTROLLER_URL:-}" ] || [ -z "${NODE_TOKEN:-}" ]; then
        die \
"this container is set to BUILDERBOT_ROLE=node but has nothing to enroll with.
   Set CONTROLLER_URL to the dashboard's address and NODE_TOKEN to a one-time
   enrollment token: the Nodes tab's Enroll node mints one, and it is shown
   once. Tick only the capabilities this node can honor — a container is not
   a docker-host."
    fi
    log "enrolling with ${CONTROLLER_URL} as a node"
    # The token is spent by this one call. If it fails the container exits and
    # Docker restarts it, which retries with the same token — right while the
    # controller was merely unreachable, and harmless once it is burned,
    # because the message then says so rather than half-enrolling.
    python3 "$AGENT" enroll \
        --controller "$CONTROLLER_URL" \
        --token "$NODE_TOKEN" \
        --user "$(id -un)" \
        ${NODE_PIN:+--pin "$NODE_PIN"} \
        --store "data=${NODE_HOME}/data" \
        --store "packages=${PACKAGES}" \
        --store "cache=${NODE_HOME}/cache" \
        --store "artifacts=${NODE_HOME}/artifacts"
    log "enrolled — its record is ${BUILDERBOT_NODE_JSON}"
else
    log "already enrolled (${BUILDERBOT_NODE_JSON}) — CONTROLLER_URL and NODE_TOKEN are ignored"
fi

log "node agent starting"
exec python3 "$AGENT" run
