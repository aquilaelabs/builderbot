"""bb settings show (scripts/lib/settings-verbs.py): every Agents may dial
is on the list a session reads, the signing ones included (R106), each as
the project has it or at its default."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.join(HERE, "..")
LIB = os.path.join(HERE, "..", "..", "lib")


class Show(unittest.TestCase):
    def run_show(self, project_prefs):
        state = tempfile.mkdtemp()
        with open(os.path.join(state, "claude-prefs.json"), "w") as f:
            json.dump({"projects": {"app": project_prefs}}, f)
        p = subprocess.run([sys.executable, os.path.join(LIB, "settings-verbs.py"), "show", DASH, "app"],
                           env=dict(os.environ, DASHBOARD_STATE=state, PYTHONPATH=LIB),
                           capture_output=True, text=True, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_the_signing_dials_are_listed_at_their_defaults(self):
        out = self.run_show({})
        self.assertRegex(out, r"Agents may: Sign a build\s+ask")
        self.assertRegex(out, r"Agents may: Manage signing keys\s+ask")

    def test_and_as_a_project_sets_them(self):
        out = self.run_show({"sign": "auto", "keys": "deny"})
        self.assertRegex(out, r"Agents may: Sign a build\s+auto")
        self.assertRegex(out, r"Agents may: Manage signing keys\s+deny")


if __name__ == "__main__":
    unittest.main()
