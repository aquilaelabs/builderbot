"""A node's toolchain versions are checked weekly like the controller's own
(the operator, 6 Oct: a node's tab said twelve days ago). The loop checked
only the controller's store, and a node's answers aged until somebody
pressed Check."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402

DAY = 86400
NOW = 1_800_000_000


def node(nid, **kw):
    return {"id": nid, "name": nid, "kind": "agent", "state": "online", "live": True,
            "reported": {"stores": {"toolchains": {"path": "/s"}}}} | kw


class NodeChecks(unittest.TestCase):
    def run_with(self, rows, jobs):
        queued = []

        class Nodes:
            @staticmethod
            def node_list():
                return rows

            @staticmethod
            def jobs_for(node_id=None, type=None, n=50):
                return jobs.get(node_id, [])

        was = toolchains.nodes, toolchains.node_job, toolchains.TOOLCHAINS
        toolchains.nodes = Nodes
        toolchains.node_job = lambda p, nid, action, names: queued.append((p, nid, action)) or {"ok": True, "job": "j"}
        toolchains.TOOLCHAINS = [{"name": "jdk"}]
        try:
            return toolchains.node_checks_due(now=NOW), queued
        finally:
            toolchains.nodes, toolchains.node_job, toolchains.TOOLCHAINS = was

    def test_a_node_checked_twelve_days_ago_is_checked(self):
        got, queued = self.run_with([node("n1")], {"n1": [
            {"state": "succeeded", "ended": NOW - 12 * DAY, "spec": {"action": "check"}}]})
        self.assertEqual(got, ["n1"])
        self.assertEqual(queued, [("system", "n1", "check")])

    def test_one_checked_this_week_is_left(self):
        got, _ = self.run_with([node("n1")], {"n1": [
            {"state": "succeeded", "ended": NOW - 2 * DAY, "spec": {"action": "check"}}]})
        self.assertEqual(got, [])

    def test_never_checked_is_checked(self):
        got, _ = self.run_with([node("n1")], {})
        self.assertEqual(got, ["n1"])

    def test_busy_offline_or_storeless_nodes_are_left(self):
        rows = [node("busy"), node("off", live=False), node("drain", state="draining"),
                node("bare", reported={}), node("ctl", kind="local")]
        got, _ = self.run_with(rows, {"busy": [{"state": "running", "spec": {"action": "install"}}]})
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main()
