#!/usr/bin/env python3
"""Timed touches on the running emulator (R101): `bb emu touch`, and $BB_TOUCH
inside a capture's --drive script.

    touch.py tap X Y
    touch.py hold X Y --ms N
    touch.py glide X Y X Y [X Y...] [--hand NAME] [--seed N] [--pre MS] [--hold MS]

Screen pixels, as a screenshot shows them, whichever way the screen is
turned. `adb shell input tap` costs about 300 ms a call and `input swipe`
moves at its own pace, so neither can time a glide across letters or tell a
long-press from a slide: a keyboard session found that out and wrote its
own sendevent script (Shebang-DevBoard, 30 Sep). This one writes the whole
gesture as one `adb shell` of sendevent lines with sleeps between them, so
the device sees the timing the script asked for. --pre holds the finger
still before it starts moving (a long-press that then slides), --hold keeps
it down at the end before lifting. The path between the points is a
hand's (hand.py, R127): curved, eased, overshooting and wobbling the way a
finger moves, `--hand ruler` for the straight even stroke, and hand.py's
dials (--speed, --curve, --shake, --overshoot, --dwell, --ms) to set one.

The touch panel is found with `getevent -p` (the device that reports
ABS_MT_POSITION_X, and its range), the screen's size with `wm size` and its
rotation with dumpsys input, so a landscape tap lands where the screenshot
shows it. BB_CAPTURE_ADB or ADB names adb; BB_TOUCH_DEV names the panel when
the guess is wrong.
"""
import os
import re
import shutil
import subprocess
import sys
import time
from typing import NoReturn

import hand

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_MT_SLOT, ABS_MT_TOUCH_MAJOR, ABS_MT_POSITION_X, ABS_MT_POSITION_Y = 0x2F, 0x30, 0x35, 0x36
ABS_MT_TOOL_TYPE, ABS_MT_TRACKING_ID, ABS_MT_PRESSURE = 0x37, 0x39, 0x3A


def die(msg) -> NoReturn:
    sys.stderr.write(f"[builderbot] ERROR: {msg}\n")
    sys.exit(1)


def adb():
    return os.environ.get("BB_CAPTURE_ADB") or os.environ.get("ADB") or shutil.which("adb") or die(
        "adb is not on this node: bb emu says what the emulator needs")


def shell(a, *words):
    r = subprocess.run([a, "shell", *words], capture_output=True, text=True, timeout=30, check=False)
    return r.stdout or ""


def ensure_root(a):
    """Make the device's adb shell root, which sendevent needs, or say why not.

    A google_apis emulator image is a userdebug build: adbd starts as
    `shell` and `adb root` makes it root until the next cold boot. A quick
    boot restores whatever the snapshot held, so a session that once ran
    `adb root` saw every later boot come up root, and the first cold boot
    (the card arriving changed the GPU mode, 1 Oct) broke this verb with
    "Permission denied" (reports 44 and 45, Shebang-DevBoard). A user build
    (a phone, a Play Store image) has no root to give."""
    uid = shell(a, "id", "-u").strip()
    if uid == "0" or not uid.isdigit():
        return
    if shell(a, "getprop", "ro.debuggable").strip() != "1":
        die("this device's adb shell is not root and its build will not make it so "
            "(a user build: a phone, or a Play Store image), and sendevent needs root; "
            "adb shell input tap and swipe work without it, with adb's own timing")
    sys.stderr.write("[builderbot] adb was not root here: running adb root, as bb emu start does\n")
    subprocess.run([a, "root"], capture_output=True, text=True, timeout=30, check=False)
    subprocess.run([a, "wait-for-device"], capture_output=True, text=True, timeout=60, check=False)
    for _ in range(40):
        if shell(a, "id", "-u").strip() == "0":
            return
        time.sleep(0.5)
    die("adb root did not take: the shell is still not root, and sendevent needs it")


def _order(dev):
    """Devices in the kernel's order, by their number: sorted as text,
    /dev/input/event10 came before event2, and a phone with several
    virtio multi-touch devices got the one the display ignores (report 43,
    Shebang-DevBoard, 30 Sep). The first is the one bound to the display."""
    m = re.search(r"(\d+)$", dev)
    return (int(m.group(1)) if m else 1 << 30, dev)


def panel(a):
    """(device path, x max, y max) of the multi-touch panel: the first one
    reporting ABS_MT_POSITION_X, by device number."""
    want = os.environ.get("BB_TOUCH_DEV", "")
    dev, xs, ys = "", {}, {}
    for line in shell(a, "getevent", "-p").splitlines():
        m = re.match(r"add device \d+: (\S+)", line)
        if m:
            dev = m.group(1)
            continue
        m = re.search(r"\b(0035|0036)\s*:\s*value \d+, min \d+, max (\d+)", line)
        if m and dev:
            (xs if m.group(1) == "0035" else ys)[dev] = int(m.group(2))
    for d in [want] if want else sorted(xs, key=_order):
        if d in xs and d in ys:
            return d, xs[d], ys[d]
    die("no touch panel found on the emulator (getevent -p reports none with ABS_MT_POSITION_X); "
        "BB_TOUCH_DEV=/dev/input/eventN names one")


def screen(a):
    """(width, height, rotation) as the screen is shown: the physical size
    and the display's rotation (0..3, quarter turns)."""
    size = re.findall(r"size: (\d+)x(\d+)", shell(a, "wm", "size"))
    if not size:
        die("wm size did not say the screen's size")
    w, h = int(size[-1][0]), int(size[-1][1])
    rot = os.environ.get("BB_TOUCH_ROTATION", "")
    if not rot:
        m = re.search(r"SurfaceOrientation:\s*(\d)", shell(a, "dumpsys", "input"))
        rot = m.group(1) if m else "0"
    return w, h, int(rot)


def to_panel(x, y, w, h, rot, xmax, ymax):
    """A screen pixel to the panel's own frame and range. The panel is the
    portrait screen; a rotated screen has its x along the panel's y."""
    if rot == 1:
        px, py = w - 1 - y, x
    elif rot == 2:
        px, py = w - 1 - x, h - 1 - y
    elif rot == 3:
        px, py = y, h - 1 - x
    else:
        px, py = x, y
    return int(px * xmax / max(w - 1, 1)), int(py * ymax / max(h - 1, 1))


def main(argv):
    args = list(argv)
    if not args or args[0] in ("-h", "--help"):
        sys.stderr.write(__doc__ or "")
        return 0 if args else 1
    try:
        args, hopts = hand.parse(args)
    except ValueError as e:
        die(str(e))
    # --ms is the hand's for a glide (the time each leg takes) and hold's
    # for a hold (how long the finger stays down).
    opts = {"pre": 0, "hold": 0, "ms": int(hopts.pop("ms", 0) or 0)}
    for k in list(opts):
        flag = f"--{k}"
        if flag in args:
            i = args.index(flag)
            try:
                opts[k] = int(args[i + 1])
            except (IndexError, ValueError):
                die(f"{flag} takes a number of milliseconds")
            del args[i:i + 2]
    verb, nums = args[0], args[1:]
    try:
        pts = [(int(nums[i]), int(nums[i + 1])) for i in range(0, len(nums), 2)]
    except (IndexError, ValueError):
        die("coordinates come in X Y pairs, in screen pixels")
    if verb not in ("tap", "hold", "glide") or not pts:
        die("touch.py tap X Y | hold X Y --ms N | glide X Y X Y... [--pre MS] [--hold MS]")
    stroke = None
    if verb == "glide":
        try:
            stroke = hand.path(pts, ms=opts["ms"] or None, **hopts)
        except ValueError as e:
            die(str(e))
    if verb == "hold" and not opts["ms"]:
        die("hold takes --ms N: how long the finger stays down")
    a = adb()
    ensure_root(a)
    dev, xmax, ymax = panel(a)
    w, h, rot = screen(a)
    ev = lambda t, c, v: f"sendevent {dev} {t} {c} {v}"  # noqa: E731
    lines = []
    px, py = to_panel(pts[0][0], pts[0][1], w, h, rot, xmax, ymax)
    lines += [ev(EV_ABS, ABS_MT_SLOT, 0), ev(EV_ABS, ABS_MT_TRACKING_ID, 1),
              ev(EV_ABS, ABS_MT_TOOL_TYPE, 0), ev(EV_ABS, ABS_MT_TOUCH_MAJOR, 20),
              ev(EV_ABS, ABS_MT_PRESSURE, 200), ev(EV_ABS, ABS_MT_POSITION_X, px),
              ev(EV_ABS, ABS_MT_POSITION_Y, py), ev(EV_SYN, 0, 0)]
    moved = 0
    if verb == "hold":
        lines.append(f"sleep {opts['ms'] / 1000}")
    if verb == "glide":
        if opts["pre"]:
            lines.append(f"sleep {opts['pre'] / 1000}")
        # The hand's samples, DT ms apart, as the finger's positions.
        for _, x, y in stroke["samples"][1:]:
            mx, my = to_panel(x, y, w, h, rot, xmax, ymax)
            lines += [f"sleep {hand.DT / 1000}", ev(EV_ABS, ABS_MT_POSITION_X, mx),
                      ev(EV_ABS, ABS_MT_POSITION_Y, my), ev(EV_SYN, 0, 0)]
            moved += 1
        if opts["hold"]:
            lines.append(f"sleep {opts['hold'] / 1000}")
    lines += [ev(EV_ABS, ABS_MT_PRESSURE, 0), ev(EV_ABS, ABS_MT_TRACKING_ID, -1), ev(EV_SYN, 0, 0)]
    r = subprocess.run([a, "shell", ";".join(lines)], capture_output=True, text=True, timeout=120, check=False)
    if r.returncode:
        die(f"sendevent on {dev} failed: {(r.stderr or r.stdout).strip()[-200:]}")
    took = opts["ms"] if verb == "hold" else opts["pre"] + opts["hold"] + moved * hand.DT
    where = " ".join(f"{x},{y}" for x, y in pts)
    print(f"{verb} {where}: {len(lines)} events on {dev}, about {took} ms" + (f" (rotation {rot})" if rot else "")
          + (f"; {hand.summary(stroke)}" if stroke else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
