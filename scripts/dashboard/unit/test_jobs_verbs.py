"""bb jobs names each job by what it did: a line told to a Claude session
says which session and what it said, where it read as `exec` with an empty
command and a failed one could not be explained (B775)."""
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "..", "lib")
SCRIPT = os.path.join(LIB, "jobs-verbs.py")
JOBS = {"jobs": [{"id": "j_1a2b3c4d", "type": "tell", "state": "failed", "node": "n_1", "queued": 1, "started": 1,
                  "ended": 4, "error": "exit 3", "project": "",
                  "spec": {"session": "u_1~claude-alpha", "text": "BuilderBot is back after an update.\nPick up"}}],
        "nodes": {"n_1": "box"}}


class Answer(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 (the base class's name)
        del format, args

    def do_GET(self):  # noqa: N802 (the base class's name)
        b = json.dumps(JOBS).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


class JobsList(unittest.TestCase):
    def test_a_tell_names_its_session_and_its_words(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Answer)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        env = {k: v for k, v in os.environ.items() if k != "BB_CONTROLLER_PIN"}
        env.update(BB_CONTROLLER=f"http://127.0.0.1:{port}", BB_JOBS_AUTH="Bearer x", PYTHONPATH=LIB,
                   BB_CONTROLLER_WAIT="0", BB_PROJECT="")
        out = subprocess.run([sys.executable, SCRIPT, "5"], env=env, capture_output=True, text=True, check=False).stdout
        self.assertIn('tell u_1~claude-alpha: "BuilderBot is back after an update. Pick up"', out)
        self.assertNotIn("exec", out)


if __name__ == "__main__":
    unittest.main()
