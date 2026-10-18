"""version._git keeps what a read about history answered while the
repository's own files say nothing moved (the operator, 18 Oct: the
Artifacts view ran sixteen git commands on the controller's share at half a
second each). A commit, a tag and a branch switch each move the stamp and are
answered fresh; the working tree is always asked."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import version  # noqa: E402

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


class Kept(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ws, ignore_errors=True)
        version.configure(workspace=self.ws, state=self.ws / ".state", write_json=lambda *a, **k: None)
        version._git_kept.clear()
        self.p = self.ws / "app"
        self.p.mkdir()
        subprocess.run([*GIT, "init", "-q", "-b", "main", str(self.p)], check=True)
        self.commit("0.1.0\n")
        self.calls = 0
        real = subprocess.run

        def counted(*a, **k):
            if a and a[0][:1] == ["git"]:
                self.calls += 1
            return real(*a, **k)
        self.real, version.subprocess.run = version.subprocess.run, counted
        self.addCleanup(setattr, version.subprocess, "run", self.real)

    def commit(self, text, name="VERSION"):
        (self.p / name).write_text(text)
        subprocess.run([*GIT, "-C", str(self.p), "add", name], check=True)
        subprocess.run([*GIT, "-C", str(self.p), "commit", "-qm", "c"], check=True)

    def count(self):
        return version._git("app", "rev-list", "--count", "HEAD")

    def test_a_history_read_is_asked_once_while_nothing_moves(self):
        self.assertEqual(self.count(), "1")
        self.assertEqual(self.count(), "1")
        self.assertEqual(self.calls, 1)

    def test_a_commit_is_seen_at_once(self):
        self.assertEqual(self.count(), "1")
        self.commit("0.1.1\n")
        self.assertEqual(self.count(), "2")

    def test_a_tag_is_seen_at_once(self):
        self.assertEqual(version._git("app", "tag", "-l", "v0.1.0"), "")
        subprocess.run([*GIT, "-C", str(self.p), "tag", "v0.1.0"], check=True)
        self.assertEqual(version._git("app", "tag", "-l", "v0.1.0"), "v0.1.0")

    def test_a_branch_switch_is_seen_at_once(self):
        subprocess.run([*GIT, "-C", str(self.p), "checkout", "-qb", "side"], check=True)
        self.commit("x\n", "other")
        self.assertEqual(self.count(), "2")
        subprocess.run([*GIT, "-C", str(self.p), "checkout", "-q", "main"], check=True)
        self.assertEqual(self.count(), "1")

    def test_a_remote_ref_moving_is_seen_at_once(self):
        head = subprocess.run([*GIT, "-C", str(self.p), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertIsNone(version._git("app", "rev-parse", "--verify", "-q", "origin/main"))
        subprocess.run([*GIT, "-C", str(self.p), "update-ref", "refs/remotes/origin/main", head], check=True)
        self.assertEqual(version._git("app", "rev-parse", "--verify", "-q", "origin/main"), head)

    def test_the_working_tree_is_always_asked(self):
        version._git("app", "status", "--porcelain")
        version._git("app", "status", "--porcelain")
        self.assertEqual(self.calls, 2)

    def test_a_write_is_never_kept(self):
        version._git("app", "tag", "v9")
        version._git("app", "tag", "-d", "v9")
        self.assertEqual(version._git("app", "tag", "-l", "v9"), "", "a tag made and deleted is gone")
        self.assertEqual(self.calls, 3)


if __name__ == "__main__":
    unittest.main()
