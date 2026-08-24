#!/usr/bin/env bash
#
# An X display for the GPU, so the Android emulator can render on it.
#
# The emulator's `-gpu host` needs GLES from the host's driver, and NVIDIA's
# EGL will not hand out a display without an X server carrying its own GLX
# module. That is the whole obstacle: the card is otherwise perfectly usable
# here — the Vulkan loader finds it, and the emulator itself picks it for
# Vulkan before failing at "Failed to get EGL display" and giving up on GLES.
#
# Xvfb does not solve it and it is worth writing down why, because it is the
# obvious thing to try: Xvfb is a software framebuffer server with no NVIDIA
# GLX, so EGL falls through to Mesa, which has no driver for an NVIDIA card
# and lands on llvmpipe. That is software rendering by a slower road than the
# emulator's own SwiftShader.
#
# So: a real Xorg, on the injected nvidia_drv.so, with no monitor attached.
# It has to start here rather than from `bb emu start`, because a session runs
# as an unprivileged user with no capabilities at all and cannot become DRM
# master or open a VT. This hook runs as root at boot, which can.
#
# Everything below is best-effort. A box with no GPU, no X server, or a driver
# that refuses skips it silently, and `bb emu start` falls back to software on
# its own — the emulator working slowly is not worth a boot failure.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

is_true "${ENABLE_GPU_DISPLAY:-true}" || exit 0
command -v Xorg >/dev/null 2>&1 || exit 0
command -v nvidia-smi >/dev/null 2>&1 || exit 0

# The X module the runtime injects only when NVIDIA_DRIVER_CAPABILITIES asks
# for `display`. Without it Xorg would start on some other driver and hand the
# emulator a software context, which is worse than not starting at all —
# because it would look like it worked.
glx="$(find /usr/lib /usr/lib64 -maxdepth 5 -name libglxserver_nvidia.so 2>/dev/null | head -1)"
drv="$(find /usr/lib /usr/lib64 -maxdepth 5 -name nvidia_drv.so 2>/dev/null | head -1)"
if [ -z "$glx" ] || [ -z "$drv" ]; then
    log "gpu display: no nvidia X modules injected — set NVIDIA_DRIVER_CAPABILITIES=all to include 'display'"
    exit 0
fi

# Already up (a dashboard restart re-runs the hooks; the server is not ours to
# duplicate).
[ -S /tmp/.X11-unix/X0 ] && exit 0

# Xorg needs the card's PCI address in its own notation: nvidia-smi gives
# 00000000:01:00.0, the config wants PCI:1:0:0.
bus="$(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader 2>/dev/null | head -1 || true)"
if [ -z "$bus" ]; then
    log "gpu display: nvidia-smi reported no GPU — skipping"
    exit 0
fi
bus="${bus#0000}"; bus="${bus#:}"
IFS=':.' read -r b d f <<< "$bus"
busid="PCI:$((16#${b:-0})):$((16#${d:-0})):$((16#${f:-0}))"

# The module path matters: the injected server module is not where Debian's
# Xorg looks by default, so the search path is told about it explicitly.
moddir="$(dirname "$(dirname "$glx")")"
mkdir -p /etc/X11
cat > /etc/X11/xorg.conf <<EOF
# Written at boot by 48-gpu-display.root.sh. Headless by design: no monitor is
# attached, and the only client is the Android emulator asking EGL for a
# display it can render into.
Section "ServerFlags"
    Option "AutoAddDevices" "false"
    Option "AutoAddGPU"     "false"
EndSection

Section "Files"
    ModulePath "${moddir}"
    ModulePath "/usr/lib/xorg/modules"
EndSection

Section "Device"
    Identifier "nvidia"
    Driver     "nvidia"
    BusID      "${busid}"
    # No display is connected, so the driver is told to come up anyway and to
    # allocate a virtual screen rather than probing for a monitor.
    Option     "AllowEmptyInitialConfiguration" "true"
    Option     "UseDisplayDevice" "none"
EndSection

Section "Screen"
    Identifier "screen"
    Device     "nvidia"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
        Virtual 1920 1080
    EndSubSection
EndSection
EOF

log "gpu display: starting Xorg on :0 for ${busid} (headless, for -gpu host)"
# -noreset so a client disconnecting does not tear the server down; no TCP,
# because the only clients are in this container.
nohup Xorg :0 -noreset -nolisten tcp > /var/log/xorg-builderbot.log 2>&1 &

# Bounded: a driver that refuses should not hold the boot open. Two seconds is
# generous for a server with no devices to probe.
for _ in $(seq 1 20); do
    [ -S /tmp/.X11-unix/X0 ] && break
    sleep 0.5
done
if [ -S /tmp/.X11-unix/X0 ]; then
    # World-writable so the unprivileged session can connect; there is one
    # user in this container and the socket is not reachable from outside it.
    chmod 1777 /tmp/.X11-unix 2>/dev/null || true
    log "gpu display: X is up on :0 — bb emu start will use -gpu host if EGL agrees"
else
    warn "gpu display: Xorg did not come up (see /var/log/xorg-builderbot.log) — the emulator will use software rendering"
fi
