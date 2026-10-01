"""touch.py's mapping from a screen pixel to the touch panel's own frame and
range, at each rotation (R101). test/capture.mjs drives it through a
stand-in adb; this pins the arithmetic."""
import os
import sys
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


if __name__ == "__main__":
    unittest.main()
