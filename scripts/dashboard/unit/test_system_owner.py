"""System, the owner of what BuilderBot deploys itself (R180): no project, so
never a deleted one; given every compose project on its node by the
containers' network map, with `all` for an agent that reads it; and set by
the deployment alone, never through the owner picker."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import containers  # noqa: E402
import devapp  # noqa: E402


class SystemOwner(unittest.TestCase):
    def setUp(self):
        saved = {k: getattr(devapp, k) for k in ("_load", "_owners", "_instance_node", "reads_of", "_node_here", "WORKSPACE")}
        self.addCleanup(lambda: [setattr(devapp, k, v) for k, v in saved.items()])
        csaved = containers._known_container
        self.addCleanup(setattr, containers, "_known_container", csaved)
        devapp._load = lambda: {"alpha": {"main": {"node": "n1"}}, "beta": {"main": {"node": "n1"}}}
        devapp._instance_node = lambda p, i: "n1"
        devapp._owners = lambda: {"n1": {"nginx-n1": devapp.SYSTEM, "radarr": "alpha"}}
        devapp.reads_of = lambda p: ["beta"] if p == "alpha" else []
        devapp._node_here = lambda: "n1"

    def test_system_is_no_deleted_project(self):
        self.assertFalse(devapp.owner_gone(devapp.SYSTEM))
        self.assertEqual(devapp.owner_label(devapp.SYSTEM), "System")

    def test_the_map_gives_system_everything_and_nobody_system(self):
        m = devapp.container_net_own("n1")
        self.assertEqual(sorted(m["nginx-n1"]["to"]), sorted({"nginx-n1", "radarr", "alpha", "beta"}))
        self.assertTrue(m["nginx-n1"].get("all"), "an agent that reads `all` adds what the controller never named")
        self.assertEqual(sorted(m["alpha"]["to"]), ["alpha", "beta", "radarr"], "alpha reads beta, and nothing of System's")
        self.assertNotIn("all", m["alpha"])

    def test_no_picker_sets_it(self):
        containers._known_container = lambda name: {"name": name, "ours": False}
        r = containers.set_container_owner("stranger", devapp.SYSTEM)
        self.assertIn("BuilderBot's own", r.get("error", ""))


if __name__ == "__main__":
    unittest.main()
