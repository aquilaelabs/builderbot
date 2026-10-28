"""The controller's own machine's name and time zone (R161 step 3, R56 step
8): the agent's machine job sets each through systemd's tool after holding
it to its shape, the census carries the time zone, and the controller
queues the job for the own machine alone."""
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import agentpkg  # noqa: E402


class Job:
    def __init__(self):
        self.log = []

    def say(self, s):
        self.log.append(s)

    def step(self, s):
        self.log.append(f"[{s}]")

    def text(self):
        return "".join(self.log)


class TheAgent(unittest.TestCase):
    def setUp(self):
        self.agent = agentpkg.load("builderbot_agent_machine")
        self.cp = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".configplane"]
        self.d = tempfile.mkdtemp()
        self.seenf = os.path.join(self.d, "seen")
        for tool in ("hostnamectl", "timedatectl"):
            p = os.path.join(self.d, tool)
            with open(p, "w") as f:
                f.write(f'#!/bin/sh\necho "{tool} $*" >> {self.seenf}\n')
            os.chmod(p, stat.S_IRWXU)
        cp = self.cp

        class A(cp.ConfigPlaneMixin):
            def _sh(self, job, argv, cwd=None, timeout=0):
                r = subprocess.run(argv, capture_output=True, text=True, check=False)
                job.say(r.stdout)
                return r.returncode

            def hello_again(self, why):
                self.said = why
        self.A = A

    def run_job(self, cfg, zone_ok=True):
        job = Job()
        with mock.patch.dict(os.environ, {"PATH": self.d + ":" + os.environ.get("PATH", "")}), \
             mock.patch.object(self.cp.os, "geteuid", return_value=0), \
             mock.patch.object(self.cp.os.path, "isfile", side_effect=lambda p: zone_ok if p.startswith("/usr/share/zoneinfo/") else os.path.exists(p)):
            state, code = self.A()._apply_machine(job, cfg)
        return state, code, job.text()

    def seen(self):
        try:
            return open(self.seenf).read()
        except OSError:
            return ""

    def test_the_name_and_the_zone_are_set_through_systemds_tools(self):
        state, code, text = self.run_job({"hostname": "Nas-One", "timezone": "Europe/Paris"})
        self.assertEqual((state, code), ("succeeded", 0), text)
        self.assertEqual(self.seen().splitlines(), ["hostnamectl set-hostname nas-one", "timedatectl set-timezone Europe/Paris"])

    def test_what_is_not_a_name_or_a_zone_is_refused_before_any_tool_runs(self):
        for cfg in ({"hostname": "bad name"}, {"hostname": "-x"}, {"hostname": "a" * 64}, {"timezone": "../etc"}, {"timezone": "Mars/Base"}, {}):
            state, code, text = self.run_job(cfg, zone_ok=False)
            self.assertEqual(state, "failed", cfg)
            self.assertIn("refused", text)
        self.assertEqual(self.seen(), "")

    def test_the_census_reads_the_zone_off_the_system(self):
        census = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".census"]
        with mock.patch("builtins.open", mock.mock_open(read_data="Europe/Berlin\n")):
            self.assertEqual(census.timezone_now(), "Europe/Berlin")
        with mock.patch("builtins.open", side_effect=OSError), mock.patch.object(census.os, "readlink", return_value="/usr/share/zoneinfo/Asia/Tokyo"):
            self.assertEqual(census.timezone_now(), "Asia/Tokyo")
        with mock.patch("builtins.open", side_effect=OSError), mock.patch.object(census.os, "readlink", side_effect=OSError):
            self.assertEqual(census.timezone_now(), "")


class TheController(unittest.TestCase):
    def test_the_zone_is_kept_to_its_shape_and_the_verb_is_the_own_machines(self):
        import nodes
        self.assertEqual(nodes._census({"timezone": "Europe/Paris<b>"})["timezone"], "Europe/Parisb")
        self.assertNotIn("timezone", nodes._census({"timezone": 7}))
        # The verb's gates are node_machine's: a node that is not the own
        # machine is told so (the rest of its gates are every system job's).
        state = tempfile.mkdtemp()
        nodes.configure(state=state)
        self.assertEqual(nodes.node_machine("user:t", "n_none", "x")["error"], "no such node")


if __name__ == "__main__":
    unittest.main()
