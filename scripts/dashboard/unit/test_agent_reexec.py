"""The agent restarts into a new version only once nothing else runs (B134):
a rebuild taken beside an update, after its busy check, was lost to the
exec, and an update that installed nothing restarted it all the same."""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import agentpkg  # noqa: E402


class Fake:
    def __init__(self, jobs):
        self.lock, self.jobs, self.execs = threading.Lock(), dict(jobs), 0

    def reexec(self):
        self.execs += 1


class Job:
    def __init__(self, jid):
        self.job = {"id": jid}


class Reexec(unittest.TestCase):
    def setUp(self):
        a = agentpkg.load("reexec")
        self.Agent = a.Agent
        a.log = lambda *x, **k: None

    def test_alone_it_restarts_at_once(self):
        f = Fake({})
        self.Agent.reexec_when_idle(f)
        self.assertEqual(f.execs, 1)

    def test_beside_a_running_job_it_waits_for_it(self):
        f = Fake({"j_build": Job("j_build")})
        self.Agent.reexec_when_idle(f)
        self.assertEqual(f.execs, 0, "not while the rebuild runs")
        self.Agent.finished(f, Job("j_build"))
        self.assertEqual(f.execs, 1, "once it ends")

    def test_a_job_ending_with_no_update_waiting_restarts_nothing(self):
        f = Fake({"j1": Job("j1")})
        self.Agent.finished(f, Job("j1"))
        self.assertEqual(f.execs, 0)


if __name__ == "__main__":
    unittest.main()
