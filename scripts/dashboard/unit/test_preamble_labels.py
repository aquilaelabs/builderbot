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

    def test_the_id_reaches_the_briefing_and_the_session_name(self):
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(os.path.join(t, "ws", "here-2"))
            with open(os.path.join(t, "projects.json"), "w") as f:
                json.dump({"next": 4, "projects": {
                    "here-2": {"id": 3, "name": "here", "state": "live"}}}, f)
            env = dict(os.environ, DASHBOARD_STATE=t, WORKSPACE=os.path.join(t, "ws"))
            run = lambda *a: subprocess.run([sys.executable, VERBS, DASH, "here-2", *a], env=env,  # noqa: E731
                                            capture_output=True, text=True, timeout=60)
            got = json.loads(run("--json").stdout)
            self.assertEqual((got["name"], got["id"]), ("here", "P3"))
            self.assertIn("Its id is P3, which never changes.", run("").stdout)

    def test_a_project_is_told_its_tool_packs(self):
        # R77: the packs its settings switch on, by name, and a pack's own
        # guidance as bb help tool-NAME; a project that has not switched one
        # on is told nothing about it.
        with tempfile.TemporaryDirectory() as t:
            for d in ("here", "other"):
                os.makedirs(os.path.join(t, "ws", d))
            with open(os.path.join(t, "toolpacks.json"), "w") as f:
                json.dump({"packs": {"hexkit": {"manifest": {"label": "Hex kit"}, "guidance": "Dump before you patch."}}}, f)
            with open(os.path.join(t, "claude-prefs.json"), "w") as f:
                json.dump({"projects": {"here": {"packs_on": ["hexkit"]}}}, f)
            env = dict(os.environ, DASHBOARD_STATE=t, WORKSPACE=os.path.join(t, "ws"))

            def run(proj, *a):
                return subprocess.run([sys.executable, VERBS, DASH, proj, *a], env=env,
                                      capture_output=True, text=True, timeout=60)
            self.assertIn("This project's sessions may use the tool packs Hex kit (`bb tool hexkit`)", run("here", "").stdout)
            self.assertIn("Dump before you patch.", run("here", "--topic", "tool-hexkit").stdout)
            self.assertNotIn("tool packs", run("other", "").stdout)
            self.assertNotEqual(run("other", "--topic", "tool-hexkit").returncode, 0)


if __name__ == "__main__":
    unittest.main()
