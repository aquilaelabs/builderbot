#!/usr/bin/env bash
#
# roles: controller node
#
# Put this container's icon into Unraid's own icon cache, so the Docker page
# shows it without ever fetching a URL.
#
# Unraid keeps two copies (emhttp/plugins/dynamix.docker.manager/include/
# DockerClient.php, getIcon):
#
#     RAM   $docroot/state/plugins/dynamix.docker.manager/images/<Name>-icon.png
#     disk  /var/lib/docker/unraid/images/<Name>-icon.png
#
#     if (!is_file($iconRAM)) {
#         if (!is_file($icon)) $this->download_url($imgUrl, $icon);
#         @copy($icon, $iconRAM);
#     }
#
# It downloads only when *both* are missing. The RAM copy is tmpfs and is gone
# after every reboot; the disk copy survives, and is what we write here. So a
# private repo — whose raw.githubusercontent URL answers 404 to Unraid's
# unauthenticated fetch — stops mattering: there is nothing left to fetch.
#
# Two things this cannot paper over:
#
#   - The Icon field in the template must be NON-EMPTY. getIcon returns early
#     on an empty URL and never looks at the cache at all, so an empty <Icon/>
#     gets the question-mark placeholder no matter what is on disk. The value
#     itself is never used while the cache is warm; it only has to be there.
#   - The filename is built from the *container* name, not the image or the
#     hostname, and nothing inside a container can see that. UNRAID_ICON_NAME
#     overrides it if you renamed the container.
#
# Entirely optional: without the mount this exits quietly.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

CACHE="${UNRAID_ICON_DIR:-/unraid-icons}"
SRC="${UNRAID_ICON_SRC:-/opt/builderbot/icon.png}"
NAME="${UNRAID_ICON_NAME:-BuilderBot}"

[ -d "$CACHE" ] || exit 0
[ -f "$SRC" ]   || { warn "icon source $SRC is missing"; exit 0; }

if [ ! -w "$CACHE" ]; then
    warn "$CACHE is mounted read-only — set the mount to rw for the container icon"
    exit 0
fi

DEST="$CACHE/$NAME-icon.png"

# Only write when it would change something. Unraid re-reads this on its own
# schedule and a needless rewrite is a needless write to the docker data root.
if [ -f "$DEST" ] && cmp -s "$SRC" "$DEST"; then
    exit 0
fi

# Same-filesystem temp + rename, so the web UI never sees a half-written PNG.
TMP="$(mktemp "$CACHE/.$NAME-icon.XXXXXX")" || { warn "cannot write to $CACHE"; exit 0; }
trap 'rm -f "$TMP"' EXIT
cp "$SRC" "$TMP"
chmod 0644 "$TMP"
mv -f "$TMP" "$DEST"
trap - EXIT

log "installed the container icon at $DEST"
