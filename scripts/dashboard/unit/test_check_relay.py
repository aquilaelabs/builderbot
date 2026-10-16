"""The stop hook's house-rule check (bb-check-relay, B759): it never waits for
a test run that holds the lock, since a session's own suites are what hold
it, and a refused check is skipped rather than reported; and when it does
block, the failing checks lead, not a tail of passing lint lines."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "bb-check-relay")
FAKE_BB = """#!/bin/bash
# Stands in for bb: says what it was handed, then answers as FAKE_MODE says.
echo "wait=${BB_TEST_WAIT_LOCK:-unset}" >> "$FAKE_LOG"
[ "$1" = toolchains ] && exit 0
case "$FAKE_MODE" in
  busy) echo "[dashboard-test] ERROR: another dashboard test run is going (pid 1)"; exit 1 ;;
  fail) echo "FAIL  [nodes] a status read that brings nothing new writes nothing"
        for i in $(seq 200); do echo "  [ok]   a passing lint line number $i"; done; exit 1 ;;
  *) exit 0 ;;
esac
"""


class CheckRelay(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "dashboard"))
        shutil.copy(HOOK, os.path.join(self.root, "dashboard", "bb-check-relay"))
        bb = os.path.join(self.root, "bb")
        with open(bb, "w") as f:
            f.write(FAKE_BB)
        os.chmod(bb, 0o755)
        self.tree = os.path.join(self.root, "ws")
        os.makedirs(self.tree)
        subprocess.run(["git", "init", "-q", self.tree], check=True)
        with open(os.path.join(self.tree, "changed.txt"), "w") as f:
            f.write("something new\n")
        self.log = os.path.join(self.root, "bb.log")

    def hook(self, mode):
        env = {**os.environ, "BB_TREE": self.tree, "XDG_CACHE_HOME": os.path.join(self.root, "cache"),
               "FAKE_MODE": mode, "FAKE_LOG": self.log, "BB_ACCOUNT_UID": "u_1"}
        env.pop("BB_TEST_WAIT_LOCK", None)
        r = subprocess.run([sys.executable, os.path.join(self.root, "dashboard", "bb-check-relay"), "alpha"],
                           input="{}", capture_output=True, text=True, env=env, check=False, timeout=60)
        return r.stdout

    def test_a_run_going_is_skipped_and_never_waited_for(self):
        self.assertEqual(self.hook("busy").strip(), "")
        with open(self.log) as f:
            self.assertIn("wait=0", f.read())

    def test_a_failure_leads_with_the_failing_checks(self):
        out = json.loads(self.hook("fail"))
        self.assertEqual(out["decision"], "block")
        self.assertIn("FAIL  [nodes] a status read", out["reason"].split("...")[0])

    def test_a_pass_says_nothing(self):
        self.assertEqual(self.hook("pass").strip(), "")


if __name__ == "__main__":
    unittest.main()
