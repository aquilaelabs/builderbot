"""The signing keys sealed at rest (R111 step 2): with an install key every
keystore and its passwords are ciphertext in /config, opened in memory for
the one who signs; a key sealed under another secret is locked and says so;
without one they are kept as before; keys from before are sealed at start."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import signing  # noqa: E402
import re  # noqa: E402

KS = b"\x30\x82\x0a\x00 a keystore's bytes, whatever they are"


class Sealed(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {k: getattr(signing, k) for k in ("STATE", "PROJECT_NAME", "MASTER")}
        self.addCleanup(lambda: [setattr(signing, k, v) for k, v in saved.items()])
        self.secret = self.tmp / "secret"
        signing.configure(state=self.tmp / "state", project_name=re.compile(r"[a-z]+"),
                          secret_file=str(self.secret))

    def keep(self):
        signing._write_secret(signing._dir("web") / "sideload.ks", KS)
        signing._save_rec("web", "default", "sideload", {"alias": "app", "store_pass": "s3cret-store", "key_pass": "s3cret-key"})

    def disk(self):
        d = signing._dir("web")
        return (d / "sideload.ks").read_bytes(), (d / "sideload.json").read_text()

    def master(self, value):
        self.secret.write_text(value)
        signing.load_master(str(self.secret))

    def test_without_a_secret_kept_as_before(self):
        self.assertIsNone(signing.MASTER)
        self.keep()
        ks, rec = self.disk()
        self.assertEqual(ks, KS)
        self.assertIn("s3cret-store", rec)
        self.assertEqual(signing.at_rest("web"), "open")

    def test_sealed_on_disk_opened_for_the_signer(self):
        self.master("a" * 64)
        self.keep()
        ks, rec = self.disk()
        self.assertTrue(ks.startswith(signing.MAGIC) and KS not in ks)
        self.assertNotIn("s3cret", rec)
        blob, r = signing.secret("web", "sideload")
        self.assertEqual((blob, r["store_pass"], r["key_pass"]), (KS, "s3cret-store", "s3cret-key"))
        self.assertNotIn("store_pass", signing._public(r))
        self.assertNotIn("sealed", signing._public(r))
        self.assertEqual(signing.at_rest("web"), "sealed")

    def test_another_secret_is_locked_and_says_so(self):
        self.master("a" * 64)
        self.keep()
        self.master("b" * 64)
        self.assertIsNone(signing.secret("web", "sideload"))
        self.assertIn("another install key", signing.locked("web", "sideload"))
        self.assertEqual(signing.at_rest("web"), "locked")
        self.assertEqual(signing.backup("web", "sideload")[1], 409)

    def test_a_flipped_byte_is_refused_not_opened(self):
        self.master("a" * 64)
        sealed = bytearray(signing.seal(KS))
        sealed[len(signing.MAGIC) + 20] ^= 1
        with self.assertRaises(signing.Locked):
            signing.unseal(bytes(sealed))
        self.assertNotEqual(signing.seal(KS), signing.seal(KS), "a fresh nonce each seal")

    def test_keys_from_before_sealed_at_start(self):
        self.keep()
        self.master("a" * 64)
        self.assertEqual(signing.at_rest("web"), "mixed")
        self.assertEqual(signing.seal_all(), 1)
        ks, rec = self.disk()
        self.assertTrue(ks.startswith(signing.MAGIC))
        self.assertNotIn("s3cret", rec)
        self.assertEqual(signing.secret("web", "sideload")[0], KS)
        self.assertEqual(signing.seal_all(), 0, "once")

    def test_a_short_secret_is_none(self):
        self.master("short")
        self.assertIsNone(signing.MASTER)


if __name__ == "__main__":
    unittest.main()
