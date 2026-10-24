"""The memory fence as a node's census says it (R110 step 4): the slice's
limit and what is in it, or None where there is no fence or no limit."""
import os
import shutil
import tempfile
import unittest

import agentpkg  # noqa: E402
agent = agentpkg.load("builderbot_agent_fence")
agent.log = lambda *a, **k: None


class Fence(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="fence-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.was = agent.Sampler.FENCE_DIR
        self.addCleanup(setattr, agent.Sampler, "FENCE_DIR", self.was)
        agent.Sampler.FENCE_DIR = self.dir

    def write(self, mx, cur):
        for name, v in (("memory.max", mx), ("memory.current", cur)):
            with open(os.path.join(self.dir, name), "w") as f:
                f.write(v + "\n")

    def test_a_limit_and_what_is_in_it(self):
        self.write(str(14 << 30), str(3 << 30))
        self.assertEqual(agent.Sampler._fence(), {"max_mb": 14 << 10, "used_mb": 3 << 10})

    def test_no_limit_or_no_slice_is_none(self):
        self.write("max", "100")
        self.assertIsNone(agent.Sampler._fence())
        agent.Sampler.FENCE_DIR = os.path.join(self.dir, "gone")
        self.assertIsNone(agent.Sampler._fence())


if __name__ == "__main__":
    unittest.main()
