"""Versions derived, not typed (R254 steps 3 and 4): the releases a project's
CHANGELOG dates, newest first with the end of each day, and a closed bug
keeping when it was closed, which says the release that shipped the fix."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bugs  # noqa: E402
import roadmap  # noqa: E402


class Releases(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, "alpha"))
        self.old = os.environ.get("WORKSPACE")
        os.environ["WORKSPACE"] = self.ws
        self.addCleanup(lambda: os.environ.pop("WORKSPACE", None) if self.old is None
                        else os.environ.__setitem__("WORKSPACE", self.old))

    def test_every_dated_heading_newest_first(self):
        with open(os.path.join(self.ws, "alpha", "CHANGELOG.md"), "w") as f:
            f.write("# Changelog\n\n## Unreleased\n\n- next\n\n## 0.7.0: 2026-09-25\n\n- seven\n\n"
                    "## 0.6.0: 2026-09-19\n\n- six\n")
        got = roadmap.releases("alpha")
        self.assertEqual([v for v, _ in got], ["0.7.0", "0.6.0"])
        self.assertEqual(got[0][1], time.mktime(time.strptime("2026-09-25", "%Y-%m-%d")) + 86400)
        self.assertEqual(roadmap.last_release("alpha"), got[0])

    def test_entries_naming_an_item_or_a_bug_by_its_id(self):
        with open(os.path.join(self.ws, "alpha", "CHANGELOG.md"), "w") as f:
            f.write("# Changelog\n\n## Unreleased\n\n### Fixed\n\n- the bell resumes (B773) (abc1234)\n"
                    "- Sessions is a page (R250 step 1)\n\n## 0.7.0: 2026-09-25\n\n- old fix (B12, B773)\n"
                    "- not a ref: AB12 or B12x or R-2\n")
        b = roadmap.changelog_refs("alpha", "B")
        self.assertEqual([e["in"] for e in b["B773"]], ["Unreleased", "0.7.0"])
        self.assertEqual(b["B12"], [{"in": "0.7.0", "text": "old fix (B12, B773)"}])
        self.assertEqual(roadmap.changelog_refs("alpha", "R"), {"R250": [{"in": "Unreleased", "text": "Sessions is a page (R250 step 1)"}]})

    def test_none_without_a_changelog(self):
        self.assertEqual(roadmap.releases("alpha"), [])
        self.assertIsNone(roadmap.last_release("alpha"))


class ClosedAt(unittest.TestCase):
    def test_closing_keeps_when_and_reopening_drops_it(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "ws" / "p").mkdir(parents=True)
        bugs.configure(write_json=lambda p, d, mode=0o644: Path(p).write_text(json.dumps(d)), state=tmp,
                       workspace=str(Path(tmp) / "ws"), releases=lambda p: [("1.0.0", 9e9)])
        bugs.add("p", "a thing broke")
        bid = bugs.payload("p")["bugs"][0]["id"]
        t = time.time()
        bugs.set_status("p", bid, "fixed", note="mended")
        got = next(b for b in bugs.payload("p")["bugs"] if b["id"] == bid)
        self.assertGreaterEqual(got["closed_at"], int(t))
        self.assertEqual(bugs.payload("p")["releases"], [("1.0.0", 9e9)])
        bugs.set_status("p", bid, "open")
        self.assertNotIn("closed_at", next(b for b in bugs.payload("p")["bugs"] if b["id"] == bid))


if __name__ == "__main__":
    unittest.main()
