#!/usr/bin/env bash
#
# roles: node
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

# One writer for the state, so every branch leaves it readable. The reader is
# `bb emu gpu` and `bb doctor` running as the builder account, and a file only
# root can read makes the report they exist to print come out blank.
say_display() {
    printf '%s\n' "$1" > "$GPU_DISPLAY_STATE" 2>/dev/null || return 0
    chmod 0644 "$GPU_DISPLAY_STATE" 2>/dev/null || true
}

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
# duplicate). Probed rather than stat'd: Xorg leaves /tmp/.X11-unix/X0 and
# /tmp/.X0-lock behind when it dies, and neither /tmp nor /run is a mount of
# its own here, so both survive a `docker restart`. A guard that only looked
# for the socket therefore exited here on the boot AFTER a death and left the
# emulator on software — making "restart the container", the operator's first
# and most obvious remedy, the one thing that could not work.
if x_display_up; then
    exit 0
fi
# Nothing is listening, so anything left over is a corpse. It has to go before
# Xorg will start at all: it refuses a display whose lock file is present with
# "Server is already active for display 0".
if [ -e /tmp/.X11-unix/X0 ] || [ -e /tmp/.X0-lock ]; then
    log "gpu display: clearing a dead server's socket and lock on :0"
    rm -f /tmp/.X11-unix/X0 /tmp/.X0-lock
fi

# Xorg needs the card's PCI address in its own notation: nvidia-smi gives
# 00000000:01:00.0, the config wants PCI:1:0:0.
bus="$(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader 2>/dev/null | head -1 || true)"
if [ -z "$bus" ]; then
    log "gpu display: nvidia-smi reported no GPU — skipping"
    exit 0
fi
# Four fields, not three: nvidia-smi's form is domain:bus:device.function
# (00000000:01:00.0). The first version stripped a fixed "0000" prefix, so
# the eight-digit domain survived, the split landed "00.0" in one field, and
# $((16#00.0)) took the whole hook down before Xorg ever started.
IFS=':.' read -r _domain b d f <<< "$bus"
if [ -z "${f:-}" ]; then
    warn "gpu display: could not parse PCI bus id '${bus}' — skipping"
    exit 0
fi
busid="PCI:$((16#${b})):$((16#${d})):$((16#${f}))"

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

# --- keeping it alive, within reason -------------------------------------
# Xorg here has died hours into a boot with no last words in its log: no error,
# no signal, a clean startup and then nothing (bug #17). What made that
# expensive was not the death, it was the silence — the emulator went on
# working, on software, and every timing conclusion drawn afterwards was wrong.
#
# So it is watched, and the watching is bounded. An unbounded respawn against a
# card the host has taken back would be worse than the silence it replaces:
# a loop launching a server that cannot start, forever, with nothing saying so.
# Three restarts, then it stops and SAYS it stopped — `bb emu gpu` and
# `bb doctor` read the state file and report it, which turns a silent drop to
# software into a stated one.
#
# The card is checked before every restart. If nvidia-smi no longer answers,
# the card is gone and there is nothing to restart onto: that is recorded and
# the watch ends immediately rather than spending its three tries proving it.
GPU_DISPLAY_MAX=3

supervise() {
    local tries=0 gone=""
    while sleep 30; do
        x_display_up && continue
        # It is down. A corpse's socket and lock survive here (neither /tmp nor
        # /run is a mount of its own), and Xorg refuses a display whose lock is
        # present, so they go before anything is started.
        if ! nvidia-smi -L >/dev/null 2>&1; then
            gone="the card no longer answers nvidia-smi — the host has taken it back"
            break
        fi
        if [ "$tries" -ge "$GPU_DISPLAY_MAX" ]; then
            gone="Xorg died ${tries} times and was left down; see /var/log/xorg-builderbot.log"
            break
        fi
        tries=$((tries + 1))
        log "gpu display: X on :0 has died — restart ${tries}/${GPU_DISPLAY_MAX}"
        rm -f /tmp/.X11-unix/X0 /tmp/.X0-lock
        nohup Xorg :0 -noreset -nolisten tcp >> /var/log/xorg-builderbot.log 2>&1 &
        # Longer each time: a server dying immediately is a different fault
        # from one dying after hours, and backing off keeps the first from
        # writing a log nobody can read.
        sleep $((tries * 20))
        if x_display_up; then
            chmod 1777 /tmp/.X11-unix 2>/dev/null || true
            say_display "restarted $tries times"
            log "gpu display: X is back on :0"
        fi
    done
    say_display "down: $gone"
    warn "gpu display: ${gone} — the emulator is on software from here (bb emu gpu)"
}

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
    say_display 'up'
    supervise &
else
    # Name the reason rather than pointing at a log. These three cover what
    # actually goes wrong here, and the first is the one to expect after a
    # driver update: NVIDIA's X modules are built against one server ABI, and
    # the distribution's Xorg moves on its own schedule.
    reason=""
    if grep -qiE "module ABI major version.*does not match|ABI.*mismatch" /var/log/xorg-builderbot.log 2>/dev/null; then
        reason="the nvidia X module and this Xorg disagree about the server ABI — the driver is newer or older than the server expects"
    elif grep -qiE "no devices detected|no screens found" /var/log/xorg-builderbot.log 2>/dev/null; then
        reason="Xorg found no device at ${busid} — check the BusID against nvidia-smi"
    elif grep -qiE "permission denied|cannot open /dev/dri" /var/log/xorg-builderbot.log 2>/dev/null; then
        reason="Xorg could not open the DRM device — the container needs /dev/dri passed through"
    fi
    warn "gpu display: Xorg did not come up${reason:+ — $reason}"
    warn "gpu display: the emulator falls back to software rendering; full log in /var/log/xorg-builderbot.log"
    say_display "down: ${reason:-Xorg did not start; see /var/log/xorg-builderbot.log}"
fi
