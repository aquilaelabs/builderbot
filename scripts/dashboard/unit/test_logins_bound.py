"""A browser's sign-in is bound to the browser it was made in (R158 step
8): a cookie presented from another is refused, a row ended from Profile
refuses its cookie, the rows list what Profile shows, and a row from before
binding is bound to the first browser seen."""
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

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


    def test_the_same_browser_on_its_desktop_site_or_a_new_version_stays_signed_in(self):
        # B447: the browser is the binding, never its version or its system.
        lid = logins.mint("u_12345678", "", PHONE, "10.0.0.5")
        mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
        self.assertTrue(logins.seen("u_12345678", lid, mac), "Safari's desktop site")
        self.assertTrue(logins.seen("u_12345678", lid, PHONE.replace("17.0", "18.1")), "Safari updated")
        lid = logins.mint("u_12345678", "", CHROME, "10.0.0.5")
        self.assertTrue(logins.seen("u_12345678", lid, CHROME.replace("Chrome/130.0", "Chrome/131.0")))
        self.assertFalse(logins.seen("u_12345678", lid, PHONE), "another browser, still refused")


class Migration0018(unittest.TestCase):
    def test_a_whole_string_binding_becomes_its_browsers_and_stays_signed_in(self):
        here = os.path.dirname(os.path.abspath(__file__))
        spec = importlib.util.spec_from_file_location("m0018", os.path.join(here, "..", "statemigrations", "0018_signin_by_browser.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        old = hashlib.sha256(PHONE.encode()).hexdigest()[:16]
        Path(t, "logins.json").write_text(json.dumps({"u_12345678": {
            "a": {"ua": old, "agent": "Safari on iPhone", "at": 1, "last": 1},
            "b": {"ua": old, "agent": "a browser", "at": 1, "last": 1},
            "basic": {"at": 1, "last": 1, "kind": "basic"}}}))
        m.run({"state": t})
        m.run({"state": t})
        d = json.loads(Path(t, "logins.json").read_text())["u_12345678"]
        self.assertEqual(d["a"]["ua"], logins.family_digest("Safari"))
        self.assertEqual(d["b"]["ua"], "", "held to nothing, bound again by the first browser seen")
        self.assertNotIn("ua", d["basic"])
        logins.configure(state=t)
        self.assertTrue(logins.seen("u_12345678", "a", PHONE), "signed in through the upgrade")

if __name__ == "__main__":
    unittest.main()
