"""A session's push held for a person (R219): the flagged lines go to the
account whose session pushes, and to the administrators; Approve runs the
push through the relay's own repository with the lines okayed, and the
outcome the waiting bb reads carries the push's apply; Deny runs nothing."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import phone  # noqa: E402

FOUND = [{"path": "config.py", "line": 2, "text": 'TOKEN = "ghp_x"', "kind": "a GitHub token", "key": "k1"},
         {"path": "a.md", "line": 1, "text": "ops@acme.io", "kind": "an email address", "key": "k2"}]


class PushAsk(unittest.TestCase):
    def setUp(self):
        self.ran = []
        self.was = phone.pusher
        phone.pusher = lambda rec, by: (self.ran.append((rec["project"], rec["cwd"], rec["args"], [f["key"] for f in rec["findings"]], by))
                                        or {"code": 0, "out": "pushed\n", "err": "", "apply": {"upstream": [["topic", "origin", "refs/heads/topic"]]}})
        self.addCleanup(setattr, phone, "pusher", self.was)

    def test_it_waits_on_the_asking_account_and_shows_the_lines(self):
        r = phone.ask_push("alpha", "/workspace/alpha", ["origin", "topic"], FOUND, asker_uid="u_00000002", asker_name="ada")
        self.assertTrue(r.get("ok"), r)
        self.assertIn("your own account", r["to"])
        mine = [x for x in phone.requests_open("u_00000002", False) if x["id"] == r["id"]]
        self.assertEqual(mine[0]["kind"], "push")
        self.assertEqual(mine[0]["cmd"], ["git", "push", "origin", "topic"])
        self.assertIn("2 lines look sensitive", mine[0]["why"])
        self.assertIn("config.py:2  (a GitHub token)", mine[0]["detail"])
        self.assertEqual(mine[0]["count"], 2)
        self.assertNotIn("findings", mine[0], "the listing carries the text, not the keys")
        self.assertTrue([x for x in phone.requests_open("u_00000009", True) if x["id"] == r["id"]],
                        "an administrator sees it too")
        self.assertFalse([x for x in phone.requests_open("u_00000009", False) if x["id"] == r["id"]],
                         "another user does not")

    def test_approve_pushes_with_the_lines_okayed_and_hands_back_the_apply(self):
        r = phone.ask_push("alpha", "/workspace/alpha", ["origin", "topic"], FOUND, asker_uid="u_00000002", asker_name="ada")
        self.assertIn("for the account", phone.decide(r["id"], True, "u_00000009", name="bob", admin=False).get("error", ""))
        got = phone.decide(r["id"], True, "u_00000002", name="ada", admin=False)
        self.assertTrue(got.get("ok"), got)
        self.assertEqual(self.ran, [("alpha", "/workspace/alpha", ["origin", "topic"], ["k1", "k2"], "ada")])
        o = phone.outcome(r["id"], "alpha")
        self.assertEqual((o["state"], o["code"], o["out"]), ("done", 0, "pushed\n"))
        self.assertEqual(o["apply"], {"upstream": [["topic", "origin", "refs/heads/topic"]]})
        self.assertIn("no such request", phone.outcome(r["id"], "beta")["error"], "another project cannot read it")

    def test_deny_runs_nothing(self):
        r = phone.ask_push("alpha", "/workspace/alpha", [], FOUND, asker_uid="u_00000002", asker_name="ada")
        phone.decide(r["id"], False, "u_00000002", name="ada", admin=False)
        self.assertEqual(self.ran, [])
        self.assertEqual(phone.outcome(r["id"], "alpha")["state"], "denied")

    def test_nothing_to_ask_about_is_refused(self):
        self.assertIn("nothing", phone.ask_push("alpha", "/w", [], [], asker_uid="u_1")["error"])


if __name__ == "__main__":
    unittest.main()
