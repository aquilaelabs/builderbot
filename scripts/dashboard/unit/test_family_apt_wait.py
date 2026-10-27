"""The Debian family's apt waits for another apt to let go of its lock (B320):
a machine just booted from a cloud image runs its own apt-get for a few
minutes, and an install begun as soon as ssh answered failed on the lock.
apt_waiting runs the command again while it fails on the lock, and passes
any other failure on at once. Against a stand-in apt-get on PATH."""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DEB = os.path.join(HERE, "..", "..", "..", "nodes", "families", "deb.sh")

STUB = """#!/bin/bash
n=$(cat "$STATE" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$STATE"
if [ "$n" -le "$LOCKED" ]; then
  echo "E: Could not get lock /var/lib/apt/lists/lock. It is held by process 1054 (apt-get)" >&2; exit 100
fi
[ "$FAIL" = 1 ] && { echo "E: Unable to locate package nope" >&2; exit 100; }
echo "done $*"
"""


class AptWaiting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bin_ = os.path.join(self.tmp, "bin")
        os.mkdir(bin_)
        for name, body in (("apt-get", STUB), ("sleep", "#!/bin/sh\nexit 0\n")):
            with open(os.path.join(bin_, name), "w") as f:
                f.write(body)
            os.chmod(os.path.join(bin_, name), 0o755)
        self.env = {**os.environ, "PATH": bin_ + ":" + os.environ["PATH"], "STATE": os.path.join(self.tmp, "n")}

    def run_it(self, locked, fail=False):
        env = dict(self.env, LOCKED=str(locked), FAIL="1" if fail else "0")
        return subprocess.run(["bash", "-c", f'source "{DEB}"; pkg_refresh'], capture_output=True, text=True, env=env, timeout=30)

    def tries(self):
        with open(self.env["STATE"]) as f:
            return int(f.read())

    def test_a_held_lock_is_waited_out(self):
        r = self.run_it(locked=3)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("done update", r.stdout)
        self.assertEqual(self.tries(), 4)
        self.assertEqual(r.stderr.count("waiting for another apt"), 1, "said once")

    def test_any_other_failure_is_passed_on_at_once(self):
        r = self.run_it(locked=0, fail=True)
        self.assertEqual(r.returncode, 100)
        self.assertIn("Unable to locate package", r.stdout)
        self.assertEqual(self.tries(), 1)


if __name__ == "__main__":
    unittest.main()
