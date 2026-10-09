"""A node is heard while its loop takes a census (the operator, 7 Oct): a
hello said on the loop, after a job changed the machine, takes the census
there, over a minute on a busy node, and the controller read the node as
not answering on every project row. census_beating tells it the node is
there every BEAT_S meanwhile, and stops when the census is done; the
controller's beat stamps last_seen and touches nothing else."""
import json
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import agentpkg  # noqa: E402
agent = agentpkg.load("builderbot_agent_beat")
agent.log = lambda *a, **k: None
sys.path.insert(0, os.path.join(HERE, ".."))
import nodes  # noqa: E402


class Ctl:
    def __init__(self):
        self.calls = []

    def call(self, verb, body=None, timeout=30):
        self.calls.append((verb, time.monotonic()))
        return 200, {}


class Beating(unittest.TestCase):
    def test_a_slow_census_beats_and_stops(self):
        saved = agent.BEAT_S
        self.addCleanup(setattr, agent, "BEAT_S", saved)
        agent.BEAT_S = 0.05
        a = object.__new__(agent.Agent)
        a.ctl = Ctl()
        a.census_take = lambda: (time.sleep(0.3), {"census": True})[1]
        self.assertEqual(a.census_beating(), {"census": True})
        beats = len([c for c in a.ctl.calls if c[0] == "beat"])
        self.assertGreaterEqual(beats, 3, "beat while the census ran")
        time.sleep(0.2)
        self.assertEqual(len([c for c in a.ctl.calls if c[0] == "beat"]), beats, "...and not after")

    def test_a_quick_census_says_nothing(self):
        a = object.__new__(agent.Agent)
        a.ctl = Ctl()
        a.census_take = lambda: {"census": True}
        a.census_beating()
        self.assertEqual(a.ctl.calls, [])


class Beat(unittest.TestCase):
    def test_the_controller_stamps_last_seen_and_nothing_else(self):
        nodes.configure(state=tempfile.mkdtemp())
        mint = nodes.enroll_mint("user:test", "box")
        nodes.enroll(nodes.authenticate(mint["token"]), {"cpu": 2, "mem_mb": 4096, "arch": "x86_64",
                                                         "system": "linux", "session": {"up": True, "user": "b"}},
                     "10.0.0.5", user="bb")
        nid = mint["id"]
        nodes._exec("UPDATE nodes SET agent = json_set(agent, '$.last_seen', 1) WHERE id = ?", (nid,))
        before = nodes.node(nid)
        nodes.beat(nid)
        after = nodes.node(nid)
        self.assertGreater(after["agent"]["last_seen"], time.time() - 5)
        self.assertEqual(after["reported"], before["reported"])
        self.assertEqual(json.dumps(after["agent"].get("version")), json.dumps(before["agent"].get("version")))


if __name__ == "__main__":
    unittest.main()
