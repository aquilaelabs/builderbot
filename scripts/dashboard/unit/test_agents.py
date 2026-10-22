"""agents.py: the table of coding agents (R95 step 1). Claude's adapter is
the one live row, and every name and argument reads as it did before the
table; the page's copy (page-agents.js) and the node agent's prefixes are
held to the table here."""
import json
import os
import re
import sys
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import agents  # noqa: E402
import idle  # noqa: E402
import names  # noqa: E402
import projsessions  # noqa: E402
sys.path.insert(0, HERE)
import agentpkg  # noqa: E402

node = agentpkg.load("builderbot_agent")


class Table(unittest.TestCase):
    def test_four_agents_with_claude_first_and_the_open_one_not_live_yet(self):
        self.assertEqual([a.id for a in agents.TABLE], ["claude", "codex", "copilot", "open"])
        self.assertEqual([a.id for a in agents.live()], ["claude", "codex", "copilot"])
        self.assertIs(agents.default(), agents.get("claude"))

    def test_every_row_is_well_formed(self):
        ids = set()
        for a in agents.TABLE:
            self.assertRegex(a.id, r"^[a-z]+$")
            self.assertNotIn(a.id, ids)
            ids.add(a.id)
            self.assertIn(a.briefing, agents.BRIEFING)
            self.assertIn(a.guards, agents.GUARDS)
            self.assertIn(a.state, agents.STATES)
            self.assertTrue(a.name and a.product and a.command and a.update_job)
            # No session prefix is another's prefix, so no name reads as two.
            for b in agents.TABLE:
                if b is not a:
                    self.assertFalse(b.session.startswith(a.session))
            # A sign-in is both halves or neither.
            self.assertEqual(bool(a.login_job), bool(a.logout_job))
            self.assertEqual(bool(a.login_job), bool(a.provider))

    def test_claude_is_named_as_it_always_was(self):
        c = agents.get("claude")
        self.assertEqual((c.arg, c.session, c.command, c.reported),
                         ("claude:", "claude-", "claude", "claude"))
        self.assertEqual((c.update_job, c.login_job, c.logout_job),
                         ("claude-update", "claude-login", "claude-logout"))
        self.assertEqual(c.transcripts, ".claude/projects")


class Names(unittest.TestCase):
    def test_a_session_name_reads_back_its_agent_and_project(self):
        a, stem = agents.of_session("claude-alpha")
        self.assertEqual((a.id, stem), ("claude", "alpha"))
        self.assertEqual(agents.of_session("shell-alpha"), (None, ""))
        self.assertEqual(agents.of_session("claude-"), (None, ""))
        self.assertEqual(agents.of_session(""), (None, ""))

    def test_a_planned_agent_s_names_are_not_read_as_its_yet(self):
        # A scratch session somebody called open-x stays a scratch session
        # until the open agent is wired.
        self.assertEqual(agents.of_session("open-alpha"), (None, ""))
        self.assertEqual(agents.of_arg("open:alpha"), (None, ""))
        self.assertFalse(idle.is_claude("open-alpha"))

    def test_codex_and_copilot_sessions_are_read_as_theirs(self):
        a, stem = agents.of_session("codex-alpha")
        self.assertEqual((a.id, stem), ("codex", "alpha"))
        self.assertEqual(agents.of_arg("copilot:alpha")[0].id, "copilot")
        self.assertTrue(idle.is_claude("u_0123abcd~copilot-alpha"))

    def test_an_argument_reads_back_its_agent_and_project(self):
        a, rest = agents.of_arg("claude:alpha:r:abc-123:n:n1")
        self.assertEqual((a.id, rest), ("claude", "alpha:r:abc-123:n:n1"))
        self.assertEqual(agents.project_of_arg("claude:alpha:r:abc"), "alpha")
        self.assertEqual(agents.project_of_arg("shell:alpha"), "")

    def test_the_session_name_is_what_tmux_calls_it(self):
        self.assertEqual(agents.session_name("claude", "ex.ample:x"), "claude-ex_ample_x")
        self.assertEqual(names.claude_session("ex.ample"), "claude-ex_ample")
        self.assertEqual(names.agent_session("claude", "a"), "claude-a")

    def test_the_idle_rule_reads_an_account_s_agent_session(self):
        self.assertTrue(idle.is_claude("claude-alpha"))
        self.assertTrue(idle.is_claude("u_0123abcd~claude-alpha"))
        self.assertFalse(idle.is_claude("u_0123abcd~shell-alpha"))
        self.assertFalse(idle.is_claude("shell-claude-alpha"))


class Asker(unittest.TestCase):
    """The dials hold for every agent's session alike; which agent asked is
    named on the record beside `by`, for display (the operator, 22 Oct)."""

    def test_a_session_s_record_names_its_agent(self):
        with unittest.mock.patch.dict(os.environ, {"BB_AGENT": "codex"}):
            self.assertEqual(agents.asker("claude"), {"agent": "codex"})
            self.assertEqual(agents.asker("you"), {})

    def test_no_agent_or_an_unknown_one_adds_nothing(self):
        with unittest.mock.patch.dict(os.environ, {"BB_AGENT": "nonsense"}):
            self.assertEqual(agents.asker("claude"), {})
        env = {k: v for k, v in os.environ.items() if k != "BB_AGENT"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(agents.asker("claude"), {})

    def test_a_held_change_names_the_agent_that_asked(self):
        import pending
        import tempfile
        import statefile
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        pending.configure(write_json=statefile.write_json, state=d)
        with unittest.mock.patch.dict(os.environ, {"BB_AGENT": "copilot"}):
            r = pending.hold("alpha", "roadmap", "add", {}, "an item", number=3)
        self.assertEqual((r["held"]["by"], r["held"]["agent"]), ("claude", "copilot"))
        self.assertIn("Agents may: Add to roadmap", pending.refusal("roadmap"))


class Transcripts(unittest.TestCase):
    """bb transcripts (the operator, 22 Oct): the asking account's own
    conversations on the project, each marked with its agent, and never
    another account's."""

    def test_an_account_lists_its_own_marked_with_the_agent(self):
        import tempfile
        import transcripts
        root = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, root, True)
        ws = os.path.join(root, "ws")
        homes = {u: os.path.join(root, "share", u, "projects") for u in ("u_0000aaaa", "u_0000bbbb")}
        transcripts.configure(workspace=ws, root_for=lambda uid: homes[uid])
        for uid, sid in (("u_0000aaaa", "mine-1"), ("u_0000bbbb", "theirs-1")):
            d = os.path.join(homes[uid], (ws + "/alpha").replace("/", "-"))
            os.makedirs(d)
            with open(os.path.join(d, sid + ".jsonl"), "w") as f:
                f.write('{"type":"user","message":{"content":"hello"}}\n')
        rows = transcripts.mine("u_0000aaaa", ["alpha"])
        self.assertEqual([(r["id"], r["agent"]) for r in rows], [("mine-1", "claude")])
        self.assertIsNone(transcripts.raw("u_0000aaaa", "alpha", "theirs-1"))


class Briefing(unittest.TestCase):
    """R95 step 5: one briefing for every agent, named where it matters."""

    def test_another_agent_is_told_what_it_is_ahead_of_the_block(self):
        import preamble
        self.assertEqual(preamble.for_agent("claude", "BODY"), "BODY")
        self.assertEqual(preamble.for_agent("", "BODY"), "BODY")
        got = preamble.for_agent("copilot", "BODY")
        self.assertTrue(got.startswith("This session runs Copilot CLI, BuilderBot's Copilot agent."))
        self.assertTrue(got.endswith("\n\nBODY"))
        self.assertEqual(preamble.for_agent("codex", ""), "")


class State(unittest.TestCase):
    """R95 step 7: another agent's session says working, waiting and asking
    through its hooks, and its turn is its own beside a Claude one's."""

    def test_a_turn_marks_it_working_and_its_end_waiting_under_its_own_name(self):
        import hooks
        keep = {k: getattr(hooks, k) for k in ("users", "agent_state", "turn_scope", "asking_set", "asking_clear")}
        self.addCleanup(lambda: hooks.configure(**keep))
        said, scoped, asked = [], [], []
        users_stub = type("U", (), {"load": staticmethod(lambda: {"users": {}})})
        hooks.configure(users=users_stub, agent_state=lambda *a: said.append(a),
                        turn_scope=lambda p, u, a="claude": scoped.append(a) or None,
                        asking_set=lambda *a: asked.append(a), asking_clear=lambda *a: asked.append(("clear",) + a))
        self.assertEqual(hooks.verb("turn", {"agent": "codex"}, {}, "u_0123abcd", "alpha"), ({"ok": True, "go": True}, 200))
        hooks.verb("turn-done", {"agent": "codex"}, {}, "u_0123abcd", "alpha")
        hooks.verb("asking", {"agent": "copilot", "text": "may I?"}, {}, "u_0123abcd", "alpha")
        hooks.verb("turn", {}, {}, "u_0123abcd", "alpha")
        self.assertEqual(said, [("alpha", "u_0123abcd", "codex", "working"), ("alpha", "u_0123abcd", "codex", "waiting")])
        self.assertEqual(scoped, ["codex", "codex", "claude"])
        self.assertIn(("clear", "alpha", "u_0123abcd", "codex"), asked)
        self.assertIn(("alpha", "u_0123abcd", "may I?", "copilot"), asked)


class ByPath(unittest.TestCase):
    """bb loads the notebook's modules by path (lib/dash.py), with nothing of
    the dashboard on sys.path: each that reads the agent table finds it."""

    def test_every_module_bb_loads_by_path_loads(self):
        import subprocess
        lib = os.path.join(HERE, "..", "..", "lib")
        for m in ("prefs", "pending", "rules", "testreg", "bugs", "roadmap", "memory", "nodes"):
            code = f"import sys; sys.path.insert(0, {lib!r}); import dash; dash.load({m!r}, {os.path.join(HERE, '..')!r})"
            p = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd="/")
            self.assertEqual(p.returncode, 0, (m, p.stderr[-300:]))


class OtherTranscripts(unittest.TestCase):
    """R95 step 8: Codex's and Copilot's logs, kept by their Stop hook in
    an <agent>/ folder of the tree's transcripts folder, listed, read and
    shown as Claude's are, each marked with its agent."""

    CODEX = [
        {"timestamp": "2026-10-22T10:00:00Z", "type": "session_meta", "payload": {"cwd": "/w"}},
        {"timestamp": "2026-10-22T10:00:01Z", "type": "response_item",
         "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>x</environment_context>"}]}},
        {"timestamp": "2026-10-22T10:00:02Z", "type": "response_item",
         "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Make the page blue"}]}},
        {"timestamp": "2026-10-22T10:00:03Z", "type": "response_item",
         "payload": {"type": "function_call", "name": "shell", "call_id": "c1",
                     "arguments": json.dumps({"command": ["bash", "-lc", "bb roadmap"]})}},
        {"timestamp": "2026-10-22T10:00:04Z", "type": "response_item",
         "payload": {"type": "function_call_output", "call_id": "c1", "output": {"output": "R1 the page"}}},
        {"timestamp": "2026-10-22T10:00:05Z", "type": "response_item",
         "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done."}]}},
    ]
    COPILOT = [
        {"type": "user.message", "data": {"content": "Fix the build"}, "timestamp": "2026-10-22T11:00:00Z"},
        {"type": "tool.execution_start", "data": {"toolName": "bash", "toolCallId": "t1", "arguments": {"command": "make"}}},
        {"type": "tool.execution_complete", "data": {"toolCallId": "t1", "result": {"content": "ok"}}},
        {"type": "assistant.message", "data": {"content": "Built."}},
    ]

    def setUp(self):
        import tempfile
        import transcripts
        self.t = transcripts
        self.root = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.root, True)
        self.ws = os.path.join(self.root, "ws")
        self.home = os.path.join(self.root, "share", "u_0000aaaa", "projects")
        transcripts.configure(workspace=self.ws, root_for=lambda uid: self.home)

    def put(self, tree, agent, sid, records):
        d = os.path.join(self.home, re.sub(r"[^A-Za-z0-9]", "-", tree), agent)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".jsonl"), "w") as f:
            f.write("\n".join(json.dumps(r) for r in records) + "\n")

    def test_codex_and_copilot_conversations_are_listed_with_their_agent(self):
        self.put(f"{self.ws}/.worktrees/alpha/u_0000aaaa-codex", "codex", "0199aaaa-bbbb-cccc-dddd-eeeeffff0000", self.CODEX)
        self.put(f"{self.ws}/.worktrees/alpha/u_0000aaaa-copilot", "copilot", "cop-1", self.COPILOT)
        rows = {r["id"]: (r["agent"], r["first"]) for r in self.t.mine("u_0000aaaa", ["alpha"])}
        self.assertEqual(rows, {"0199aaaa-bbbb-cccc-dddd-eeeeffff0000": ("codex", "Make the page blue"),
                                "cop-1": ("copilot", "Fix the build")})

    def test_a_codex_conversation_reads_as_turns_and_as_text(self):
        self.put(f"{self.ws}/.worktrees/alpha/u_0000aaaa-codex", "codex", "cx-1", self.CODEX)
        got, st = self.t.turns("u_0000aaaa", "alpha", "cx-1")
        self.assertEqual(st, 200)
        self.assertEqual(got["agent_name"], "ChatGPT")
        self.assertEqual([(t["who"], t["text"]) for t in got["turns"]],
                         [("you", "Make the page blue"), ("claude", ""), ("claude", "Done.")])
        self.assertEqual(got["turns"][1]["tools"][0]["call"], "shell: $ bb roadmap")
        self.assertEqual(got["turns"][1]["tools"][0]["result"], "R1 the page")
        text, name = self.t.render("u_0000aaaa", "alpha", "cx-1")
        self.assertIn("ChatGPT", text)
        self.assertIn("$ bb roadmap", text)
        self.assertTrue(name.startswith("codex-alpha-"))

    def test_the_stop_hook_keeps_the_log_where_the_list_reads_it(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("bbah", os.path.join(HERE, "..", "bb-agent-hook"))
        spec = importlib.util.spec_from_loader("bbah", loader)
        h = importlib.util.module_from_spec(spec)
        loader.exec_module(h)
        src = os.path.join(self.root, "rollout-2026-10-22T10-00-00-0199aaaa-bbbb-cccc-dddd-eeeeffff0001.jsonl")
        with open(src, "w") as f:
            f.write("\n".join(json.dumps(r) for r in self.CODEX) + "\n")
        home = os.path.join(self.root, "home")
        os.makedirs(os.path.join(home, ".claude"))
        os.makedirs(self.home, exist_ok=True)
        os.symlink(self.home, os.path.join(home, ".claude", "projects"))
        tree = f"{self.ws}/.worktrees/alpha/u_0000aaaa-codex"
        with unittest.mock.patch.dict(os.environ, {"BB_TREE": tree, "HOME": home}):
            h.keep("codex", {"transcript_path": src})
        rows = [(r["id"], r["agent"]) for r in self.t.mine("u_0000aaaa", ["alpha"])]
        self.assertEqual(rows, [("0199aaaa-bbbb-cccc-dddd-eeeeffff0001", "codex")])


class Copies(unittest.TestCase):
    def test_the_page_s_table_is_this_one(self):
        with open(os.path.join(HERE, "..", "page-agents.js")) as f:
            src = f.read()
        body = src[src.index("const AGENTS = ["):src.index("];", src.index("const AGENTS = ["))]
        rows = re.findall(r"\{id: \"(\w+)\", name: \"([^\"]+)\", product: \"([^\"]+)\", command: \"(\w+)\", "
                          r"provider: \"([^\"]*)\", live: (true|false)\}", body)
        self.assertEqual(rows, [(a.id, a.name, a.product, a.command, a.provider, "true" if a.live else "false")
                                for a in agents.TABLE])

    def test_each_agent_s_models_are_the_same_in_all_three_places(self):
        with open(os.path.join(HERE, "..", "page-agents.js")) as f:
            js = f.read()
        with open(os.path.join(HERE, "..", "bb-tty")) as f:
            tty = f.read()
        for kind, key in (("MODELS", "models"), ("EFFORTS", "efforts")):
            for ag, xs in getattr(agents, kind).items():
                m = re.search(ag + r": \{models: \[(.*?)\],\s*efforts: \[(.*?)\]\}", js, re.S)
                got = re.findall(r'"([^"]+)"', m.group(1 if key == "models" else 2))
                self.assertEqual(tuple(got), xs, (ag, kind))
                fn = "agent_" + key
                body = tty[tty.index(fn + "() {"):tty.index("}", tty.index(fn + "() {"))]
                m = re.search(ag + r'\) printf %s "([^"]*)"', body)
                self.assertEqual(tuple(m.group(1).split()), xs, (ag, kind))

    def test_the_node_agent_s_prefixes_are_the_live_rows(self):
        self.assertEqual(tuple(node.AGENT_PREFIXES), agents.prefixes())

    def test_each_live_agent_s_launcher_may_be_respawned(self):
        for a in agents.live():
            line = f"/home/x/.cache/builderbot/u/u_0000abcd/project/p/{a.id}-run.sh"
            self.assertIsNotNone(re.fullmatch(node.RESPAWNABLE, line), a.id)
        self.assertIsNone(re.fullmatch(node.RESPAWNABLE, "/home/x/.cache/builderbot/project/p/sh-run.sh"))

    def test_an_agent_s_own_worktree_syncs_as_its_account_s(self):
        import wssync
        self.assertEqual(wssync.worktree_of(".worktrees/alpha/u_0123abcd-codex"), ("alpha", "u_0123abcd", "u_0123abcd-codex"))
        self.assertEqual(wssync.worktree_of(".worktrees/alpha/u_0123abcd"), ("alpha", "u_0123abcd", "u_0123abcd"))
        self.assertIsNone(wssync.worktree_of(".worktrees/alpha/u_0123abcd-Codex"))
        self.assertTrue(node.module("wssync").WT_UNIT.fullmatch(".worktrees/alpha/u_0123abcd-copilot"))


class Sessions(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"name": "claude-alpha", "claude": {"state": "working"}},
            {"name": "u_0123abcd~claude-alpha", "claude": {"state": "asking"}},
            {"name": "shell-alpha"},
            {"name": "shell-alpha-2"},
            {"name": "open-alpha"},
        ]
        projsessions.configure(
            sessions=lambda: self.rows,
            base=lambda n: n.split("~", 1)[1] if "~" in n else n,
            owner=lambda n: n.split("~", 1)[0] if "~" in n else "",
            accounts=lambda: {"u_0123abcd": "bo"}, owner_name=lambda: "al",
            end=lambda name, node: {"ok": True})

    def test_a_project_s_sessions_say_which_agent(self):
        got = [(r["who"], r["kind"], r["agent"]) for r in projsessions.of("alpha")]
        self.assertEqual(got, [("al", "claude", "Claude"), ("al", "shell", ""), ("al", "shell", ""),
                               ("bo", "claude", "Claude")])

    def test_the_maps_count_agent_sessions_as_before(self):
        m = projsessions.maps(self.rows, ["alpha"])
        self.assertEqual(sorted(m["claude_with"]["alpha"]), ["al", "bo"])
        self.assertEqual(m["claude_busy"], {"alpha": ["al"]})
        self.assertEqual(m["claude_asking"], {"alpha": ["bo"]})
        self.assertEqual([w["agent"] for w in m["claude_where"]["alpha"]], ["claude", "claude"])


if __name__ == "__main__":
    unittest.main()
