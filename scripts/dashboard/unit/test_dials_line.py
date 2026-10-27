"""The briefing says the project's Agents may dials as they stand (the
operator, 27 Oct): a session told only the defaults said a release would
wait on the owner's answer where the dial was auto."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import preamble  # noqa: E402


class DialsLine(unittest.TestCase):
    def setUp(self):
        was = (preamble.prefs_mod, preamble.version_policy)
        self.addCleanup(lambda: (setattr(preamble, "prefs_mod", was[0]), setattr(preamble, "version_policy", was[1])))

    def said(self, rec, policy=None):
        fake = type("P", (), {})()
        fake.get = lambda p: rec
        preamble.prefs_mod = fake
        preamble.version_policy = policy
        return preamble.dials_line("app")

    def test_each_dial_as_it_stands(self):
        s = self.said({"release": "auto", "gate": {"bugs": "ask"}, "devbuild": "auto"}, lambda p: "minor")
        self.assertIn("Tag and publish a release auto", s)
        self.assertIn("File bugs ask", s)
        self.assertIn("Run its container auto", s)
        self.assertIn("Move the version minor", s)
        self.assertIn("auto runs at once", s)

    def test_the_defaults_where_none_is_set(self):
        s = self.said({})
        self.assertIn("Tag and publish a release ask", s)
        self.assertIn("Make VMs deny", s)
        self.assertNotIn("Move the version", s)


if __name__ == "__main__":
    unittest.main()
