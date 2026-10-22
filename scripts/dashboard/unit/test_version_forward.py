"""A released patch line merged forward (R112 step 3, bb version forward):
its fixes carried into the later line's branch, that line's VERSION kept,
the patch's dated changelog section placed among the others by version,
and an entry it already released taken out of the later line's
Unreleased."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import changelog  # noqa: E402
import version  # noqa: E402

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
BASE = "# Changelog\n\n## Unreleased\n\n## 0.6.1: 2026-10-22\n\n### Added\n\n- the first release\n"


def git(*a, cwd):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout


class Stitch(unittest.TestCase):
    def test_a_section_placed_by_version_and_a_shipped_entry_said_once(self):
        ours = ("# Changelog\n\n## Unreleased\n\n### Added\n\n- a new page\n\n### Fixed\n\n- the crash on save (abc1234)\n\n"
                "## 0.6.1: 2026-10-22\n\n### Added\n\n- the first release\n")
        theirs = ("# Changelog\n\n## Unreleased\n\n## 0.6.2: 2026-10-30\n\n### Fixed\n\n- the crash on save (def5678)\n\n"
                  "## 0.6.1: 2026-10-22\n\n### Added\n\n- the first release\n")
        text, titles, dropped = changelog.stitch(ours, theirs)
        self.assertEqual(titles, ["0.6.2: 2026-10-30"])
        self.assertEqual(dropped, ["the crash on save (abc1234)"])
        heads = [ln for ln in text.splitlines() if ln.startswith("## ")]
        self.assertEqual(heads, ["## Unreleased", "## 0.6.2: 2026-10-30", "## 0.6.1: 2026-10-22"])
        unrel = text.split("## 0.6.2")[0]
        self.assertIn("- a new page", unrel)
        self.assertNotIn("### Fixed", unrel, "a heading left empty goes with its entry")


class Forward(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.ws)])
        self.p = p = self.ws / "app"
        p.mkdir()
        git("init", "-q", "-b", "main", cwd=p)
        (p / "VERSION").write_text("0.6.1\n")
        (p / "CHANGELOG.md").write_text(BASE)
        (p / "app.txt").write_text("one\n")
        git("add", ".", cwd=p)
        git("commit", "-qm", "0.6.1", cwd=p)
        git("tag", "v0.6.1", cwd=p)
        # The patch line: a fix, released as 0.6.2.
        git("checkout", "-q", "-b", "claude/0.6.2", cwd=p)
        (p / "fix.txt").write_text("fixed\n")
        (p / "VERSION").write_text("0.6.2\n")
        (p / "CHANGELOG.md").write_text(BASE.replace("## 0.6.1", "## 0.6.2: 2026-10-30\n\n### Fixed\n\n- the crash on save\n\n## 0.6.1"))
        git("add", ".", cwd=p)
        git("commit", "-qm", "Fix the crash on save", cwd=p)
        # The next line, which made the same fix itself and more.
        git("checkout", "-q", "-b", "claude/0.7.0", "v0.6.1", cwd=p)
        (p / "page.txt").write_text("new\n")
        (p / "CHANGELOG.md").write_text(BASE.replace("## Unreleased\n", "## Unreleased\n\n### Added\n\n- a new page\n\n### Fixed\n\n- the crash on save\n"))
        git("add", ".", cwd=p)
        git("commit", "-qm", "A new page", cwd=p)
        (self.ws / "versions.json").write_text(json.dumps({"projects": {"app": {"policy": "open"}}}))
        for name, value in (("WORKSPACE", self.ws), ("FILE", self.ws / "versions.json"), ("changelog", changelog)):
            m = mock.patch.object(version, name, value)
            m.start()
            self.addCleanup(m.stop)

    def test_carried_with_its_number_kept_and_the_changelog_stitched(self):
        r = version.forward("app", "claude/0.6.2", env=ENV)
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(len(r["carried"]), 1)
        self.assertEqual((self.p / "VERSION").read_text(), "0.6.1\n", "this line's VERSION, not the patch's")
        self.assertTrue((self.p / "fix.txt").is_file())
        text = (self.p / "CHANGELOG.md").read_text()
        self.assertEqual(text.count("- the crash on save"), 1)
        self.assertLess(text.index("## 0.6.2"), text.index("## 0.6.1"))
        self.assertIn("merged forward into 0.7.0", git("log", "-1", "--format=%s", cwd=self.p))
        self.assertEqual(version.forward("app", "claude/0.6.2", env=ENV)["carried"], [], "twice is nothing")

    def test_refused_backwards_unreleased_or_dirty(self):
        self.assertIn("older line to a newer", version.forward("app", "claude/0.7.0")["error"])
        (self.p / "page.txt").write_text("changed\n")
        self.assertIn("not committed", version.forward("app", "claude/0.6.2")["error"])
        git("checkout", "-q", "--", "page.txt", cwd=self.p)
        git("checkout", "-q", "claude/0.6.2", cwd=self.p)
        (self.p / "CHANGELOG.md").write_text(BASE.replace("## Unreleased\n", "## Unreleased\n\n- more\n"))
        git("commit", "-qam", "more", cwd=self.p)
        git("checkout", "-q", "claude/0.7.0", cwd=self.p)
        self.assertIn("not released yet", version.forward("app", "claude/0.6.2")["error"])


    def test_backport_carries_a_fix_and_its_entry_back(self):
        # A fix made on 0.7.0, wanted on 0.6.2 too.
        (self.p / "app.txt").write_text("fixed again\n")
        text = (self.p / "CHANGELOG.md").read_text().replace("- a new page\n", "- a new page\n\n### Security\n\n- the token is not logged\n")
        (self.p / "CHANGELOG.md").write_text(text)
        git("commit", "-qam", "The token is not logged (B9)", cwd=self.p)
        fix = git("rev-parse", "HEAD", cwd=self.p).strip()
        git("checkout", "-q", "claude/0.6.2", cwd=self.p)
        r = version.backport("app", fix, env=ENV)
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r["entries"], ["the token is not logged"])
        self.assertEqual((self.p / "VERSION").read_text(), "0.6.2\n")
        cl = (self.p / "CHANGELOG.md").read_text()
        unrel = cl.split("## 0.6.2")[0]
        self.assertIn("### Security", unrel)
        self.assertIn("- the token is not logged", unrel)
        self.assertNotIn("a new page", cl, "only what the commit added")
        self.assertIn("cherry picked from commit " + fix, git("log", "-1", "--format=%B", cwd=self.p))
        self.assertIn("already on this branch", version.backport("app", "HEAD")["error"])


if __name__ == "__main__":
    unittest.main()
