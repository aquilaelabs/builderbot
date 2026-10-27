"""Grok Build's sign-in sealed beside Claude's and Codex's (R126 step 3):
its file is one of the sealed ones, and its seal's header names the
account its token's claims name, or that it is an xAI account."""
import base64
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agentpkg  # noqa: E402

tokens = agentpkg.load("tokens")


def _jwt(claims):
    part = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{part}.sig"


class GrokSeal(unittest.TestCase):
    def test_its_session_file_is_sealed(self):
        self.assertIn(("grok", os.path.join(".grok", "auth.json")), tokens.FILES)

    def test_the_header_names_whose_it_is(self):
        data = json.dumps({"session": {"access": _jwt({"email": "pat@example.invalid"})}}).encode()
        self.assertEqual(tokens.about("grok", data, "/nowhere")["email"], "pat@example.invalid")
        self.assertEqual(tokens.about("grok", b'{"key": "x"}', "/nowhere")["email"], "an xAI account")


if __name__ == "__main__":
    unittest.main()
