"""A project of several repositories (R136): its record (registry.py's repos
state, repos.py's members), Merge and Split with their refusals, and the
settings and grants that go by the project (prefs.py's overlay, reads_trees,
regrant and ungrant)."""
import json
import os
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

    def test_a_repository_made_a_project_of_two_keeps_its_name_by_default(self):
        got = repos.merge("app", ["server"])
        self.assertTrue(got["ok"], got)
        key = got["key"]
        self.assertTrue(got["made"])
        self.assertTrue(registry.is_repos(key))
        self.assertEqual(repos.members(key), ["app", "server"])
        self.assertEqual(registry.label(key), "app", "the project took its first repository's name")
        self.assertEqual(registry.live_named("app"), key, "the name means the project")
        self.assertEqual(registry.resolve("App"), key, "...typed as a name")
        self.assertEqual(registry.resolve("app"), "app", "the folder typed exactly is the repository")
        self.assertEqual(registry.resolve(registry.pid(key)), key, "and the project by its id")
        self.assertEqual(registry.resolve("server"), "server", "a repository is still reached by its own")
        self.assertTrue(registry.pid(key).startswith("P"))
        self.assertNotEqual(registry.pid(key), registry.pid("app"), "the project has an id of its own")
        self.assertFalse((self.ws / key).exists(), "nothing on disk")
        self.assertNotIn(key, registry.live_dirs(), "nor is it listed as a folder")
        self.assertEqual(registry.sync()["projects"][key]["state"], "repos", "a sync leaves it be")

    def test_a_project_may_be_named_anew_and_a_third_joins_it(self):
        key = repos.merge("app", ["server"], name="Shop")["key"]
        self.assertEqual(registry.label(key), "Shop")
        self.assertEqual(registry.resolve("shop"), key)
        got = repos.merge(key, ["docs"])
        self.assertEqual((got["made"], got["added"]), (False, ["docs"]))
        self.assertEqual(repos.members(key), ["app", "server", "docs"])
        self.assertEqual(repos.expand([key, "reader"]), ["app", "server", "docs", "reader"])

    def test_merge_refuses_what_cannot_join(self):
        key = repos.merge("app", ["server"])["key"]
        self.assertIn("already in", repos.merge("docs", ["server"])["error"])
        self.assertIn("not a repository", repos.merge("docs", ["nope"])["error"])
        self.assertIn("not a repository, not", repos.merge("docs", [key])["error"].replace("repositories, not a repository", "not a repository, not"))
        self.assertIn("not a project", repos.merge("nope", ["docs"])["error"])
        self.assertIn("name a repository", repos.merge(key, [])["error"])

    def test_split_puts_a_repository_back_and_a_project_of_one_is_none(self):
        key = repos.merge("app", ["server", "docs"])["key"]
        got = repos.split("docs")
        self.assertEqual((got["out"], got["dropped"]), (["docs"], False))
        self.assertEqual(repos.members(key), ["app", "server"])
        self.assertEqual(repos.project_of("docs"), "")
        got = repos.split("server")
        self.assertEqual((sorted(got["out"]), got["dropped"]), (["app", "server"], True))
        self.assertFalse(registry.is_repos(key))
        self.assertEqual(registry.resolve("App"), "app", "the name is the repository's again")
        self.assertIn(key.lower(), registry.taken_dirs(), "the key is never handed out again")
        self.assertIn("not in a project", repos.split("app")["error"])

    def test_a_repository_reads_its_projects_settings_and_keeps_its_own(self):
        prefs.set_prefs("app", node="n1", devbuild="auto", build="make app", reads=["reader"])
        prefs.set_prefs("server", node="n9", build="make server")
        key = repos.merge("app", ["server"])["key"]
        prefs.adopt(key, "app")
        s = prefs.get("server")
        self.assertEqual((s["node"], s["devbuild"], s["repos_of"]), ("n1", "auto", key),
                         "the project's node and dials, taken from the repository it was made from")
        self.assertEqual(s["build"], "make server", "a repository's own build stays its own")
        # A change to a project field from a repository's settings is the project's.
        prefs.set_prefs("server", devbuild="ask", build="make all")
        self.assertEqual((prefs.get("app")["devbuild"], prefs.get("server")["build"], prefs.get("app")["build"]),
                         ("ask", "make all", "make app"))
        # Split out, the repository is back to what it had.
        repos.split("server")
        self.assertEqual((prefs.get("server")["node"], prefs.get("server")["devbuild"]), ("n9", "deny"))
        self.assertNotIn("repos_of", prefs.get("server"))

    def test_reads_go_by_the_project_and_take_in_a_repository_added_later(self):
        prefs.set_prefs("reader", reads=["app"])
        key = repos.merge("app", ["server"])["key"]
        self.assertEqual(prefs.regrant(key, repos.members(key)), ["reader"])
        self.assertEqual(prefs.get("reader")["reads"], [key])
        self.assertEqual(prefs.reads_trees("reader"), ["app", "server"])
        repos.merge(key, ["docs"])
        self.assertEqual(prefs.reads_trees("reader"), ["app", "server", "docs"], "no setting changed")
        # A session on one repository reads the others of its project.
        self.assertEqual(prefs.reads_trees("app"), ["server", "docs"])
        # Split, a project that read the project still reads what it did.
        got = repos.split("docs")
        prefs.ungrant(key, got["out"], got["dropped"])
        self.assertEqual(prefs.get("reader")["reads"], [key, "docs"])
        self.assertEqual(prefs.reads_trees("reader"), ["app", "server", "docs"])
        got = repos.split("server")
        prefs.ungrant(key, got["out"], got["dropped"])
        self.assertEqual(sorted(prefs.get("reader")["reads"]), ["app", "docs", "server"])


if __name__ == "__main__":
    unittest.main()
