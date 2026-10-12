"""Leaving a synced copy (R164): the agent's half. While the controller says
leaving it keeps sending and says what is left after a whole walk; told the
node is off with a clean-up token, it removes the copies, their records and
the conversations' folder once, answers by the token, and never removes
anything through a mount."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import agentpkg  # noqa: E402

AGENT = agentpkg.load("sync_leave")
node_sync = AGENT.module("wssync")


class Ctl:
    def __init__(self):
        self.answer = {"mode": "sync", "projects": {}, "reads": {}}

    def call(self, verb, body, timeout=0):
        assert verb == "sync" and body.get("action") == "projects", (verb, body)
        return 200, json.loads(json.dumps(self.answer))


class Agent:
    def __init__(self, data):
        self.state = {"stores": {"data": data}}
        self.ctl = Ctl()
        self.hello_at = 1

    def hello_again(self, why):
        self.hello_at = 0

    def session_account(self):
        return ""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class Leave(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="syncleave-")
        self.ws = os.path.join(self.tmp, "workspace")
        self.data = os.path.join(self.tmp, "data")
        self.agent = Agent(self.data)
        self.s = node_sync.WorkspaceSync(self.agent, root=self.ws)
        rd = self.s.record_dir()
        for name in ("alpha", "beta"):
            write(os.path.join(self.ws, name, "a.txt"), "x" * 5000)
            write(os.path.join(rd, name + ".json"), json.dumps({"rev": 1, "ready": True, "files": {}}))
        write(os.path.join(self.ws, ".claude", "u_0123abcd", "projects", "-workspace-alpha", "c.jsonl"), "{}\n")
        write(os.path.join(rd, "claude.json"), "{}")
        write(os.path.join(self.ws, "not-a-copy", "keep.txt"), "made by hand\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ask(self, **answer):
        self.agent.ctl.answer = {"projects": {}, "reads": {}, **answer}
        self.s.asked_at = 0.0
        self.s.step()

    def test_leaving_is_reported_and_ends(self):
        self.assertIsNone(self.s.drain(), "nothing to say while not leaving")
        self.ask(mode="sync", leaving=True)
        d = self.s.drain()
        self.assertEqual(d["files"], 0)
        self.ask(mode="sync")
        self.assertIsNone(self.s.drain(), "...and nothing once the controller stops saying it")

    def test_off_with_a_token_cleans_once(self):
        self.ask(mode="off", clean="t1")
        for name in ("alpha", "beta", ".claude"):
            self.assertFalse(os.path.exists(os.path.join(self.ws, name)), name)
        self.assertTrue(os.path.exists(os.path.join(self.ws, "not-a-copy", "keep.txt")),
                        "only what a record names is removed")
        self.assertEqual(sorted(os.listdir(self.s.record_dir())), [])
        done = self.s.done()
        self.assertEqual(done["token"], "t1")
        self.assertEqual(done["error"], "")
        self.assertGreater(done["freed"], 0)
        # Asked again by the same token: answered, not done twice.
        write(os.path.join(self.ws, "alpha", "new.txt"), "after\n")
        self.ask(mode="off", clean="t1")
        self.assertTrue(os.path.exists(os.path.join(self.ws, "alpha", "new.txt")))

    def test_no_clean_without_a_token_or_in_sync(self):
        self.ask(mode="off")
        self.assertTrue(os.path.isdir(os.path.join(self.ws, "alpha")))
        self.ask(mode="sync", clean="t2")
        self.assertTrue(os.path.isdir(os.path.join(self.ws, "alpha")))

    def test_never_through_a_mount(self):
        real = node_sync.os.path.ismount
        node_sync.os.path.ismount = lambda p: p == self.ws or real(p)
        try:
            self.ask(mode="off", clean="t3")
        finally:
            node_sync.os.path.ismount = real
        self.assertTrue(os.path.isdir(os.path.join(self.ws, "alpha")))
        self.assertIn("mounted", self.s.done()["error"])


if __name__ == "__main__":
    unittest.main()
