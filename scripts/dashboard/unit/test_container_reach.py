"""Where a session's word on a container is looked for (B649): on every node
its project names now, the node set and the hosting nodes under Hosts its
containers on, and on no other, so one left on a node taken off the project
is the project's still and the session's no longer (the operator, 11 Oct).
Drives containers.session_verb with devapp's node hooks stood in for."""
import contextlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import containers  # noqa: E402
import devapp  # noqa: E402


class Reach(unittest.TestCase):
    def setUp(self):
        self.visited = []
        saved = {k: getattr(devapp, k) for k in ("nodes_of", "project_daemon", "on_node", "containers", "row_named",
                                                 "owner_of", "hosts_of", "_load", "_instance_node")}
        self.addCleanup(lambda: [setattr(devapp, k, v) for k, v in saved.items()])
        csaved = {k: getattr(containers, k) for k in ("owned_container", "container_logs")}
        self.addCleanup(lambda: [setattr(containers, k, v) for k, v in csaved.items()])

        @contextlib.contextmanager
        def on_node(nid):
            self.visited.append(nid)
            self.here = nid
            yield
        devapp.nodes_of = lambda p: ["n_own"]
        devapp.project_daemon = lambda p: "n_own"
        devapp.on_node = on_node
        devapp.containers = lambda: {"containers": []}
        devapp.row_named = lambda name: None
        devapp.owner_of = lambda proj, inst=None, rec=None: (rec or {}).get("owner", "")
        devapp.hosts_of = lambda p: []
        devapp._load = lambda: {}
        devapp._instance_node = lambda proj, inst: (devapp._load().get(proj, {}).get(inst) or {}).get("node", "")
        # The probe lives on the hosting node and nowhere else.
        self.lives = "n_host"
        containers.owned_container = lambda name: (({"name": name}, "alpha") if self.here == self.lives else (None, ""))
        containers.container_logs = lambda name: {"text": f"log of {name}"}

    def test_a_hosting_node_the_project_names_is_looked_on(self):
        devapp.hosts_of = lambda p: ["n_host"]
        got, status = containers.session_verb("alpha", {}, "logs", "probe", {})
        self.assertEqual((status, got.get("text")), (200, "log of probe"), got)
        self.assertEqual(self.visited[:2], ["n_own", "n_host"], "its own nodes first, then the hosting node")

    def test_the_node_an_instance_was_put_on_is_looked_on(self):
        # bb devapp new --node: a node the project neither works on nor
        # names as a host, which the session that made it could not reach.
        self.lives = "n_vps"
        devapp._load = lambda: {"alpha": {"site": {"owner": "alpha", "node": "n_vps"}}}
        got, status = containers.session_verb("alpha", {}, "logs", "probe", {})
        self.assertEqual((status, got.get("text")), (200, "log of probe"), got)
        self.assertEqual(devapp.container_nodes("alpha"), ["n_own", "n_vps"])

    def test_a_node_taken_off_the_project_is_not(self):
        got, status = containers.session_verb("alpha", {}, "logs", "probe", {})
        self.assertEqual(status, 403, got)
        self.assertNotIn("n_host", self.visited, "nothing of the project's is looked for off its nodes")


if __name__ == "__main__":
    unittest.main()
