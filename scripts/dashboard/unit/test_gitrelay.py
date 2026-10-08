"""gitrelay.ref_ok and _wanted: which ref names read out of somebody's tree
may be written into a config file and packed-refs (R86 named these as
untested). git check-ref-format's rules, held to ASCII and no quote."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gitrelay  # noqa: E402


class RefOk(unittest.TestCase):
    def test_ordinary_refs(self):
        for name in ("refs/heads/main", "refs/tags/v1.0", "refs/heads/claude/a-b_c",
                     "refs/remotes/origin/main"):
            self.assertTrue(gitrelay.ref_ok(name), name)

    def test_what_git_refuses(self):
        for name in ("main", "refs/heads/a..b", "refs/heads/a@{b", "refs/heads/x.lock",
                     "refs/heads/.hidden", "refs/heads/a b", "refs/heads/a~1", "refs/heads/a^",
                     "refs/heads/a:b", "refs/heads/a?", "refs/heads/a*", "refs/heads/a[",
                     "refs/heads/a\\b", "refs/heads/", "refs/heads/a.", "refs/heads//a",
                     "refs/heads/a\x01", "refs/heads/a\x7f"):
            self.assertFalse(gitrelay.ref_ok(name), repr(name))

    def test_what_this_side_refuses_besides(self):
        self.assertFalse(gitrelay.ref_ok('refs/heads/a"b'))
        self.assertFalse(gitrelay.ref_ok("refs/heads/café"))
        self.assertFalse(gitrelay.ref_ok("refs/heads/" + "a" * 250))
        self.assertFalse(gitrelay.ref_ok(None))
        self.assertFalse(gitrelay.ref_ok(b"refs/heads/main"))


class Wanted(unittest.TestCase):
    def test_branches_tags_and_remotes_only(self):
        self.assertTrue(gitrelay._wanted("refs/heads/main"))
        self.assertTrue(gitrelay._wanted("refs/tags/v2"))
        self.assertTrue(gitrelay._wanted("refs/remotes/origin/x"))
        for name in ("refs/notes/commits", "refs/pull/1/head", "refs/stash", "refs/heads/a..b"):
            self.assertFalse(gitrelay._wanted(name), name)


if __name__ == "__main__":
    unittest.main()
