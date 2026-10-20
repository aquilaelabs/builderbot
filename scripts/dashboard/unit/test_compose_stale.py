"""A compose job that fails on a node whose agent is behind this
controller's says so after its reason (B133): a fix that is the agent's,
sent to an agent without it, read like any other failure."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402
import devactions  # noqa: E402


class Queue:
    def __init__(self, stale):
        self.stale = stale

    def node(self, nid):
        return {"id": nid, "name": "box", "kind": "agent"}

    def agent_stale(self, n):
        return self.stale

    def job_tail(self, jid, n):
        return "could not make /run/docker.sock: File exists\n"


class ComposeStale(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.was = devapp.queue
        self.addCleanup(setattr, devapp, "queue", self.was)

    def done(self, stale):
        devapp.configure(workspace=self.tmp, state=self.tmp, write_json=lambda p, d: None)
        devapp.queue = Queue(stale)
        job = {"id": "j1", "node": "n1", "state": "failed",
               "spec": {"project": "alpha", "instance": "main", "action": "rebuild", "plan": [{}]},
               "outputs": [{"kind": "compose", "failed_at": "preparing", "steps_done": 0}]}
        return devactions._compose_done(job, "failed")

    def test_a_node_behind_says_an_update_may_be_what_it_needs(self):
        got = self.done("box runs agent 0.5.210 and this controller ships 0.5.211: press Update agent on its row first.")
        self.assertTrue(got.startswith("a bind directory could not be made on the node: could not make /run/docker.sock"), got)
        self.assertIn("press Update agent on its row first", got)

    def test_a_current_node_says_the_reason_alone(self):
        got = self.done("")
        self.assertEqual(got, "a bind directory could not be made on the node: could not make /run/docker.sock: File exists")


if __name__ == "__main__":
    unittest.main()
