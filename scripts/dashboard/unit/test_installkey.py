"""The install key made by the install and changed from the page (R154,
installkey.py): a change seals what is kept under the key again under the
new one at once, opens with the one before meanwhile, keeps that one only
while the nodes still need it, and a key set in the environment is never
changed here; the fingerprint names a key and opens nothing."""
import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import accountkeys  # noqa: E402
import gitcreds     # noqa: E402
import installkey   # noqa: E402
import signing      # noqa: E402

OLD = b"a" * 64


class InstallKey(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.kd = self.d / "install-key"
        self.kd.mkdir()
        (self.kd / "key").write_bytes(OLD)
        self.env = {"BB_INSTALL_KEY_DIR": str(self.kd), "BB_INSTALL_KEY_IN": "secrets",
                    "BB_SIGNING_SECRET_FILE": str(self.kd / "key"),
                    "BB_INSTALL_KEY_PREVIOUS_FILE": str(self.kd / "key-previous")}
        self.was = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.master = signing.MASTER, signing.PREVIOUS
        signing.load_master()
        gitcreds.configure(state=self.d, seal_fn=signing.seal, unseal_fn=signing.unseal,
                           sealing_fn=lambda: signing.MASTER is not None)
        accountkeys.configure(state=self.d)
        self.nodes = 0
        installkey.configure(passes=(gitcreds.seal_all, accountkeys.seal_all), nodes_previous=lambda: self.nodes)

    def tearDown(self):
        for k, v in self.was.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        signing.MASTER, signing.PREVIOUS = self.master

    def test_status_says_where_and_names_the_key_without_it(self):
        s = installkey.status()
        self.assertEqual((s["where"], s["changeable"], s["saved"], s["previous"]), ("secrets", True, False, False))
        self.assertRegex(s["fingerprint"], r"^[0-9a-f]{4} [0-9a-f]{4}$")
        self.assertNotIn(OLD.decode(), json.dumps(s))

    def test_a_change_seals_everything_again_under_the_new_key(self):
        gitcreds.write_line("web", "https://x:tok@github.com")
        acct = accountkeys.key_of("u_00000001")
        body, code = installkey.change()
        self.assertEqual(code, 200, body)
        self.assertNotEqual((self.kd / "key").read_bytes(), OLD)
        self.assertEqual(body["resealed"], 2)
        # Opened under the new key alone: the one before is gone, nothing
        # on the nodes needing it.
        self.assertIsNone(signing.PREVIOUS)
        self.assertFalse((self.kd / "key-previous").exists())
        raw = (self.d / "gitcreds" / "web").read_text().strip()
        self.assertTrue(signing.current(base64.b64decode(raw[len(gitcreds.SEALED):])))
        self.assertEqual(gitcreds.read_line("web"), "https://x:tok@github.com")
        self.assertEqual(accountkeys.key_of("u_00000001"), acct)

    def test_the_one_before_is_kept_while_the_nodes_need_it(self):
        self.nodes = 2
        self.assertEqual(installkey.change()[1], 200)
        self.assertEqual((self.kd / "key-previous").read_bytes(), OLD)
        self.assertEqual(installkey.status()["previous_on_nodes"], 2)
        body, code = installkey.change()
        self.assertEqual(code, 409)
        self.assertIn("2 sign-ins", body["error"])
        self.nodes = 0
        self.assertFalse(installkey.status()["previous"])
        self.assertEqual(installkey.change()[1], 200)

    def test_a_pasted_key_and_a_bad_one(self):
        self.assertEqual(installkey.change("short")[1], 400)
        self.assertEqual(installkey.change("b" * 40)[1], 200)
        self.assertEqual((self.kd / "key").read_bytes(), b"b" * 40)

    def test_saved_names_todays_key(self):
        fp = installkey.status()["fingerprint"]
        self.assertEqual(installkey.saved("0000 0000")[1], 409)
        self.assertEqual(installkey.saved(fp)[1], 200)
        self.assertTrue(installkey.status()["saved"])
        installkey.change()
        self.assertFalse(installkey.status()["saved"])

    def test_the_environments_key_is_shown_and_never_changed(self):
        os.environ["BB_INSTALL_KEY_IN"] = "env"
        os.environ["BB_INSTALL_KEY_ADOPTED"] = "yes"
        self.assertEqual(installkey.status()["adopted"], "yes")
        os.environ.pop("BB_INSTALL_KEY_ADOPTED")
        self.assertFalse(installkey.status()["changeable"])
        self.assertEqual(installkey.change()[1], 409)
        self.assertEqual(installkey.reveal()[1], 409)
        self.assertEqual((self.kd / "key").read_bytes(), OLD)

    def test_unseal_opens_with_the_one_before(self):
        blob = signing.seal(b"x")
        (self.kd / "key-previous").write_bytes(OLD)
        (self.kd / "key").write_bytes(b"c" * 64)
        signing.load_master()
        self.assertFalse(signing.current(blob))
        self.assertEqual(signing.unseal(blob), b"x")


if __name__ == "__main__":
    unittest.main()
