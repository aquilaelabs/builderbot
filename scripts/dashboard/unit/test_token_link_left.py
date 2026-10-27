"""A home's sign-in link with no seal behind it (B386): the token pass takes
it away, so a terminal on the node says to sign in rather than that a
sealed sign-in is waiting; a link with a seal or an opened copy stays."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "agent"))
from builderbot_agent.tokens import link_left  # noqa: E402


class LinkLeft(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        j = lambda *p: os.path.join(self.d.name, *p)  # noqa: E731
        os.makedirs(j("open"))
        os.makedirs(j("seal"))
        self.home, self.opened, self.seal = j("credentials.json"), j("open", "claude.json"), j("seal", "claude.seal")
        os.symlink(self.opened, self.home)

    def test_a_link_with_nothing_behind_it_is_left_over(self):
        self.assertTrue(link_left(self.home, self.opened, self.seal))

    def test_a_seal_not_yet_opened_keeps_it(self):
        open(self.seal, "wb").close()
        self.assertFalse(link_left(self.home, self.opened, self.seal))

    def test_an_opened_copy_keeps_it(self):
        open(self.opened, "wb").close()
        self.assertFalse(link_left(self.home, self.opened, self.seal))

    def test_a_plain_file_or_another_link_is_not_ours(self):
        os.unlink(self.home)
        open(self.home, "wb").close()
        self.assertFalse(link_left(self.home, self.opened, self.seal))
        os.unlink(self.home)
        os.symlink(self.opened + ".other", self.home)
        self.assertFalse(link_left(self.home, self.opened, self.seal))


if __name__ == "__main__":
    unittest.main()
