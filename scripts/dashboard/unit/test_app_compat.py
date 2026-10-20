"""The released apps' windows (R79 step 8): the device door (devices.py) and
the Files API (files.py) each refuse an app from before their window, by the
name it said, and let through one that said nothing, which speaks the first."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devices  # noqa: E402
import files  # noqa: E402


class Windows(unittest.TestCase):
    def test_an_app_that_says_nothing_speaks_the_first(self):
        self.assertEqual(devices.door_refused(None), "")
        self.assertEqual(files.api_refused(None), "")

    def test_one_inside_the_window_is_let_through(self):
        self.assertEqual(devices.door_refused(str(devices.DOOR), "companion/1.0.0"), "")
        self.assertEqual(files.api_refused(str(files.API), "vscode/1.0.0"), "")

    def test_one_before_the_window_is_refused_by_name_with_the_way_to_update(self):
        with mock.patch.object(devices, "DOOR_MIN", 3):
            why = devices.door_refused("2", "companion/0.9.0")
        self.assertIn("companion/0.9.0 speaks the controller's door 2", why)
        self.assertIn("needs 3 or newer", why)
        with mock.patch.object(files, "API_MIN", 2):
            why = files.api_refused("1", "")
        self.assertIn("this extension speaks the Files API 1", why)
        self.assertIn("update the extension", why)

    def test_a_garbled_version_is_refused(self):
        self.assertTrue(devices.door_refused("two"))
        self.assertTrue(files.api_refused("x"))

    def test_the_window_is_never_inverted(self):
        self.assertLessEqual(devices.DOOR_MIN, devices.DOOR)
        self.assertLessEqual(files.API_MIN, files.API)


if __name__ == "__main__":
    unittest.main()
