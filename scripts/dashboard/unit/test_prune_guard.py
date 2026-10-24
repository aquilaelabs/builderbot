"""The Containers page's prunes pass devapp's docker guard exactly as
PRUNES spells them, and a prune spelled any other way does not (B245: two
of the four were refused as a bug in BuilderBot)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import devapp  # noqa: E402


class PruneGuard(unittest.TestCase):
    def test_every_prune_the_page_offers_passes(self):
        for kind, argv in devapp.PRUNES.items():
            self.assertEqual(devapp._guard([devapp.DOCKER, *argv]), "", kind)

    def test_a_prune_spelled_otherwise_is_refused(self):
        for argv in (["image", "prune", "-a", "-f"], ["volume", "prune", "-f", "--all"],
                     ["builder", "prune", "-a", "-f"], ["system", "prune", "-f"]):
            self.assertTrue(devapp._guard([devapp.DOCKER, *argv]), argv)


class PruneTime(unittest.TestCase):
    def test_a_prune_on_a_node_gets_its_minutes_and_a_start_its_seconds(self):
        asked = []
        was = devapp.queue
        self.addCleanup(setattr, devapp, "queue", was)

        class Q:
            @staticmethod
            def run_wait(principal, nid, argv, timeout, forget):
                asked.append(timeout)
                return {"code": 0, "out": ""}
        devapp.queue = Q
        n = {"id": "n_1", "name": "box"}
        devapp._agent_exec(n, [devapp.DOCKER, *devapp.PRUNES["cache"]], 600)
        devapp._agent_exec(n, [devapp.DOCKER, "start", "web"], 600)
        self.assertEqual(asked, [600, 25])


if __name__ == "__main__":
    unittest.main()
