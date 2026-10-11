"""Published ports bound to 127.0.0.1 by default on a hosting node (R190):
the daemon.json the agent writes, and the row's address for a port that is
on the node alone."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402
from agentpkg import load  # noqa: E402


class DaemonJson(unittest.TestCase):
    def setUp(self):
        self.m = load()

    def test_the_ip_is_set_beside_what_is_there_and_taken_off_again(self):
        f = self.m.base.daemon_json_with_ip
        self.assertEqual(f("", True), '{\n  "ip": "127.0.0.1"\n}\n')
        kept = f('{"labels": ["builderbot.sandbox=1"], "log-driver": "json-file"}', True)
        self.assertIn('"labels"', kept)
        self.assertIn('"ip": "127.0.0.1"', kept)
        self.assertIsNone(f(kept, True), "already so: nothing to write, no docker restart")
        off = f(kept, False)
        self.assertNotIn('"ip"', off)
        self.assertIn('"labels"', off)
        self.assertIsNone(f("", False), "never set: nothing to take off")
        self.assertIsNone(f("not json {", True), "a file that is not JSON is left alone")


class RowAddress(unittest.TestCase):
    def test_a_loopback_bound_port_is_published_and_known_as_local(self):
        ports = ["127.0.0.1:8380->80/tcp", "0.0.0.0:8381->8080/tcp", "9000->9000/tcp"]
        self.assertEqual(devapp._published(ports), [8380, 8381, 9000])
        self.assertEqual(devapp._published(ports, local=True), [8380])
        self.assertEqual(devapp._published([{"published": 80, "proto": "tcp", "host_ip": "127.0.0.1"}], local=True), [80])


if __name__ == "__main__":
    unittest.main()
