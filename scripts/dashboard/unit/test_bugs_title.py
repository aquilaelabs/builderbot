"""A bug's title is one line of at most bugs.MAX_SHORT characters, and a longer one is
refused with where the rest goes, not cut: cutting it lost whatever followed,
often the half that said why (B621)."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bugs  # noqa: E402


def write_json(p, d, mode=0o644):
    Path(p).write_text(json.dumps(d))


class Title(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (Path(self.tmp) / "ws" / "p").mkdir(parents=True)
        bugs.configure(write_json=write_json, state=self.tmp, workspace=str(Path(self.tmp) / "ws"))

    def test_a_long_title_is_refused_and_says_where_the_rest_goes(self):
        r = bugs.add("p", "word " * (bugs.MAX_SHORT // 5 + 20))
        n = len(("word " * (bugs.MAX_SHORT // 5 + 20)).strip())
        self.assertIn(f"at most {bugs.MAX_SHORT} characters (this one is {n})", r.get("error", ""))
        self.assertIn("repro or a note", r["error"])

    def test_one_that_fits_is_kept_whole(self):
        title = "x" * bugs.MAX_SHORT
        r = bugs.add("p", title)
        self.assertTrue(r.get("ok") or r.get("id"), r)
        got = bugs.payload("p")["bugs"][0]
        self.assertEqual(got["title"], title)
        e = bugs.edit("p", got["id"], title="y " * bugs.MAX_SHORT)
        self.assertIn(f"at most {bugs.MAX_SHORT}", e.get("error", ""), "an edit is held to it too")


class EditHistory(unittest.TestCase):
    """A bug edit's History names the fields that moved, not every one the
    form sent (B42), and an edit that moved nothing leaves no line."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (Path(self.tmp) / "ws" / "p").mkdir(parents=True)
        bugs.configure(write_json=write_json, state=self.tmp, workspace=str(Path(self.tmp) / "ws"))

    def test_only_what_moved_is_named(self):
        r = bugs.add("p", "first", severity="low", area="nb", repro="press it")
        n = r.get("id") or r["bug"]["id"]
        form = {"title": "second", "severity": "low", "area": "nb", "repro": "press it",
                "expected": "", "actual": "", "notes": ""}
        bugs.edit("p", n, **form)
        notes = [e.get("note") for e in bugs.history("p") if e.get("act") == "edited"]
        self.assertEqual(notes, ["title"])
        bugs.edit("p", n, **form)
        self.assertEqual(len([e for e in bugs.history("p") if e.get("act") == "edited"]), 1,
                         "the same form again is no edit")


if __name__ == "__main__":
    unittest.main()
