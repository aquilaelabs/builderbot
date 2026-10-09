"""Static routes on a node (the operator, 7 Oct): every network backend the
agent drives renders a node's routes beside its address, in either mode,
and dhcpcd, which has no setting for one, refuses them by name rather than
dropping them. What each file says, read back as text."""
import os
import tempfile
import unittest
import agentpkg  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
agent = agentpkg.load("builderbot_agent_routes")
agent.log = lambda *a, **k: None

R = [{"to": "10.20.0.0/24", "via": "192.168.1.1"}, {"to": "172.16.5.0/24", "via": "192.168.1.2"}]


class Routes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = {k: getattr(agent, k) for k in ("INTERFACES_FILE", "SYSCONFIG_NET_DIR", "NETWORKD_DIR")}
        agent.INTERFACES_FILE = os.path.join(self.tmp, "interfaces")
        agent.SYSCONFIG_NET_DIR = os.path.join(self.tmp, "sysconfig")
        agent.NETWORKD_DIR = os.path.join(self.tmp, "networkd")

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(agent, k, v)

    def test_netplan_in_both_modes(self):
        static = agent.NetplanNet.render("eth0", "static", "192.168.1.10/24", "192.168.1.1", ["1.1.1.1"], R)
        self.assertIn("      routes:\n        - to: default\n          via: 192.168.1.1\n"
                      "        - to: 10.20.0.0/24\n          via: 192.168.1.1\n", static)
        dhcp = agent.NetplanNet.render("eth0", "dhcp", "", "", [], R[:1])
        self.assertIn("dhcp4: true\n      routes:\n        - to: 10.20.0.0/24", dhcp)
        self.assertNotIn("routes", agent.NetplanNet.render("eth0", "dhcp", "", "", [], ()))

    def test_networkmanager(self):
        got = agent.NetworkManagerNet.render("eth0", "dhcp", "", "", [], R)
        self.assertEqual(got["ipv4.routes"], "10.20.0.0/24 192.168.1.1, 172.16.5.0/24 192.168.1.2")
        self.assertIn("ipv4.routes", agent.NetworkManagerNet.FIELDS, "snapshotted, so a revert puts them back")
        self.assertEqual(agent.NetworkManagerNet.render("eth0", "static", "1.2.3.4/24", "", [], ())["ipv4.routes"], "")

    def test_networkd(self):
        text = next(iter(agent.NetworkdNet().render("eth0", "dhcp", "", "", [], R).values()))
        self.assertIn("[Route]\nDestination=10.20.0.0/24\nGateway=192.168.1.1\n", text)
        self.assertEqual(text.count("[Route]"), 2)

    def test_ifupdown_keeps_them_in_the_stanza(self):
        with open(agent.INTERFACES_FILE, "w") as f:
            f.write("auto lo\niface lo inet loopback\n")
        text = agent.IfupdownNet().render("eth0", "static", "192.168.1.10/24", "192.168.1.1", [], R)[agent.INTERFACES_FILE]
        self.assertIn("    up ip route add 10.20.0.0/24 via 192.168.1.1 dev eth0\n"
                      "    down ip route del 10.20.0.0/24 via 192.168.1.1 dev eth0\n", text)
        self.assertTrue(text.startswith("auto lo\niface lo inet loopback\n"))

    def test_wicked_ifroute(self):
        out = agent.WickedNet().render("eth0", "static", "192.168.1.10/24", "192.168.1.1", [], R)
        route = out[os.path.join(agent.SYSCONFIG_NET_DIR, "ifroute-eth0")]
        self.assertEqual(route, "default 192.168.1.1 - eth0\n10.20.0.0/24 192.168.1.1 - eth0\n"
                                "172.16.5.0/24 192.168.1.2 - eth0\n")
        dhcp = agent.WickedNet().render("eth0", "dhcp", "", "", [], ())
        self.assertIsNone(dhcp[os.path.join(agent.SYSCONFIG_NET_DIR, "ifroute-eth0")])

    def test_dhcpcd_says_it_cannot(self):
        self.assertIn("no setting for a static route", agent.DhcpcdNet.no_routes)


if __name__ == "__main__":
    unittest.main()
