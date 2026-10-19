"""System, the owner of what BuilderBot deploys itself (R180): no project, so
never a deleted one; given every compose project on its node by the
containers' network map's `all`; and set by the deployment alone, never
through the owner picker."""
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
        self.assertEqual(m["nginx-n1"]["to"], ["nginx-n1"])
        self.assertTrue(m["nginx-n1"].get("all"), "`all` reaches every compose project, the ones the controller never named included")
        self.assertEqual(sorted(m["alpha"]["to"]), ["alpha", "beta", "radarr"], "alpha reads beta, and nothing of System's")
        self.assertNotIn("all", m["alpha"])

    def test_a_strangers_name_must_be_unique_for_the_project_it_is_given_to(self):
        """A container BuilderBot did not start keeps the name docker gave it,
        so giving it to a project is refused while that name is an instance's
        compose name, or a stranger already the project's on another node
        (the operator, 11 Oct)."""
        containers._known_container = lambda name: {"name": name, "ours": False}
        saved = {k: getattr(devapp, k) for k in ("row_named", "on_project_node", "node_name", "write_json")}
        self.addCleanup(lambda: [setattr(devapp, k, v) for k, v in saved.items()])
        devapp.on_project_node = lambda whose, node, ship=False: ("", node)
        devapp.node_name = lambda nid: {"n1": "home", "n2": "vps"}.get(nid, nid)
        devapp.write_json = lambda path, d: None
        devapp.row_named = lambda name: ("alpha", "main") if name == "alpha" else None
        self.assertIn("alpha's container", containers.set_container_owner("alpha", "beta")["error"])
        devapp._owners = lambda: {"n2": {"radarr": "alpha"}, "n1": {}}
        self.assertIn("already has a container called radarr on vps", containers.set_container_owner("radarr", "alpha")["error"])
        self.assertTrue(containers.set_container_owner("sonarr", "alpha").get("ok"), "a name nobody else of alpha's has is given")

    def test_no_picker_sets_it(self):
        containers._known_container = lambda name: {"name": name, "ours": False}
        r = containers.set_container_owner("stranger", devapp.SYSTEM)
        self.assertIn("BuilderBot's own", r.get("error", ""))


if __name__ == "__main__":
    unittest.main()
