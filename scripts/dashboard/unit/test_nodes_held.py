"""nodes.held(): inside one block each node row is read from the store once
(the operator, 17 Oct: the status read asked for the same rows dozens of
times, each ask queued on the store's one lock), handed out as a copy, and
read fresh again once the block ends."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import nodes  # noqa: E402


class Held(unittest.TestCase):
    def setUp(self):
        self.asked = []
        self.real = nodes._rows

        def rows(sql, args=()):
            self.asked.append(sql)
            if "FROM nodes" in sql:
                row = {k: "{}" for k in nodes._JSON_COLS}
                row.update({"id": "n_a", "name": "a", "kind": "agent", "state": "online",
                            "reported": '{"gpu": "card"}', "created": 1})
                return [row]
            return []
        nodes._rows = rows

    def tearDown(self):
        nodes._rows = self.real

    def reads(self):
        return sum(1 for q in self.asked if "FROM nodes" in q)

    def test_once_inside_a_block(self):
        with nodes.held():
            first = nodes.node("n_a") or {}
            for _ in range(5):
                nodes.node("n_a")
            nodes.node_list()
            nodes.node_list()
            with nodes.held():
                nodes.node("n_a")
        self.assertEqual(self.reads(), 2, "one read for the row and one for the list, nested blocks sharing them")
        self.assertEqual(first["reported"], {"gpu": "card"}, "the row is inflated as before")

    def test_a_copy_each_time(self):
        with nodes.held():
            (nodes.node("n_a") or {})["name"] = "changed"
            nodes.node_list()[0]["name"] = "changed"
            self.assertEqual((nodes.node("n_a") or {})["name"], "a")
            self.assertEqual(nodes.node_list()[0]["name"], "a")

    def test_fresh_outside(self):
        with nodes.held():
            nodes.node("n_a")
        nodes.node("n_a")
        nodes.node("n_a")
        self.assertEqual(self.reads(), 3, "outside a block every ask reads the store, as before")


if __name__ == "__main__":
    unittest.main()
