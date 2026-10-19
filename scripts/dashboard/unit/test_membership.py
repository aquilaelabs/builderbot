"""membership.py: every project has an owner; an invite-only project's
people are its owner's (and BuilderBot's owner's) to change, so an
administrator cannot add themselves; people join by accepting an
invitation from their bell; BuilderBot's owner can always add itself."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import membership  # noqa: E402
import users  # noqa: E402


def write_json(path, d):
    Path(path).write_text(json.dumps(d))


class Membership(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        write_json(self.tmp / "users.json", {"users": {
            "sean": {"role": "owner", "uid": "u_00000001", "projects": ["*"]},
            "ada": {"role": "admin", "uid": "u_00000002", "projects": ["app"]},
            "bob": {"role": "admin", "uid": "u_00000003", "projects": []},
            "cy": {"role": "user", "uid": "u_00000004", "projects": []}}})
        users.configure(state=self.tmp, write_json=write_json)
        membership.configure(state=self.tmp, write_json=write_json)
        import roles
        roles.configure(state=self.tmp, write_json=write_json)
        # An invitation names the role it offers, a role on a project (R155).
        roles.set_role("dev", "projects", {"projects": "write"})
        membership.on_create("app", "ada")

    def me(self, name):
        return users.get(name)

    def test_whoever_made_it_owns_it_and_an_old_one_is_the_owners(self):
        self.assertEqual(membership.owner_of("app"), "u_00000002")
        self.assertEqual(membership.owner_of("older"), "u_00000001")

    def test_an_open_project_takes_any_administrator(self):
        self.assertEqual(membership.member_refusal(self.me("bob"), "app"), "")
        self.assertNotEqual(membership.member_refusal(self.me("cy"), "app"), "")
        # A plain account is refused for what it is, not told the project
        # is invite only when it is not (B36).
        self.assertNotIn("invite only", membership.member_refusal(self.me("cy"), "app"))
        self.assertIn("ada", membership.member_refusal(self.me("cy"), "app"))

    def test_invite_only_keeps_administrators_out_but_not_the_owners(self):
        r, st = membership.set_owner(self.me("ada"), "app", restrict=True)
        self.assertEqual(st, 200, r)
        self.assertIn("invite only", membership.member_refusal(self.me("bob"), "app"))
        self.assertEqual(membership.member_refusal(self.me("ada"), "app"), "")
        self.assertEqual(membership.member_refusal(self.me("sean"), "app"), "")
        # ...and through the Users tab's own verb, an administrator adding
        # themselves is refused there.
        bob = self.me("bob")
        r = users.verb("projects", {"name": "bob", "projects": ["app"]}, lambda: {"app"},
                       may_change=lambda p: membership.member_refusal(bob, p))
        self.assertIn("invite only", r.get("error", ""))
        self.assertNotIn("app", users.get("bob")["projects"])

    def test_only_the_owner_or_builderbots_restricts_or_hands_it_on(self):
        self.assertEqual(membership.set_owner(self.me("bob"), "app", restrict=True)[1], 403)
        self.assertEqual(membership.set_owner(self.me("bob"), "app", owner="bob")[1], 403)

    def test_builderbots_owner_hands_it_on_at_once(self):
        r, st = membership.set_owner(self.me("sean"), "app", owner="bob")
        self.assertEqual(st, 200, r)
        self.assertEqual(r["owner"], "bob")
        self.assertIsNone(r["offer"])
        self.assertIn("app", users.get("bob")["projects"])

    def test_the_projects_owner_offers_it_and_it_moves_on_acceptance(self):
        r, st = membership.set_owner(self.me("ada"), "app", owner="cy")
        self.assertEqual((st, r["owner"], r["offered"], r["offer"]["name"]), (200, "ada", "cy", "cy"))
        mine = membership.mine(self.me("cy"))
        self.assertEqual([(i["project"], i["kind"], i["by"]) for i in mine], [("app", "owner", "ada")])
        r, st = membership.answer(self.me("cy"), mine[0]["id"], True)
        self.assertEqual((st, r["owner"]), (200, True))
        self.assertEqual(membership.owner_of("app"), "u_00000004")
        self.assertIn("app", users.get("cy")["projects"])

    def test_a_declined_offer_leaves_it_where_it_was(self):
        membership.set_owner(self.me("ada"), "app", owner="cy")
        iid = membership.mine(self.me("cy"))[0]["id"]
        membership.answer(self.me("cy"), iid, False)
        self.assertEqual(membership.owner_of("app"), "u_00000002")

    def test_an_offer_from_somebody_who_no_longer_owns_it_cannot_be_taken(self):
        membership.set_owner(self.me("ada"), "app", owner="cy")
        iid = membership.mine(self.me("cy"))[0]["id"]
        membership.set_owner(self.me("sean"), "app", owner="bob")
        self.assertEqual(membership.answer(self.me("cy"), iid, True)[1], 409)
        self.assertEqual(membership.owner_of("app"), "u_00000003")

    def test_an_invitation_is_accepted_from_the_bell(self):
        membership.set_owner(self.me("ada"), "app", restrict=True)
        self.assertEqual(membership.invite(self.me("bob"), "app", "cy", "dev")[1], 403)
        r, st = membership.invite(self.me("ada"), "app", "cy", "dev")
        self.assertEqual(st, 200, r)
        self.assertEqual(membership.invite(self.me("ada"), "app", "cy", "dev")[1], 400)
        mine = membership.mine(self.me("cy"))
        self.assertEqual([(i["project"], i["by"]) for i in mine], [("app", "ada")])
        self.assertEqual(membership.answer(self.me("bob"), mine[0]["id"], True)[1], 404)
        r, st = membership.answer(self.me("cy"), mine[0]["id"], True)
        self.assertEqual((st, r["joined"]), (200, True))
        self.assertIn("app", users.get("cy")["projects"])
        self.assertEqual(users.get("cy")["project_roles"]["app"], ["dev"], "accepting gives the role it offered")
        self.assertEqual(membership.mine(self.me("cy")), [])

    def test_an_invitation_names_a_role_on_a_project(self):
        self.assertIn("pick the role", membership.invite(self.me("ada"), "app", "cy", "")[0]["error"])
        self.assertIn("pick the role", membership.invite(self.me("ada"), "app", "cy", "nope")[0]["error"])

    def test_declined_and_withdrawn(self):
        membership.invite(self.me("ada"), "app", "bob", "dev")
        iid = membership.mine(self.me("bob"))[0]["id"]
        self.assertEqual(membership.answer(self.me("bob"), iid, False)[0]["joined"], False)
        self.assertNotIn("app", users.get("bob")["projects"])
        membership.invite(self.me("ada"), "app", "cy", "dev")
        iid = membership.mine(self.me("cy"))[0]["id"]
        self.assertEqual(membership.withdraw(self.me("bob"), iid)[1], 403)
        self.assertEqual(membership.withdraw(self.me("ada"), iid)[1], 200)
        self.assertEqual(membership.mine(self.me("cy")), [])

    def test_a_session_does_none_of_it(self):
        sess = {"session": "app", "name": "ada", "uid": "u_00000002", "role": "user"}
        self.assertFalse(membership.may_manage(sess, "app"))
        self.assertEqual(membership.answer(sess, 1, True)[1], 403)

    def test_a_removed_account_takes_its_invitations_and_ownership_with_it(self):
        membership.invite(self.me("ada"), "app", "cy", "dev")
        membership.forget_account("u_00000002")
        self.assertEqual(membership.owner_of("app"), "u_00000001")
        self.assertEqual(membership.mine(self.me("cy")), [])


if __name__ == "__main__":
    unittest.main()
