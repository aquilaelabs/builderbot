"""An unlock that gives up less (R158 step 5) and a key of the person's own
(R157): a token opened per use for the window picked and logged; a store
moved under a key the person holds opens only while unlocked, with a
secret that is theirs; Lock lets go of everything, handouts included; the
node's public halves are remembered while it is shut; the move puts a
project's background token in the project's own keeping unless kept."""
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
AGENT = str(HERE.parent.parent / "agent")

import accountkeys  # noqa: E402
import gitcreds     # noqa: E402
import logins       # noqa: E402
import signing      # noqa: E402
import tokenkeys    # noqa: E402
import unlocks      # noqa: E402

UID, OTHER = "u_0000000a", "u_0000000b"
LINE = "https://octo:ghp_abcdefghijklmnop0123@github.com"
KEY = b"k" * 32


class Unlocks(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        self.was = signing.MASTER, signing.PREVIOUS
        signing.MASTER, signing.PREVIOUS = KEY, None
        self.addCleanup(lambda: setattr(signing, "MASTER", self.was[0]) or setattr(signing, "PREVIOUS", self.was[1]))
        tokenkeys.configure(agent_dir=AGENT)
        tokenkeys._pub_cache.clear()
        accountkeys.configure(state=self.d)
        unlocks.configure(run_dir=str(self.d / "run"))
        gitcreds.configure(state=self.d, seal_fn=signing.seal, unseal_fn=signing.unseal,
                           sealing_fn=lambda: signing.MASTER is not None)
        logins.configure(state=self.d, devices_of=lambda uid: [])
        logins.mint(UID, "a browser")
        self.fid = accountkeys.link_forge(UID, "github.com", LINE, "octo")[0]["id"]
        unlocks._open.clear()
        self.addCleanup(unlocks._open.clear)

    def test_a_token_is_opened_per_use_for_the_window_and_logged(self):
        st = unlocks.status(UID)
        self.assertEqual((st["own"], st["locked"], st["for"]), (False, False, 3600))
        self.assertEqual(accountkeys.forge_line(UID, self.fid, why="push", project="web", by=UID), LINE)
        u = unlocks.uses(UID)[0]
        self.assertEqual((u["why"], u["project"], u["host"], u["login"]), ("push", "web", "github.com", "octo"))
        self.assertEqual(unlocks.status(UID)["open_tokens"], 1)
        # Within the window the opened line is what answers; after it, the
        # seal is opened again (and logged again).
        unlocks._open[UID]["tokens"][self.fid]["until"] = int(time.time()) - 1
        self.assertEqual(accountkeys.forge_line(UID, self.fid, why="pull"), LINE)
        self.assertEqual(unlocks.uses(UID)[0]["why"], "pull")
        # The window picked is kept with the key record.
        self.assertTrue(accountkeys.set_unlock_for(UID, 900))
        self.assertFalse(accountkeys.set_unlock_for(UID, 123))
        self.assertEqual(unlocks.status(UID)["for"], 900)
        # Lock lets go: nothing open, said in the log.
        unlocks.lock(UID)
        self.assertEqual(unlocks.status(UID)["open_tokens"], 0)
        self.assertEqual(unlocks.uses(UID)[0]["why"], "locked")

    def test_a_key_of_the_persons_own(self):
        before = accountkeys.status(UID)["fingerprint"]
        secret = bytes(range(32))
        gitcreds.link_account("web", UID, self.fid)
        # Moving: the sealed account key goes under the person's public
        # half, the install key's seal of it goes, and the store is open.
        body, code = accountkeys.move_to_own(UID, secret, "key")
        self.assertEqual(code, 200, body)
        rec = accountkeys._entry(UID)
        self.assertNotIn("key", rec)
        self.assertEqual(rec["own"]["how"], "key")
        st = accountkeys.status(UID)
        self.assertEqual((st["own"], st["locked"], st["fingerprint"]), (True, False, before))
        self.assertEqual(accountkeys.forge_line(UID, self.fid, why="push", project="web"), LINE)
        # Locked: nothing opens, the fingerprint still shows, git waits and says why.
        unlocks.lock(UID)
        st = accountkeys.status(UID)
        self.assertEqual((st["locked"], st["fingerprint"]), (True, before))
        self.assertIsNone(accountkeys.key_of(UID))
        self.assertEqual(accountkeys.forge_line(UID, self.fid), "")
        self.assertEqual(gitcreds.helpers("web", UID), [])
        self.assertIn("locked", gitcreds.usable("web", UID)["why"])
        self.assertIn("locked", gitcreds.usable("web", OTHER)["why"], "the one giver signed in has it locked")
        # Nobody else's secret opens it; theirs does, for the window.
        self.assertIn("error", unlocks.unlock(UID, b"x" * 32))
        got = unlocks.unlock(UID, secret, 28800)
        self.assertTrue(got.get("ok"), got)
        self.assertEqual(unlocks.status(UID)["for"], 28800)
        self.assertEqual(accountkeys.forge_line(UID, self.fid), LINE)
        self.assertEqual(len(gitcreds.helpers("web", UID)), 1)
        # A terminal's seal keys and the node's public half come from the
        # opened key; shut, the public half is the one remembered.
        pub = tokenkeys.public("n1", UID)
        self.assertTrue(pub)
        unlocks.lock(UID)
        self.assertEqual(tokenkeys.public("n1", UID), pub, "remembered while shut, so a login is still sealed")
        self.assertEqual(tokenkeys.public("n2", UID), "", "a node never seen while open has none")
        # Changing the account key is refused under an own key; back under
        # the install key it works again, and the own record is gone.
        self.assertEqual(accountkeys.change(UID)[1], 409)
        self.assertEqual(accountkeys.move_back(UID)[1], 409, "locked: give it back only while open")
        unlocks.unlock(UID, secret)
        self.assertEqual(accountkeys.move_back(UID)[1], 200)
        self.assertNotIn("own", accountkeys._entry(UID))
        self.assertEqual(accountkeys.status(UID)["own"], False)
        self.assertEqual(accountkeys.forge_line(UID, self.fid), LINE)

    def test_the_window_runs_out_and_a_handout_is_shredded(self):
        gitcreds.link_account("web", UID, self.fid)
        hs = gitcreds.helpers("web", UID, why="fetch")
        handout = Path(hs[0].split(" ", 1)[1].strip("'"))
        self.assertTrue(handout.is_file())
        unlocks._open[UID]["until"] = int(time.time()) - 1
        unlocks.sweep()
        self.assertFalse(handout.exists(), "the window ended: shredded")
        self.assertEqual(unlocks.uses(UID)[0]["why"], "the window ended")
        # A start clears what an earlier process handed out.
        gitcreds.helpers("web", UID, why="fetch")
        unlocks.clear_all_handouts()
        self.assertEqual([p for p in (self.d / "run").rglob("*") if p.is_file()], [])

    def test_a_secret_typed_and_the_prf_salt(self):
        self.assertIsNone(unlocks.secret_from_hex("short"))
        self.assertEqual(len(unlocks.secret_from_hex("ab" * 32)), 32)
        self.assertEqual(unlocks.prf_salt(UID), unlocks.prf_salt(UID))
        self.assertNotEqual(unlocks.prf_salt(UID), unlocks.prf_salt(OTHER))
        self.assertEqual(len(unlocks.new_secret()), 64)


class TheProjectsOwnLine(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        self.was = signing.MASTER, signing.PREVIOUS
        signing.MASTER, signing.PREVIOUS = KEY, None
        self.addCleanup(lambda: setattr(signing, "MASTER", self.was[0]) or setattr(signing, "PREVIOUS", self.was[1]))
        accountkeys.configure(state=self.d)
        gitcreds.configure(state=self.d, seal_fn=signing.seal, unseal_fn=signing.unseal,
                           sealing_fn=lambda: signing.MASTER is not None)
        logins.configure(state=self.d, devices_of=lambda uid: [])
        unlocks._open.clear()
        self.addCleanup(unlocks._open.clear)

    def test_kept_beside_the_givers_and_read_when_nobody_can(self):
        fid = accountkeys.link_forge(UID, "github.com", LINE, "octo")[0]["id"]
        gitcreds.link_account("web", UID, fid)
        self.assertTrue(gitcreds.keep_as_own("web", LINE))
        raw = (self.d / "gitcreds" / "web").read_text()
        self.assertIn(f"account:{UID}:{fid}", raw)
        self.assertNotIn("ghp_", raw, "sealed")
        self.assertEqual(gitcreds.givers("web"), [(UID, fid)])
        self.assertTrue(gitcreds.own_line("web"))
        # Nobody signed in: the project's own line serves, and usable says so.
        self.assertEqual(gitcreds.read_line("web", uid=""), LINE)
        self.assertEqual(gitcreds.usable("web", "")["why"], "")
        self.assertEqual(len(gitcreds.helpers("web", "")), 1)
        # The givers' lines move without losing it, and losing the last giver keeps it.
        gitcreds.unlink_person("web", UID)
        self.assertTrue(gitcreds.own_line("web"))
        self.assertEqual(gitcreds.givers("web"), [])


if __name__ == "__main__":
    unittest.main()
