"""Accounts as their own users on a node (R125): the sudo rule and the layout
say so only once the agent is ready, tmux goes to the server a session is on,
and bb-session holds each caller to its own account and refuses a terminal
that is not proven."""
import importlib.machinery
import importlib.util
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agentpkg  # noqa: E402
agent = agentpkg.load("account_users")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
_loader = importlib.machinery.SourceFileLoader("bb_session_r125", os.path.join(REPO, "nodes", "bb-session"))
_spec = importlib.util.spec_from_loader("bb_session_r125", _loader)
bbs = importlib.util.module_from_spec(_spec)
_loader.exec_module(bbs)


class Rules(unittest.TestCase):
    def test_the_rule_names_the_accounts_only_when_ready(self):
        self.assertNotIn("%bbu", agent.session_sudoers("builder"))
        rule = agent.session_sudoers("builder", True)
        self.assertIn("%bbu ALL=(root) NOPASSWD: /usr/local/sbin/bb-session enter *", rule)
        self.assertNotIn("tty", rule.split("%bbu", 1)[1], "an account's user may not start another's terminal")

    def test_the_layout_says_where_to_ask_and_what_to_run(self):
        st = {"stores": {}}
        self.assertNotIn("ACCOUNT_USERS", agent.session_conf(st, "builder"))
        conf = agent.session_conf(st, "builder", False, {"controller": "https://c:7680", "pin": "sha256:ab",
                                                         "bundle": "/usr/local/lib/builderbot/bundle/current"})
        for line in ("ACCOUNT_USERS=on", "CONTROLLER=https://c:7680", "CONTROLLER_PIN=sha256:ab",
                     "BUNDLE=/usr/local/lib/builderbot/bundle/current"):
            self.assertIn(line, conf)


class Tmux(unittest.TestCase):
    def setUp(self):
        self.a = object.__new__(agent.Agent)
        self.a.state = {}
        self.calls = []
        self.a.session_account = lambda: "builder"
        self.a._tmux_users = lambda: ["builder", "bbu-0000abcd"]

        def as_(user, argv, timeout=10, quiet=False):
            self.calls.append((user, argv[0]))
            return {"builder": "u_1111abcd~claude-web\n", "bbu-0000abcd": "u_0000abcd~claude-web\n"}.get(user) \
                if argv[0] == "list-sessions" else ("ok" if user == "bbu-0000abcd" else "")
        self.a._tmux_as = as_

    def test_a_session_of_an_account_goes_to_its_own_server(self):
        self.a._tmux(["send-keys", "-t", "u_0000abcd~claude-web", "Enter"])
        self.assertEqual(self.calls, [("bbu-0000abcd", "send-keys")])

    def test_a_listing_is_every_server_s(self):
        got = self.a._tmux(["list-sessions", "-F", "#{session_name}"])
        self.assertIn("u_1111abcd~claude-web", got)
        self.assertIn("u_0000abcd~claude-web", got)

    def test_one_with_no_account_of_its_own_stays_on_the_session_account_s(self):
        self.a._tmux(["send-keys", "-t", "=u_1111abcd~claude-web", "Enter"])
        self.assertEqual(self.calls, [("builder", "send-keys")])


class Caller(unittest.TestCase):
    def test_an_account_user_is_held_to_its_own_account(self):
        c = {"SESSION_USER": "builder", "ACCOUNT_USERS": "on"}
        pw = mock.Mock(pw_name="bbu-0000abcd", pw_uid=1201, pw_gid=1201)
        sa = mock.Mock(pw_name="builder", pw_uid=99, pw_gid=100)
        with mock.patch.object(bbs.os, "geteuid", return_value=0), \
                mock.patch.object(bbs, "account_user", lambda acct: pw if acct == "u_0000abcd" else None), \
                mock.patch.object(bbs.pwd, "getpwnam", return_value=sa), \
                mock.patch.dict(bbs.os.environ, {"SUDO_UID": "1201"}):
            self.assertEqual(bbs.caller(c, "u_0000abcd"), ("bbu-0000abcd", 1201, 1201))
            with self.assertRaises(bbs.Refused):
                bbs.caller(c, "u_1111abcd")

    def test_off_an_account_user_is_nobody(self):
        c = {"SESSION_USER": "builder", "ACCOUNT_USERS": ""}
        sa = mock.Mock(pw_name="builder", pw_uid=99, pw_gid=100)
        with mock.patch.object(bbs.os, "geteuid", return_value=0), \
                mock.patch.object(bbs.pwd, "getpwnam", return_value=sa), \
                mock.patch.dict(bbs.os.environ, {"SUDO_UID": "1201"}):
            with self.assertRaises(bbs.Refused):
                bbs.caller(c, "u_0000abcd")


class Tty(unittest.TestCase):
    def test_a_terminal_without_a_token_is_refused_before_anything_is_asked(self):
        c = {"ACCOUNT_USERS": "on", "HOME_ROOT": "/home/builder"}
        with mock.patch.object(bbs.os, "geteuid", return_value=0), \
                mock.patch.object(bbs, "_grant", side_effect=AssertionError("asked")):
            with self.assertRaises(bbs.Refused):
                bbs.tty(c, ["claude:web", "u:u_0000abcd"])

    def test_off_no_terminal_starts_this_way(self):
        with mock.patch.object(bbs.os, "geteuid", return_value=0):
            with self.assertRaises(bbs.Refused):
                bbs.tty({"ACCOUNT_USERS": ""}, ["claude:web", "tok:bbs_abcdefghij"])

    def test_the_controller_s_answer_names_the_account_and_nothing_else_does(self):
        c = {"ACCOUNT_USERS": "on", "HOME_ROOT": "/home/builder"}
        with mock.patch.object(bbs.os, "geteuid", return_value=0), \
                mock.patch.object(bbs, "_grant", return_value=(403, {"error": "not yours"})):
            with self.assertRaises(bbs.Refused) as e:
                bbs.tty(c, ["claude:web", "u:u_0000abcd", "tok:bbs_abcdefghij"])
        self.assertIn("not yours", str(e.exception))


if __name__ == "__main__":
    unittest.main()
