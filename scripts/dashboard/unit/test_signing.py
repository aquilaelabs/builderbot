"""signing.py (R106): a project's Android keys kept by the controller.
Against a real keytool where one is installed (the jdk toolchain), skipped
where none is: a key is checked before it is kept, the listing carries no
password, the files are the owner's alone, and backup marks it saved."""
import base64
import glob
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import signing  # noqa: E402


def find_keytool():
    for c in [os.environ.get("BB_KEYTOOL", ""), shutil.which("keytool") or "",
              *glob.glob("/mnt/SDK/*/jdk/bin/keytool"), *glob.glob("/sdk/*/jdk/bin/keytool")]:
        if c and os.access(c, os.X_OK):
            return c
    return ""


KT = find_keytool()


@unittest.skipUnless(KT, "no keytool on this machine (the jdk toolchain)")
class Signing(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        signing.configure(state=self.tmp / "state", project_name=re.compile(r"[A-Za-z0-9._-]+"),
                          keytool=lambda: KT)
        self.ks = self.tmp / "k.p12"
        subprocess.run([KT, "-genkeypair", "-keystore", str(self.ks), "-storetype", "PKCS12",
                        "-storepass", "s3cret-pass", "-alias", "upload", "-keyalg", "RSA",
                        "-keysize", "2048", "-validity", "100", "-dname", "CN=Test"],
                       check=True, capture_output=True)
        self.b64 = base64.b64encode(self.ks.read_bytes()).decode()

    def test_a_key_is_kept_once_keytool_reads_it(self):
        r, st = signing.put("app", "sideload", self.b64, "s3cret-pass", by="sean")
        self.assertEqual(st, 200, r)
        self.assertEqual(r["key"]["alias"], "upload")
        self.assertRegex(r["key"]["sha256"], r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")
        self.assertNotIn("store_pass", r["key"])
        d = self.tmp / "state" / "signing" / "app"
        self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700)
        for f in d.iterdir():
            self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600, f)

    def test_a_wrong_password_is_refused_and_nothing_kept(self):
        r, st = signing.put("app", "play", self.b64, "nope")
        self.assertEqual(st, 400)
        self.assertIn("password", r["error"])
        self.assertIsNone(signing.listing("app")[0]["keys"]["play"])

    def test_the_listing_never_carries_a_password(self):
        signing.put("app", "play", self.b64, "s3cret-pass")
        listed = signing.listing("app")[0]
        self.assertNotIn("s3cret-pass", repr(listed))
        self.assertEqual(listed["keys"]["play"]["alias"], "upload")
        self.assertIsNone(listed["keys"]["sideload"])

    def test_backup_hands_the_keystore_back_and_marks_it(self):
        signing.put("app", "sideload", self.b64, "s3cret-pass")
        self.assertEqual(signing.listing("app")[0]["keys"]["sideload"]["backed_up"], 0)
        (name, blob), st = signing.backup("app", "sideload")
        self.assertEqual(st, 200)
        self.assertEqual(name, "app-sideload.p12")
        self.assertEqual(blob, self.ks.read_bytes())
        self.assertGreater(signing.listing("app")[0]["keys"]["sideload"]["backed_up"], 0)

    def test_remove(self):
        signing.put("app", "play", self.b64, "s3cret-pass")
        self.assertEqual(signing.remove("app", "play")[1], 200)
        self.assertEqual(signing.remove("app", "play")[1], 404)

    def test_only_the_two_routes_and_a_real_project(self):
        self.assertEqual(signing.put("app", "other", self.b64, "s3cret-pass")[1], 400)
        self.assertEqual(signing.put("../x", "play", self.b64, "s3cret-pass")[1], 400)


class NoKeytool(unittest.TestCase):
    def test_without_one_it_says_what_to_install(self):
        signing.configure(state=tempfile.mkdtemp(), project_name=re.compile(r"[A-Za-z0-9._-]+"),
                          keytool=lambda: None)
        r, st = signing.put("app", "play", base64.b64encode(b"x").decode(), "p")
        self.assertEqual(st, 400)
        self.assertIn("jdk toolchain", r["error"])


if __name__ == "__main__":
    unittest.main()
