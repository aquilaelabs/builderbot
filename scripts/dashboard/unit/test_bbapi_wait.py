"""bb waits out a restarting controller (R251): a refused connection is asked
again with backoff for up to BB_CONTROLLER_WAIT seconds, since the request
never reached a server; the session's gate is told at once; a hook, at 0,
is answered at once; and a POST the server may have read is never sent
twice, where a GET it hung up on is asked again."""
import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "lib"))
import bbapi  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Ok(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 (the base class's name)
        del format, args

    def do_GET(self):  # noqa: N802 (the base class's name)
        b = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


class Wait(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.home = tempfile.mkdtemp()
        self.env = dict(os.environ)
        os.environ.update(BB_CONTROLLER=f"http://127.0.0.1:{self.port}", HOME=self.home,
                          BB_PROJECT="alpha", BB_ACCOUNT_UID="u_1")
        os.environ.pop("XDG_CACHE_HOME", None)
        os.environ.pop("BB_CONTROLLER_PIN", None)
        self.steps = bbapi.WAIT_STEPS
        bbapi.WAIT_STEPS = (0.3, 0.3, 0.3, 0.3, 0.3, 0.3)
        self.srv = None

    def tearDown(self):
        bbapi.WAIT_STEPS = self.steps
        os.environ.clear()
        os.environ.update(self.env)
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()

    def gate(self):
        with open(os.path.join(self.home, ".cache", "builderbot", "u", "u_1", "project", "alpha", "gate")) as f:
            return json.load(f)

    def test_a_restart_is_waited_out(self):
        os.environ["BB_CONTROLLER_WAIT"] = "5"

        def up_later():
            time.sleep(0.8)
            self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), Ok)
            self.srv.serve_forever()
        threading.Thread(target=up_later, daemon=True).start()
        st, got = bbapi.request("/api/status")
        self.assertEqual((st, got), (200, {"ok": True}))
        self.assertFalse(self.gate()["ok"], "the gate was told the moment nothing answered")

    def test_a_hook_is_answered_at_once(self):
        os.environ["BB_CONTROLLER_WAIT"] = "0"
        t = time.time()
        st, got = bbapi.request("/api/status")
        self.assertIsNone(st)
        self.assertLess(time.time() - t, 0.25)
        self.assertIn("restarting after an update", got["error"])
        self.assertIn("write where you are", got["error"])
        self.assertFalse(self.gate()["ok"])

    def test_a_post_the_server_hung_up_on_is_not_sent_twice(self):
        os.environ["BB_CONTROLLER_WAIT"] = "5"
        seen = []
        lst = socket.socket()
        lst.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        lst.bind(("127.0.0.1", self.port))
        lst.listen(8)

        def hang_up():
            while True:
                try:
                    c, _ = lst.accept()
                except OSError:
                    return
                seen.append(c.recv(65536)[:4])
                c.close()
        threading.Thread(target=hang_up, daemon=True).start()
        st, _got = bbapi.request("/api/x", {"a": 1})
        self.assertIsNone(st)
        time.sleep(0.2)
        self.assertEqual(len(seen), 1, "a POST is sent once")
        bbapi.request("/api/x")
        time.sleep(0.2)
        self.assertGreater(len(seen), 2, "a GET it hung up on is asked again")
        lst.close()


if __name__ == "__main__":
    unittest.main()
