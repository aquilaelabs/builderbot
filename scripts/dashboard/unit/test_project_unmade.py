"""A create that never took, and a project deleted for good, leave nothing
behind on the accounts (B93, B95): a clone that failed kept its folder name,
so the next try landed in NAME-2, and its owner role stayed on the Profile and
the Roles page, as did the role of a project purged, under one label with
the live project shown by the same name."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import membership  # noqa: E402
import projects  # noqa: E402
import registry  # noqa: E402
import roles  # noqa: E402
import users  # noqa: E402


def write_json(p, d, mode=0o644):
    Path(p).write_text(json.dumps(d))


class Unmade(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = self.tmp / "ws"
        (self.ws / "alpha").mkdir(parents=True)
        write_json(self.tmp / "users.json", {"users": {
            "sean": {"role": "owner", "uid": "u_00000001", "projects": ["*"]},
            "ada": {"role": "admin", "uid": "u_00000002", "projects": []}}})
        users.configure(state=self.tmp, write_json=write_json)
        membership.configure(state=self.tmp, write_json=write_json)
        roles.configure(state=self.tmp, write_json=write_json)
        registry.configure(state=self.tmp, workspace=self.ws, write_json=write_json)
        registry.sync()
        self.was = (projects.unmade, projects.purged)
        projects.purged = lambda name: membership.forget_project(name, live=registry.live_dirs())
        projects.unmade = projects.purged
        self.addCleanup(lambda: setattr(projects, "unmade", self.was[0]) or setattr(projects, "purged", self.was[1]))

    def make(self, name, account="ada"):
        """What create and create_from_dialog do, up to the clone's start."""
        d = registry.new_dir(name)
        (self.ws / d).mkdir()
        registry.claim(d, name)
        users.take_on(account, d)
        membership.on_create(d, account)
        return d

    def held(self, name):
        u = users.get("ada") or {}
        return (name in (u.get("projects") or []), name in (u.get("project_roles") or {}),
                roles.owner_role_name(name) in roles.all_roles(), membership._owners()["projects"].get(name))

    def test_a_failed_clone_frees_its_folder_and_takes_its_owner_role_with_it(self):
        d = self.make("rcclone")
        self.assertEqual(d, "rcclone")
        self.assertEqual(self.held(d)[:3], (True, True, True))
        shutil.rmtree(self.ws / d)           # what _clone does on a failure
        projects._unmade(d)
        self.assertNotIn("rcclone", registry.taken_dirs(), "the folder is free for the next try")
        self.assertEqual(registry.new_dir("rcclone"), "rcclone")
        self.assertEqual(self.held(d), (False, False, False, None))

    def test_a_folder_still_there_is_not_forgotten(self):
        self.assertFalse(registry.forget("alpha"))
        self.assertIn("alpha", registry.taken_dirs())

    def test_a_purged_project_leaves_no_owner_role_and_a_trashed_one_keeps_it(self):
        gone, kept = self.make("walk-act-r2"), self.make("walk-proj-a")
        registry.mark(gone, "purged")
        projects.purged(gone)
        registry.mark(kept, "trashed")
        self.assertEqual(self.held(gone), (False, False, False, None))
        self.assertEqual(self.held(kept)[:3], (True, True, True), "kept for Put back")
        self.assertIn("walk-act-r2", registry.taken_dirs(), "...while a purged folder is never handed out again")

    def test_a_role_another_live_project_shares_by_its_cut_name_is_kept(self):
        long = "a" * 40
        d = self.make(long)
        other = self.make(long[:33] + "zz")
        self.assertEqual(roles.owner_role_name(d), roles.owner_role_name(other))
        registry.mark(d, "purged")
        projects.purged(d)
        self.assertIn(roles.owner_role_name(other), roles.all_roles())

if __name__ == "__main__":
    unittest.main()
