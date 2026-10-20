"""The trash says when a project was deleted (B41): the time the registry
recorded the move, not the directory's mtime, which is when its contents
last changed. A folder put in the bin by hand has only its mtime."""
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import projects  # noqa: E402
import registry  # noqa: E402


def write(p, d, mode=0o644):
    Path(p).write_text(json.dumps(d))


class TrashWhen(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        ws, state = self.tmp / "ws", self.tmp / "state"
        for d in (ws / "alpha", ws / ".trash" / "byhand", state):
            d.mkdir(parents=True)
        registry.configure(state=state, workspace=ws, write_json=write)
        projects.configure(run=None, workspace=ws, agent_keys=lambda: [], gh_authed=lambda: False,
                           ensure_deploy_alias=lambda *a: "", project_name=re.compile(r"[A-Za-z0-9._-]+"),
                           state=state, home=self.tmp, write_json=write)
        registry.sync()
        old = time.time() - 3600
        os.utime(ws / "alpha", (old, old))
        os.utime(ws / ".trash" / "byhand", (old, old))
        self.old = int(old)

    def test_deleted_now_reads_now(self):
        self.addCleanup(setattr, projects, "drop_push", projects.drop_push)
        projects.drop_push = lambda name: None
        _, st = projects.trash({"name": "alpha"})
        self.assertEqual(st, 200)
        items = {e["name"]: e["at"] for e in projects.trash_list()["items"]}
        self.assertGreaterEqual(items["alpha"], int(time.time()) - 5,
                                "an hour-old directory deleted now was deleted now")
        self.assertEqual(items["byhand"], self.old, "one moved by hand has its mtime")


if __name__ == "__main__":
    unittest.main()
