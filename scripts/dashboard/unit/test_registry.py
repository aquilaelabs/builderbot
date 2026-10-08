"""Projects by id (registry.py, R154): every directory has a number and a
shown name, a directory is never handed out twice, shown names are unique
among live projects with (2) after a second, and the trash keeps a
project's directory for it."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import registry  # noqa: E402


def write_json(p, d, mode=0o644):
    Path(p).write_text(json.dumps(d))


class Registry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = Path(self.tmp) / "ws"
        (self.ws / "alpha").mkdir(parents=True)
        (self.ws / ".trash" / "old-2").mkdir(parents=True)
        registry.configure(state=self.tmp, workspace=self.ws, write_json=write_json)

    def test_every_directory_on_disk_is_given_an_id(self):
        ps = registry.sync()["projects"]
        self.assertEqual((ps["alpha"]["id"], ps["alpha"]["name"], ps["alpha"]["state"]), (1, "alpha", "live"))
        self.assertEqual((ps["old-2"]["name"], ps["old-2"]["state"], ps["old-2"].get("legacy")),
                         ("old", "trashed", True), "a numbered delete from before ids was the name without it")
        self.assertEqual(registry.sync()["next"], 3, "and nothing again")

    def test_a_directory_is_never_handed_out_twice(self):
        registry.sync()
        self.assertEqual(registry.new_dir("alpha"), "alpha-2")
        self.assertEqual(registry.new_dir("ALPHA"), "ALPHA-2", "case does not make another")
        self.assertEqual(registry.new_dir("old-2"), "old-2-2")
        registry.claim("gone", "Gone")
        registry.mark("gone", "purged")
        self.assertEqual(registry.new_dir("gone"), "gone-2", "deleted for good still counts")
        self.assertEqual(registry.new_dir("fresh"), "fresh")

    def test_shown_names_are_unique_among_live_projects(self):
        registry.sync()
        (self.ws / "alpha-2").mkdir()
        self.assertEqual(registry.claim("alpha-2", "alpha")["name"], "alpha (2)")
        (self.ws / "alpha-3").mkdir()
        self.assertEqual(registry.claim("alpha-3", "Alpha")["name"], "Alpha (3)")
        self.assertIn("already a project's name", registry.set_name("alpha-3", "ALPHA (2)")["error"])
        self.assertEqual(registry.set_name("alpha-3", "Third")["name"], "Third")
        self.assertEqual(registry.label("alpha-3"), "Third")
        self.assertEqual(registry.resolve("Third"), "alpha-3")
        self.assertEqual(registry.resolve("alpha-3"), "alpha-3")
        self.assertEqual(registry.resolve("nope"), "")

    def test_a_restore_whose_name_was_taken_meanwhile_is_numbered(self):
        registry.sync()
        registry.mark("alpha", "trashed")
        (self.ws / "alpha-2").mkdir()
        registry.claim("alpha-2", "alpha")
        self.assertEqual(registry.label("alpha-2"), "alpha", "a trashed one does not block the name")
        registry.mark("alpha", "live")
        self.assertEqual(registry.label("alpha"), "alpha (2)")

    def test_a_folder_made_by_hand_is_numbered_and_never_wakes_a_trashed_one(self):
        registry.sync()
        registry.set_name("alpha", "Media")
        (self.ws / "Media").mkdir()
        self.assertEqual(registry.sync()["projects"]["Media"]["name"], "Media (2)")
        registry.mark("alpha", "trashed")
        (self.ws / ".trash" / "alpha").mkdir()
        (self.ws / "alpha").rename(self.ws / "alpha-tmp")
        registry.sync()
        (self.ws / "alpha").mkdir()
        self.assertEqual(registry.sync()["projects"]["alpha"]["state"], "trashed",
                         "the trashed one stays trashed")
        self.assertTrue(registry.shadowed("alpha"))

    def test_names_are_one_printable_line(self):
        self.assertEqual(registry.clean_name("  My   App\n\x07 "), "My App")
        self.assertEqual(len(registry.clean_name("x" * 200)), registry.NAME_MAX)


if __name__ == "__main__":
    unittest.main()
