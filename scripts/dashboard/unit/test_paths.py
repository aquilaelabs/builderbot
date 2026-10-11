"""Where the controller keeps what grows (paths.py): the default in the state
directory, a move that switches only once everything has arrived, and the
places that are refused."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import paths  # noqa: E402


class Paths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "state").mkdir()
        (self.root / "ws" / "alpha").mkdir(parents=True)
        paths.configure(state=self.root / "state", workspace=self.root / "ws")
        paths._moving.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def wait(self, name):
        for _ in range(200):
            if name not in paths._moving:
                return
            time.sleep(0.01)
        self.fail(f"{name} still moving: {paths._moving.get(name)}")

    def test_default_is_the_state_directory(self):
        self.assertEqual(paths.of("gitrelay"), self.root / "state" / "gitrelay")
        self.assertEqual({p["name"] for p in paths.view()["paths"]}, set(paths.KINDS))

    def test_a_move_carries_what_is_there_and_switches_after(self):
        src = paths.of("gitview")
        (src / "a" / "b").mkdir(parents=True)
        (src / "a" / "b" / "f").write_text("kept")
        to = self.root / "big" / "gitview"
        r = paths.set_path("gitview", str(to))
        self.assertTrue(r["ok"] and r["moving"], r)
        self.wait("gitview")
        self.assertEqual(paths.of("gitview"), to)
        self.assertEqual((to / "a" / "b" / "f").read_text(), "kept")
        self.assertFalse((src / "a").exists())
        r = paths.set_path("gitview", "")
        self.wait("gitview")
        self.assertEqual(paths.of("gitview"), src, "an empty path is the default again")
        self.assertEqual((src / "a" / "b" / "f").read_text(), "kept")
        self.assertNotIn("gitview", paths._load(), "the default is not stored")

    def test_an_empty_place_switches_at_once(self):
        r = paths.set_path("project-snapshots", str(self.root / "snaps"))
        self.assertEqual(r, {"ok": True, "moving": False})
        self.assertEqual(paths.of("project-snapshots"), self.root / "snaps")

    def test_refused(self):
        for bad, why in ((str(self.root / "ws" / "alpha" / "x"), "inside the projects"),
                         ("relative/path", "absolute"), ("/etc", "system"), (f"{self.root}/../x", "absolute")):
            self.assertIn(why, paths.set_path("gitview", bad).get("error", ""), bad)
        full = self.root / "full"
        full.mkdir()
        (full / "x").write_text("x")
        self.assertIn("not empty", paths.set_path("gitview", str(full))["error"])
        paths.set_path("gitrelay", str(self.root / "one"))
        self.assertIn("already holds gitrelay", paths.set_path("gitview", str(self.root / "one"))["error"])
        self.assertIn("not a kind", paths.set_path("nope", "/tmp/x")["error"])

    def test_a_failed_move_leaves_the_old_place_in_use(self):
        src = paths.of("logs")
        src.mkdir(parents=True)
        (src / "f").write_text("x")
        real = paths.os.rename
        real_copy = paths.shutil.copy2

        def boom(*a, **k):
            raise OSError("disk full")
        paths.os.rename, paths.shutil.copy2 = boom, boom
        try:
            if paths.pinned("logs"):
                self.skipTest("logs are pinned by this container")
            paths.set_path("logs", str(self.root / "elsewhere"))
            for _ in range(200):
                if paths._moving.get("logs", {}).get("error"):
                    break
                time.sleep(0.01)
        finally:
            paths.os.rename, paths.shutil.copy2 = real, real_copy
        self.assertIn("disk full", paths._moving["logs"]["error"])
        self.assertEqual(paths.of("logs"), src)
        self.assertTrue((src / "f").exists())


if __name__ == "__main__":
    unittest.main()
