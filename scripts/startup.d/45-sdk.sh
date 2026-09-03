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

# Not $ROOT/env.sh: the SDK root is a share the sandbox mounts too, at its
# own path, and every line generated here is absolute — so a copy in the
# store is wrong for whichever machine did not write it last. Container-local
# instead; sdk.sh's sdk_env_file() is the same answer, one generator.
ENV_FILE="$(run_as_builder bash -c '. /opt/builderbot/scripts/lib/common.sh; sdk_env_file')"
mkdir -p "$(dirname "$ENV_FILE")" 2>/dev/null || true
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
# Rewritten rather than merely added, which the comment above always claimed
# and the code never did: it only ever appended when the marker was absent,
# so a bashrc written before the file moved went on sourcing the old path
# forever. Anchored on the marker, so the line after it is replaced.
if [ -f "$BASHRC" ]; then
    if grep -qF "$MARK" "$BASHRC"; then
        awk -v mark="$MARK" -v f="$ENV_FILE" '
            # The line after the marker is ours to replace — but only if it
            # looks like ours, so a hand edit under the marker is kept rather
            # than silently eaten.
            skip { skip = 0; if (index($0, "env.sh")) next }
            { print }
            $0 == mark { printf "[ -f \"%s\" ] && . \"%s\"\n", f, f; skip = 1 }
        ' "$BASHRC" > "$BASHRC.new" && mv -f "$BASHRC.new" "$BASHRC"
    else
        printf '\n%s\n[ -f "%s" ] && . "%s"\n' "$MARK" "$ENV_FILE" "$ENV_FILE" >> "$BASHRC"
    fi
    log "sdk: shells will source ${ENV_FILE}"
fi
# The copy that used to live in the shared store, taken back out of it — it
# is wrong for every machine but the last one to write it, and nothing reads
# it now.
[ -f "$ROOT/env.sh" ] && rm -f "$ROOT/env.sh" && log "sdk: removed env.sh from the shared store"

if [ -s "$ENV_FILE" ] && [ "$(grep -c '^export' "$ENV_FILE" || true)" -gt 0 ]; then
    log "sdk: $(grep -c '^export' "$ENV_FILE") toolchain path(s) from ${ROOT}"
fi
