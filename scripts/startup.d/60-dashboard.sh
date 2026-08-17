#!/usr/bin/env bash
#
# Web dashboard: a status page on DASHBOARD_PORT and a terminal on
# DASHBOARD_TTYD_PORT.
#
# Off unless ENABLE_DASHBOARD is true, and it refuses to start without
# DASHBOARD_AUTH. That refusal is the point: this serves an interactive shell
# into a container holding a loaded ssh-agent and read-write mounts of every
# project, so an unauthenticated instance on a LAN would hand all of that to
# anyone who can reach the port. Failing loudly beats defaulting to open.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

is_true "${ENABLE_DASHBOARD:-false}" || exit 0

PORT="${DASHBOARD_PORT:-8080}"
TTYD_PORT="${DASHBOARD_TTYD_PORT:-7681}"
# The port the browser must reach, which differs from the one ttyd binds to
# whenever the host publishes it elsewhere. Nothing in here can discover that,
# so it has to be told.
TTYD_PUBLIC_PORT="${DASHBOARD_TTYD_PUBLIC_PORT:-$TTYD_PORT}"
DASH=/opt/builderbot/scripts/dashboard

if [ -z "${DASHBOARD_AUTH:-}" ]; then
    warn "ENABLE_DASHBOARD=true but DASHBOARD_AUTH is empty — dashboard NOT started."
    warn "Set DASHBOARD_AUTH=user:password. It exposes a shell with your ssh keys"
    warn "and every mounted project; it will not run without a credential."
    exit 0
fi
case "$DASHBOARD_AUTH" in
    *:*) ;;
    *) warn "DASHBOARD_AUTH must be user:password — dashboard NOT started."; exit 0 ;;
esac

for bin in ttyd tmux; do
    command -v "$bin" >/dev/null 2>&1 \
        || { warn "${bin} is missing from this image — dashboard NOT started."; exit 0; }
done

# tmux keeps sessions alive across browser disconnects, which is the only
# reason a closed tab does not kill a Claude session mid-turn.
cat > "$HOME/.tmux.conf" <<'EOF'
set -g history-limit 50000
set -g mouse on
set -g status-style bg=colour236,fg=colour252
set -g status-left '#[bold] #S '
set -g status-right ' builderbot '
setw -g aggressive-resize on
EOF

log "dashboard: http://<host>:${PORT}  (terminal on ${TTYD_PUBLIC_PORT})"
if [ "$TTYD_PUBLIC_PORT" != "$TTYD_PORT" ]; then
    log "dashboard: advertising terminal port ${TTYD_PUBLIC_PORT} to browsers (ttyd binds ${TTYD_PORT})"
fi

# --url-arg lets the page choose the session; bb-tty validates it. -W makes the
# terminal writable, which is the entire point, and is why the credential above
# is not optional.
nohup ttyd --port "$TTYD_PORT" --interface 0.0.0.0 \
        --credential "$DASHBOARD_AUTH" \
        --url-arg --writable \
        --max-clients 16 \
        "$DASH/bb-tty" \
    >> "$(bb_log_dir)/ttyd.log" 2>&1 &

nohup env DASHBOARD_PORT="$PORT" DASHBOARD_TTYD_PORT="$TTYD_PORT" \
        DASHBOARD_TTYD_PUBLIC_PORT="$TTYD_PUBLIC_PORT" \
        DASHBOARD_AUTH="$DASHBOARD_AUTH" \
        python3 "$DASH/server.py" \
    >> "$(bb_log_dir)/dashboard.log" 2>&1 &

# Neither is supervised: a dashboard that dies should not take the workstation
# with it, and the container is useful without it. `bb logs` names the files.
