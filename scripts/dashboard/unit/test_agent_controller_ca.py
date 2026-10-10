"""The agent's connection through a public hostname (R170): with the pin `ca` the
controller is verified by the system's CAs and the hostname, as a browser
would, and nothing is pinned; any other pin is compared as before."""
import http.client
import unittest

import agentpkg  # noqa: E402
agent = agentpkg.load("builderbot_agent_ca")
agent.log = lambda *a, **k: None


class Made:
    """What HTTPSConnection was asked to make, without a network."""
    calls = []

    def __init__(self, host, port, timeout=None, context=None):
        Made.calls.append((host, port, context))
        self.sock = None

    def connect(self):
        pass


class CaMode(unittest.TestCase):
    def setUp(self):
        Made.calls = []
        self.was = http.client.HTTPSConnection
        http.client.HTTPSConnection = Made
        self.addCleanup(setattr, http.client, "HTTPSConnection", self.was)

    def test_the_hostname_is_verified_by_ca_and_nothing_pinned(self):
        c = agent.Controller("https://bb.example.com", "tok", agent.Controller.CA)
        c._conn(5)
        host, port, ctx = Made.calls[0]
        self.assertEqual((host, port), ("bb.example.com", 443))
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, agent.ssl.CERT_REQUIRED)
        self.assertEqual(c.seen_pin, "ca")

    def test_a_pinned_controller_still_skips_the_ca(self):
        c = agent.Controller("https://192.168.1.16:7680", "tok", "sha256:abc")
        with self.assertRaises(AttributeError):      # no socket here: the pin read needs one
            c._conn(5)
        _, _, ctx = Made.calls[0]
        self.assertFalse(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, agent.ssl.CERT_NONE)


class Pieces(unittest.TestCase):
    def test_an_upload_in_pieces_sends_offset_and_total_and_stops_when_whole(self):
        import os
        import tempfile
        c = agent.Controller("https://bb.example.com", "tok", agent.Controller.CA)
        f = tempfile.NamedTemporaryFile(delete=False)
        f.write(b"x" * 10)
        f.close()
        self.addCleanup(os.unlink, f.name)
        sent = []

        def fake(path, src, timeout=600, offset=0, length=None):
            sent.append((path, offset, length))
            done = offset + length
            return 200, {"ok": True, "bytes": done, **({"more": True} if done < 10 else {})}
        c.upload = fake
        code, r = c.upload_pieces("devdata-put?job=j1", f.name, 4)
        self.assertEqual(code, 200)
        self.assertEqual(sent, [("devdata-put?job=j1&offset=0&total=10", 0, 4),
                                ("devdata-put?job=j1&offset=4&total=10", 4, 4),
                                ("devdata-put?job=j1&offset=8&total=10", 8, 2)])
        self.assertEqual(r["bytes"], 10)


if __name__ == "__main__":
    unittest.main()
