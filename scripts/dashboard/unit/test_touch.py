"""touch.py's mapping from a screen pixel to the touch panel's own frame and
range, at each rotation (R101). test/capture.mjs drives it through a
stand-in adb; this pins the arithmetic."""
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import touch  # noqa: E402

W, H, MAX = 1080, 2400, 32767


def at(x, y, rot):
    return touch.to_panel(x, y, W, H, rot, MAX, MAX)


class ToPanel(unittest.TestCase):
    def test_portrait_corners_reach_the_panel_corners(self):
        self.assertEqual(at(0, 0, 0), (0, 0))
        self.assertEqual(at(W - 1, H - 1, 0), (MAX, MAX))

    def test_each_rotation_lands_the_screens_origin_on_a_different_panel_corner(self):
        corners = {rot: at(0, 0, rot) for rot in range(4)}
        self.assertEqual(len(set(corners.values())), 4, corners)

    def test_a_landscape_screens_far_corner(self):
        # Rotation 1: the screen's x runs along the panel's y.
        self.assertEqual(at(H - 1, 0, 1), (MAX, MAX))

    def test_the_middle_stays_in_the_middle(self):
        for rot in range(4):
            x, y = (W // 2, H // 2) if rot % 2 == 0 else (H // 2, W // 2)
            px, py = at(x, y, rot)
            self.assertLess(abs(px - MAX // 2), MAX // 50, rot)
            self.assertLess(abs(py - MAX // 2), MAX // 50, rot)


class Panel(unittest.TestCase):
    """Which touch device a tap goes to: with several virtio multi-touch
    devices, the first by number, which is the one bound to the display
    (report 43: sorted as text, event10 came before event2)."""

    def test_no_device_at_all_says_the_emulator_is_not_answering(self):
        # A dying emulator lists nothing (B321, diagnostics #128), which read
        # as an emulator with no touch panel.
        for said, want in (("", "not answering"),
                           ("add device 1: /dev/input/event1\n  name: \"keys\"", "no touch panel")):
            was = touch.shell
            touch.shell = lambda a, *w, s=said: s
            err = io.StringIO()
            try:
                with self.assertRaises(SystemExit), contextlib.redirect_stderr(err):
                    touch.panel("adb")
                self.assertIn(want, err.getvalue())
            finally:
                touch.shell = was

    def test_the_first_device_by_number(self):
        lines = []
        for n in list(range(2, 12)):
            lines += [f"add device {n - 1}: /dev/input/event{n}",
                      f'  name:     "virtio_input_multi_touch_{n - 1}"',
                      "    0035  : value 0, min 0, max 32767",
                      "    0036  : value 0, min 0, max 32767"]
        was, was_env = touch.shell, os.environ.pop("BB_TOUCH_DEV", None)
        touch.shell = lambda a, *w: "\n".join(lines)
        try:
            self.assertEqual(touch.panel("adb")[0], "/dev/input/event2")
        finally:
            touch.shell = was
            if was_env is not None:
                os.environ["BB_TOUCH_DEV"] = was_env


class Root(unittest.TestCase):
    """sendevent needs a root shell (reports 44 and 45): already root goes
    straight on, a build that will not give it is refused with what does
    work instead, and an answer that is not a uid is not second-guessed."""

    def run_with(self, answers):
        was = touch.shell
        touch.shell = lambda a, *w: answers.get(" ".join(w), "")
        try:
            touch.ensure_root("adb")
        finally:
            touch.shell = was

    def test_root_goes_straight_on(self):
        self.run_with({"id -u": "0\n"})

    def test_a_user_build_is_refused_with_the_way_that_works(self):
        with self.assertRaises(SystemExit):
            self.run_with({"id -u": "2000\n", "getprop ro.debuggable": "0\n"})

    def test_no_uid_is_left_alone(self):
        self.run_with({})


FAKE_ADB = """#!/bin/sh
# A device whose sendevent costs 8 ms, the shape of an emulator's: the
# gesture's own shell is run here for real, with its sleeps and its clock.
case "$1 $2 $3" in
  "shell getevent -p") printf 'add device 2: /dev/input/event2\\n  0035  : value 0, min 0, max 32767\\n  0036  : value 0, min 0, max 32767\\n' ;;
  "shell wm size") echo "Physical size: 1080x2400" ;;
  "shell dumpsys input") echo "  SurfaceOrientation: 0" ;;
  "shell id -u") echo 0 ;;
  "shell "*) shift; exec sh -c "sendevent() { sleep 0.008; }; $*" ;;
esac
"""


class Pace(unittest.TestCase):
    """A glide takes the time it was asked to on a device where one move
    costs more than the hand's 10 ms between samples, and --mark is made
    when the finger arrives to be held (Shebang-DevBoard, 5 Oct: a 3.6 s
    stroke ran long, and a shot timed by a sleep caught the first key)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.adb = os.path.join(self.tmp, "adb")
        with open(self.adb, "w") as f:
            f.write(FAKE_ADB)
        os.chmod(self.adb, 0o755)

    def run_touch(self, *args):
        lib = os.path.join(os.path.dirname(__file__), "..", "..", "lib", "touch.py")
        return subprocess.run([sys.executable, lib, *args], capture_output=True, text=True, timeout=60,
                              env={**os.environ, "BB_CAPTURE_ADB": self.adb})

    def test_the_stroke_keeps_its_pace_and_says_how_long_it_took(self):
        mark = os.path.join(self.tmp, "held")
        r = self.run_touch("glide", "100", "1000", "600", "1000", "--hand", "ruler", "--ms", "800",
                           "--hold", "200", "--mark", mark)
        self.assertEqual(r.returncode, 0, r.stderr)
        m = re.search(r"the stroke took (\d+) ms on the device, asked (\d+) \(a move every (\d+) ms", r.stdout)
        self.assertTrue(m, r.stdout)
        took, asked = int(m.group(1)), int(m.group(2))
        self.assertGreater(int(m.group(3)), 10, "the moves are spaced to what one costs")
        self.assertLess(abs(took - asked), asked * 0.35, r.stdout)
        self.assertTrue(os.path.exists(mark), "--mark is made when the finger is held")


if __name__ == "__main__":
    unittest.main()
