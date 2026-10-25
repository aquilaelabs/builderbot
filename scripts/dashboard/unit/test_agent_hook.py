"""bb-agent-hook (R95 steps 6, 21): Codex's, Copilot's and Grok's hooks hold Claude's
guards. Their payloads said again in Claude Code's shape, the same hooks run
in the same order, and a refusal answered in each agent's own way; against
stand-in hooks, never the real controller."""
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shlex
import shutil
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

    def test_a_grok_call_comes_in_camel_case_with_its_own_tool_names(self):
        got = self.h.as_claude("grok", {"sessionId": "g1", "toolName": "run_terminal_command",
                                        "toolInput": {"command": "ls"}, "cwd": "/w"})
        self.assertEqual((got["session_id"], got["tool_name"], got["tool_input"], got["cwd"]),
                         ("g1", "Bash", {"command": "ls"}, "/w"))
        got = self.h.as_claude("grok", {"toolName": "search_replace", "toolInput": {"file_path": "src/a.rs"}})
        self.assertEqual((got["tool_name"], got["tool_input"]), ("Edit", {"file_path": "src/a.rs"}))

    def test_grok_s_events_are_claude_s_names_without_the_asking_mark(self):
        self.assertEqual(self.h.agent_events("grok"),
                         [["PreToolUse", "pre", 120], ["PostCompact", "recall", 30],
                          ["UserPromptSubmit", "prompt", 900], ["Stop", "stop", 3600]])


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
        # ...under each script's own name, in a directory of its own.
        hooks = os.path.join(self.d, "hooks")
        os.mkdir(hooks)
        for spec in self.h.HOOKS.values():
            for script, *_ in spec["steps"]:
                if not os.path.exists(os.path.join(hooks, script)):
                    os.symlink(stub, os.path.join(hooks, script))
        self.h.HERE = hooks

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

    def test_grok_is_refused_as_claude_is_exit_2_and_the_reason(self):
        code, _, err = self.call("grok", "pre", {"toolName": "run_terminal_command", "toolInput": {"command": "rm -rf build"}})
        self.assertEqual((code, err.strip()), (2, "a rule refuses rm -rf here"))

    def test_an_edit_is_noted_and_a_plain_command_passes(self):
        self.assertEqual(self.call("codex", "pre", {"tool_name": "apply_patch", "tool_input": "*** Update File: a.py\n"})[0], 0)
        self.assertEqual(self.ran()[-1][0], "alpha")
        self.assertEqual(len(self.ran()), 2)

    def test_an_edit_outside_the_sessions_tree_or_to_version_is_walled_as_claudes_are(self):
        env = {"BB_PROJECT": "alpha", "BB_AGENT_WHO": "u_0123abcd", "WORKSPACE": "/workspace",
               "BB_TREE": "/workspace/.worktrees/alpha/codex-u_0123abcd", "BB_CLAUDE_SHARE": "/workspace/.claude"}
        code, _, err = self.call("codex", "pre", {"tool_name": "apply_patch",
                                                  "tool_input": "*** Update File: /workspace/alpha/main.py\n"}, env)
        self.assertEqual(code, 2)
        self.assertIn("outside this session's tree", err)
        code, out, _ = self.call("copilot", "pre", {"toolName": "edit", "toolArgs": {"path": "VERSION"},
                                                    "cwd": env["BB_TREE"]}, env)
        self.assertEqual(json.loads(out)["permissionDecision"], "deny")
        self.assertEqual(self.call("codex", "pre", {"tool_name": "apply_patch",
                                                    "tool_input": "*** Update File: src/a.py\n"}, env)[0], 0)
        self.assertEqual(self.call("codex", "pre", {"tool_name": "apply_patch",
                                                    "tool_input": "*** Add File: /tmp/scratch.txt\n"}, env)[0], 0)

    def test_a_projects_other_repositories_are_its_trees_too(self):
        # R136: a session of a project of several repositories writes in
        # each, as Claude's walls let it, each one's VERSION held.
        env = {"BB_PROJECT": "alpha", "BB_AGENT_WHO": "u_0123abcd", "WORKSPACE": "/workspace",
               "BB_TREE": "/workspace/.worktrees/alpha/codex-u_0123abcd", "BB_CLAUDE_SHARE": "/workspace/.claude",
               "BB_WORKS": "beta", "BB_WORK_DIRS": "/workspace/.worktrees/beta/codex-u_0123abcd "}
        def edit(path):
            return self.call("codex", "pre", {"tool_name": "apply_patch", "tool_input": f"*** Update File: {path}\n"}, env)[0]
        self.assertEqual(edit("/workspace/.worktrees/beta/codex-u_0123abcd/main.py"), 0)
        self.assertEqual(edit("/workspace/beta/main.py"), 0)
        self.assertEqual(edit("/workspace/.worktrees/beta/codex-u_0123abcd/VERSION"), 2)
        self.assertEqual(edit("/workspace/gamma/main.py"), 2, "a project it does not hold is still walled")

    def test_a_copilot_search_runs_the_map_hook_as_claudes_grep_does(self):
        self.assertEqual(self.call("copilot", "pre", {"toolName": "grep", "toolArgs": {"pattern": "def main"}})[0], 0)
        self.assertEqual(self.ran(), [["alpha", "u_0123abcd"], ["map", "alpha"]])

    def test_a_prompt_runs_the_relay_the_rules_and_the_turn_and_passes_on_what_they_said(self):
        code, out, _ = self.call("codex", "prompt", {"prompt": "hello"})
        self.assertEqual(code, 0)
        self.assertEqual([r[0] for r in self.ran()], ["alpha", "prompt", "--turn"])
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["additionalContext"], "RULE TEXT")

    def test_outside_a_builderbot_session_nothing_runs(self):
        self.assertEqual(self.call("codex", "pre", {"tool_name": "shell", "tool_input": {"command": "rm -rf /"}}, env={"BB_PROJECT": ""})[0], 0)
        self.assertFalse(os.path.exists(self.log))



class OneList(unittest.TestCase):
    """Claude's settings, the other agents' hooks files and what their calls
    run all come from HOOKS, so none can hold a guard the others lack."""

    def setUp(self):
        self.h = load()
        self.settings = self.h.claude_settings("alpha", "u_x", self.h.HERE)

    def claude_runs(self, event, tool=None):
        """The commands Claude Code runs for an event and a tool, by its
        settings' own matchers (a regex on the tool name, or the event's)."""
        name, matcher = self.h.HOOKS[event]["claude"]
        out = []
        for group in self.settings.get(name, []):
            m = group.get("matcher")
            if m is not None and m != matcher and not (tool and re.fullmatch(m, tool)):
                continue
            out += [x["command"] for x in group["hooks"]]
        return out

    def test_claude_runs_what_the_other_agents_run_for_every_event_and_tool(self):
        tools = [None, "Bash", "Edit", "Write", "Grep", "Read"]
        for event in self.h.HOOKS:
            for tool in tools if event == "pre" else [None]:
                call = {"tool_name": tool, "tool_input": {"file_path": "/workspace/alpha/a.py"}}
                theirs = [shlex.join(argv) for argv, _t in self.h.plan(event, call, "alpha", "u_x")]
                if tool in ("Write",):
                    # Codex's and Copilot's edits all arrive as Edit (as_claude).
                    continue
                self.assertEqual(sorted(self.claude_runs(event, tool)), sorted(theirs), f"{event} {tool}")

    def test_every_step_is_in_claudes_settings(self):
        said = json.dumps(self.settings)
        for event, spec in self.h.HOOKS.items():
            for script, args, *_ in spec["steps"]:
                argv = self.h._argv(script, args, "alpha", "u_x")
                self.assertIn(shlex.join(argv), said, event)

    def test_each_agent_hooks_file_calls_every_event_it_has(self):
        for agent in ("codex", "copilot"):
            evs = {ev for _n, ev, _t in self.h.agent_events(agent)}
            want = {ev for ev, spec in self.h.HOOKS.items() if agent in spec}
            self.assertEqual(evs, want, agent)
        self.assertEqual({ev for _n, ev, _t in self.h.agent_events("codex")}, set(self.h.HOOKS))

if __name__ == "__main__":
    unittest.main()
