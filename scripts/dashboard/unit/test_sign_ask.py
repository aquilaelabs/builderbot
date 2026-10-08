"""bb sign's ask (R106 step 3): a project on `ask` puts the signing in
front of its owner, and only its owner; Approve starts it as the session's
own; the dial is ask unless a project says otherwise."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import phone  # noqa: E402
import prefs  # noqa: E402


class SignAsk(unittest.TestCase):
    def setUp(self):
        self.started = []
        self.was = phone.signer
        phone.signer = lambda principal, project, file, route, key="": (
            self.started.append((principal, project, file, route)) or ({"ok": True, "job": "j_9"}, 200))
        self.addCleanup(setattr, phone, "signer", self.was)

    def test_it_waits_on_the_projects_owner_alone(self):
        r = phone.ask_sign("for testers", "app", "app-release.apk", "sideload", "u_00000002", "ada",
                           asker_name="sean", principal="session:app")
        self.assertTrue(r.get("ok"), r)
        mine = [x for x in phone.requests_open("u_00000002", False) if x["id"] == r["id"]]
        self.assertEqual(mine[0]["kind"], "sign")
        self.assertEqual(mine[0]["cmd"], ["sign", "app-release.apk", "--for", "sideload"])
        self.assertFalse([x for x in phone.requests_open("u_00000009", True) if x["id"] == r["id"]],
                         "an administrator who does not own the project is not the one asked")

    def test_approve_starts_it_as_the_session_asked(self):
        r = phone.ask_sign("for testers", "app", "app-release.apk", "sideload", "u_00000002", "ada",
                           principal="session:app")
        got = phone.decide(r["id"], True, "u_00000002", name="ada", admin=False)
        self.assertTrue(got.get("ok"), got)
        self.assertEqual(self.started, [("session:app", "app", "app-release.apk", "sideload")])
        self.assertEqual(phone.outcome(r["id"])["out"], "j_9")

    def test_a_reason_is_needed(self):
        self.assertIn("--why", phone.ask_sign("", "app", "a.apk", "sideload", "u_1", "x")["error"])

    def test_the_dial_is_ask_unless_set(self):
        self.assertEqual(prefs._clean({})["sign"], "ask")
        self.assertEqual(prefs._clean({"sign": "auto"})["sign"], "auto")
        self.assertEqual(prefs._clean({"sign": "whatever"})["sign"], "ask")


if __name__ == "__main__":
    unittest.main()
