"""An item that is not on the list says why (B737): finished (its last
step done, or ticked off), dropped, or never there, rather than 'no such
item' for all three."""
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


class Gone(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        roadmap.configure(write_json=write_json, state=self.tmp)

    def test_a_step_after_the_last_one_says_the_item_is_done(self):
        r = roadmap.add("alpha", "a plan", by="claude", steps=["one", "two"])
        rid = r["item"]["id"]
        self.assertTrue(roadmap.step_done("alpha", rid, 0).get("ok"))
        last = roadmap.step_done("alpha", rid, 1)
        self.assertTrue(last.get("finished"), last)
        again = roadmap.step_done("alpha", rid, 1)
        self.assertIn(f"R{rid} is done already", again["error"])

    def test_a_plan_finished_by_its_last_step_keeps_its_steps(self):
        # B767: the Finished section showed it as the words alone.
        rid = roadmap.add("alpha", "a plan", by="claude", steps=["one", "two"])["item"]["id"]
        roadmap.step_done("alpha", rid, 0)
        roadmap.step_done("alpha", rid, 1)
        done = next(r for r in roadmap.finished("alpha") if r["id"] == rid)
        self.assertEqual([st["text"] for st in done["steps"]], ["one", "two"])

    def test_a_dropped_one_and_one_never_there_say_so(self):
        rid = roadmap.add("alpha", "to drop", by="claude")["item"]["id"]
        roadmap.remove("alpha", rid, why="not needed", by="operator")
        self.assertIn(f"R{rid} was dropped", roadmap.step_done("alpha", rid, 0)["error"])
        self.assertEqual(roadmap.step_done("alpha", 4242, 0)["error"], "no item R4242 on this list")


if __name__ == "__main__":
    unittest.main()
