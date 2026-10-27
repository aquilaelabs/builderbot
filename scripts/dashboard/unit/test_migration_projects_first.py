"""State migration 0010 (R138): every live repository is put in a project of
its own, named as it was shown, and what was the repository's as a project
(settings, owner, lists, roles, marks, reads) moves onto the project's key;
a project of several repositories from before keeps its key; a second run
changes nothing."""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "m0010", os.path.join(HERE, "..", "statemigrations", "0010_projects_first.py"))
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def put(d, name, data):
    (d / name).write_text(json.dumps(data))


def get(d, name):
    return json.loads((d / name).read_text())


class ProjectsFirst(unittest.TestCase):
    def setUp(self):
        t = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, t, True)
        self.state, self.ws = t / "state", t / "ws"
        self.state.mkdir()
        for d in ("web", "api", "docs", ".trash"):
            (self.ws / d).mkdir(parents=True)
        put(self.state, "projects.json", {"next": 5, "projects": {
            "web": {"id": 1, "name": "web", "state": "live"},
            "api": {"id": 2, "name": "api", "state": "live"},
            "docs": {"id": 3, "name": "Shop", "state": "live"},
            "Shop": {"id": 4, "name": "Shop", "state": "repos"},
            "gone": {"id": 0, "name": "gone", "state": "deleted"},
        }})
        put(self.state, "project-repos.json", {"projects": {"Shop": {"members": ["api"]}}})
        put(self.state, "claude-prefs.json", {"projects": {
            "web": {"node": "n1", "build": "make", "reads": ["api"]},
            "api": {"node": "n2"},
        }})
        put(self.state, "project-owners.json", {"projects": {"web": "u_a", "api": "u_b"}})
        put(self.state, "users.json", {"users": {"u_a": {
            "projects": ["web", "api", "Shop"], "project_roles": {"web": ["dev"], "api": ["ops"]}}}})
        put(self.state, "pinned-projects.json", {"u_a": ["web"]})
        put(self.state, "project-colors.json", {"u_a": {"web": "red"}})
        put(self.state, "archived-projects.json", ["docs"])
        put(self.state, "locked-projects.json", {"web": {"by": "u_a"}})

    def run_it(self):
        m.run({"state": str(self.state), "workspace": str(self.ws)})

    def test_each_repository_is_placed_and_its_marks_follow(self):
        self.run_it()
        recs = get(self.state, "projects.json")["projects"]
        groups = get(self.state, "project-repos.json")["projects"]
        home = {mem: k for k, g in groups.items() for mem in g["members"]}
        self.assertEqual(set(home), {"web", "api", "docs"}, "a deleted record is left out")
        self.assertEqual(home["api"], "Shop", "an R136 project keeps its key")
        web, docs = home["web"], home["docs"]
        self.assertNotEqual(web, "web", "the key is not the folder already on disk")
        self.assertEqual(recs[web]["name"], "web")
        self.assertEqual(recs[docs]["name"], "Shop (P3)", "a title already a project's gets its number")
        prefs = get(self.state, "claude-prefs.json")["projects"]
        self.assertEqual((prefs[web]["node"], prefs["web"].get("node"), prefs["web"]["build"]), ("n1", None, "make"),
                         "a project's setting moves, a repository's own stays")
        self.assertEqual((prefs["Shop"]["node"], prefs[web]["reads"]), ("n2", ["Shop"]))
        self.assertEqual(get(self.state, "project-owners.json")["projects"], {web: "u_a", "Shop": "u_b"})
        u = get(self.state, "users.json")["users"]["u_a"]
        self.assertEqual(u["projects"], [web, "Shop"])
        self.assertEqual(u["project_roles"], {web: ["dev"], "Shop": ["ops"]})
        self.assertEqual(get(self.state, "pinned-projects.json"), {"u_a": [web]})
        self.assertEqual(get(self.state, "project-colors.json"), {"u_a": {web: "red"}})
        self.assertEqual(get(self.state, "archived-projects.json"), [docs])
        self.assertEqual(list(get(self.state, "locked-projects.json")), [web])

    def test_a_second_run_changes_nothing(self):
        self.run_it()
        before = {p.name: p.read_text() for p in self.state.iterdir()}
        self.run_it()
        self.assertEqual({p.name: p.read_text() for p in self.state.iterdir()}, before)

    def test_an_install_with_no_projects_is_left_alone(self):
        empty = self.state / "e"
        empty.mkdir()
        m.run({"state": str(empty), "workspace": str(self.ws)})
        self.assertEqual(list(empty.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
