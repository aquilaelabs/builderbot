"""roles.py since R152 (the operator, 7 Oct): a role is a scope (Global, or
the user's projects) and, per area, Read or Write; owner and admin are
built in with everything; the old user role is an ordinary role seeded with
what it allowed; roles given on one project hold there alone; a role from
before R152 is read as one of these."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import roles  # noqa: E402

OWNER = {"name": "boss", "role": "owner", "projects": ["alpha"]}
ADMIN = {"name": "adm", "role": "admin", "projects": ["alpha"]}
USER = {"name": "u", "role": "user", "projects": ["alpha"]}


def on_project(u, name):
    return name in (u.get("projects") or [])


class Model(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        roles.configure(state=self.tmp, write_json=lambda p, d: open(p, "w").write(json.dumps(d)))

    def g(self, u, action, project=None):
        return roles.granted(u, action, project, on_project)

    def test_the_owner_and_an_admin_may_do_everything(self):
        for u in (OWNER, ADMIN):
            for cap in roles.CAP_AREA:
                self.assertTrue(self.g(u, cap), (u["role"], cap))
                self.assertTrue(self.g(u, cap, "beta"), (u["role"], cap))
        self.assertIn("error", roles.set_role("admin", "global", {}), "built in")
        self.assertIn("error", roles.remove("owner"))

    def test_there_is_no_user_role(self):
        # The operator, 7 Oct: an account on `user` holds nothing until given a role.
        self.assertIsNone(roles.get("user"))
        for cap in ("read", "work", "roadmap", "terminal"):
            self.assertFalse(self.g(USER, cap, "alpha"), cap)

    def test_roles_are_named_for_a_person(self):
        # R255 step 1: BuilderBot's owner, an administrator, and the Owner of
        # a project told apart by name, not by their keys.
        roles.ensure_owner_role("alpha")
        self.assertEqual(roles.label("owner"), "BuilderBot's owner")
        self.assertEqual(roles.label("admin"), "Administrator")
        self.assertEqual(roles.label("alpha_owner"), "Owner of alpha")
        self.assertEqual(roles.label("nosuch"), "nosuch")

    def test_what_an_account_may_do_said_once(self):
        # R255 step 5: its roles by name and where they hold, and the areas
        # they add up to, in the Roles tab's order.
        import users
        name = roles.ensure_owner_role("alpha")
        u = {"name": "o", "role": "user", "roles": [], "projects": ["alpha"], "project_roles": {"alpha": [name]}}
        with mock.patch.object(users, "get", lambda n: u):
            got = users.what_may("o")
        self.assertEqual(got["roles"], ["Owner of alpha"])
        self.assertIn(["Projects", "Write"], got["may"])
        self.assertNotIn("Nodes", [a for a, _ in got["may"]])

    def test_an_owner_role_is_every_project_area_and_can_be_cut_back(self):
        name = roles.ensure_owner_role("alpha")
        self.assertEqual(name, "alpha_owner")
        r = roles.get(name)
        self.assertEqual((r["scope"], set(r["perms"])), ("projects", set(roles.PROJECT_AREAS)))
        u = {"name": "o", "role": "user", "roles": [], "projects": ["alpha"], "project_roles": {"alpha": [name]}}
        self.assertTrue(self.g(u, "trash", "alpha"))
        self.assertFalse(self.g(u, "work", "beta"))
        self.assertFalse(self.g(u, "node"), "no global area")
        # Cut back by hand (the operator: FTP taken off an owner role), and
        # not put back by the next ensure.
        perms = dict(r["perms"])
        perms.pop("files")
        roles.set_role(name, "projects", perms, r["note"])
        roles.ensure_owner_role("alpha")
        self.assertNotIn("files", roles.get(name)["perms"])
        self.assertEqual(roles.owner_role_name("2048 game"), "p2048 game_owner")

    def test_a_role_is_a_scope_and_areas(self):
        r = roles.set_role("tester", "projects", {"projects": "write", "containers": "write", "bogus": "write",
                                                  "terminal": "x"})
        self.assertEqual(r["perms"], {"projects": "write", "containers": "write"}, "unknown areas and levels dropped")
        self.assertIn("project areas only", roles.set_role("bad", "projects", {"nodes": "read"})["error"])
        # Given on a project, held there (R155); through the account's own
        # list a role on a project holds nowhere.
        t = {"name": "t", "role": "user", "roles": [], "projects": ["alpha"],
             "project_roles": {"alpha": ["tester"]}}
        self.assertTrue(self.g(t, "docker-write", "alpha"))
        self.assertFalse(self.g(t, "trash", "alpha"), "nothing it did not say")
        self.assertFalse(self.g(t, "docker-write", "beta"), "the project it is given on only")
        listed = {"name": "l", "role": "user", "roles": ["tester"], "projects": ["alpha"]}
        self.assertFalse(self.g(listed, "docker-write", "alpha"), "a project role on the account's list holds nowhere")
        roles.set_role("ops", "global", {"nodes": "write", "jobs": "read"})
        o = {"name": "o", "role": "user", "roles": ["ops"], "projects": []}
        self.assertTrue(self.g(o, "node"))
        self.assertFalse(self.g(o, "jobs"), "read is not write")
        self.assertEqual(roles.summary(o), {"nodes": "write", "jobs": "read"})

    def test_a_global_role_may_hold_its_node_areas_on_named_nodes(self):
        # The operator, 7 Oct: making projects on one node, and node areas
        # scoped as they were before R152.
        r = roles.set_role("creator", "global", {"newprojects": "write", "toolchains": "write", "controller": "read"},
                           nodes=["n1"])
        self.assertEqual(r["nodes"], ["n1"])
        c = {"name": "c", "role": "user", "roles": ["creator"], "projects": []}
        self.assertTrue(roles.granted(c, "create", node="n1"))
        self.assertFalse(roles.granted(c, "create", node="n2"), "not a node it names")
        self.assertTrue(roles.granted(c, "create"), "at all: somewhere")
        self.assertTrue(roles.granted(c, "toolchains-write", node="n1"))
        self.assertFalse(roles.granted(c, "toolchains-write", node="n2"))
        self.assertEqual(roles.nodes_for(c, "newprojects"), ["n1"])
        self.assertIsNone(roles.nodes_for(ADMIN, "newprojects"), "admin: every node")
        self.assertEqual(roles.CAP_AREA["create"], ("newprojects", "write"), "its own area, not Controller's")
        self.assertEqual(roles.set_role("p", "projects", {"projects": "read"}, nodes=["n1"])["nodes"], [],
                         "only a Global role names nodes")

    def test_a_role_given_on_one_project_holds_there_alone(self):
        roles.set_role("releaser", "projects", {"projects": "read", "releases": "write"})
        u = {"name": "r", "role": "user", "roles": [], "projects": ["alpha", "beta"],
             "project_roles": {"beta": ["releaser"]}}
        self.assertTrue(self.g(u, "version", "beta"))
        self.assertFalse(self.g(u, "version", "alpha"), "given on beta, not alpha")
        self.assertTrue(self.g(u, "version"), "at all")

    def test_a_role_from_before_r152_is_read_as_areas(self):
        with open(os.path.join(self.tmp, "roles.json"), "w") as f:
            json.dump({"roles": {"deployer": {"grants": [{"cap": "version", "scope": ["alpha"]},
                                                         {"cap": "jobs", "scope": "all"}], "note": "old"}}}, f)
        d = roles.get("deployer")
        self.assertEqual((d["scope"], d["perms"]), ("global", {"releases": "write", "jobs": "write"}))
        self.assertEqual(d["note"], "old")

    def test_an_unknown_role_on_an_account_grants_nothing(self):
        ghost = {"name": "g", "role": "gone", "roles": ["gone"], "projects": ["alpha"]}
        self.assertFalse(self.g(ghost, "work", "alpha"))


if __name__ == "__main__":
    unittest.main()


class Migration(unittest.TestCase):
    """users.migrate_r152, once: user accounts to no role, each project's
    owner to PROJECT_owner on it; the owner role moves with the project."""

    def setUp(self):
        import users
        self.users = users
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        wj = lambda p, d, mode=0o644: open(p, "w").write(json.dumps(d))  # noqa: E731
        roles.configure(state=self.tmp, write_json=wj)
        users.configure(state=self.tmp, write_json=wj)
        with users._lock:
            d = users.load()
            d["users"] = {"boss": {"uid": "u_1", "role": "owner", "projects": ["*"]},
                          "adm": {"uid": "u_2", "role": "admin", "projects": []},
                          "ann": {"uid": "u_3", "role": "user", "projects": ["alpha"], "roles": ["user", "tester"]},
                          "bob": {"uid": "u_4", "role": "user", "projects": ["beta"]}}
            users._save(d)

    def test_users_lose_user_and_owners_hold_their_projects(self):
        u = self.users
        self.assertTrue(u.migrate_r152({"alpha": "u_3", "beta": "u_1"}))
        self.assertEqual(u.get("ann")["roles"], ["tester"], "user taken off, a role of its own kept")
        self.assertEqual(u.get("bob")["roles"], [])
        self.assertEqual(u.get("ann")["project_roles"], {"alpha": ["alpha_owner"]})
        self.assertNotIn("beta", u.get("boss").get("project_roles") or {}, "BuilderBot's owner needs none")
        self.assertEqual(u.get("adm")["role"], "admin")
        self.assertFalse(u.migrate_r152({"alpha": "u_4"}), "once")

    def test_the_owner_gets_the_owner_role(self):
        u = self.users
        u.migrate_r152({"alpha": "u_3"})
        u.give_owner_role("alpha", "u_4")
        self.assertNotIn("alpha", u.get("ann").get("project_roles") or {})
        self.assertEqual(u.get("bob")["project_roles"]["alpha"], ["alpha_owner"])
        self.assertIn("alpha", u.get("bob")["projects"], "the owner works on what it owns")


def write_json(p, d, mode=0o644):
    with open(p, "w") as f:
        json.dump(d, f)


class R155(unittest.TestCase):
    """A role on a project given on the project alone, and being on one is
    holding a role there (the operator, 8 Oct)."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        roles.configure(state=self.tmp, write_json=write_json)
        import users
        users.configure(state=self.tmp, write_json=write_json)
        self.users = users
        roles.set_role("dev", "projects", {"projects": "write"})
        roles.set_role("ops", "global", {"nodes": "read"})
        with users._lock:
            d = users.load()
            d["users"] = {
                "boss": {"uid": "u_1", "role": "owner", "projects": ["*"]},
                "ann": {"uid": "u_2", "role": "user", "projects": ["alpha", "beta", "gamma"],
                        "roles": ["dev", "ops"], "project_roles": {"gamma": ["dev"]}},
            }
            users._save(d)

    def test_the_migration_gives_a_listed_project_role_on_each_project(self):
        self.assertTrue(self.users.migrate_r155())
        a = self.users.get("ann")
        self.assertEqual(a["roles"], ["ops"], "an Everywhere role stays the account's")
        self.assertEqual(a["project_roles"], {"alpha": ["dev"], "beta": ["dev"], "gamma": ["dev"]})
        self.assertEqual(a["projects"], ["alpha", "beta", "gamma"])
        self.assertFalse(self.users.migrate_r155(), "once")

    def test_assign_follows_the_roles_and_keeps_kinds_apart(self):
        boss = self.users.get("boss")
        r, st = self.users.assign(boss, "ann", ["ops", "dev"], None)
        self.assertEqual(st, 400)
        self.assertIn("on a project", r["error"])
        r, st = self.users.assign(boss, "ann", None, {"alpha": ["ops"]})
        self.assertEqual(st, 400)
        self.assertIn("holds everywhere", r["error"])
        r, st = self.users.assign(boss, "ann", ["ops"], {"alpha": ["dev"], "beta": [], "gamma": []})
        self.assertEqual(st, 200, r)
        self.assertEqual(self.users.get("ann")["projects"], ["alpha"], "on a project is holding a role there")


class SessionAndAccount(unittest.TestCase):
    """A session does no more than the account behind it (the operator,
    7 Oct): its own rules, and its account's roles on the project."""

    def setUp(self):
        import users
        self.users = users
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        wj = lambda p, d, mode=0o644: open(p, "w").write(json.dumps(d))  # noqa: E731
        roles.configure(state=self.tmp, write_json=wj)
        users.configure(state=self.tmp, write_json=wj)
        roles.set_role("reader", "projects", {"projects": "read"})
        roles.set_role("worker", "projects", {"projects": "write"})
        with users._lock:
            d = users.load()
            d["users"] = {"boss": {"uid": "u_1", "role": "owner", "projects": ["alpha"]},
                          "ann": {"uid": "u_3", "role": "user", "projects": ["alpha", "beta"], "roles": [],
                                  "project_roles": {"alpha": ["reader"], "beta": ["worker"]}},
                          "nobody": {"uid": "u_4", "role": "user", "projects": ["alpha"], "roles": []}}
            users._save(d)

    def sess(self, uid, project, reads=()):
        return {"name": f"session:{project}", "role": "user", "projects": [project, *reads],
                "session": project, "uid": uid, "reads": list(reads)}

    def test_a_session_is_held_to_its_accounts_roles(self):
        may = self.users.may
        self.assertEqual(may(self.sess("u_3", "beta"), "work", "beta"), "", "the account works on beta")
        why = may(self.sess("u_3", "alpha"), "work", "alpha")
        self.assertIn("ann's roles give no Projects Write on alpha", why)
        self.assertIn("a session does no more than its account", why)
        self.assertEqual(may(self.sess("u_3", "alpha"), "read", "alpha"), "", "...though it reads there")
        self.assertEqual(may(self.sess("u_1", "alpha"), "work", "alpha"), "", "the owner's session as ever")

    def test_a_project_it_reads_needs_the_account_to_read_it(self):
        may = self.users.may
        self.assertEqual(may(self.sess("u_3", "beta", reads=("alpha",)), "read", "alpha"), "")
        self.assertIn("nobody's roles give no Projects Read on alpha",
                      may(self.sess("u_4", "alpha"), "read", "alpha"))

    def test_a_person_without_a_role_may_do_nothing(self):
        self.assertIn("your roles give no Projects Write on alpha",
                      self.users.may(self.users.get("nobody"), "work", "alpha"))
