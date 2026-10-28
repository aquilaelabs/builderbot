"""A node's features (R91): bb-sandbox's feature command checks its verb and
id before it touches the machine, the controller queues the install as a
system job and refuses what could only fail with the reason the Features
section shows, and the agent hands bb-sandbox nothing outside its table."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import nodes  # noqa: E402

PROVISIONER = os.path.join(HERE, "..", "..", "..", "nodes", "provision-linux.sh")
CENSUS = {"cpu": 2, "mem_mb": 4096, "arch": "x86_64", "system": "linux", "administers": True, "sandbox": True,
          "features": {"vmhost": {"installed": False, "kvm": True, "libvirt": "10.0.0"},
                       "firewall": {"installed": False}}}


class Helper(unittest.TestCase):
    """bb-sandbox feature, run as the bash it is, with id standing in for
    root: an unknown verb or feature is refused by name before anything."""
    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with open(PROVISIONER, encoding="utf-8") as f:
            m = re.search(r"^cat > \"\$BBSANDBOX_TMP\" <<'BBSANDBOX'\n(.*?)^BBSANDBOX$", f.read(), re.S | re.M)
        self.helper = os.path.join(d, "bb-sandbox")
        with open(self.helper, "w", encoding="utf-8") as f:
            f.write(m.group(1))
        os.mkdir(os.path.join(d, "bin"))
        with open(os.path.join(d, "bin", "id"), "w") as f:
            f.write("#!/bin/sh\necho 0\n")
        os.chmod(os.path.join(d, "bin", "id"), 0o755)
        self.env = os.environ | {"PATH": f"{d}/bin:{os.environ['PATH']}"}

    def run_helper(self, *args):
        return subprocess.run(["bash", self.helper, "feature", *args], capture_output=True, text=True,
                              timeout=30, env=self.env)

    def test_an_unknown_feature_or_verb_is_refused_by_name(self):
        r = self.run_helper("install", "warpdrive")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no such feature: warpdrive; one of: vmhost firewall iommu", r.stderr)
        r = self.run_helper("explode", "vmhost")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("usage: bb-sandbox feature install|remove|state", r.stderr)

    def test_state_reads_the_marker(self):
        r = self.run_helper("state", "vmhost")
        self.assertEqual((r.returncode, r.stdout.strip()),
                         (0, "installed" if os.path.exists("/etc/builderbot/features/vmhost") else "absent"))


class Controller(unittest.TestCase):
    def setUp(self):
        nodes.configure(state=tempfile.mkdtemp())
        mint = nodes.enroll_mint("user:test", "box")
        self.nid = mint["id"]
        nodes.enroll(nodes.authenticate(mint["token"]), dict(CENSUS), "203.0.113.5", user="bb")

    def census(self, **features):
        c = json.loads(json.dumps(CENSUS))
        for k, v in features.items():
            c["features"][k].update(v)
        rep = dict(nodes.node(self.nid).get("reported") or {}, features=c["features"])
        nodes._exec("UPDATE nodes SET reported = ? WHERE id = ?", (json.dumps(rep), self.nid))

    def test_an_install_is_a_system_job_with_its_feature(self):
        r = nodes.node_feature("user:test", self.nid, "vmhost", "install")
        self.assertTrue(r.get("job"), r)
        got = nodes.job_next(self.nid, 0)
        self.assertEqual((got or {}).get("spec", {}).get("apply"), "feature")
        self.assertEqual(got["spec"]["config"], {"id": "vmhost", "op": "install"})
        self.assertIn("one at a time", nodes.node_feature("user:test", self.nid, "vmhost", "install").get("error", ""))

    def test_no_kvm_is_refused_with_the_host_setting(self):
        self.census(vmhost={"kvm": False})
        self.assertIn("host-passthrough", nodes.node_feature("user:test", self.nid, "vmhost", "install").get("error", ""))

    def test_a_kernel_without_kvm_says_so(self):
        self.census(vmhost={"kvm": False, "nokvm": "kernel"})
        self.assertIn("kernel-default", nodes.node_feature("user:test", self.nid, "vmhost", "install").get("error", ""))

    def test_the_firewall_is_a_hosting_only_node_s(self):
        self.assertIn("hosting-only", nodes.node_feature("user:test", self.nid, "firewall", "install").get("error", ""))
        # ...whose machine runs no sessions: the switch alone left them, and
        # the job failed on the machine (R97's walk).
        nodes.node_update("user:test", self.nid, {"host_only": True})
        rep = dict(nodes.node(self.nid).get("reported") or {}, session={"up": True})
        nodes._exec("UPDATE nodes SET reported = ? WHERE id = ?", (json.dumps(rep), self.nid))
        self.assertIn("still runs sessions", nodes.node_feature("user:test", self.nid, "firewall", "install").get("error", ""))

    def test_an_unknown_one_is_refused(self):
        self.assertIn("no such feature", nodes.node_feature("user:test", self.nid, "warpdrive", "install").get("error", ""))

    def test_a_controller_update_is_the_own_node_s_job_on_a_bare_metal_install(self):
        # R90 step 5: refused on a container install and on any node but
        # the controller's own machine; there, a system job with the release
        # named only by its tag.
        from unittest import mock
        with mock.patch.dict(os.environ, {"BB_INSTALL": ""}):
            self.assertIn("installed bare metal", nodes.node_controller_update("user:test", self.nid).get("error", ""))
        with mock.patch.dict(os.environ, {"BB_INSTALL": "bare-metal"}):
            self.assertIn("own machine", nodes.node_controller_update("user:test", self.nid).get("error", ""))
            cfg = dict((nodes.node(self.nid) or {}).get("config") or {}, own=True)
            nodes._exec("UPDATE nodes SET config = ? WHERE id = ?", (json.dumps(cfg), self.nid))
            self.assertIn("vX.Y.Z", nodes.node_controller_update("user:test", self.nid, "main").get("error", ""))
            r = nodes.node_controller_update("user:test", self.nid, "v0.9.0")
            self.assertTrue(r.get("job"), r)
            got = nodes.job_next(self.nid, 0)
            self.assertEqual((got["spec"]["apply"], got["spec"]["config"]), ("controller-update", {"release": "v0.9.0"}))
            self.assertIn("one at a time", nodes.node_controller_update("user:test", self.nid).get("error", ""))


class Agent(unittest.TestCase):
    def test_only_the_table_reaches_bb_sandbox(self):
        import agentpkg
        agent = agentpkg.load("builderbot_agent_features")
        a = object.__new__(agent.Agent)
        a.state = {}
        ran = []
        a._sh = lambda job, argv, **kw: ran.append(argv[1:]) or 0
        a.hello_again = lambda why: None

        class Job:
            def say(self, x):
                pass
        self.assertEqual(a._apply_feature(Job(), {"id": "vmhost; rm -rf /", "op": "install"}), ("failed", 64))
        self.assertEqual(a._apply_feature(Job(), {"id": "vmhost", "op": "purge"}), ("failed", 64))
        self.assertEqual(a._apply_feature(Job(), {"id": "vmhost", "op": "remove"}), ("succeeded", 0))
        self.assertEqual(ran, [["feature", "remove", "vmhost"]])
        # The controller's own update (R90 step 5): only where the installer's
        # own-node marker and the installer are, and a release by its tag.
        from unittest import mock
        self.assertEqual(a._apply_controller_update(Job(), {}), ("failed", 77))
        with mock.patch("os.path.isfile", return_value=True):
            self.assertEqual(a._apply_controller_update(Job(), {"release": "main; rm -rf /"}), ("failed", 64))
            a._sh = lambda job, argv, **kw: ran.append(argv) or 0
            self.assertEqual(a._apply_controller_update(Job(), {"release": "v0.9.0"}), ("succeeded", 0))
            self.assertEqual(ran[-1], ["bash", "/opt/builderbot/nodes/install-controller.sh", "--update", "--release", "v0.9.0"])


class HelperFresh(unittest.TestCase):
    """B163: a system job fetches the bundle before it compares bb-sandbox
    with the bundle's copy, so a job pressed right after a controller update
    does not run the helper from before it."""
    def test_the_bundle_is_fetched_first(self):
        import agentpkg
        agent = agentpkg.load("builderbot_agent_fresh")
        cp = sys.modules[agent.Agent.__module__.rsplit(".", 1)[0] + ".configplane"]
        a = object.__new__(agent.Agent)
        a.state = {"user": "bb", "stores": {"toolchains": "/nowhere"}}
        fetched = []
        a.bundle = lambda job, who: fetched.append(who) or ""
        a.as_user = lambda env, user: {"user": user}
        was = (cp.os.geteuid, cp.os.path.isfile, cp.tc_root)
        cp.os.geteuid, cp.os.path.isfile, cp.tc_root = (lambda: 0), (lambda p: p == cp.SANDBOX_BIN), (lambda st: "/nowhere")
        try:
            a.refresh_sandbox_tool(None)
        finally:
            cp.os.geteuid, cp.os.path.isfile, cp.tc_root = was
        self.assertEqual(fetched, [{"user": "bb"}])


if __name__ == "__main__":
    unittest.main()


class PowerEndsSessions(unittest.TestCase):
    """B372: a reboot or a power-off ends every session on the machine first
    and says so to the controller before the machine goes, so none is left
    open on the record."""
    def test_sessions_end_before_the_machine_goes(self):
        import agentpkg
        agent = agentpkg.load("builderbot_agent_power")
        cp = sys.modules[agent.Agent.__module__.rsplit(".", 1)[0] + ".configplane"]
        a = object.__new__(agent.Agent)
        order = []
        a.sessions_now = lambda: [{"name": "u_12345678~claude-alpha"}, {"name": "sh-alpha"}]
        a.kill_sessions = lambda names, why="": order.append(("end", tuple(names), why))
        a.hello_at = 5.0
        a.hello_again = lambda why: order.append(("hello", why))
        said = []

        class Job:
            def say(self, x):
                said.append(x)
        was = (cp.os.geteuid, cp.subprocess.Popen)
        cp.os.geteuid = lambda: 0
        # subprocess is the process's own module: another thread's Popen in
        # the same moment is that thread's, not the power-off (B403).
        me, real = threading.get_ident(), was[1]
        cp.subprocess.Popen = lambda argv, **kw: (order.append(("power", argv[-2:])) if threading.get_ident() == me
                                                  else real(argv, **kw))
        try:
            got = a._apply_power(Job(), "poweroff")
        finally:
            cp.os.geteuid, cp.subprocess.Popen = was
        self.assertEqual(got, ("succeeded", 0))
        self.assertEqual([o[0] for o in order], ["end", "hello", "power"])
        self.assertEqual(order[0][1], ("u_12345678~claude-alpha", "sh-alpha"))
        self.assertIn("before a power off", order[0][2])
        self.assertTrue(any("ending 2 sessions first" in x for x in said))
