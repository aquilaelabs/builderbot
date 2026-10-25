"""A device sign-in's link as the page offers it (B235): Codex prints its
link in color, and the link must end where the color code begins, or the
page opens an address OpenAI answers with 'your session ended'."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import signin  # noqa: E402

CODEX = ("Welcome to Codex\n"
         "1. Open this link in your browser and sign in to your account\n"
         "   \x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n"
         "2. Enter this one-time code \x1b[90m(expires in 15 minutes)\x1b[0m\n"
         "   \x1b[94mABCD-EFGH2\x1b[0m\n")
COPILOT = "To authenticate, visit \x1b[1mhttps://github.com/login/device\x1b[0m and enter code 1A2B-3C4D.\n"

GROK = "Open \x1b[1mhttps://auth.x.ai/device\x1b[0m and enter the code WXYZ-9876 to sign in.\n"


class Link(unittest.TestCase):
    def test_codex_link_ends_at_its_color_code(self):
        m = signin.FLOWS["codex"]["url"].search(CODEX)
        self.assertEqual(m.group(0), "https://auth.openai.com/codex/device")
        self.assertEqual(signin.FLOWS["codex"]["code"].search(CODEX).group(1), "ABCD-EFGH2")

    def test_copilot_link_and_code(self):
        self.assertEqual(signin.FLOWS["copilot"]["url"].search(COPILOT).group(0), "https://github.com/login/device")
        self.assertEqual(signin.FLOWS["copilot"]["code"].search(COPILOT).group(1), "1A2B-3C4D")

    def test_grok_link_and_code(self):
        self.assertEqual(signin.FLOWS["grok"]["url"].search(GROK).group(0), "https://auth.x.ai/device")
        self.assertEqual(signin.FLOWS["grok"]["code"].search(GROK).group(1), "WXYZ-9876")

    def test_a_link_without_color_is_taken_whole(self):
        m = signin.FLOWS["codex"]["url"].search("open https://auth.openai.com/codex/device?x=1 now")
        self.assertEqual(m.group(0), "https://auth.openai.com/codex/device?x=1")


if __name__ == "__main__":
    unittest.main()
