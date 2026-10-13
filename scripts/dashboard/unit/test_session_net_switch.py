"""The row's switch for keeping each session to its own network (R79) takes
only where the node's agent says it can: on Rocky with firewalld owning the
firewall the agent reports it cannot, and a switch that took anyway had the
launcher refuse every session there while the row alone said why (B709, the
dev pair, 13 Oct)."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import nodes  # noqa: E402


class SessionNetSwitch(unittest.TestCase):
    def setUp(self):
        nodes.configure(state=tempfile.mkdtemp())
        mint = nodes.enroll_mint("user:test", "box")
        nodes.enroll(nodes.authenticate(mint["token"]), {"cpu": 2, "mem_mb": 4096, "arch": "x86_64",
                                                         "system": "linux", "session": {"up": True, "user": "b"}},
                     "10.0.0.5", user="bb")
        self.nid = mint["id"]

    def said(self, can, why=""):
        # The session network rides the census, which a hello carries.
        nodes.hello(self.nid, {"cpu": 2, "mem_mb": 4096, "arch": "x86_64", "system": "linux",
                               "session": {"up": True, "user": "b"},
                               "session_net": {"can": can, "why": why, "wanted": False, "active": False}}, "10.0.0.5")

    def test_a_node_that_cannot_keeps_the_switch_off_and_says_why(self):
        self.said(False, "firewalld owns this node's firewall, which this setting does not go through yet")
        r = nodes.node_session_net("user:test", self.nid, True)
        self.assertIn("firewalld", r.get("error", ""))
        self.assertFalse((nodes.node(self.nid)["config"] or {}).get("session_net"))

    def test_a_node_that_can_takes_it(self):
        self.said(True)
        self.assertEqual(nodes.node_session_net("user:test", self.nid, True), {"ok": True, "on": True})
        self.assertTrue(nodes.node(self.nid)["config"]["session_net"])

    def test_off_is_always_allowed(self):
        self.said(False, "firewalld")
        self.assertEqual(nodes.node_session_net("user:test", self.nid, False), {"ok": True, "on": False})


if __name__ == "__main__":
    unittest.main()
