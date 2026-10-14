"""What a push is read for before it goes (pushscan, R219): the lines that
look like a secret or something private, keyed so that approving one okays
that exact line in that file and nothing else."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pushscan  # noqa: E402


def write_json(path, d):
    import json
    with open(path, "w") as f:
        json.dump(d, f)


DIFF = """diff --git a/config.py b/config.py
--- a/config.py
+++ b/config.py
@@ -1,2 +1,6 @@
 import os
+GITHUB_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
+DB = "postgres://app:s3cretpass@db.internal:5432/app"
+ADMIN_EMAIL = "sean@example.com"
+password = os.environ["PASSWORD"]
+SECRET_KEY = "${SECRET_KEY}"
@@ -10,1 +14,3 @@
 x = 1
+HOME = "192.168.1.16"
+version = "1.2.3.4"
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1,0 +1,2 @@
+Write to ops@acme-widgets.io for access.
+token = "changeme"
"""


class Classify(unittest.TestCase):
    def test_secrets_and_private_things_are_named(self):
        self.assertEqual(pushscan.classify('GITHUB_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"'), "a GitHub token")
        self.assertEqual(pushscan.classify("-----BEGIN OPENSSH PRIVATE KEY-----"), "a private key")
        self.assertEqual(pushscan.classify("url: postgres://app:s3cretpass@db:5432/app"), "a password in an address")
        self.assertEqual(pushscan.classify("Authorization: Bearer abcdef0123456789abcdef"), "an Authorization header")
        self.assertEqual(pushscan.classify("api_key = 'q7Gh2kLp9sTz4wXv'"), "a password or secret")
        self.assertEqual(pushscan.classify("contact sean@acme-widgets.io"), "an email address")
        self.assertEqual(pushscan.classify("host = 192.168.1.16"), "an IP address")
        self.assertEqual(pushscan.classify("AWS_KEY=AKIAIOSFODNN7EXAMPLE"), "an AWS key")
        self.assertEqual(pushscan.classify("key: sk-ant-api03-abcdefghijklmnopqrstuvwxyz"), "an Anthropic key")

    def test_placeholders_and_documentation_addresses_are_not(self):
        for line in ('password = "${PASSWORD}"', "token = process.env.TOKEN", "secret: <your secret>",
                     'api_key = "changeme"', 'password = ""', "password = os.environ['PW']",
                     "token: example-token", "secret = mysecret", 'PASSWORD: "********"',
                     "contact: someone@example.com", "noreply@github.com", "bot@users.noreply.github.com",
                     "listen 127.0.0.1:8080", "bind 0.0.0.0", "doc 192.0.2.1", "version 1.2.3.4",
                     "release v2.0.1.4", "x = 1", ""):
            self.assertEqual(pushscan.classify(line), "", line)

    def test_a_long_line_is_skipped(self):
        self.assertEqual(pushscan.classify("ghp_" + "a" * 5000), "")


class Scan(unittest.TestCase):
    def test_the_added_lines_of_a_diff_with_their_file_and_line(self):
        got = pushscan.scan(DIFF)
        self.assertEqual([(f["path"], f["line"], f["kind"]) for f in got],
                         [("config.py", 2, "a GitHub token"), ("config.py", 3, "a password in an address"),
                          ("config.py", 15, "an IP address"), ("README.md", 1, "an email address")])
        self.assertEqual(got[0]["text"], 'GITHUB_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"')
        self.assertEqual(got[0]["key"], pushscan.key_of("config.py", got[0]["text"]))

    def test_the_key_is_the_file_and_the_text(self):
        a = pushscan.key_of("a.py", "token = 'x'")
        self.assertEqual(a, pushscan.key_of("a.py", "  token = 'x'  "), "whitespace around it is not a change")
        self.assertNotEqual(a, pushscan.key_of("b.py", "token = 'x'"), "another file is another finding")
        self.assertNotEqual(a, pushscan.key_of("a.py", "token = 'y'"), "a changed line is another finding")

    def test_the_block_and_the_summary(self):
        got = pushscan.scan(DIFF)
        text = pushscan.block(got)
        self.assertIn("config.py:2  (a GitHub token)\n    GITHUB_TOKEN", text)
        self.assertIn("4 lines look sensitive", pushscan.summary(got))
        self.assertIn("a GitHub token", pushscan.summary(got))
        self.assertIn("1 line looks sensitive", pushscan.summary(got[:1]))
        self.assertIn("...and 1 more", pushscan.block(got, limit=3))


class Okayed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        pushscan.configure(state=self.tmp, write_json=write_json)

    def test_approved_lines_pass_until_they_change(self):
        got = pushscan.scan(DIFF)
        self.assertEqual(len(pushscan.fresh("alpha", got)), 4)
        pushscan.okay("alpha", got[:2], "ada")
        left = pushscan.fresh("alpha", got)
        self.assertEqual([f["line"] for f in left], [15, 1])
        self.assertEqual(len(pushscan.fresh("beta", got)), 4, "another project's list is its own")
        changed = pushscan.scan(DIFF.replace("ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD", "ghp_zyxwvutsrqponmlkjihgfedcba9876543210DCBA"))
        self.assertEqual([f["line"] for f in pushscan.fresh("alpha", changed)], [2, 15, 1], "the changed token is asked about again")
        rec = pushscan._load()["alpha"][got[0]["key"]]
        self.assertEqual((rec["by"], rec["path"], rec["kind"]), ("ada", "config.py", "a GitHub token"))

    def test_okaying_nothing_writes_nothing(self):
        pushscan.okay("alpha", [], "ada")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "pushok.json")))


if __name__ == "__main__":
    unittest.main()
