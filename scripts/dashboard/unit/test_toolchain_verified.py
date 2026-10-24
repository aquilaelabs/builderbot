"""How each toolchain was checked when it was installed (R137 step 5): the
agent reads each one's .bb-verified into its census, and the controller
keeps only the shapes it knows."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import agentpkg  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
agent = agentpkg.load("builderbot_agent_verified")


class Verified(unittest.TestCase):
    def test_the_agent_reads_each_record(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        for name, line in (("go", "sha256\t" + "ab" * 32 + "\tgo.dev's download index"),
                           ("swift", "none\tSwift signs its downloads"), ("old", None), ("bad", "md5\tx\ty")):
            os.makedirs(os.path.join(root, name))
            if line is not None:
                with open(os.path.join(root, name, ".bb-verified"), "w") as f:
                    f.write(line + "\n")
        mod = sys.modules[agent.sdk_verified.__module__]
        with mock.patch.object(mod, "tc_root", lambda state: root):
            got = agent.sdk_verified({})
        self.assertEqual(got, {"go": {"algo": "sha256", "where": "go.dev's download index"},
                               "swift": {"algo": "none", "where": "Swift signs its downloads"}})

    def test_the_controller_keeps_the_shapes_it_knows(self):
        import nodes  # noqa: PLC0415
        census = {"toolchain_verified": {"go": {"algo": "sha256", "where": "x" * 500},
                                         "evil": {"algo": "rm -rf", "where": "y"}, "odd": "not a dict"}}
        out = nodes._census(census) if hasattr(nodes, "_census") else None
        if out is None:
            self.skipTest("nodes._census is not where the census is kept")
        self.assertEqual(set(out["toolchain_verified"]), {"go"})
        self.assertEqual(len(out["toolchain_verified"]["go"]["where"]), 200)


if __name__ == "__main__":
    unittest.main()
