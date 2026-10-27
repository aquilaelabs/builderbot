"""sdk.sh's sdk_verify_download (R137): a download that matches what its
publisher states is kept and the install says how it was checked; one that
does not is removed and the install stops naming both digests; a row whose
publisher states nothing says so and goes on."""
import hashlib
import os
import subprocess
import tempfile
import unittest

LIB = os.path.join(os.path.dirname(__file__), "..", "..", "lib")


def run(answer, body=b"payload"):
    d = tempfile.mkdtemp()
    f = os.path.join(d, "dl")
    with open(f, "wb") as fh:
        fh.write(body)
    script = f"""
source {LIB}/common.sh
source {LIB}/sdk.sh
sdk_meta() {{ printf '%b\\n' {answer!r}; }}
sdk_verify_download thing {f} https://x/thing.tar.gz 1 {d}
echo kept=$([ -f {f} ] && echo yes || echo no)
cat {d}/.bb-verified
"""
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    return p.returncode, p.stdout + p.stderr, os.path.exists(f)


class Verify(unittest.TestCase):
    def test_a_match_is_kept_and_recorded(self):
        h = hashlib.sha256(b"payload").hexdigest()
        rc, out, kept = run(f"sha256\t{h}\tGitHub's digest")
        self.assertEqual(rc, 0, out)
        self.assertTrue(kept)
        self.assertIn("verified: sha256 matches GitHub's digest", out)
        self.assertIn(f"sha256\t{h}\tGitHub's digest", out)

    def test_a_mismatch_is_removed_and_stops(self):
        rc, out, kept = run("sha256\t" + "0" * 64 + "\tthe publisher's list")
        self.assertNotEqual(rc, 0)
        self.assertFalse(kept, "the bad file is not left to be unpacked")
        self.assertIn("is not what the publisher's list says it is", out)
        self.assertIn("expected " + "0" * 64, out)
        self.assertIn("nothing was installed", out)

    def test_none_says_why_and_goes_on(self):
        rc, out, kept = run("none\t\tits publisher states no checksum")
        self.assertEqual(rc, 0, out)
        self.assertIn("not verified: its publisher states no checksum", out)


if __name__ == "__main__":
    unittest.main()
