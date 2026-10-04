"""forgerelease.py (R123): Release's GitHub release, against a stand-in for
GitHub's API and its upload host on a local port. The notes are the
changelog's section for the version, the assets the released commit's
builds (signed ones when there are any), and a second press makes nothing
twice."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cilogs  # noqa: E402
import forgerelease as fr  # noqa: E402

SEEN = []
MADE = {}


class Forge(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def answer(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        SEEN.append(("GET", self.path, None))
        if self.path.startswith("/repos/o/app/releases/tags/"):
            tag = self.path.rsplit("/", 1)[-1]
            return self.answer(200, MADE[tag]) if tag in MADE else self.answer(404, {"message": "Not Found"})
        return self.answer(404, {"message": "Not Found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        if self.headers.get("Authorization") != "Bearer tok":
            return self.answer(401, {"message": "Bad credentials"})
        if self.path == "/repos/o/app/releases":
            b = json.loads(raw)
            SEEN.append(("POST", self.path, b))
            MADE[b["tag_name"]] = {"id": 7, "html_url": f"https://github.com/o/app/releases/tag/{b['tag_name']}"}
            return self.answer(201, MADE[b["tag_name"]])
        if self.path.startswith("/repos/o/app/releases/7/assets?name="):
            SEEN.append(("UPLOAD", self.path, len(raw)))
            return self.answer(201, {"id": 1})
        return self.answer(404, {"message": "Not Found"})


class Release(unittest.TestCase):
    def setUp(self):
        SEEN.clear(); MADE.clear()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Forge)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "gitcreds").mkdir()
        (self.tmp / "gitcreds" / "app").write_text("https://x:tok@github.com\n")
        app = self.tmp / "ws" / "app"
        (app / "dist").mkdir(parents=True)
        (app / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n\n- not yet\n\n## 0.5.0: 2026-10-04\n\n"
                                          "### Added\n\n- Voice typing (abc1234)\n\n### Fixed\n\n- A crash on rotate\n\n"
                                          "## 0.4.0: 2026-09-01\n\n### Added\n\n- older\n")
        for n in ("app-0.5.0-dev.12-65298e0-release.apk", "app-0.5.0-dev.12-65298e0-release-signed.apk",
                  "app-0.5.0-dev.12-65298e0-debug.apk", "app-0.5.0-dev.11-1111111-release-signed.apk",
                  "app-0.5.0-dev.12-65298e0-dirty.apk"):
            (app / "dist" / n).write_bytes(b"apk")
        cilogs.configure(state=self.tmp, workspace=self.tmp / "ws",
                         push_record_fn={"app": {"repo": "o/app", "host": "github.com"}}.get)

        def wj(path, d):
            Path(path).write_text(json.dumps(d))
        fr.configure(state=self.tmp, workspace=self.tmp / "ws", write_json_fn=wj)
        base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        for k, v in (("API", base), ("UPLOADS", base)):
            self.addCleanup(setattr, fr, k, getattr(fr, k))
            setattr(fr, k, v)

    def test_the_release_carries_the_versions_notes_and_its_signed_builds(self):
        r = fr.publish("app", "v0.5.0", "0.5.0", "65298e0")
        self.assertTrue(r.get("made"), r)
        made = [b for m, p, b in SEEN if m == "POST"][0]
        self.assertEqual((made["tag_name"], made["name"]), ("v0.5.0", "0.5.0"))
        self.assertIn("### Added\n\n- Voice typing", made["body"])
        self.assertIn("- A crash on rotate", made["body"])
        self.assertNotIn("older", made["body"])
        self.assertNotIn("not yet", made["body"])
        self.assertEqual(r["assets"], ["app-0.5.0-dev.12-65298e0-release-signed.apk"])
        self.assertEqual(fr.kept("app")["v0.5.0"]["url"], "https://github.com/o/app/releases/tag/v0.5.0")

    def test_a_second_press_makes_nothing_twice(self):
        fr.publish("app", "v0.5.0", "0.5.0", "65298e0")
        n = len([1 for m, _, _ in SEEN if m == "POST"])
        r = fr.publish("app", "v0.5.0", "0.5.0", "65298e0")
        self.assertFalse(r["made"])
        self.assertEqual(len([1 for m, _, _ in SEEN if m == "POST"]), n)

    def test_no_forge_or_no_token_is_said(self):
        cilogs.configure(state=self.tmp, workspace=self.tmp / "ws", push_record_fn=lambda p: None)
        self.assertIn("not on GitHub", fr.publish("app", "v0.5.0", "0.5.0", "65298e0")["error"])

    def test_a_refused_token_is_said_in_words(self):
        (self.tmp / "gitcreds" / "app").write_text("https://x:wrong@github.com\n")
        self.assertIn("refused the token", fr.publish("app", "v0.5.0", "0.5.0", "65298e0")["error"])
        # ...and kept, so the version row says why there is no release.
        self.assertIn("refused the token", fr.kept("app")["v0.5.0"]["error"])


if __name__ == "__main__":
    unittest.main()
