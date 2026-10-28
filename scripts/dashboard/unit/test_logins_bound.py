"""A browser's sign-in is bound to the browser it was made in (R158 step
8): a cookie presented from another is refused, a row ended from Profile
refuses its cookie, the rows list what Profile shows, and a row from before
binding is bound to the first browser seen."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import logins  # noqa: E402

CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"


class Bound(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        logins.configure(state=self.tmp)

    def test_another_browser_is_refused_and_an_ended_row_too(self):
        lid = logins.mint("u_12345678", "", CHROME, "10.0.0.5")
        self.assertTrue(logins.seen("u_12345678", lid, CHROME, "10.0.0.5"))
        self.assertFalse(logins.seen("u_12345678", lid, PHONE, "10.0.0.9"), "a cookie copied to another browser")
        self.assertTrue(logins.seen("u_12345678", lid, CHROME), "the browser it was made in, still")
        rows = logins.rows("u_12345678", lid)
        self.assertEqual((rows[0]["agent"], rows[0]["ip"], rows[0]["mine"]), ("Chrome on Windows", "10.0.0.5", True))
        logins.drop("u_12345678", lid)
        self.assertFalse(logins.seen("u_12345678", lid, CHROME), "ended from Profile: its cookie is nobody's")
        self.assertFalse(logins.seen("u_12345678", "nosuchrow", CHROME))

    def test_a_row_from_before_binding_binds_to_the_first_browser(self):
        lid = logins.mint("u_12345678")
        with logins._lock:
            d = logins._load()
            d["u_12345678"][lid].pop("ua", None)
            logins._save(d)
        self.assertTrue(logins.seen("u_12345678", lid, PHONE))
        self.assertFalse(logins.seen("u_12345678", lid, CHROME))
        self.assertEqual(logins.rows("u_12345678")[0]["agent"], "Safari on iPhone")

    def test_browser_words(self):
        self.assertEqual(logins.browser_words("curl/8.5.0"), "curl")
        self.assertEqual(logins.browser_words(""), "a browser")
        self.assertEqual(logins.browser_words("Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"), "Firefox on Linux")


if __name__ == "__main__":
    unittest.main()
