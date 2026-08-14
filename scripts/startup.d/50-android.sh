#!/usr/bin/env bash
#
# Android: report the SDK, and create the default AVD when the emulator is
# enabled. AVDs live in ~/.android on the persistent home volume, so this is
# a one-time cost.
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

AVD_NAME="${ANDROID_AVD_NAME:-builderbot}"

if avdmanager list avd 2>/dev/null | grep -q "Name: ${AVD_NAME}$"; then
    log "AVD '${AVD_NAME}' already exists"
    exit 0
fi

# Use whatever system image the build baked in.
sys_image="$(sdkmanager --list_installed 2>/dev/null \
    | awk '$1 ~ /^system-images;/ {print $1; exit}')"
if [ -z "$sys_image" ]; then
    warn "no system image installed — cannot create an AVD"
    exit 0
fi

log "creating AVD '${AVD_NAME}' from ${sys_image}"
if echo no | avdmanager create avd -n "$AVD_NAME" -k "$sys_image" --device pixel_7 >/dev/null; then
    log "AVD ready — start it with: bb emu start"
else
    warn "AVD creation failed"
fi
