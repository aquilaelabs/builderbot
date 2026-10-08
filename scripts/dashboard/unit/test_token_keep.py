"""bb token keep, which the node agent runs to refresh an idle session's
token (R27): kept where bb reads it, and when it cannot be, a failure that
says why rather than an exit 0 over nothing written (B419)."""
import base64
import os
import subprocess
import sys
import tempfile
import unittest

LIB = os.path.join(os.path.dirname(__file__), "..", "..", "lib")
sys.path.insert(0, LIB)
import bbapi  # noqa: E402


def tok(project="alpha"):
    return "bbs_" + base64.urlsafe_b64encode(f"{project}|9999999999|u_12345678|sig".encode()).decode().rstrip("=")


class Keep(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.env = dict(os.environ, HOME=self.home, BB_ACCOUNT_UID="u_12345678")
        self.env.pop("XDG_CACHE_HOME", None)

    def run_keep(self, token):
        return subprocess.run([sys.executable, os.path.join(LIB, "token-verbs.py"), "keep"],
                              env=dict(self.env, BB_TOKEN=token, PYTHONPATH=LIB),
                              capture_output=True, text=True, check=False)

    def test_kept_where_bb_reads_it(self):
        r = self.run_keep(tok())
        self.assertEqual(r.returncode, 0, r.stderr)
        f = os.path.join(self.home, ".cache", "builderbot", "u", "u_12345678", "project", "alpha", "token")
        with open(f) as h:
            self.assertEqual(h.read().strip(), tok())

    def test_a_cache_it_cannot_write_fails_and_says_where(self):
        with open(os.path.join(self.home, ".cache"), "w") as h:
            h.write("a file where the directory should be")
        r = self.run_keep(tok())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not kept under " + self.home, r.stderr)

    def test_a_token_with_no_project_is_refused(self):
        self.assertEqual(bbapi.keep_token("bbs_" + base64.urlsafe_b64encode(b"|1|x").decode()),
                         "the token names no project")


if __name__ == "__main__":
    unittest.main()
