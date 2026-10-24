"""A session sees a release's signing and asks for it again (R134): bb sign
status prints whether the release APK can be signed and how the newest went,
in the Signing view's words; bb sign release asks the project's owner, under
Sign a build, and Allow starts the look the Signing view's press starts; bb
version release is refused before the tag when the APK could not be signed,
unless told --without-apk. The clients against a stand-in controller on a
local port; the ask against phone.py itself."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "..", "lib")
sys.path.insert(0, os.path.join(HERE, ".."))
import phone  # noqa: E402

GOT = []
ANSWER = {}


class Controller(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        GOT.append((self.path, body))
        status, got = ANSWER.get(body.get("action"), (200, {}))
        data = json.dumps(got).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def status():
    """Stamped when asked: a whole tier's run is minutes, and the ages printed
    are read against the clock then."""
    now = int(time.time())
    return {"release": {
        "wanted": True, "node": "bb-sandbox", "why": "", "looking": False,
        "keys": [{"package": "dev.example.app", "key": "release", "sha256": "DE:66:E7"}],
        "signed": [{"tag": "v0.7.0", "at": now - 120, "files": ["app-0.7.0.apk"], "key": "release",
                    "cert": "DE:66:E7", "url": "https://example.test/releases/v0.7.0"}],
        "failed": [{"tag": "v0.6.9", "at": now - 7200, "why": "no sideload key"}]}, "attention": []}


class Clients(unittest.TestCase):
    def setUp(self):
        GOT.clear()
        ANSWER.clear()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Controller)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def env(self):
        return {**os.environ, "BB_CONTROLLER": f"http://127.0.0.1:{self.srv.server_address[1]}",
                "BB_SIGN_AUTH": "Bearer t", "BB_SIGN_PROJECT": "app", "BB_VERSION_AUTH": "Bearer t",
                "PYTHONPATH": LIB}

    def sign(self, *argv):
        return subprocess.run([sys.executable, os.path.join(LIB, "sign-verbs.py"), *argv],
                              capture_output=True, text=True, timeout=30, env=self.env())

    def test_status_says_the_key_the_node_and_each_result(self):
        ANSWER["release"] = (200, status())
        r = self.sign("--status", "", "")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(GOT[0][1], {"action": "release", "project": "app"})
        self.assertIn("dev.example.app: releases sign with release  DE:66:E7", r.stdout)
        self.assertIn("signed on bb-sandbox", r.stdout)
        self.assertIn("ready: a release's APK can be signed", r.stdout)
        self.assertIn("v0.7.0: signed 2 min ago, app-0.7.0.apk with release (DE:66:E7)", r.stdout)
        self.assertIn("v0.6.9: FAILED 2 h ago: no sideload key", r.stdout)
        self.assertIn("bb sign release", r.stdout, "a failure says how to ask again")
        self.assertLess(r.stdout.index("v0.7.0"), r.stdout.index("v0.6.9"), "newest first")

    def test_status_of_one_tag_and_what_would_stop_one(self):
        ANSWER["release"] = (200, {"release": status()["release"] | {"why": "the project has no sideload key"}})
        r = self.sign("--status", "", "", "v0.7.0")
        self.assertIn("NOT READY: the project has no sideload key", r.stdout)
        self.assertIn("v0.7.0: signed", r.stdout)
        self.assertNotIn("v0.6.9", r.stdout)
        r = self.sign("--status", "", "", "v9.9.9")
        self.assertIn("nothing yet for v9.9.9", r.stdout)

    def test_a_project_that_hands_over_no_apk_says_so(self):
        ANSWER["release"] = (200, {"release": {"wanted": False}})
        self.assertIn("signs none of its releases", self.sign("--status", "", "").stdout)

    def test_release_on_auto_starts_the_look(self):
        ANSWER["release-sign"] = (200, {"ok": True, "started": True, "said": "looking"})
        r = self.sign("--release", "", "the key was added")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(GOT[0][1], {"action": "release-sign", "project": "app", "why": "the key was added"})
        self.assertIn("bb sign status says how it went", r.stderr)

    def test_release_refused_says_why(self):
        ANSWER["release-sign"] = (403, {"error": "app's settings say Claude does not sign its builds"})
        r = self.sign("--release", "", "again")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not sign its builds", r.stderr)

    def version_release(self, *words):
        with tempfile.TemporaryDirectory() as state:
            return subprocess.run([sys.executable, os.path.join(LIB, "version-verbs.py"),
                                   os.path.join(HERE, "..", "version.py"), "app", "release", *words],
                                  capture_output=True, text=True, timeout=30,
                                  env=self.env() | {"DASHBOARD_STATE": state, "BB_WORKSPACE": state})

    def test_version_release_carries_without_apk(self):
        ANSWER["release"] = (409, {"error": "v0.7.1's Android APK could not be signed: no sideload key"})
        r = self.version_release("--why", "the patch")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("could not be signed: no sideload key", r.stderr)
        self.assertIs(GOT[-1][1]["unsigned"], False)
        ANSWER["release"] = (200, {"released": {"tag": "v0.7.1", "sha": "abc1234"}})
        r = self.version_release("--why", "the patch", "--without-apk")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIs(GOT[-1][1]["unsigned"], True)


class Ask(unittest.TestCase):
    def setUp(self):
        self.ran = []
        self.was = phone.release_signer
        phone.release_signer = lambda p: (self.ran.append(p) or ({"ok": True, "said": "looking"}, 200))
        self.addCleanup(setattr, phone, "release_signer", self.was)

    def test_it_waits_on_the_owner_and_allow_starts_the_look(self):
        self.assertIn("say what it is for", phone.ask_release_sign("", "app", "u_00000001", "ada")["error"])
        r = phone.ask_release_sign("the key was added", "app", "u_00000001", "ada", asker_name="bob")
        mine = [x for x in phone.requests_open("u_00000001", False) if x["id"] == r["id"]]
        self.assertEqual((mine[0]["kind"], mine[0]["cmd"]), ("release-sign", ["sign", "release"]))
        self.assertFalse([x for x in phone.requests_open("u_00000009", True) if x["id"] == r["id"]],
                         "the owner's to answer, not an administrator's")
        self.assertTrue(phone.decide(r["id"], True, "u_00000001", name="ada").get("ok"))
        self.assertEqual(self.ran, ["app"])
        o = phone.outcome(r["id"], "app")
        self.assertEqual((o["state"], o["code"], o["out"]), ("done", 0, "looking"))


if __name__ == "__main__":
    unittest.main()
