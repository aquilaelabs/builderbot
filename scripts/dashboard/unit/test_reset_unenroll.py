"""Reset un-enrolls the nodes it is given first (the operator, 12 Oct): a
node BuilderBot set up and can reach is uninstalled, any other is retired
here, and a refusal (a node in use) comes back named rather than skipped."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nodes  # noqa: E402


class ResetUnenroll(unittest.TestCase):
    def setUp(self):
        self.rows = {
            "n_aaaa1111": {"id": "n_aaaa1111", "name": "sandbox", "kind": "agent", "state": "online", "live": True,
                           "reported": {"sandbox": True}},
            "n_bbbb2222": {"id": "n_bbbb2222", "name": "guest", "kind": "agent", "state": "online", "live": True,
                           "reported": {}},
            "n_cccc3333": {"id": "n_cccc3333", "name": "gone", "kind": "agent", "state": "retired", "live": False,
                           "reported": {}},
        }
        self.calls = []
        saved = {k: getattr(nodes, k) for k in ("node", "node_uninstall", "node_state")}
        self.addCleanup(lambda: [setattr(nodes, k, v) for k, v in saved.items()])
        nodes.node = lambda nid: self.rows.get(nid)
        nodes.node_uninstall = lambda p, nid, rings: (self.calls.append(("uninstall", nid, rings))
                                                      or {"ok": True, "job": "j_1"})
        nodes.node_state = lambda p, nid, st: self.calls.append((st, nid)) or {"ok": True}

    def test_each_node_the_way_it_can_be_taken_off(self):
        out = nodes.reset_unenroll("op", ["n_aaaa1111", "n_bbbb2222", "n_cccc3333", "n_nope"], stores=True)
        self.assertEqual([(x["name"], x["how"]) for x in out], [("sandbox", "uninstall"), ("guest", "retired")])
        self.assertEqual(self.calls[0], ("uninstall", "n_aaaa1111", {"stores": True, "configured": True, "doors": True}))
        self.assertEqual(self.calls[1], ("retired", "n_bbbb2222"))
        self.assertEqual(out[0]["job"], "j_1")

    def test_a_refusal_comes_back_named(self):
        nodes.node_uninstall = lambda p, nid, rings: {"error": "sandbox is in use: 1 session running there"}
        out = nodes.reset_unenroll("op", ["n_aaaa1111"])
        self.assertEqual(out[0]["error"], "sandbox is in use: 1 session running there")


if __name__ == "__main__":
    unittest.main()
