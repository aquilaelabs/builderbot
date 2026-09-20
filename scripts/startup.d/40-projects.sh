#!/usr/bin/env bash
#
# Report on the mounted projects, and put each one's commit identity into its
# repo config. That identity is the project's own setting (prefs.py), so a
# session commits as the person that project belongs to and a repo without one
# says so at the first commit rather than committing as nobody.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

shopt -s nullglob

for dir in "$WORKSPACE"/*/; do
    name="$(basename "$dir")"
    [ "$name" = "_work" ] && continue
    # Same rule the dashboard applies: a directory holding .bbignore is not a
    # project. Two places, one meaning: a log that disagreed with the card
    # would be worse than either.
    [ -e "${dir}.bbignore" ] && continue

    if [ -d "$dir/.git" ]; then
        log "project: ${name} (branch $(git_branch "$dir"))"
    else
        log "project: ${name}"
    fi

    # The identity, from the same file the dashboard writes (claude-prefs.json).
    if [ -d "$dir/.git" ] && [ -r "${DASHBOARD_STATE:-/config}/claude-prefs.json" ] \
            && command -v jq >/dev/null 2>&1; then
        gname="$(jq -r --arg p "$name" '.projects[$p].git_name // empty' \
                 "${DASHBOARD_STATE:-/config}/claude-prefs.json" 2>/dev/null || true)"
        gemail="$(jq -r --arg p "$name" '.projects[$p].git_email // empty' \
                  "${DASHBOARD_STATE:-/config}/claude-prefs.json" 2>/dev/null || true)"
        [ -z "$gname" ]  || git -C "$dir" config user.name  "$gname"  2>/dev/null || true
        [ -z "$gemail" ] || git -C "$dir" config user.email "$gemail" 2>/dev/null || true
    fi
done
