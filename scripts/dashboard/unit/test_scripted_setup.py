"""A new install set up from a shell on the controller (R84): the owner
claimed, a node's enrollment token minted, a folder put in place after the
first run made a project, and its node set, each as the dashboard does it."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.normpath(os.path.join(HERE, ".."))
LIB = os.path.normpath(os.path.join(HERE, "..", "..", "lib"))


class ScriptedSetup(unittest.TestCase):
    def setUp(self):
        self.state, self.ws = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.env = dict(os.environ, DASHBOARD_STATE=self.state, WORKSPACE=self.ws)

    def run_lib(self, script, *args, **env):
        return subprocess.run([sys.executable, os.path.join(LIB, script), *args],
                              env=dict(self.env, **env), capture_output=True, text=True, timeout=60)

    def test_the_owner_is_claimed_once(self):
        a = self.run_lib("users-verbs.py", "claim", os.path.join(DASH, "users.py"), "boss", BB_USERS_PW="longenough1")
        self.assertEqual(a.returncode, 0, a.stderr)
        rec = json.load(open(os.path.join(self.state, "users.json")))["users"]["boss"]
        self.assertEqual(rec["role"], "owner")
        self.assertRegex(rec["uid"], r"^u_[0-9a-f]{8}$")
        b = self.run_lib("users-verbs.py", "claim", os.path.join(DASH, "users.py"), "second", BB_USERS_PW="longenough1")
        self.assertNotEqual(b.returncode, 0)

    def test_a_token_a_project_and_its_node(self):
        t = self.run_lib("nodes-verbs.py", "enroll-token", os.path.join(DASH, "nodes.py"), "box1", "--user", "builder")
        self.assertEqual(t.returncode, 0, t.stderr)
        self.assertTrue(t.stdout.strip().startswith("bbe_"))
        self.assertNotEqual(self.run_lib("nodes-verbs.py", "enroll-token", os.path.join(DASH, "nodes.py"), "box1").returncode, 0)

        os.makedirs(os.path.join(self.ws, "first"))
        sys.path.insert(0, DASH)
        import registry
        registry.configure(state=self.state, workspace=self.ws,
                           write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
        registry.sync()
        os.makedirs(os.path.join(self.ws, "seeded"))
        a = self.run_lib("projects-adopt.py", DASH, BB_ADOPT_DIR="seeded", BB_ADOPT_NAME="Seeded App")
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertIn("shown as Seeded-App", a.stdout)
        self.assertNotEqual(self.run_lib("projects-adopt.py", DASH, BB_ADOPT_DIR="seeded").returncode, 0)

        n = self.run_lib("settings-verbs.py", "node", DASH, "seeded", BB_SET_VALUE="box1")
        self.assertEqual(n.returncode, 0, n.stderr)
        prefs = json.load(open(os.path.join(self.state, "claude-prefs.json")))
        self.assertTrue(prefs["projects"]["seeded"]["node"].startswith("n_"))
        self.assertNotEqual(self.run_lib("settings-verbs.py", "node", DASH, "seeded", BB_SET_VALUE="nope").returncode, 0)


if __name__ == "__main__":
    unittest.main()
