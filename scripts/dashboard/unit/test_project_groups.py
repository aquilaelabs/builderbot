"""A project's group and its color (the operator, 18 Oct): labels of one
account's, a group keeping projects together on the Projects page and a
color worn by its card, its tabs and its bar, set and cleared one project at
a time, kept apart per account, and only for a project that exists. Colors
start from what projects wore while a color was the project's."""
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import projects  # noqa: E402


class Groups(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        ws, state = self.tmp / "ws", self.tmp / "state"
        for d in (ws / "alpha", ws / "beta", state):
            d.mkdir(parents=True)
        projects.configure(run=None, workspace=ws, agent_keys=lambda: [], gh_authed=lambda: False,
                           ensure_deploy_alias=lambda *a: "", project_name=re.compile(r"[A-Za-z0-9._-]+"),
                           state=state, home=self.tmp, write_json=lambda p, d: Path(p).write_text(json.dumps(d)))
        self.addCleanup(setattr, projects, "lock", projects.lock)
        projects.lock = threading.Lock()

    def test_a_group_deleted_leaves_its_projects_in_none(self):
        projects.set_group("u1", "alpha", "Clients")
        projects.set_group("u1", "beta", "Games")
        projects.set_group("u2", "alpha", "Clients")
        got, st = projects.delete_group("u1", "Clients")
        self.assertEqual((st, got["groups"]), (200, {"beta": "Games"}), "the group's projects are in no group")
        self.assertEqual(projects.load_project_groups("u2"), {"alpha": "Clients"}, "another account's group stays")
        self.assertEqual(projects.delete_group("u1", "Clients")[1], 400, "a group that is not there is said so")

    def test_set_listed_and_cleared(self):
        self.assertEqual(projects.set_group("u1", "alpha", "  Clients   one ")[1], 200)
        projects.set_group("u1", "beta", "Clients one")
        self.assertEqual(projects.load_project_groups("u1"), {"alpha": "Clients one", "beta": "Clients one"},
                         "kept by name, its spaces made one")
        projects.set_group("u1", "alpha", "")
        self.assertEqual(projects.load_project_groups("u1"), {"beta": "Clients one"}, "an empty name takes it out")

    def test_each_account_its_own(self):
        projects.set_group("u1", "alpha", "Work")
        self.assertEqual(projects.load_project_groups("u2"), {})

    def test_only_a_project_that_exists(self):
        got, status = projects.set_group("u1", "nope", "Work")
        self.assertEqual(status, 400)
        self.assertIn("unknown project", got["error"])

    def test_a_long_name_is_cut(self):
        projects.set_group("u1", "alpha", "x" * 100)
        self.assertEqual(len(projects.load_project_groups("u1")["alpha"]), projects.GROUP_MAX)


    def test_colors_start_from_the_projects_and_are_each_accounts(self):
        old = {"alpha": "teal", "beta": ""}
        self.assertEqual(projects.load_marks("color", "u1", start=old), {"alpha": "teal"},
                         "an account that never picked sees what the projects wore")
        projects.set_mark("color", "u1", "beta", "red", start=old)
        self.assertEqual(projects.load_marks("color", "u1", start=old), {"alpha": "teal", "beta": "red"},
                         "its first pick keeps the rest it started with")
        projects.set_mark("color", "u1", "alpha", "", start=old)
        self.assertEqual(projects.load_marks("color", "u1", start=old), {"beta": "red"}, "none takes one off")
        self.assertEqual(projects.load_marks("color", "u2", start=old), {"alpha": "teal"}, "another account is untouched")


if __name__ == "__main__":
    unittest.main()
