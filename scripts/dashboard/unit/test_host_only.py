"""A hosting-only node held to running the containers sent to it, however
the work reaches it and whatever the box says about itself (R92)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nodes  # noqa: E402


def row(host_only=True, **kw):
    return {"id": "n_vps", "kind": "agent", "state": "online", "pool": "default", "capabilities": [],
            "labels": {}, "agent": {}, "config": {"host_only": True} if host_only else {}, **kw}


class Placement(unittest.TestCase):
    def setUp(self):
        self.was = nodes.agent_stale
        nodes.agent_stale = lambda n: ""

    def tearDown(self):
        nodes.agent_stale = self.was

    def test_a_selector_exec_is_not_taken_by_a_hosting_only_node(self):
        job = {"type": "exec", "placement": {"select": {"pool": "default"}}, "spec": {"argv": ["sh", "-c", "env"]}}
        self.assertFalse(nodes.fits(job, row()))
        self.assertTrue(nodes.fits(job, row(host_only=False)), "any other node in the pool takes it")

    def test_what_it_may_run_it_still_takes(self):
        sel = {"select": {"pool": "default"}}
        self.assertTrue(nodes.fits({"type": "compose", "placement": sel, "spec": {}}, row()))
        self.assertTrue(nodes.fits({"type": "exec", "placement": sel, "spec": {"argv": ["docker", "ps"]}}, row()))


class RefusalAudit(unittest.TestCase):
    def setUp(self):
        nodes._host_refused_at.clear()

    def test_a_verb_once_an_hour_and_made_up_verbs_kept_to_a_few(self):
        self.assertEqual(nodes.host_refused_audit("n_vps", "source", 0), "source")
        self.assertEqual(nodes.host_refused_audit("n_vps", "source", 10), "", "once an hour")
        said = [nodes.host_refused_audit("n_vps", f"a{i}", 20) for i in range(1000)]
        self.assertEqual(sum(1 for x in said if x), nodes.HOST_REFUSED_VERBS - 1)
        self.assertIn("unrecorded", [x for x in said if x][-1])
        self.assertLessEqual(len(nodes._host_refused_at), nodes.HOST_REFUSED_VERBS, "the table does not grow")
        self.assertEqual(nodes.host_refused_audit("n_other", "source", 30), "source", "another node is its own")
        self.assertEqual(nodes.host_refused_audit("n_vps", "source", 3700), "source", "an hour on, again")


class Hellos(unittest.TestCase):
    def test_a_dozen_a_minute(self):
        nodes._host_hellos.clear()
        said = [nodes.host_hello_allowed("n_vps", i) for i in range(30)]
        self.assertEqual(said.count(True), nodes.HOST_HELLOS_A_MINUTE)
        self.assertTrue(nodes.host_hello_allowed("n_vps", 61), "a minute on, again")
        self.assertTrue(nodes.host_hello_allowed("n_other", 5), "another node is its own")


class StaysHostOnly(unittest.TestCase):
    def test_a_node_enrolled_through_a_public_hostname_cannot_be_switched_off_hosting_only(self):
        import json
        import tempfile
        nodes.configure(state=tempfile.mkdtemp())
        nid = nodes.enroll_mint("user:test", "vps")["id"]
        nodes._exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(
            {"host_only": True, "tunnel": {"kind": "public", "host": "bb.example.com"}}), nid))
        self.assertIn("public hostname", nodes.node_update("user:test", nid, {"host_only": False}).get("error", ""))
        self.assertTrue(nodes.host_only(nid))
        nodes._exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps({"host_only": True}), nid))
        self.assertTrue(nodes.node_update("user:test", nid, {"host_only": False}).get("ok"), "one on the LAN may")


class Lockdown(unittest.TestCase):
    """Lock down: from the press the box may take only its lockdown job,
    which stops what it runs and shuts its door, and its credential is
    revoked when that ends or when its grace runs out unanswered."""

    def setUp(self):
        import json
        import tempfile
        nodes.configure(state=tempfile.mkdtemp())
        mint = nodes.enroll_mint("user:test", "vps")
        self.nid = mint["id"]
        nodes.enroll(nodes.authenticate(mint["token"]), {"cpu": 2, "mem_mb": 4096, "arch": "x86_64",
                                                         "system": "linux"}, "203.0.113.5", user="bb")

        nodes._exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps({"host_only": True}), self.nid))

    def test_its_job_ends_and_the_node_is_retired(self):
        r = nodes.node_lockdown("user:test", self.nid)
        self.assertTrue(r.get("job"), r)
        self.assertIn("already", nodes.node_lockdown("user:test", self.nid).get("error", ""))
        got = nodes.job_next(self.nid, 0)
        self.assertEqual((got or {}).get("id"), r["job"])
        nodes.job_result(self.nid, r["job"], "failed", 1)
        self.assertEqual(nodes.node(self.nid)["state"], "retired", "even when a step failed")

    def test_a_node_away_is_retired_at_the_press(self):
        nodes._exec("UPDATE nodes SET agent = json_set(agent, '$.last_seen', 0) WHERE id = ?", (self.nid,))
        r = nodes.node_lockdown("user:test", self.nid)
        self.assertTrue(r.get("retired"), r)
        self.assertEqual(nodes.node(self.nid)["state"], "retired")

    def test_a_locked_node_asks_for_nothing_but_its_job(self):
        cfg = dict(nodes.node(self.nid)["config"], lockdown={"at": 1e12, "by": "user:test"})
        import json
        nodes._exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(cfg), self.nid))
        self.assertEqual(nodes.host_refuses(self.nid, "work"), "")
        self.assertIn("locked down", nodes.host_refuses(self.nid, "devdata"))
        n = nodes.node(self.nid)
        mine = {"type": "system", "spec": {"apply": "lockdown"}, "placement": {"node": self.nid}}
        self.assertTrue(nodes.fits(mine, n))
        self.assertFalse(nodes.fits({"type": "compose", "spec": {}, "placement": {"node": self.nid}}, n))
        self.assertFalse(nodes.fits({"type": "self-update", "spec": {}, "placement": {"node": self.nid}}, n))

    def test_past_its_grace_it_is_retired_whether_or_not_it_answered(self):
        import json
        cfg = dict(nodes.node(self.nid)["config"], lockdown={"at": 1, "by": "user:test"})
        nodes._exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(cfg), self.nid))
        self.assertTrue(nodes.lockdown_over(nodes.node(self.nid)))

    def test_only_a_hosting_only_node(self):
        import json
        nodes._exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps({}), self.nid))
        self.assertIn("hosting-only", nodes.node_lockdown("user:test", self.nid).get("error", ""))


class AgentLockdown(unittest.TestCase):
    def test_every_container_stops_none_restarts_and_the_door_shuts(self):
        import tempfile
        import agentpkg
        agent = agentpkg.load("builderbot_agent_lockdown")
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "docker"), "w") as f:
            f.write("#!/bin/sh\n[ \"$1\" = ps ] && printf 'c1\\nc2\\n'\nexit 0\n")
        os.chmod(os.path.join(d, "docker"), 0o755)
        was = os.environ["PATH"]
        os.environ["PATH"] = f"{d}:{was}"
        self.addCleanup(os.environ.__setitem__, "PATH", was)
        a = object.__new__(agent.Agent)
        a.state = {"door": {"kind": "cloudflared"}}
        ran = []
        a._sh = lambda job, argv, **kw: ran.append([os.path.basename(argv[0]), *argv[1:]]) or 0

        class Job:
            said = []

            def say(self, x):
                self.said.append(x)
        st, code = a._apply_lockdown(Job())
        self.assertEqual((st, code), ("succeeded", 0))
        self.assertIn(["docker", "update", "--restart=no", "c1", "c2"], ran)
        self.assertIn(["docker", "stop", "-t", "10", "c1", "c2"], ran)
        if __import__("shutil").which("systemctl"):
            self.assertIn(["systemctl", "disable", "--now", "cloudflared"], ran)


if __name__ == "__main__":
    unittest.main()
