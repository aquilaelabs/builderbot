"""The way back from an outage (R251): a node's agent reports the sessions
its gates held, the controller keeps them whitelisted, and the bell lists
each for its own account or an administrator."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import agentpkg  # noqa: E402
import nodes  # noqa: E402

agent = agentpkg.load("builderbot_agent_held")


class AgentReads(unittest.TestCase):
    def test_marks_under_the_session_home_are_reported(self):
        home = tempfile.mkdtemp()
        for base, uid, proj, sess in [(home, "u_1", "alpha", "claude-alpha"),
                                      (os.path.join(home, "users", "u_2"), "u_2", "beta", "u_2~claude-beta")]:
            d = os.path.join(base, ".cache", "builderbot", "u", uid, "project", proj)
            os.makedirs(d)
            with open(os.path.join(d, "held"), "w") as f:
                json.dump({"session": sess, "since": 99}, f)
        agent.SESSION["home"] = home
        got = sorted(agent.SessionsMixin.held_now(None), key=lambda h: h["project"])
        self.assertEqual(got, [{"project": "alpha", "uid": "u_1", "session": "claude-alpha", "since": 99},
                               {"project": "beta", "uid": "u_2", "session": "u_2~claude-beta", "since": 99}])


class ControllerKeeps(unittest.TestCase):
    def setUp(self):
        nodes.configure(state=tempfile.mkdtemp())
        mint = nodes.enroll_mint("user:test", "box")
        nodes.enroll(nodes.authenticate(mint["token"]), {"cpu": 2, "mem_mb": 4096, "arch": "x86_64",
                                                         "system": "linux", "session": {"up": True, "user": "b"}},
                     "10.0.0.5", user="bb")
        self.nid = mint["id"]

    def test_held_sessions_are_rows_for_their_account(self):
        r0 = nodes._rev[0]
        nodes.heartbeat(self.nid, {"held": [{"project": "alpha", "uid": "u_1", "session": "claude-alpha", "since": 50},
                                             {"project": "../x", "uid": "u 2", "session": "s;rm", "since": "x"},
                                             "junk"]}, "10.0.0.5")
        self.assertNotEqual(nodes._rev[0], r0, "a hold is news for the bell")
        with mock.patch.object(nodes, "node_list", lambda: [dict(nodes.node(self.nid), live=True)]):
            mine = nodes.held_attention("u_1", False)
            theirs = nodes.held_attention("u_9", False)
            admin = nodes.held_attention("u_9", True)
        self.assertEqual([(r["session"], r["key"]) for r in mine], [("claude-alpha", f"held:{self.nid}|claude-alpha@50")])
        self.assertEqual(theirs, [], "another account's session is not offered")
        self.assertEqual(len(admin), 2, "an administrator sees every hold")
        self.assertEqual(admin[1]["session"], "srm", "what a node says is whitelisted")


if __name__ == "__main__":
    unittest.main()
