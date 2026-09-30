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


if __name__ == "__main__":
    unittest.main()
