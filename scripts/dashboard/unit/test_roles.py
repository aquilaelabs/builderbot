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

    def test_each_action_follows_its_own_area(self):
        # R255 step 3 (the operator, 16 Oct): what sat behind accounts write
        # follows the area it concerns, and accounts write alone gives none of it.
        roles.set_role("ops", scope="global", perms={"controller": "write", "nodes": "write"})
        roles.set_role("rel", scope="projects", perms={"projects": "read", "releases": "write", "settings": "write"})
        roles.set_role("hr", scope="global", perms={"accounts": "write"})
        ops = {"name": "o", "role": "user", "roles": ["ops"], "projects": []}
        rel = {"name": "r", "role": "user", "roles": [], "projects": ["alpha"], "project_roles": {"alpha": ["rel"]}}
        hr = {"name": "h", "role": "user", "roles": ["hr"], "projects": []}
        self.assertTrue(self.g(ops, "controller") and self.g(ops, "controller-read") and self.g(ops, "nodes-write"))
        self.assertFalse(self.g(ops, "admin"), "controller write is not accounts write")
        self.assertTrue(self.g(rel, "signing", "alpha") and self.g(rel, "settings", "alpha"))
        self.assertFalse(self.g(rel, "signing", "beta"))
        self.assertTrue(self.g(hr, "admin"))
        self.assertFalse(self.g(hr, "controller") or self.g(hr, "nodes-write") or self.g(hr, "signing", "alpha"))
        # Every project's containers at once is an Everywhere role's, not a
        # role held on one project.
        roles.set_role("box", scope="projects", perms={"projects": "read", "containers": "read"})
        boxer = {"name": "b", "role": "user", "roles": [], "projects": ["alpha"], "project_roles": {"alpha": ["box"]}}
        self.assertFalse(self.g(boxer, "containers-read"))
        roles.set_role("seer", scope="global", perms={"containers": "read"})
        self.assertTrue(self.g({"name": "s", "role": "user", "roles": ["seer"], "projects": []}, "containers-read"))

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
        import registry
        with mock.patch.object(users, "get", lambda n: u), mock.patch.object(registry, "FILE", None):
            got = users.what_may("o")
        self.assertEqual(got["roles"], ["Owner of alpha"])
        self.assertIn(["Projects", "Write"], got["may"])
        self.assertNotIn("Nodes", [a for a, _ in got["may"]])

    def test_a_project_gone_is_not_said(self):
        # B75: Owner of a project in the bin, or purged, is neither listed
        # nor counted toward what the account may do; the grant is kept.
        import registry
        import users
        live, gone, binned = (roles.ensure_owner_role(p) for p in ("alpha", "beta", "gamma"))
        roles.set_role("peek", scope="projects", perms={"projects": "read", "containers": "write"})
        u = {"name": "o", "role": "user", "roles": [], "projects": ["alpha", "beta", "gamma"],
             "project_roles": {"alpha": [live], "beta": [gone, "peek"], "gamma": [binned]}}
        with mock.patch.object(users, "get", lambda n: u), mock.patch.object(registry, "FILE", "x"), \
                mock.patch.object(registry, "is_project", lambda p: p == "alpha"), \
                mock.patch.object(registry, "label", str):
            got = users.what_may("o")
        self.assertEqual(got["roles"], ["Owner of alpha"])
        self.assertEqual(sorted(u["project_roles"]), ["alpha", "beta", "gamma"], "the grants are kept")
        roles.set_role("alpha_owner", scope="projects", perms={"projects": "read"})
        with mock.patch.object(users, "get", lambda n: u), mock.patch.object(registry, "FILE", "x"), \
                mock.patch.object(registry, "is_project", lambda p: p == "alpha"), \
                mock.patch.object(registry, "label", str):
            got = users.what_may("o")
        self.assertEqual(got["may"], [["Projects", "Read"]], "a gone project's grant adds nothing")

    def test_an_owner_role_is_named_by_the_project_s_shown_name(self):
        # B102: a project whose folder is not its name (syncwalk-mv1bm36p,
        # shown as syncwalk) is owned, and held on, by the name shown.
        import registry
        import users
        name = roles.ensure_owner_role("syncwalk-mv1bm36p")
        roles.set_role("peek", scope="projects", perms={"projects": "read"})
        u = {"name": "o", "role": "user", "roles": [], "projects": ["syncwalk-mv1bm36p"],
             "project_roles": {"syncwalk-mv1bm36p": [name, "peek"]}}
        with mock.patch.object(users, "get", lambda n: u), mock.patch.object(registry, "FILE", "x"), \
                mock.patch.object(registry, "is_project", lambda p: True), \
                mock.patch.object(registry, "label", lambda p: {"syncwalk-mv1bm36p": "syncwalk"}.get(p, p)):
            self.assertEqual(roles.label(name), "Owner of syncwalk")
            got = users.what_may("o")
        self.assertEqual(got["roles"], ["peek on syncwalk", "Owner of syncwalk"])

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
        # The list from before R260 reads as each node area on those nodes at
        # its own level.
        self.assertEqual(r["only"], {"newprojects": {"n1": "write"}, "toolchains": {"n1": "write"}})
        c = {"name": "c", "role": "user", "roles": ["creator"], "projects": []}
        self.assertTrue(roles.granted(c, "create", node="n1"))
        self.assertFalse(roles.granted(c, "create", node="n2"), "not a node it names")
        self.assertTrue(roles.granted(c, "create"), "at all: somewhere")
        self.assertTrue(roles.granted(c, "toolchains-write", node="n1"))
        self.assertFalse(roles.granted(c, "toolchains-write", node="n2"))
        self.assertEqual(roles.nodes_for(c, "newprojects"), ["n1"])
        self.assertIsNone(roles.nodes_for(ADMIN, "newprojects"), "admin: every node")
        self.assertEqual(roles.CAP_AREA["create"], ("newprojects", "write"), "its own area, not Controller's")
        self.assertEqual(roles.set_role("p", "projects", {"projects": "read"}, nodes=["n1"])["only"], {},
                         "only a Global role names nodes")

    def test_an_area_held_instance_by_instance(self):
        # The operator, 16 Oct: an area's row opens on its nodes or runners,
        # Read or Write on each.
        r = roles.set_role("ops", "global", {"nodes": "read", "runner": "read", "controller": "read"},
                           only={"nodes": {"n1": "write", "n2": "read"}, "runner": {"n1/a": "read"},
                                 "storage": {}, "controller": {"x": "write"}})
        self.assertEqual(r["only"], {"nodes": {"n1": "write", "n2": "read"}, "runner": {"n1/a": "read"}},
                         "instance areas alone, an empty map dropped")
        self.assertEqual(r["perms"]["nodes"], "write", "the area at the best of its instances")
        o = {"name": "o", "role": "user", "roles": ["ops"], "projects": []}
        self.assertEqual(roles.level_of(o, "nodes", node="n1"), "write")
        self.assertEqual(roles.level_of(o, "nodes", node="n2"), "read")
        self.assertEqual(roles.level_of(o, "nodes", node="n3"), "", "a node it does not name")
        self.assertEqual(roles.level_of(o, "nodes"), "write", "anywhere: the best")
        self.assertTrue(roles.granted(o, "nodes-write", node="n1"))
        self.assertFalse(roles.granted(o, "nodes-write", node="n2"), "read on n2, not write")
        self.assertEqual(roles.level_of(o, "runner", instance="n1/a"), "read")
        self.assertEqual(roles.level_of(o, "runner", instance="n2/a"), "")
        self.assertEqual(roles.nodes_for(o, "nodes"), ["n1", "n2"])
        self.assertEqual(roles.nodes_for(o, "nodes", "write"), ["n1"])
        self.assertEqual(roles.nodes_for(o, "runner"), ["n1/a"])
        roles.set_role("all", "global", {"nodes": "read"})
        o["roles"].append("all")
        self.assertIsNone(roles.nodes_for(o, "nodes"), "a role holding it on every node: every node")
        self.assertEqual(roles.level_of(o, "nodes", node="n3"), "read")

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

    def test_accounts_write_through_a_role_gives_roles_but_not_admin(self):
        # B66: Accounts and roles Write held through a role of one's own
        # gives roles as the administrator does; the built-in admin stays
        # an administrator's.
        roles.set_role("hr", "global", {"accounts": "write"})
        with self.users._lock:
            d = self.users.load()
            d["users"]["hal"] = {"uid": "u_5", "role": "user", "projects": [], "roles": ["hr"]}
            d["users"]["adm"] = {"uid": "u_6", "role": "admin", "projects": []}
            self.users._save(d)
        hal = self.users.get("hal")
        self.assertTrue(self.users.assignable(hal)["admin"])
        r, st = self.users.assign(hal, "ann", ["ops"], {"alpha": ["dev"]})
        self.assertEqual(st, 200, r)
        r, st = self.users.assign(hal, "ann", ["admin"], None)
        self.assertEqual(st, 403, r)
        r, st = self.users.assign(hal, "adm", [], None)
        self.assertEqual(st, 403, r)
        self.assertEqual(self.users.get("adm")["role"], "admin")


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

    def test_what_was_the_administrators_is_never_a_sessions(self):
        # R255 step 3 gave these to roles; the owner's own session still
        # reaches none of them.
        for action, project in (("settings", "alpha"), ("signing", "alpha"), ("controller", None),
                                ("controller-read", None), ("nodes-write", None), ("containers-read", None)):
            why = self.users.may(self.sess("u_1", "alpha"), action, project)
            self.assertIn("a person's, not a session's", why, action)
        self.assertEqual(self.users.may(self.users.get("boss"), "settings", "alpha"), "", "...while the person does")

    def test_a_project_it_reads_needs_the_account_to_read_it(self):
        may = self.users.may
        self.assertEqual(may(self.sess("u_3", "beta", reads=("alpha",)), "read", "alpha"), "")
        self.assertIn("nobody's roles give no Projects Read on alpha",
                      may(self.sess("u_4", "alpha"), "read", "alpha"))

    def test_a_person_without_a_role_may_do_nothing(self):
        self.assertIn("your roles give no Projects Write on alpha",
                      self.users.may(self.users.get("nobody"), "work", "alpha"))
