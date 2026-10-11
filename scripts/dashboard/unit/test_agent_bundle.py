"""The agent's zip runs as a program (the operator, 11 Oct): the provisioner
runs it as "$AGENT enroll" and the unit as "$AGENT run", and a zip with no
first line was "Exec format error" for both, so a new node could not
enroll. The shebang goes before the zip; Python still finds the zip by its
end, and the bytes stay the same for the same sources."""
import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.join(HERE, "..", "..", "agent")
spec = importlib.util.spec_from_file_location("bb_bundle", os.path.join(AGENT, "builderbot_agent", "bundle.py"))
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class Bundle(unittest.TestCase):
    def test_it_runs_as_a_program_and_is_the_same_bytes_each_time(self):
        body = bundle.build(AGENT)
        self.assertTrue(body.startswith(b"#!/usr/bin/env python3\n"))
        self.assertEqual(body, bundle.build(AGENT))
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "builderbot-agent")
            with open(f, "wb") as h:
                h.write(body)
            os.chmod(f, os.stat(f).st_mode | stat.S_IEXEC)
            env = dict(os.environ, PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""))
            r = subprocess.run([f, "--help"], capture_output=True, text=True, timeout=30, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Runs anywhere", r.stdout + r.stderr)
            r = subprocess.run([f, "nosuch"], capture_output=True, text=True, timeout=30, env=env)
            self.assertEqual(r.returncode, 64, r.stderr)


if __name__ == "__main__":
    unittest.main()
