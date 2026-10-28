"""Encrypted pools (R162 step 3): the key record (kept sealed, or asked
after every boot and offered once), what the hello hands the agent and
nothing in Safe mode, the agent making a pool with the passphrase on
zpool's stdin and unlocking a locked pool from the hello, the census's
locked flag and the bell's row."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import agentpkg  # noqa: E402
import poolkeys  # noqa: E402


class TheRecord(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        poolkeys.configure(state=self.d, write_json=lambda p, v: open(p, "w").write(json.dumps(v)),
                           seal=lambda b: b"S" + b[::-1], unseal=lambda b: b[1:][::-1], sealing=lambda: True)
        poolkeys._pending.clear()

    def test_kept_sealed_or_asked_and_offered_once(self):
        self.assertIn("8 to 512", poolkeys.set_key("tank", "short", True)["error"])
        self.assertEqual(poolkeys.set_key("tank", "correct horse battery", True)["mode"], "kept")
        on_disk = json.load(open(os.path.join(self.d, "poolkeys.json")))["pools"]["tank"]["key"]
        self.assertTrue(on_disk.startswith("sealed:") and "horse" not in on_disk)
        self.assertEqual(poolkeys.wanted(set()), [{"pool": "tank", "passphrase": "correct horse battery"}])
        self.assertEqual(poolkeys.wanted(set(), safe_mode=True), [], "Safe mode boots with every pool locked")
        self.assertEqual(poolkeys.modes(), {"tank": "kept"})
        self.assertEqual(poolkeys.forget("tank")["mode"], "ask")
        self.assertEqual(poolkeys.wanted(set()), [], "asked after every boot: nothing kept, nothing offered yet")
        self.assertEqual(json.load(open(os.path.join(self.d, "poolkeys.json")))["pools"]["tank"]["key"], "")
        self.assertTrue(poolkeys.offer("tank", "correct horse battery")["ok"])
        self.assertEqual(poolkeys.wanted(set()), [{"pool": "tank", "passphrase": "correct horse battery"}])
        self.assertEqual(poolkeys.wanted({"tank"}), [], "the pool open: the offer is forgotten")
        self.assertEqual(poolkeys.wanted(set()), [])
        self.assertEqual(poolkeys.set_key("fast", "another passphrase", False)["mode"], "ask")
        self.assertEqual([k["pool"] for k in poolkeys.wanted(set())], ["fast"], "an ask-mode pool being made is offered once")
        poolkeys._pending["fast"] = ("another passphrase", 0)
        self.assertEqual(poolkeys.wanted(set()), [], "an offer not taken in time goes")

    def test_seal_all_seals_what_was_plain(self):
        poolkeys.configure(seal=None, unseal=None, sealing=lambda: False)
        poolkeys.set_key("tank", "plain passphrase", True)
        self.assertEqual(json.load(open(os.path.join(self.d, "poolkeys.json")))["pools"]["tank"]["key"], "plain passphrase")
        poolkeys.configure(seal=lambda b: b"S" + b[::-1], unseal=lambda b: b[1:][::-1], sealing=lambda: True)
        self.assertEqual(poolkeys.seal_all(), 1)
        self.assertEqual(poolkeys.wanted(set())[0]["passphrase"], "plain passphrase")


class TheAgent(unittest.TestCase):
    def setUp(self):
        self.agent = agentpkg.load("builderbot_agent_poolkeys")
        self.pm = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".pools"]
        pm = self.pm
        ran = self.ran = []

        class A(pm.PoolsMixin):
            def _sh(self, job, argv, timeout=0, **kw):
                ran.append(argv)
                return 0

            def hello_again(self, why):
                self.said = why
        self.A = A

    def test_the_census_says_encrypted_and_locked(self):
        def out(argv, timeout=0):
            if argv[1:2] == ["list"]:
                return "tank\t4000000000000\t1000000000000\t3000000000000\tONLINE\t-\n"
            if argv[1:3] == ["get", "-H"]:
                return "/mnt/tank\naes-256-gcm\nunavailable\n"
            return "errors: No known data errors\n"
        with mock.patch.object(self.pm, "_out", side_effect=out), mock.patch.object(self.pm.shutil, "which", return_value="/usr/sbin/zpool"):
            [p] = self.pm.pools_now()
        self.assertEqual((p["encrypted"], p["locked"]), (True, True))

    def test_a_pool_made_encrypted_takes_the_passphrase_from_the_hello_on_stdin(self):
        a = self.A()
        a.pool_keys_want([{"pool": "data", "passphrase": "correct horse battery"}])
        self.assertNotIn("pool_keys", getattr(a, "state", {}) or {}, "never in node.json")
        runs = []
        disks = [{"name": "sdb", "size_mb": 10, "system": False, "holds": "nothing", "parts": []}]
        with mock.patch.object(self.pm, "pools_now", return_value=[]), mock.patch.object(self.pm, "disks_now", return_value=disks), \
             mock.patch.object(self.pm.shutil, "which", return_value="/usr/sbin/zpool"), mock.patch.object(self.pm.os, "geteuid", return_value=0), \
             mock.patch.object(self.pm, "by_id", side_effect=lambda n: f"/dev/disk/by-id/ata-{n}"), \
             mock.patch.object(self.pm.subprocess, "run", side_effect=lambda argv, **kw: runs.append((argv, kw.get("input"))) or mock.Mock(returncode=0, stdout="", stderr="")):
            job = type("J", (), {"log": [], "say": lambda s, t: s.log.append(t), "text": lambda s: "".join(s.log)})()
            state, code = a._apply_storage_pool(job, {"pool": "create", "name": "data", "layout": "single", "disks": ["sdb"], "encrypt": True})
        self.assertEqual((state, code), ("succeeded", 0), job.text())
        argv, fed = runs[-1]
        self.assertEqual(argv[:2], ["/usr/sbin/zpool", "create"])
        self.assertIn("encryption=aes-256-gcm", argv)
        self.assertIn("keylocation=prompt", argv)
        self.assertEqual(fed, "correct horse battery\ncorrect horse battery\n")
        self.assertNotIn("correct horse", job.text(), "the passphrase is never in the job's log")
        self.assertEqual(self.ran, [], "nothing streamed: the one command took the passphrase on its stdin")

    def test_a_locked_pool_is_unlocked_from_the_hello_and_not_in_safe_mode(self):
        a = self.A()
        runs = []
        locked = [{"name": "tank", "encrypted": True, "locked": True}, {"name": "open", "encrypted": True, "locked": False}]
        with mock.patch.object(self.pm, "pools_now", return_value=locked), mock.patch.object(self.pm.shutil, "which", return_value="/usr/sbin/zfs"), \
             mock.patch.object(self.pm.os, "geteuid", return_value=0), mock.patch.object(self.pm, "safe_mode", return_value=False), \
             mock.patch.object(self.pm, "log"), \
             mock.patch.object(self.pm.subprocess, "run", side_effect=lambda argv, **kw: runs.append((argv, kw.get("input"))) or mock.Mock(returncode=0, stdout="", stderr="")):
            a.pool_keys_want([{"pool": "tank", "passphrase": "correct horse battery"}, {"pool": "open", "passphrase": "x" * 8}])
        self.assertEqual(runs[0], (["/usr/sbin/zfs", "load-key", "-L", "prompt", "tank"], "correct horse battery\n"))
        self.assertEqual(runs[1][0], ["/usr/sbin/zfs", "mount", "-a"])
        self.assertEqual(len(runs), 2, "the open pool is left alone")
        runs.clear()
        with mock.patch.object(self.pm, "pools_now", return_value=locked), mock.patch.object(self.pm.shutil, "which", return_value="/usr/sbin/zfs"), \
             mock.patch.object(self.pm.os, "geteuid", return_value=0), mock.patch.object(self.pm, "safe_mode", return_value=True), \
             mock.patch.object(self.pm.subprocess, "run", side_effect=lambda argv, **kw: runs.append(argv)):
            a.pool_keys_want([{"pool": "tank", "passphrase": "correct horse battery"}])
        self.assertEqual(runs, [], "Safe mode: every pool stays locked")


class TheController(unittest.TestCase):
    def test_the_census_the_verb_and_the_bell(self):
        import nodes
        got = nodes._census({"pools": [{"name": "tank", "size_mb": 1, "alloc_mb": 1, "free_mb": 0, "health": "ONLINE", "mount": "/mnt/tank", "encrypted": True, "locked": "yes", "vdevs": []}]})
        self.assertEqual((got["pools"][0]["encrypted"], got["pools"][0]["locked"]), (True, False))
        own = {"id": "n1", "name": "nas", "kind": "agent", "live": True, "config": {"own": True},
               "reported": {"administers": True, "pools": [{"name": "tank", "health": "online", "encrypted": True, "locked": True}]}}
        with mock.patch.object(nodes, "node_list", return_value=[own]):
            rows = nodes.storage_attention()
        self.assertEqual([(r["what"], r["bad"]) for r in rows], [("locked", False)])
        nodes.configure(state=tempfile.mkdtemp())
        with mock.patch.object(nodes, "node", return_value=own), mock.patch.object(nodes, "own_machine", return_value=True), \
             mock.patch.object(nodes, "audit"), mock.patch.object(nodes, "_bump"), \
             mock.patch.object(nodes, "pool_keys_offer", lambda p, k: {"ok": True, "pool": p}), \
             mock.patch.object(nodes, "pool_keys_set", lambda p, k, keep: {"ok": True, "pool": p, "mode": "kept" if keep else "ask"}), \
             mock.patch.object(nodes, "pool_keys_forget", lambda p: {"ok": True, "pool": p, "mode": "ask"}):
            self.assertIn("not an encrypted pool", nodes.node_storage_key("user:t", "n1", {"key": "unlock", "pool": "nope"})["error"])
            self.assertTrue(nodes.node_storage_key("user:t", "n1", {"key": "unlock", "pool": "tank", "passphrase": "x" * 9})["ok"])
            self.assertEqual(nodes.node_storage_key("user:t", "n1", {"key": "forget", "pool": "tank"})["mode"], "ask")


if __name__ == "__main__":
    unittest.main()
