"""The node's half of a held push (scripts/lib/relay.py, R219): a relayed
`bb git push` the controller holds waits on the ask the way bb root run
does, and when the person approves, what the controller's push answered is
printed here and its apply (an upstream set by -u) lands in this tree, as
the session. Proven against a stand-in controller, since the harness drives
the controller's endpoint directly and never this script."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LIB = os.path.join(os.path.dirname(__file__), "..", "..", "lib")


class Controller(BaseHTTPRequestHandler):
    """Holds the first push (ask #5), says running once, then done with the
    push's output and an upstream to set; denies ask #6."""
    polls = 0
    seen = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        Controller.seen.append((self.path, body))
        if self.path == "/api/v1/bb":
            ask = 6 if "deny-me" in body.get("argv", []) else 5
            out = {"held": ask, "code": 1, "out": "", "err": "[builderbot] held: 1 line looks sensitive\n"}
        elif self.path == "/api/phone" and body.get("action") == "outcome":
            if body.get("id") == 6:
                out = {"ok": True, "state": "denied", "out": "", "code": None, "why": "x"}
            else:
                Controller.polls += 1
                out = ({"ok": True, "state": "running", "out": "", "code": None, "why": "x"} if Controller.polls == 1
                       else {"ok": True, "state": "done", "out": "pushed to origin\n", "code": 0, "why": "x",
                             "apply": {"upstream": [["topic", "origin", "refs/heads/topic"]]}})
        else:
            out = {"error": "unexpected"}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):     # noqa: A002 (the base class's name)
        pass


class RelayHeld(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "alpha")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", "-b", "topic", self.repo], check=True)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Controller)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        Controller.polls, Controller.seen = 0, []
        self.env = {**os.environ, "BB_CONTROLLER": f"http://127.0.0.1:{self.srv.server_port}",
                    "BB_AUTH_HEADER": "Bearer x", "BB_RELAY_PROJECT": "alpha", "HOME": self.tmp}
        self.env.pop("BB_CONTROLLER_PIN", None)

    def relay(self, *words):
        return subprocess.run([sys.executable, os.path.join(LIB, "relay.py"), "", *words], cwd=self.repo,
                              env=self.env, capture_output=True, text=True, timeout=60, check=False)

    def test_a_held_push_waits_and_takes_the_approved_pushs_answer_and_apply(self):
        r = self.relay("git", "push", "-u", "origin", "topic")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("held: 1 line looks sensitive", r.stderr, "the hold is said at once")
        self.assertEqual(r.stdout, "pushed to origin\n", "the approved push's output, once the answer came")
        self.assertGreaterEqual(Controller.polls, 2, "waited on the outcome")
        up = subprocess.run(["git", "config", "branch.topic.remote"], cwd=self.repo, capture_output=True, text=True, check=False)
        self.assertEqual(up.stdout.strip(), "origin", "the apply landed here, as the session")

    def test_a_denied_push_ends_the_verb_with_its_sentence(self):
        r = self.relay("git", "push", "origin", "deny-me")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("the push was denied", r.stderr)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
