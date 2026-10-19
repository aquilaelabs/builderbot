"""The Git view reads a tree through the controller's own git dir, and the
tree's .git/info/exclude goes with it (B45): BuilderBot keeps its code map's
.bb-map/ out of a project's git there, and a status that read another git
dir's exclude listed it as an uncommitted change."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
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

    def test_the_code_map_is_out_even_when_the_tree_never_got_the_line(self):
        (self.repo / ".git" / "info" / "exclude").write_text("# git's own\n")
        files = [f["path"] for f in git.status(self.repo)["files"]]
        self.assertFalse([f for f in files if f.startswith(".bb-map")], files)


class Clone(unittest.TestCase):
    """A clone (the round 2 walk's project) has .bb-map/ in its own exclude
    before its map is built, so neither the Git view nor a terminal's git
    offers it to commit."""
    def setUp(self):
        import json
        import re
        import threading
        import mapping
        import projects
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = self.tmp / "ws"
        self.ws.mkdir()
        src = self.tmp / "src"
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
        subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
        (src / "a.py").write_text("def f():\n    return 1\n")
        subprocess.run(["git", "-C", str(src), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(src), "commit", "-qm", "one"], check=True, env=env)
        self.src, self.mapping, self.projects = src, mapping, projects
        mapping.configure(workspace=self.ws,
                          codemap=Path(__file__).resolve().parents[2] / "lib" / "codemap.py")

        def run(cmd, timeout=60, env=None, register=None, **_):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
            return {"code": r.returncode, "out": r.stdout + r.stderr}
        projects.configure(run=run, workspace=self.ws, agent_keys=lambda: [], gh_authed=lambda: False,
                           ensure_deploy_alias=lambda *a: "", project_name=re.compile(r"[A-Za-z0-9._-]+"),
                           state=self.tmp, home=self.tmp,
                           write_json=lambda p, d: Path(p).write_text(json.dumps(d)),
                           after_create=mapping.start)
        self.addCleanup(setattr, projects, "lock", projects.lock)
        projects.lock = threading.Lock()
        for k in ("set_push_hook", "_aborted", "_step"):
            self.addCleanup(setattr, projects, k, getattr(projects, k))
        projects.set_push_hook = lambda *a: None
        projects._aborted = lambda: False
        projects._step = lambda *a: None

    def test_a_clone_is_excluded_before_its_map_is_written(self):
        dest = self.ws / "cloned"
        err, _ = self.projects._clone(dest, str(self.src))
        self.assertEqual(err, "")
        self.assertIn(".bb-map/", (dest / ".git" / "info" / "exclude").read_text().split("\n"))
        for _ in range(300):
            if not self.mapping._jobs.get("cloned", {}).get("running"):
                break
            time.sleep(0.1)
        self.assertTrue((dest / ".bb-map").is_dir(), "the map was built")
        out = subprocess.run(["git", "-C", str(dest), "status", "--porcelain"],
                             capture_output=True, text=True).stdout
        self.assertNotIn(".bb-map", out)


if __name__ == "__main__":
    unittest.main()
