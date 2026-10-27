"""The session port's rule is the screen relay's port alone (R133): a node
provisioned while ttyd's ports were open to the controller has them on
its next check narrowed to 7684, the one port its terminals and its VMs'
screens come in on, the controller's and nobody else's on the LAN
(nftables), and reachable by the controller at all (firewalld drops what
no rule allows), with ttyd's old rules taken away."""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import agentpkg  # noqa: E402

agent = agentpkg.load("builderbot_agent_session_ports")
agent.log = lambda *a, **k: None

OLD_NFT = """table inet builderbot_session {
    chain input {
        type filter hook input priority -10; policy accept;
        tcp dport { 7681, 7682 } iifname "lo" accept
        tcp dport { 7681, 7682 } ip saddr 192.168.1.16 accept
        tcp dport { 7681, 7682 } drop
    }
}
"""


class Fake(agent.SessionsMixin):
    state = {"controller": "http://ctl.example:7680"}
    fw_checked = 0


class SessionPorts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.g = Fake.session_firewall_check.__globals__
        saved = {k: self.g[k] for k in ("SESSION_NFT", "NFT_BIN", "controller_ip", "_have", "_run")}
        self.addCleanup(self.g.update, saved)
        self.g["controller_ip"] = lambda url: "192.168.1.16"
        self.g["NFT_BIN"] = "true"
        p = mock.patch.object(os, "geteuid", return_value=0)
        p.start()
        self.addCleanup(p.stop)

    def test_nftables_keeps_to_the_relays_port(self):
        nft = os.path.join(self.tmp, "session-ports.nft")
        with open(nft, "w") as f:
            f.write(OLD_NFT)
        self.g["SESSION_NFT"] = nft
        Fake().session_firewall_check()
        with open(nft) as f:
            text = f.read()
        self.assertEqual(text.count("tcp dport { 7684 }"), 3, text)
        self.assertNotIn("7681", text)
        self.assertIn("ip saddr 192.168.1.16 accept", text)
        before = os.stat(nft).st_mtime_ns
        a = Fake()
        a.session_firewall_check()
        self.assertEqual(os.stat(nft).st_mtime_ns, before, "a rule already right is left alone")

    def test_firewalld_trades_ttyds_rules_for_the_relays(self):
        self.g["SESSION_NFT"] = os.path.join(self.tmp, "none.nft")
        self.g["_have"] = lambda cmd: True
        rules = "\n".join(f'rule family="ipv4" source address="192.168.1.16" port port="{p}" protocol="tcp" accept'
                          for p in (7681, 7682))
        self.g["_run"] = lambda argv, timeout=10: "running" if "--state" in argv else rules
        calls = []
        with mock.patch.object(subprocess, "run", side_effect=lambda argv, **k: calls.append(argv) or
                               subprocess.CompletedProcess(argv, 0)):
            Fake().session_firewall_check()
        added = [a for c in calls for a in c if a.startswith("--add-rich-rule=")]
        removed = [a for c in calls for a in c if a.startswith("--remove-rich-rule=")]
        self.assertTrue(any('port="7684"' in a and 'address="192.168.1.16"' in a for a in added), added)
        self.assertEqual(len(added), 1)
        self.assertEqual(len(removed), 2, removed)


if __name__ == "__main__":
    unittest.main()
