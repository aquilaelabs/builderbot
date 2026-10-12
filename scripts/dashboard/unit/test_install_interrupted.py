"""An install cut short never reads as installed, and an aborted batch fails
only what it began (the operator, 12 Oct: Abort on flutter left half of it
reading installed, and the twelve behind it reading failed)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import agentpkg  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
agent = agentpkg.load("builderbot_agent_interrupted")
agent.log = lambda *a, **k: None


class Marker(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def sh(self, script):
        return subprocess.run(["bash", "-c", f'. "{REPO}/scripts/lib/common.sh"; . "{REPO}/scripts/lib/sdk.sh"; {script}'],
                              capture_output=True, text=True, env={**os.environ, "PATH": "/usr/bin:/bin"})

    def test_the_marker_stands_until_the_install_ends_and_clears_a_leftover(self):
        d = os.path.join(self.root, "flutter")
        self.sh(f'sdk_mark_partial "{d}"')
        self.assertTrue(os.path.exists(os.path.join(self.root, ".bb-installing.flutter")), "marked on the way in")
        os.makedirs(os.path.join(d, "bin"))
        r = self.sh(f'sdk_clear_interrupted "{d}"')
        self.assertFalse(os.path.exists(d), r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".bb-installing.flutter")))

    def test_the_agent_does_not_list_a_marked_directory(self):
        st = agent.stores if hasattr(agent, "stores") else __import__("builderbot_agent_interrupted.stores", fromlist=["x"])
        self.addCleanup(st._SCOPE.update, name="")
        st.use_scope(self.root, "n_1234abcd")
        node = os.path.join(self.root, "n_1234abcd")
        os.makedirs(os.path.join(node, "flutter", "bin"))
        os.makedirs(os.path.join(node, "go", "bin"))
        open(os.path.join(node, ".bb-installing.flutter"), "w").close()
        self.assertEqual(st.store_dirs({"stores": {"toolchains": self.root}})["top"], ["go"])


class Tried(unittest.TestCase):
    def test_only_what_the_log_began(self):
        log = "toolchain\n== bb toolchains install node\nok\n== bb toolchains install flutter\n[builderbot] WARN: aborted\n"

        class Nodes:
            @staticmethod
            def job(jid, with_log=True):
                return {"log": log}
        saved = toolchains.nodes
        self.addCleanup(setattr, toolchains, "nodes", saved)
        toolchains.nodes = Nodes()
        toolchains._tried_memo.clear()
        self.assertEqual(toolchains._tried("j1"), {"node", "flutter"})


if __name__ == "__main__":
    unittest.main()
