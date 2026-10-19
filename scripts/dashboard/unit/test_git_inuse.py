"""git.in_use: what the project directory's own open Claude session keeps
off it. A switch waits while the session is open; a new branch switched to
is a switch too (B859: it went round the guard and moved the tree under
an open session); a new branch left where it is moves nothing."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import git  # noqa: E402


class InUse(unittest.TestCase):
    def setUp(self):
        self.saved = {k: getattr(git, k) for k in ("SESSION_OPEN", "WORKING", "OWNER_UID", "OWNER_NAME")}
        git.SESSION_OPEN = lambda project: True
        git.WORKING = lambda project, uid: False
        git.OWNER_UID = lambda: "u1"
        git.OWNER_NAME = lambda: "owner"

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(git, k, v)

    def test_a_switch_waits_for_an_open_session(self):
        self.assertIn("end it before switching", git.in_use("p", "switch", {"name": "x"}, "u1"))

    def test_a_new_branch_switched_to_waits_too(self):
        self.assertIn("end it before switching", git.in_use("p", "branch", {"name": "x", "switch": True}, "u1"))

    def test_a_new_branch_left_where_it_is_does_not(self):
        self.assertEqual(git.in_use("p", "branch", {"name": "x"}, "u1"), "")

    def test_no_open_session_no_wait(self):
        git.SESSION_OPEN = lambda project: False
        self.assertEqual(git.in_use("p", "branch", {"name": "x", "switch": True}, "u1"), "")


if __name__ == "__main__":
    unittest.main()
