"""What a node's disks hold, for the Storage page (storage.py): each
project's folders in the stores, its synced copy and the accounts' build
caches, added up by project; the filesystems once each; Docker's sizes read
from the words it prints."""
import os
import shutil
import tempfile
import unittest

import agentpkg  # noqa: E402
agent = agentpkg.load("builderbot_agent_storage")
agent.log = lambda *a, **k: None


def fill(path, mb):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(os.urandom(mb * 1024 * 1024))


class Storage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="storage-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        t = self.tmp
        self.stores = {r: os.path.join(t, r) for r in ("cache", "artifacts", "appdata", "data")}
        fill(os.path.join(t, "cache", "alpha", "gradle.bin"), 2)
        fill(os.path.join(t, "artifacts", "alpha", "app.apk"), 1)
        fill(os.path.join(t, "appdata", "beta", "main", "db"), 3)
        fill(os.path.join(t, "data", "emu", "alpha", "avd.img"), 1)
        fill(os.path.join(t, "ws", "alpha", "src.bin"), 1)
        fill(os.path.join(t, "home", ".cache", "builderbot", "u", "u_1", "project", "alpha", "build", "o"), 2)
        fill(os.path.join(t, "home", "users", "u_2", ".cache", "builderbot", "u", "u_2", "project", "beta", "gradle-home", "x"), 1)
        agent.SHARE = os.path.join(t, "ws")
        agent.SESSION.clear()
        agent.SESSION["home"] = os.path.join(t, "home")
        self.addCleanup(agent.SESSION.clear)
        agent.storage._docker = lambda: {}

    def test_each_projects_folders_are_added_up_by_where_they_are(self):
        got = agent.storage.measure({"stores": self.stores})
        a, b = got["projects"]["alpha"], got["projects"]["beta"]
        self.assertEqual((a["cache"], a["artifacts"], a["emulator"], a["workspace"], a["builds"]), (2, 1, 1, 1, 2))
        self.assertEqual((b["appdata"], b["builds"]), (3, 1))
        self.assertNotIn("emu", got["projects"], "the data store's emu/ is a folder of projects, not one")
        self.assertGreaterEqual(got["stores"]["appdata"]["used_mb"], 3)
        self.assertEqual(agent.storage.last()["at"], got["at"])
        self.assertTrue(got["homes"]["mb"] >= 3)

    def test_a_filesystem_is_listed_once_with_its_room(self):
        fss = agent.storage._filesystems()
        self.assertTrue(any(f["path"] == "/" for f in fss) or fss, fss)
        for f in fss:
            self.assertLessEqual(f["free_mb"], f["total_mb"])
        self.assertEqual(len({f["path"] for f in fss}), len(fss))
        self.assertEqual(agent.storage.fs_of("/x/y", [{"path": "/"}, {"path": "/x"}]), "/x")

    def test_dockers_sizes_are_read_from_its_words(self):
        s = agent.storage._size_mb
        self.assertEqual((s("1.5GB"), s("300MB (12%)"), s("0B"), s("12kB"), s("")), (1500, 300, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
