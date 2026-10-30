"""The configuration backed up and found again (R161 step 4, backup.py): a
copy is the move's bundle sealed under the password's key, written to every
folder where copies go with the five newest kept, listed, found by a fresh
install, and restored through the move's gate; nothing without a password."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import backup   # noqa: E402
import move     # noqa: E402
import signing  # noqa: E402


def write_json(path, obj):
    import json
    Path(path).write_text(json.dumps(obj))


class Backup(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "config"
        self.pool = self.tmp / "mnt" / "tank"
        for d in (self.state / "logs", self.pool):
            d.mkdir(parents=True)
        (self.state / "users.json").write_text('{"users": {"ann": {}}}')
        (self.state / "logs" / "old.log").write_text("not copied")
        self.password = "correct horse battery"
        move.configure(state=self.state, workspace=self.tmp / "ws", secrets_dir="", write_json_fn=write_json,
                       seal_fn=signing.seal, open_fn=signing.open_with, state_version_fn=lambda: 16, build_version_fn=lambda: "0.9.0",
                       install_key_fn=lambda: b"", store_paths_fn=lambda: {}, page_url_fn=lambda: "", node_ids_fn=lambda: [], bare_metal_fn=lambda: True)
        self.configure(self.state)

    def configure(self, state, password=None):
        backup.configure(state=state, pack_fn=move.pack, seal_fn=signing.seal, restore_fn=move.restore, manifest_fn=move.read_manifest,
                         password_fn=lambda: self.password if password is None else password,
                         dirs_fn=lambda: [str(self.tmp / "mnt" / "tank").replace(str(self.tmp), "", 1) and "/mnt/tank"],
                         version_fn=lambda: "0.9.0", state_version_fn=lambda: 16, write_json_fn=write_json, host_fn=lambda: "nas")
        # The pool's folder is under /mnt in life; here it is the temp dir's, so where() is told by hand.
        backup.where = lambda: [state / "backup", self.pool / ".builderbot" / "backup"]

    def test_a_copy_is_written_sealed_to_every_folder_and_the_newest_five_kept(self):
        r = backup.make("user:ann", "asked")
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(len(r["where"]), 2)
        for d in (self.state / "backup", self.pool / ".builderbot" / "backup"):
            files = list(d.glob("*.bbbackup"))
            self.assertEqual(len(files), 1, d)
            raw = files[0].read_bytes()
            self.assertTrue(raw.startswith(b"BBBACKUP1\n"))
            self.assertNotIn(b'"users"', raw, "sealed, not readable")
            self.assertNotIn(b"not copied", raw)
        for i in range(6):
            time.sleep(0.01)
            backup.make("user:ann", f"again {i}")
        self.assertEqual(len(list((self.state / "backup").glob("*.bbbackup"))), 5, "the five newest kept")
        st = backup.status()
        self.assertTrue(st["on"] and st["made_at"] and len(st["copies"]) == 10)
        self.assertEqual(st["copies"][0]["version"], "0.9.0")

    def test_nothing_is_written_without_a_password(self):
        self.configure(self.state, password="short")
        r = backup.make("user:ann")
        self.assertIn("no backup password", r.get("error", ""))
        self.assertFalse((self.state / "backup").exists())

    def test_a_fresh_install_finds_the_copy_on_its_disks_and_restores_it_under_the_password(self):
        backup.make("user:ann", "asked")
        found = backup.found([str(self.pool)])
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["host"], found[0]["version"]), ("nas", "0.9.0"))
        fresh = self.tmp / "fresh" / "config"
        fresh.mkdir(parents=True)
        (fresh / "nothing.json").write_text("{}")
        r = backup.restore(found[0]["path"], "wrong password", state_dir=fresh, workspace_dir=self.tmp / "ws2", build_state_version=16)
        self.assertIn("did not open under that password", r.get("error", ""))
        r = backup.restore(found[0]["path"], self.password, state_dir=fresh, workspace_dir=self.tmp / "ws2", build_state_version=16)
        self.assertTrue(r.get("ok"), r)
        self.assertIn('"ann"', (fresh / "users.json").read_text())
        self.assertFalse((fresh / "logs" / "old.log").exists())
        r = backup.restore(found[0]["path"], self.password, state_dir=fresh, build_state_version=15)
        self.assertIn("never lands on an older build", r.get("error", ""))
        # A move bundle is not a backup, and a backup takes no move token.
        self.assertIn("password, not a move token", move.restore(found[0]["path"], "tok", state_dir=fresh).get("error", ""))

    def test_the_loop_copies_once_the_state_has_been_quiet(self):
        backup.make("user:ann", "asked")
        at = backup.status()["made_at"]
        changed, newest = backup._changed_since(at)
        self.assertFalse(changed, "nothing moved since")
        time.sleep(1.1)
        (self.state / "users.json").write_text('{"users": {"ann": {}, "bo": {}}}')
        changed, newest = backup._changed_since(at)
        self.assertTrue(changed and newest > at)
        (self.state / "logs" / "new.log").write_text("x")
        changed2, newest2 = backup._changed_since(newest)
        self.assertFalse(changed2, "a log is not a change")


if __name__ == "__main__":
    unittest.main()
