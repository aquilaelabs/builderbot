"""A stick written rarely (R161 step 10): on a stick boot the initramfs puts
the logs and the journal in memory and holds docker, containerd and libvirt
until a system pool is named; the system-pool tool says the stick's state
and refuses a pool it cannot take; the agent reports it and runs the move
as a system job; the controller keeps the report to its shape and takes the
verb only for a stick, and only for a pool the machine has mounted."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.join(HERE, "..")
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
EXTRA = os.path.join(ROOT, "image", "mkosi.extra")
TOOL = os.path.join(EXTRA, "usr", "lib", "builderbot-os", "system-pool")
sys.path.insert(0, DASH)
import agentpkg  # noqa: E402


def read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


class Job:
    def __init__(self):
        self.out = []

    def say(self, s):
        self.out.append(s)


class TheImage(unittest.TestCase):
    def test_a_stick_boot_alone_keeps_the_logs_in_memory_and_holds_docker(self):
        s = read(EXTRA, "etc", "initramfs-tools", "scripts", "init-bottom", "builderbot-os")
        block = s[s.index('if [ "$stick" = 1 ]; then'):]
        self.assertIn("bbtoram=1) stick=1", s)
        self.assertIn("commit=60", block)
        self.assertIn('tmpfs "${rootmnt}/var/log"', block)
        self.assertIn("Storage=volatile", block)
        self.assertIn("ConditionPathExists=/run/builderbot-os/system-pool-ready", block)
        self.assertIn('"${rootmnt}/usr/lib/systemd', block, "written into the root's tmpfs: this boot alone")
        unit = read(EXTRA, "usr", "lib", "systemd", "system", "builderbot-os-system-pool.service")
        self.assertIn("ConditionKernelCommandLine=bbtoram=1", unit)
        self.assertIn("Before=containerd.service docker.service libvirtd.service", unit)
        self.assertIn("Restart=on-failure", unit)
        self.assertIn("builderbot-os-system-pool.service", read(ROOT, "image", "mkosi.postinst"))
        self.assertTrue(os.access(TOOL, os.X_OK))

    def tool(self, d, *argv, stick=True):
        with open(os.path.join(d, "cmd"), "w") as f:
            f.write("bbslot=a bbtoram=1\n" if stick else "bbslot=a\n")
        with open(os.path.join(d, "env"), "w") as f:
            f.write(f"SDK_ROOT={d}/sdk\nWORKSPACE={d}/ws\n")
        env = dict(os.environ, BB_OS_WORK=f"{d}/work", BB_OS_RUN=f"{d}/run", BB_CMDLINE=f"{d}/cmd", BB_CONTROLLER_ENV=f"{d}/env",
                   BB_SP_DOCKER=f"{d}/docker", BB_SP_CONTAINERD=f"{d}/containerd", BB_SP_LIBVIRT=f"{d}/libvirt", BB_SP_NO_SYSTEMCTL="1")
        return subprocess.run(["bash", TOOL, *argv], capture_output=True, text=True, env=env, check=False)

    def test_the_tool_says_what_is_on_the_stick_and_refuses_what_it_cannot_take(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(f"{d}/docker")
            with open(f"{d}/docker/x", "w") as f:
                f.write("x")
            got = json.loads(self.tool(d, "status").stdout)
            self.assertEqual((got["stick"], got["pool"], got["ready"], got["on_stick"]), (True, "", False, ["docker"]))
            self.assertIn("no system pool named yet", self.tool(d, "apply").stdout)
            self.assertEqual(self.tool(d, "set", "relative").returncode, 2)
            r = self.tool(d, "set", f"{d}/nopool")
            self.assertEqual(r.returncode, 2)
            self.assertIn("is not a mounted pool", r.stderr)
            self.assertEqual(json.loads(self.tool(d, "status", stick=False).stdout), {"stick": False})
            self.assertIn("not a stick boot", self.tool(d, "apply", stick=False).stdout)


class TheAgent(unittest.TestCase):
    def setUp(self):
        self.agent = agentpkg.load("builderbot_agent_stick")
        self.av = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".osimage"]

    def test_the_census_reads_the_tool(self):
        with tempfile.TemporaryDirectory() as d:
            fake = os.path.join(d, "system-pool")
            with open(fake, "w") as f:
                f.write('echo \'{"stick": true, "pool": "/mnt/fast", "ready": true, "on_stick": ["projects"], "written_kb": 2048, "boot_written_kb": 12}\'\n')
            with mock.patch.dict(os.environ, {"BB_OS_POOL": fake}):
                got = self.av.stick_status()
            self.assertEqual(got, {"stick": True, "pool": "/mnt/fast", "ready": True, "on_stick": ["projects"], "written_kb": 2048, "boot_written_kb": 12})
            with mock.patch.dict(os.environ, {"BB_OS_POOL": os.path.join(d, "none")}):
                self.assertEqual(self.av.stick_status(), {})

    def test_the_job_refuses_a_machine_without_the_tool_and_a_relative_path(self):
        av = self.av

        class A(av.OsImageMixin):
            def _sh(self, job, argv, **kw):
                self.ran = argv
                return 0

            def hello_again(self, why):
                self.said = why
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"BB_OS_POOL": os.path.join(d, "none")}):
                self.assertEqual(A()._apply_system_pool(Job(), {"path": "/mnt/fast"}), ("failed", 77))
            with open(os.path.join(d, "tool"), "w"):
                pass
            with mock.patch.dict(os.environ, {"BB_OS_POOL": os.path.join(d, "tool")}):
                self.assertEqual(A()._apply_system_pool(Job(), {"path": "mnt"}), ("failed", 64))
                a = A()
                self.assertEqual(a._apply_system_pool(Job(), {"path": "/mnt/fast"}), ("succeeded", 0))
                self.assertEqual(a.ran[-2:], ["set", "/mnt/fast"])


class TheController(unittest.TestCase):
    def test_the_census_keeps_the_stick_to_its_shape(self):
        import nodes
        got = nodes._census({"os_stick": {"stick": True, "pool": "/mnt/fast", "ready": True, "on_stick": ["projects", "evil"],
                                          "written_kb": 2048, "boot_written_kb": -1}})
        self.assertEqual(got["os_stick"], {"stick": True, "pool": "/mnt/fast", "ready": True, "on_stick": ["projects"],
                                           "written_kb": 2048, "boot_written_kb": None})
        self.assertNotIn("os_stick", nodes._census({"os_stick": {"stick": False}}))

    def test_the_verb_is_a_sticks(self):
        import nodes
        state = tempfile.mkdtemp()
        nodes.configure(state=state)
        tok = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "lib", "nodes-verbs.py"), "enroll-token",
                              os.path.join(DASH, "nodes.py"), "nas", "--own"],
                             env=dict(os.environ, DASHBOARD_STATE=state), capture_output=True, text=True, check=False)
        self.assertEqual(tok.returncode, 0, tok.stderr)
        n = next(x for x in nodes.node_list() if x["name"] == "nas")
        self.assertIn("does not run BuilderBot OS from a stick", nodes.node_system_pool("user:t", n["id"], "/mnt/fast").get("error", ""))
        self.assertEqual(nodes.node_system_pool("user:t", "n_nothere", "/mnt/fast").get("error"), "no such node")


if __name__ == "__main__":
    unittest.main()
