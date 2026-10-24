"""Copilot CLI's sign-in on a machine with no keyring asks whether to keep
its token in its config file, after the device is approved, and waits on
the answer; the agent's sign-in answers it, and says so (the operator, 23
Oct: the sign-in hung after GitHub said the device was connected)."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agentpkg  # noqa: E402
agent = agentpkg.load("login_copilot")

# A stand-in for `bb login --flow --agent copilot`: the link, then Copilot's
# question, then what it was told, written where the test can read it.
FAKE = """#!/bin/bash
echo "To authenticate, visit https://github.com/login/device and enter code ABCD-1234"
printf 'Store token in plaintext config file? (y/N) '
read -r answer
printf '%s' "$answer" > "ANSWER_TO"
echo "Signed in."
"""


class FakeAgent:
    def __init__(self, into):
        self.into = into
        self.state = {"name": "shed", "controller": "http://c"}

    def session_account(self):
        return "builder"

    def as_user(self, env, user):
        return {}

    def bundle(self, job, who):
        return self.into


class CopilotLogin(unittest.TestCase):
    def test_the_plain_text_question_is_answered_yes_and_said(self):
        into = tempfile.mkdtemp()
        os.makedirs(os.path.join(into, "scripts"))
        answer = os.path.join(into, "answer")
        # The flow runs with the agent's own environment, so the stand-in is
        # told where to write in its text.
        with open(os.path.join(into, "scripts", "bb"), "w") as f:
            f.write(FAKE.replace("ANSWER_TO", answer))
        job = agent.Job(FakeAgent(into), {"id": "j_1", "type": "copilot-login", "spec": {}})
        job.flush = lambda keepalive=False: True
        state, code = job.claude_login({"uid": "u_0000abcd", "timeout": 20}, "copilot")
        said = "".join(c["chunk"] for c in job.pending)
        with open(answer) as f:
            self.assertEqual(f.read(), "y")
        self.assertEqual((state, code), ("succeeded", 0))
        self.assertIn("Copilot keeps its token in ~/.copilot/config.json", said)


if __name__ == "__main__":
    unittest.main()
