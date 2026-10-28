"""Claude Code is a coding agent of each node (R145, R95): a row on its
Agents page from the census and the latest known, installed on purpose, and
required for a session, which is held where it is missing."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import claudecode  # noqa: E402
import agentcode  # noqa: E402


def node(claude="1.0.0 (Claude Code)", up=True, **kw):
    return {"id": "n1", "name": "clbox", "kind": "agent", "live": True,
            "reported": {"sandbox": True, "session": {"up": up, "claude": claude}}} | kw


class Nodes:
    def __init__(self, n):
        self.n = n

    def node_list(self):
        return [self.n]

    def node(self, nid):
        return self.n

    def jobs_for(self, *a, **k):
        return []


class ClaudeToolchain(unittest.TestCase):
    def setUp(self):
        self.was = claudecode.nodes, agentcode.nodes, agentcode.claudecode, dict(claudecode._latest)
        self.addCleanup(self.restore)
        claudecode._latest.update(version="1.2.0", at=1, error="")

    def restore(self):
        claudecode.nodes, agentcode.nodes, agentcode.claudecode, latest = self.was
        claudecode._latest.clear()
        claudecode._latest.update(latest)

    def use(self, n):
        claudecode.nodes = agentcode.nodes = Nodes(n)
        agentcode.claudecode = claudecode

    def test_a_node_behind_has_a_row_offering_the_update(self):
        self.use(node())
        r = agentcode.claude_row(node())
        self.assertEqual((r["name"], r["installed"], r["latest"], r["state"]), ("claude-code", "1.0.0", "1.2.0", "update"))

    def test_none_installed_is_absent_and_holds_the_nodes_projects(self):
        n = node(claude="")
        self.use(n)
        self.assertEqual(agentcode.claude_row(n)["state"], "absent")
        self.assertIn("Claude Code is not installed on clbox: the Library installs it there",
                      claudecode.holds().get("n1", ""))

    def test_none_installed_does_not_end_a_running_session(self):
        # B540: the sweep ended live sessions on a stale "not installed".
        self.use(node(claude=""))
        self.assertEqual(claudecode.holds(reap=True), {})

    def test_no_session_account_no_row_and_no_hold(self):
        n = node(up=False)
        self.use(n)
        self.assertIsNone(agentcode.claude_row(n))
        self.assertEqual(claudecode.holds(), {})


if __name__ == "__main__":
    unittest.main()
