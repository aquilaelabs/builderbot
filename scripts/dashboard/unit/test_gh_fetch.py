"""scripts/lib/gh-fetch (B335): a release asset kept only when its download
matches the digest GitHub states for it; a mismatch or a release that states
none leaves the destination as it was. A local server stands in for GitHub."""
import hashlib
import http.server
import json
import os
import subprocess
import tempfile
import threading
import unittest

GHF = os.path.join(os.path.dirname(__file__), "..", "..", "lib", "gh-fetch")


class Fake(http.server.BaseHTTPRequestHandler):
    pages = {}

    def do_GET(self):
        body = self.pages.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class GhFetch(unittest.TestCase):
    def setUp(self):
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
        self.d = tempfile.mkdtemp()

    def release(self, digest, body=b"the tool"):
        Fake.pages = {
            "/repos/o/r/releases/latest": json.dumps({"tag_name": "v9", "assets": [
                {"name": "tool-linux-x86_64", "digest": digest, "browser_download_url": self.base + "/dl/tool"},
                {"name": "tool-linux-arm64", "digest": None, "browser_download_url": self.base + "/dl/other"}]}).encode(),
            "/dl/tool": body}

    def run_it(self, pattern="tool-linux-x86_64"):
        dest = os.path.join(self.d, "tool")
        p = subprocess.run(["bash", GHF, "o/r", "latest", pattern, dest], capture_output=True, text=True, check=False,
                           env=dict(os.environ, GH_FETCH_API=self.base + "/repos", GITHUB_TOKEN=""))
        return p, dest

    def test_a_matching_asset_is_kept_and_its_tag_said(self):
        self.release("sha256:" + hashlib.sha256(b"the tool").hexdigest())
        p, dest = self.run_it("TOOL-linux-x86_64")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), "v9")
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), b"the tool")

    def test_a_mismatch_is_not_kept(self):
        self.release("sha256:" + "0" * 64)
        p, dest = self.run_it()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("is not what GitHub says it is", p.stderr)
        self.assertFalse(os.path.exists(dest))

    def test_no_digest_or_no_single_match_is_refused(self):
        self.release("sha256:" + "0" * 64)
        p, dest = self.run_it("tool-linux-arm64")
        self.assertIn("states no digest", p.stderr)
        p, _ = self.run_it("tool-linux-*")
        self.assertIn("2 assets of v9 match", p.stderr)


if __name__ == "__main__":
    unittest.main()
