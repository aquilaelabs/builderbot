#!/usr/bin/env python3
"""Timed touches on the running emulator (R101): `bb emu touch`, and $BB_TOUCH
inside a capture's --drive script.

    touch.py tap X Y
    touch.py hold X Y --ms N
    touch.py glide X Y X Y [X Y...] [--pre MS] [--hold MS] [--step-ms MS]

Screen pixels, as a screenshot shows them, whichever way the screen is
turned. `adb shell input tap` costs about 300 ms a call and `input swipe`
moves at its own pace, so neither can time a glide across letters or tell a
long-press from a slide: a keyboard session found that out and wrote its
own sendevent script (Shebang-DevBoard, 30 Sep). This one writes the whole
gesture as one `adb shell` of sendevent lines with sleeps between them, so
the device sees the timing the script asked for. --pre holds the finger
still before it starts moving (a long-press that then slides), --hold keeps
it down at the end before lifting, --step-ms is the time between moves of
25 px (12 by default, about 2 px a millisecond).

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
from typing import NoReturn

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_MT_SLOT, ABS_MT_TOUCH_MAJOR, ABS_MT_POSITION_X, ABS_MT_POSITION_Y = 0x2F, 0x30, 0x35, 0x36
ABS_MT_TOOL_TYPE, ABS_MT_TRACKING_ID, ABS_MT_PRESSURE = 0x37, 0x39, 0x3A
STEP_PX = 25


def die(msg) -> NoReturn:
    sys.stderr.write(f"[builderbot] ERROR: {msg}\n")
    sys.exit(1)


def adb():
    return os.environ.get("BB_CAPTURE_ADB") or os.environ.get("ADB") or shutil.which("adb") or die(
        "adb is not on this node: bb emu says what the emulator needs")


def shell(a, *words):
    r = subprocess.run([a, "shell", *words], capture_output=True, text=True, timeout=30, check=False)
    return r.stdout or ""


def panel(a):
    """(device path, x max, y max) of the multi-touch panel."""
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
    for d in [want] if want else sorted(xs):
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
    opts = {"pre": 0, "hold": 0, "ms": 0, "step-ms": 12}
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
    if verb == "glide" and len(pts) < 2:
        die("a glide needs at least two points")
    if verb == "hold" and not opts["ms"]:
        die("hold takes --ms N: how long the finger stays down")
    a = adb()
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
        sx, sy = pts[0]
        for x, y in pts[1:]:
            steps = max(2, int(((x - sx) ** 2 + (y - sy) ** 2) ** 0.5 / STEP_PX))
            for s in range(1, steps + 1):
                mx, my = to_panel(sx + (x - sx) * s // steps, sy + (y - sy) * s // steps, w, h, rot, xmax, ymax)
                lines += [ev(EV_ABS, ABS_MT_POSITION_X, mx), ev(EV_ABS, ABS_MT_POSITION_Y, my), ev(EV_SYN, 0, 0),
                          f"sleep {opts['step-ms'] / 1000}"]
                moved += 1
            sx, sy = x, y
        if opts["hold"]:
            lines.append(f"sleep {opts['hold'] / 1000}")
    lines += [ev(EV_ABS, ABS_MT_PRESSURE, 0), ev(EV_ABS, ABS_MT_TRACKING_ID, -1), ev(EV_SYN, 0, 0)]
    r = subprocess.run([a, "shell", ";".join(lines)], capture_output=True, text=True, timeout=120, check=False)
    if r.returncode:
        die(f"sendevent on {dev} failed: {(r.stderr or r.stdout).strip()[-200:]}")
    took = opts["ms"] if verb == "hold" else opts["pre"] + opts["hold"] + moved * opts["step-ms"]
    where = " ".join(f"{x},{y}" for x, y in pts)
    print(f"{verb} {where}: {len(lines)} events on {dev}, about {took} ms" + (f" (rotation {rot})" if rot else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
