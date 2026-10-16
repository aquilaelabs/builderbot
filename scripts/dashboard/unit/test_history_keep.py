"""History worth reading (R254 step 5): a reorder is one line, from where an
item started to where it ended, and the tracker's log keeps each report's
filing and closing through its trim, as the roadmap keeps a finished item."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bugs  # noqa: E402
import roadmap  # noqa: E402


def write_json(p, d, mode=0o644):
    del mode
    Path(p).write_text(json.dumps(d))


class Moves(unittest.TestCase):
    def setUp(self):
        roadmap.configure(state=tempfile.mkdtemp(), write_json=write_json)
        for t in ("one", "two", "three"):
            roadmap.add("alpha", t)

    def test_a_reorder_is_one_line(self):
        third = roadmap.items("alpha")[2]["id"]
        roadmap.move("alpha", third, dir=-1)
        roadmap.move("alpha", third, dir=-1)
        moved = [e for e in roadmap.history("alpha") if e.get("act") == "moved"]
        self.assertEqual(len(moved), 1)
        self.assertEqual((moved[0]["id"], moved[0]["from"], moved[0]["to"]), (third, 3, 1))

    def test_moving_back_where_it_was_leaves_no_line(self):
        first = roadmap.items("alpha")[0]["id"]
        roadmap.move("alpha", first, dir=1)
        roadmap.move("alpha", first, dir=-1)
        self.assertFalse([e for e in roadmap.history("alpha") if e.get("act") == "moved"])


class BugTrim(unittest.TestCase):
    def test_filings_and_closings_outlive_the_trim(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "ws" / "p").mkdir(parents=True)
        bugs.configure(write_json=write_json, state=tmp, workspace=str(Path(tmp) / "ws"))
        bugs.add("p", "the oldest report")
        first = bugs.payload("p")["bugs"][0]["id"]
        bugs.set_status("p", first, "fixed", note="mended")
        for i in range(bugs.MAX_HISTORY + 20):
            bugs.edit("p", first, notes=f"a note {i}")
        acts = [e.get("act") for e in bugs.history("p") if e.get("id") == first]
        self.assertIn("filed", acts)
        self.assertIn("fixed", acts)


if __name__ == "__main__":
    unittest.main()
