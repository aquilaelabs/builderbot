"""roles.py (R137): the built-in roles reproduce the gate's answers from
before roles existed, a role of your own grants exactly what it says, and
several roles add up."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import roles  # noqa: E402

OWNER = {"name": "boss", "role": "owner", "projects": ["alpha"]}
ADMIN = {"name": "adm", "role": "admin", "projects": ["alpha"]}
USER = {"name": "u", "role": "user", "projects": ["alpha"]}


def on_project(u, name):
    return name in (u.get("projects") or [])


class Builtin(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        roles.configure(state=tmp, write_json=lambda p, d: open(p, "w").write(json.dumps(d)))

    def g(self, u, action, project=None):
        return roles.granted(u, action, project, on_project)

    def test_the_owner_and_an_admin_may_do_everything(self):
        for u in (OWNER, ADMIN):
            for cap in roles.CAPS:
                self.assertTrue(self.g(u, cap), (u["role"], cap))
                self.assertTrue(self.g(u, cap, "beta"), (u["role"], cap))

    def test_a_user_works_on_its_own_projects_and_touches_no_machinery(self):
        self.assertTrue(self.g(USER, "work", "alpha"))
        self.assertTrue(self.g(USER, "roadmap", "alpha"), "an action not listed on its own is work")
        self.assertTrue(self.g(USER, "read", "alpha"))
        self.assertTrue(self.g(USER, "read"), "at all: the projects it is on")
        self.assertFalse(self.g(USER, "work", "beta"), "not on beta")
        for cap in roles.OWN_CAPS:
            self.assertFalse(self.g(USER, cap, "alpha"), cap)
            self.assertFalse(self.g(USER, cap), cap)

    def test_a_role_of_your_own_grants_what_it_says(self):
        self.assertIn("error", roles.set_role("admin", [{"cap": "*", "scope": "all"}]), "built in")
        self.assertIn("error", roles.set_role("deployer", []), "a grant is needed")
        r = roles.set_role("deployer", [{"cap": "version", "scope": ["alpha", "beta"]},
                                        {"cap": "jobs", "scope": "all"}, {"cap": "bogus", "scope": "all"}])
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["grants"]), 2, "an unknown capability is dropped")
        dep = {"name": "d", "role": "user", "roles": ["user", "deployer"], "projects": ["alpha"]}
        self.assertTrue(self.g(dep, "version", "alpha"))
        self.assertTrue(self.g(dep, "version", "beta"), "named, though not on it")
        self.assertFalse(self.g(dep, "version", "gamma"))
        self.assertTrue(self.g(dep, "jobs"))
        self.assertFalse(self.g(dep, "trash", "alpha"), "nothing it did not say")
        self.assertTrue(self.g(dep, "work", "alpha"), "...and the user role still adds up")
        self.assertEqual(roles.summary(dep)["version"], [["alpha", "beta"]])
        self.assertEqual(roles.summary(dep)["jobs"], ["all"])

    def test_a_project_renamed_moves_in_every_named_scope(self):
        roles.set_role("deployer", [{"cap": "version", "scope": ["alpha"]}])
        self.assertTrue(roles.rename_project("alpha", "omega"))
        self.assertEqual(roles.get("deployer")["grants"][0]["scope"], ["omega"])
        self.assertTrue(roles.remove("deployer")["ok"])
        self.assertIn("error", roles.remove("user"))

    def test_an_unknown_role_on_an_account_grants_nothing(self):
        ghost = {"name": "g", "role": "user", "roles": ["user", "gone"], "projects": []}
        self.assertFalse(self.g(ghost, "work", "alpha"))
        self.assertEqual(roles.roles_of(ghost), ["user", "gone"])


if __name__ == "__main__":
    unittest.main()
