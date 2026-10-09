"""A dev instance on a node holding synced copies (R163 step 4): its own
/workspace is the projects root as the share mounted there was, so the path
mapping takes it as such with no mount in its census."""
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
            "n_share": {"id": "n_share", "kind": "agent", "config": {}, "reported": {
                "mounts": [{"path": "/workspace", "mounted": True}]}},
            "n_none": {"id": "n_none", "kind": "agent", "config": {}, "reported": {"mounts": []}}})

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

    def test_a_node_on_the_share_is_judged_by_its_mount_as_before(self):
        self.on("n_share")
        self.assertTrue(devapp._node_mounts_at("/workspace"))
        self.on("n_none")
        self.assertFalse(devapp._node_mounts_at("/workspace"))
        self.assertFalse(devapp._daemon_mounts("/workspace"))


if __name__ == "__main__":
    unittest.main()
