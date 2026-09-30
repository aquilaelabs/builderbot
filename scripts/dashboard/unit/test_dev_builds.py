"""artifacts.sweep_dev_builds (R105): of each kind of dev build in a
project's dist/, the newest few stay and the rest go when the Artifacts tab
draws. A kind is the name with its dev version taken out; a release and a
file with no version are never swept."""
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

    def test_the_newest_three_of_each_kind_stay(self):
        debug = [self.make(f"P-0.1.0-dev.{n}-abcdef{n}-debug.apk") for n in range(1, 8)]
        release = [self.make(f"P-0.1.0-dev.{n}-abcdef{n}-release.apk") for n in range(1, 3)]
        gone = artifacts.sweep_dev_builds("proj")
        self.assertEqual(sorted(gone), sorted(debug[:4]))
        left = sorted(p.name for p in self.dist.iterdir())
        self.assertEqual(left, sorted(debug[4:] + release))

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

    def test_no_dist_is_nothing(self):
        self.assertEqual(artifacts.sweep_dev_builds("nothing-here"), [])


if __name__ == "__main__":
    unittest.main()
