"""A toolchain installed on a node after its last check reads as current,
not as the update the check found (the operator, 6 Oct: an updated JDK sat
unticked with 'update available' until somebody checked again)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402

NODE = {"id": "n1", "name": "box", "kind": "agent", "state": "online", "live": True,
        "reported": {"os": "linux x86_64", "toolchains": {"jdk": "21.0.4", "go": "1.22.0"},
                     "stores": {"toolchains": {"path": "/s"}}}}
CHECK = "== bb toolchains check\njdk\t21.0.4\t21.0.5\tupdate\ngo\t1.22.0\t1.23.0\tupdate\n"


class AfterInstall(unittest.TestCase):
    def payload(self, jobs):
        class Nodes:
            @staticmethod
            def node(nid):
                return NODE

            @staticmethod
            def jobs_for(node_id=None, type=None, n=50, **k):
                return jobs

            @staticmethod
            def job_tail(jid, n=4000):
                return CHECK if jid == "c1" else ""

            def __getattr__(self, name):
                return lambda *a, **k: None
        was = toolchains.nodes
        toolchains.nodes = Nodes()
        toolchains._node_checks.clear()
        try:
            return {i["name"]: i for i in toolchains.payload_for_node("n1").get("items", [])}
        finally:
            toolchains.nodes = was

    def test_installed_after_the_check_reads_current_and_the_rest_keep_the_update(self):
        got = self.payload([
            {"id": "i1", "state": "succeeded", "ended": 200, "spec": {"action": "install", "names": ["jdk"]}},
            {"id": "c1", "state": "succeeded", "ended": 100, "spec": {"action": "check"}},
        ])
        self.assertEqual(got["jdk"]["state"], "current")
        self.assertEqual(got["go"]["state"], "update")

    def test_a_failed_install_leaves_the_update(self):
        got = self.payload([
            {"id": "i1", "state": "failed", "ended": 200, "spec": {"action": "install", "names": ["jdk"]}},
            {"id": "c1", "state": "succeeded", "ended": 100, "spec": {"action": "check"}},
        ])
        self.assertEqual(got["jdk"]["state"], "update")


if __name__ == "__main__":
    unittest.main()
