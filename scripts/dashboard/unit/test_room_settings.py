"""The room a node keeps, as Controller settings (R110 steps 1 and 5): whole
numbers held to their range, and a container whose compose file sets no
memory limit given the default one right after up."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402
import devactions  # noqa: E402
import settings  # noqa: E402


def write_json(path, d):
    Path(path).write_text(json.dumps(d))


class Numbers(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = (settings.FILE, settings.write_json)
        self.addCleanup(lambda: setattr(settings, "FILE", saved[0]) or setattr(settings, "write_json", saved[1]))
        settings.FILE, settings.write_json = self.tmp / "settings.json", write_json

    def test_defaults_then_a_number_in_range(self):
        self.assertEqual((settings.get("room_floor_gb"), settings.get("room_mem_pct"), settings.get("container_mem_gb")), (10, 92, 0))
        self.assertTrue(settings.set_many({"room_floor_gb": "25", "container_mem_gb": 4}).get("ok"))
        self.assertEqual((settings.get("room_floor_gb"), settings.get("container_mem_gb")), (25, 4))
        self.assertEqual(settings.payload()["meta"]["room_mem_pct"], {"applied": "now", "min": 50, "max": 99})

    def test_out_of_range_or_not_a_number_is_refused(self):
        for bad in (0, 1001, "ten", True, "2.5"):
            self.assertIn("whole number from 1 to 1000", settings.set_many({"room_floor_gb": bad}).get("error", ""), bad)
        self.assertEqual(settings.get("room_floor_gb"), 10)


class Limit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="room-"))
        self.was = {k: getattr(devapp, k, None) for k in
                    ("WORKSPACE", "STATE", "FILE", "OWNERS", "ENVDIR", "write_json", "label_of", "container_mem_gb")}
        ws, st = self.tmp / "ws", self.tmp / "state"
        st.mkdir()
        devapp.configure(workspace=ws, state=st, write_json=write_json)
        (ws / "alpha").mkdir(parents=True)
        (ws / "alpha" / "compose.yml").write_text("services:\n  web:\n    build: .\n")
        self.assertTrue(devapp.create_instance("alpha", "web-a").get("ok"))

    def tearDown(self):
        for k, v in self.was.items():
            setattr(devapp, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def names(self, action):
        return [s["name"] for s in devactions._plan("alpha", "web-a", action)]

    def test_none_set_adds_nothing(self):
        devapp.container_mem_gb = lambda: 0
        self.assertEqual(self.names("up"), ["starting"])
        self.assertNotIn("limiting memory", self.names("rebuild"))

    def test_a_default_follows_every_up(self):
        devapp.container_mem_gb = lambda: 4
        self.assertEqual(self.names("up"), ["starting", "limiting memory"])
        self.assertEqual(self.names("rebuild")[-2:], ["starting", "limiting memory"])
        self.assertEqual(self.names("update")[-1], "limiting memory")
        step = devactions._plan("alpha", "web-a", "up")[-1]
        self.assertEqual(step["argv"][-3:], [devapp.DOCKER, devapp._pname("alpha", "web-a"), "4g"])
        self.assertIn("{{.HostConfig.Memory}}", step["argv"][2], "a limit the compose file set is kept")


if __name__ == "__main__":
    unittest.main()
