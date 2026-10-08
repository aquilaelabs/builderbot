"""bb build and bb test run once more when a failure reads as the projects
share's (B439): a tree on NFS now and then refuses a build's delete or lock,
and the same command passes when run again. A failure that is the code's
stands at once."""
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BB = os.path.join(HERE, "..", "..", "bb")
COMMON = os.path.join(HERE, "..", "..", "lib", "common.sh")

# run_here and share_flake out of bb, in a shell with bb's own options.
HARNESS = f"""set -euo pipefail
source {COMMON} 2>/dev/null || true
eval "$(sed -n '/^share_flake()/,/^}}/p;/^run_here()/,/^}}/p' {BB})"
tests_going() {{ :; }}
rc=0; run_here build -- "$1" || rc=$?; echo "rc=$rc"
"""


class ShareFlake(unittest.TestCase):
    def run_build(self, body):
        d = tempfile.mkdtemp()
        script = os.path.join(d, "b.sh")
        with open(script, "w") as f:
            f.write("#!/bin/sh\ncd \"$(dirname \"$0\")\"\n" + body)
        os.chmod(script, 0o755)
        r = subprocess.run(["bash", "-c", HARNESS, "x", script], capture_output=True, text=True,
                           cwd=d, env={**os.environ, "BB_PROJECT": "x"}, timeout=30, check=False)
        return r.stdout + r.stderr

    def test_a_failure_on_the_share_runs_once_more_and_says_so(self):
        out = self.run_build('if [ -f done ]; then echo built; exit 0; fi\ntouch done\n'
                             'echo "Unable to delete directory /w/app/build/intermediates"; exit 1\n')
        self.assertIn("reads as the projects share", out)
        self.assertIn("passed on the second run", out)
        self.assertIn("rc=0", out)

    def test_a_failure_of_the_code_stands(self):
        out = self.run_build('echo "e: Unresolved reference: foo"; exit 1\n')
        self.assertNotIn("once more", out)
        self.assertIn("rc=1", out)

    def test_a_second_failure_on_the_share_stands(self):
        out = self.run_build('echo "java.io.IOException: Stale file handle"; exit 1\n')
        self.assertEqual(out.count("Stale file handle"), 3)   # two runs and the warning naming it
        self.assertIn("rc=1", out)


if __name__ == "__main__":
    unittest.main()
