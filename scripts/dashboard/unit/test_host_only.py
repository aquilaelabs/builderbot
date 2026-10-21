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


class RefusalAudit(unittest.TestCase):
    def setUp(self):
        nodes._host_refused_at.clear()

    def test_a_verb_once_an_hour_and_made_up_verbs_kept_to_a_few(self):
        self.assertEqual(nodes.host_refused_audit("n_vps", "source", 0), "source")
        self.assertEqual(nodes.host_refused_audit("n_vps", "source", 10), "", "once an hour")
        said = [nodes.host_refused_audit("n_vps", f"a{i}", 20) for i in range(1000)]
        self.assertEqual(sum(1 for x in said if x), nodes.HOST_REFUSED_VERBS - 1)
        self.assertIn("unrecorded", [x for x in said if x][-1])
        self.assertLessEqual(len(nodes._host_refused_at), nodes.HOST_REFUSED_VERBS, "the table does not grow")
        self.assertEqual(nodes.host_refused_audit("n_other", "source", 30), "source", "another node is its own")
        self.assertEqual(nodes.host_refused_audit("n_vps", "source", 3700), "source", "an hour on, again")


class StaysHostOnly(unittest.TestCase):
    def test_a_node_enrolled_through_a_public_hostname_cannot_be_switched_off_hosting_only(self):
        import json
        import tempfile
        nodes.configure(state=tempfile.mkdtemp())
        nid = nodes.enroll_mint("user:test", "vps")["id"]
        nodes._exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(
            {"host_only": True, "tunnel": {"kind": "public", "host": "bb.example.com"}}), nid))
        self.assertIn("public hostname", nodes.node_update("user:test", nid, {"host_only": False}).get("error", ""))
        self.assertTrue(nodes.host_only(nid))
        nodes._exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps({"host_only": True}), nid))
        self.assertTrue(nodes.node_update("user:test", nid, {"host_only": False}).get("ok"), "one on the LAN may")


if __name__ == "__main__":
    unittest.main()
