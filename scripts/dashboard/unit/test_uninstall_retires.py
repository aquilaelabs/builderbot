"""An uninstall from the Nodes tab retires the node when its job ends done,
which the agent reports from its own stop handler, since the uninstall
removes the agent's unit inside the seconds the agent watches it (B703).
A cancel does not retire: the machine may still be whole."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import nodes  # noqa: E402


class UninstallRetires(unittest.TestCase):
    def setUp(self):
        nodes.configure(state=tempfile.mkdtemp())
        mint = nodes.enroll_mint("user:test", "box")
        nodes.enroll(nodes.authenticate(mint["token"]), {"cpu": 2, "mem_mb": 4096, "arch": "x86_64",
                                                         "system": "linux", "session": {"up": True, "user": "b"}},
                     "10.0.0.5", user="bb")
        self.nid = mint["id"]

    def ended(self, state, error):
        r = nodes.job_add("user:test", {"node": self.nid}, "system",
                          {"apply": "uninstall", "config": {}, "timeout": 900})
        j = nodes.job_next(self.nid, 0)
        self.assertEqual(j and j["id"], r["job"], "the node is handed the uninstall")
        nodes.job_result(self.nid, r["job"], state, 0 if state == "succeeded" else None, error)
        return nodes.node(self.nid)["state"]

    def test_done_retires(self):
        self.assertEqual(self.ended("succeeded", ""), "retired")

    def test_a_cancel_keeps_the_row(self):
        self.assertNotEqual(self.ended("canceled", "canceled: the agent was stopped"), "retired")


if __name__ == "__main__":
    unittest.main()
