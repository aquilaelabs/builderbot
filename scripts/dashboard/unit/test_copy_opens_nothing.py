"""A copy of /config opens nothing (R135 step 5): with an install key, the
secrets the controller keeps there (a project's git token, the tunnel's and
Cloudflare's tokens) are ciphertext, the sign-in cookies' key is not kept at
all, and none of them is found in any file of the state, byte for byte; a
controller holding the copy without the key, or with another key, opens
none of them."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gitcreds  # noqa: E402
import settings  # noqa: E402
import signing  # noqa: E402

GIT_TOKEN = "ghp_CopyOfConfigTokenValue123"
TUNNEL = "eyJhIjoiY29weS1vZi1jb25maWctdHVubmVsIn0"
CF = "cf-copy-of-config-api-token"


def write_json(p, d, mode=0o644):
    Path(p).write_text(json.dumps(d))


class CopyOpensNothing(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "config"
        self.state.mkdir()
        (self.tmp / "key").write_text("an-install-key-of-thirty-two-chr")
        signing.load_master(str(self.tmp / "key"))
        self.addCleanup(signing.load_master, str(self.tmp / "none"))
        for mod in (settings,):
            for k in ("seal", "unseal", "sealing"):
                self.addCleanup(setattr, mod, k, getattr(mod, k))
        hooks = dict(seal_fn=signing.seal, unseal_fn=signing.unseal, sealing_fn=lambda: signing.MASTER is not None)
        gitcreds.configure(state=self.state, **hooks)
        settings.configure(write_json=write_json, state=self.state)
        settings.seal, settings.unseal = signing.seal, signing.unseal
        settings.sealing = lambda: signing.MASTER is not None
        gitcreds.write_line("web", f"https://oauth2:{GIT_TOKEN}@github.com")
        settings.set_many({"tunnel_token": TUNNEL, "cf_api_token": CF})

    def every_byte(self, root):
        return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())

    def test_no_secret_is_in_any_file_of_the_state(self):
        raw = self.every_byte(self.state)
        for s in (GIT_TOKEN, TUNNEL, CF):
            self.assertNotIn(s.encode(), raw, s)
        self.assertFalse((self.state / "dashboard-secret").exists())

    def test_the_copy_opens_nothing_without_the_key_or_with_another(self):
        copy = self.tmp / "copy"
        shutil.copytree(self.state, copy)
        gitcreds.configure(state=copy)
        settings.configure(write_json=write_json, state=copy)
        for key in (None, "another-key-of-thirty-two-chars!"):
            if key:
                (self.tmp / "other").write_text(key)
                signing.load_master(str(self.tmp / "other"))
            else:
                signing.load_master(str(self.tmp / "none"))
            self.assertEqual(gitcreds.read_line("web"), "")
            self.assertEqual(settings.secret("tunnel_token"), "")
            self.assertEqual(settings.secret("cf_api_token"), "")

    def test_the_right_key_opens_them(self):
        self.assertEqual(gitcreds.read_line("web"), f"https://oauth2:{GIT_TOKEN}@github.com")
        self.assertEqual(settings.secret("tunnel_token"), TUNNEL)


if __name__ == "__main__":
    unittest.main()
