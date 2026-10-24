"""When the agent a node runs was built (R131): the controller's own build,
written when the node first reports the agent it ships, kept with that
digest, gone with another."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import nodes  # noqa: E402


class Built(unittest.TestCase):
    def test_written_for_the_shipped_agent_and_kept_with_its_digest(self):
        ag = {"digest": "sha256:old"}
        nodes.agent_built(ag, "sha256:new", "sha256:new", "2026-10-23T20:12Z")
        self.assertEqual(ag["built"], "2026-10-23T20:12Z")
        ag["digest"] = "sha256:new"
        nodes.agent_built(ag, "sha256:new", "sha256:newer", "2026-10-30T09:00Z")
        self.assertEqual(ag["built"], "2026-10-23T20:12Z", "a newer controller does not re-date the old agent")

    def test_another_digest_takes_it_away_and_an_unknown_one_says_nothing(self):
        ag = {"digest": "sha256:a", "built": "2026-10-01T00:00Z"}
        nodes.agent_built(ag, "sha256:b", "sha256:c", "2026-10-23T20:12Z")
        self.assertNotIn("built", ag)

    def test_an_unstamped_build_writes_nothing(self):
        ag = {}
        nodes.agent_built(ag, "sha256:a", "sha256:a", "")
        self.assertNotIn("built", ag)


if __name__ == "__main__":
    unittest.main()
