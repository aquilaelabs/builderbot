"""A hello that takes its own census while one hello_step asked for is still
on its way lets that older one go (B851): said after the job's own hello, it
put back what the job had just taken away (a removed GPU driver read as
waiting again until the next ten-minute hello)."""
import threading
import unittest

import agentpkg  # noqa: E402
agent = agentpkg.load("builderbot_agent_census_stale")
Agent = agent.module("agent").Agent


class Ctl:
    def __init__(self):
        self.said = []

    def call(self, verb, body, timeout=30):
        self.said.append(body["census"])
        return 503, {}                     # nothing after a refusal runs


class CensusStale(unittest.TestCase):
    def test_a_census_on_its_way_is_let_go_and_taken_again(self):
        a = Agent.__new__(Agent)
        a.ctl, a.state = Ctl(), {}
        a.hello_at, a.hello_said, a.census_asked = 0, True, True
        a.census_stale, a.census_next, a.census_thread = False, None, None
        a.running_ids = lambda: []
        a.keep_report = lambda: {}
        a.census_beating = lambda: {"driver": "absent"}
        gate = threading.Event()
        taken = iter([{"driver": "waiting"}, {"driver": "absent"}])

        def take():
            gate.wait(5)
            return next(taken)
        a.census_take = take
        self.assertIsNone(a.hello_step())            # the asked-for census starts beside the loop
        a.hello()                                    # the job's own hello, while it is on its way
        self.assertTrue(a.census_stale)
        gate.set()
        a.census_thread.join(5)
        self.assertIsNone(a.hello_step())            # the old one let go, a fresh one started
        a.census_thread.join(5)
        a.hello_step()
        self.assertEqual(a.ctl.said, [{"driver": "absent"}, {"driver": "absent"}])


if __name__ == "__main__":
    unittest.main()
