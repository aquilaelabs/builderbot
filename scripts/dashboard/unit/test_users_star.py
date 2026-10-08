"""The owner takes projects on like everybody (R135): "*" on a record
lists every project and takes none on, migrate_star turns an owner's "*"
into the projects that exist, and take_on adds to any list."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import users  # noqa: E402


class Star(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        users.configure(state=self.tmp, write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
        with users._lock:
            d = users.load()
            d["users"]["boss"] = {"uid": "u_00000001", "role": "owner", "projects": ["*"],
                                  "password": "x", "created": 0, "seen": 0}
            d["users"]["adm"] = {"uid": "u_00000002", "role": "admin", "projects": ["beta"],
                                 "password": "x", "created": 0, "seen": 0}
            users._save(d)

    def test_a_star_lists_everything_and_takes_nothing_on(self):
        boss = users.get("boss")
        self.assertTrue(users.sees_all(boss))
        self.assertTrue(users.may_see(boss, "alpha"))
        self.assertFalse(users.may_work(boss, "alpha"), "a star is not a project taken on")

    def test_migrate_star_gives_the_owner_the_projects_that_exist(self):
        self.assertEqual(users.migrate_star(["beta", "alpha"]), 1)
        self.assertEqual(users.get("boss")["projects"], ["alpha", "beta"])
        self.assertEqual(users.get("adm")["projects"], ["beta"], "an explicit list is left alone")
        self.assertEqual(users.migrate_star(["alpha"]), 0, "nothing to move the second time")
        self.assertTrue(users.may_work(users.get("boss"), "alpha"))
        self.assertFalse(users.may_work(users.get("boss"), "gamma"), "a project made later is taken on like any")

    def test_take_on_adds_to_any_list(self):
        self.assertEqual(users.take_on("boss", "gamma")["projects"], ["*", "gamma"])
        self.assertTrue(users.may_work(users.get("boss"), "gamma"))
        self.assertEqual(users.take_on("boss", "gamma")["projects"], ["*", "gamma"], "once")


if __name__ == "__main__":
    unittest.main()
