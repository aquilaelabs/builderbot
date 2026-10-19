"""bb devapp remove (B755, report #111): the controller answers a remove by
queueing the down as a job, and the verb follows that job to its end. A
down that failed (the compose file gone from the tree: "empty compose
file") left the container running while the verb printed "removed"."""
import http.server
import json
import os
import subprocess
import sys
import threading
import unittest

HERE = os.path.dirname(__file__)
VERBS = os.path.join(HERE, "..", "..", "lib", "devapp-verbs.py")


class Fake(http.server.BaseHTTPRequestHandler):
    """The controller: a remove queues j_1, and j_1 ends the way the test says."""
    outcome = "failed"
    polls = 0
    ask = False               # held for a person, whose Allow queues the job

    def log_message(self, format, *args):  # noqa: A002 (the base class's name)
        del format, args

    def _send(self, d):
        b = json.dumps(d).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):  # noqa: N802 (the base class's name)
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.startswith("/api/phone"):
            self._send({"ok": True, "state": "done", "out": "j_1", "code": 0, "why": ""})
        elif Fake.ask:
            self._send({"ok": True, "id": 7, "to": "the operator"})
        else:
            self._send({"ok": True, "job": "j_1"})

    def do_GET(self):  # noqa: N802 (the base class's name)
        Fake.polls += 1
        if Fake.polls < 2:
            self._send({"id": "j_1", "state": "running"})
        elif Fake.outcome == "failed":
            self._send({"id": "j_1", "state": "failed", "error": "stopping it failed: empty compose file"})
        else:
            self._send({"id": "j_1", "state": "succeeded"})


class RemoveFollowsItsJob(unittest.TestCase):
    def setUp(self):
        Fake.polls = 0
        Fake.ask = False
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def run_remove(self):
        env = dict(os.environ, BB_CONTROLLER=f"http://127.0.0.1:{self.srv.server_address[1]}",
                   BB_DEV_PROJECT="web", BB_DEV_AUTH="Bearer x", BB_DEV_VERB="remove",
                   BB_DEV_CONTAINER="site", PYTHONPATH=os.path.join(HERE, "..", "..", "lib"))
        return subprocess.run([sys.executable, VERBS, "edit"], env=env, capture_output=True,
                              text=True, timeout=60, check=False)

    def test_a_failed_down_is_said_as_a_failure(self):
        Fake.outcome = "failed"
        r = self.run_remove()
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("removed;", r.stdout)
        self.assertIn("not removed", r.stderr)
        self.assertIn("empty compose file", r.stderr)

    def test_a_down_that_landed_says_removed(self):
        Fake.outcome = "succeeded"
        r = self.run_remove()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("removed; its env and data stay", r.stdout)
        self.assertGreaterEqual(Fake.polls, 2)

    def test_an_allowed_remove_follows_its_job_too(self):
        # B15: after Allow, the job the approval queued is followed as well,
        # so a down that failed is not reported as removed.
        Fake.ask, Fake.outcome = True, "failed"
        r = self.run_remove()
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("allowed, and removed", r.stdout)
        self.assertIn("empty compose file", r.stderr)
        Fake.polls, Fake.outcome = 0, "succeeded"
        r = self.run_remove()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("allowed, and removed; its env and data stay", r.stdout)


if __name__ == "__main__":
    unittest.main()
