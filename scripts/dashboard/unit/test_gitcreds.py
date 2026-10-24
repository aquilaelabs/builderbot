"""A project's git token kept sealed under the install key (R135): written as
ciphertext where there is a key, open lines sealed at start, read plain by
the dashboard, and handed to git by git-credential-bb only for the scheme
and host it was written for; another key, or none, opens nothing."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import gitcreds  # noqa: E402
import signing  # noqa: E402


class Sealed(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.key = self.tmp / "key"
        self.addCleanup(signing.load_master, str(self.tmp / "none"))
        gitcreds.configure(state=self.tmp, seal_fn=signing.seal, unseal_fn=signing.unseal,
                           sealing_fn=lambda: signing.MASTER is not None)

    def keyed(self, k):
        self.key.write_text(k)
        signing.load_master(str(self.key))

    def ask(self, host, protocol="https"):
        env = {**os.environ, "BB_SIGNING_SECRET_FILE": str(self.key)}
        r = subprocess.run([gitcreds.HELPER, str(gitcreds.path("web")), "get"], input=f"protocol={protocol}\nhost={host}\n\n",
                           capture_output=True, text=True, env=env, timeout=30)
        return r.stdout

    def test_sealed_with_a_key_and_handed_to_git_for_its_host_alone(self):
        self.keyed("k" * 32)
        gitcreds.write_line("web", "https://oauth2:ghp_abc%2F123@github.com")
        self.assertNotIn("ghp_abc", gitcreds.path("web").read_text())
        self.assertEqual(gitcreds.read_line("web"), "https://oauth2:ghp_abc%2F123@github.com")
        self.assertEqual(self.ask("github.com"), "username=oauth2\npassword=ghp_abc/123\n")
        self.assertEqual(self.ask("gitlab.com"), "", "another host is told nothing")
        self.assertEqual(self.ask("github.com", "http"), "", "nor another scheme")
        self.keyed("j" * 32)
        self.assertEqual(self.ask("github.com"), "", "another key opens nothing")
        self.assertEqual(gitcreds.read_line("web"), "")

    def test_open_before_a_key_and_sealed_at_start(self):
        signing.load_master(str(self.tmp / "none"))
        gitcreds.write_line("web", "http://oauth2:tok@gitea.lan:3000")
        self.assertIn("tok@gitea.lan", gitcreds.path("web").read_text())
        self.assertEqual(self.ask("gitea.lan:3000", "http"), "username=oauth2\npassword=tok\n", "an open line works too")
        self.keyed("k" * 32)
        self.assertEqual(gitcreds.seal_all(), 1)
        self.assertNotIn("tok@", gitcreds.path("web").read_text())
        self.assertEqual(self.ask("gitea.lan:3000", "http"), "username=oauth2\npassword=tok\n")
        self.assertEqual(gitcreds.seal_all(), 0)

    def test_a_repo_still_naming_gits_store_counts_as_scoped(self):
        f = str(gitcreds.path("web"))
        self.assertTrue(gitcreds.names_helper(f"store --file={f}\n", "web"))
        self.assertTrue(gitcreds.names_helper(f"!{gitcreds.HELPER} {f}\n", "web"))
        self.assertFalse(gitcreds.names_helper("store --file=/elsewhere\n", "web"))


if __name__ == "__main__":
    unittest.main()
