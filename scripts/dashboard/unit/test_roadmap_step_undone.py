"""A step a session marked done can be taken back by a session (the
operator, 17 Oct): the mark goes, the log says so with why, and the step is
done again with no second thing to undo."""
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


class StepUndone(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        roadmap.configure(write_json=write_json, state=self.tmp)
        self.rid = roadmap.add("alpha", "a plan", by="claude", steps=["one", "two", "three"])["item"]["id"]

    def steps(self):
        row = next(r for r in roadmap.items("alpha") if r["id"] == self.rid)
        return [bool(st.get("done")) for st in row["steps"]]

    def test_a_done_step_taken_back_is_to_do_again_and_logged(self):
        roadmap.step_done("alpha", self.rid, 1)
        self.assertEqual(self.steps(), [False, True, False])
        r = roadmap.step_undone("alpha", self.rid, 1, note="ticked the wrong one")
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(self.steps(), [False, False, False])
        ev = [e for e in roadmap.history("alpha") if e.get("act") == "undone-step"]
        self.assertTrue(ev and ev[-1]["why"] == "ticked the wrong one" and ev[-1]["step"] == 1, ev)
        # ...and it can be marked done again.
        self.assertTrue(roadmap.step_done("alpha", self.rid, 1).get("ok"))

    def test_a_step_not_done_is_refused(self):
        self.assertIn("not done", roadmap.step_undone("alpha", self.rid, 0)["error"])
        self.assertIn("no such step", roadmap.step_undone("alpha", self.rid, 9)["error"])


if __name__ == "__main__":
    unittest.main()
