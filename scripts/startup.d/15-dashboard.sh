#!/usr/bin/env bash
#
# Web dashboard: the page, its API and the browser terminals, all on
# DASHBOARD_PORT. The terminals are BuilderBot's own (R133), websockets on
# that port, so there is one port and one sign-in.
#
# Numbered 15 so it starts BEFORE the slow hooks rather than after them. It
# needs nothing they produce (tmux and python are in the image), and it
# used to run second-to-last, which meant the whole boot was time the operator
# spent looking at a browser that would not connect. Measured on this box: a
# container start to the last hook finishing is about fifty seconds, and the
# Claude Code update at hook 20 and any project's own setup.sh at hook 40 are
# both ahead of where this used to sit.
#
# What that costs is a few seconds of a dashboard that does not know everything
# yet: the toolchain store is listed as a project until hook 41 marks it, git columns
# are blank until 30, and Claude's version is unknown until 20. Every one of
# those is a poll away from correcting itself, and none of them is worth the
# whole page for.
#
# 61-sessions.sh restores saved terminals into this one's tmux and deliberately
# does NOT move with it: a restored Claude session starting before hook 30 has
# no ssh agent yet, so its first push would fail for a reason that has nothing
# to do with the session. The dashboard being up early costs nothing; sessions
# being up early costs that.
#
# No credential is needed to START it. A container with no accounts serves
# the first-run screen and nothing else until somebody claims it, which is
# what the old DASHBOARD_AUTH gate was protecting, and that gate outlived
# the variable it read: with DASHBOARD_AUTH gone from the template, its
# unguarded expansion below killed this hook under set -u, and an updated
# container came up with no dashboard at all (bug #55). The variable is read
# by nothing here any more; bb still honors one passed for a single command.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

# No switch. This IS the controller: nodes dial into its API, so without it
# there are no nodes, and compiling, testing, CI and emulation all run on one.
# It is also what starts a session with its guardrails: bb-tty writes the
# settings file that walls a session into its project and injects the roadmap
# and the bug tracker, so `docker exec claude` without this is a session with
# no scope and no context.

PORT="${DASHBOARD_PORT:-7680}"
DASH=/opt/builderbot/scripts/dashboard

if [ ! -s "${DASHBOARD_STATE:-/config}/users.json" ]; then
    log "dashboard: no accounts yet; the first page it serves asks you to make the owner. Do it now."
fi

command -v tmux >/dev/null 2>&1 \
    || { warn "tmux is missing from this image; dashboard NOT started."; exit 0; }

# tmux keeps sessions alive across browser disconnects, which is the only
# reason a closed tab does not kill a Claude session mid-turn.
#
# Our settings live in their own file, which we own and overwrite; ~/.tmux.conf
# merely sources it, and is created only if absent. The home directory is a
# persistent volume, so writing ~/.tmux.conf directly meant reverting the
# user's own tmux config on every container start.
cp -f /opt/builderbot/scripts/lib/tmux.conf "$HOME/.tmux.builderbot.conf"

if [ ! -e "$HOME/.tmux.conf" ]; then
    printf 'source-file ~/.tmux.builderbot.conf\n' > "$HOME/.tmux.conf"
elif ! grep -qF 'tmux.builderbot.conf' "$HOME/.tmux.conf"; then
    # The operator's own file is left alone.
    log "dashboard: keeping your ~/.tmux.conf: add 'source-file ~/.tmux.builderbot.conf' to it for the defaults"
fi

# One port to publish: the terminals are websockets on it (/termws).
log "dashboard: http://<host>:${PORT}"

# Started only where nothing listens yet: the supervisor runs this hook again
# when the dashboard has died (B282).
listening() { ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$1\$"; }

# Without the shielded secrets: the hooks run with them, and the dashboard
# and every controller terminal it opens would carry them (B389).
unset_args=()
for v in ${BB_SHIELDED:-}; do unset_args+=(-u "$v"); done

# Through log-split rather than straight into the file: the full stream stays
# where it was, and the warnings are copied to this hook's own stdout, which is
# the container's, and therefore the boot log. That is what makes the session
# log carry what went wrong AFTER the hooks finished, which it never did.
#
# -u so a warning is in the file at the moment it happens rather than when a
# 8kB buffer fills, which for a mostly-idle server can be hours.
listening "$PORT" || \
nohup env "${unset_args[@]}" DASHBOARD_PORT="$PORT" \
        python3 -u "$DASH/server.py" 2>&1 \
    | /opt/builderbot/scripts/lib/log-split.sh "$(bb_log_dir)/dashboard.log" dashboard &

# It is not supervised: a dashboard that dies should not take the workstation
# with it, and the container is useful without it. `bb logs` names the files.
