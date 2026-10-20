"""The account sessions run as, on a node whose agent is not root: its own,
and a uid with no passwd entry (a container started as a bare number) is
named rather than raising, which killed the agent after its first hello
(diag report #119)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import agentpkg  # noqa: E402


class SessionAccount(unittest.TestCase):
    def setUp(self):
        self.agent = agentpkg.load("account")
        self.mixin = self.agent.SessionsMixin

    def account(self, uid, user=None, known=True):
        fake = type("F", (), {"state": {}})()
        env = {"USER": user} if user else {}
        def getpwuid(n):
            if not known:
                raise KeyError(f"getpwuid(): uid not found: {n}")
            return type("P", (), {"pw_name": "builder"})()
        with mock.patch("os.geteuid", return_value=uid), \
             mock.patch("pwd.getpwuid", side_effect=getpwuid), \
             mock.patch.dict(os.environ, env, clear=False):
            if not user:
                os.environ.pop("USER", None)
            return self.mixin.session_account(fake)

    def test_a_known_uid_is_its_name(self):
        self.assertEqual(self.account(1000), "builder")

    def test_an_unknown_uid_is_named_from_the_environment_or_its_number(self):
        self.assertEqual(self.account(99, user="nobody99", known=False), "nobody99")
        self.assertEqual(self.account(99, known=False), "99")


if __name__ == "__main__":
    unittest.main()
