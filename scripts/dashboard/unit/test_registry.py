"""Projects by id (registry.py, R154): every directory has a number and a
shown name, a directory is never handed out twice, shown names are unique
among live projects with -2 after a second, a name follows GitHub's rules
for a repository's, and the trash keeps a project's directory for it."""
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

    def test_the_first_run_records_what_is_there_and_nothing_after(self):
        ps = registry.sync()["projects"]
        self.assertEqual((ps["alpha"]["id"], ps["alpha"]["name"], ps["alpha"]["state"]), (1, "alpha", "live"))
        self.assertEqual((ps["old-2"]["name"], ps["old-2"]["state"], ps["old-2"].get("legacy")),
                         ("old", "trashed", True), "a numbered delete from before ids was the name without it")
        (self.ws / "byhand").mkdir()
        self.assertNotIn("byhand", registry.sync()["projects"], "a folder made by hand is no project")
        self.assertFalse(registry.is_project("byhand"))
        self.assertTrue(registry.is_project("alpha"))
        self.assertEqual(registry.new_dir("byhand"), "byhand-2", "...and its name is not handed out")

    def test_a_directory_is_never_handed_out_twice(self):
        registry.sync()
        self.assertEqual(registry.new_dir("alpha"), "alpha-2")
        self.assertEqual(registry.new_dir("ALPHA"), "ALPHA-2", "case does not make another")
        self.assertEqual(registry.new_dir("old-2"), "old-2-2")
        registry.claim("gone", "Gone")
        registry.mark("gone", "purged")
        self.assertEqual(registry.new_dir("gone"), "gone-2", "deleted for good still counts")
        self.assertEqual(registry.new_dir("fresh"), "fresh")
        # What the New project dialog reads to say so before Create (B63).
        taken = registry.taken_dirs()
        self.assertIn("gone", taken, "a purged directory is listed as taken")
        self.assertIn("alpha", taken)
        self.assertNotIn("fresh", taken)

    def test_shown_names_are_unique_among_live_repositories(self):
        registry.sync()
        (self.ws / "alpha-2").mkdir()
        self.assertEqual(registry.claim("alpha-2", "alpha")["name"], "alpha-2")
        (self.ws / "alpha-3").mkdir()
        self.assertEqual(registry.claim("alpha-3", "Alpha")["name"], "Alpha-3")
        self.assertIn("already a repository's name", registry.set_name("alpha-3", "ALPHA 2")["error"])
        self.assertEqual(registry.set_name("alpha-3", "Third")["name"], "Third")
        self.assertEqual(registry.label("alpha-3"), "Third")
        self.assertEqual(registry.resolve("Third"), "alpha-3")
        self.assertEqual(registry.resolve("alpha-3"), "alpha-3")
        self.assertEqual(registry.resolve("nope"), "")

    def test_a_project_is_named_by_its_id_too(self):
        registry.sync()
        pid = registry.pid("alpha")
        self.assertRegex(pid, r"^P\d+$")
        self.assertEqual(registry.resolve(pid), "alpha")
        self.assertEqual(registry.resolve(pid.lower()), "alpha")
        self.assertEqual(registry.resolve("P99999"), "")
        self.assertEqual(registry.pid("nope"), "")

    def test_a_restore_whose_name_was_taken_meanwhile_is_numbered(self):
        registry.sync()
        registry.mark("alpha", "trashed")
        (self.ws / "alpha-2").mkdir()
        registry.claim("alpha-2", "alpha")
        self.assertEqual(registry.label("alpha-2"), "alpha", "a trashed one does not block the name")
        registry.mark("alpha", "live")
        self.assertEqual(registry.label("alpha"), "alpha-2")

    def test_a_trashed_folder_moved_back_by_hand_is_live_and_one_made_beside_it_is_not(self):
        registry.sync()
        (self.ws / "alpha").rename(self.ws / ".trash" / "alpha")
        self.assertEqual(registry.sync()["projects"]["alpha"]["state"], "trashed")
        (self.ws / "alpha").mkdir()
        self.assertEqual(registry.sync()["projects"]["alpha"]["state"], "trashed",
                         "made by hand while the trashed one is in the trash: not it")
        (self.ws / "alpha").rmdir()
        (self.ws / ".trash" / "alpha").rename(self.ws / "alpha")
        self.assertEqual(registry.sync()["projects"]["alpha"]["state"], "live", "moved back: it")

    def test_names_follow_githubs_rules_for_a_repository(self):
        # the operator, 9 Oct: a rename to "Turing Lens" kept the space
        self.assertEqual(registry.clean_name("Turing Lens"), "Turing-Lens")
        self.assertEqual(registry.clean_name("  My   App\n\x07 "), "My-App")
        self.assertEqual(registry.clean_name("Clanker-Detector"), "Clanker-Detector")
        self.assertEqual(registry.clean_name("a__b.c"), "a__b.c")
        self.assertEqual(registry.clean_name("café crème!"), "caf-cr-me")
        self.assertEqual(registry.clean_name(".."), "")
        self.assertEqual(registry.clean_name("---"), "")
        self.assertEqual(len(registry.clean_name("x" * 200)), registry.NAME_MAX)
        self.assertEqual(registry.NAME_MAX, 100)
        registry.sync()
        self.assertEqual(registry.set_name("alpha", "Turing Lens")["name"], "Turing-Lens")

    def test_a_name_stored_before_the_rule_is_brought_to_it(self):
        registry.sync()
        d = json.loads(registry.FILE.read_text())
        d["projects"]["alpha"]["name"] = "Turing Lens"
        registry.FILE.write_text(json.dumps(d))
        registry._cache.update(mtime=None, data=None)
        registry.sync()
        self.assertEqual(registry.label("alpha"), "Turing-Lens")
        self.assertEqual(registry.resolve("Turing-Lens"), "alpha")


if __name__ == "__main__":
    unittest.main()
