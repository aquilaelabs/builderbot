"""A project's own deploy key, made or pasted in its settings (the operator,
12 Oct): the private half goes to the root-only helper on stdin and no
further, the key is wired as the ssh remote to switch to, and one in use
is not forgotten out from under the push."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import names  # noqa: E402
import projects  # noqa: E402

PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIabc app-deploy"


class DeployKey(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        (self.ws / "app").mkdir()
        self.calls, self.push, self.url = [], {"app": {"repo": "o/app"}}, "https://github.com/o/app.git"
        saved = {k: getattr(projects, k) for k in ("WORKSPACE", "PROJECT_NAME", "_key_helper", "agent_keys",
                                                     "ensure_deploy_alias", "load_push", "save_push", "origin_url")}
        self.addCleanup(lambda: [setattr(projects, k, v) for k, v in saved.items()])
        projects.WORKSPACE, projects.PROJECT_NAME = self.ws, names.PROJECT_NAME
        projects._key_helper = lambda argv, text=None: (self.calls.append((argv, text)) or (PUB, ""))
        projects.agent_keys = lambda: [{"name": "app-deploy", "pub": PUB}]
        projects.ensure_deploy_alias = lambda name, pub, host: f"bb-{name}-github-com"
        projects.load_push = lambda: self.push
        projects.save_push = lambda d: None
        projects.origin_url = lambda dest: self.url

    def test_made_and_wired_to_switch_to(self):
        body, st = projects.deploy_key("app", "key-make")
        self.assertEqual(st, 200, body)
        self.assertEqual(self.calls, [(["make", "app-deploy"], None)])
        self.assertEqual(body["deploy"]["pub"], PUB)
        self.assertEqual(body["deploy"]["page"], "https://github.com/o/app/settings/keys")
        self.assertEqual(self.push["app"]["ssh_url"], "git@bb-app-deploy-github-com:o/app.git")

    def test_a_paste_goes_on_stdin_and_nowhere_else(self):
        key = "-----BEGIN OPENSSH PRIVATE KEY-----\nxyz\n-----END OPENSSH PRIVATE KEY-----\n"
        body, st = projects.deploy_key("app", "key-store", key)
        self.assertEqual(st, 200, body)
        self.assertEqual(self.calls, [(["store", "app-deploy"], key)])
        self.assertNotIn("xyz", repr(body))
        self.assertEqual(projects.deploy_key("app", "key-store", "not a key")[1], 400)

    def test_a_read_only_clone_gets_none(self):
        self.push = {}
        body, st = projects.deploy_key("app", "key-make")
        self.assertEqual(st, 400)
        self.assertIn("without push rights", body["error"])
        self.assertEqual(self.calls, [])

    def test_the_key_in_use_is_not_forgotten(self):
        self.url = "git@bb-app-deploy-github-com:o/app.git"
        body, st = projects.deploy_key("app", "key-forget")
        self.assertEqual(st, 409, body)
        self.assertEqual(self.calls, [])
        self.url = "https://github.com/o/app.git"
        self.push["app"]["ssh_url"] = "git@bb-app-deploy-github-com:o/app.git"
        body, st = projects.deploy_key("app", "key-forget")
        self.assertEqual(st, 200, body)
        self.assertNotIn("ssh_url", self.push["app"], "nothing left to switch back to")


if __name__ == "__main__":
    unittest.main()
