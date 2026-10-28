"""The machine's power and its own packages (R164 step 3): the agent reads
the UPS through NUT and counts the host's package updates once an hour,
the host-update job runs apt and restarts only when asked, and the
controller keeps both to their shape, puts the battery and the updates on
the bell, and queues the job for the own machine alone."""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import agentpkg  # noqa: E402

UPSC = """battery.charge: 87
battery.runtime: 1543
device.model: Back-UPS 950
ups.load: 23
ups.status: OB DISCHRG
"""
SIM = """Reading package lists...
Inst libssl3t64 [3.0.15-1] (3.0.16-1 Debian-Security:13/stable-security [amd64])
Inst curl [8.14.1-1] (8.14.1-2 Debian:13.1/stable [amd64])
Conf libssl3t64 (3.0.16-1 Debian-Security:13/stable-security [amd64])
2 upgraded, 1 newly installed, 0 to remove and 0 not upgraded.
"""


class Job:
    def __init__(self):
        self.log = []

    def say(self, s):
        self.log.append(s)

    def text(self):
        return "".join(self.log)


class TheAgent(unittest.TestCase):
    def setUp(self):
        self.agent = agentpkg.load("builderbot_agent_power")
        self.pw = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".power"]
        pw = self.pw
        ran = self.ran = []

        class A(pw.PowerMixin):
            def __init__(self):
                self.state = {}

            def _sh(self, job, argv, timeout=0, **kw):
                ran.append(argv)
                return 0

            def hello_again(self, why):
                self.said = why
        self.A = A

    def test_the_ups_is_read_in_words(self):
        with mock.patch.object(self.pw.shutil, "which", return_value="/bin/upsc"), mock.patch.object(self.pw, "_out", return_value=UPSC):
            got = self.pw.ups_now()
        self.assertEqual(got, {"model": "Back-UPS 950", "status": "OB DISCHRG", "words": "on battery, discharging", "charge": 87, "runtime_s": 1543, "load": 23, "answers": True})
        with mock.patch.object(self.pw.shutil, "which", return_value="/bin/upsc"), mock.patch.object(self.pw, "_out", return_value="Error: Data stale\n"):
            self.assertFalse(self.pw.ups_now()["answers"])
        with mock.patch.object(self.pw.shutil, "which", return_value=None):
            self.assertEqual(self.pw.ups_now(), {})

    def test_the_hosts_updates_are_counted_once_an_hour_and_never_on_the_image(self):
        state = {}
        calls = []

        def out(argv, timeout=20, env=None):
            calls.append(argv)
            return SIM if "-s" in argv else ""
        with mock.patch.object(self.pw.shutil, "which", return_value="/usr/bin/apt-get"), mock.patch.object(self.pw.os, "geteuid", return_value=0), \
             mock.patch.object(self.pw, "os_release", return_value={}), mock.patch.object(self.pw, "_out", side_effect=out), \
             mock.patch.object(self.pw, "save_state"), mock.patch.object(self.pw.os.path, "exists", return_value=True):
            got = self.pw.host_updates_now(state)
            self.assertEqual((got["pending"], got["security"], got["reboot"]), (3, 1, True))
            self.assertEqual([a[1:] for a in calls], [["-qq", "update"], ["-s", "-o", "Debug::NoLocking=true", "upgrade"]])
            again = self.pw.host_updates_now(state)
            self.assertEqual(len(calls), 2, "within the hour the count kept is answered")
            self.assertEqual(again["pending"], 3)
        with mock.patch.object(self.pw.shutil, "which", return_value="/usr/bin/apt-get"), mock.patch.object(self.pw.os, "geteuid", return_value=0), \
             mock.patch.object(self.pw, "os_release", return_value={"version": "0.9.0"}):
            self.assertEqual(self.pw.host_updates_now({}), {}, "BuilderBot OS updates whole")

    def test_the_update_job_runs_apt_and_restarts_only_when_asked(self):
        a = self.A()
        with mock.patch.object(self.pw.shutil, "which", return_value="/usr/bin/apt-get"), mock.patch.object(self.pw.os, "geteuid", return_value=0), \
             mock.patch.object(self.pw, "os_release", return_value={}), mock.patch.object(self.pw, "save_state"), \
             mock.patch.object(self.pw.os.path, "exists", return_value=True):
            job = Job()
            self.assertEqual(a._apply_host_update(job, {}), ("succeeded", 0))
            self.assertEqual([x[3:5] if x[0] == "env" else x[:2] for x in self.ran], [["/usr/bin/apt-get", "-q"], ["/usr/bin/apt-get", "-y"], ["/usr/bin/apt-get", "-y"]])
            self.assertIn("a restart is needed", job.text())
            self.assertNotIn("shutdown", str(self.ran))
            self.ran.clear()
            job = Job()
            self.assertEqual(a._apply_host_update(job, {"reboot": True}), ("succeeded", 0))
            self.assertEqual(self.ran[-1][:3], ["shutdown", "-r", "+1"])
        with mock.patch.object(self.pw.shutil, "which", return_value="/usr/bin/apt-get"), mock.patch.object(self.pw.os, "geteuid", return_value=0), \
             mock.patch.object(self.pw, "os_release", return_value={"version": "0.9.0"}):
            job = Job()
            self.assertEqual(a._apply_host_update(job, {})[0], "failed")
            self.assertIn("whole image", job.text())


class TheController(unittest.TestCase):
    def test_the_census_keeps_the_ups_and_the_updates_to_their_shape(self):
        import nodes
        got = nodes._census({"ups": {"model": "Back-UPS<b>", "status": "OB LB", "words": "on battery, low battery", "answers": True, "charge": 12, "runtime_s": "x", "load": 40},
                             "host_updates": {"pending": 3, "security": 1, "reboot": "yes", "checked": 5}})
        self.assertEqual(got["ups"], {"model": "Back-UPSb", "status": "OB LB", "words": "on battery, low battery", "answers": True, "charge": 12, "runtime_s": None, "load": 40})
        self.assertEqual(got["host_updates"], {"pending": 3, "security": 1, "checked": 5, "reboot": False})
        self.assertNotIn("ups", nodes._census({"ups": {}}))

    def test_the_battery_and_the_updates_are_on_the_bell(self):
        import nodes
        own = {"id": "n1", "name": "nas", "kind": "agent", "live": True, "config": {"own": True},
               "reported": {"features": {"ups": {"installed": True, "nut": True}}, "ups": {"answers": True, "status": "OB DISCHRG", "charge": 80, "runtime_s": 900},
                            "host_updates": {"pending": 4, "security": 2, "reboot": True, "checked": 1}}}
        with mock.patch.object(nodes, "node_list", return_value=[own]):
            got = nodes.power_attention()
        self.assertEqual([(r["kind"], r["what"], r["bad"], r["key"]) for r in got],
                         [("power", "battery", True, "ups:battery:n1"), ("host", "security", False, "host:security:n1:2"), ("host", "reboot", False, "host:reboot:n1")])
        self.assertIn("at 80%, 15 min left", got[0]["said"])
        own["reported"]["ups"] = {"answers": False}
        own["reported"]["host_updates"] = {"pending": 4, "security": 0, "reboot": False}
        with mock.patch.object(nodes, "node_list", return_value=[own]):
            got = nodes.power_attention()
        self.assertEqual([r["what"] for r in got], ["silent"])
        own["reported"]["ups"]["status"] = "OL LB"
        own["reported"]["ups"]["answers"] = True
        with mock.patch.object(nodes, "node_list", return_value=[own]):
            self.assertEqual([(r["what"], r["bad"]) for r in nodes.power_attention()], [("low", True)])

    def test_the_verb_is_the_own_machines_and_never_the_images(self):
        import nodes
        nodes.configure(state=tempfile.mkdtemp())
        self.assertEqual(nodes.node_host_update("user:t", "n_none")["error"], "no such node")
        n = {"id": "n1", "name": "box", "kind": "agent", "live": True, "config": {"own": True}, "reported": {"administers": True, "os_image": {"version": "0.9.0"}}}
        with mock.patch.object(nodes, "node", return_value=n), mock.patch.object(nodes, "own_machine", return_value=True), \
             mock.patch.object(nodes, "node_locked", return_value=""), mock.patch.object(nodes, "system_job_for", return_value=None), \
             mock.patch.object(nodes, "audit"), mock.patch.object(nodes, "job_add", side_effect=lambda *a: {"ok": True, "job": "j1", "spec": a[3]}) as add:
            self.assertIn("whole image", nodes.node_host_update("user:t", "n1")["error"])
            n["reported"]["os_image"] = {}
            r = nodes.node_host_update("user:t", "n1", reboot=True)
            self.assertTrue(r.get("ok"), r)
            self.assertEqual(add.call_args[0][3], {"apply": "host-update", "config": {"reboot": True}, "timeout": 7200})


if __name__ == "__main__":
    unittest.main()
