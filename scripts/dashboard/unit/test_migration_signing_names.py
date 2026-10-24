"""State migration 0007: a project's signing keys from before it could hold
several move under `default` once, whoever opens the project next."""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "m0007", os.path.join(HERE, "..", "statemigrations", "0007_signing_key_names.py"))
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


class Move(unittest.TestCase):
    def test_old_slots_move_once_and_a_named_key_is_never_overwritten(self):
        t = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, t, True)
        old, kept = t / "signing" / "older", t / "signing" / "both"
        old.mkdir(parents=True)
        (old / "play.ks").write_bytes(b"k")
        (old / "play.json").write_text("{}")
        (kept / "default").mkdir(parents=True)
        (kept / "default" / "sideload.ks").write_bytes(b"new")
        (kept / "sideload.ks").write_bytes(b"old")
        m.run({"state": str(t)})
        m.run({"state": str(t)})
        self.assertTrue((old / "default" / "play.ks").is_file())
        self.assertFalse((old / "play.ks").exists())
        self.assertEqual((kept / "default" / "sideload.ks").read_bytes(), b"new")

    def test_an_install_with_no_signing_is_left_alone(self):
        t = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, t, True)
        m.run({"state": str(t)})
        self.assertFalse((t / "signing").exists())


if __name__ == "__main__":
    unittest.main()
