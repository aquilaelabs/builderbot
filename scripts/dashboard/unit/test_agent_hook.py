"""bb-agent-hook (R95 step 6): Codex's and Copilot's hooks hold Claude's
guards. Their payloads said again in Claude Code's shape, the same hooks run
in the same order, and a refusal answered in each agent's own way; against
stand-in hooks, never the real controller."""
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "bb-agent-hook")


def load():
    loader = importlib.machinery.SourceFileLoader("bb_agent_hook", PATH)
    spec = importlib.util.spec_from_loader("bb_agent_hook", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


class Shape(unittest.TestCase):
    def setUp(self):
        self.h = load()

    def test_a_codex_shell_call_reads_as_bash_and_its_script(self):
        got = self.h.as_claude("codex", {"tool_name": "shell", "tool_input": {"command": ["bash", "-lc", "git push --force"]}})
        self.assertEqual((got["tool_name"], got["tool_input"]), ("Bash", {"command": "git push --force"}))

    def test_a_codex_patch_reads_as_an_edit_of_its_file(self):
        got = self.h.as_claude("codex", {"tool_name": "apply_patch",
                                         "tool_input": {"input": "*** Begin Patch\n*** Update File: src/a.py\n@@\n"}})
        self.assertEqual((got["tool_name"], got["tool_input"]), ("Edit", {"file_path": "src/a.py"}))

    def test_a_copilot_call_comes_in_camel_case(self):
        got = self.h.as_claude("copilot", {"sessionId": "s1", "toolName": "bash", "toolArgs": json.dumps({"command": "ls"}),
                                           "cwd": "/w"})
        self.assertEqual((got["session_id"], got["tool_name"], got["tool_input"], got["cwd"]),
                         ("s1", "Bash", {"command": "ls"}, "/w"))


class Runs(unittest.TestCase):
    def setUp(self):
        self.h = load()
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.log = os.path.join(self.d, "log")
        # A stand-in for every hook: records its argv and what it read, and
        # refuses a command with "rm -rf" in it the way bb-rule-hook does.
        stub = os.path.join(self.d, "hook")
        with open(stub, "w") as f:
            f.write("#!/usr/bin/env python3\nimport json, sys\nd = json.load(sys.stdin)\n"
                    f"open({self.log!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
                    "if sys.argv[1:2] == ['guard'] and 'rm -rf' in (d.get('tool_input') or {}).get('command', ''):\n"
                    "    print('a rule refuses rm -rf here', file=sys.stderr); sys.exit(2)\n"
                    "if sys.argv[1:2] == ['prompt']:\n"
                    "    print(json.dumps({'hookSpecificOutput': {'additionalContext': 'RULE TEXT'}}))\n")
        os.chmod(stub, 0o755)
        for k in ("GATE", "NOTE", "RELAY", "CHECK", "RULE"):
            setattr(self.h, k, stub)

    def call(self, agent, event, payload, env=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {"BB_PROJECT": "alpha", "BB_AGENT_WHO": "u_0123abcd"}), \
                mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = self.h.main([agent, event])
        return code, out.getvalue(), err.getvalue()

    def ran(self):
        with open(self.log) as f:
            return [l.split()[:2] for l in f.read().splitlines()]

    def test_codex_runs_the_gate_then_the_rule_guard_and_a_refusal_is_exit_2(self):
        code, out, err = self.call("codex", "pre", {"tool_name": "shell", "tool_input": {"command": ["bash", "-lc", "rm -rf /"]}})
        self.assertEqual((code, err.strip()), (2, "a rule refuses rm -rf here"))
        self.assertEqual(self.ran(), [["alpha", "u_0123abcd"], ["guard", "alpha"]])

    def test_copilot_is_told_deny_in_its_own_words(self):
        code, out, _ = self.call("copilot", "pre", {"toolName": "bash", "toolArgs": {"command": "rm -rf build"}})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"permissionDecision": "deny", "permissionDecisionReason": "a rule refuses rm -rf here"})

    def test_an_edit_is_noted_and_a_plain_command_passes(self):
        self.assertEqual(self.call("codex", "pre", {"tool_name": "apply_patch", "tool_input": "*** Update File: a.py\n"})[0], 0)
        self.assertEqual(self.ran()[-1][0], "alpha")
        self.assertEqual(len(self.ran()), 2)

    def test_a_prompt_runs_the_relay_the_rules_and_the_turn_and_passes_on_what_they_said(self):
        code, out, _ = self.call("codex", "prompt", {"prompt": "hello"})
        self.assertEqual(code, 0)
        self.assertEqual([r[0] for r in self.ran()], ["alpha", "prompt", "--turn"])
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["additionalContext"], "RULE TEXT")

    def test_outside_a_builderbot_session_nothing_runs(self):
        self.assertEqual(self.call("codex", "pre", {"tool_name": "shell", "tool_input": {"command": "rm -rf /"}}, env={"BB_PROJECT": ""})[0], 0)
        self.assertFalse(os.path.exists(self.log))


if __name__ == "__main__":
    unittest.main()
