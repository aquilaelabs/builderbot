"""A release is checked against the files its project lists in
.release-files at the release's tag, and one short of a file is a red row
on the bell naming the file and why (R190 step 4)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import releasefiles  # noqa: E402
import releasesign  # noqa: E402


def git(d, *a):
    subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.invalid",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.invalid"})


class Files(unittest.TestCase):
    def setUp(self):
        self.ws, self.state = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        d = self.ws / "app"
        d.mkdir()
        git(d, "init", "-q", "-b", "main")
        (d / ".release-files").write_text("# what a release carries\napp-@VER@.tar.gz\napp-@VER@.apk\napp-@VER@-*.iso\n")
        git(d, "add", ".release-files")
        git(d, "commit", "-q", "-m", "list")
        git(d, "tag", "v1.0.0-dev.5")
        # A later list does not change what the tagged release is held to.
        (d / ".release-files").write_text("app-@VER@.tar.gz\napp-@VER@.exe\n")
        git(d, "commit", "-q", "-am", "later")

        def write(f, data):
            Path(f).write_text(json.dumps(data))
        releasefiles.configure(state=self.state, workspace=self.ws, write_json_fn=write)
        releasesign.configure(state=self.state, workspace=self.ws, write_json_fn=write)

    def test_the_list_is_the_tags_with_its_version_filled_in(self):
        self.assertEqual(releasefiles.wanted("app", "v1.0.0-dev.5"),
                         ["app-1.0.0-dev.5.tar.gz", "app-1.0.0-dev.5.apk", "app-1.0.0-dev.5-*.iso"])

    def check(self, have, after=4 * 3600):
        releasefiles.expect("app", "v1.0.0-dev.5")
        with mock.patch.object(releasefiles.forgerelease, "_handle", return_value=("github", "GitHub", None)), \
                mock.patch.object(releasefiles.forgerelease, "_files_on",
                                  return_value=("https://h/r", {n: (1, 1, 1) for n in have})):
            import time
            releasefiles.check("app", now=time.time() + after)
        return releasefiles.attention(["app"])

    def test_a_whole_release_says_nothing(self):
        self.assertEqual(self.check(["app-1.0.0-dev.5.tar.gz", "app-1.0.0-dev.5.apk", "app-1.0.0-dev.5-x.iso"]), [])

    def test_a_missing_apk_is_said_with_why(self):
        rows = self.check(["app-1.0.0-dev.5.tar.gz", "app-1.0.0-dev.5-x.iso"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["files"], ["app-1.0.0-dev.5.apk"])
        self.assertTrue(rows[0]["bad"])
        self.assertIn("has not signed it", rows[0]["why"])

    def test_nothing_is_checked_before_ci_has_had_its_time(self):
        self.assertEqual(self.check([], after=60), [])

    def test_a_project_with_no_list_is_never_expected(self):
        (self.ws / "bare").mkdir()
        git(self.ws / "bare", "init", "-q")
        releasefiles.expect("bare", "v1.0.0")
        self.assertNotIn("bare", json.loads((self.state / "release-files.json").read_text()) if
                         (self.state / "release-files.json").exists() else {})


if __name__ == "__main__":
    unittest.main()
