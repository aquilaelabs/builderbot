"""projects.set_address: the same repository at its new address, after its
owner or organization was renamed on the host. Real git throughout: the
"new address" is an https URL that git's url.insteadOf sends to a local bare
repository, so ls-remote is asked for real with no network."""
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import projects  # noqa: E402


def run(cmd, cwd=None, timeout=120, env=None, split_err=False, register=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, timeout=timeout, check=False)
    out, err = p.stdout or "", p.stderr or ""
    if not split_err:
        out, err = out + err, ""
    return {"cmd": shlex.join(cmd), "code": p.returncode, "out": out, "err": err}


def git(*a, cwd=None):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))


class SetAddress(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        ws, state = self.tmp / "ws", self.tmp / "state"
        ws.mkdir()
        state.mkdir()

        def write_json(path, d):
            Path(path).write_text(json.dumps(d))
        projects.configure(run=run, workspace=ws, agent_keys=lambda: [], gh_authed=lambda: False,
                           ensure_deploy_alias=lambda *a: "", project_name=re.compile(r"[A-Za-z0-9._-]+"),
                           state=state, home=self.tmp, write_json=write_json)
        self.dest = ws / "app"
        self.dest.mkdir()
        git("init", "-q", "-b", "main", cwd=self.dest)
        (self.dest / "f").write_text("x")
        git("add", "f", cwd=self.dest)
        git("commit", "-qm", "one", cwd=self.dest)
        git("remote", "add", "origin", "https://example.test/OldOwner/app.git", cwd=self.dest)
        # The repository at its new address: this project's history.
        self.bare = self.tmp / "renamed.git"
        git("clone", "-q", "--bare", str(self.dest), str(self.bare))
        git("config", f"url.{self.bare}.insteadOf", "https://example.test/NewOwner/app.git", cwd=self.dest)
        # ...and an unrelated one.
        other = self.tmp / "other"
        other.mkdir()
        git("init", "-q", "-b", "main", cwd=other)
        (other / "g").write_text("y")
        git("add", "g", cwd=other)
        git("commit", "-qm", "else", cwd=other)
        git("clone", "-q", "--bare", str(other), str(self.tmp / "other.git"))
        git("config", f"url.{self.tmp / 'other.git'}.insteadOf", "https://example.test/Someone/else.git", cwd=self.dest)
        projects.grant_push("app", "example.test", "oldowner/app", "token")

    def origin(self):
        # As configured: get-url applies the test's insteadOf.
        return subprocess.run(["git", "-C", str(self.dest), "config", "remote.origin.url"],
                              capture_output=True, text=True, check=False).stdout.strip()

    def test_the_same_repository_moves_with_its_rights(self):
        msg, err = projects.set_address("app", self.dest, "https://example.test/NewOwner/app")
        self.assertEqual(err, "")
        self.assertIn("points at example.test/NewOwner/app", msg)
        self.assertEqual(self.origin(), "https://example.test/NewOwner/app.git")
        self.assertEqual(projects.load_push()["app"]["repo"], "newowner/app")

    def test_another_repository_is_refused_and_nothing_moves(self):
        msg, err = projects.set_address("app", self.dest, "https://example.test/Someone/else.git")
        self.assertIn("shares no commit", err)
        self.assertEqual(self.origin(), "https://example.test/OldOwner/app.git")
        self.assertEqual(projects.load_push()["app"]["repo"], "oldowner/app")

    def test_another_host_is_refused(self):
        _, err = projects.set_address("app", self.dest, "https://elsewhere.test/NewOwner/app.git")
        self.assertIn("another host", err)

    def test_a_repository_another_project_pushes_to_is_refused(self):
        projects.grant_push("other", "example.test", "newowner/app", "token")
        _, err = projects.set_address("app", self.dest, "https://example.test/NewOwner/app.git")
        self.assertIn("other already pushes to", err)

    def test_a_deploy_keys_alias_keeps_its_form(self):
        git("remote", "set-url", "origin", "git@bb-key-github-com:OldOwner/app.git", cwd=self.dest)
        git("config", f"url.{self.bare}.insteadOf", "git@bb-key-github-com:NewOwner/app.git", cwd=self.dest)
        was = projects.forges.host_of
        projects.forges.host_of = lambda u: "github.com"
        try:
            projects.grant_push("app", "github.com", "oldowner/app", "key")
            msg, err = projects.set_address("app", self.dest, "https://github.com/NewOwner/app")
        finally:
            projects.forges.host_of = was
        self.assertEqual(err, "")
        self.assertEqual(self.origin(), "git@bb-key-github-com:NewOwner/app.git")


if __name__ == "__main__":
    unittest.main()
