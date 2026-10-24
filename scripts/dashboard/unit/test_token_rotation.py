"""A node's token rotated (R135 step 4): an agent that rotates is handed a
fresh token each hello, held pending until it is first used, which makes it
the node's and retires the old one; the old one is still taken for a grace,
for calls already on their way, and presented after it means a copy of the
credential is in use, so every token of the node is revoked and the bell
says so. The screen and terminal key follows the token in use, not one
merely handed out; an agent that does not rotate keeps its token."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nodes  # noqa: E402

CENSUS = {"cpu": 2, "mem_mb": 4096, "arch": "x86_64", "system": "linux"}


class Rotation(unittest.TestCase):
    def setUp(self):
        nodes.configure(state=tempfile.mkdtemp())
        mint = nodes.enroll_mint("user:test", "box")
        got = nodes.enroll(nodes.authenticate(mint["token"]), CENSUS, "10.0.0.5", user="bb")
        self.nid, self.first = mint["id"], got["token"]

    def hello(self, rotates=True):
        return nodes.hello(self.nid, CENSUS, "10.0.0.5", rotates=rotates)

    def test_a_fresh_token_each_hello_live_once_used(self):
        key = nodes.screen_key(self.nid)
        new = self.hello()["token"]
        self.assertTrue(new.startswith("bbn_") and new != self.first)
        self.assertEqual(nodes.screen_key(self.nid), key, "the key is the token in use, not the one handed out")
        self.assertIn("node", nodes.authenticate(new))
        self.assertNotEqual(nodes.screen_key(self.nid), key, "...and moves once the new one is used")
        self.assertIn("node", nodes.authenticate(self.first), "the old one within its grace")

    def test_a_retired_token_after_its_grace_revokes_the_node(self):
        new = self.hello()["token"]
        nodes.authenticate(new)
        nodes._exec("UPDATE tokens SET expires = ? WHERE revoked = ?", (int(time.time()) - 1, nodes.TOKEN_RETIRED))
        self.assertEqual(nodes.authenticate(self.first), {"error": "credential revoked"})
        self.assertEqual(nodes.authenticate(new), {"error": "credential revoked"}, "the live one goes with it")
        rows = [r for r in nodes.token_attention() if r["kind"] == "token-reuse"]
        self.assertEqual([r["id"] for r in rows], [self.nid])

    def test_a_pending_one_never_used_is_dropped_at_the_next(self):
        a = self.hello()["token"]
        b = self.hello()["token"]
        self.assertEqual(nodes.authenticate(a), {"error": "credential revoked"})
        self.assertIn("node", nodes.authenticate(b))

    def test_an_agent_that_does_not_rotate_keeps_its_token(self):
        self.assertNotIn("token", self.hello(rotates=False))
        self.assertIn("node", nodes.authenticate(self.first))


if __name__ == "__main__":
    unittest.main()
