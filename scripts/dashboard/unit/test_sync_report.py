"""A node's sync report names each unit it holds a copy of: a project, or an
account's worktree of one (.worktrees/P/u_x). The controller keeps those
names as sent, slashes included, because the session gate (server.py's
session_where) looks a worktree's unit up under its real name: with the
slashes stripped it was never found ready, and a session on a project the
account has a worktree of waited for a copy that was there all along (B693)."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import nodes  # noqa: E402


class SyncReport(unittest.TestCase):
    def test_a_worktree_unit_keeps_its_name(self):
        rows = nodes.sync_rows({"hello": {"ready": True, "rev": 66},
                                ".worktrees/hello/u_3deb3420": {"ready": True, "rev": 6, "pending": 0},
                                "../etc": {"ready": False}, "bad": "not a row"})
        self.assertEqual(set(rows), {"hello", ".worktrees/hello/u_3deb3420", "../etc"})
        self.assertTrue(rows[".worktrees/hello/u_3deb3420"]["ready"])
        self.assertEqual(rows["hello"], {"ready": True, "rev": 66, "pending": 0, "copying": 0, "error": ""})

    def test_the_heartbeat_keeps_it_on_the_row(self):
        nodes.configure(state=tempfile.mkdtemp())
        mint = nodes.enroll_mint("user:test", "box")
        nodes.enroll(nodes.authenticate(mint["token"]), {"cpu": 2, "mem_mb": 4096, "arch": "x86_64",
                                                         "system": "linux", "session": {"up": True, "user": "b"}},
                     "10.0.0.5", user="bb")
        nodes.heartbeat(mint["id"], {"sync": {".worktrees/hello/u_3deb3420": {"ready": True, "rev": 6}}},
                        "10.0.0.5")
        self.assertTrue(nodes.node(mint["id"])["reported"]["sync"][".worktrees/hello/u_3deb3420"]["ready"])


if __name__ == "__main__":
    unittest.main()
