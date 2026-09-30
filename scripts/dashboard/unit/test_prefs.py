"""prefs.py's Also sees setting: which paths a project may be shown on its
node (B378). test/reads.mjs proves the dialog; this proves the rule."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import prefs  # noqa: E402


class Sees(unittest.TestCase):
    def test_a_share_on_the_node_is_a_place(self):
        for p in ("/mnt/media", "/workspace-dev", "/srv/data_1"):
            self.assertEqual(prefs.sees_problem(p), "", p)

    def test_the_machine_and_builderbot_are_never(self):
        for p in ("/etc", "/home/x", "/root", "/workspace", "/proc/1", "/usr/local"):
            self.assertTrue(prefs.sees_problem(p), p)

    def test_a_path_that_is_not_a_plain_absolute_one_is_refused(self):
        for p in ("mnt/media", "/mnt/../etc", "/mnt/me dia", "/mnt/$(x)", ""):
            self.assertTrue(prefs.sees_problem(p), p)

    def test_stored_list_drops_bad_and_repeated_and_caps(self):
        many = [f"/mnt/d{i}" for i in range(prefs.SEES_MAX + 3)]
        got = prefs._sees_of({"sees": ["/mnt/a/", "/mnt/a", "/etc", *many]})
        self.assertEqual(got[0], "/mnt/a")
        self.assertNotIn("/etc", got)
        self.assertEqual(len(got), prefs.SEES_MAX)

    def test_a_record_without_the_setting_sees_nothing(self):
        self.assertEqual(prefs._sees_of({}), [])
        self.assertEqual(prefs._sees_of({"sees": "nope"}), [])


if __name__ == "__main__":
    unittest.main()
