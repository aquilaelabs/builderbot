"""A version or changelog question asked from a worktree of the project's
own repository is answered for that tree, wherever the worktree is (B214:
a Claude Code worktree under .claude/worktrees wrote the main checkout's
changelog)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import version  # noqa: E402


def git(*a, cwd):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                            GIT_COMMITTER_EMAIL="t@t"))


class Worktree(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        main = self.ws / "proj"
        main.mkdir()
        git("init", "-q", cwd=main)
        (main / "VERSION").write_text("1.0.0\n")
        git("add", ".", cwd=main)
        git("commit", "-qm", "one", cwd=main)
        self.inside = main / ".claude" / "worktrees" / "w1"
        git("worktree", "add", "-q", str(self.inside), cwd=main)
        other = self.ws / "other"
        other.mkdir()
        git("init", "-q", cwd=other)
        (other / "f").write_text("x")
        git("add", ".", cwd=other)
        git("commit", "-qm", "o", cwd=other)
        self.foreign = self.ws / "elsewhere"
        git("worktree", "add", "-q", str(self.foreign), cwd=other)

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.ws)], check=False)

    def test_a_worktree_of_the_project_is_its_tree_and_another_repo_s_is_not(self):
        with mock.patch.object(version, "WORKSPACE", self.ws):
            with mock.patch.dict(os.environ, {"BB_VERSION_TREE": str(self.inside)}):
                self.assertEqual(version.root("proj"), self.inside.resolve())
            with mock.patch.dict(os.environ, {"BB_VERSION_TREE": str(self.foreign)}):
                self.assertEqual(version.root("proj"), self.ws / "proj")
            with mock.patch.dict(os.environ, {"BB_VERSION_TREE": ""}):
                self.assertEqual(version.root("proj"), self.ws / "proj")


if __name__ == "__main__":
    unittest.main()
