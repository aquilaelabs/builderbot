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
        import json
        f = self.m.base.daemon_json_with_ip
        both = json.loads(f("", True))
        self.assertEqual(both, {"ip": "127.0.0.1", "default-network-opts": {"bridge": {
            "com.docker.network.bridge.host_binding_ipv4": "127.0.0.1"}},
            "log-opts": {"max-size": "20m", "max-file": "3"}},
            "the default bridge's and every network compose makes (a hosting node, 11 Oct), and bounded container logs")
        kept = f('{"labels": ["builderbot.sandbox=1"], "log-driver": "json-file"}', True)
        self.assertIn('"labels"', kept)
        self.assertIn('"ip": "127.0.0.1"', kept)
        self.assertIsNone(f(kept, True), "already so: nothing to write, no docker restart")
        # A node R190's first agent wrote, with `ip` alone, gets the other.
        self.assertIn("host_binding_ipv4", f('{"ip": "127.0.0.1"}', True))
        off = f(kept, False)
        self.assertNotIn('"ip"', off)
        self.assertNotIn("default-network-opts", off)
        self.assertIn('"labels"', off)
        mixed = f('{"default-network-opts": {"bridge": {"com.docker.network.bridge.mtu": "1400"}}}', True)
        self.assertIn("mtu", mixed, "another bridge option is kept")
        self.assertIn("mtu", f(mixed, False))
        self.assertEqual(json.loads(f("", False)), {"log-opts": {"max-size": "20m", "max-file": "3"}},
                         "never set: nothing to take off, and the container logs bounded")
        self.assertIsNone(f(f("", False), False), "and then nothing more to write")
        mine = '{"log-opts": {"max-size": "100m"}}'
        self.assertEqual(json.loads(f(mine, True))["log-opts"], {"max-size": "100m"}, "a node's own log options are kept")
        self.assertNotIn("log-opts", json.loads(f('{"log-driver": "journald"}', True)), "and its own driver")
        self.assertIsNone(f("not json {", True), "a file that is not JSON is left alone")


class RowAddress(unittest.TestCase):
    def test_a_loopback_bound_port_is_published_and_known_as_local(self):
        ports = ["127.0.0.1:8380->80/tcp", "0.0.0.0:8381->8080/tcp", "9000->9000/tcp"]
        self.assertEqual(devapp._published(ports), [8380, 8381, 9000])
        self.assertEqual(devapp._published(ports, local=True), [8380])
        self.assertEqual(devapp._published([{"published": 80, "proto": "tcp", "host_ip": "127.0.0.1"}], local=True), [80])

    def test_the_listing_keeps_a_loopback_address_and_names_the_open_ones(self):
        raw = "0.0.0.0:8380->80/tcp, [::]:8380->80/tcp, 127.0.0.1:8381->8080/tcp"
        self.assertEqual(devapp._ports(raw), ["8380->80/tcp", "127.0.0.1:8381->8080/tcp"],
                         "one entry per port, the loopback one saying so")
        self.assertEqual(devapp._published(devapp._ports(raw), local=True), [8381])


if __name__ == "__main__":
    unittest.main()
