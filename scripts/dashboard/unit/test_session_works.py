"""bb-session's --works (R136 step 4): one session in every repository of a
project, each repository's tree and worktrees in the view to write as the
project's own are, the session's folder allowed in any of them, and a
repository named twice, as a read too, or that is not there refused."""
import importlib.machinery
import importlib.util
import os
import pwd
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


session = load("bb_session_works", os.path.join(ROOT, "nodes", "bb-session"))
ME = pwd.getpwuid(os.getuid()).pw_name
NOWALL = {"BB_SESSION_WALL": "/nonexistent/wall", "BB_SESSION_MARKS": "/nonexistent/x"}


class Works(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.d, True))
        self.ws, home = f"{self.d}/ws", f"{self.d}/home"
        self.account = "u_0000abcd"
        for p in (f"{self.ws}/app", f"{self.ws}/server", f"{self.ws}/docs", f"{self.ws}/other",
                  f"{self.ws}/.worktrees/server/{self.account}", f"{home}/users/{self.account}"):
            os.makedirs(p)
        self.c = {"SESSION_USER": ME, "WORKSPACE": self.ws, "HOME_ROOT": home, "DATA_STORE": "",
                  "ARTIFACTS_STORE": "", "RUNNER_DIR": "/nonexistent", "HIDE": "", "STATE_DIR": "",
                  "TOOLCHAINS_STORE": ""}
        self.a = {"project": "app", "account": self.account, "home": f"{home}/users/{self.account}",
                  "cwd": f"{self.ws}/app", "works": ["server", "docs"], "reads": ["other"]}

    def plan(self, **over):
        with mock.patch.dict(os.environ, NOWALL):
            return session.plan(self.c, dict(self.a, **over), None)

    def test_the_word_is_taken_once_per_repository(self):
        got = session.args(["--project", "app", "--works", "server", "--works", "docs"])[0]
        self.assertEqual(got["works"], ["server", "docs"])

    def test_every_repository_is_bound_to_write(self):
        steps = self.plan()
        for rel in ("app", "server", "docs", ".worktrees/server"):
            self.assertIn(("bindmap", f"{session.STAGE}/ws/{rel}", f"{self.ws}/{rel}"), steps, rel)
        self.assertIn(("bindro", f"{session.STAGE}/ws/other", f"{self.ws}/other"), steps)
        self.assertFalse(any(s[0] == "bindro" and s[-1] == f"{self.ws}/server" for s in steps),
                         "a repository worked in is not also bound read-only")

    def test_the_session_may_start_in_any_of_them(self):
        self.plan(cwd=f"{self.ws}/.worktrees/server/{self.account}")
        with self.assertRaises(session.Refused):
            self.plan(cwd=f"{self.ws}/other")

    def test_what_is_not_one_is_refused(self):
        for bad in (["app"], ["nope"], [".hidden"], ["../x"]):
            with self.assertRaises(session.Refused, msg=bad):
                self.plan(works=bad)

    def test_a_read_that_is_also_worked_in_is_worked_in(self):
        steps = self.plan(reads=["other", "server"])
        self.assertIn(("bindmap", f"{session.STAGE}/ws/server", f"{self.ws}/server"), steps)
        self.assertFalse(any(s[0] == "bindro" and s[-1] == f"{self.ws}/server" for s in steps))


if __name__ == "__main__":
    unittest.main()
