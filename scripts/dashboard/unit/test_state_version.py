"""/config's state version (R79): a fresh /config is stamped, one newer
than the build or older than it migrates from is refused in one sentence,
one about to move is copied first (the newest three kept, what grows left
out), and the numbered migrations past the stamp run once, in order, each
stamped as it lands. And migration 0001, the one-off migrators that ran at
every start before the stamp, folded into one that runs once."""
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stateversion as sv  # noqa: E402


def write_json(p, d, mode=0o644):
    with open(p, "w") as f:
        json.dump(d, f)


class Gate(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.state, True)
        self.cur = sv.current()

    def stamp(self, n, by="9.9.9"):
        (self.state / "state.json").write_text(json.dumps({"state": n, "by": by}))

    def lived_in(self):
        (self.state / "users.json").write_text('{"users": {}}')
        (self.state / "logs").mkdir()
        (self.state / "logs" / "dashboard.log").write_text("big\n")
        (self.state / "wiki" / "alpha").mkdir(parents=True)
        (self.state / "wiki" / "alpha" / "Home.md").write_text("# Home\n")
        (self.state / "roadmap.json.lock").write_text("")
        db = sqlite3.connect(self.state / "builderbot.db")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE t (x)")
        db.execute("INSERT INTO t VALUES (7)")
        db.commit()
        return db

    def test_this_build_writes_its_newest_migration(self):
        self.assertGreaterEqual(self.cur, 1, "0.5.0 is state 1")
        self.assertEqual(self.cur, sv.migrations()[-1][0])
        self.assertLessEqual(sv.SUPPORTED_FROM, self.cur)

    def test_a_fresh_config_is_stamped_current_with_nothing_copied(self):
        self.assertEqual(sv.gate(self.state, "0.5.0"), self.cur)
        self.assertEqual(sv.read(self.state), (self.cur, "0.5.0"))
        self.assertFalse((self.state / "backups").exists())

    def test_a_config_from_before_the_stamp_is_state_0_and_copied_first(self):
        db = self.lived_in()
        self.addCleanup(db.close)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(sv.gate(self.state, "0.5.0"), 0)
        dest = self.state / "backups" / "before-0.5.0"
        self.assertTrue((dest / "users.json").is_file())
        self.assertTrue((dest / "wiki" / "alpha" / "Home.md").is_file(), "the wiki is state")
        self.assertFalse((dest / "logs").exists(), "logs are not")
        self.assertFalse((dest / "roadmap.json.lock").exists())
        self.assertFalse((dest / "backups").exists())
        got = sqlite3.connect(dest / "builderbot.db").execute("SELECT x FROM t").fetchall()
        self.assertEqual(got, [(7,)], "the database copied whole, its WAL folded in")
        self.assertEqual(sv.read(self.state), (None, ""), "the stamp moves when the migrations have run")

    def test_a_second_try_keeps_the_first_copy(self):
        self.lived_in().close()
        with redirect_stdout(io.StringIO()):
            sv.gate(self.state, "0.5.0")
            (self.state / "users.json").write_text('{"half": "migrated"}')
            sv.gate(self.state, "0.5.0")
        self.assertEqual((self.state / "backups" / "before-0.5.0" / "users.json").read_text(), '{"users": {}}')

    def test_the_newest_three_copies_are_kept(self):
        (self.state / "users.json").write_text("{}")
        for i, v in enumerate(("0.5.0", "0.5.1", "0.5.2", "0.6.0")):
            sv.backup(self.state, v)
            os.utime(self.state / "backups" / f"before-{v}", (1000 + i, 1000 + i))
        self.assertEqual(sorted(p.name for p in (self.state / "backups").iterdir()),
                         ["before-0.5.1", "before-0.5.2", "before-0.6.0"])

    def test_a_newer_config_is_refused_naming_the_copy_to_restore(self):
        (self.state / "users.json").write_text("{}")
        sv.backup(self.state, "0.9.0")
        self.stamp(self.cur + 1, "0.9.0")
        why = sv.refusal(self.state, "0.5.0")
        self.assertIn("Downgrades are not supported", why)
        self.assertIn("0.9.0", why)
        self.assertIn(str(self.state / "backups" / "before-0.9.0"), why)
        self.assertNotIn("—", why)
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err), self.assertRaises(SystemExit) as cm:
            sv.gate(self.state, "0.5.0")
        self.assertEqual(cm.exception.code, 78)
        self.assertIn("will not start", err.getvalue())
        self.assertEqual(sv.read(self.state)[0], self.cur + 1, "nothing written")

    def test_an_older_config_than_this_build_migrates_from_names_the_way_through(self):
        self.stamp(0, "0.4.0")
        with mock.patch.object(sv, "SUPPORTED_FROM", 1), mock.patch.object(sv, "THROUGH", {0: "0.5"}):
            why = sv.refusal(self.state, "0.6.0")
        self.assertIn("Start the newest 0.5 release on it first", why)
        self.assertIn("install.md#upgrading", why)
        self.assertEqual(sv.refusal(self.state, "0.5.0"), "", "this build migrates from 0")

    def test_an_unreadable_stamp_is_refused_rather_than_guessed(self):
        (self.state / "state.json").write_text("{nope")
        self.assertIn("cannot be read", sv.refusal(self.state, "0.5.0"))
        (self.state / "state.json").write_text('{"state": "1"}')
        self.assertIn("no state number", sv.refusal(self.state, "0.5.0"))

    def test_the_entrypoint_check_says_the_same(self):
        self.stamp(self.cur + 5)
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            self.assertEqual(sv.main(["check", str(self.state)]), 78)
        self.assertIn("Downgrades are not supported", err.getvalue())
        self.stamp(self.cur)
        self.assertEqual(sv.main(["check", str(self.state)]), 0)


class Migrate(unittest.TestCase):
    """The runner, over a directory of migrations of the test's own."""
    def setUp(self):
        self.state = Path(tempfile.mkdtemp())
        self.mig = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.state, True)
        self.addCleanup(shutil.rmtree, self.mig, True)
        for n, body in ((1, "ctx['ran'].append(1)"), (2, "ctx['ran'].append(2)"),
                        (3, "ctx['ran'].append(3)\n    if ctx.get('fail'): raise ValueError('no')")):
            (self.mig / f"{n:04d}_m.py").write_text(f"def run(ctx):\n    {body}\n")
        patch = mock.patch.object(sv, "MIGRATIONS", self.mig)
        patch.start()
        self.addCleanup(patch.stop)
        (self.state / "users.json").write_text("{}")

    def test_each_runs_once_in_order_and_is_stamped(self):
        ctx = {"ran": []}
        with redirect_stdout(io.StringIO()):
            self.assertEqual(sv.migrate(self.state, ctx, "0.6.0"), [1, 2, 3])
            self.assertEqual(sv.migrate(self.state, ctx, "0.6.0"), [])
        self.assertEqual(ctx["ran"], [1, 2, 3])
        self.assertEqual(sv.read(self.state), (3, "0.6.0"))

    def test_a_failure_stops_at_the_last_that_ran_and_the_next_start_resumes(self):
        (self.state / "state.json").write_text('{"state": 1}')
        ctx = {"ran": [], "fail": True}
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(sv.migrate(self.state, ctx), [2])
        self.assertIn("0003_m.py failed", out.getvalue())
        self.assertEqual(sv.read(self.state)[0], 2)
        ctx["fail"] = False
        with redirect_stdout(io.StringIO()):
            self.assertEqual(sv.migrate(self.state, ctx), [3])

    def test_no_copy_no_migration(self):
        with mock.patch.object(sv, "backup", side_effect=OSError("disk full")), \
                mock.patch.object(sv, "HELD", ""), redirect_stdout(io.StringIO()):
            sv.gate(self.state, "0.6.0")
            self.assertIn("disk full", sv.HELD)
            self.assertEqual(sv.migrate(self.state, {"ran": []}), [])
        self.assertEqual(sv.read(self.state), (None, ""))


class First(unittest.TestCase):
    """0001: what ran at every start before the stamp, now once."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "ws" / "alpha").mkdir(parents=True)
        (self.tmp / "ws" / "beta").mkdir(parents=True)
        import membership
        import registry
        import roles
        import settings
        import users
        self.users, self.settings = users, settings
        for m in (membership, roles, users, settings):
            m.configure(state=self.tmp, write_json=write_json)
        registry.configure(state=self.tmp, workspace=self.tmp / "ws", write_json=write_json)
        with users._lock:
            d = users.load()
            d["users"] = {"boss": {"uid": "u_1", "role": "owner", "projects": ["*"]},
                          "ann": {"uid": "u_2", "role": "user", "projects": ["alpha"]}}
            users._save(d)
        write_json(self.tmp / "settings.json", {"apps_token": "ghp_x", "apps_android": True})

    def test_it_runs_the_old_migrators_and_twice_changes_nothing(self):
        m = sv._load(sv.migrations()[0][1])
        with redirect_stdout(io.StringIO()):
            m.run({"project_names": lambda: ["alpha", "beta"]})
        d = self.users.load()
        self.assertTrue(d.get("r152") and d.get("r155"), "both marked done")
        self.assertEqual(d["users"]["boss"]["projects"], ["alpha", "beta"], "the owner's star, by name")
        self.assertEqual(d["users"]["ann"]["projects"], [], "a project held with no role is let go")
        self.assertEqual(json.loads((self.tmp / "settings.json").read_text()), {"apps_android": True})
        self.assertNotIn("apps_token", self.settings.KEYS, "and it is no setting any more")
        before = (self.tmp / "users.json").read_text()
        with redirect_stdout(io.StringIO()):
            m.run({"project_names": lambda: ["alpha", "beta"]})
        self.assertEqual((self.tmp / "users.json").read_text(), before)


class Release(unittest.TestCase):
    """bb version release, and the Artifacts view's Release, refuse a
    version with no snapshot where the tree keeps them."""
    def test_a_tree_that_keeps_snapshots_needs_this_ones(self):
        import version
        tree = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tree, True)
        with mock.patch.object(version, "root", lambda _p: tree):
            self.assertEqual(version.no_upgrade_snapshot("p", "", "0.5.0"), "", "a tree that keeps none")
            snaps = tree / version.UPGRADE_SNAPSHOTS
            (snaps / "0.5.0").mkdir(parents=True)
            self.assertIn("tools/upgrade-snapshot.py", version.no_upgrade_snapshot("p", "", "0.5.0"))
            (snaps / "0.5.0" / "manifest.json").write_text("{}")
            self.assertEqual(version.no_upgrade_snapshot("p", "", "0.5.0"), "")
            self.assertIn("0.5.1", version.no_upgrade_snapshot("p", "", "0.5.1"))
            self.assertEqual(version.no_upgrade_snapshot("p", "android", "0.5.1"), "", "a component is its own")


if __name__ == "__main__":
    unittest.main()
