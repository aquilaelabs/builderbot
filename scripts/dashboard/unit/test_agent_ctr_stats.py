"""What each running container uses, read by the agent once a minute for the
hour the controller keeps (R218 step 9): one docker stats, its lines read
into [cpu %, memory %] by name, a line it cannot read skipped, and nothing at
all said between two minutes or where there is no docker."""
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agentpkg  # noqa: E402

agent = agentpkg.load("builderbot_agent_ctr_stats")


class CtrStats(unittest.TestCase):
    def fake_docker(self, out):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "docker")
        with open(path, "w") as f:
            f.write("#!/bin/sh\ncat <<'EOF'\n" + out + "EOF\n")
        os.chmod(path, 0o755)
        agent.DOCKER_BIN = path

    def test_a_minutes_sample_is_read_into_numbers(self):
        self.fake_docker("web-1\t12.50%\t3.25%\nweird line\ndb-1\t--\t1%\nnginx\t0.00%\t0.40%\n")
        me = types.SimpleNamespace()
        got = agent.SessionsMixin.stats_now(me)
        self.assertEqual(got, {"web-1": [12.5, 3.25], "nginx": [0.0, 0.4]})
        # ...and nothing again until the minute is up.
        self.assertIsNone(agent.SessionsMixin.stats_now(me))

    def test_no_docker_says_nothing(self):
        agent.DOCKER_BIN = "/nonexistent/docker"
        self.assertIsNone(agent.SessionsMixin.stats_now(types.SimpleNamespace()))


if __name__ == "__main__":
    unittest.main()
