"""The settings' secrets sealed under the install key (R135): the tunnel's and
Cloudflare's tokens kept as ciphertext in settings.json once the install has
a key, those kept open before sealed at start, opened only for the code that
uses them, still said to be set on the Settings page, and read as unset by an
install that has another key or none."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settings  # noqa: E402
import signing  # noqa: E402


def write_json(p, d, mode=0o644):
    Path(p).write_text(json.dumps(d))


class Sealed(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        settings.configure(write_json=write_json, state=self.tmp)
        self.addCleanup(signing.load_master, str(self.tmp / "none"))
        for k in ("seal", "unseal", "sealing"):
            self.addCleanup(setattr, settings, k, getattr(settings, k))
        settings.seal, settings.unseal = signing.seal, signing.unseal
        settings.sealing = lambda: signing.MASTER is not None

    def key(self, k):
        (self.tmp / "key").write_text(k)
        signing.load_master(str(self.tmp / "key"))

    def stored(self):
        return json.loads((self.tmp / "settings.json").read_text())

    def test_open_without_a_key_and_sealed_at_start_once_there_is_one(self):
        signing.load_master(str(self.tmp / "none"))
        settings.set_many({"tunnel_token": "eyJ-a-tunnel-token"})
        self.assertEqual(self.stored()["tunnel_token"], "eyJ-a-tunnel-token")
        self.key("k" * 32)
        self.assertEqual(settings.seal_all(), 1)
        self.assertTrue(self.stored()["tunnel_token"].startswith("bbseal:"))
        self.assertNotIn("eyJ-a-tunnel-token", (self.tmp / "settings.json").read_text())
        self.assertEqual(settings.secret("tunnel_token"), "eyJ-a-tunnel-token")
        self.assertEqual(settings.seal_all(), 0, "nothing sealed twice")

    def test_written_sealed_said_set_and_unset_under_another_key(self):
        self.key("k" * 32)
        settings.set_many({"cf_api_token": "cf-api-token-123"})
        self.assertNotIn("cf-api-token-123", (self.tmp / "settings.json").read_text())
        eff = settings.effective()["cf_api_token"]
        self.assertEqual((eff["value"], eff["set"]), ("", True))
        self.assertEqual(settings.secret("cf_api_token"), "cf-api-token-123")
        self.key("j" * 32)
        self.assertEqual(settings.secret("cf_api_token"), "", "another key opens nothing")


if __name__ == "__main__":
    unittest.main()
