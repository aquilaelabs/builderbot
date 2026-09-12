#!/usr/bin/env bash
#
# PID 1 payload (running as `builder`).
#
# Keeps the container alive and owns the graceful shutdown below. Neither CI
# nor a Claude session runs here any more — every runner is on a node
# (docs/nodes.md phase 7) and so is every session (R47) — so what a stop has
# to be careful with is the terminals and the emulator.
#
set -euo pipefail

# shellcheck source=lib/common.sh
. /opt/builderbot/scripts/lib/common.sh

RUNNER_PID=""

# ---------------------------------------------------------------------------
# Graceful shutdown
#
# `docker stop` gives us SIGTERM and then SIGKILL after a timeout. Unraid always
# passes that timeout explicitly — DockerClient.php stops a container with
# `/containers/<id>/stop?t=` DOCKER_TIMEOUT, default **10** — so the container's
# own --stop-timeout is ignored and ten seconds is all we get out of the box.
#
# Everything here is therefore ordered by value-per-second, not by tidiness:
# record state first because it costs milliseconds, signal everything next
# because signaling is instant, and only then wait. Whatever we are killed
# part-way through, the earlier steps already happened.
# ---------------------------------------------------------------------------

# Save the terminal sessions so the next boot can put them back.
#
# What is saved is the shell, not what was running in it: the directory it was
# in and what had been printed there. Processes go down with the container —
# that is what a restart is — and pretending otherwise by restarting them would
# be a different and much worse promise.
#
# Claude sessions are deliberately not saved. A conversation ended with the
# container; recreating its terminal would produce a new session wearing the old
# one's name, which is exactly the confusion the tab pruning already avoids.
SESSION_DIR="${DASHBOARD_STATE:-/config}/sessions"
# A constant, not a setting (roadmap R29): nobody had a reason to change it,
# and a variable that nobody changes is five places to keep in step.
SESSION_LINES=2000

save_sessions() {
    local name dir first=1 out="$SESSION_DIR/index.json"
    mkdir -p "$SESSION_DIR" 2>/dev/null || return 0
    # Anything from a previous boot that is not saved again below is stale.
    rm -f "$SESSION_DIR"/*.hist 2>/dev/null || true
    {
        printf '['
        while read -r name dir; do
            [ -n "$name" ] || continue
            # Neither a Claude conversation nor a sign-in flow is a workspace
            # to put back, and neither runs here any longer — the filter stays
            # because a name from an older boot may still be in this tmux.
            case "$name" in claude-*|login) continue ;; esac
            # The names bb-tty makes are all of this shape; anything else is not
            # ours to write into a filename.
            case "$name" in *[!A-Za-z0-9._-]*) continue ;; esac
            [ -d "$dir" ] || dir="$WORKSPACE"
            # -e keeps the colors, so a restored terminal looks like the one
            # that was there rather than a flat transcript of it.
            tmux capture-pane -p -e -S "-${SESSION_LINES}" -t "$name" \
                > "$SESSION_DIR/${name}.hist" 2>/dev/null || true
            [ "$first" -eq 1 ] || printf ','
            first=0
            printf '\n  {"name": "%s", "cwd": "%s"}' "$name" "$dir"
        done < <(tmux list-panes -a -F '#{session_name} #{pane_current_path}' 2>/dev/null \
                 | sort -u -k1,1 || true)
        [ "$first" -eq 1 ] || printf '\n'
        printf ']\n'
    } > "$out.tmp" 2>/dev/null && mv -f "$out.tmp" "$out" 2>/dev/null || true
    log "shutdown: saved $(grep -c '"name"' "$out" 2>/dev/null || echo 0) terminal sessions"
}

# The emulator launcher execs qemu; either form means an AVD is live and would
# be left dirty by a hard kill. Deliberately not `adb devices`, which starts an
# adb server of its own if none is running.
emulator_running() { pgrep -f 'qemu-system|/emulator/emulator|emulator64' >/dev/null 2>&1; }

shutdown() {
    trap '' TERM INT                 # a second stop must not re-enter this
    # 90s, a constant (R29): Unraid's own stop timeout is the number that
    # actually decides how long a stop gets, and that lives on the host.
    local t0 waited grace=90
    t0=$(date +%s)
    log "shutdown: stopping cleanly (up to ${grace}s; Unraid's DOCKER_TIMEOUT may cut this short)"

    # --- instant work, before anything can time us out ---------------------
    save_sessions
    pkill -TERM -x ttyd 2>/dev/null || true
    pkill -TERM -f 'dashboard/server\.py' 2>/dev/null || true

    # --- signal the slow thing ---------------------------------------------
    # A killed emulator leaves the AVD dirty and costs a cold boot next time.
    if emulator_running; then
        log "shutdown: asking the emulator to power off"
        ( bb emu stop >/dev/null 2>&1 || true ) &
    fi

    # --- and wait for it ---------------------------------------------------
    while :; do
        waited=$(( $(date +%s) - t0 ))
        if [ "$waited" -ge "$grace" ]; then
            warn "shutdown: ${grace}s budget spent; forcing the rest"
            break
        fi
        if ! emulator_running; then
            log "shutdown: everything stopped cleanly after ${waited}s"
            break
        fi
        sleep 1
    done

    [ -n "$RUNNER_PID" ] && kill -KILL "$RUNNER_PID" 2>/dev/null || true
    # Last, because it takes the terminals with it — including any this ran in.
    tmux kill-server 2>/dev/null || true
    log "bye"
    exit 0
}
trap shutdown TERM INT

# The container NAME is what `docker exec` needs, and it is not the hostname —
# Unraid names the container BuilderBot while the hostname is builderbot, and
# docker matches names case-sensitively. Unraid exports HOST_CONTAINERNAME;
# fall back to the hostname elsewhere.
CONTAINER_NAME="${HOST_CONTAINERNAME:-${HOSTNAME}}"

cat <<EOF
[builderbot] ready.

  A Claude session runs on its project's node, opened from the dashboard.
  A shell as the builder user:
      docker exec -it ${CONTAINER_NAME} bb shell

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
