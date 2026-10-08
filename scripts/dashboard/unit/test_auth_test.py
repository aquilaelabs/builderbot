"""projects.auth_test, the project settings' Test (the operator, 7 Oct):
whether what a project authenticates with can read and push, and what it is
missing when it cannot. Real git throughout: the remote is an https URL that
git's url.insteadOf sends to a local bare repository, so ls-remote and the
dry-run push are asked for real with no network. The host's API is stubbed
at forges._ask_full, the one place it is asked."""
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
import forges  # noqa: E402
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


URL = "https://example.test/Owner/app.git"


class AuthTest(unittest.TestCase):
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
        forges.configure(run=run)
        self.dest = ws / "app"
        self.dest.mkdir()
        git("init", "-q", "-b", "main", cwd=self.dest)
        (self.dest / "f").write_text("x")
        git("add", "f", cwd=self.dest)
        git("commit", "-qm", "one", cwd=self.dest)
        git("remote", "add", "origin", URL, cwd=self.dest)
        self.bare = self.tmp / "app.git"
        git("clone", "-q", "--bare", str(self.dest), str(self.bare))
        git("config", f"url.{self.bare}.insteadOf", URL, cwd=self.dest)
        projects.grant_push("app", "example.test", "owner/app", "token")

    def test_a_remote_it_can_read_and_push_says_so_and_pushes_nothing(self):
        j, code = projects.auth_test("app")
        self.assertEqual(code, 200)
        self.assertEqual((j["read"], j["push"], j["missing"]), (True, True, []))
        heads = subprocess.run(["git", "-C", str(self.bare), "for-each-ref", "--format=%(refname)"],
                               capture_output=True, text=True, check=True).stdout
        self.assertNotIn("builderbot-access-check", heads)

    def test_a_push_the_host_refuses_is_named_as_missing_write_access(self):
        git("config", f"url.{self.tmp / 'nowhere.git'}.pushInsteadOf", URL, cwd=self.dest)
        j, _ = projects.auth_test("app")
        self.assertTrue(j["read"])
        self.assertFalse(j["push"])
        self.assertEqual(len(j["missing"]), 1)
        self.assertTrue(j["missing"][0].startswith("write access: "), j["missing"])

    def test_a_remote_it_cannot_read_is_missing_read_and_push_is_not_tried(self):
        git("config", "--unset", f"url.{self.bare}.insteadOf", cwd=self.dest)
        git("config", f"url.{self.tmp / 'nowhere.git'}.insteadOf", URL, cwd=self.dest)
        j, _ = projects.auth_test("app")
        self.assertEqual((j["read"], j["push"]), (False, None))
        self.assertTrue(j["missing"][0].startswith("read access: "), j["missing"])

    def test_without_push_rights_it_says_a_session_cannot_push(self):
        projects.drop_push("app")
        j, _ = projects.auth_test("app")
        self.assertTrue(any("without push rights" in n for n in j["notes"]), j["notes"])

    def test_a_typed_token_is_tried_from_a_file_that_is_gone_after(self):
        before = set(os.listdir(tempfile.gettempdir()))
        j, _ = projects.auth_test("app", "a-typed-token-123")
        self.assertEqual((j["mode"], j["read"], j["push"]), ("typed", True, True))
        left = {f for f in set(os.listdir(tempfile.gettempdir())) - before if f.startswith("bb-authtest-")}
        self.assertEqual(left, set())

    def test_a_403_from_git_is_said_in_words(self):
        saved = projects.run
        def refused(cmd, **kw):
            if "ls-remote" in cmd:
                return {"cmd": "", "code": 128, "out": "", "err": "fatal: unable to access "
                        "'https://github.com/o/r.git/': The requested URL returned error: 403"}
            return saved(cmd, **kw)
        projects.run = refused
        try:
            j, _ = projects.auth_test("app")
        finally:
            projects.run = saved
        self.assertFalse(j["read"])
        self.assertIn("refused it this repository (403)", j["missing"][0])
        self.assertIn("organization may have to approve", j["missing"][0])

    def test_the_hosts_reason_for_a_refused_read_takes_gits_place(self):
        git("config", "--unset", f"url.{self.bare}.insteadOf", cwd=self.dest)
        git("config", f"url.{self.tmp / 'nowhere.git'}.insteadOf", URL, cwd=self.dest)
        saved = forges.token_access
        forges.token_access = lambda *a, **k: {"missing": ["access to owner/app: no"], "notes": []}
        try:
            j, _ = projects.auth_test("app", "a-typed-token-123")
        finally:
            forges.token_access = saved
        self.assertEqual(j["missing"], ["access to owner/app: no"])

    def test_no_remote_is_an_error(self):
        git("remote", "remove", "origin", cwd=self.dest)
        j, code = projects.auth_test("app")
        self.assertEqual(code, 400)
        self.assertIn("no remote", j["error"])


class GitSaid(unittest.TestCase):
    """The line that says why, not the boilerplate git and ssh print around it."""

    def test_the_reason_is_picked_out_of_git_and_ssh_noise(self):
        tail = ("\nfatal: Could not read from remote repository.\n\n"
                "Please make sure you have the correct access rights\nand the repository exists.")
        for said, want in [("Could not create directory '/home/x/.ssh' (Permission denied).\n"
                            "Failed to add the host to the list of known hosts (/home/x/.ssh/known_hosts).\n"
                            "git@github.com: Permission denied (publickey)." + tail,
                            "git@github.com: Permission denied (publickey)."),
                           ("git@github.com: Permission denied (publickey)." + tail,
                            "git@github.com: Permission denied (publickey)."),
                           ("ERROR: The key you are authenticating with has been marked as read only." + tail,
                            "ERROR: The key you are authenticating with has been marked as read only."),
                           ("remote: Permission to o/r.git denied to someone.\nfatal: unable to access "
                            "'https://github.com/o/r.git/': The requested URL returned error: 403",
                            "remote: Permission to o/r.git denied to someone.")]:
            self.assertEqual(projects._git_said({"err": said, "out": "", "code": 128}), want)


class TokenAccess(unittest.TestCase):
    """What GitHub, Gitea and GitLab say about a token, stubbed."""

    def setUp(self):
        self.saved = forges._ask_full

    def tearDown(self):
        forges._ask_full = self.saved

    def answer(self, body, headers=None, code=200, why=""):
        forges._ask_full = lambda url, kind, token, data=None: (body, why, headers or {}, code)

    def test_a_classic_github_token_without_workflow_is_missing_it(self):
        self.answer({"permissions": {"pull": True, "push": True}, "private": True},
                    {"X-OAuth-Scopes": "repo, read:org"})
        got = forges.token_access(forges.BY_ID["github"], "github.com", "t", "o/r")
        self.assertEqual(len(got["missing"]), 1)
        self.assertIn("workflow scope", got["missing"][0])

    def test_a_github_token_that_reads_only_is_missing_write(self):
        self.answer({"permissions": {"pull": True, "push": False}}, {"X-OAuth-Scopes": "repo, workflow"})
        got = forges.token_access(forges.BY_ID["github"], "github.com", "t", "o/r")
        self.assertEqual(len(got["missing"]), 1)
        self.assertTrue(got["missing"][0].startswith("write access to o/r"))

    def test_a_fine_grained_token_says_what_cannot_be_read_back(self):
        self.answer({"permissions": {"pull": True, "push": True}})
        got = forges.token_access(forges.BY_ID["github"], "github.com", "t", "o/r")
        self.assertEqual(got["missing"], [])
        self.assertIn("Workflows permission", got["notes"][0])

    def test_a_revoked_token_is_named(self):
        self.answer(None, code=401, why="Bad credentials")
        got = forges.token_access(forges.BY_ID["github"], "github.com", "t", "o/r")
        self.assertIn("Bad credentials", got["missing"][0])

    def test_a_gitlab_reporter_cannot_push(self):
        self.answer({"permissions": {"project_access": {"access_level": 20}, "group_access": None},
                     "scopes": ["read_repository", "write_repository"]})
        got = forges.token_access(forges.BY_ID["gitlab"], "gitlab.com", "t", "g/r")
        self.assertEqual(len(got["missing"]), 1)
        self.assertIn("Developer role", got["missing"][0])

    def test_a_host_with_no_api_answers_nothing(self):
        got = forges.token_access(forges.OTHER, "example.test", "t", "o/r")
        self.assertEqual(got, {"missing": [], "notes": []})


if __name__ == "__main__":
    unittest.main()
