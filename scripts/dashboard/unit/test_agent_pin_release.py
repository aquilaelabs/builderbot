"""An agent the vendor installs as a release folder (Codex CLI: bin/codex,
bin/codex-code-mode-host, codex-resources) is pinned whole, with the command
and its helpers links into it, so it finds its helpers beside itself (B247:
only bin/codex was copied, and every command a Codex session ran failed)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agentpkg  # noqa: E402
agent = agentpkg.load("builderbot_agent_pin_release")


def release(root, version):
    os.makedirs(os.path.join(root, "bin"))
    os.makedirs(os.path.join(root, "codex-resources"))
    for f in ("codex", "codex-code-mode-host"):
        with open(os.path.join(root, "bin", f), "w") as fh:
            fh.write(f"#!/bin/sh\necho {f} {version}\n")
        os.chmod(os.path.join(root, "bin", f), 0o755)
    with open(os.path.join(root, "codex-resources", "rg"), "w") as fh:
        fh.write("rg")


class PinRelease(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pin = os.path.join(self.tmp, "agents", "codex")
        os.makedirs(self.pin)
        p = mock.patch("os.lchown")
        p.start()
        self.addCleanup(p.stop)

    def test_the_whole_release_is_pinned_and_the_helper_sits_beside_the_command(self):
        src = os.path.join(self.tmp, "rel1")
        release(src, "0.163.0")
        agent._pin_release(self.pin, "codex", src)
        for f in ("codex", "codex-code-mode-host"):
            self.assertTrue(os.path.islink(os.path.join(self.pin, f)), f)
            self.assertTrue(os.access(os.path.join(self.pin, f), os.X_OK), f)
        real = os.path.realpath(os.path.join(self.pin, "codex"))
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(real), "codex-code-mode-host")))
        self.assertTrue(os.path.exists(os.path.join(self.pin, "release", "codex-resources", "rg")))

    def test_an_update_replaces_the_release_whole(self):
        a, b = os.path.join(self.tmp, "rel1"), os.path.join(self.tmp, "rel2")
        release(a, "0.163.0")
        release(b, "0.164.0")
        agent._pin_release(self.pin, "codex", a)
        agent._pin_release(self.pin, "codex", b)
        with open(os.path.join(self.pin, "codex")) as fh:
            self.assertIn("0.164.0", fh.read())
        self.assertFalse(os.path.exists(os.path.join(self.pin, ".release.old")))
        self.assertFalse(os.path.exists(os.path.join(self.pin, ".release.new")))


if __name__ == "__main__":
    unittest.main()
