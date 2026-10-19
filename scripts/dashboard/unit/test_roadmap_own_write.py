"""A session's own bb roadmap writes are not news to it (B56): the panel's
'changed, not told to the session yet' stays off, so the next send carries no
'(Also: the shared to-do list just changed...)'. Another session still hears
of it by its own counter, and the operator's edit still sets the flag."""
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


class OwnWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        roadmap.configure(write_json=write_json, state=self.tmp)
        # Two sessions that have each been told once, so each has a seat.
        roadmap.catchup("alpha", "u_one")
        roadmap.catchup("alpha", "u_two")

    def test_a_session_adding_and_finishing_leaves_the_flag_off(self):
        rid = roadmap.add("alpha", "a thing", by="claude", who="u_one")["item"]["id"]
        roadmap.tick("alpha", rid, by="claude", who="u_one")
        self.assertFalse(roadmap.unsaved("alpha")["roadmap"])
        self.assertEqual(roadmap.catchup("alpha", "u_one"), "")

    def test_the_other_session_is_still_told(self):
        roadmap.add("alpha", "a thing", by="claude", who="u_one")
        self.assertIn("to-do list", roadmap.catchup("alpha", "u_two"))

    def test_the_operators_edit_sets_the_flag(self):
        roadmap.add("alpha", "a thing")
        self.assertTrue(roadmap.unsaved("alpha")["roadmap"])


if __name__ == "__main__":
    unittest.main()
