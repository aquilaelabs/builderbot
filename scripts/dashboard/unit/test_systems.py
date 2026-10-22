"""Enroll node's systems (R204, R97): a vetted one is offered as it is, and
one that cannot be walked here says why beside its dev tag."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import forges  # noqa: E402
import systems  # noqa: E402


class Offered(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, forges, "unvetted_ok", forges.unvetted_ok)

    def test_a_system_that_cannot_be_walked_says_why(self):
        forges.unvetted_ok = lambda: True
        got = {s["id"]: s for s in systems.offered()}
        self.assertIn("no cloud image", got["void"]["why"])
        self.assertIn("rolling", got["gentoo"]["why"])
        self.assertIn("subscription", got["rhel"]["why"])
        self.assertNotIn("why", got["ubuntu"])
        forges.unvetted_ok = lambda: False
        self.assertNotIn("void", {s["id"] for s in systems.offered()}, "a dev system is offered only behind Offer dev features")


if __name__ == "__main__":
    unittest.main()
