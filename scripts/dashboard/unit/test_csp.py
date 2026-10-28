"""The page's content security policy (R158 step 4): the header allows the
page's own origin and the inline blocks it ships by their hash, a page
script carries its integrity, and what a browser refuses is kept for the
Doctor."""
import base64
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import csp  # noqa: E402

HERE = os.path.join(os.path.dirname(__file__), "..")


class Header(unittest.TestCase):
    def test_the_inline_blocks_are_allowed_by_hash_and_nothing_else_inline(self):
        html = b'<html><head><style>body{color:red}</style><script src="a.js"></script><script>let x = 1;</script></head></html>'
        h = csp.header(html)
        want_s = "'sha256-" + base64.b64encode(hashlib.sha256(b"let x = 1;").digest()).decode() + "'"
        want_c = "'sha256-" + base64.b64encode(hashlib.sha256(b"body{color:red}").digest()).decode() + "'"
        self.assertIn(f"script-src 'self' {want_s};", h)
        self.assertIn(f"style-src 'self' {want_c};", h)
        self.assertNotIn("unsafe-inline", h)
        self.assertNotIn("unsafe-eval", h)
        self.assertIn("object-src 'none'", h)
        self.assertIn("report-uri /api/csp-report", h)

    def test_the_dashboard_page_itself_hashes_to_its_blocks(self):
        raw = pathlib.Path(HERE, "index.html").read_bytes()
        scripts, styles = csp.hashes(raw)
        self.assertGreaterEqual(len(scripts), 1, "the page's head script and its wiring are inline")
        self.assertGreaterEqual(len(styles), 1, "the page's stylesheet is inline")
        # Nothing in the page runs by an inline handler or sets a style
        # attribute, which the policy would refuse.
        import re
        self.assertEqual(re.findall(rb'\son[a-z]+="', raw), [], "an inline handler would be refused")
        for name in sorted(os.listdir(HERE)):
            if name.endswith(".js") and (name.startswith(("tab-", "nb-", "page-"))):
                src = pathlib.Path(HERE, name).read_text()
                self.assertNotIn(' style="', src, f"{name} writes a style attribute, which the policy refuses: write data-style")

    def test_integrity_is_the_sha384_of_the_file(self):
        self.assertEqual(csp.integrity(b"abc"), "sha384-" + base64.b64encode(hashlib.sha384(b"abc").digest()).decode())


class Reports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        csp.configure(state=self.tmp)

    def test_a_report_is_kept_newest_first_and_capped(self):
        self.assertEqual(csp.reports(), [])
        body = json.dumps({"csp-report": {"blocked-uri": "inline", "violated-directive": "script-src 'self'",
                                          "document-uri": "https://bb/#/home", "line-number": 12}}).encode()
        self.assertTrue(csp.report(body, "ann"))
        self.assertFalse(csp.report(b"not json"))
        r = csp.reports()
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["who"], r[0]["blocked"], r[0]["directive"], r[0]["line"]), ("ann", "inline", "script-src 'self'", 12))
        for i in range(csp.KEEP + 5):
            csp.report(json.dumps({"csp-report": {"blocked-uri": f"x{i}"}}).encode())
        r = csp.reports()
        self.assertEqual(len(r), csp.KEEP)
        self.assertEqual(r[0]["blocked"], f"x{csp.KEEP + 4}")
        csp.clear()
        self.assertEqual(csp.reports(), [])


if __name__ == "__main__":
    unittest.main()
