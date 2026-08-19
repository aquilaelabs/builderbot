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

# Which Claude conversations were live, and which transcript each was writing.
# The transcripts survive on their own; this records that they were *running*,
# so the dashboard can offer to resume the one you were actually in rather than
# merely the most recently touched.
record_sessions() {
    local out="${DASHBOARD_STATE:-/config}/last-sessions.json"
    local sess proj dir latest first=1
    mkdir -p "$(dirname "$out")" 2>/dev/null || return 0
    {
        printf '{\n  "stopped_at": %s,\n  "sessions": {' "$(date +%s)"
        while read -r sess; do
            [ -n "$sess" ] || continue
            proj="${sess#claude-}"
            dir="$WORKSPACE/$proj"
            latest="$(ls -1t "$HOME/.claude/projects/${dir//\//-}"/*.jsonl 2>/dev/null | head -1 || true)"
            [ -n "$latest" ] || continue
            latest="$(basename "$latest" .jsonl)"
            [ "$first" -eq 1 ] || printf ','
            first=0
            printf '\n    "%s": "%s"' "$proj" "$latest"
        done < <(tmux list-sessions -F '#{session_name}' 2>/dev/null | grep '^claude-' || true)
        [ "$first" -eq 1 ] || printf '\n  '
        printf '}\n}\n'
    } > "$out.tmp" 2>/dev/null && mv -f "$out.tmp" "$out" 2>/dev/null || true
}

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
SESSION_LINES="${BB_SESSION_HISTORY:-2000}"

save_sessions() {
    local name dir first=1 out="$SESSION_DIR/index.json"
    mkdir -p "$SESSION_DIR" 2>/dev/null || return 0
    # Anything from a previous boot that is not saved again below is stale.
    rm -f "$SESSION_DIR"/*.hist 2>/dev/null || true
    {
        printf '['
        while read -r name dir; do
            [ -n "$name" ] || continue
            case "$name" in claude-*) continue ;; esac
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

# The pids each Claude pane is running. tmux reports the pane's pid, which for
# these sessions is claude itself — it was the session's command.
claude_pids() {
    tmux list-panes -a -F '#{session_name} #{pane_pid}' 2>/dev/null \
        | awk '/^claude-/ {print $2}' || true
}

# A SIGKILL'd claude still leaves its transcript, which is appended as it goes,
# but a clean exit closes the turn instead of abandoning it mid-write.
signal_claude() {
    local pid
    while read -r pid; do
        [ -n "$pid" ] && kill -TERM "$pid" 2>/dev/null || true
    done < <(claude_pids)
}

claude_running() { [ -n "$(claude_pids)" ]; }

# The emulator launcher execs qemu; either form means an AVD is live and would
# be left dirty by a hard kill. Deliberately not `adb devices`, which starts an
# adb server of its own if none is running.
emulator_running() { pgrep -f 'qemu-system|/emulator/emulator|emulator64' >/dev/null 2>&1; }

shutdown() {
    trap '' TERM INT                 # a second stop must not re-enter this
    local t0 waited grace="${SHUTDOWN_GRACE:-90}"
    t0=$(date +%s)
    log "shutdown: stopping cleanly (up to ${grace}s; Unraid's DOCKER_TIMEOUT may cut this short)"

    # --- instant work, before anything can time us out ---------------------
    record_sessions
    save_sessions
    pkill -TERM -x ttyd 2>/dev/null || true
    pkill -TERM -f 'dashboard/server\.py' 2>/dev/null || true

    # --- signal every slow thing at once -----------------------------------
    signal_claude
    if [ -n "$RUNNER_PID" ] && kill -0 "$RUNNER_PID" 2>/dev/null; then
        log "shutdown: draining the Actions runner so it deregisters"
        kill -TERM "$RUNNER_PID" 2>/dev/null || true
    fi
    # A killed emulator leaves the AVD dirty and costs a cold boot next time.
    if emulator_running; then
        log "shutdown: asking the emulator to power off"
        ( bb emu stop >/dev/null 2>&1 || true ) &
    fi

    # --- now wait on them together, not one after another ------------------
    local runner_up emu_up cl_up
    while :; do
        waited=$(( $(date +%s) - t0 ))
        if [ "$waited" -ge "$grace" ]; then
            warn "shutdown: ${grace}s budget spent; forcing the rest"
            break
        fi
        kill -0 "$RUNNER_PID" 2>/dev/null && runner_up=1 || runner_up=0
        emulator_running && emu_up=1 || emu_up=0
        # Claude gets a shorter leash than the rest: its work is already on
        # disk, so waiting past this only delays the emulator and the runner.
        if [ "$waited" -lt "${SHUTDOWN_CLAUDE_GRACE:-10}" ] && claude_running; then
            cl_up=1
        else
            cl_up=0
        fi
        if [ "$runner_up" -eq 0 ] && [ "$emu_up" -eq 0 ] && [ "$cl_up" -eq 0 ]; then
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

if is_true "${ENABLE_RUNNER:-true}"; then
    log "GitHub Actions runner: enabled"
    /opt/builderbot/scripts/runner.sh &
    RUNNER_PID=$!
else
    log "GitHub Actions runner: disabled (ENABLE_RUNNER=${ENABLE_RUNNER:-})"
fi

# The container NAME is what `docker exec` needs, and it is not the hostname —
# Unraid names the container BuilderBot while the hostname is builderbot, and
# docker matches names case-sensitively. Unraid exports HOST_CONTAINERNAME;
# fall back to the hostname elsewhere.
CONTAINER_NAME="${HOST_CONTAINERNAME:-${HOSTNAME}}"

cat <<EOF
[builderbot] ready.

  Open a Claude Code session:
      docker exec -it ${CONTAINER_NAME} claude
  Or a shell as the builder user:
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
