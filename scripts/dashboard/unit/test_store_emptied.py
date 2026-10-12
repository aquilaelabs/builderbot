"""A toolchain whose directory is gone from a node's store reads as not
installed, whatever the last check or an install since it said (B671, the
operator, 12 Oct: the store wiped by hand to install everything again, and
every row still read current). The node's listing comes with every hello,
so a deletion by hand is read within one, a controller restart included."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402

CHECK = "== bb toolchains check\njdk\t21.0.4\t21.0.5\tupdate\ngo\t1.22.0\t1.22.0\tcurrent\n"
JOBS = [{"id": "i1", "state": "succeeded", "ended": 200, "spec": {"action": "install", "names": ["jdk", "go"]}},
        {"id": "c1", "state": "succeeded", "ended": 100, "spec": {"action": "check"}}]


def node(store_dirs):
    rep = {"os": "linux x86_64", "stores": {"toolchains": {"path": "/s", "scope": "n_1"}}}
    if store_dirs is not None:
        rep["store_dirs"] = store_dirs
    return {"id": "n1", "name": "box", "kind": "agent", "state": "online", "live": True, "reported": rep}


class Emptied(unittest.TestCase):
    def run_with(self, n):
        class Nodes:
            @staticmethod
            def node(nid):
                return n

            @staticmethod
            def node_list(**k):
                return [n]

            @staticmethod
            def jobs_for(node_id=None, type=None, n=50, active=False, **k):
                return [] if active else JOBS

            @staticmethod
            def job_tail(jid, n=4000):
                return CHECK if jid == "c1" else ""

            def __getattr__(self, name):
                return lambda *a, **k: None
        was = toolchains.nodes
        toolchains.nodes = Nodes()
        toolchains._node_checks.clear()
        try:
            items = {i["name"]: i for i in toolchains.payload_for_node("n1").get("items", [])}
            bell = toolchains.attention({"p": "n1"})
            return items, bell
        finally:
            toolchains.nodes = was

    def test_an_emptied_store_frees_every_row(self):
        items, bell = self.run_with(node({"top": [], "android": [], "incomplete": [], "roots": ["n_1", "shared"]}))
        for name in ("jdk", "go"):
            self.assertFalse(items[name]["installed"], f"{name} is not there")
            self.assertFalse(items[name]["unknown"], "an empty listing is an empty store, not an unknown one")
            self.assertEqual(items[name]["state"], "absent", f"{name} reads absent, not what the check said")
        self.assertEqual([r for r in bell if r.get("kind") == "toolchain"], [], "nothing to update in the bell")

    def test_one_deleted_by_hand_is_read_from_the_listing(self):
        items, bell = self.run_with(node({"top": ["go"], "android": [], "incomplete": [], "roots": ["n_1"]}))
        self.assertFalse(items["jdk"]["installed"])
        self.assertEqual(items["jdk"]["state"], "absent")
        self.assertTrue(items["go"]["installed"])
        self.assertEqual(items["go"]["state"], "current", "the install since the check made it current")
        self.assertEqual([t["name"] for r in bell if r.get("kind") == "toolchain" for t in r["tools"]], [])

    def test_a_node_that_has_not_listed_its_store_is_still_unknown(self):
        items, _ = self.run_with(node(None))
        self.assertTrue(items["jdk"]["unknown"])
        self.assertEqual(items["jdk"]["state"], "current", "the check and the install since it stand")


if __name__ == "__main__":
    unittest.main()
