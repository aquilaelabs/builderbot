"""bb version release's ask (R138): a project on `ask` puts the tag and the
commit it would mark in front of its owner, and only its owner; Approve
runs the release as the Artifacts view's Release does, never the session
itself; the dial is ask unless a project says otherwise."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import phone  # noqa: E402
import prefs  # noqa: E402

PLAN = {"tag": "v0.5.4", "sha": "eb9d75f", "target": "0.5.4"}


class ReleaseAsk(unittest.TestCase):
    def setUp(self):
        self.ran = []
        self.was = phone.releaser
        phone.releaser = lambda project, comp, asker, principal, dev=False: (
            self.ran.append((project, comp, asker, principal) + (("dev",) if dev else ()))
            or ({"released": {"tag": "v0.5.4", "sha": "eb9d75f", "pushed": True,
                              "forge": {"url": "https://github.com/o/app/releases/tag/v0.5.4"}}}, 200))
        self.addCleanup(setattr, phone, "releaser", self.was)

    def test_it_names_the_tag_and_waits_on_the_projects_owner_alone(self):
        r = phone.ask_release("0.5.4 for testers", "app", "", PLAN, "u_00000002", "ada",
                              asker_name="sean", principal="session:app")
        self.assertTrue(r.get("ok"), r)
        mine = [x for x in phone.requests_open("u_00000002", False) if x["id"] == r["id"]]
        self.assertEqual(mine[0]["kind"], "release")
        self.assertEqual((mine[0]["tag"], mine[0]["sha"]), ("v0.5.4", "eb9d75f"))
        self.assertEqual(mine[0]["cmd"], ["version", "release", "v0.5.4 on eb9d75f"])
        self.assertNotIn("principal", mine[0], "the listing never carries who to act as")
        self.assertFalse([x for x in phone.requests_open("u_00000009", True) if x["id"] == r["id"]],
                         "an administrator who does not own the project is not the one asked")

    def test_approve_runs_the_release_and_says_what_it_made(self):
        r = phone.ask_release("0.5.4 for testers", "app", "", PLAN, "u_00000002", "ada",
                              asker_name="sean", principal="session:app")
        got = phone.decide(r["id"], True, "u_00000002", name="ada", admin=False)
        self.assertTrue(got.get("ok"), got)
        self.assertEqual(self.ran, [("app", "", "sean", "session:app")])
        out = phone.outcome(r["id"])["out"]
        self.assertIn("v0.5.4 tagged on eb9d75f and pushed", out)
        self.assertIn("releases/tag/v0.5.4", out)

    def test_a_dev_ask_runs_the_dev_release(self):
        # B453: Approve on a --dev ask cut the plain release.
        r = phone.ask_release("the dev build", "app", "", dict(PLAN, tag="v0.5.4-dev.9"), "u_00000002", "ada",
                              asker_name="sean", principal="session:app", dev=True)
        phone.decide(r["id"], True, "u_00000002", name="ada", admin=False)
        self.assertEqual(self.ran, [("app", "", "sean", "session:app", "dev")])

    def test_deny_runs_nothing(self):
        r = phone.ask_release("0.5.4", "app", "", PLAN, "u_00000002", "ada")
        phone.decide(r["id"], False, "u_00000002", name="ada", admin=False)
        self.assertEqual(self.ran, [])

    def test_a_reason_is_needed(self):
        self.assertIn("--why", phone.ask_release("", "app", "", PLAN, "u_1", "x")["error"])

    def test_the_dial_is_ask_unless_set(self):
        self.assertEqual(prefs._clean({})["release"], "ask")
        self.assertEqual(prefs._clean({"release": "auto"})["release"], "auto")
        self.assertEqual(prefs._clean({"release": "whatever"})["release"], "ask")


if __name__ == "__main__":
    unittest.main()
