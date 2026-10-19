"""bb gpu (scripts/lib/gpu.py, R102): what a session is told about the
node's card, and the turn a heavy job takes on it. Run as the program it
is, with a fake sysfs, a stand-in nvidia-smi and a lock directory of its own."""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

GPU = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lib", "gpu.py")


class GpuVerb(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.bin = os.path.join(self.dir, "bin")
        self.lock = os.path.join(self.dir, "lock")
        os.mkdir(self.bin)
        os.mkdir(self.lock)
        for t in ("sh", "sleep", "true", "false", "env", "printenv"):
            os.symlink(shutil.which(t), os.path.join(self.bin, t))

    def card(self):
        d = os.path.join(self.dir, "sys", "bus", "pci", "devices", "0000:04:00.0")
        os.makedirs(d)
        for name, text in (("vendor", "0x10de"), ("class", "0x030000")):
            with open(os.path.join(d, name), "w") as f:
                f.write(text + "\n")

    def smi(self, used=1000, total=8192):
        f = os.path.join(self.bin, "nvidia-smi")
        with open(f, "w") as h:
            h.write(f'#!/bin/sh\ncase "$1" in --query-gpu*) echo "NVIDIA GeForce RTX 3070 Ti, {used}, {total}" ;; esac\n')
        os.chmod(f, os.stat(f).st_mode | stat.S_IEXEC)

    def go(self, *args, gpu="on", timeout=30):
        env = {"PATH": self.bin, "BB_SYS_ROOT": os.path.join(self.dir, "sys"), "BB_GPU_LOCK_DIR": self.lock,
               "BB_GPU": gpu, "BB_PROJECT": "alpha"}
        return subprocess.run([sys.executable, GPU, *args], capture_output=True, text=True, env=env,
                              timeout=timeout, check=False)

    def test_no_card_is_one_plain_line_and_nothing_for_status(self):
        self.assertEqual(self.go("line").stdout, "")
        self.assertIn("no NVIDIA card", self.go().stdout)

    def test_a_card_with_no_driver_says_who_installs_it(self):
        self.card()
        self.assertIn("no driver", self.go("line").stdout)
        r = self.go("run", "--", "true")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Toolchains page", r.stderr)

    def test_the_line_names_the_card_and_its_free_memory(self):
        self.card()
        self.smi(used=1024, total=8192)
        line = self.go("line").stdout
        self.assertIn("RTX 3070 Ti", line)
        self.assertIn("7.0 GB of 8.0 GB free", line)

    def test_a_session_the_card_is_not_for_is_told_who_said_so(self):
        self.card()
        self.smi()
        self.assertIn("project's settings", self.go("line", gpu="project").stdout)
        self.assertIn("switched off for sessions", self.go("line", gpu="node").stdout)
        r = self.go("run", "--", "true", gpu="node")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("CPU path", r.stderr)

    def test_run_gives_the_command_a_turn_and_its_exit_code(self):
        self.card()
        self.smi()
        self.assertEqual(self.go("run", "--", "true").returncode, 0)
        self.assertEqual(self.go("run", "--", "false").returncode, 1)
        self.assertEqual(self.go("run", "--", "printenv", "BB_GPU_TURN").stdout.strip(), "1")

    def test_more_memory_than_the_card_has_is_refused_at_once(self):
        self.card()
        self.smi(total=8192)
        r = self.go("run", "--mem", "20000", "--", "true")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("more than the card has", r.stderr)

    def test_a_second_job_waits_for_the_first_ones_turn(self):
        self.card()
        self.smi()
        env = {"PATH": self.bin, "BB_SYS_ROOT": os.path.join(self.dir, "sys"), "BB_GPU_LOCK_DIR": self.lock,
               "BB_GPU": "on", "BB_PROJECT": "alpha"}
        first = subprocess.Popen([sys.executable, GPU, "run", "--", "sleep", "1"], env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(first.kill)
        for _ in range(50):
            if os.path.exists(os.path.join(self.lock, "builderbot-gpu.holder")):
                break
            time.sleep(0.1)
        self.assertIn("held by alpha", self.go("line").stdout)
        late = self.go("run", "--wait", "0", "--", "true")
        self.assertNotEqual(late.returncode, 0)
        self.assertIn("did not come free", late.stderr)
        self.assertIn("held by alpha", late.stderr)
        first.wait(timeout=20)
        self.assertEqual(self.go("run", "--", "true").returncode, 0)
        self.assertNotIn("held by", self.go("line").stdout)


if __name__ == "__main__":
    unittest.main()
