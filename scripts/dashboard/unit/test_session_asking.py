"""Another account's Claude session on Claude Code's permission prompt reads
asking to whoever may see the project, not waiting (B104), and the maps the
status read and /api/live carry are every account's sessions on the
projects the viewer sees and on no other."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import projsessions  # noqa: E402


class Maps(unittest.TestCase):
    def setUp(self):
        saved = {k: getattr(projsessions, k) for k in ("BASE", "OWNER", "ACCOUNTS", "OWNER_NAME", "BEHIND")}
        self.addCleanup(lambda: [setattr(projsessions, k, v) for k, v in saved.items()])
        projsessions.BASE = lambda n: n.split("~", 1)[-1]
        projsessions.OWNER = lambda n: n.split("~", 1)[0] if "~" in n else ""
        projsessions.ACCOUNTS = lambda: {"u_1": "sam", "u_2": "alice"}
        projsessions.OWNER_NAME = lambda: "owner"
        projsessions.BEHIND = lambda s: []
        self.sessions = [
            {"name": "u_2~claude-app", "claude": {"state": "asking", "task": "run ls?"}},
            {"name": "u_1~claude-app", "claude": {"state": "working", "task": ""}},
            {"name": "claude-app", "claude": {"state": "waiting", "task": ""}},
            {"name": "u_2~claude-secret", "claude": {"state": "asking", "task": ""}},
            {"name": "u_1~shell-app", "claude": None},
        ]

    def test_another_account_s_session_on_the_prompt_reads_asking(self):
        got = projsessions.maps(self.sessions, ["app"])
        self.assertEqual(got["claude_asking"], {"app": ["alice"]})
        self.assertEqual(got["claude_busy"], {"app": ["sam"]})
        self.assertEqual(sorted(got["claude_with"]["app"]), ["alice", "owner", "sam"])
        rows = {r["who"]: r for r in got["claude_where"]["app"]}
        self.assertTrue(rows["alice"]["asking"] and not rows["alice"]["working"])
        self.assertFalse(rows["sam"]["asking"])

    def test_a_project_the_viewer_was_not_given_is_in_none_of_them(self):
        got = projsessions.maps(self.sessions, ["app"])
        self.assertTrue(all("secret" not in m for m in got.values()), got)
        self.assertIn("secret", projsessions.maps(self.sessions)["claude_asking"],
                      "an account that sees every project sees it")


if __name__ == "__main__":
    unittest.main()
