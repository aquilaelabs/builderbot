"""A toolchain directory without the tool its layout runs is not installed
(diagnostics #124): half of flutter with no bin/flutter was listed, and
`flutter` was then not found by the session that trusted the list."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agentpkg  # noqa: E402
agent = agentpkg.load("store_toolless")


class Toolless(unittest.TestCase):
    def store(self, files):
        root = tempfile.mkdtemp()
        for f in files:
            os.makedirs(os.path.dirname(os.path.join(root, f)), exist_ok=True)
            open(os.path.join(root, f), "w").close()
        saved = agent.tc_root
        self.addCleanup(lambda: setattr(agent, "tc_root", saved))
        agent.tc_root = lambda state: root
        return agent.store_dirs({})

    def test_a_directory_without_its_tool_is_incomplete(self):
        got = self.store(["flutter/docs/README.md", "go/bin/go"])
        self.assertIn("flutter", got.get("incomplete", []))
        self.assertNotIn("go", got.get("incomplete", []))

    def test_a_whole_one_is_not(self):
        got = self.store(["flutter/bin/flutter"])
        self.assertNotIn("flutter", got.get("incomplete", []))


if __name__ == "__main__":
    unittest.main()
