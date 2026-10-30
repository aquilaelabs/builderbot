"""The debug and dev options exist only on a controller started with
DEBUG_MODE=1 (the operator, 12 Oct): without it they read off, cannot be
turned on, and at a start every one that was on is put back off, the
projects' Debug grants with them. Debug mode itself is the environment's
(the operator, 26 Oct): on exactly while DEBUG_MODE=1, never saved."""
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

    def test_on_it_is_on(self):
        os.environ["DEBUG_MODE"] = "1"
        self.assertTrue(settings.get("debug_mode"), "on with nothing saved")
        self.assertEqual(settings.effective()["debug_mode"]["source"], "env")
        self.assertIn("DEBUG_MODE=1", settings.set_many({"debug_mode": False}).get("error", ""), "not a setting to save")
        self.assertTrue(settings.set_many({"offer_unvetted": True}).get("ok"))
        self.assertTrue(settings.payload()["debug_available"])

    def test_off_it_reads_off_and_will_not_turn_on(self):
        os.environ["DEBUG_MODE"] = "1"
        settings.set_many({"offer_unvetted": True})
        os.environ.pop("DEBUG_MODE")
        self.assertFalse(settings.get("debug_mode"))
        self.assertFalse(settings.get("offer_unvetted"), "reads off whatever the file says")
        self.assertIn("not available", settings.set_many({"offer_unvetted": True}).get("error", ""))
        self.assertTrue(settings.set_many({"offer_unvetted": False}).get("ok"), "turning off is always allowed")

    def test_a_start_without_it_puts_everything_back_off(self):
        os.environ["DEBUG_MODE"] = "1"
        settings.set_many({"offer_unvetted": True})
        prefs.FILE.write_text(json.dumps({"projects": {"a": {"diag": True, "log_from": ["n_1"], "node": "n_1"},
                                                       "b": {"node": "n_2"}}}))
        os.environ.pop("DEBUG_MODE")
        self.assertTrue(settings.reset_debug())
        self.assertEqual(prefs.reset_debug(), 1)
        os.environ["DEBUG_MODE"] = "1"
        self.assertTrue(settings.get("debug_mode"), "on again with DEBUG_MODE, as the environment says")
        self.assertFalse(settings.get("offer_unvetted"), "...and the rest starts from off")
        a = json.loads(prefs.FILE.read_text())["projects"]["a"]
        self.assertEqual(a, {"node": "n_1"}, "the grants went, the rest stayed")



    def test_a_boot_that_asks_for_the_dev_channel_gets_it_in_debug_mode_alone(self):
        # R161 step 12: a stick's builderbot.env says BB_RELEASE_CHANNEL=dev.
        was = os.environ.get("BB_RELEASE_CHANNEL")
        self.addCleanup(lambda: os.environ.pop("BB_RELEASE_CHANNEL", None) if was is None else os.environ.__setitem__("BB_RELEASE_CHANNEL", was))
        os.environ["BB_RELEASE_CHANNEL"] = "dev"
        os.environ.pop("DEBUG_MODE", None)
        self.assertFalse(settings.boot_channel(), "nothing without DEBUG_MODE=1")
        os.environ["DEBUG_MODE"] = "1"
        self.assertTrue(settings.boot_channel())
        self.assertTrue(settings.dev_channel_ok())
        self.assertEqual(settings.get("release_channel"), "dev")
        self.assertFalse(settings.boot_channel(), "the next start finds it so and writes nothing")
        os.environ["BB_RELEASE_CHANNEL"] = "nightly"
        settings.set_many({"release_channel": "normal"})
        self.assertFalse(settings.boot_channel(), "no other word")
        self.assertEqual(settings.get("release_channel"), "normal")

    def test_the_dev_channel_is_offered_only_with_debug_and_the_dev_switch(self):
        # R179: refused without debug mode, refused with it until the dev
        # switch is on, back to normal at a start without debug mode.
        os.environ.pop("DEBUG_MODE", None)
        self.assertIn("dev channel", settings.set_many({"release_channel": "dev"}).get("error", ""))
        self.assertTrue(settings.set_many({"release_channel": "normal"}).get("ok"), "normal may always be picked")
        os.environ["DEBUG_MODE"] = "1"
        self.assertIn("dev channel", settings.set_many({"release_channel": "dev"}).get("error", ""), "debug alone is not enough")
        settings.set_many({"offer_unvetted": True})
        self.assertTrue(settings.dev_channel_ok())
        self.assertTrue(settings.set_many({"release_channel": "dev"}).get("ok"))
        self.assertEqual(settings.get("release_channel"), "dev")
        os.environ.pop("DEBUG_MODE")
        self.assertTrue(settings.reset_debug())
        self.assertEqual(settings.get("release_channel"), "normal", "a start without debug mode puts the channel back")
        self.assertFalse(settings.dev_channel_ok())


if __name__ == "__main__":
    unittest.main()
