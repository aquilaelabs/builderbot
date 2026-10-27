"""Every git action is a person's, with their own token (R159): each person
gives a project their own, the project keeps none, a token is used only while
its person holds a live sign-in (logins.py), work that is nobody's takes any
signed-in giver's, and the relay says what a signed-out person's push waits
on."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import accountkeys  # noqa: E402
import gitcreds     # noqa: E402
import logins       # noqa: E402
import signing      # noqa: E402

KEY = bytes(range(32))
ADA, BOB = "u_0000000a", "u_0000000b"
ADA_LINE = "https://ada:ghp_adaadaadaadaadaada1@github.com"
BOB_LINE = "https://bob:ghp_bobbobbobbobbobbob1@github.com"


class PerPerson(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        self.was = signing.MASTER, signing.PREVIOUS
        signing.MASTER, signing.PREVIOUS = KEY, None
        self.addCleanup(lambda: setattr(signing, "MASTER", self.was[0]) or setattr(signing, "PREVIOUS", self.was[1]))
        accountkeys.configure(state=self.d)
        gitcreds.configure(state=self.d, seal_fn=signing.seal, unseal_fn=signing.unseal,
                           sealing_fn=lambda: signing.MASTER is not None)
        self.devices = {}
        logins.configure(state=self.d, devices_of=lambda uid: self.devices.get(uid, []))
        self.ada = accountkeys.link_forge(ADA, "github.com", ADA_LINE, "ada")[0]["id"]
        self.bob = accountkeys.link_forge(BOB, "github.com", BOB_LINE, "bob")[0]["id"]

    def test_each_person_gives_their_own_and_the_project_keeps_none(self):
        gitcreds.link_account("web", ADA, self.ada)
        gitcreds.link_account("web", BOB, self.bob)
        self.assertEqual(gitcreds.givers("web"), [(ADA, self.ada), (BOB, self.bob)])
        self.assertEqual(gitcreds.linked_to("web"), (ADA, self.ada), "the first giver, for what read the one link")
        self.assertEqual(gitcreds.linked_projects(BOB), ["web"])
        raw = (self.d / "gitcreds" / "web").read_text()
        self.assertNotIn("ghp_", raw, "the project's file names entries, never a token")
        self.assertTrue(gitcreds.unlink_person("web", ADA))
        self.assertEqual(gitcreds.givers("web"), [(BOB, self.bob)])
        self.assertFalse(gitcreds.unlink_person("web", ADA))
        gitcreds.unlink_person("web", BOB)
        self.assertEqual(gitcreds.givers("web"), [])
        self.assertFalse((self.d / "gitcreds" / "web").exists())

    def test_a_token_is_used_only_while_its_person_is_signed_in(self):
        gitcreds.link_account("web", ADA, self.ada)
        self.assertEqual(gitcreds.read_line("web", uid=ADA), "", "signed out everywhere: nothing")
        self.assertEqual(gitcreds.helpers("web", ADA), [gitcreds.helper("web")], "no helper of their own while signed out")
        lid = logins.mint(ADA, "a browser")
        self.assertTrue(logins.live(ADA))
        self.assertEqual(gitcreds.read_line("web", uid=ADA), ADA_LINE)
        self.assertEqual(len(gitcreds.helpers("web", ADA)), 2)
        logins.drop(ADA, lid)
        self.assertFalse(logins.live(ADA))
        self.assertEqual(gitcreds.read_line("web", uid=ADA), "")
        # A device signed in as them counts the same way.
        self.devices[ADA] = [{"id": "d1"}]
        self.assertTrue(logins.live(ADA))
        self.assertEqual(gitcreds.read_line("web", uid=ADA), ADA_LINE)

    def test_work_that_is_nobodys_takes_any_signed_in_givers(self):
        gitcreds.link_account("web", ADA, self.ada)
        gitcreds.link_account("web", BOB, self.bob)
        self.assertEqual(gitcreds.read_line("web", uid=""), "", "nobody signed in: nothing, and CI watching pauses")
        logins.mint(BOB, "phone")
        self.assertEqual(gitcreds.read_line("web", uid=""), BOB_LINE)
        self.assertEqual(gitcreds.read_line("web", uid=ADA), BOB_LINE, "Ada signed out: Bob's, as the project's helper gives it")
        logins.mint(ADA, "desk")
        self.assertEqual(gitcreds.read_line("web", uid=ADA), ADA_LINE, "signed in: her own first")
        # The acting account, set per request, is the default.
        tok = gitcreds.ACTING.set(ADA)
        try:
            self.assertEqual(gitcreds.read_line("web"), ADA_LINE)
        finally:
            gitcreds.ACTING.reset(tok)

    def test_usable_says_what_a_push_runs_with_or_waits_on(self):
        self.assertIn("no git token", gitcreds.usable("web", ADA)["why"])
        gitcreds.link_account("web", ADA, self.ada)
        u = gitcreds.usable("web", ADA)
        self.assertEqual((u["mine"], u["live"]), (True, False))
        self.assertIn("bb git waits for you to sign in", u["why"])
        self.assertIn("nobody who gave this project a token is signed in", gitcreds.usable("web", BOB)["why"])
        logins.mint(ADA)
        self.assertEqual(gitcreds.usable("web", ADA), {"by": ADA, "mine": True, "live": True, "given": True, "why": ""})
        u = gitcreds.usable("web", BOB)
        self.assertEqual((u["by"], u["mine"], u["why"]), (ADA, False, ""), "Bob's press runs with Ada's, who is signed in")

    def test_a_sign_in_runs_out_with_its_cookie(self):
        lid = logins.mint(ADA)
        d = logins._load()
        d[ADA][lid]["at"] = int(time.time()) - (logins.DAYS + 1) * 86400
        logins._save(d)
        self.assertFalse(logins.live(ADA))
        self.assertEqual(logins.count(ADA), 0)
        logins.mint(ADA)
        self.assertEqual(logins.count(ADA), 1, "the run-out one pruned")
        logins.drop_all(ADA)
        self.assertFalse(logins.live(ADA))

    def test_a_store_gone_takes_its_lines_and_a_project_left_with_nobodys_says_so(self):
        gitcreds.link_account("web", ADA, self.ada)
        gitcreds.link_account("web", BOB, self.bob)
        gitcreds.link_account("api", ADA, self.ada)
        self.assertEqual(gitcreds.unlink_account(ADA, "ada"), ["api"], "web keeps Bob's")
        self.assertEqual(gitcreds.givers("web"), [(BOB, self.bob)])
        self.assertEqual([r["project"] for r in gitcreds.gone_rows(["web", "api"])], ["api"])


if __name__ == "__main__":
    unittest.main()
