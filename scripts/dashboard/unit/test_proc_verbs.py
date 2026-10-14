"""bb proc (scripts/lib/proc-verbs.py, B736): a pattern that is on the
calling shell's own command line finds and ends the processes it names and
never that shell, which is what pgrep -f and pkill -f from a tool call get
wrong."""
import os
import subprocess
import sys
import time
import unittest
import uuid

VERBS = os.path.join(os.path.dirname(__file__), "..", "..", "lib", "proc-verbs.py")


class ProcVerbs(unittest.TestCase):
    def setUp(self):
        self.mark = "bbproc-" + uuid.uuid4().hex[:10]
        # A process that carries the mark: sleep, renamed through exec -a.
        self.child = subprocess.Popen(["bash", "-c", f"exec -a {self.mark}-sleeper sleep 60"])
        self.addCleanup(lambda: self.child.poll() is None and self.child.kill())
        time.sleep(0.3)

    def run_in_shell(self, *words):
        # The calling shell carries the mark on its own command line, the
        # way a tool call that names it does.
        line = f": {self.mark}; python3 {VERBS} " + " ".join(words)
        return subprocess.run(["bash", "-c", line], capture_output=True, text=True, timeout=30, check=False)

    def test_list_names_the_process_and_not_the_shell_asking(self):
        r = self.run_in_shell(self.mark)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, r.stdout)
        self.assertIn(f"{self.mark}-sleeper", lines[0])
        self.assertIn(str(self.child.pid), lines[0])

    def test_stop_ends_it_and_the_calling_shell_lives_to_say_so(self):
        r = self.run_in_shell("stop", self.mark)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"ended {self.child.pid}", r.stdout)
        self.child.wait(timeout=5)
        self.assertIsNotNone(self.child.returncode)

    def test_wait_returns_once_it_is_gone_and_reports_what_is_left_on_timeout(self):
        r = self.run_in_shell("wait", self.mark, "--timeout", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("still running after 1s", r.stderr)
        self.child.kill()
        self.child.wait(timeout=5)
        r = self.run_in_shell("wait", self.mark, "--timeout", "5")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def test_stop_refuses_an_empty_pattern(self):
        r = subprocess.run([sys.executable, VERBS, "stop"], capture_output=True, text=True, timeout=10, check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("takes a pattern", r.stderr)
        self.assertIsNone(self.child.poll())


if __name__ == "__main__":
    unittest.main()
