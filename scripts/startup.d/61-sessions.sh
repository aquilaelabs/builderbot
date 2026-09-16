#!/usr/bin/env bash
#
# Put back the terminal sessions the last shutdown saved.
#
# A terminal in the dashboard is a tmux session, and tmux dies with the
# container — so without this, restarting means every terminal you had open is
# gone, including the ones you had minimized out of the tab strip. The shutdown
# writes each session's directory and the last screenful of its scrollback; this
# recreates the session there and prints that scrollback back into it before the
# shell starts, which is the same trick tmux-resurrect uses.
#
# What comes back is the terminal, not what was running in it. A build that was
# halfway through went down with the container; restarting it here would be a
# promise this cannot keep. Claude sessions are not restored at all — the
# conversation ended, and a new session wearing its name would be a lie.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

SESSION_DIR="${DASHBOARD_STATE:-/config}/sessions"
INDEX="$SESSION_DIR/index.json"

[ -f "$INDEX" ] || exit 0
command -v tmux >/dev/null 2>&1 || exit 0
command -v jq   >/dev/null 2>&1 || { warn "sessions: jq missing — not restoring"; exit 0; }

restored=0
while IFS=$'\t' read -r name dir; do
    [ -n "$name" ] || continue
    # Same shape check the writer applied. This file lives on a volume the
    # operator can edit, and the name becomes a tmux target and a filename.
    case "$name" in
        *[!A-Za-z0-9._-]*) continue ;;
    esac
    tmux has-session -t "$name" 2>/dev/null && continue
    [ -d "$dir" ] || dir="$WORKSPACE"

    hist="$SESSION_DIR/${name}.hist"
    if [ -s "$hist" ]; then
        # `cat` then hand the pane to the shell, so the old screen is above the
        # new prompt exactly as it was. exec so there is no extra shell between
        # the session and the one you type into.
        tmux new-session -d -s "$name" -c "$dir" \
            "cat -- $(printf '%q' "$hist"); exec ${SHELL:-/bin/bash} -l" 2>/dev/null || continue
    else
        tmux new-session -d -s "$name" -c "$dir" 2>/dev/null || continue
    fi
    # Shells select-to-copy, which means tmux must not own the mouse. bb-tty
    # sets this too; a session restored before anyone connects needs it now.
    tmux set-option -t "$name" mouse off 2>/dev/null || true
    restored=$((restored + 1))
done < <(jq -r '.[]? | "\(.name)\t\(.cwd)"' "$INDEX" 2>/dev/null || true)

if [ "$restored" -gt 0 ]; then
    tmux unbind-key -n MouseDown3Pane 2>/dev/null || true
    log "sessions: restored ${restored} terminal$([ "$restored" = 1 ] || echo s) from the last run"
fi
