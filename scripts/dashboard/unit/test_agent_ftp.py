"""The node agent's half of a project's file access (FtpServers, R151): a
bb-ftpd started per project hello names, each login it asks relayed to the
controller's ftp-auth and the answer handed back down its stdin, a server
for a project no longer named stopped, and a node without the toolchain
said as such. The bb-ftpd here is a stand-in on PATH that asks one login
and writes down the answer, so this runs without pyftpdlib."""
import json
import os
import shutil
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import agentpkg  # noqa: E402
agent = agentpkg.load("builderbot_agent_ftp")
agent.log = lambda *a, **k: None

STAND_IN = """#!/usr/bin/env python3
import json, os, sys, time
a = sys.argv[1:]
root, out = a[a.index("--root") + 1], os.environ["FTP_OUT"]
sys.stderr.write("bb-ftpd: listening on x:" + a[a.index("--port") + 1] + "\\n"); sys.stderr.flush()
sys.stdout.write(json.dumps({"id": 1, "user": "ann", "password": "pw", "addr": "10.0.0.5"}) + "\\n"); sys.stdout.flush()
ans = sys.stdin.readline()
with open(os.path.join(out, os.path.basename(root) + ".json"), "w") as f:
    f.write(ans)
time.sleep(60)
"""


class Ctl:
    def __init__(self):
        self.calls = []

    def call(self, verb, body=None, timeout=30):
        self.calls.append((verb, body))
        if verb == "ftp-auth":
            return 200, {"access": "rw" if body["password"] == "pw" else ""}
        return 200, {}


class Fake:
    def __init__(self, state):
        self.state, self.ctl, self.hello_at = state, Ctl(), 1

    def hello_again(self, why):
        self.hello_at = 0

    def as_user(self, env, user):
        return {}

    def session_account(self):
        return ""

    def session_bind(self):
        return "127.0.0.1"


class AgentFtp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = os.path.join(self.tmp, "bin")
        self.out = os.path.join(self.tmp, "out")
        self.root = os.path.join(self.tmp, "alpha")
        for d in (self.bin, self.out, self.root):
            os.makedirs(d)
        self.saved = agent.sdk_env
        self.addCleanup(setattr, agent, "sdk_env", self.saved)
        agent.sdk_env = lambda state, who=None: {"PATH": self.bin + ":/usr/bin:/bin", "HOME": self.tmp,
                                                 "FTP_OUT": self.out}
        self.fake = Fake({})
        self.ftp = agent.FtpServers(self.fake)
        self.addCleanup(self.ftp.stop_all)

    def put_stand_in(self):
        p = os.path.join(self.bin, "bb-ftpd")
        with open(p, "w") as f:
            f.write(STAND_IN)
        os.chmod(p, 0o755)

    def wait_for(self, path, s=10):
        end = time.time() + s
        while time.time() < end:
            if os.path.exists(path) and os.path.getsize(path):
                return True
            time.sleep(0.05)
        return False

    def test_a_login_is_asked_of_the_controller_and_answered(self):
        self.put_stand_in()
        self.ftp.wanted = [{"project": "alpha", "port": 2121, "root": self.root}]
        self.ftp.apply()
        self.assertTrue(self.wait_for(os.path.join(self.out, "alpha.json")))
        with open(os.path.join(self.out, "alpha.json")) as f:
            self.assertEqual(json.load(f), {"id": 1, "access": "rw", "why": ""})
        asked = [b for v, b in self.fake.ctl.calls if v == "ftp-auth"]
        self.assertEqual(asked, [{"project": "alpha", "user": "ann", "password": "pw", "addr": "10.0.0.5"}])
        said = [b for v, b in self.fake.ctl.calls if v == "ftp"][-1]
        self.assertEqual(said["servers"][0]["up"], True)

    def test_a_project_no_longer_named_is_stopped(self):
        self.put_stand_in()
        self.ftp.wanted = [{"project": "alpha", "port": 2121, "root": self.root}]
        self.ftp.apply()
        proc = self.ftp.procs["alpha"]["proc"]
        self.ftp.wanted = []
        self.ftp.apply()
        self.assertIsNotNone(proc.poll())
        self.assertEqual([b for v, b in self.fake.ctl.calls if v == "ftp"][-1], {"servers": []})

    def test_without_the_toolchain_it_says_so(self):
        self.ftp.wanted = [{"project": "alpha", "port": 2121, "root": self.root}]
        self.ftp.apply()
        row = [b for v, b in self.fake.ctl.calls if v == "ftp"][-1]["servers"][0]
        self.assertFalse(row["up"])
        self.assertIn("ftp toolchain is not installed", row["why"])


if __name__ == "__main__":
    unittest.main()
