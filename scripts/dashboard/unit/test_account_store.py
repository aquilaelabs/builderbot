"""An account's own key store (R154): a token it gives a repository is kept
sealed under its own key, any number for one host, and sealed again when
that key changes; its own git work asks it before the project's, the entry
its project is linked to first; git's helper answers from it; a token kept
as a project's own from before goes to the project owner's store (0011);
purging it, or removing the account, unlinks those projects, each saying
so until it is given access again."""
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
import logins       # noqa: E402
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
        # A token is used only while its person is signed in (R159): this
        # account is, in a browser.
        logins.configure(state=self.d, devices_of=lambda uid: [])
        logins.mint(UID, "a browser")
        got = accountkeys.link_forge(UID, "github.com", LINE, "octo")
        self.assertEqual(got[1], 200)
        self.fid = got[0]["id"]

    def tearDown(self):
        signing.MASTER, signing.PREVIOUS = self.was

    def test_kept_sealed_under_the_accounts_own_key(self):
        raw = (self.d / "account-secrets.json").read_text()
        self.assertNotIn("ghp_abcdefghijklmnop0123", raw)
        self.assertEqual(accountkeys.forge_line(UID, host="GitHub.com"), LINE)
        self.assertEqual(accountkeys.forge_line(UID, self.fid), LINE)
        self.assertEqual(accountkeys.forges_of(UID)[0]["login"], "octo")
        self.assertEqual(accountkeys.forge_line("u_0000000b", host="github.com"), "")
        # The same token again is the same entry; a new one for that account
        # on the host replaces it in place (the operator, 30 Oct: no record
        # of the tokens before); another account on the host is its own.
        self.assertEqual(accountkeys.link_forge(UID, "github.com", LINE, "octo")[0]["id"], self.fid)
        new = LINE.replace("ghp_abcdef", "ghp_zzzzzz")
        self.assertEqual(accountkeys.link_forge(UID, "github.com", new, "octo")[0]["id"], self.fid)
        self.assertEqual(len(accountkeys.forges_of(UID)), 1)
        self.assertEqual(accountkeys.forge_line(UID, self.fid), new)
        other = accountkeys.link_forge(UID, "github.com", new.replace("octo", "octo2"), "octo2")[0]["id"]
        self.assertNotEqual(other, self.fid)
        self.assertEqual(len(accountkeys.forges_of(UID)), 2)

    def test_a_key_change_seals_the_store_again(self):
        before = (self.d / "account-secrets.json").read_text()
        self.assertEqual(accountkeys.change(UID)[1], 200)
        self.assertNotEqual((self.d / "account-secrets.json").read_text(), before)
        self.assertEqual(accountkeys.forge_line(UID, self.fid), LINE)

    def test_git_c_hands_any_command_the_credential(self):
        gitcreds.write_line("web", "https://x:projtoken123@github.com")
        c = gitcreds.git_c("web", UID)
        self.assertEqual(c[:2], ["-c", "credential.helper="], "the tree's own helpers are reset first")
        self.assertEqual(len([x for x in c if x.startswith("credential.helper=!")]), 1, "the project's own line")
        gitcreds.link_account("web", UID, self.fid)
        c = gitcreds.git_c("web", UID)
        self.assertEqual(len([x for x in c if x.startswith("credential.helper=!")]), 2, "their handout, then the project's")
        self.assertEqual(gitcreds.git_c("nothing-here"), [])

    def test_their_own_work_is_handed_their_token_opened_per_use(self):
        # Their token, given to the project, reaches git as a handout file
        # (R158 step 5): one line, theirs, for the window; the helper
        # opens nothing itself, and the use is on their Profile.
        gitcreds.link_account("web", UID, self.fid)
        hs = gitcreds.helpers("web", UID, why="push")
        self.assertEqual(len(hs), 1)
        handout = hs[0].split(" ", 1)[1].strip("'")
        self.assertTrue(handout.endswith("/web"), handout)
        self.assertEqual(Path(handout).read_text().strip(), LINE)
        self.assertEqual(oct(Path(handout).stat().st_mode & 0o777), "0o600")
        self.assertIn("password=ghp_abcdefghijklmnop0123", self.helper([handout, "get"]))
        import unlocks
        use = unlocks.uses(UID)[0]
        self.assertEqual((use["why"], use["project"], use["host"]), ("push", "web", "github.com"))
        # Locked, nothing is handed out, and what was is shredded.
        unlocks.lock(UID)
        self.assertFalse(Path(handout).exists())
        # Somebody who gave nothing, and work that is nobody's, take a
        # signed-in giver's, handed out the same way and logged for them.
        self.assertEqual(len(gitcreds.helpers("web", "u_0000000b")), 1)
        self.assertEqual(len(gitcreds.helpers("web", "")), 1)
        self.assertEqual(unlocks.uses(UID)[0]["by"], "")

    def helper(self, argv, host="github.com"):
        env = {**os.environ, "BB_SIGNING_SECRET_FILE": str(self.d / "key")}
        (self.d / "key").write_bytes(KEY)
        r = subprocess.run([sys.executable, str(HERE.parent / "git-credential-bb"), *argv],
                           input=f"protocol=https\nhost={host}\n", capture_output=True, text=True, env=env, timeout=30)
        return r.stdout

    def test_the_helper_opens_no_store_itself(self):
        # The form from before, which opened the account's store in the
        # helper's own process, answers nothing: a handout is the way in.
        self.assertEqual(self.helper(["--account", str(self.d), UID, "web", "get"]), "")

    def test_a_project_linked_to_the_account(self):
        gitcreds.link_account("web", UID, self.fid)
        self.assertEqual(gitcreds.linked_to("web"), (UID, self.fid))
        self.assertEqual(gitcreds.read_line("web"), LINE)
        self.assertEqual(gitcreds.linked_projects(UID), ["web"])
        self.assertIn("password=ghp_abcdefghijklmnop0123", self.helper([str(self.d / "gitcreds" / "web"), "get"]))
        # Sealing the install's own leaves a link as it is.
        gitcreds.seal_all(again=True)
        self.assertEqual(gitcreds.linked_to("web"), (UID, self.fid))

    def test_a_token_from_before_goes_to_the_project_owner(self):
        gitcreds.write_line("web", "https://x:projtoken123@github.com")
        gitcreds.write_line("api", "https://y:apitoken123@gitlab.com")
        self.assertEqual(gitcreds.adopt(lambda p: UID), 2)
        self.assertEqual(gitcreds.linked_to("web")[0], UID)
        self.assertEqual(gitcreds.read_line("web"), "https://x:projtoken123@github.com")
        self.assertEqual(gitcreds.read_line("api"), "https://y:apitoken123@gitlab.com")
        self.assertEqual(gitcreds.adopt(lambda p: UID), 0, "once: a linked project is left as it is")

    def test_a_token_given_is_the_givers(self):
        self.assertTrue(gitcreds.keep_for("web", UID, "https://x:given123@github.com", "x"))
        uid, fid = gitcreds.linked_to("web")
        self.assertEqual(uid, UID)
        self.assertEqual(gitcreds.read_line("web"), "https://x:given123@github.com")
        self.assertEqual(gitcreds.linked_projects(UID, fid), ["web"])

    def test_the_store_gone_unlinks_its_projects(self):
        gitcreds.link_account("web", UID, self.fid)
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
