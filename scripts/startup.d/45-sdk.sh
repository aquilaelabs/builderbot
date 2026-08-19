#!/usr/bin/env bash
#
# Put whatever `bb sdk install` has put on the SDK share onto every shell's
# PATH.
#
# The toolchains live outside the image on purpose — see `bb sdk` — which
# means the image cannot bake their PATH entries in: what is installed is
# only known at runtime, and changes without a rebuild. So this regenerates
# one small file on every start and makes sure the user's shell reads it.
#
# ~/.bashrc rather than /etc/profile.d: the home volume's copy is the one
# that survives, and a `docker exec bash` is an interactive non-login shell,
# which reads bashrc and never touches profile.d.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

ROOT="$(sdk_root)"
mkdir -p "$ROOT" 2>/dev/null || true
[ -d "$ROOT" ] || exit 0

ENV_FILE="$ROOT/env.sh"
# Written by bb so the file and `bb sdk env` can never disagree — one
# generator, two ways of asking for it.
if run_as_builder bb sdk env > "$ENV_FILE.new" 2>/dev/null; then
    mv -f "$ENV_FILE.new" "$ENV_FILE"
else
    rm -f "$ENV_FILE.new"
fi
chown "$PUID:$PGID" "$ENV_FILE" 2>/dev/null || true

# One source line, added once. Anchored on a marker rather than the path, so
# moving the share rewrites the line instead of adding a second one.
BASHRC="${BUILDER_HOME:-/home/builder}/.bashrc"
MARK='# builderbot:sdk-env'
if [ -f "$BASHRC" ] && ! grep -qF "$MARK" "$BASHRC"; then
    printf '\n%s\n[ -f "%s" ] && . "%s"\n' "$MARK" "$ENV_FILE" "$ENV_FILE" >> "$BASHRC"
    log "sdk: shells will source ${ENV_FILE}"
fi

if [ -s "$ENV_FILE" ] && [ "$(grep -c '^export' "$ENV_FILE" || true)" -gt 0 ]; then
    log "sdk: $(grep -c '^export' "$ENV_FILE") toolchain path(s) from ${ROOT}"
fi
