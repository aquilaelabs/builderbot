"""A hosting-only node held to running the containers sent to it, however
the work reaches it and whatever the box says about itself (R92)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nodes  # noqa: E402


def row(host_only=True, **kw):
    return {"id": "n_vps", "kind": "agent", "state": "online", "pool": "default", "capabilities": [],
            "labels": {}, "agent": {}, "config": {"host_only": True} if host_only else {}, **kw}


class Placement(unittest.TestCase):
    def setUp(self):
        self.was = nodes.agent_stale
        nodes.agent_stale = lambda n: ""

    def tearDown(self):
        nodes.agent_stale = self.was

    def test_a_selector_exec_is_not_taken_by_a_hosting_only_node(self):
        job = {"type": "exec", "placement": {"select": {"pool": "default"}}, "spec": {"argv": ["sh", "-c", "env"]}}
        self.assertFalse(nodes.fits(job, row()))
        self.assertTrue(nodes.fits(job, row(host_only=False)), "any other node in the pool takes it")

    def test_what_it_may_run_it_still_takes(self):
        sel = {"select": {"pool": "default"}}
        self.assertTrue(nodes.fits({"type": "compose", "placement": sel, "spec": {}}, row()))
        self.assertTrue(nodes.fits({"type": "exec", "placement": sel, "spec": {"argv": ["docker", "ps"]}}, row()))


if __name__ == "__main__":
    unittest.main()
