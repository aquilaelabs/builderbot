"""Every account a Unix user of its own on every node, and the coding
agents' sign-ins sealed there (R125 step 11 and R126 step 6, the operator,
26 Oct): the two switches went in 0.9.0, a key an older build left reads as
on, and a hosting-only node, which runs no sessions, is neither."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


class AlwaysOn(unittest.TestCase):
    def test_on_wherever_sessions_run_and_the_switches_refuse(self):
        import nodes
        saved = nodes.node, nodes.can_seal
        self.addCleanup(lambda: (setattr(nodes, "node", saved[0]), setattr(nodes, "can_seal", saved[1])))
        conf = {"a": {}, "h": {"host_only": True}, "x": {"account_users": False, "token_seal": False}}
        nodes.node = lambda nid: {"id": nid, "kind": "agent", "config": conf[nid]}
        nodes.can_seal = lambda: True
        self.assertEqual((nodes.account_users_on("a"), nodes.token_seal_on("a")), (True, True))
        self.assertEqual((nodes.account_users_on("h"), nodes.token_seal_on("h")), (False, False),
                         "a hosting-only node runs no sessions")
        self.assertEqual((nodes.account_users_on("x"), nodes.token_seal_on("x")), (True, True),
                         "a key an older build left reads as on")
        # ...and sealing waits on an install key to make each account's key from.
        nodes.can_seal = lambda: False
        self.assertEqual((nodes.account_users_on("a"), nodes.token_seal_on("a")), (True, False))
        self.assertIn("went in 0.9.0", nodes.node_account_users("user:t", "a", False).get("error", ""))
        self.assertIn("went in 0.9.0", nodes.node_token_seal("user:t", "a", True).get("error", ""))


if __name__ == "__main__":
    unittest.main()
