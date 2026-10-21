"""An item's target, the release it is meant to ship in (the operator, 21
Oct): set and cleared on its own verb and on add, checked as X.Y.Z, logged,
and kept when a finished item's row is rebuilt from the log."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import roadmap  # noqa: E402


def write_json(path, data, mode=0o644):
    del mode
    with open(path, "w") as f:
        json.dump(data, f)


class Target(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        roadmap.configure(write_json=write_json, state=self.tmp)

    def row(self, rid):
        return next(r for r in roadmap.items("alpha") if r["id"] == rid)

    def test_set_changed_and_cleared_with_the_log_saying_so(self):
        rid = roadmap.add("alpha", "a goal")["item"]["id"]
        self.assertNotIn("target", self.row(rid))
        self.assertTrue(roadmap.set_target("alpha", rid, "v0.6.0").get("ok"))
        self.assertEqual(self.row(rid)["target"], "0.6.0")
        self.assertTrue(roadmap.set_target("alpha", rid, "0.5.4").get("ok"))
        self.assertIn("already for 0.5.4", roadmap.set_target("alpha", rid, "0.5.4")["error"])
        self.assertTrue(roadmap.set_target("alpha", rid, "").get("ok"))
        self.assertNotIn("target", self.row(rid))
        ev = [e for e in roadmap.history("alpha") if e.get("act") == "target"]
        self.assertEqual([(e["target"], e.get("was", "")) for e in ev][-3:],
                         [("0.6.0", ""), ("0.5.4", "0.6.0"), ("", "0.5.4")], ev)

    def test_add_takes_one_and_nothing_but_a_version_is_one(self):
        r = roadmap.add("alpha", "a goal", target="0.6.0")
        self.assertEqual(r["item"]["target"], "0.6.0")
        for bad in ("0.6", "next", "0.6.0-rc1", "1.2.3.4"):
            self.assertIn("not a version", roadmap.add("alpha", "x", target=bad)["error"], bad)
            self.assertIn("not a version", roadmap.set_target("alpha", r["item"]["id"], bad)["error"], bad)

    def test_the_verb_from_the_page(self):
        rid = roadmap.add("alpha", "a goal")["item"]["id"]
        _, status = roadmap.verb("alpha", "target", {"id": rid, "target": "0.6.0"}, {}, live=[], prefix="")
        self.assertEqual(status, 200)
        self.assertEqual(self.row(rid)["target"], "0.6.0")

    def test_a_rebuilt_row_keeps_it(self):
        events = [{"act": "add", "id": 4, "text": "a goal", "target": "0.6.0"},
                  {"act": "target", "id": 4, "text": "a goal", "target": "0.7.0", "was": "0.6.0"}]
        self.assertEqual(roadmap._rebuilt_row(events, 4, "a goal")["target"], "0.7.0")
        events.append({"act": "target", "id": 4, "text": "a goal", "target": "", "was": "0.7.0"})
        self.assertNotIn("target", roadmap._rebuilt_row(events, 4, "a goal"))


if __name__ == "__main__":
    unittest.main()
