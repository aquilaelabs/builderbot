"""A toolchain update or removal on a node is refused while anything runs
from it, naming whose (the operator, 6 Oct): an update replaces files in
place, and a session's build or emulator running from them breaks under it."""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import agentpkg  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
agent = agentpkg.load("builderbot_agent_tc")
agent.log = lambda *a, **k: None


class InUse(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.store, ignore_errors=True)
        os.makedirs(os.path.join(self.store, "jdk", "bin"))
        os.makedirs(os.path.join(self.store, "android", "emulator"))
        os.makedirs(os.path.join(self.store, "android", "platforms", "android-36"))

    def test_where_each_kind_lives(self):
        s = self.store
        self.assertEqual(agent.tc_dir(s, "jdk", {"source": {"kind": "tarball"}}, "remove"), os.path.join(s, "jdk"))
        self.assertEqual(agent.tc_dir(s, "android:emulator", {"source": {"package": "emulator"}}, "install"),
                         os.path.join(s, "android", "emulator"))
        # Not installed: nothing to pull out from under anybody.
        self.assertEqual(agent.tc_dir(s, "node", {"source": {"kind": "tarball"}}, "install"), "")
        # A new platform level installs beside the old.
        self.assertEqual(agent.tc_dir(s, "android:platforms", {"source": {"package": "platforms", "versioned": True}},
                                      "install"), "")

    def test_a_process_running_from_it_is_named_with_its_project(self):
        d = os.path.join(self.store, "jdk")
        p = subprocess.Popen(["sleep", "30"], cwd=d, env={**os.environ, "BB_PROJECT": "Shebang-DevBoard"})
        self.addCleanup(p.kill)
        time.sleep(0.2)
        users = agent.tc_users(d)
        mine = [u for u in users if u["pid"] == p.pid]
        self.assertEqual(len(mine), 1, users)
        self.assertEqual(mine[0]["project"], "Shebang-DevBoard")
        said = agent.tc_users_said("jdk", mine)
        self.assertIn("jdk is in use by sleep", said)
        self.assertIn("Shebang-DevBoard's session", said)

    def test_an_install_of_what_is_there_is_an_update_by_the_verb_that_works(self):
        """R193 (the operator, 11 Oct), and Swift on a node (12 Oct): an
        install of a toolchain that is there already is `update` where that
        verb knows the recipe, and a remove and the install where it does
        not or the recipe refuses an existing directory; one not installed,
        or a versioned Android package, is the one verb."""
        s = self.store
        os.makedirs(os.path.join(s, "swift"))
        os.makedirs(os.path.join(s, "python"))
        self.assertEqual(agent.tc_verbs(s, "jdk", {"source": {"kind": "tarball"}}, "install"), ["remove", "install"])
        self.assertEqual(agent.tc_verbs(s, "jdk", {"source": {"kind": "tarball"}}, "remove"), ["remove"])
        self.assertEqual(agent.tc_verbs(s, "swift", {"updatable": True, "source": {"kind": "tarball", "fresh_only": True}}, "install"),
                         ["update"], "updatable and fresh_only both: update knows swift (it went to install, which refused)")
        self.assertEqual(agent.tc_verbs(s, "python", {"updatable": True, "source": {"kind": "script", "fresh_only": True}}, "install"),
                         ["remove", "install"], "update does not know python, whatever the catalog says")
        self.assertEqual(agent.tc_verbs(s, "node", {"source": {"kind": "tarball"}}, "install"), ["install"], "not there yet")
        self.assertEqual(agent.tc_verbs(s, "android:emulator", {"source": {"package": "emulator"}, "updatable": True}, "install"),
                         ["update"], "sdkmanager updates an installed android package")
        self.assertEqual(agent.tc_verbs(s, "android:platforms", {"source": {"package": "platforms", "versioned": True}}, "install"),
                         ["install"], "a new level installs beside the old")

    def test_nothing_running_from_it_is_free(self):
        self.assertEqual(agent.tc_users(os.path.join(self.store, "android", "emulator")), [])


if __name__ == "__main__":
    unittest.main()
