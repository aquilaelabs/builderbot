"""The Git view reads a tree through the controller's own git dir, and the
tree's .git/info/exclude goes with it (B45): BuilderBot keeps its code map's
.bb-map/ out of a project's git there, and a status that read another git
dir's exclude listed it as an uncommitted change."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import git  # noqa: E402


class Exclude(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.saved = {k: getattr(git, k) for k in ("STATE", "WORKSPACE", "paths")}
        self.addCleanup(lambda: [setattr(git, k, v) for k, v in self.saved.items()])
        ws = self.tmp / "ws"
        self.repo = ws / "p"
        self.repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        (self.repo / ".bb-map").mkdir()
        (self.repo / ".bb-map" / "map3.json").write_text("{}")
        (self.repo / "main.c").write_text("int main(){}\n")
        with open(self.repo / ".git" / "info" / "exclude", "a") as fh:
            fh.write(".bb-map/\n")
        (self.tmp / "state").mkdir()
        git.STATE, git.WORKSPACE, git.paths = self.tmp / "state", ws, None

    def test_the_code_map_is_not_an_uncommitted_change(self):
        self.assertIsNotNone(git._own(self.repo), "read through the controller's own git dir")
        files = [f["path"] for f in git.status(self.repo)["files"]]
        self.assertIn("main.c", files)
        self.assertFalse([f for f in files if f.startswith(".bb-map")], files)


if __name__ == "__main__":
    unittest.main()
