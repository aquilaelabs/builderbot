"""names.py and ids.py: the tmux name a project's session really has, and
the item numbers a person types (R86 named these as untested)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ids  # noqa: E402
import names  # noqa: E402


class TmuxName(unittest.TestCase):
    def test_tmux_rewrites_dots_and_colons(self):
        self.assertEqual(names.tmux_name("example.com"), "example_com")
        self.assertEqual(names.tmux_name("a:b.c"), "a_b_c")
        self.assertEqual(names.claude_session("ep.silon"), "claude-ep_silon")

    def test_a_plain_name_is_itself(self):
        self.assertEqual(names.claude_session("BuilderBot"), "claude-BuilderBot")


class ItemNumbers(unittest.TestCase):
    def test_the_ways_a_person_types_one(self):
        for word in ("12", "R12", "r12", "#12", "R012", " R12 "):
            self.assertEqual(ids.parse("roadmap", word), (12, None), word)
        self.assertEqual(ids.parse("bugs", "b7"), (7, None))

    def test_numbers_pass_through_and_booleans_do_not(self):
        self.assertEqual(ids.parse("roadmap", 5), (5, None))
        self.assertEqual(ids.parse("roadmap", 5.0), (5, None))
        self.assertEqual(ids.parse("roadmap", 5.5), (None, None))
        self.assertEqual(ids.parse("roadmap", True), (None, None))

    def test_another_tabs_letter_is_refused_with_a_reason(self):
        n, why = ids.parse("bugs", "R12")
        self.assertIsNone(n)
        self.assertTrue(why)
        n, why = ids.parse("roadmap", "X3")
        self.assertIsNone(n)
        self.assertTrue(why)

    def test_nonsense_is_no_item_and_no_reason(self):
        for word in ("twelve", "", "R", "12a", None, []):
            self.assertEqual(ids.parse("roadmap", word), (None, None), repr(word))

    def test_labels(self):
        self.assertEqual(ids.label("bugs", 7), "B7")
        self.assertEqual(ids.label("roadmap", 12), "R12")


if __name__ == "__main__":
    unittest.main()
