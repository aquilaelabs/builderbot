#!/usr/bin/env bash
#
# Mark the container's own directories inside the projects share so the
# dashboard stops calling them projects.
#
# The projects folder is mounted whole, so anything an operator puts under it
# becomes a project, including paths this container asked them to create.
# The toolchain store is the one that bites: put inside the projects folder
# (the store at /mnt/user/projects/SDK with the projects at
# /mnt/user/projects), the same directory is both /sdk and /workspace/SDK and
# the Projects card lists it as a repository with nothing in it.
#
# The marker is a plain hidden file, `.bbignore`, and its meaning is exactly
# "not a project". Anyone can create one by hand for a directory they would
# rather not see; this hook only makes sure the container's own paths carry
# one without anybody having to know that.
#
# It hides. It does not block: excluding a project is the control that stops
# sessions starting there, and it is enforced in bb-tty because a rule only
# the UI honors is a suggestion. This is housekeeping, not a boundary.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

MARKER=".bbignore"

# mark DIR WHY: drop the marker, explaining itself to whoever finds it.
mark() {
    local dir="$1" why="$2"
    [ -d "$dir" ] || return 0
    # Only inside the projects share: a marker anywhere else would be litter
    # in a directory nothing lists.
    case "$dir" in "$WORKSPACE"/*) ;; *) return 0 ;; esac
    [ -e "$dir/$MARKER" ] && return 0
    if cat > "$dir/$MARKER" <<EOF 2>/dev/null
# BuilderBot: this directory is ${why}, not a project.
#
# The file's existence is the whole signal: the dashboard skips any
# directory under the projects share that holds one. Delete it to have this
# directory listed as a project again; create one anywhere else you would
# rather the Projects card left alone.
EOF
    then
        log "not-a-project: marked ${dir#"$WORKSPACE"/} (${why})"
    else
        warn "could not write ${dir}/${MARKER}; it will be listed as a project"
    fi
}

# The paths this container is responsible for. Both are only inside the
# projects share when the operator put them there, which the mark() guard
# checks rather than assumes.
mark "$(sdk_store_root)" "the toolchain store"
