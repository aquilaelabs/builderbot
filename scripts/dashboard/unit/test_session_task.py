"""A session's task follows its latest turn (B59): the pane title Claude names
from the first turn and keeps, so the Sessions page said the first thing it
was asked for every turn after. The prompt hook's `seen` trip notes what was
typed, and the row reads the newest line asked since the session began."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import hooks  # noqa: E402
import projsessions  # noqa: E402


class Task(unittest.TestCase):
    def setUp(self):
        projsessions._asked.clear()

    def test_the_latest_turn_wins(self):
        projsessions.asked("u_0123abcd", "alpha", "fix the login form", now=100)
        projsessions.asked("u_0123abcd", "alpha", "now write the release notes\nwith the dates", now=200)
        self.assertEqual(projsessions.latest_task("u_0123abcd", "alpha", created=50), "now write the release notes")

    def test_a_turn_of_machinery_keeps_the_last_one(self):
        projsessions.asked("u_0123abcd", "alpha", "fix the login form", now=100)
        projsessions.asked("u_0123abcd", "alpha", "  \n", now=200)
        self.assertEqual(projsessions.latest_task("u_0123abcd", "alpha"), "fix the login form")

    def test_an_earlier_sessions_prompt_is_not_this_ones(self):
        projsessions.asked("u_0123abcd", "alpha", "fix the login form", now=100)
        self.assertEqual(projsessions.latest_task("u_0123abcd", "alpha", created=100 + projsessions.SKEW + 1), "")

    def test_keyed_by_account_and_tmux_name_and_trimmed(self):
        projsessions.asked("u_0123abcd", "ep.silon", "x" * 300, now=100)
        got = projsessions.latest_task("u_0123abcd", "ep_silon")
        self.assertTrue(len(got) <= projsessions.TASK_MAX and got.endswith("…"), got)
        self.assertEqual(projsessions.latest_task("u_99999999", "ep_silon"), "")

    def test_the_seen_hook_notes_it(self):
        class Users:
            @staticmethod
            def load():
                return {"users": {}}

        class Nothing:
            def __getattr__(self, name):
                return lambda *a, **k: ([] if name == "matching" else ("", []) if name == "mentioned" else "")
        hooks.configure(users=Users, rules=Nothing(), preamble=Nothing(), roadmap=Nothing(), pending=Nothing(),
                        seen_note=lambda *a, **k: "", asked=projsessions.asked)
        _, status = hooks.verb("seen", {"prompt": "add the dark theme"}, {}, "u_0123abcd", "alpha")
        self.assertEqual(status, 200)
        self.assertEqual(projsessions.latest_task("u_0123abcd", "alpha"), "add the dark theme")


if __name__ == "__main__":
    unittest.main()
