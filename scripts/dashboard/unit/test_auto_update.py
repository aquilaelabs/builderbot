"""A node's agent behind this controller inside its window is updated by the
controller itself once the node is idle (R253); one with a job in flight is
left until it is idle, one from another window is the operator's press, and
an attempt is not repeated within AUTO_UPDATE_EVERY."""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import nodes  # noqa: E402


class AutoUpdate(unittest.TestCase):
    def setUp(self):
        nodes.configure(state=tempfile.mkdtemp())
        nodes._auto_tried.clear()
        mint = nodes.enroll_mint("user:test", "box")
        nodes.enroll(nodes.authenticate(mint["token"]), {"cpu": 2, "mem_mb": 4096, "arch": "x86_64",
                                                         "system": "linux", "session": {"up": True, "user": "b"}},
                     "box.lan", user="bb")
        self.nid = mint["id"]
        self.ours = nodes.agent_file()

    def runs(self, version):
        nodes._exec("UPDATE nodes SET agent = json_set(agent, '$.digest', ?, '$.version', ?) WHERE id = ?",
                    ("sha256:" + "0" * 64, version, self.nid))

    def queued(self):
        return [j for j in nodes.jobs_for(node_id=self.nid, n=10, active=True) if j.get("type") == "self-update"]

    def test_an_idle_node_behind_inside_the_window_is_updated(self):
        self.runs(self.ours["version"])
        self.assertTrue(nodes.agent_stale(nodes.node(self.nid)), "the same number, another file: behind")
        self.assertTrue(nodes.auto_update(self.nid))
        self.assertEqual(len(self.queued()), 1)
        self.assertIsNone(nodes.auto_update(self.nid), "not asked again while one is queued, nor within the wait")

    def test_a_busy_node_waits_and_another_window_is_the_operators(self):
        self.runs(self.ours["version"])
        with mock.patch.object(nodes, "agent_stale", lambda n: "behind"), \
             mock.patch.object(nodes, "jobs_for", lambda **k: [{"id": "j_busy"}]):
            self.assertIsNone(nodes.auto_update(self.nid), "a job in flight: left until the node is idle")
        nodes._auto_tried.clear()
        self.runs("0.1.1")
        with mock.patch.object(nodes, "agent_stale", lambda n: "behind"):
            self.assertIsNone(nodes.auto_update(self.nid), "another window ends sessions: the operator presses it")
        self.runs("harness")
        self.assertIsNone(nodes.auto_update(self.nid), "a version with no window is no proof of the same one")
        self.assertEqual(self.queued(), [])


if __name__ == "__main__":
    unittest.main()
