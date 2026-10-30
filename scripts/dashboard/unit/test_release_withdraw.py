"""A release withdrawn takes its tag with it, on GitHub, and a tag whose
release is already gone goes alone (R190 step 3): the 0.9.0 dev release
left a tag GitHub would not delete beside its release, and a tag with no
release, each deleted by hand."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import forgerelease  # noqa: E402

API = forgerelease.API + "/repos/o/r"


class Forge:
    def __init__(self, release=True, tag=True):
        self.release, self.tag, self.calls = release, tag, []

    def __call__(self, method, url, token, body=None, data=None, ctype=None):
        self.calls.append((method, url))
        if url == f"{API}/releases/tags/v1.0.0-dev.5" and method == "GET":
            return {"id": 41, "prerelease": True, "assets": [{"name": "a"}, {"name": "b"}],
                    "html_url": "https://h/r"} if self.release else None
        if url == f"{API}/git/ref/tags/v1.0.0-dev.5" and method == "GET":
            return {"ref": "refs/tags/v1.0.0-dev.5"} if self.tag else None
        if method == "DELETE" and url == f"{API}/releases/41":
            self.release = False
            return {}
        if method == "DELETE" and url == f"{API}/git/refs/tags/v1.0.0-dev.5":
            self.tag = False
            return {}
        raise forgerelease.Refused(f"unexpected {method} {url}")


class Withdraw(unittest.TestCase):
    def go(self, forge, fn, *a):
        with mock.patch.object(forgerelease, "_handle", return_value=("github", "GitHub", ("o/r", "t"))), \
                mock.patch.object(forgerelease, "_req", forge):
            return fn("app", *a)

    def test_the_plan_names_what_goes(self):
        p = self.go(Forge(), forgerelease.withdraw_plan, "v1.0.0-dev.5")
        self.assertEqual((p["release"], p["tagged"], p["prerelease"], p["files"]), (True, True, True, 2))

    def test_the_release_goes_first_then_its_tag(self):
        f = Forge()
        r = self.go(f, forgerelease.withdraw, "v1.0.0-dev.5")
        self.assertEqual((r["release"], r["tagged"]), (True, True))
        dels = [u for m, u in f.calls if m == "DELETE"]
        self.assertEqual(dels, [f"{API}/releases/41", f"{API}/git/refs/tags/v1.0.0-dev.5"])
        self.assertIn("its release and its tag deleted", forgerelease.withdraw_said(r))

    def test_a_tag_left_alone_by_its_release_goes_alone(self):
        f = Forge(release=False)
        self.assertTrue(self.go(f, forgerelease.withdraw_plan, "v1.0.0-dev.5")["tagged"])
        r = self.go(f, forgerelease.withdraw, "v1.0.0-dev.5")
        self.assertEqual((r["release"], r["tagged"]), (False, True))

    def test_nothing_there_is_refused_before_anybody_is_asked(self):
        p = self.go(Forge(release=False, tag=False), forgerelease.withdraw_plan, "v1.0.0-dev.5")
        self.assertIn("neither a release nor a tag", p["error"])

    def test_the_tag_is_read_exactly_never_by_prefix(self):
        f = Forge()
        self.go(f, forgerelease.withdraw_plan, "v1.0.0-dev.5")
        self.assertNotIn(("GET", f"{API}/git/refs/tags/v1.0.0-dev.5"), f.calls)


if __name__ == "__main__":
    unittest.main()
