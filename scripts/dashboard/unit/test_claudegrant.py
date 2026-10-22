"""claudegrant.py: which nodes each account is signed in to Claude on, as
each node reported it. A login is one account's on one node, so a report
about one node says nothing about another, and the sign-in flow's own rules
(signin.py) about which node it may run on."""
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import claudegrant  # noqa: E402
import signin  # noqa: E402


class Record(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)

    def test_a_fresh_account_is_signed_in_nowhere(self):
        self.assertEqual(claudegrant.nodes_of(self.home), {})
        self.assertEqual(claudegrant.nodes_of(""), {})
        self.assertEqual(claudegrant.on(self.home, "n1"), {})

    def test_a_report_is_about_its_own_node_and_no_other(self):
        self.assertTrue(claudegrant.report(self.home, "n1", "Me@Example.com", "max")["ok"])
        self.assertEqual(claudegrant.on(self.home, "n1")["email"], "Me@Example.com")
        self.assertEqual(claudegrant.on(self.home, "n2"), {})

    def test_each_node_may_be_a_different_anthropic_account(self):
        claudegrant.report(self.home, "n1", "me@example.com", "max")
        self.assertTrue(claudegrant.report(self.home, "n2", "someone@else.com", "pro")["ok"])
        got = claudegrant.nodes_of(self.home)
        self.assertEqual({k: (v["email"], v["plan"]) for k, v in got.items()},
                         {"n1": ("me@example.com", "max"), "n2": ("someone@else.com", "pro")})

    def test_signing_out_on_one_node_leaves_the_other(self):
        claudegrant.report(self.home, "n1", "me@example.com")
        claudegrant.report(self.home, "n2", "me@example.com")
        self.assertTrue(claudegrant.report(self.home, "n1", "", signed_in=False)["ok"])
        self.assertEqual(sorted(claudegrant.nodes_of(self.home)), ["n2"])

    def test_a_sign_out_where_there_was_none_writes_nothing(self):
        self.assertTrue(claudegrant.report(self.home, "n1", "", signed_in=False, agent="codex")["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config", "builderbot", "codex-grant.json")))

    def test_another_agents_sign_in_is_its_own_record(self):
        claudegrant.report(self.home, "n1", "me@example.com", "max")
        claudegrant.report(self.home, "n1", "me@example.com", "plus", agent="codex")
        claudegrant.report(self.home, "n1", "", signed_in=False, agent="codex")
        self.assertEqual(claudegrant.nodes_of(self.home, "codex"), {})
        self.assertEqual(claudegrant.on(self.home, "n1")["plan"], "max")

    def test_an_empty_plan_keeps_the_stored_one_and_the_answer_carries_it(self):
        claudegrant.report(self.home, "n1", "me@example.com", "max")
        self.assertEqual(claudegrant.report(self.home, "n1", "me@example.com")["plan"], "max")
        self.assertEqual(claudegrant.on(self.home, "n1")["plan"], "max")

    def test_another_account_on_the_same_node_does_not_inherit_the_plan(self):
        claudegrant.report(self.home, "n1", "me@example.com", "max")
        self.assertEqual(claudegrant.report(self.home, "n1", "other@example.com")["plan"], "")

    def test_a_report_must_say_its_node_and_account(self):
        self.assertIn("error", claudegrant.report(self.home, "", "me@example.com"))
        self.assertIn("error", claudegrant.report(self.home, "n1", ""))
        self.assertIn("error", claudegrant.report("", "n1", "me@example.com"))

    def test_the_record_is_the_accounts_own(self):
        claudegrant.report(self.home, "n1", "me@example.com")
        mode = stat.S_IMODE(os.stat(os.path.join(self.home, ".claude", claudegrant.MARK)).st_mode)
        self.assertEqual(mode, 0o600)

    def test_a_record_with_the_plan_beside_the_nodes_is_read_once(self):
        os.makedirs(os.path.join(self.home, ".claude"))
        with open(os.path.join(self.home, ".claude", claudegrant.MARK), "w") as f:
            json.dump({"gen": 3, "email": "me@example.com", "plan": "max",
                       "nodes": {"n1": {"email": "me@example.com", "at": 1}}}, f)
        self.assertEqual(claudegrant.on(self.home, "n1")["plan"], "max")
        self.assertEqual(claudegrant.report(self.home, "n1", "me@example.com")["plan"], "max")
        with open(os.path.join(self.home, ".claude", claudegrant.MARK)) as f:
            self.assertEqual(sorted(json.load(f)), ["nodes"])


class UsersTab(unittest.TestCase):
    """Which Anthropic accounts each BuilderBot account is on, and who
    shares one."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.was = claudegrant.home_for
        claudegrant.home_for = lambda uid: os.path.join(self.root, uid)
        self.addCleanup(setattr, claudegrant, "home_for", self.was)

    def test_the_accounts_an_account_is_on_and_who_shares_one(self):
        claudegrant.report(os.path.join(self.root, "a"), "n1", "one@example.com")
        claudegrant.report(os.path.join(self.root, "a"), "n2", "two@example.com")
        claudegrant.report(os.path.join(self.root, "b"), "n1", "Two@example.com")
        os.makedirs(os.path.join(self.root, "c"))
        got = {u["name"]: u for u in claudegrant.logins_of(
            [{"name": "ann", "uid": "a"}, {"name": "bob", "uid": "b"}, {"name": "cy", "uid": "c"}])}
        self.assertEqual(got["ann"]["claude"], "one@example.com, two@example.com")
        self.assertEqual(got["ann"]["claude_shared_with"], ["bob"])
        self.assertEqual(got["bob"]["claude_shared_with"], ["ann"])
        self.assertEqual((got["cy"]["claude"], got["cy"]["claude_shared_with"]), ("", []))
        self.assertNotIn("_emails", got["ann"])


class WhichNode(unittest.TestCase):
    """Where a sign-in or a sign-out may run: a node that answers and runs
    sessions, named by the press."""

    def node(self, **kw):
        return {"id": "n1", "name": "shed", "kind": "agent", "state": "online", "live": True,
                "reported": {"session": {"up": True}}, **kw}

    def test_a_node_that_answers_and_runs_sessions(self):
        self.assertEqual(signin.cannot(self.node()), "")

    def test_no_node_named_or_not_an_agent_node(self):
        self.assertIn("which node", signin.cannot(None))
        self.assertIn("which node", signin.cannot(self.node(kind="local")))

    def test_one_that_is_not_answering(self):
        self.assertIn("not answering", signin.cannot(self.node(live=False)))
        self.assertIn("draining and takes no new work", signin.cannot(self.node(state="draining")))

    def test_one_that_runs_no_sessions(self):
        self.assertIn("runs no sessions", signin.cannot(self.node(reported={})))

    def test_a_flow_is_shown_to_the_account_it_was_started_for(self):
        class Flow:
            uid = "u_aaaaaaaa"

            def state(self):
                return {"running": True, "url": "https://claude.com/x", "node": "n1"}
        was, signin._flow = signin._flow, Flow()
        self.addCleanup(setattr, signin, "_flow", was)
        self.assertTrue(signin.state("u_aaaaaaaa")["running"])
        self.assertEqual(signin.state("u_bbbbbbbb"), {"running": False})
        self.assertEqual(signin.state(""), {"running": False})
        self.assertTrue(signin.state()["running"])


if __name__ == "__main__":
    unittest.main()
