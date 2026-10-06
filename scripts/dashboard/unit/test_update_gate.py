"""An agent update waits for its node to go quiet (B516). The agent refuses
a self-update while another job runs, and a node a session builds and tests
on all day refused every press of Update agent. So while one is queued the
node is handed nothing new, and the update once the node is idle; one that
waited UPDATE_QUIET_S is failed, naming what kept the node busy."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nodes  # noqa: E402


class UpdateGate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        nodes.configure(state=self.tmp)
        # The controller's own row, made an agent node with room for four, so
        # what holds a job back below is the gate and not a full slot.
        self.n = nodes.LOCAL
        nodes._exec("UPDATE nodes SET kind = 'agent', concurrency = 4 WHERE id = ?", (self.n,))

    def job(self, jid, type, state="queued", node=None, ago=0):
        nodes._exec("INSERT INTO jobs (id, type, project, requested_by, placement, source, spec, outputs, "
                    "state, node, queued) VALUES (?, ?, '', 'test', '{}', '{}', '{}', '[]', ?, ?, ?)",
                    (jid, type, state, self.n if node is None else node, int(time.time()) - ago))

    def state(self, jid):
        return nodes._rows("SELECT state, error FROM jobs WHERE id = ?", (jid,))[0]

    def test_a_quiet_node_takes_its_update(self):
        self.job("u1", "self-update")
        got = nodes.job_next(self.n, 0)
        self.assertEqual((got["id"], got["state"]), ("u1", "assigned"))

    def test_a_busy_node_takes_work_when_no_update_waits(self):
        self.job("r1", "build", state="running")
        self.job("q1", "build", node="")
        self.assertEqual(nodes.job_next(self.n, 0)["id"], "q1")

    def test_a_busy_node_is_handed_nothing_while_the_update_waits(self):
        self.job("r1", "build", state="running")
        self.job("u1", "self-update")
        self.job("q1", "build", node="")
        self.assertIsNone(nodes.job_next(self.n, 0))
        self.assertEqual(self.state("u1")["state"], "queued")
        self.assertEqual(self.state("q1")["state"], "queued")
        nodes._exec("UPDATE jobs SET state = 'succeeded' WHERE id = 'r1'")
        got = nodes.job_next(self.n, 0)
        self.assertEqual(got["id"], "u1", "the update goes first once the node is quiet")

    def test_an_update_that_never_found_the_node_quiet_fails_saying_why(self):
        self.job("r1", "build", state="running")
        self.job("r2", "test", state="assigned")
        self.job("u1", "self-update", ago=nodes.UPDATE_QUIET_S + 5)
        nodes.job_next(self.n, 0)
        got = self.state("u1")
        self.assertEqual(got["state"], "failed")
        self.assertIn("never went quiet", got["error"])
        self.assertIn("1 build", got["error"])
        self.assertIn("1 test", got["error"])

    def test_another_nodes_update_holds_nothing_here(self):
        self.job("u1", "self-update", node="elsewhere")
        self.assertIsNone(nodes._update_gate(self.n))

    def test_the_controllers_own_runner_is_not_gated(self):
        self.job("r1", "build", state="running")
        self.job("u1", "self-update", ago=nodes.UPDATE_QUIET_S + 5)
        # runner="controller" never consults the gate: an agent's update is
        # not its to hand over or to fail.
        nodes.job_next(self.n, 0, runner="controller")
        self.assertEqual(self.state("u1")["state"], "queued")

    def test_the_row_knows_which_jobs_run_and_which_wait(self):
        self.job("r1", "build", state="running")
        self.job("u1", "self-update")
        row = next(r for r in nodes.node_list() if r["id"] == self.n)
        self.assertEqual(sorted((j["type"], j["state"]) for j in row["jobs"]),
                         [("build", "running"), ("self-update", "queued")])


if __name__ == "__main__":
    unittest.main()
