"""Why there is no daemon to send docker work to, said for this install
(B147): nodes enrolled with no Docker are told to install it, an install
with none is told to enroll one, and one that holds enrolling off is not."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402
import featuresoff  # noqa: E402


class Queue:
    def __init__(self, rows):
        self.rows = rows

    def node_list(self):
        return self.rows


class NoDaemon(unittest.TestCase):
    def why(self, rows, off=""):
        with mock.patch.object(devapp, "queue", Queue(rows)), \
             mock.patch.dict(os.environ, {"FEATURES_OFF": off, "FEATURES_OFF_WHY": "not here"}), \
             mock.patch.object(featuresoff, "_off", None):
            return devapp._no_daemon_why()

    def test_nodes_enrolled_without_docker_are_told_to_install_it(self):
        w = self.why([{"name": "demo-node", "kind": "agent", "state": "active"}])
        self.assertIn("(demo-node): install Docker on one", w)
        self.assertNotIn("sandbox VM", w)

    def test_no_node_is_told_to_enroll_one(self):
        self.assertIn("enroll one on the Nodes page", self.why([]))

    def test_enrolling_held_off_is_said_and_not_advised(self):
        w = self.why([], off="enroll")
        self.assertIn("is off: not here", w)
        self.assertNotIn("enroll one", w)


if __name__ == "__main__":
    unittest.main()
