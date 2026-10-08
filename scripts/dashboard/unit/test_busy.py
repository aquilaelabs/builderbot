"""Whether a node is quiet enough to time on (R108): busy.verdict's word
and reasons, and the agent's count of what runs there by kind."""
import importlib.util
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import busy  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "builderbot_agent_busy", os.path.join(HERE, "..", "..", "agent", "builderbot-agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def sample(**k):
    return {"at": int(time.time()), "cores": 4, "load1": 0.2, "cpu_pct": 5, "mem_used_mb": 2000,
            "mem_mb": 16000} | k


class Verdict(unittest.TestCase):
    def test_quiet(self):
        self.assertEqual(busy.verdict(sample(), [], 1), ("quiet", []))

    def test_idle_processes_alone_leave_it_quiet(self):
        # Two Gradle daemons idling after a build, at 2.7% CPU (2 Oct).
        word, why = busy.verdict(sample(cpu_pct=2.7, load1=0.7, kinds={"gradle": 2}), [], 1)
        self.assertEqual(word, "quiet")
        self.assertEqual(why, ["running: 2 gradle, idle"])

    def test_busy_says_why_without_naming_another_project(self):
        word, why = busy.verdict(sample(load1=2.4, kinds={"emulator": 1, "gradle": 2, "claude": 3}),
                                 [{"type": "exec", "mine": False}, {"type": "sign", "mine": True}], 3)
        self.assertEqual(word, "busy")
        self.assertIn("load 2.4 on 4 cores", why)
        self.assertIn("running: 1 emulator, 2 gradle", why)
        self.assertIn("1 job of other projects", why)
        self.assertIn("2 other Claude sessions working", why)

    def test_saturated(self):
        self.assertEqual(busy.verdict(sample(load1=14.0), [], 1)[0], "saturated")
        self.assertEqual(busy.verdict(sample(cpu_pct=97), [], 1)[0], "saturated")
        self.assertEqual(busy.verdict(sample(mem_used_mb=15500), [], 1)[0], "saturated")

    def test_a_node_that_has_not_reported_is_unknown(self):
        self.assertEqual(busy.verdict(sample(at=int(time.time()) - 600), [], 1)[0], "unknown")
        self.assertEqual(busy.verdict({}, [], 0)[0], "unknown")


class Kinds(unittest.TestCase):
    def test_it_counts_by_kind_from_proc(self):
        root = tempfile.mkdtemp()
        for pid, comm, args in ((10, "qemu-system-x86_64-headless", "qemu -avd x"),
                                (11, "java", "java -cp gradle-launcher org.gradle.launcher.daemon.bootstrap.GradleDaemon"),
                                (12, "java", "java -jar thing.jar"), (13, "bash", "bash"),
                                (14, "claude", "claude --remote-control")):
            d = os.path.join(root, str(pid))
            os.makedirs(d)
            with open(os.path.join(d, "comm"), "w") as f:
                f.write(comm + "\n")
            with open(os.path.join(d, "cmdline"), "wb") as f:
                f.write(args.replace(" ", "\0").encode())
        self.assertEqual(agent._proc_kinds(root), {"emulator": 1, "gradle": 1, "java": 1, "claude": 1})


if __name__ == "__main__":
    unittest.main()
