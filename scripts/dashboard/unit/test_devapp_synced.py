"""A dev instance on a node holding synced copies (R163 step 4): its own
/workspace is the projects root, so the path mapping takes it as such with
no mount in its census; every agent node holds them unless taken off its
copy (R164), and the controller's own node never does."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402


class Queue:
    def __init__(self, rows):
        self.rows = rows

    def node(self, nid):
        return self.rows.get(nid)


class Synced(unittest.TestCase):
    def setUp(self):
        self.was = (devapp.WORKSPACE, devapp.queue, getattr(devapp._node_ctx, "node", None))
        devapp.WORKSPACE = Path("/workspace")
        devapp.queue = Queue({
            "n_sync": {"id": "n_sync", "kind": "agent", "config": {"workspace": "sync"}, "reported": {"mounts": []}},
            "n_plain": {"id": "n_plain", "kind": "agent", "config": {}, "reported": {"mounts": []}},
            "n_off": {"id": "n_off", "kind": "agent", "config": {"workspace": "off"}, "reported": {"mounts": []}},
            "local": {"id": "local", "kind": "local", "config": {}, "reported": {"mounts": []}}})

    def tearDown(self):
        devapp.WORKSPACE, devapp.queue, devapp._node_ctx.node = self.was

    def on(self, nid):
        devapp._node_ctx.node = nid

    def test_a_synced_node_has_the_projects_root_with_no_mount(self):
        self.on("n_sync")
        self.assertTrue(devapp._node_mounts_at("/workspace"))
        self.assertTrue(devapp._daemon_mounts("/workspace/"))

    def test_only_the_projects_root(self):
        self.on("n_sync")
        self.assertFalse(devapp._node_mounts_at("/devdata"))
        self.assertFalse(devapp._daemon_mounts("/mnt/SDK"))

    def test_every_agent_node_but_one_taken_off_its_copy(self):
        self.on("n_plain")
        self.assertTrue(devapp._node_mounts_at("/workspace"), "a node with no workspace word holds its copy")
        self.on("n_off")
        self.assertFalse(devapp._node_mounts_at("/workspace"))
        self.on("local")
        self.assertFalse(devapp._node_mounts_at("/workspace"), "the controller's own node holds the original")

    def test_a_bind_the_daemon_cannot_have_is_named(self):
        """A compose binding into the project, addressed to a node taken off
        its copy: the daemon there has no /workspace, docker would mount an
        empty directory, and problems() says so before anything starts."""
        import tempfile
        with tempfile.TemporaryDirectory() as ws:
            devapp.WORKSPACE = Path(ws)
            os.makedirs(os.path.join(ws, "alpha"))
            was = devapp._pairs
            devapp._pairs = lambda: []
            try:
                cfg = {"services": {"app": {"volumes": [f"{ws}/alpha/data:/data"]}}}
                self.on("n_off")
                got = devapp.problems("alpha", cfg)
                self.assertEqual(len(got), 1, got)
                self.assertIn("this container's path", got[0])
                self.on("n_plain")
                self.assertEqual(devapp.problems("alpha", cfg), [], "a node holding its copy has it")
            finally:
                devapp._pairs = was


if __name__ == "__main__":
    unittest.main()
