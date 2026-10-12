"""What on a shared toolchain store no node runs from any more is offered
for removal (R196): a retired or unknown node's directory, never a live
node's, never `shared` or the controller's own <os>-<arch>."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402


def node(nid, name, scope, roots=(), state="online"):
    return {"id": nid, "name": name, "kind": "agent", "state": state, "live": state == "online",
            "reported": {"os": "linux x86_64", "store_dirs": {"top": [], "android": [], "roots": list(roots)},
                         "stores": {"toolchains": {"path": "/s", "id": "share1", "scope": scope}}}}


class Cleanable(unittest.TestCase):
    def setUp(self):
        test = self
        self.nodes_ = []

        class Nodes:
            @staticmethod
            def node(nid):
                return next((n for n in test.nodes_ if n["id"] == nid), None)

            @staticmethod
            def node_list(all=False):
                return [n for n in test.nodes_ if all or n["state"] != "retired"]
        saved = toolchains.nodes
        self.addCleanup(setattr, toolchains, "nodes", saved)
        toolchains.nodes = Nodes()

    def test_a_retired_or_unknown_nodes_directory_and_nothing_else(self):
        roots = ["linux-x86_64", "n_aaaa1111", "n_cccc3333", "n_dddd4444", "n_eeee5555", "shared"]
        self.nodes_ = [node("n_aaaa1111", "bb-sandbox", "n_aaaa1111", roots=roots),
                       node("n_cccc3333", "redhat", "n_cccc3333", roots=roots),
                       node("n_dddd4444", "gone", "n_dddd4444", state="retired")]
        got = {c["dir"]: c["what"] for c in toolchains.cleanable("n_aaaa1111")}
        self.assertEqual(set(got), {"n_dddd4444", "n_eeee5555"},
                         "a retired node's and an unknown one's; not a live node's, shared or the controller's")
        self.assertIn("gone's, a node since retired", got["n_dddd4444"])
        self.assertIn("no longer enrolled here", got["n_eeee5555"])
        self.assertEqual({c["dir"] for c in toolchains.cleanable("n_cccc3333")}, set(got), "the same from any node on the share")

    def test_nothing_reported_offers_nothing(self):
        self.nodes_ = [node("n_aaaa1111", "bb-sandbox", "n_aaaa1111")]
        self.assertEqual(toolchains.cleanable("n_aaaa1111"), [])


class HelloKeepsTheListing(unittest.TestCase):
    """The hello's whitelist of a node's census keeps store_dirs.roots, which
    cleanable reads: with top, android and incomplete alone nothing was ever
    offered (bb-dev-sandbox, 12 Oct)."""

    def test_roots_come_through(self):
        import nodes
        got = nodes._census({"store_dirs": {"top": ["go"], "android": [], "incomplete": [],
                                            "roots": ["linux-x86_64", "n_aaaa1111", "shared"], "junk": 1}})
        self.assertEqual(got["store_dirs"]["roots"], ["linux-x86_64", "n_aaaa1111", "shared"])
        self.assertNotIn("junk", got["store_dirs"])


if __name__ == "__main__":
    unittest.main()
