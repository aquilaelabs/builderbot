"""A release whose tag could not be pushed says why, in git's own words, and
never the credential a remote's URL carries (B398): "the push failed" alone
left the person guessing between the network, the credential and the
remote."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import version  # noqa: E402


def git(d, *a):
    subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.invalid",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.invalid"})


class PushSaid(unittest.TestCase):
    def test_a_failed_push_says_why_and_no_secret(self):
        ws = Path(tempfile.mkdtemp())
        d = ws / "app"
        d.mkdir()
        git(d, "init", "-q", "-b", "main")
        (d / "VERSION").write_text("1.2.3\n")
        git(d, "add", "VERSION")
        git(d, "commit", "-q", "-m", "one")
        git(d, "remote", "add", "origin", f"file://{ws}/nowhere-sekrit:hunter2@x/repo.git")
        version.configure(workspace=str(ws), state=str(ws / "state"), write_json=lambda *a, **k: None)
        r = version.release("app")
        self.assertTrue(r.get("ok"), r)
        self.assertFalse(r["pushed"])
        self.assertIn("the push failed: ", r["note"])
        self.assertIn("git push origin v1.2.3", r["note"])


if __name__ == "__main__":
    unittest.main()
