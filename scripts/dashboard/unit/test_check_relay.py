"""The stop hook's house-rule check (bb-check-relay, B759): it never waits for
a test run that holds the lock, since a session's own suites are what hold
it, and a refused check is skipped rather than reported; and when it does
block, the failing checks lead, not a tail of passing lint lines. Where the
project's new asks cut a test run (B824), the checks run detached and the
stop goes through at once; the verdict is served on the next hand-back."""
import time
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
# The project's Claude setting: restart where FAKE_CUT says so (B824).
[ "$1" = settings ] && { printf '{"test_change": "%s"}\\n' "${FAKE_CUT:-wait}"; exit 0; }
case "$FAKE_MODE" in
  slow) sleep 60; exit 0 ;;
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
        os.makedirs(os.path.join(self.root, "lib"))
        for m in ("rulehook.py", "cmdmatch.py"):
            shutil.copy(os.path.join(HERE, "..", "..", "lib", m), os.path.join(self.root, "lib", m))
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

    def hook(self, mode, cut="wait"):
        env = {**os.environ, "BB_TREE": self.tree, "XDG_CACHE_HOME": os.path.join(self.root, "cache"),
               "FAKE_MODE": mode, "FAKE_LOG": self.log, "BB_ACCOUNT_UID": "u_1", "FAKE_CUT": cut}
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

    def run_rec(self):
        try:
            with open(os.path.join(self.root, "cache", "builderbot", "u", "u_1", "project", "alpha", "checked.run")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def wait_ended(self):
        for _ in range(100):
            if self.run_rec().get("rc") is not None:
                return self.run_rec()
            time.sleep(0.1)
        self.fail("the background run never recorded its end")

    def test_where_asks_cut_a_run_the_stop_is_not_held_and_the_verdict_comes_next(self):
        t0 = time.time()
        self.assertEqual(self.hook("fail", cut="restart").strip(), "")
        self.assertLess(time.time() - t0, 20)
        self.assertEqual(self.wait_ended()["rc"], 1)
        out = json.loads(self.hook("fail", cut="restart"))
        self.assertEqual(out["decision"], "block")
        self.assertIn("FAIL  [nodes] a status read", out["reason"])
        sys.path.insert(0, os.path.join(self.root, "lib"))
        os.environ["XDG_CACHE_HOME"], os.environ["BB_ACCOUNT_UID"] = os.path.join(self.root, "cache"), "u_1"
        try:
            import rulehook
            said = rulehook.check_failed("alpha")
            self.assertIn("FAIL  [nodes] a status read", said)
            self.assertEqual(rulehook.check_failed("alpha"), "")
        finally:
            sys.path.remove(os.path.join(self.root, "lib"))
            sys.modules.pop("rulehook", None)
            os.environ.pop("XDG_CACHE_HOME", None)
            os.environ.pop("BB_ACCOUNT_UID", None)

    def test_a_newer_hand_back_cuts_the_run_still_going(self):
        self.assertEqual(self.hook("slow", cut="restart").strip(), "")
        first = self.run_rec()
        self.assertTrue(first.get("pid"))
        with open(os.path.join(self.tree, "changed.txt"), "a") as f:
            f.write("and more\n")
        self.assertEqual(self.hook("slow", cut="restart").strip(), "")
        for _ in range(50):
            try:
                os.kill(first["pid"], 0)
            except OSError:
                break
            time.sleep(0.1)
        else:
            self.fail("the run for the older tree was left going")
        self.assertNotEqual(self.run_rec().get("stamp"), first["stamp"])
        with __import__("contextlib").suppress(OSError):
            os.killpg(self.run_rec()["pid"], 15)


if __name__ == "__main__":
    unittest.main()
