"""A docker read on an agent node (devapp._agent_read): asked every time,
busy or not, and answered from what was kept, marked stale, only when the
node does not answer (the operator, 11 Oct: the Containers page read "down, as
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


class ExecOut(unittest.TestCase):
    """A waited-on command's output is the command's: the agent's opening
    line of every job's log ("exec") was the first line of every container
    log read on an agent node (B65)."""

    def test_the_jobs_opening_line_is_not_the_commands(self):
        import nodes
        self.assertEqual(nodes.exec_out("exec\n2026-10-19T10:00:00Z up\n"), "2026-10-19T10:00:00Z up\n")
        self.assertEqual(nodes.exec_out("exec"), "exec", "a command that printed only 'exec' keeps it")
        self.assertEqual(nodes.exec_out("execute\n"), "execute\n")
        self.assertEqual(nodes.exec_out(""), "")


class NoTree(unittest.TestCase):
    """A record under a written container's name that lost its source mark
    asks git nothing: there is no tree (B634)."""

    def test_no_tree_no_git(self):
        import tempfile
        from pathlib import Path
        saved_ws, saved_run = devapp.WORKSPACE, devapp._run
        self.addCleanup(setattr, devapp, "WORKSPACE", saved_ws)
        self.addCleanup(setattr, devapp, "_run", saved_run)
        devapp.WORKSPACE = Path(tempfile.mkdtemp())
        asked = []
        devapp._run = lambda argv, **k: asked.append(argv) or {"code": 128, "out": "cannot change to"}
        self.assertEqual((devapp._dirty("nginx-vps"), devapp._head("nginx-vps")), (False, ""))
        self.assertEqual(asked, [], "git was not asked")


if __name__ == "__main__":
    unittest.main()
