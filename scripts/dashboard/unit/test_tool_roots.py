"""Where the controller finds a toolchain to run (B231): its own scope in the
store first, then each node's beside it, and only one that runs here, since
toolchains are installed on nodes and never on the controller."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402


def tool(path, code):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nexit {code}\n")
    path.chmod(0o755)


class Roots(unittest.TestCase):
    def setUp(self):
        self.store = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.store, True)
        (self.store / "linux-x86_64").mkdir()
        tool(self.store / "n_bad" / "jdk" / "bin" / "java", 1)
        tool(self.store / "n_good" / "jdk" / "bin" / "java", 0)
        saved = list(toolchains._sdk_root_cache)
        self.addCleanup(lambda: toolchains._sdk_root_cache.__setitem__(slice(None), saved))
        toolchains._sdk_root_cache[:] = [str(self.store / "linux-x86_64")]
        toolchains._runs.clear()

    def test_a_node_s_jdk_that_runs_here_and_not_one_that_does_not(self):
        self.assertEqual(toolchains.tool_roots(os.path.join("jdk", "bin", "java")), [str(self.store / "n_good")])

    def test_the_controller_s_own_scope_comes_first(self):
        tool(self.store / "linux-x86_64" / "jdk" / "bin" / "java", 0)
        toolchains._runs.clear()
        got = toolchains.tool_roots(os.path.join("jdk", "bin", "java"))
        self.assertEqual(got[0], str(self.store / "linux-x86_64"))


if __name__ == "__main__":
    unittest.main()
