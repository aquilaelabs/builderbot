"""bb browser (scripts/lib/browser.mjs, R247): Chrome and Firefox with an
unpacked extension loaded, each on its own port and profile, driven from one
verb and ended by its process group. Run against the toolchain store's
Playwright browsers where this node has them, skipped where it does not."""
import glob
import http.server
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest

HERE = os.path.dirname(__file__)
BB = os.path.join(HERE, "..", "..", "bb")
MJS = os.path.join(HERE, "..", "..", "lib", "browser.mjs")


def store_browser(pattern):
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")] + glob.glob("/mnt/SDK/*/playwright")
    for r in [x for x in roots if x]:
        hit = glob.glob(os.path.join(r, pattern))
        if hit:
            return hit[0]
    return ""


CHROME = store_browser("chromium-*/chrome-linux*/chrome")
FIREFOX = store_browser("firefox-*/firefox/firefox")
NODE = shutil.which("node") or ""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 (the base class's name)
        del format, args


@unittest.skipUnless(NODE, "no node here")
class Browser(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        ext = os.path.join(self.tmp, "ext")
        os.makedirs(ext)
        with open(os.path.join(ext, "manifest.json"), "w") as f:
            json.dump({"manifest_version": 3, "name": "bb unit ext", "version": "1.0",
                       "browser_specific_settings": {"gecko": {"id": "bbunit@example.invalid"}},
                       "background": {"service_worker": "sw.js", "scripts": ["sw.js"]},
                       "content_scripts": [{"matches": ["http://127.0.0.1/*"], "js": ["cs.js"]}],
                       "action": {"default_popup": "popup.html"}}, f)
        for name, text in (("cs.js", 'document.documentElement.dataset.bbext = "on";'),
                           ("sw.js", "self.ready = true;"), ("popup.html", "<p id=x>popup</p>")):
            with open(os.path.join(ext, name), "w") as f:
                f.write(text)
        self.ext = ext
        self.env = {**os.environ, "XDG_CACHE_HOME": os.path.join(self.tmp, "cache"),
                    "BB_BROWSER_CHROME": CHROME, "BB_BROWSER_FIREFOX": FIREFOX}
        site = os.path.join(self.tmp, "site")
        os.makedirs(site)
        with open(os.path.join(site, "index.html"), "w") as f:
            f.write("<title>t</title><p>a page</p>")
        handler = lambda *a, **k: Quiet(*a, directory=site, **k)  # noqa: E731
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.url = f"http://127.0.0.1:{self.srv.server_port}/"

    def bb(self, *words, timeout=90):
        r = subprocess.run([NODE, MJS, *words], env=self.env, capture_output=True, text=True,
                           timeout=timeout, check=False)
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    def walk(self, kind):
        code, out, err = self.bb("open", "--ext", self.ext, f"--{kind}", "--url", self.url)
        self.assertEqual(code, 0, err + out)
        bid = re.match(r"browser (b\w+):", out).group(1)
        self.addCleanup(lambda: self.bb("stop", bid))
        self.assertIn("loaded as", out)
        code, out, err = self.bb("eval", bid, 'document.documentElement.dataset.bbext || "none"')
        self.assertEqual((code, out), (0, '"on"'), err)
        shot = os.path.join(self.tmp, f"{kind}.png")
        code, _, err = self.bb("shot", bid, shot)
        self.assertEqual(code, 0, err)
        with open(shot, "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
        code, out, _ = self.bb("list")
        self.assertIn(bid, out)
        return bid

    @unittest.skipUnless(CHROME, "no Playwright Chromium in the store")
    def test_chrome_runs_the_extension_and_opens_its_own_page(self):
        bid = self.walk("chrome")
        code, out, err = self.bb("go", bid, "ext:popup.html")
        self.assertEqual(code, 0, err)
        self.assertIn("chrome-extension://", out)
        self.assertEqual(self.bb("eval", bid, 'document.getElementById("x").textContent')[1], '"popup"')
        code, out, _ = self.bb("stop", bid)
        self.assertEqual(code, 0)
        self.assertIn(f"ended {bid}", out)
        self.assertIn("no browser of yours is open", self.bb("list")[1])

    @unittest.skipUnless(FIREFOX, "no Playwright Firefox in the store")
    def test_firefox_runs_the_extension_and_says_its_own_pages_are_chromes(self):
        bid = self.walk("firefox")
        code, _, err = self.bb("go", bid, "ext:popup.html")
        self.assertNotEqual(code, 0)
        self.assertIn("open it in Chrome", err)

    def test_open_says_what_it_needs(self):
        code, _, err = self.bb("open")
        self.assertNotEqual(code, 0)
        self.assertIn("needs --ext DIR", err)
        code, _, err = self.bb("open", "--ext", self.tmp)
        self.assertIn("holds no manifest.json", err)


if __name__ == "__main__":
    unittest.main()
