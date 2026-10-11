"""A docker read on an agent node (devapp._agent_read): asked every time,
busy or not, and answered from what was kept, marked stale, only when the
node does not answer (the operator, 11 Oct: the Docker tab read "down, as
last seen" whenever anything ran on the node, including the change just
made from it)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402


class Queue:
    def __init__(self):
        self.asked, self.answer, self.busy = [], {"code": 0, "out": "up"}, 1

    def job_running(self, nid):
        return self.busy

    def run_wait(self, who, nid, argv, timeout=30, forget=False):
        self.asked.append(argv)
        return dict(self.answer)


class AgentRead(unittest.TestCase):
    def setUp(self):
        self.q = Queue()
        saved = devapp.queue
        devapp.queue = self.q
        self.addCleanup(setattr, devapp, "queue", saved)
        devapp._last_reads.clear()
        self.n = {"id": "n1", "name": "box"}
        self.argv = [devapp.DOCKER, "ps", "--all"]

    def test_a_busy_node_is_still_asked(self):
        self.q.answer = {"code": 0, "out": "was down"}
        devapp._agent_read(self.n, self.argv, 30)
        self.q.answer = {"code": 0, "out": "now starting"}
        r = devapp._agent_read(self.n, self.argv, 30)
        self.assertEqual(r, {"code": 0, "out": "now starting"}, "fresh, not the kept answer")
        self.assertEqual(len(self.q.asked), 2)

    def test_a_node_that_does_not_answer_gets_what_was_kept_marked_stale(self):
        devapp._agent_read(self.n, self.argv, 30)
        self.q.answer = {"error": "the node did not answer in 25s"}
        r = devapp._agent_read(self.n, self.argv, 30)
        self.assertEqual((r["out"], r.get("stale")), ("up", True))

    def test_nothing_kept_and_no_answer_is_the_error(self):
        self.q.answer = {"error": "the node did not answer in 25s"}
        r = devapp._agent_read(self.n, self.argv, 30)
        self.assertEqual((r["code"], r["out"], r.get("stale")), (1, "the node did not answer in 25s", None))


if __name__ == "__main__":
    unittest.main()
