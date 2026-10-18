"""A recipe's system packages reach the machine whole (B836): the agent read
the first 64 and dropped the rest without a word, and Playwright with
WebKit's libraries is past that on apt, so WebKit installed and could not
launch. Every package the shipped playwright recipe names is asked about,
and a list past the cap stops at the cap, not at 64."""
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import agentpkg  # noqa: E402
agent = agentpkg.load("builderbot_agent_sysdeps")
CATALOG = os.path.join(HERE, "..", "..", "..", "config", "toolchains.json")


class SysdepsTest(unittest.TestCase):
    def test_the_playwright_recipe_is_read_whole(self):
        cat = json.load(open(CATALOG))
        apt = next(p for p in cat["toolchains"] if p["name"] == "playwright")["system"]["apt"]
        self.assertGreater(len(apt), 64, "the recipe carries WebKit's libraries too")
        self.assertLessEqual(len(apt), agent.SYSDEPS_MAX)
        # A query that finds nothing installed: every entry comes back,
        # the first alternative of each where the repositories cannot say.
        agent.pkg_available = lambda fam, name: True
        missing, other = agent.sysdeps_missing(cat, "playwright", "apt", ["false"])
        self.assertIsNone(other)
        self.assertEqual(len(missing), len(apt))
        self.assertIn("libgtk-4-1", missing)
        self.assertIn("libx264-165", missing)

    def test_a_list_past_the_cap_stops_there(self):
        names = [f"pkg{i}" for i in range(agent.SYSDEPS_MAX + 20)]
        cat = {"toolchains": [{"name": "big", "system": {"apt": names}}]}
        missing, _ = agent.sysdeps_missing(cat, "big", "apt", ["false"])
        self.assertEqual(len(missing), agent.SYSDEPS_MAX)


if __name__ == "__main__":
    unittest.main()
