"""What is mounted at a node's /workspace: a share is held (a copy could
write through it onto somebody else's files), a tmpfs is the node's own and
syncs (diag report #121)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import agentpkg  # noqa: E402


class ForeignMount(unittest.TestCase):
    def check(self, fstype):
        agent = agentpkg.load("mount")
        with tempfile.NamedTemporaryFile("w", suffix=".mounts", delete=False) as f:
            f.write(f"overlay / overlay rw 0 0\n{fstype} /workspace {fstype} rw 0 0\n")
        self.addCleanup(os.unlink, f.name)
        with mock.patch("os.path.ismount", return_value=True), \
             mock.patch("os.path.realpath", side_effect=lambda p: p):
            return agent.foreign_mount("/workspace", mounts=f.name)

    def test_a_share_is_held(self):
        self.assertTrue(self.check("nfs4"))
        self.assertTrue(self.check("cifs"))

    def test_a_tmpfs_is_the_nodes_own(self):
        self.assertFalse(self.check("tmpfs"))


if __name__ == "__main__":
    unittest.main()
