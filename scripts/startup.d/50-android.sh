#!/usr/bin/env bash
#
# Android: report the SDK, then make sure every API level in
# ANDROID_SYSTEM_IMAGES has a system image, a matching platform, and an AVD.
#
# The entrypoint symlinks system-images/ and platforms/ onto the home volume,
# so each level is downloaded once and survives image updates. Without that
# this hook would re-fetch gigabytes on every rebuild.
#
# The emulator is started on demand with `bb emu start`, never automatically —
# it holds a few GB of RAM.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

command -v sdkmanager >/dev/null 2>&1 || exit 0

log "android sdk: ${ANDROID_HOME:-?}"

is_true "${ENABLE_ANDROID_EMULATOR:-false}" || exit 0

if ! command -v emulator >/dev/null 2>&1; then
    warn "ENABLE_ANDROID_EMULATOR=true but this image was built without the emulator"
    exit 0
fi

if [ ! -e /dev/kvm ]; then
    warn "/dev/kvm is not mapped into the container — the emulator will be unusably slow."
    warn "Add '--device=/dev/kvm' (template Extra Params) or the devices: block (compose)."
fi

VARIANT="${ANDROID_SYSTEM_IMAGE_VARIANT:-google_apis;x86_64}"
VARIANT_PATH="$(printf '%s' "$VARIANT" | tr ';' '/')"
PREFIX="${ANDROID_AVD_PREFIX:-builderbot}"

# The fallback tracks the platform the image shipped (ANDROID_DEFAULT_API is
# baked at build time from ANDROID_PLATFORM), so an unset variable means "the
# level that is already here" rather than a hardcoded number that goes stale.
for api in $(printf '%s' "${ANDROID_SYSTEM_IMAGES:-${ANDROID_DEFAULT_API:-36}}" | tr ',' ' '); do
    case "$api" in
        ''|*[!0-9]*)
            warn "ANDROID_SYSTEM_IMAGES: '${api}' is not an API level — skipping"
            continue ;;
    esac

    pkg="system-images;android-${api};${VARIANT}"
    avd="${PREFIX}-${api}"

    if [ ! -d "${ANDROID_HOME}/system-images/android-${api}/${VARIANT_PATH}" ]; then
        log "installing ${pkg} — a couple of GB, downloaded once and kept on the home volume"
        if ! sdkmanager --install "$pkg" >/dev/null 2>&1; then
            warn "could not install ${pkg} — check that API ${api} ships a '${VARIANT}' image"
            continue
        fi
    fi

    # Cheap next to the system image, and you generally want to compile against
    # a level you are emulating.
    if [ ! -d "${ANDROID_HOME}/platforms/android-${api}" ]; then
        sdkmanager --install "platforms;android-${api}" >/dev/null 2>&1 \
            || warn "could not install platforms;android-${api}"
    fi

    if avdmanager list avd 2>/dev/null | grep -q "Name: ${avd}$"; then
        log "AVD '${avd}' already exists"
        continue
    fi

    log "creating AVD '${avd}' from ${pkg}"
    if echo no | avdmanager create avd -n "$avd" -k "$pkg" --device pixel_7 >/dev/null; then
        log "AVD ready — start it with: bb emu start ${api}"
    else
        warn "AVD creation failed for ${avd}"
    fi
done
