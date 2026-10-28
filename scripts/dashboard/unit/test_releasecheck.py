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
                {"tag_name": "v0.8.2"}, {"tag_name": "junk"},
                {"tag_name": "v0.9.1-dev.4500", "prerelease": True, "html_url": "https://example/dev4500"},
                {"tag_name": "v0.9.1-dev.4400", "prerelease": True},
                {"tag_name": "v0.9.2-dev.9", "draft": True, "prerelease": True}]
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



    def test_the_dev_channel_takes_pre_releases_and_only_where_it_may(self):
        # R179: the normal channel passes a pre-release over; the dev
        # channel takes the newest dev build's and ranks it against the
        # releases; a dev channel picked where dev may not be is normal.
        on = {"dev": True}
        releasecheck.configure(version=lambda: "0.9.0", bare_metal=lambda: True, channel=lambda: "dev", dev_ok=lambda: on["dev"])
        got = releasecheck.check()
        self.assertEqual((got["version"], got["dev"]["version"], got["dev"]["tag"]), ("0.9.0", "0.9.1-dev.4500", "v0.9.1-dev.4500"),
                         "the newest pre-release whose tag is a dev build's, never a draft")
        self.assertEqual(releasecheck.newer(), "0.9.1-dev.4500", "on the dev channel a release moves to the dev build past it")
        self.assertEqual(releasecheck.status()["channel"], "dev")
        releasecheck.configure(version=lambda: "0.9.1-dev.4450+abc1234", bare_metal=lambda: True, channel=lambda: "dev", dev_ok=lambda: True)
        self.assertEqual(releasecheck.newer(), "0.9.1-dev.4500", "a dev build moves to a later dev build")
        releasecheck.configure(version=lambda: "0.9.1-dev.4600+abc1234", bare_metal=lambda: True, channel=lambda: "dev", dev_ok=lambda: True)
        self.assertEqual(releasecheck.newer(), "", "...and not to an earlier one")
        releasecheck.configure(version=lambda: "0.9.1-dev.4600+abc1234", bare_metal=lambda: True, channel=lambda: "normal", dev_ok=lambda: True)
        self.assertEqual(releasecheck.newer(), "", "the normal channel never offers a dev build")
        on["dev"] = False
        releasecheck.configure(version=lambda: "0.9.0", bare_metal=lambda: True, channel=lambda: "dev", dev_ok=lambda: on["dev"])
        self.assertEqual((releasecheck.channel(), releasecheck.newer(), releasecheck.status()["dev_ok"]), ("normal", "", False),
                         "dev picked where it may not be is the normal channel")
        self.assertEqual(releasecheck.rank("0.9.0"), (0, 9, 0, 10 ** 9))
        self.assertEqual(releasecheck.rank("v0.9.0-dev.12+abcdef0"), (0, 9, 0, 12))


if __name__ == "__main__":
    unittest.main()
