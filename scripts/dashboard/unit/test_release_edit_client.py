"""bb version release --edit's client (lib/release-edit.py, report 60): it
runs where it is typed, so notes in the session's own scratch directory and
notes on stdin both reach the controller, and an attached file is named by
its path inside the project. Against a stand-in controller on a local port."""
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
GOT = []


class Controller(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        GOT.append((self.path, json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))))
        data = json.dumps({"edited": {}, "said": "edited on Gitea: the notes replaced"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Client(unittest.TestCase):
    def setUp(self):
        GOT.clear()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Controller)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = os.path.join(self.tmp, "ws")
        os.makedirs(os.path.join(self.ws, "app", "docs"))
        open(os.path.join(self.ws, "app", "docs", "shot.png"), "wb").write(b"png")
        self.scratch = os.path.join(self.tmp, "scratchpad")
        os.makedirs(self.scratch)

    def run_edit(self, *words, stdin=""):
        env = {**os.environ, "BB_CONTROLLER": f"http://127.0.0.1:{self.srv.server_address[1]}",
               "BB_WORKSPACE": self.ws, "BB_VERSION_AUTH": "Bearer t", "PYTHONPATH": LIB}
        return subprocess.run([sys.executable, os.path.join(LIB, "release-edit.py"), "app", "release", "--edit", *words],
                              input=stdin, capture_output=True, text=True, timeout=30, env=env,
                              cwd=os.path.join(self.ws, "app"))

    def test_notes_from_the_sessions_own_scratch_and_a_file_in_the_project(self):
        notes = os.path.join(self.scratch, "notes.md")
        open(notes, "w").write("## 0.5.4\n\n![The keyboard](asset:shot.png)\n")
        r = self.run_edit("--why", "screenshots", "--notes", notes, "--attach", "docs/shot.png")
        self.assertEqual(r.returncode, 0, r.stderr)
        path, body = GOT[0]
        self.assertEqual(path, "/api/version")
        self.assertEqual((body["action"], body["project"], body["attach"]), ("release-edit", "app", ["docs/shot.png"]))
        self.assertIn("asset:shot.png", body["notes"])
        self.assertIn("the notes replaced", r.stdout)

    def test_notes_on_stdin(self):
        r = self.run_edit("--why", "notes", "--notes", "-", stdin="## 0.5.4\n\nFrom stdin.\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(GOT[0][1]["notes"], "## 0.5.4\n\nFrom stdin.\n")

    def test_a_file_outside_the_project_is_refused_here(self):
        r = self.run_edit("--why", "x", "--attach", os.path.join(self.scratch, "notes.md"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("a file in app", r.stderr)
        self.assertEqual(GOT, [])


if __name__ == "__main__":
    unittest.main()
