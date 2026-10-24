"""A project's daily snapshots (R165): what the sync carries, stored once by
content, a day reusing what did not change, pruned to the project's days
with the objects nobody names removed, and restored whole or a file at a
time after a snapshot of the tree as it is, so the restore can be undone."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import paths  # noqa: E402
import snapshots  # noqa: E402
import wssync  # noqa: E402


class Nodes:
    @staticmethod
    def sync_hint(*a):
        pass

    @staticmethod
    def sync_node_ids():
        return frozenset()


class Snap(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = self.tmp / "ws"
        self.tree = self.ws / "alpha"
        (self.tree / "src").mkdir(parents=True)
        (self.tree / "src" / "a.py").write_text("one\n")
        (self.tree / "README").write_text("readme\n")
        (self.tree / "node_modules" / "x").mkdir(parents=True)
        (self.tree / "node_modules" / "x" / "big.js").write_text("rebuilt, not kept\n")
        os.symlink("src/a.py", self.tree / "link")
        (self.tmp / "state").mkdir()
        paths.configure(state=self.tmp / "state", workspace=self.ws)
        wssync.configure(workspace=self.ws, nodes_module=Nodes, bound_nodes=lambda p: [])
        self.keep = {"alpha": 14}
        self.audited = []
        snapshots.configure(workspace=self.ws, days=lambda p: self.keep[p], names=lambda: ["alpha"],
                            audit_fn=lambda *row: self.audited.append(row))

    def objects(self):
        return sorted(p.name for p in (paths.of("project-snapshots") / "objects").glob("??/*"))

    def test_what_is_kept_and_stored_once(self):
        r = snapshots.take("alpha")
        self.assertEqual(r["files"], 3, "the two files and the link; nothing the sync leaves out")
        m = json.loads((paths.of("project-snapshots") / "days" / "alpha" / f"{r['day']}.json").read_text())
        self.assertNotIn("node_modules/x/big.js", m["files"])
        self.assertEqual(m["files"]["link"][4], "src/a.py")
        before = self.objects()
        self.assertEqual(len(before), 2)
        o = paths.of("project-snapshots") / "objects" / before[0][:2] / before[0]
        self.assertEqual(o.stat().st_mode & 0o777, 0o444, "an object is read-only")
        snapshots.take("alpha", why="before-restore")
        self.assertEqual(self.objects(), before, "a second day of the same tree adds nothing")

    def test_restore_whole_and_one_file_and_undo(self):
        day = snapshots.take("alpha")["day"]
        (self.tree / "src" / "a.py").write_text("tampered\n")
        (self.tree / "README").unlink()
        (self.tree / "planted.sh").write_text("rm -rf /\n")
        r = snapshots.restore("alpha", day, "src/a.py", who="op")
        self.assertTrue(r["ok"], r)
        self.assertEqual((self.tree / "src" / "a.py").read_text(), "one\n")
        self.assertTrue((self.tree / "planted.sh").exists(), "one file's restore touches that file alone")
        (self.tree / "src" / "a.py").write_text("tampered again\n")
        r = snapshots.restore("alpha", day, who="op")
        self.assertEqual((r["wrote"], r["removed"]), (2, 1), r)
        self.assertEqual((self.tree / "README").read_text(), "readme\n")
        self.assertFalse((self.tree / "planted.sh").exists(), "what the day did not have is removed")
        self.assertTrue((self.tree / "node_modules" / "x" / "big.js").exists(), "and nothing outside the sync")
        undo = r["undo"]
        self.assertIn("before-restore", undo)
        snapshots.restore("alpha", undo, "planted.sh")
        self.assertEqual((self.tree / "planted.sh").read_text(), "rm -rf /\n", "the restore can be undone")
        self.assertEqual(self.audited[-1][1], "snapshot-restore")

    def test_refused(self):
        day = snapshots.take("alpha")["day"]
        self.assertIn("not a snapshot", snapshots.restore("alpha", "../../etc")["error"])
        self.assertIn("no snapshot", snapshots.restore("alpha", "2000-01-01")["error"])
        self.assertIn("was not in", snapshots.restore("alpha", day, "nope.txt")["error"])

    def test_daily_prune_and_gc(self):
        snapshots.daily()
        kept = snapshots.days("alpha")
        self.assertEqual(len(kept), 1, "one a day")
        snapshots.daily()
        self.assertEqual(len(snapshots.days("alpha")), 1, "not twice in one day")
        old = paths.of("project-snapshots") / "days" / "alpha" / "2000-01-01.json"
        (self.tree / "gone.txt").write_text("only in the old day\n")
        snapshots.take("alpha", why="before-restore")
        f = next(p for p in (paths.of("project-snapshots") / "days" / "alpha").glob("*before-restore.json"))
        d = json.loads(f.read_text())
        d["at"] = int(time.time()) - 30 * 86400
        old.write_text(json.dumps(d))
        f.unlink()
        n = len(self.objects())
        snapshots.daily()
        self.assertFalse(old.exists(), "a day older than the project keeps goes")
        self.assertEqual(len(self.objects()), n - 1, "and the object only it named")
        self.keep["alpha"] = 0
        snapshots.daily()
        self.assertEqual(snapshots.days("alpha"), [], "0 keeps none")
        self.assertEqual(self.objects(), [])


    def test_a_pinned_day_outlives_the_days_kept_and_off_takes_none(self):
        on = {"alpha": True}
        snapshots.configure(workspace=self.ws, days=lambda p: self.keep[p], names=lambda: ["alpha"],
                            audit_fn=lambda *row: None, on=lambda p: on[p])
        snapshots.daily()
        day = snapshots.days("alpha")[0]["day"]
        self.assertTrue(snapshots.pin("alpha", day).get("ok"))
        self.assertTrue(snapshots.days("alpha")[0]["pinned"])
        self.assertIn("already", snapshots.pin("alpha", day)["error"])
        self.assertIn("not kept", snapshots.pin("alpha", "1999-01-01")["error"])
        self.assertIn("not a day", snapshots.pin("alpha", "../x")["error"])
        self.keep["alpha"] = 0
        snapshots.daily()
        self.assertEqual([d["day"] for d in snapshots.days("alpha")], [day], "0 days keeps a pinned one")
        self.assertTrue(self.objects(), "and the objects it names")
        self.assertTrue(snapshots.pin("alpha", day, False).get("ok"))
        snapshots.daily()
        self.assertEqual(snapshots.days("alpha"), [], "unpinned, it goes with the rest")
        # Switched off: none is taken, whatever the days kept.
        self.keep["alpha"], on["alpha"] = 14, False
        snapshots.daily()
        self.assertEqual(snapshots.days("alpha"), [], "off takes none")
        on["alpha"] = True
        snapshots.daily()
        self.assertEqual(len(snapshots.days("alpha")), 1, "on again, one a day")


if __name__ == "__main__":
    unittest.main()
