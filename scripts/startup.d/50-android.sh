#!/usr/bin/env bash
#
# Android: report the SDK, then make sure every API level in
# ANDROID_SYSTEM_IMAGES has a system image, a matching platform, and an AVD.
#
# The entrypoint symlinks the package directories onto the SDK share, so each
# level is downloaded once and survives image updates. Without that this hook
# would re-fetch gigabytes on every rebuild.
#
# The emulator is started on demand with `bb emu start`, never automatically —
# it holds a few GB of RAM.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

command -v sdkmanager >/dev/null 2>&1 || exit 0

log "android sdk: ${ANDROID_HOME:-?} (packages under $(sdk_root)/android)"

# The image carries only sdkmanager and adb now, so the platform and
# build-tools a project needs are installed here — once, onto the SDK store,
# where the next image update will find them still sitting. A container that
# has them already does nothing at all.
baseline_api="${ANDROID_BASELINE_PLATFORM:-${ANDROID_DEFAULT_API:-36}}"
if [ ! -d "${ANDROID_HOME}/platforms/android-${baseline_api}" ]; then
    log "installing the android ${baseline_api} baseline — downloaded once, kept outside the image"
    sdkmanager --sdk_root="${ANDROID_HOME}" --install "platforms;android-${baseline_api}" >/dev/null 2>&1 \
        || warn "could not install platforms;android-${baseline_api}"
fi
if [ -n "${ANDROID_BASELINE_BUILD_TOOLS:-}" ] \
   && [ ! -d "${ANDROID_HOME}/build-tools/${ANDROID_BASELINE_BUILD_TOOLS}" ]; then
    sdkmanager --sdk_root="${ANDROID_HOME}" --install "build-tools;${ANDROID_BASELINE_BUILD_TOOLS}" >/dev/null 2>&1 \
        || warn "could not install build-tools;${ANDROID_BASELINE_BUILD_TOOLS}"
fi

is_true "${ENABLE_ANDROID_EMULATOR:-false}" || exit 0

# The emulator is 800MB and is no longer in the image either. Fetched on the
# first boot that asks for it, and never again — nor after the operator has
# taken it out, which ENABLE_ANDROID_EMULATOR being true does not override:
# the variable says this container wants an emulator, the marker says a person
# removed this package, and the more specific instruction wins.
if [ -e "$(sdk_removed_marker android:emulator)" ]; then
    warn "the android emulator package was removed by the operator — bb emu will not work"
    warn "  put it back with: bb sdk install android:emulator"
elif ! command -v emulator >/dev/null 2>&1; then
    log "installing the android emulator — 800MB, downloaded once, kept outside the image"
    if ! sdkmanager --sdk_root="${ANDROID_HOME}" --install emulator >/dev/null 2>&1; then
        warn "could not install the emulator package"
        exit 0
    fi
    # sdkmanager replaces the symlink with a real directory for some packages
    # — the emulator among them — which would leave 821MB inside the image
    # layer for the next update to discard. bb puts it back.
    bb sdk relink >/dev/null 2>&1 || true
    hash -r
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

    # Same rule as the emulator above: ANDROID_SYSTEM_IMAGES says this
    # container wants API ${api}, the marker says a person removed that image
    # from the Tools tab, and the more specific instruction wins. Without this
    # a removal from the dashboard is undone by the next restart, several GB
    # at a time and with nothing on screen to say so.
    if [ -e "$(sdk_removed_marker "android:${pkg}")" ]; then
        warn "system image ${pkg} was removed by the operator — not reinstalling it"
        warn "  put it back with: bb sdk install android:${pkg}"
        continue
    fi

    if [ ! -d "${ANDROID_HOME}/system-images/android-${api}/${VARIANT_PATH}" ]; then
        log "installing ${pkg} — a couple of GB, downloaded once and kept on the SDK share"
        if ! sdkmanager --sdk_root="${ANDROID_HOME}" --install "$pkg" >/dev/null 2>&1; then
            warn "could not install ${pkg} — check that API ${api} ships a '${VARIANT}' image"
            continue
        fi
        bb sdk relink >/dev/null 2>&1 || true
    fi

    # Cheap next to the system image, and you generally want to compile against
    # a level you are emulating.
    if [ ! -d "${ANDROID_HOME}/platforms/android-${api}" ]; then
        sdkmanager --sdk_root="${ANDROID_HOME}" --install "platforms;android-${api}" >/dev/null 2>&1 \
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
