"""A publisher's signature (R137 step 4): a checksum file believed only when
the publisher's key signed its exact bytes, and the shell's check of a
signed download; a tampered file or a stranger's key refused. A throwaway
key made in a private gpg home stands in for the publisher's."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import sdkmeta  # noqa: E402

LIB = os.path.join(os.path.dirname(__file__), "..", "..", "lib")


def key(home, who):
    env = dict(os.environ, GNUPGHOME=home)
    subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-gen-key", who, "ed25519", "sign", "never"],
                   env=env, capture_output=True, check=True)
    return env


@unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgv"), "no gpg here")
class Signed(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.home, self.other = os.path.join(self.d, "pub"), os.path.join(self.d, "stranger")
        os.makedirs(self.home, mode=0o700)
        os.makedirs(self.other, mode=0o700)
        self.env = key(self.home, "Publisher <p@example.com>")
        self.oenv = key(self.other, "Stranger <s@example.com>")
        self.keys = os.path.join(self.d, "keys")
        os.makedirs(self.keys)
        asc = subprocess.run(["gpg", "--batch", "--armor", "--export"], env=self.env, capture_output=True, check=True).stdout
        with open(os.path.join(self.keys, "pub.asc"), "wb") as f:
            f.write(asc)
        self.patch = mock.patch.multiple(sdkmeta, KEYS_DIR=self.keys, CACHE_DIR=os.path.join(self.d, "cache"))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def sign(self, data, env):
        p = os.path.join(self.d, "x")
        with open(p, "wb") as f:
            f.write(data)
        subprocess.run(["gpg", "--batch", "--yes", "--detach-sign", "-o", p + ".sig", p], env=env, capture_output=True, check=True)
        with open(p + ".sig", "rb") as f:
            return f.read()

    def test_a_signed_list_is_believed_and_says_who(self):
        data = b"ab" * 32 + b"  node.tar.xz\n"
        self.assertIn("Publisher", sdkmeta.signed_by(data, self.sign(data, self.env), "pub.asc"))

    def test_a_tampered_list_or_a_strangers_key_is_refused(self):
        data = b"ab" * 32 + b"  node.tar.xz\n"
        sig = self.sign(data, self.env)
        with self.assertRaises(SystemExit):
            sdkmeta.signed_by(data.replace(b"ab", b"cd", 1), sig, "pub.asc")
        with self.assertRaises(SystemExit):
            sdkmeta.signed_by(data, self.sign(data, self.oenv), "pub.asc")

    def test_the_shell_checks_a_signed_download(self):
        dl = os.path.join(self.d, "dl")
        with open(dl, "wb") as f:
            f.write(b"payload")
        good = self.sign(b"payload", self.env)
        sigp = os.path.join(self.d, "good.sig")
        with open(sigp, "wb") as f:
            f.write(good)
        ring = sdkmeta.keyring("pub.asc")
        script = f"""
source {LIB}/common.sh
source {LIB}/sdk.sh
sdk_fetch() {{ cp {sigp} "$2"; }}
sdk_meta() {{ case "$1" in keyring) echo {ring} ;; *) printf 'gpg\\tfile:///sig\\tpub.asc\\n' ;; esac; }}
sdk_verify_download thing {dl} https://x/thing.tar.gz 1 {self.d}
cat {self.d}/.bb-verified
"""
        p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("signed by Publisher", p.stdout)
        with open(dl, "wb") as f:
            f.write(b"tampered")
        p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("does not carry its publisher's signature", p.stderr)
        self.assertFalse(os.path.exists(dl), "the bad download is removed")


if __name__ == "__main__":
    unittest.main()
