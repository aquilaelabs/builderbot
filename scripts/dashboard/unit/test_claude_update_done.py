"""A Claude Code update's row says the new version the moment its job ends
(B249), read off the job's last line, which names the version the way
`claude --version` prints it, its own "(Claude Code)" included (B167)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import claudecode  # noqa: E402


class Nodes:
    def __init__(self, log):
        self.log, self.set = log, []

    def job(self, jid, with_log=False):
        return {"id": jid, "log": self.log, "spec": {}}

    def reported_set(self, nid, key, sub, value):
        self.set.append((nid, key, sub, value))


class UpdateDone(unittest.TestCase):
    def tearDown(self):
        claudecode.nodes = None

    def test_the_version_the_agent_writes_reaches_the_row(self):
        for line, want in (("Claude Code 2.1.306 (Claude Code) is what a session here runs now", "2.1.306"),
                           ("Claude Code 2.1.306 is what a session here runs now", "2.1.306")):
            claudecode.nodes = Nodes("pinned it\n" + line + "\n")
            claudecode.update_done({"id": "j1", "node": "n1"}, "succeeded")
            self.assertEqual(claudecode.nodes.set, [("n1", "session", "claude", f"{want} (Claude Code)")], line)


if __name__ == "__main__":
    unittest.main()
