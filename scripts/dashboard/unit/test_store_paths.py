"""Where a node's store or mount may go (R120): the controller refuses a
system directory before anybody presses Apply and the agent refuses it
whatever it is told, from two copies of one list, held equal here."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import nodes  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "..", "..", "agent"))
from builderbot_agent import base, stores  # noqa: E402


class StorePaths(unittest.TestCase):
    def test_the_two_lists_are_one(self):
        self.assertEqual(nodes.STORE_DENY_EXACT, base.STORE_DENY_EXACT)
        self.assertEqual(tuple(nodes.STORE_DENY_UNDER), tuple(base.STORE_DENY_UNDER))

    def test_system_folders_are_refused_on_both_ends(self):
        for p in ("/", "/etc", "/etc/builderbot", "/usr/local/x", "/var", "/var/lib", "/var/log", "/boot/x"):
            self.assertTrue(nodes.store_path_ok(p), p)
            self.assertTrue(stores.store_path_ok(p), p)

    def test_a_folder_of_its_own_is_allowed(self):
        for p in ("/var/log/builderbot", "/var/lib/builderbot/data", "/mnt/tank/bb", "/srv/share/node"):
            self.assertEqual(nodes.store_path_ok(p), "", p)
            self.assertEqual(stores.store_path_ok(p), "", p)

    def test_a_mount_point_is_said_as_one(self):
        self.assertIn("a mount point is a directory of its own", nodes.store_path_ok("/etc", "a mount point"))


if __name__ == "__main__":
    unittest.main()
