"""The debug and dev options exist only on a controller started with
DEBUG_MODE=1 (the operator, 12 Oct): without it they read off, cannot be
turned on, and at a start every one that was on is put back off, the
projects' Debug grants with them."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import prefs  # noqa: E402
import settings  # noqa: E402


class DebugMode(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = (settings.FILE, settings.write_json, prefs.FILE, prefs.write_json, os.environ.get("DEBUG_MODE"))
        def back():
            settings.FILE, settings.write_json, prefs.FILE, prefs.write_json = saved[:4]
            os.environ.pop("DEBUG_MODE", None) if saved[4] is None else os.environ.__setitem__("DEBUG_MODE", saved[4])
        self.addCleanup(back)
        wj = lambda p, d: Path(p).write_text(json.dumps(d))   # noqa: E731
        settings.FILE, settings.write_json = self.tmp / "settings.json", wj
        prefs.FILE, prefs.write_json = self.tmp / "prefs.json", wj

    def test_on_it_turns_on(self):
        os.environ["DEBUG_MODE"] = "1"
        self.assertTrue(settings.set_many({"debug_mode": True, "offer_unvetted": True}).get("ok"))
        self.assertTrue(settings.get("debug_mode"))
        self.assertTrue(settings.payload()["debug_available"])

    def test_off_it_reads_off_and_will_not_turn_on(self):
        os.environ["DEBUG_MODE"] = "1"
        settings.set_many({"debug_mode": True})
        os.environ.pop("DEBUG_MODE")
        self.assertFalse(settings.get("debug_mode"), "reads off whatever the file says")
        self.assertIn("not available", settings.set_many({"debug_mode": True}).get("error", ""))
        self.assertTrue(settings.set_many({"debug_mode": False}).get("ok"), "turning off is always allowed")

    def test_a_start_without_it_puts_everything_back_off(self):
        os.environ["DEBUG_MODE"] = "1"
        settings.set_many({"debug_mode": True, "offer_unvetted": True})
        prefs.FILE.write_text(json.dumps({"projects": {"a": {"diag": True, "log_from": ["n_1"], "node": "n_1"},
                                                       "b": {"node": "n_2"}}}))
        os.environ.pop("DEBUG_MODE")
        self.assertTrue(settings.reset_debug())
        self.assertEqual(prefs.reset_debug(), 1)
        os.environ["DEBUG_MODE"] = "1"
        self.assertFalse(settings.get("debug_mode"), "on again, it starts from off")
        self.assertFalse(settings.get("offer_unvetted"))
        a = json.loads(prefs.FILE.read_text())["projects"]["a"]
        self.assertEqual(a, {"node": "n_1"}, "the grants went, the rest stayed")


if __name__ == "__main__":
    unittest.main()
