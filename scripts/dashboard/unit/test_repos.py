"""Projects and their repositories (R136, R138): a project made with a name
alone (spaces and punctuation kept), a repository in one at a time and moved
between them, a project deleted only when empty, a repository out of its
project as it goes to the trash with where it was kept, names unique within
each kind, and the settings and grants that go by the project (prefs.py's
overlay, reads_trees, regrant)."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import prefs  # noqa: E402
import registry  # noqa: E402
import repos  # noqa: E402


def write_json(p, d, mode=0o644):
    Path(p).write_text(json.dumps(d))


class Repos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = Path(self.tmp) / "ws"
        for n in ("app", "server", "docs", "reader"):
            (self.ws / n).mkdir(parents=True)
        registry.configure(state=self.tmp, workspace=self.ws, write_json=write_json)
        registry.sync()
        repos.configure(state=self.tmp, write_json=write_json, registry=registry)
        prefs.configure(write_json=write_json, state=self.tmp)
        prefs.configure_repos(project_of=repos.project_of, members=repos.members, is_repos=registry.is_repos)
        self.addCleanup(lambda: prefs.__dict__.update(_repos=None))

    def project(self, name, *dirs):
        got = repos.create(name)
        self.assertTrue(got.get("ok"), got)
        for d in dirs:
            self.assertTrue(repos.add(got["key"], d).get("ok"))
        return got["key"]

    def test_a_project_is_made_with_a_name_alone(self):
        got = repos.create("Shop front, v2!")
        self.assertTrue(got["ok"], got)
        self.assertEqual((got["name"], repos.members(got["key"])), ("Shop front, v2!", []),
                         "spaces and punctuation kept, and nothing in it yet")
        self.assertTrue(registry.is_repos(got["key"]) and not (self.ws / got["key"]).exists())
        registry.sync()
        self.assertEqual(registry.label(got["key"]), "Shop front, v2!", "a sync keeps a project's name as typed")
        self.assertIn("already a project's name", repos.create("shop front, V2!")["error"])
        self.assertIn("letter or digit", repos.create("  ?! ")["error"])

    def test_a_repository_made_after_a_session_started_is_named(self):
        key = self.project("Shop", "app", "server", "docs")
        d = json.loads((Path(self.tmp) / "projects.json").read_text())
        for n, at in (("app", 100), ("server", 50), ("docs", 300)):
            d["projects"][n]["at"] = at
        (Path(self.tmp) / "projects.json").write_text(json.dumps(d))
        r = json.loads((Path(self.tmp) / "project-repos.json").read_text())
        r["projects"][key]["added"] = {"app": 100, "server": 50, "docs": 300}
        (Path(self.tmp) / "project-repos.json").write_text(json.dumps(r))
        repos._cache.update(mtime=None, data=None)
        self.assertEqual(repos.made_since("app", 200), ["docs"],
                         "docs was made after a session on app started; server before; app is its own")
        # One moved in from another project after the session started counts,
        # made long before or not (the operator, 27 Oct).
        other = self.project("Elsewhere", "reader")
        d["projects"]["reader"]["at"] = 10
        (Path(self.tmp) / "projects.json").write_text(json.dumps(d))
        self.assertTrue(repos.move("reader", key).get("ok"))
        self.assertEqual(repos.made_since("app", 200), ["docs", "reader"])
        self.assertTrue(other)
        self.assertEqual(repos.made_since("loner", 0), [], "a repository in no project has none beside it")

    def test_a_project_and_its_repository_may_share_a_name(self):
        key = self.project("app", "app")
        self.assertNotEqual(key, "app")
        self.assertEqual((registry.label(key), registry.label("app")), ("app", "app"))
        # A name asked for is the repository's, which bb -p and a notebook want.
        self.assertEqual(registry.resolve("app"), "app")
        self.assertEqual((repos.key_of("app"), repos.key_of(key), repos.key_of("docs")), (key, key, "docs"))

    def test_a_repository_is_in_one_project_and_moves_between_them(self):
        shop, tools = self.project("Shop", "app", "server"), self.project("Tools", "docs")
        self.assertIn("already in Shop", repos.add(tools, "app")["error"])
        got = repos.move("server", tools)
        self.assertEqual((got["was"], repos.members(shop), repos.members(tools)), (shop, ["app"], ["docs", "server"]))
        self.assertIn("already in Tools", repos.move("server", tools)["error"])
        self.assertIn("is not a project", repos.move("server", "nowhere")["error"])
        self.assertEqual(repos.members(tools), ["docs", "server"], "a refused move leaves it where it was")

    def test_a_repository_in_no_project_is_given_one_of_its_own(self):
        shop = self.project("app", "server")
        made = repos.place()
        keys = dict((d, k) for k, d in made)
        self.assertEqual(set(keys), {"app", "docs", "reader"}, "every live repository not in one, and only those")
        self.assertEqual(registry.label(keys["docs"]), "docs")
        self.assertEqual(registry.label(keys["app"]), f"app ({registry.pid('app')})",
                         "a name that is a project's already gets the repository's id beside it")
        self.assertEqual((repos.members(keys["app"]), repos.project_of("server")), (["app"], shop))
        self.assertEqual(repos.place(), [], "a second time, nothing to place")

    def test_one_put_back_by_hand_goes_back_into_its_project(self):
        shop = self.project("Shop", "app", "server")
        repos.detach("app")
        made = repos.place()
        self.assertNotIn("app", [d for _, d in made], "no project made for it")
        self.assertEqual(repos.project_of("app"), shop, "back where it was deleted from")

    def test_a_project_is_deleted_only_with_nothing_in_it(self):
        shop = self.project("Shop", "app")
        self.assertIn("move or delete its repositories first", repos.delete(shop)["error"])
        self.assertEqual(repos.detach("app"), shop, "to the trash, out of its project")
        self.assertEqual((repos.project_of("app"), registry.last_project("app")), ("", shop),
                         "its record keeps where it was, for the trash and a restore")
        self.assertTrue(repos.delete(shop)["ok"])
        self.assertFalse(registry.is_repos(shop))
        self.assertTrue(repos.create("Shop")["ok"], "its name is free again")

    def test_a_repository_reads_its_projects_settings_and_keeps_its_own(self):
        prefs.set_prefs("app", build="make app")
        key = self.project("Shop", "app", "server")
        prefs.set_prefs("app", node="n1", devbuild="auto", reads=["reader"])
        prefs.set_prefs("server", build="make server")
        s = prefs.get("server")
        self.assertEqual((s["node"], s["devbuild"], s["repos_of"]), ("n1", "auto", key),
                         "the project's node and dials, set from any of its repositories")
        self.assertEqual((s["build"], prefs.get("app")["build"]), ("make server", "make app"),
                         "a repository's own build stays its own")

    def test_a_repository_with_no_record_of_its_own_lists_its_projects_settings(self):
        key = self.project("Shop", "app")
        prefs.set_prefs("app", devbuild="auto")
        repos.add(key, "docs")
        self.assertEqual(prefs.all_projects()["docs"]["devbuild"], "auto", "the status row reads the project's dial")

    def test_reads_go_by_the_project_and_take_in_a_repository_added_later(self):
        prefs.set_prefs("reader", reads=["app"])
        key = self.project("Shop", "app", "server")
        self.assertEqual(prefs.regrant(key, repos.members(key)), ["reader"])
        self.assertEqual(prefs.get("reader")["reads"], [key])
        self.assertEqual(prefs.reads_trees("reader"), ["app", "server"])
        repos.add(key, "docs")
        self.assertEqual(prefs.reads_trees("reader"), ["app", "server", "docs"], "no setting changed")
        # A session on one repository reads the others of its project.
        self.assertEqual(prefs.reads_trees("app"), ["server", "docs"])


class Briefing(unittest.TestCase):
    """The briefing of a session on a project of several repositories
    carries the others' rules, roadmap and bugs, each under its name."""

    def test_the_other_repositories_are_briefed_under_their_names(self):
        import preamble  # noqa: PLC0415
        fake = type("S", (), {})
        rules, roadmap, bugs = fake(), fake(), fake()
        rules.fitted = lambda d, share: (f"rules of {d}", "")
        roadmap.brief = lambda d: f"roadmap of {d}"
        bugs.brief = lambda d: f"bugs of {d}"
        preamble.configure(rules_mod=rules, roadmap_mod=roadmap, bugs_mod=bugs)
        preamble.repos_fn = lambda p: ("Shop", "P9", [("app", "app"), ("server", "server")]) if p in ("app", "server") else None
        self.addCleanup(lambda: setattr(preamble, "repos_fn", None))
        text = preamble.repos_part("app")
        self.assertIn("Shop (P9), a project of 2 repositories", text)
        self.assertIn("### Repository server", text)
        for want in ("rules of server", "roadmap of server", "bugs of server"):
            self.assertIn(want, text)
        self.assertNotIn("roadmap of app", text, "its own are the briefing's own parts")
        self.assertEqual(preamble.repos_part("other"), "")

    def test_a_session_is_briefed_as_its_project_with_every_repository_its_own(self):
        """The operator, 27 Oct: a session in the second repository's project
        was told it was the first repository's project by that one's name
        and id, and that the other repository was read-only."""
        import preamble  # noqa: PLC0415
        fake = type("P", (), {})()
        fake.reads_trees = lambda p: ["server", "elsewhere"]
        fake.get = lambda p: {}
        was = (preamble.prefs_mod, preamble.label_of, preamble.id_of)
        self.addCleanup(lambda: (setattr(preamble, "prefs_mod", was[0]), setattr(preamble, "label_of", was[1]),
                                 setattr(preamble, "id_of", was[2]), setattr(preamble, "repos_fn", None),
                                 setattr(preamble, "project_fn", None)))
        preamble.prefs_mod = fake
        preamble.label_of = lambda p: p
        preamble.id_of = lambda p: "P1"
        preamble.repos_fn = lambda p: ("Shop", "P9", [("app", "app"), ("server", "server")]) if p in ("app", "server") else None
        preamble.project_fn = lambda p: ("Shop", "P9") if p in ("app", "server") else None
        who = preamble.identity_line("app")
        self.assertIn("shown as Shop; its id is P9", who)
        self.assertIn("app at /workspace/app, server at /workspace/server", who)
        self.assertIn("own to work in, commit to and push", who)
        reads = preamble.reads_line("app")
        self.assertIn("elsewhere", reads)
        self.assertNotIn("server", reads, "its own project's repository is not called read-only")
        preamble.repos_fn = lambda p: None
        preamble.project_fn = lambda p: ("Shop", "P9")
        self.assertIn("shown as Shop", preamble.identity_line("app"), "a project of one is briefed as the project")

    def test_bb_preamble_briefs_the_project(self):
        """bb preamble (preamble-verbs.py), which every session's briefing
        comes from, wired as the server is: the project, both repositories
        its own, and neither called read-only."""
        import subprocess  # noqa: PLC0415
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        ws = Path(tmp) / "ws"
        for n in ("app", "server"):
            (ws / n).mkdir(parents=True)
        registry.configure(state=tmp, workspace=ws, write_json=write_json)
        registry.sync()
        repos.configure(state=tmp, write_json=write_json, registry=registry)
        key = repos.create("Shop")["key"]
        for d in ("app", "server"):
            repos.add(key, d)
        here = os.path.dirname(os.path.abspath(__file__))
        env = dict(os.environ, DASHBOARD_STATE=tmp, WORKSPACE=str(ws))
        r = subprocess.run([sys.executable, os.path.join(here, "..", "..", "lib", "preamble-verbs.py"),
                            os.path.join(here, ".."), "app", ""], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("This project is shown as Shop", r.stdout)
        self.assertIn("server at /workspace/server", r.stdout)
        self.assertNotIn("reads server", r.stdout)

    def test_each_repositorys_memories_ride_every_agents_briefing(self):
        """R152: the account's memory index of each repository, for any
        agent; a Claude session's own repository's left to Claude Code."""
        import preamble  # noqa: PLC0415
        ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ws, True)
        was = os.environ.get("WORKSPACE")
        os.environ["WORKSPACE"] = ws
        self.addCleanup(lambda: os.environ.__setitem__("WORKSPACE", was) if was is not None else os.environ.pop("WORKSPACE", None))
        for d in ("app", "server"):
            m = Path(ws, ".claude", "u_1", "projects", re.sub(r"[^A-Za-z0-9]", "-", f"{ws}/{d}"), "memory")
            m.mkdir(parents=True)
            (m / "MEMORY.md").write_text(f"- [Fact of {d}]({d}-fact.md) \u2014 about {d}\n")
        preamble.repos_fn = lambda p: ("Shop", "P9", [("app", "app"), ("server", "server")]) if p in ("app", "server") else None
        self.addCleanup(lambda: setattr(preamble, "repos_fn", None))
        claude = preamble.memory_part("app", "u_1", "claude")[0]
        self.assertIn("### server", claude)
        self.assertIn("Fact of server", claude)
        self.assertNotIn("Fact of app", claude, "Claude Code loads its own repository's index")
        self.assertIn("bb -p REPO memory add", claude)
        other = preamble.memory_part("app", "u_1", "codex")[0]
        self.assertIn("Fact of app", other)
        self.assertIn("Fact of server", other)
        self.assertIn("one about the project as a whole goes on app", other)
        self.assertEqual(preamble.memory_part("app", "", "codex"), ("", ""), "no account, nothing to read")
        preamble.repos_fn = lambda p: None
        self.assertEqual(preamble.memory_part("app", "u_1", "claude")[0], "", "a lone repository's Claude session is told nothing new")
        alone = preamble.memory_part("app", "u_1", "grok")[0]
        self.assertIn("Fact of app", alone)
        self.assertNotIn("###", alone)


if __name__ == "__main__":
    unittest.main()


class StandAlone(unittest.TestCase):
    """prefs.py loaded by a bb verb, with no server to hand it repos.py's
    answers (R138): a repository still reads its project's settings, from
    the state files themselves."""

    def test_a_repository_reads_its_projects_settings_with_no_server(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with open(os.path.join(d, "projects.json"), "w") as f:
            json.dump({"next": 3, "projects": {"alpha": {"id": 1, "name": "alpha", "state": "live"},
                                               "alpha-2": {"id": 2, "name": "alpha", "state": "repos"}}}, f)
        with open(os.path.join(d, "project-repos.json"), "w") as f:
            json.dump({"projects": {"alpha-2": {"members": ["alpha"]}}}, f)
        with open(os.path.join(d, "claude-prefs.json"), "w") as f:
            json.dump({"projects": {"alpha-2": {"sees": ["/mnt/media"], "report": "deny"}, "alpha": {"build": "make"}}}, f)
        saved = prefs.__dict__.get("_repos")
        self.addCleanup(lambda: prefs.__dict__.update(_repos=saved))
        prefs.__dict__.update(_repos=None)
        prefs.configure(state=d, write_json=write_json)
        g = prefs.get("alpha")
        self.assertEqual((g["sees"], g["report"], g["build"]), (["/mnt/media"], "deny", "make"))
