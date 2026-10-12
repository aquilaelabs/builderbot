"""R200: a session is held to its house rules by more than reading them.

The shell reader (scripts/lib/cmdmatch.py) that decides what a Bash call
runs; a rule that refuses, and the briefing's never-do lines, through
bb-rule-hook guard; a project rule that replaces a global one; the named
rules a prompt fires remembered for the conversation and said again by
bb-rule-hook recall after a summary; and the hook endpoint a node's
session asks (hooks.py), which now carries the rules (B686).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.join(HERE, "..")
LIB = os.path.join(DASH, "..", "lib")
sys.path.insert(0, DASH)
sys.path.insert(0, LIB)
import cmdmatch  # noqa: E402
import hooks  # noqa: E402
import rules  # noqa: E402


def write_json(p, d):
    with open(f"{p}.new", "w") as f:
        json.dump(d, f)
    os.replace(f"{p}.new", p)


class Reading(unittest.TestCase):
    PATS = ["apt install", "apt-get install", "pkill -f", "emulator -avd", "git config user.name"]

    def hit(self, line):
        m = cmdmatch.first_match(line, self.PATS)
        return m[1] if m else None

    def test_a_command_is_read_where_it_runs(self):
        for line, want in [
                ("sudo apt install jq", "apt install"),
                ("sudo -u root apt-get install -y jq && echo ok", "apt-get install"),
                ("ls | xargs echo; pkill -f node", "pkill -f"),
                ("echo $(apt install x)", "apt install"),
                ("X=1 timeout 30 apt install q", "apt install"),
                ("bash -c 'apt install jq'", "apt install"),
                ("bb run -- apt install foo", "apt install"),
                ("$ANDROID_HOME/emulator/emulator -avd x &", "emulator -avd"),
                ("git config user.name x", "git config user.name")]:
            self.assertEqual(self.hit(line), want, line)

    def test_words_that_are_data_are_not_commands(self):
        for line in ['grep "apt install" notes.md', "pkill -x node", "apt list --installed",
                     'git commit -m "pkill -f is bad"', "cat <<EOF > f\napt install jq\nEOF\nls",
                     "ls # pkill -f x", 'echo "unbalanced']:
            self.assertIsNone(self.hit(line), line)


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = self.tmp.name
        rules.configure(write_json=write_json, state=self.state)
        self.env = {**os.environ, "DASHBOARD_STATE": self.state, "BUILDERBOT_ROLE": "",
                    "XDG_CACHE_HOME": os.path.join(self.state, "cache"), "BB_ACCOUNT_UID": "u_t"}

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, *argv, stdin):
        r = subprocess.run([sys.executable, os.path.join(DASH, argv[0]), *argv[1:]],
                           input=json.dumps(stdin), capture_output=True, text=True, env=self.env, timeout=30)
        return r.stdout

    def test_the_shipped_install_rule_refuses_and_says_why(self):
        out = self.hook("bb-rule-hook", "guard", "alpha", "u_t",
                        stdin={"tool_name": "Bash", "tool_input": {"command": "sudo apt-get install -y jq"}})
        said = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(said["permissionDecision"], "deny")
        self.assertIn("ask-do-not-install", said["permissionDecisionReason"])
        self.assertIn("installing is the operator's", said["permissionDecisionReason"])
        self.assertEqual(self.hook("bb-rule-hook", "guard", "alpha", "u_t",
                                   stdin={"tool_name": "Bash", "tool_input": {"command": "ls -la"}}), "")

    def test_a_dry_run_is_an_exception_and_a_scratch_identity_is_let_be(self):
        self.assertIsNone(rules.refusing("alpha", "apt-get install -s nvidia-driver-595"))
        self.assertIsNotNone(rules.refusing("alpha", "apt-get install -y nvidia-driver-595"))
        self.assertIsNone(rules.refusing("alpha", "git config user.email t@t"))
        self.assertIsNotNone(rules.refusing("alpha", "git config --global user.email me@x"))

    def test_turned_off_it_refuses_nothing_and_the_briefing_lines_still_do(self):
        rules.set_project_off("alpha", ["ask-do-not-install"])
        self.assertIsNone(rules.refusing("alpha", "apt install jq"))
        self.assertEqual(rules.refusing("alpha", "pkill -f node")[0]["name"], "pkill-by-pid")

    def test_an_operator_rule_refuses_what_it_names(self):
        rules.add("alpha", "builds", "Build with bb build.", by="you", refuse="./gradlew assemble, make")
        g, cmd = rules.refusing("alpha", "cd app && ./gradlew assemble --info")
        self.assertEqual((g["name"], cmd), ("builds", "./gradlew assemble --info"))
        self.assertIsNone(rules.refusing("alpha", "./gradlew test"))
        self.assertIn("a command it names is refused", rules.block("alpha"))

    def test_a_project_rule_replaces_the_global_one_it_names(self):
        self.assertIn("side-quests", [r["name"] for r in rules.effective("alpha")])
        r = rules.add("alpha", "bugs-met", "File it and fix it.", by="you", replaces="side-quests")
        self.assertTrue(r.get("ok"), r)
        names = [r["name"] for r in rules.effective("alpha")]
        self.assertNotIn("side-quests", names)
        self.assertIn("side-quests", [r["name"] for r in rules.effective("beta")])
        self.assertIn("in place of the global rule side-quests", rules.block("alpha"))
        self.assertIn("no global rule", rules.add("alpha", "x", "y", by="you", replaces="nope")["error"])

    def test_a_fired_rule_is_said_and_said_again_after_a_summary(self):
        rules.add("alpha", "agent-compat", "Add, do not change.", by="you", words="agent")
        out = self.hook("bb-prompt-relay", "alpha", "u_t",
                        stdin={"prompt": "look at the agent", "session_id": "conv-1"})
        self.assertIn("Add, do not change.", out)
        again = json.loads(self.hook("bb-rule-hook", "recall", "alpha", "u_t",
                                     stdin={"source": "compact", "session_id": "conv-1"}))
        ctx = again["hookSpecificOutput"]["additionalContext"]
        self.assertIn("summarized", ctx)
        self.assertIn("Add, do not change.", ctx)
        self.assertEqual(self.hook("bb-rule-hook", "recall", "alpha", "u_t",
                                   stdin={"source": "compact", "session_id": "conv-2"}), "")

    def test_the_node_endpoint_carries_the_rules(self):
        rules.add("alpha", "agent-compat", "Add, do not change.", by="you",
                  words="agent", paths="scripts/agent")

        class Overlap:
            others_touching = staticmethod(lambda *a: [])
            note = staticmethod(lambda *a: None)

        class Users:
            load = staticmethod(lambda: {"users": {"t": {"uid": "u_t"}}})

        class Quiet:
            catchup = staticmethod(lambda *a: "")
            settled_line = staticmethod(lambda *a: "")

        hooks.configure(users=Users, rules=rules, overlap=Overlap, roadmap=Quiet, pending=Quiet,
                        seen_note=lambda *a, **k: "")
        got, _ = hooks.verb("note", {"path": "scripts/agent/x.py"}, {}, "u_t", "alpha")
        self.assertIn("Add, do not change.", got["rules"])
        self.assertEqual(got["names"], ["agent-compat"])
        got, _ = hooks.verb("seen", {"prompt": "the agent again"}, {}, "u_t", "alpha")
        self.assertEqual(got["names"], ["agent-compat"])
        got, _ = hooks.verb("guards", {}, {}, "u_t", "alpha")
        self.assertIn("pkill-by-pid", [g["name"] for g in got["guards"]])
        got, _ = hooks.verb("recall", {"names": ["agent-compat"]}, {}, "u_t", "alpha")
        self.assertIn("summarized", got["rules"])


if __name__ == "__main__":
    unittest.main()
