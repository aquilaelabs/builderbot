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

    def test_a_config_from_0_6_0_is_copied_before_it_moves(self):
        db = self.lived_in()
        self.addCleanup(db.close)
        self.stamp(sv.SUPPORTED_FROM, "0.6.0")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(sv.gate(self.state, "0.9.0"), sv.SUPPORTED_FROM)
        dest = self.state / "backups" / "before-0.9.0"
        self.assertTrue((dest / "users.json").is_file())
        self.assertTrue((dest / "wiki" / "alpha" / "Home.md").is_file(), "the wiki is state")
        self.assertFalse((dest / "logs").exists(), "logs are not")
        self.assertFalse((dest / "roadmap.json.lock").exists())
        self.assertFalse((dest / "backups").exists())
        got = sqlite3.connect(dest / "builderbot.db").execute("SELECT x FROM t").fetchall()
        self.assertEqual(got, [(7,)], "the database copied whole, its WAL folded in")
        self.assertEqual(sv.read(self.state), (sv.SUPPORTED_FROM, "0.6.0"), "the stamp moves when the migrations have run")

    def test_a_second_try_keeps_the_first_copy(self):
        self.lived_in().close()
        self.stamp(sv.SUPPORTED_FROM, "0.6.0")
        with redirect_stdout(io.StringIO()):
            sv.gate(self.state, "0.9.0")
            (self.state / "users.json").write_text('{"half": "migrated"}')
            sv.gate(self.state, "0.9.0")
        self.assertEqual((self.state / "backups" / "before-0.9.0" / "users.json").read_text(), '{"users": {}}')

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
        with mock.patch.object(sv, "SUPPORTED_FROM", 0):
            self.assertEqual(sv.refusal(self.state, "0.5.0"), "", "a build with no floor migrates from 0")

    def test_this_build_upgrades_from_0_6_0_on_and_sends_older_through_0_6(self):
        # The operator, 28 Oct: 0.9 upgrades from 0.6, 0.7 and 0.8, no further.
        self.stamp(2, "0.6.0")
        self.assertEqual(sv.refusal(self.state, "0.9.0"), "", "0.6.0's state is the floor")
        for n, by in ((1, "0.5.3"), (0, "")):
            self.stamp(n, by)
            self.assertIn("Start the newest 0.6 release on it first", sv.refusal(self.state, "0.9.0"))
        (self.state / "state.json").unlink()
        self.lived_in().close()
        self.assertIn("Start the newest 0.6 release on it first", sv.refusal(self.state, "0.9.0"),
                      "a lived-in /config from before the stamp is state 0")

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


class ClaimFromAShell(unittest.TestCase):
    """B436: the owner made from a shell on a new install, before its first
    start, leaves a stamped store, which that start takes as its own."""
    def test_a_claim_on_a_fresh_store_stamps_it(self):
        import subprocess
        here = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, DASHBOARD_STATE=d, BB_USERS_PW="longenough1")
            r = subprocess.run([sys.executable, str(here.parent / "lib" / "users-verbs.py"), "claim", str(here / "users.py"), "owner1"],
                               env=env, capture_output=True, text=True, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(sv.read(d)[0], sv.current())
            self.assertEqual(sv.refusal(d, "0.9.0"), "")


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
        # The runner's own behavior, below any floor a build sets.
        floor = mock.patch.object(sv, "SUPPORTED_FROM", 0)
        floor.start()
        self.addCleanup(floor.stop)
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
        # B109: said where bb doctor reads it, and cleared once nothing is held.
        self.assertIn("disk full", (self.state / sv.HELD_FILE).read_text())
        with mock.patch.object(sv, "HELD", ""), redirect_stdout(io.StringIO()):
            sv.gate(self.state, "0.6.0")
        self.assertFalse((self.state / sv.HELD_FILE).exists())

    @unittest.skipIf(os.geteuid() == 0, "root reads everything")
    def test_what_it_cannot_read_does_not_hold_the_upgrade(self):
        # B109: the root-only runner-tokens volume stopped every upgrade.
        (self.state / "users.json").write_text('{"users": {}}')
        (self.state / "wiki" / "alpha").mkdir(parents=True)
        rt = self.state / "runner-tokens"
        rt.mkdir()
        (rt / "n_1").write_text("secret")
        rt.chmod(0)
        secret = self.state / "wiki" / "alpha" / "hidden.md"
        secret.write_text("no")
        secret.chmod(0)
        self.addCleanup(rt.chmod, 0o700)
        with redirect_stdout(io.StringIO()) as out:
            sv.gate(self.state, "0.5.0")
        dest = self.state / "backups" / "before-0.5.0"
        self.assertTrue((dest / "users.json").is_file(), out.getvalue())
        self.assertFalse((dest / "runner-tokens").exists(), "its own volume, not copied")
        self.assertIn("wiki/alpha/hidden.md", (dest / "NOT-COPIED.txt").read_text())
        self.assertEqual(sv.HELD, "")


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
