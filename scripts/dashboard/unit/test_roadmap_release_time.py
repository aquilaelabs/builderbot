"""A release is dated by its tag where the project's git has one (B165): an
item finished later on a release's day is the next version's, not that one's.
The CHANGELOG's day, to its end, stands in where there is no tag."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import roadmap  # noqa: E402


class ReleaseTime(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.repo = Path(self.ws) / "p"
        self.repo.mkdir()
        (self.repo / "CHANGELOG.md").write_text("# Changelog\n\n## 0.3.0: 2026-10-21\n\n## 0.2.0: 2026-10-21\n\n## 0.1.0: 2026-10-01\n")
        git = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], check=True, capture_output=True,  # noqa: E731
                                        env=os.environ | {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                                                          "GIT_COMMITTER_EMAIL": "t@t", "GIT_COMMITTER_DATE": "@1792548935 +0000"})
        git("init", "-q")
        git("add", ".")
        git("commit", "-qm", "x")
        git("tag", "-a", "v0.2.0", "-m", "0.2.0")
        git("tag", "-a", "v0.1.0", "-m", "0.1.0")
        self.was = os.environ.get("WORKSPACE")
        os.environ["WORKSPACE"] = self.ws

    def tearDown(self):
        if self.was is None:
            os.environ.pop("WORKSPACE", None)
        else:
            os.environ["WORKSPACE"] = self.was

    def test_a_tag_dates_its_release_and_a_bumped_one_is_not_released_yet(self):
        rel = dict(roadmap.releases("p"))
        self.assertEqual(rel["0.2.0"], 1792548935)
        self.assertNotIn("0.3.0", rel, "bumped and dated, with no tag yet: not released")

    def test_a_project_with_no_tags_reads_the_day(self):
        import shutil
        shutil.rmtree(self.repo / ".git")
        rel = dict(roadmap.releases("p"))
        self.assertEqual(rel["0.1.0"], time.mktime(time.strptime("2026-10-01", "%Y-%m-%d")) + 86400)


if __name__ == "__main__":
    unittest.main()
