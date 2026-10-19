"""The Storage page's answer for one account (storage.py, R169): the nodes
the account holds the area on, each project's folders where it may see the
project, and every other project's folded into one line."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import storage  # noqa: E402

WALK = {"at": 1_700_000_000, "took_s": 3, "filesystems": [{"path": "/", "total_mb": 100, "used_mb": 60, "free_mb": 40}],
        "stores": {"cache": {"path": "/var/lib/builderbot/cache", "used_mb": 20}},
        "projects": {"alpha": {"workspace": 5, "cache": 10}, "beta": {"cache": 7, "builds": 1}, "gamma": {"appdata": 30}}}
NODES = [{"id": "n1", "name": "box", "kind": "agent", "state": "online", "live": True, "config": {},
          "reported": {"storage": WALK}},
         {"id": "n2", "name": "pend", "kind": "agent", "state": "pending", "reported": {}},
         {"id": "n3", "name": "bare", "kind": "agent", "state": "online", "live": False, "reported": {}}]


class View(unittest.TestCase):
    def test_an_administrator_sees_every_node_and_every_project(self):
        r, st = storage.view(NODES, {"role": "admin"}, is_admin=lambda u: True, nodes_for=lambda u, a: None,
                             may_see=lambda u, n: False, level_of=lambda u, a, **k: "write")
        self.assertEqual(st, 200)
        self.assertEqual([n["node"] for n in r["nodes"]], ["n1", "n3"], "a waiting row is not a disk to read")
        box = r["nodes"][0]
        self.assertEqual([p["name"] for p in box["projects"]], ["gamma", "alpha", "beta"], "largest first")
        self.assertEqual(box["projects"][1]["total"], 15)
        self.assertIsNone(box["other"])
        self.assertTrue(r["may_measure"] and box["measured"] and not r["nodes"][1]["measured"])

    def test_a_person_sees_their_projects_and_the_rest_as_one_line(self):
        r, st = storage.view(NODES, {"role": ""}, is_admin=lambda u: False, nodes_for=lambda u, a: ["n1"],
                             may_see=lambda u, n: n == "alpha", level_of=lambda u, a, **k: "read")
        self.assertEqual(st, 200)
        self.assertEqual([n["node"] for n in r["nodes"]], ["n1"], "only the node the area is held on")
        box = r["nodes"][0]
        self.assertEqual([p["name"] for p in box["projects"]], ["alpha"])
        self.assertEqual(box["other"], {"workspace": 0, "cache": 7, "artifacts": 0, "appdata": 30, "emulator": 0,
                                        "builds": 1, "total": 38}, "beta and gamma as one unnamed total")
        self.assertFalse(r["may_measure"])

    def test_without_the_area_the_tab_is_refused(self):
        r, st = storage.view(NODES, {"role": ""}, is_admin=lambda u: False, nodes_for=lambda u, a: [],
                             may_see=lambda u, n: True, level_of=lambda u, a, **k: "")
        self.assertEqual(st, 403)
        self.assertIn("Storage", r["error"])


if __name__ == "__main__":
    unittest.main()
