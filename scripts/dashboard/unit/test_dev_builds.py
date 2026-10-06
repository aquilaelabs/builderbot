"""artifacts.sweep_dev_builds (R105): of each product's dev builds in a
project's dist/, the files of the newest few builds stay, whatever they are
named after the version, and a signed build keeps its signed copy alone. A
product is the name before the version; a release and a file with no
version are never swept by count (the operator, 6 Oct)."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import artifacts  # noqa: E402


class DevBuilds(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.dist = self.ws / "proj" / "dist"
        self.dist.mkdir(parents=True)
        self.was = artifacts.WORKSPACE
        artifacts.WORKSPACE = self.ws
        self.addCleanup(setattr, artifacts, "WORKSPACE", self.was)
        self.t = time.time() - 1000

    def make(self, name):
        p = self.dist / name
        p.write_text("x")
        self.t += 10
        os.utime(p, (self.t, self.t))
        return name

    def test_the_newest_three_builds_stay_whatever_they_are_named(self):
        # Shebang-DevBoard's dist/ on 6 Oct: its first builds were -debug,
        # its later ones -release, and the old name was "the newest of its
        # kind" for good. A build is its number, so the old names go.
        debug = [self.make(f"P-0.1.0-dev.{n}-abcdef{n}-debug.apk") for n in (54, 60, 63)]
        stray = self.make("P-0.5.2-dev.140-3710be0-app-debug.apk")
        release = [self.make(f"P-0.5.4-dev.{n}-abcde{n}-release.apk") for n in (171, 174, 187)]
        gone = artifacts.sweep_dev_builds("proj")
        self.assertEqual(sorted(gone), sorted(debug + [stray]))
        self.assertEqual(sorted(p.name for p in self.dist.iterdir()), sorted(release))

    def test_each_product_keeps_its_own_newest(self):
        a = [self.make(f"App-0.5.4-dev.{n}-abcde{n}-release.apk") for n in (171, 174, 187, 190)]
        v = [self.make(f"Voice-0.5.4-dev.{n}-abcde{n}-release.apk") for n in (171, 174)]
        gone = artifacts.sweep_dev_builds("proj")
        self.assertEqual(gone, [a[0]])
        self.assertTrue(all((self.dist / x).exists() for x in v), "the add-on's own builds are its own count")

    def test_a_signed_build_keeps_its_signed_copy_alone(self):
        unsigned = self.make("P-0.5.4-dev.187-a6610d2-release.apk")
        signed = self.make("P-0.5.4-dev.187-a6610d2-release-signed.apk")
        rel = self.make("P-0.5.4-release.apk")
        rel_signed = self.make("P-0.5.4-release-signed.apk")
        lone = self.make("P-0.5.4-dev.186-b6610d2-release.apk")     # never signed: stays
        gone = artifacts.sweep_dev_builds("proj")
        self.assertEqual(sorted(gone), sorted([unsigned, rel]))
        self.assertEqual(sorted(p.name for p in self.dist.iterdir()), sorted([signed, rel_signed, lone]))

    def test_keep_none_means_keep_everything(self):
        self.make("P-0.5.4-dev.1-a6610d2-release.apk")
        self.make("P-0.5.4-dev.1-a6610d2-release-signed.apk")
        self.assertEqual(artifacts.sweep_dev_builds("proj", 0), [])

    def test_an_unnamed_build_is_flagged_and_removed_only_by_a_person(self):
        self.assertTrue(artifacts.unversioned("app-debug.apk"))
        self.assertFalse(artifacts.unversioned("P-0.5.4-release.apk"))
        self.assertFalse(artifacts.unversioned("builderbot-app-53eba569.apk"))
        self.assertFalse(artifacts.unversioned("notes.txt"))
        self.make("app-debug.apk")
        self.assertEqual(artifacts.sweep_dev_builds("proj"), [])
        self.assertEqual(artifacts.forget_unnamed("proj", "dist/P-0.5.4-release.apk")[1], 400)
        self.assertEqual(artifacts.forget_unnamed("proj", "dist/../x/app-debug.apk")[1], 400)
        self.assertEqual(artifacts.forget_unnamed("proj", "dist/app-debug.apk")[1], 200)
        self.assertFalse((self.dist / "app-debug.apk").exists())

    def test_a_release_and_an_unversioned_file_are_never_swept(self):
        keep = [self.make("P-0.1.0-debug.apk"), self.make("app-debug.apk"), self.make("notes.txt")]
        for n in range(1, 6):
            self.make(f"P-0.1.0-dev.{n}-abcdef{n}-debug.apk")
        artifacts.sweep_dev_builds("proj")
        for k in keep:
            self.assertTrue((self.dist / k).exists(), k)

    def test_a_dirty_build_is_the_same_kind(self):
        a = self.make("P-1.0.0-dev.1-1234567-dirty-app.apk")
        self.make("P-1.0.0-dev.2-2345678-app.apk")
        self.assertEqual(artifacts.dev_kind(a), artifacts.dev_kind("P-1.0.0-dev.2-2345678-app.apk"))
        self.assertEqual(artifacts.sweep_dev_builds("proj", keep=1), [a])

    def test_a_pinned_build_stays_and_is_not_one_of_the_three(self):
        import json
        builds = [self.make(f"P-0.1.0-dev.{n}-abcdef{n}-debug.apk") for n in range(1, 7)]
        state = Path(tempfile.mkdtemp())
        written = {}

        def write_json(path, d):
            written["d"] = d
            Path(path).write_text(json.dumps(d))
        self.addCleanup(setattr, artifacts, "PINS", artifacts.PINS)
        self.addCleanup(setattr, artifacts, "_write_json", artifacts._write_json)
        artifacts.PINS, artifacts._write_json = state / "artifact-pins.json", write_json
        was_cap = artifacts._capture

        class Cap:
            CAPTURE_DIRS = ("reel", "emu")
        artifacts._capture = Cap
        self.addCleanup(setattr, artifacts, "_capture", was_cap)
        self.assertEqual(artifacts.pin("proj", f"dist/{builds[0]}", True, by="ann")[1], 200)
        gone = artifacts.sweep_dev_builds("proj")
        left = sorted(p.name for p in self.dist.iterdir())
        self.assertEqual(left, sorted([builds[0]] + builds[3:]))
        self.assertEqual(sorted(gone), sorted(builds[1:3]))
        self.assertEqual(artifacts.pins("proj")[f"dist/{builds[0]}"]["by"], "ann")
        artifacts.pin("proj", f"dist/{builds[0]}", False)
        self.assertEqual(artifacts.pins("proj"), {})
        self.assertNotIn("proj", written["d"])
        self.assertEqual(artifacts.pin("proj", "dist/none.apk", True)[1], 404)
        self.assertEqual(artifacts.pin("proj", "../secret", True)[1], 404)
        (self.dist / "reel").mkdir()
        (self.dist / "reel" / "sheet.png").write_text("x")
        self.assertEqual(artifacts.pin("proj", "dist/reel/sheet.png", True)[1], 400)

    def test_the_project_says_how_many(self):
        debug = [self.make(f"P-0.1.0-dev.{n}-abcdef{n}-debug.apk") for n in range(1, 5)]
        self.assertEqual(sorted(artifacts.sweep_dev_builds("proj", 1)), sorted(debug[:3]))
        self.assertEqual([p.name for p in self.dist.iterdir()], debug[3:])

    def test_the_setting_is_a_count_or_the_default(self):
        import prefs
        self.assertEqual([prefs._dev_keep(v) for v in (None, "", "x", -1, 100, 0, "5", 99)],
                         [3, 3, 3, 3, 3, 0, 5, 99])

    def test_no_dist_is_nothing(self):
        self.assertEqual(artifacts.sweep_dev_builds("nothing-here"), [])


if __name__ == "__main__":
    unittest.main()
