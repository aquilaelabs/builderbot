"""Archive is out of sight only, and a lock says whose it is (R119, the
operator, 23 Oct): an owner's lock holds everybody but the owner, an
administrator's holds the owner too; the migration from the list Archive
used to write; and `bb settings` answering for the seat that asks."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import membership  # noqa: E402
import projects  # noqa: E402
import registry  # noqa: E402
import users  # noqa: E402

OWNER, ADMIN, PLAIN = "u_00000001", "u_00000002", "u_00000003"


def write_json(p, d, _mode=0o644):
    Path(p).write_text(json.dumps(d))


class Locks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = self.tmp / "ws"
        (self.ws / "alpha").mkdir(parents=True)
        write_json(self.tmp / "users.json", {"users": {
            "sean": {"role": "owner", "uid": "u_00000009", "projects": ["*"]},
            "ada": {"role": "admin", "uid": ADMIN, "projects": []},
            "own": {"role": "user", "uid": OWNER, "projects": ["alpha"]},
            "bob": {"role": "user", "uid": PLAIN, "projects": ["alpha"]}}})
        write_json(self.tmp / "project-owners.json", {"projects": {"alpha": {"owner": OWNER}}})
        users.configure(state=self.tmp, write_json=write_json)
        membership.configure(state=self.tmp, write_json=write_json)
        registry.configure(state=self.tmp, workspace=self.ws, write_json=write_json)
        was = (projects.STATE, projects.WORKSPACE, projects.write_json, projects.lock)
        self.addCleanup(lambda: setattr(projects, "STATE", was[0]) or setattr(projects, "WORKSPACE", was[1])
                        or setattr(projects, "write_json", was[2]) or setattr(projects, "lock", was[3]))
        projects.STATE, projects.WORKSPACE = self.tmp, self.ws
        projects.write_json, projects.lock = write_json, threading.Lock()

    def test_the_owners_lock_holds_everybody_but_the_owner(self):
        self.assertEqual(projects.lock_verb("alpha", True, by=OWNER, admin=False)[1], 200)
        self.assertIsNone(projects.locked_out("alpha", OWNER))
        self.assertIn("locked by own", projects.locked_out("alpha", PLAIN)["error"])
        self.assertIsNotNone(projects.locked_out("alpha", ADMIN))

    def test_an_administrators_lock_holds_the_owner_too(self):
        projects.lock_verb("alpha", True, by=ADMIN, admin=True)
        for uid in (OWNER, PLAIN, ADMIN):
            self.assertIn("locked by an administrator", projects.locked_out("alpha", uid)["error"])
        projects.lock_verb("alpha", False)
        self.assertIsNone(projects.locked_out("alpha", PLAIN))

    def test_archiving_locks_nothing(self):
        projects.archive_verb("alpha", True)
        self.assertEqual(projects.load_archived(), ["alpha"])
        self.assertIsNone(projects.locked_out("alpha", PLAIN))

    def test_the_migration_moves_the_old_archive_list_out_of_the_lock(self):
        (self.tmp / "locked-projects.json").write_text('["alpha", "beta"]')
        spec = importlib.util.spec_from_file_location(
            "m5", os.path.join(HERE, "..", "statemigrations", "0005_archive_is_not_a_lock.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m.run({"state": str(self.tmp)})
        self.assertEqual(json.loads((self.tmp / "archived-projects.json").read_text()), ["alpha", "beta"])
        self.assertEqual(projects.load_locks(), {})
        m.run({"state": str(self.tmp)})                       # idempotent
        self.assertEqual(json.loads((self.tmp / "archived-projects.json").read_text()), ["alpha", "beta"])

    def settings_locked(self, uid):
        # As `bb settings --json` runs it.
        env = {**os.environ, "DASHBOARD_STATE": str(self.tmp), "BB_WORKSPACE": str(self.ws),
               "BB_SETTINGS_JSON": "1", "BB_ACCOUNT_UID": uid}
        out = subprocess.run([sys.executable, os.path.join(HERE, "..", "..", "lib", "settings-verbs.py"),
                              "show", os.path.join(HERE, ".."), "alpha"],
                             capture_output=True, text=True, env=env, check=False).stdout
        return json.loads(out).get("locked")

    def test_bb_settings_says_locked_for_the_seat_that_asks(self):
        projects.lock_verb("alpha", True, by=OWNER, admin=False)
        self.assertFalse(self.settings_locked(OWNER))
        self.assertTrue(self.settings_locked(PLAIN))
        projects.lock_verb("alpha", True, by=ADMIN, admin=True)
        self.assertTrue(self.settings_locked(OWNER))


if __name__ == "__main__":
    unittest.main()
