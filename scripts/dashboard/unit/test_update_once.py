"""An agent update that succeeded is the node's agent at once: the hello that
says so waits on the new agent's census, a minute on bb-sandbox, and meanwhile
the node read as behind, so a second update went out, was refused as busy
behind the first, and the bell asked for a press (the operator, 19 Oct: the
VM node kept asking to be updated, the hosting one never did)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import nodes  # noqa: E402

NEW = {"digest": "sha256:new", "version": "0.7.206", "body": b""}


class UpdateOnce(unittest.TestCase):
    def setUp(self):
        nodes.configure(state=tempfile.mkdtemp())
        mint = nodes.enroll_mint("user:test", "box")
        nodes.enroll(nodes.authenticate(mint["token"]), {"cpu": 2, "mem_mb": 4096, "arch": "x86_64",
                                                         "system": "linux"}, "10.0.0.5",
                     version="0.7.205", digest="sha256:old", user="bb")
        self.nid = mint["id"]
        p = mock.patch.object(nodes, "agent_file", lambda: NEW)
        p.start()
        self.addCleanup(p.stop)

    def test_a_succeeded_update_is_current_before_the_hello(self):
        self.assertTrue(nodes.agent_stale(nodes.node(self.nid)))
        r = nodes.node_update_agent("user:test", self.nid)
        self.assertTrue(r.get("ok"), r)
        nodes.job_result(self.nid, r["job"], "succeeded", 0)
        self.assertEqual(nodes.agent_stale(nodes.node(self.nid)), "", "the node runs what it installed")
        again = nodes.node_update_agent("user:test", self.nid)
        self.assertTrue(again.get("current"), "and no second update goes out")

    def test_a_failed_update_leaves_it_behind(self):
        r = nodes.node_update_agent("user:test", self.nid)
        nodes.job_result(self.nid, r["job"], "failed", 1, "it broke")
        self.assertTrue(nodes.agent_stale(nodes.node(self.nid)))


if __name__ == "__main__":
    unittest.main()
