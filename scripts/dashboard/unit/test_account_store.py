"""An account's own key store (R154): a forge token it links is kept sealed
under its own key and sealed again when that key changes; its own git work
asks it before the project's; a project can be linked to it, and git's
helper then answers from the account's store; purging it, or removing the
account, unlinks those projects, each saying so until it is given access
again."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import accountkeys  # noqa: E402
import gitcreds     # noqa: E402
import signing      # noqa: E402

UID = "u_0000000a"
LINE = "https://octo:ghp_abcdefghijklmnop0123@github.com"
KEY = b"k" * 64


class Store(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.was = signing.MASTER, signing.PREVIOUS
        signing.MASTER, signing.PREVIOUS = KEY, None
        accountkeys.configure(state=self.d)
        gitcreds.configure(state=self.d, seal_fn=signing.seal, unseal_fn=signing.unseal,
                           sealing_fn=lambda: signing.MASTER is not None)
        self.assertEqual(accountkeys.link_forge(UID, "github.com", LINE, "octo")[1], 200)

    def tearDown(self):
        signing.MASTER, signing.PREVIOUS = self.was

    def test_kept_sealed_under_the_accounts_own_key(self):
        raw = (self.d / "account-secrets.json").read_text()
        self.assertNotIn("ghp_abcdefghijklmnop0123", raw)
        self.assertEqual(accountkeys.forge_line(UID, "GitHub.com"), LINE)
        self.assertEqual(accountkeys.forges_of(UID)[0]["login"], "octo")
        self.assertEqual(accountkeys.forge_line("u_0000000b", "github.com"), "")

    def test_a_key_change_seals_the_store_again(self):
        before = (self.d / "account-secrets.json").read_text()
        self.assertEqual(accountkeys.change(UID)[1], 200)
        self.assertNotEqual((self.d / "account-secrets.json").read_text(), before)
        self.assertEqual(accountkeys.forge_line(UID, "github.com"), LINE)

    def test_their_own_work_asks_their_store_first(self):
        gitcreds.write_line("web", "https://x:projtoken123@github.com")
        hs = gitcreds.helpers("web", UID)
        self.assertEqual(len(hs), 2)
        self.assertIn("--account", hs[0])
        self.assertEqual(gitcreds.helpers("web"), [gitcreds.helper("web")])
        self.assertEqual(gitcreds.helpers("web", "u_0000000b"), [gitcreds.helper("web")])

    def helper(self, argv, host="github.com"):
        env = {**os.environ, "BB_SIGNING_SECRET_FILE": str(self.d / "key")}
        (self.d / "key").write_bytes(KEY)
        r = subprocess.run([sys.executable, str(HERE.parent / "git-credential-bb"), *argv],
                           input=f"protocol=https\nhost={host}\n", capture_output=True, text=True, env=env, timeout=30)
        return r.stdout

    def test_the_helper_answers_from_the_account(self):
        self.assertIn("password=ghp_abcdefghijklmnop0123", self.helper(["--account", str(self.d), UID, "get"]))
        self.assertEqual(self.helper(["--account", str(self.d), UID, "get"], host="gitlab.com"), "")

    def test_a_project_linked_to_the_account(self):
        gitcreds.link_account("web", UID, "github.com")
        self.assertEqual(gitcreds.linked_to("web"), (UID, "github.com"))
        self.assertEqual(gitcreds.read_line("web"), LINE)
        self.assertEqual(gitcreds.linked_projects(UID), ["web"])
        self.assertIn("password=ghp_abcdefghijklmnop0123", self.helper([str(self.d / "gitcreds" / "web"), "get"]))
        # Sealing the install's own leaves a link as it is.
        gitcreds.seal_all(again=True)
        self.assertEqual(gitcreds.linked_to("web"), (UID, "github.com"))

    def test_the_store_gone_unlinks_its_projects(self):
        gitcreds.link_account("web", UID, "github.com")
        self.assertEqual(gitcreds.unlink_account(UID, "ada"), ["web"])
        accountkeys.forget(UID)
        self.assertEqual(gitcreds.read_line("web"), "")
        self.assertEqual(accountkeys.forges_of(UID), [])
        rows = gitcreds.gone_rows(["web"])
        self.assertEqual((rows[0]["kind"], rows[0]["name"]), ("git-unlinked", "ada"))
        gitcreds.write_line("web", "https://x:projtoken123@github.com")
        self.assertEqual(gitcreds.gone_rows(["web"]), [])


if __name__ == "__main__":
    unittest.main()
