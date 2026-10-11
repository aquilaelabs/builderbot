"""A written container renamed while down (the operator, 11 Oct): the node
carries its volumes and data directory under one job, the records, the
compose directory and the env follow when it has, and a rename is refused
while it is up, while a job runs on it, or under a name in use."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import containers  # noqa: E402
import devactions  # noqa: E402
import devapp  # noqa: E402
import paths  # noqa: E402
import relocate  # noqa: E402
from test_devapp_ship import write_json  # noqa: E402
from test_relocate import Queue  # noqa: E402


class Rename(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = Path(self.tmp) / "ws"
        self.ws.mkdir(parents=True)
        self.q = Queue()
        devapp.configure(workspace=self.ws, state=self.tmp, write_json=write_json, queue=self.q,
                         project_nodes=lambda p: [], project_node=lambda p: "")
        paths.configure(state=self.tmp, workspace=self.ws)
        write_json(devapp.FILE, {"radarr": {"main": {"node": "n1", "source": "file", "route": {"mode": "lan", "port": 7878}}}})
        d = devapp.containers_dir("radarr")
        d.mkdir(parents=True)
        (d / "docker-compose.yml").write_text("services:\n  web:\n    image: nginx\n")
        devapp.write_env("radarr", "PORT=7878\n", "main")
        self.up = []
        saved = {k: getattr(devapp, k) for k in ("containers", "dev_data_dir", "appdata_root")}
        self.addCleanup(lambda: [setattr(devapp, k, v) for k, v in saved.items()])
        devapp.containers = lambda: {"containers": list(self.up)}
        devapp.dev_data_dir = lambda p, i="main", make=True: f"/d/{p}"
        devapp.appdata_root = lambda node_id=None: "/d"
        real = devactions._active_job
        devactions._active_job = lambda p, i: None
        self.addCleanup(setattr, devactions, "_active_job", real)

    def test_the_scripts_never_spell_the_placeholder(self):
        self.assertNotIn("cdir", relocate.RENAME_PY)

    def test_renamed_while_down_the_node_carries_the_data_and_the_records_follow(self):
        r = containers.rename_container("radarr", "Plex Box")
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r["name"], "plex-box")
        job = self.q.jobs[r["job"]]
        spec = job["spec"]
        self.assertEqual(spec["rename"], {"to": "plex-box", "own": False})
        step = spec["plan"][0]
        self.assertEqual(step["argv"][3:], ["radarr", "plex-box", "/d/radarr", "/d/plex-box", relocate.HELPER])
        self.assertEqual(devapp._read_rec("radarr", "main").get("renaming"), "plex-box")
        self.assertIn("renaming it to plex-box", relocate.view("radarr", "main")["line"], "the row says it is renaming")
        self.assertIn("already being renamed", containers.rename_container("radarr", "other")["error"])
        self.assertEqual(relocate.rename_done(job, "succeeded"), "")
        d = devapp._load()
        self.assertNotIn("radarr", d)
        self.assertEqual(d["plex-box"]["main"]["route"]["port"], 7878, "the record came whole, the route with it")
        self.assertNotIn("renaming", d["plex-box"]["main"])
        self.assertTrue((devapp.containers_dir("plex-box") / "docker-compose.yml").is_file(), "its compose file moved")
        self.assertFalse(devapp.containers_dir("radarr").exists())
        self.assertEqual(devapp.read_env("plex-box", "main"), "PORT=7878\n", "its env moved")

    def test_a_failed_job_leaves_it_as_it_was_and_says_why(self):
        r = containers.rename_container("radarr", "plex")
        job = self.q.jobs[r["job"]]
        self.q.jobs[job["id"]]["log"] = "carrying the volume radarr_config to plex_config\na volume called plex_config is already on this node: remove it first, or pick another name\n"
        said = relocate.rename_done(job, "failed")
        self.assertIn("renaming it failed: a volume called plex_config is already on this node", said)
        self.assertIn("radarr", devapp._load())
        self.assertNotIn("renaming", devapp._read_rec("radarr", "main"))

    def test_refused_while_up_or_under_a_name_in_use_or_for_a_projects_own(self):
        self.up = [{"name": "radarr-web-1", "project": "radarr", "ours": True}]
        self.assertIn("take it down first", containers.rename_container("radarr", "plex")["error"])
        self.up = []
        write_json(devapp.FILE, devapp._load() | {"plex": {"main": {"source": "file"}}})
        self.assertIn("already exists", containers.rename_container("radarr", "plex")["error"])
        self.assertTrue(containers.rename_container("radarr", "radarr").get("same"), "the same name is nothing to do")
        write_json(devapp.FILE, devapp._load() | {"alpha": {"main": {"node": "n1"}}})
        self.assertIn("not a container written here", containers.rename_container("alpha", "beta")["error"],
                      "a project's container is renamed with its instance named")

    def test_a_projects_container_takes_a_name_of_its_own(self):
        """The operator, 11 Oct: a project's container is named whatever its
        owner wants, not after the project. The record carries the name, the
        instance keeps its key (its worktree, jobs and bb devapp --instance
        stay), and the node carries the volumes and data under the new one."""
        write_json(devapp.FILE, devapp._load() | {"aquilaeLabs": {"main": {"node": "n1", "compose": "site/compose.yml"},
                                                                   "staging": {"node": "n1"}}})
        devapp.write_env("aquilaeLabs", "PORT=8080\n", "main")
        self.assertEqual(devapp._pname("aquilaeLabs", "main"), "aquilaelabs", "named for the project until named")
        self.assertIn("is already aquilaeLabs's container", containers.rename_container("aquilaeLabs", "staging", "main")["error"],
                      "not a name another container answers to")
        self.assertIn("radarr already exists", containers.rename_container("aquilaeLabs", "radarr", "main")["error"])
        r = containers.rename_container("aquilaeLabs", "Turing Site", "main")
        self.assertTrue(r.get("ok"), r)
        job = self.q.jobs[r["job"]]
        self.assertEqual(job["spec"]["rename"], {"to": "turing-site", "own": True})
        self.assertEqual(job["spec"]["plan"][0]["argv"][3:7], ["aquilaelabs", "turing-site", "/d/aquilaeLabs", "/d/turing-site"])
        self.assertEqual(relocate.rename_done(job, "succeeded"), "")
        rec = devapp._read_rec("aquilaeLabs", "main")
        self.assertEqual((rec.get("name"), rec.get("compose"), "renaming" in rec), ("turing-site", "site/compose.yml", False))
        self.assertEqual(devapp._pname("aquilaeLabs", "main"), "turing-site", "the compose name is its own now")
        self.assertEqual(devapp.row_named("turing-site"), ("aquilaeLabs", "main"), "bb devapp --container finds it by it")
        self.assertEqual(devapp.read_env("aquilaeLabs", "main"), "PORT=8080\n", "its env followed the name")
        self.assertEqual(devapp._pname("aquilaeLabs", "staging"), "staging", "the project's other container is untouched")
        # Named back to the project's own default: no name kept.
        r = containers.rename_container("aquilaeLabs", "aquilaeLabs", "main")
        relocate.rename_done(self.q.jobs[r["job"]], "succeeded")
        self.assertNotIn("name", devapp._read_rec("aquilaeLabs", "main"))
        self.assertEqual(devapp._pname("aquilaeLabs", "main"), "aquilaelabs")


if __name__ == "__main__":
    unittest.main()
