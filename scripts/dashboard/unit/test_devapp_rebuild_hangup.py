"""bb devapp rebuild when the controller hangs up on its POST before
answering (B803, report #113): nothing was queued, and the verb stopped at
'Remote end closed connection without response' with the container on its
old commit. It now looks whether the build started and asks once more when
it did not; one that did start is watched rather than asked for twice."""
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
    """The controller: the first rebuild is hung up on; `started` says
    whether that one queued its build anyway."""
    started = False
    rebuilds = 0
    built = "old"

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
        b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        if b.get("action") == "state":
            self._send({"state": {"name": "site", "built_rev": Fake.built, "running": True, "job": {}}})
            return
        Fake.rebuilds += 1
        if Fake.rebuilds == 1:
            if Fake.started:
                Fake.built = "new"
            self.close_connection = True
            return
        Fake.built = "new"
        self._send({"ok": True, "job": "j_1", "started": True})

    def do_GET(self):  # noqa: N802 (the base class's name)
        self._send({"id": "j_1", "state": "succeeded"})


class RebuildAfterAHangUp(unittest.TestCase):
    def setUp(self):
        Fake.rebuilds, Fake.built = 0, "old"
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def run_rebuild(self):
        env = dict(os.environ, BB_CONTROLLER=f"http://127.0.0.1:{self.srv.server_address[1]}",
                   BB_DEV_PROJECT="web", BB_DEV_AUTH="Bearer x", BB_DEV_CONTAINER="site",
                   BB_CONTROLLER_WAIT="0", PYTHONPATH=os.path.join(HERE, "..", "..", "lib"))
        return subprocess.run([sys.executable, VERBS, "rebuild"], env=env, capture_output=True,
                              text=True, timeout=90, check=False)

    def test_nothing_queued_is_asked_for_again(self):
        Fake.started = False
        r = self.run_rebuild()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Fake.rebuilds, 2)
        self.assertIn("asking again", r.stderr)
        self.assertIn("rebuilt", r.stdout)

    def test_a_build_that_started_is_not_asked_for_twice(self):
        Fake.started = True
        r = self.run_rebuild()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Fake.rebuilds, 1)
        self.assertNotIn("asking again", r.stderr)
        self.assertIn("rebuilt", r.stdout)


if __name__ == "__main__":
    unittest.main()
