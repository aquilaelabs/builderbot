"""A node following its controller to a new home (R90 step 12): the move
off the hello kept in node.json, the knock on the new address with the
node's own token, the answer checked against the challenge it holds, and
the controller re-adopted or the knock refused."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import agentpkg  # noqa: E402


class Knock(unittest.TestCase):
    def setUp(self):
        self.agent = agentpkg.load("builderbot_agent_move")
        self.mod = sys.modules[self.agent.Agent.__module__]
        self.saved = []
        self.mod.save_state = lambda st: self.saved.append(dict(st))
        self.a = object.__new__(self.agent.Agent)
        self.a.state = {"controller": "https://old.example", "token": "tok", "pin": "", "node_id": "n_1",
                        "move": {"url": "https://new.example", "expect": "c" * 64}}
        self.a.quiet = 0
        self.a.hello_at = 1
        self.a.ctl = None

    def fake(self, status, answer, url="", pin=""):
        calls = []

        class Ctl:
            def __init__(self, u, token, p=""):
                calls.append((u, token, p))

            def call(self, verb, body=None, timeout=30, **kw):
                calls.append((verb, body))
                return status, {"answer": answer, "url": url, "pin": pin}
        self.mod.Controller = Ctl
        return calls

    def test_the_right_answer_moves_the_node(self):
        calls = self.fake(200, "c" * 64, url="https://new.example/", pin="AA:BB")
        self.assertTrue(self.a.knock())
        self.assertEqual(calls[0], ("https://new.example", "tok", ""), "knocked with the node's own token, no pin yet")
        self.assertEqual(calls[1], ("moved", {"node": "n_1"}))
        self.assertEqual((self.a.state["controller"], self.a.state["pin"]), ("https://new.example", "AA:BB"))
        self.assertNotIn("move", self.a.state)
        self.assertTrue(self.saved and self.saved[-1]["controller"] == "https://new.example")
        self.assertEqual(self.a.hello_at, 0, "a hello to the new home comes next")

    def test_a_wrong_or_missing_answer_leaves_the_node_where_it_is(self):
        self.fake(200, "d" * 64)
        self.assertFalse(self.a.knock())
        self.assertEqual(self.a.state["controller"], "https://old.example")
        self.fake(404, "")
        self.assertFalse(self.a.knock())
        self.a.state.pop("move")
        self.assertFalse(self.a.knock(), "nothing to knock on")


if __name__ == "__main__":
    unittest.main()
