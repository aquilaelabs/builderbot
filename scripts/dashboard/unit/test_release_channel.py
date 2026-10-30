"""A session's release from a branch other than the one builds ship from is
a dev pre-release unless --stable is said, and the channel is named (R190
step 1): a stable release cut from claude/0.9.0 had to be pulled."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import version  # noqa: E402


def git(d, *a):
    subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.invalid",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.invalid"})


class Channel(unittest.TestCase):
    def setUp(self):
        ws = Path(tempfile.mkdtemp())
        up, d = ws / "up.git", ws / "app"
        git(ws, "init", "-q", "--bare", "-b", "main", str(up))
        git(ws, "clone", "-q", str(up), str(d))
        (d / "VERSION").write_text("1.2.3\n")
        git(d, "add", "VERSION")
        git(d, "commit", "-q", "-m", "v")
        git(d, "push", "-q", "origin", "HEAD:main")
        git(d, "remote", "set-head", "origin", "main")
        self.d = d
        self.p = mock.patch.object(version, "root", lambda _p: d)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_on_main_a_release_is_stable(self):
        dev, said = version.channel_of("app")
        self.assertFalse(dev)
        self.assertIn("becomes Latest", said)

    def test_off_main_a_release_is_dev(self):
        git(self.d, "checkout", "-q", "-b", "claude/1.3.0")
        dev, said = version.channel_of("app")
        self.assertTrue(dev)
        self.assertIn("Latest stays", said)

    def test_off_main_stable_is_said_in_so_many_words(self):
        git(self.d, "checkout", "-q", "-b", "claude/1.3.0")
        self.assertFalse(version.channel_of("app", stable=True)[0])

    def test_dev_and_stable_together_are_refused(self):
        self.assertIn("not both", version.release_plan("app", dev=True, stable=True)["error"])


if __name__ == "__main__":
    unittest.main()
