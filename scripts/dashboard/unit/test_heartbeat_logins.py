"""What a node's heartbeat says about each account's coding agent sign-ins
(channel._logins, B236): a login the node read is recorded, one it found no
file for is a sign-out, and one it could not read changes nothing."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import channel  # noqa: E402
import claudegrant  # noqa: E402

UID = "u_0123abcd"


class HeartbeatLogins(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        was = channel.home_for
        self.addCleanup(setattr, channel, "home_for", was)
        channel.home_for = lambda uid: self.home
        self.addCleanup(channel._unread.clear)

    def beat(self, agents_said):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            channel._logins("n1", [{"uid": UID, "email": "", "agents": agents_said}])
        return out.getvalue()

    def test_a_login_read_is_recorded(self):
        self.beat({"codex": {"email": "me@example.com", "plan": "plus"}})
        self.assertEqual(claudegrant.on(self.home, "n1", "codex")["email"], "me@example.com")

    def test_no_login_file_is_a_sign_out_and_says_so(self):
        claudegrant.report(self.home, "n1", "me@example.com", agent="codex")
        said = self.beat({})
        self.assertEqual(claudegrant.on(self.home, "n1", "codex"), {})
        self.assertIn("reports codex signed out", said)

    def test_a_login_the_node_could_not_read_keeps_the_record_and_is_logged_once(self):
        claudegrant.report(self.home, "n1", "me@example.com", agent="codex")
        said = self.beat({"codex": {"error": "PermissionError: denied"}})
        self.assertEqual(claudegrant.on(self.home, "n1", "codex")["email"], "me@example.com")
        self.assertIn("could not read", said)
        self.assertEqual(self.beat({"codex": {"error": "PermissionError: denied"}}), "")


if __name__ == "__main__":
    unittest.main()
