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
        self.assertEqual(spec["rename"], {"to": "plex-box"})
        step = spec["plan"][0]
        self.assertEqual(step["argv"][3:], ["radarr", "plex-box", "/d/radarr", "/d/plex-box", relocate.HELPER])
        self.assertEqual(devapp._read_rec("radarr", "main").get("renaming"), "plex-box", "the row says it is renaming")
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
        self.assertIn("not a container written here", containers.rename_container("alpha", "beta")["error"])


if __name__ == "__main__":
    unittest.main()
