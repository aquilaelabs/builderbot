"""A newer release for a bare-metal install (R90 step 5, releasecheck.py):
the newest published release read, said as newer than the build running
only when it is, on the bell only on a bare-metal install, and nothing of
it on a container install."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import releasecheck  # noqa: E402


class ReleaseCheck(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: None)
        rows = [{"tag_name": "v0.9.1", "draft": True, "html_url": "x"},
                {"tag_name": "v1.0.0", "prerelease": True},
                {"tag_name": "v0.9.0", "html_url": "https://example/v0.9.0"},
                {"tag_name": "v0.8.2"}, {"tag_name": "junk"}]
        path = os.path.join(d, "releases.json")
        with open(path, "w") as f:
            json.dump(rows, f)
        self.was = releasecheck.RELEASES_URL
        releasecheck.RELEASES_URL = "file://" + path
        self.addCleanup(setattr, releasecheck, "RELEASES_URL", self.was)
        self.addCleanup(lambda: releasecheck._latest.update(version="", tag="", at=0, error="", url=""))

    def test_the_newest_published_release_and_whether_it_is_newer(self):
        releasecheck.configure(version=lambda: "0.8.2", bare_metal=lambda: True)
        got = releasecheck.check()
        self.assertEqual((got["version"], got["tag"], got["error"]), ("0.9.0", "v0.9.0", ""), "a draft and a prerelease are passed over")
        self.assertEqual(releasecheck.newer(), "0.9.0")
        self.assertEqual(releasecheck.attention("n_own")[0]["key"], "release:0.9.0")
        self.assertEqual(releasecheck.status()["newer"], "0.9.0")
        # Up to date, or ahead (a dev build of the next version): nothing.
        releasecheck.configure(version=lambda: "0.9.0", bare_metal=lambda: True)
        self.assertEqual(releasecheck.newer(), "")
        self.assertEqual(releasecheck.attention("n_own"), [])
        releasecheck.configure(version=lambda: "0.9.1-dev.12+abc", bare_metal=lambda: True)
        self.assertEqual(releasecheck.newer(), "", "a dev build past the release is not behind it")
        # A container install: nothing drawn, whatever the release.
        releasecheck.configure(version=lambda: "0.8.2", bare_metal=lambda: False)
        self.assertEqual((releasecheck.status(), releasecheck.attention("n_own")), ({}, []))

    def test_a_registry_that_does_not_answer_is_said(self):
        releasecheck.RELEASES_URL = "file:///nonexistent/releases.json"
        releasecheck.configure(version=lambda: "0.8.2", bare_metal=lambda: True)
        got = releasecheck.check()
        self.assertIn("did not answer", got["error"])
        self.assertEqual(releasecheck.newer(), "")


if __name__ == "__main__":
    unittest.main()
