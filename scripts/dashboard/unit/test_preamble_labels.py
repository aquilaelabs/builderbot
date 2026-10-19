"""B1: the briefing a session is handed (bb preamble, scripts/lib/
preamble-verbs.py) names each project as the dashboard shows it, with its
directory beside it when the two differ, so a session and the person mean
the same project by the same name."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.join(HERE, "..")
VERBS = os.path.join(HERE, "..", "..", "lib", "preamble-verbs.py")


class PreambleLabels(unittest.TestCase):
    def test_shown_names_reach_the_briefing(self):
        with tempfile.TemporaryDirectory() as t:
            for d in ("here", "Old", "plain"):
                os.makedirs(os.path.join(t, "ws", d))
            with open(os.path.join(t, "projects.json"), "w") as f:
                json.dump({"next": 4, "projects": {
                    "here": {"id": "p1", "name": "public", "state": "live"},
                    "Old": {"id": "p2", "name": "old-private", "state": "live"},
                    "plain": {"id": "p3", "name": "plain", "state": "live"}}}, f)
            with open(os.path.join(t, "claude-prefs.json"), "w") as f:
                json.dump({"projects": {"here": {"reads": ["Old", "plain"]}}}, f)
            env = dict(os.environ, DASHBOARD_STATE=t, WORKSPACE=os.path.join(t, "ws"))
            out = subprocess.run([sys.executable, VERBS, DASH, "here", ""], env=env,
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("This project is shown as public; its directory is /workspace/here", out.stdout)
            self.assertIn("This project reads old-private (directory Old), plain:", out.stdout)


if __name__ == "__main__":
    unittest.main()
