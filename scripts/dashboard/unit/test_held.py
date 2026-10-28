"""A held start (R56 step 9, held.py): held after an unclean shutdown or
when the next start was armed, not on a first boot or after a clean stop,
lifted by Start, and nothing of it on a container install."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import held  # noqa: E402


def write_json(path, obj, mode=0o644):
    with open(path, "w") as f:
        json.dump(obj, f)


class Held(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        held.configure(state=self.tmp, bare_metal=lambda: True, write_json_fn=write_json)

    def test_a_first_boot_and_a_clean_stop_are_not_held(self):
        self.assertFalse(held.boot()["held"], "a first boot has no history to hold on")
        held.shutdown_clean()
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "clean-shutdown")))
        self.assertFalse(held.boot()["held"], "a clean stop, then a start: nothing held")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "clean-shutdown")), "the marker is read once")

    def test_an_unclean_stop_holds_the_next_start_until_start(self):
        held.boot()                      # booted once, no clean marker written: the power was pulled
        got = held.boot()
        self.assertTrue(got["held"])
        self.assertIn("not clean", got["why"][0])
        self.assertTrue(held.is_held())
        self.assertIn("press Start on This machine", held.said())
        r = held.start("user:test")
        self.assertEqual((r["ok"], r["held"]), (True, False))
        self.assertFalse(held.is_held())
        self.assertEqual(held.start("user:test").get("note"), "the start was not held")

    def test_the_next_start_armed_holds_that_one_boot(self):
        held.boot()
        held.shutdown_clean()
        self.assertEqual(held.arm_next(True), {"ok": True, "armed": True})
        self.assertTrue(held.status()["armed"])
        got = held.boot()
        self.assertTrue(got["held"])
        self.assertIn("Hold the next start", got["why"][0])
        self.assertFalse(held.status()["armed"], "armed for one boot, then not")
        held.start()
        held.shutdown_clean()
        self.assertFalse(held.boot()["held"])
        held.arm_next(True)
        self.assertEqual(held.arm_next(False)["armed"], False)

    def test_a_container_install_holds_nothing(self):
        held.configure(state=self.tmp, bare_metal=lambda: False, write_json_fn=write_json)
        self.assertEqual(held.boot(), {"held": False, "why": [], "since": 0, "armed": False})
        self.assertFalse(held.is_held())
        self.assertIn("container", held.start().get("error", ""))
        self.assertIn("bare-metal", held.arm_next().get("error", ""))


if __name__ == "__main__":
    unittest.main()
