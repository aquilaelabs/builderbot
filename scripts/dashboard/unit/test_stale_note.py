"""A session whose briefing went stale is told so on its next prompt (the
operator, 27 Oct): the card said it to the person and the session never
heard, so it acted on what its briefing said. Once a change, as a rule."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import hooks  # noqa: E402


class StaleNote(unittest.TestCase):
    def setUp(self):
        self.addCleanup(lambda: setattr(hooks, "behind", None))

    def test_said_with_what_changed_and_what_to_do(self):
        hooks.behind = lambda p, u, a, s: ["docs added to its project since it started"]
        said, names = hooks.stale_note("app", "u_00000001", "claude", 1)
        self.assertIn("Your briefing is out of date: docs added to its project", said)
        self.assertIn("tell the person", said)
        self.assertIn("Restart", said)
        self.assertEqual(len(names), 1)
        self.assertEqual(hooks.stale_note("app", "u_00000001", "claude", 1, told=names), ("", []),
                         "once for each change")
        hooks.behind = lambda p, u, a, s: ["docs added", "BuilderBot updated since it started"]
        self.assertTrue(hooks.stale_note("app", "u_00000001", "claude", 1, told=names)[0], "a new change is said again")

    def test_nothing_behind_says_nothing(self):
        hooks.behind = lambda p, u, a, s: []
        self.assertEqual(hooks.stale_note("app", "u", "claude", 1), ("", []))
        hooks.behind = None
        self.assertEqual(hooks.stale_note("app", "u", "claude", 1), ("", []))

        def boom(*a):
            raise RuntimeError("no")
        hooks.behind = boom
        self.assertEqual(hooks.stale_note("app", "u", "claude", 1), ("", []), "a notice is never worth a turn")


if __name__ == "__main__":
    unittest.main()
