#!/usr/bin/env bash
#
# roles: controller node
#
# Playwright's browsers live on the package store, not in the image.
#
# They are 1.3GB of pure download and /opt is discarded on every image
# update, so baking them in meant re-fetching them weekly forever. The image
# keeps the module and the system libraries — apt packages that have to be
# there — and the bundles come here.
#
# PLAYWRIGHT_BROWSERS_PATH still says /opt/pw-browsers, because everything
# from `bb shot` to the dashboard's tests to the project CLAUDE.md template
# names that path. It is a symlink into the share now; nothing that used it
# has to know.
#
# .root.sh, and not by preference: /opt is root-owned and mode 755, so the
# builder user can write *inside* a directory the image created there but
# cannot create one. The first version of this hook ran as builder, its
# `ln -sfn` into /opt failed, `set -e` took the rest of the hook with it, and
# a container came up with no browsers at all. The download itself still runs
# as builder, so nothing lands owned by root.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

command -v playwright >/dev/null 2>&1 || exit 0
BROWSERS="${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}"
STORE="$(sdk_root)/playwright"

mkdir -p "$STORE" 2>/dev/null || { warn "cannot write ${STORE}; leaving browsers in the image"; exit 0; }
chown "$PUID:$PGID" "$STORE" 2>/dev/null || true

# An image that still ships browsers (or a session that installed some into
# the real directory) is adopted rather than discarded — the bytes are
# already here, and downloading them again to prove a point would be silly.
if [ -d "$BROWSERS" ] && [ ! -L "$BROWSERS" ]; then
    if [ -n "$(ls -A "$BROWSERS" 2>/dev/null)" ] && [ -z "$(ls -A "$STORE" 2>/dev/null)" ]; then
        log "moving playwright browsers onto ${STORE} — once, then updates stop re-downloading them"
        cp -a "$BROWSERS/." "$STORE/" 2>/dev/null || true
    fi
    rm -rf "${BROWSERS:?}"
fi
ln -sfn "$STORE" "$BROWSERS"

# A stable path to Chromium: the revisioned directory changes with every
# Playwright release, and the CLAUDE.md template has long told sessions to
# launch with executablePath /opt/pw-browsers/chromium.
relink_chromium() {
    local exe
    exe="$(find -L "$STORE" -path '*/chromium-*/chrome-linux*/chrome' -type f 2>/dev/null | head -1)"
    [ -n "$exe" ] && ln -sfn "$exe" "$STORE/chromium"
}

# First boot on an empty share: fetch them. Synchronous and loud, like the
# Android baseline — it happens once per share, and a container that comes up
# "ready" while `bb shot` cannot work would be worse than a slow start.
#
# Unless they were removed on purpose. A fresh share and one somebody just
# cleared look exactly alike from here, so without the marker an uninstall
# lasted until the next restart and no further — which is not an uninstall.
if [ -e "$(sdk_removed_marker playwright)" ]; then
    log "playwright browsers: removed by the operator — leaving them out"
    log "  put them back with: bb sdk install playwright"
elif ! find -L "$STORE" -path '*/chrome-linux*/chrome' -type f 2>/dev/null | grep -q .; then
    log "installing playwright browsers into ${STORE} (~1.3GB, once — updates will not re-download them)"
    if run_as_builder env PLAYWRIGHT_BROWSERS_PATH="$STORE" \
           playwright install chromium firefox webkit >/dev/null 2>&1; then
        log "playwright browsers ready"
    else
        warn "could not install the playwright browsers — bb shot and the dashboard"
        warn "tests will not work until: bb sdk install playwright"
    fi
fi

relink_chromium
chown -R "$PUID:$PGID" "$STORE" 2>/dev/null || true
chmod -R a+rwX "$STORE" 2>/dev/null || true
