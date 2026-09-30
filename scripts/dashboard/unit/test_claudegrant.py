"""claudegrant.py: one Anthropic account per BuilderBot account, enforced by
what nodes report, and a sign-out that reaches every node by moving a
generation. It was in no suite at all (R86)."""
import os
import shutil
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import claudegrant  # noqa: E402


class Grant(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)

    def test_a_fresh_account_is_signed_in_nowhere(self):
        st = claudegrant.state(self.home)
        self.assertEqual((st["signed_in"], st["email"], st["gen"], st["nodes"]), (False, "", 0, {}))
        self.assertFalse(claudegrant.state("")["signed_in"])

    def test_the_first_report_binds_and_the_same_account_may_join(self):
        self.assertTrue(claudegrant.report(self.home, "n1", "Me@Example.com", "max")["ok"])
        self.assertTrue(claudegrant.report(self.home, "n2", "me@example.com")["ok"])
        st = claudegrant.state(self.home)
        self.assertEqual(st["email"], "Me@Example.com")
        self.assertEqual(sorted(st["nodes"]), ["n1", "n2"])
        self.assertEqual(st["plan"], "max")

    def test_a_second_anthropic_account_is_refused_and_not_recorded(self):
        claudegrant.report(self.home, "n1", "me@example.com")
        r = claudegrant.report(self.home, "n2", "someone@else.com")
        self.assertIn("error", r)
        self.assertNotIn("n2", claudegrant.state(self.home)["nodes"])

    def test_a_node_signing_out_alone_keeps_the_binding(self):
        claudegrant.report(self.home, "n1", "me@example.com")
        claudegrant.report(self.home, "n1", "", signed_in=False)
        st = claudegrant.state(self.home)
        self.assertEqual((st["signed_in"], st["email"]), (False, "me@example.com"))
        self.assertIn("error", claudegrant.report(self.home, "n2", "other@x.com"))

    def test_sign_out_moves_the_generation_and_frees_the_binding(self):
        claudegrant.report(self.home, "n1", "me@example.com")
        r = claudegrant.sign_out(self.home)
        self.assertEqual((r["gen"], r["was"], r["nodes"]), (1, "me@example.com", ["n1"]))
        st = claudegrant.state(self.home)
        self.assertEqual((st["gen"], st["email"], st["nodes"]), (1, "", {}))
        self.assertTrue(claudegrant.report(self.home, "n2", "other@x.com")["ok"])

    def test_a_report_must_say_its_node_and_account(self):
        self.assertIn("error", claudegrant.report(self.home, "", "me@example.com"))
        self.assertIn("error", claudegrant.report(self.home, "n1", ""))
        self.assertIn("error", claudegrant.report("", "n1", "me@example.com"))

    def test_the_record_is_the_accounts_own(self):
        claudegrant.report(self.home, "n1", "me@example.com")
        mode = stat.S_IMODE(os.stat(os.path.join(self.home, ".claude", claudegrant.MARK)).st_mode)
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
