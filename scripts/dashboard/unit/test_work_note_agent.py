"""The work notes are kept per account and coding agent (R95): one person's
Claude and Codex sessions on a project are two sessions, each told when the
other has the file it is about to edit, and each named with its agent."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import overlap  # noqa: E402


def write_json(p, d):
    with open(p, "w") as f:
        json.dump(d, f)


class WorkNoteAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        overlap.configure(state=self.tmp.name, workspace=self.tmp.name, write_json=write_json)

    def test_claude_keeps_the_account_alone_and_another_agent_adds_its_id(self):
        self.assertEqual(overlap.key("u_1"), "u_1")
        self.assertEqual(overlap.key("u_1", "claude"), "u_1")
        self.assertEqual(overlap.key("u_1", "codex"), "u_1/codex")

    def test_one_persons_two_agents_see_each_other(self):
        claude, codex = overlap.key("u_1", "claude"), overlap.key("u_1", "codex")
        overlap.note("alpha", claude, "app/main.py", "run")
        self.assertEqual(overlap.others_touching("alpha", codex, "app/main.py"), [claude])
        self.assertEqual(overlap.others_touching("alpha", claude, "app/main.py"), [])

    def test_the_reader_names_the_person_and_the_agent(self):
        names = {"u_1": "sam"}
        self.assertEqual(overlap.said("u_1", names), "sam (Claude Code)")
        self.assertEqual(overlap.said("u_1/codex", names), "sam (Codex CLI)")
        self.assertEqual(overlap.said("u_1/copilot", names), "sam (Copilot CLI)")
        self.assertEqual(overlap.said("u_2/codex"), "u_2 (Codex CLI)")


if __name__ == "__main__":
    unittest.main()
