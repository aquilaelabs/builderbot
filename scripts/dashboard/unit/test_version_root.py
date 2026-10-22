"""The tree a version or changelog question is asked of (version.root): a
worktree the caller stands in when it is one of the project's, bb's own or
one Claude Code made for an agent under the project's .claude/worktrees
(B212: a changelog line asked for there landed in the main checkout's file),
and never another project's."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import version  # noqa: E402


class VersionRoot(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ws, ignore_errors=True)
        version.configure(workspace=self.ws, state=self.ws / ".state", write_json=lambda *a, **k: None)
        for d in ("app", ".worktrees/app/feature", "app/.claude/worktrees/agent-1", "other/.claude/worktrees/agent-2"):
            (self.ws / d).mkdir(parents=True)

    def at(self, tree):
        with mock.patch.dict(os.environ, {"BB_VERSION_TREE": str(self.ws / tree) if tree else ""}):
            return version.root("app")

    def test_the_project_its_worktrees_and_its_agents_worktrees(self):
        self.assertEqual(self.at(""), self.ws / "app")
        self.assertEqual(self.at(".worktrees/app/feature"), (self.ws / ".worktrees/app/feature").resolve())
        self.assertEqual(self.at("app/.claude/worktrees/agent-1"), (self.ws / "app/.claude/worktrees/agent-1").resolve())

    def test_never_another_projects(self):
        self.assertEqual(self.at("other/.claude/worktrees/agent-2"), self.ws / "app")
        self.assertEqual(self.at("other"), self.ws / "app")


if __name__ == "__main__":
    unittest.main()
