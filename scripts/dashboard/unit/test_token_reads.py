"""Who reads an account's coding-agent token on a node (R125 step 6): the
agent keeps the files at 600 and says a reader that is neither the account
nor itself; the controller audits each new one once and puts the newest on
the bell, where a dismissal holds until another."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import agentpkg  # noqa: E402
import bellseen  # noqa: E402
import nodes  # noqa: E402
agent = agentpkg.load("token_reads")
tw = agent.module("tokenwatch")


def write_json(path, d):
    with open(path, "w") as f:
        json.dump(d, f)


class Judge(unittest.TestCase):
    def test_the_account_and_the_agent_s_own_children_are_expected(self):
        procs = {500: (1201, 400, "claude"), 400: (0, 1, "bb-session"),
                 600: (0, 300, "python3"), 300: (0, 1, "builderbot-agent"),
                 700: (0, 1, "cat")}
        with mock.patch.object(tw, "_proc", lambda pid: procs.get(pid)):
            self.assertIsNone(tw.judge("/h/.claude/.credentials.json", 500, 1201, 300), "its own session")
            self.assertIsNone(tw.judge("/h/.claude/.credentials.json", 600, 1201, 300), "the agent's sign-in")
            got = tw.judge("/h/.claude/.credentials.json", 700, 1201, 300)
        self.assertEqual((got["comm"], got["uid"], got["pid"]), ("cat", 0, 700))

    def test_one_line_per_reader_and_file(self):
        w = tw.TokenWatch()
        with mock.patch.object(tw, "log") as log:
            for _ in range(3):
                w.said({"path": "/h/.codex/auth.json", "pid": 7, "comm": "cat", "uid": 0})
            w.said({"path": "/h/.codex/auth.json", "pid": 8, "comm": "less", "uid": 0})
        self.assertEqual([r["pid"] for r in w.report()], [7, 8])
        self.assertEqual(log.call_count, 2)


class Tighten(unittest.TestCase):
    def test_a_token_file_open_to_others_goes_back_to_600(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        os.makedirs(os.path.join(home, ".copilot"))
        f = os.path.join(home, ".copilot", "config.json")
        with open(f, "w") as fh:
            fh.write("{}")
        os.chmod(f, 0o644)
        w = tw.TokenWatch()
        w.why = "not started in a test"
        w.watch(home, SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()))
        self.assertEqual(os.stat(f).st_mode & 0o777, 0o600)


class Controller(unittest.TestCase):
    def read(self, at, pid=9, uid="u_0000abcd"):
        return {"at": at, "path": f"/home/builder/users/{uid}/.claude/.credentials.json",
                "pid": pid, "uid": 0, "comm": "cat"}

    def test_the_hello_s_reads_are_kept_with_their_account(self):
        kc = nodes.keep_clean({"said": [], "ok": 1, "reads": [self.read(100), "junk"]})
        self.assertEqual(kc["reads"][0]["account"], "u_0000abcd")
        self.assertEqual(len(kc["reads"]), 1)

    def test_each_read_is_audited_once(self):
        n = {"id": "n_1", "name": "box"}
        old = nodes.keep_clean({"reads": [self.read(100)]})
        new = nodes.keep_clean({"reads": [self.read(100), self.read(200, pid=10)]})
        with mock.patch.object(nodes, "audit") as audit:
            nodes.token_reads_audit(n, old, new)
        self.assertEqual(audit.call_count, 1)
        who, action, target, params = audit.call_args[0]
        self.assertEqual((who, action, target, params["pid"]), ("node:box", "token-read", "u_0000abcd", 10))

    def test_the_bell_says_the_newest_of_the_week_and_a_dismissal_holds_until_another(self):
        import time
        now = int(time.time())
        n = {"id": "n_1", "name": "box", "kind": "agent",
             "agent": {"keep": nodes.keep_clean({"reads": [self.read(now - 30 * 86400), self.read(now - 60, pid=11)]})}}
        with mock.patch.object(nodes, "node_list", return_value=[n]):
            rows = nodes.token_attention()
        self.assertEqual([(r["pid"], r["count"]) for r in rows], [(11, 1)])
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        bellseen.configure(state=tmp, write_json=write_json)
        out, _ = bellseen.filter_rows("u1", rows)
        bellseen.dismiss("u1", [out[0]["key"]])
        self.assertEqual(bellseen.filter_rows("u1", rows)[0], [])
        later = [dict(rows[0], at=now)]
        self.assertEqual(len(bellseen.filter_rows("u1", later)[0]), 1, "a newer read says it again")


class Mirror(unittest.TestCase):
    def test_an_account_s_copies_go_to_its_own_user_once_accounts_are(self):
        cs = agent.module("claudesync")
        m = object.__new__(cs.ClaudeMirror)
        m.agent = SimpleNamespace(account_users_on=lambda: True)
        m.wssync = SimpleNamespace(owner=lambda: (99, 100))
        pw = SimpleNamespace(pw_uid=1201, pw_gid=1201)
        with mock.patch.object(cs.os, "geteuid", return_value=0), \
                mock.patch.object(cs.pwd, "getpwnam", lambda name: pw if name == "bbu-0000abcd" else (_ for _ in ()).throw(KeyError(name))):
            self.assertEqual(m.owner("u_0000abcd"), (1201, 1201))
            self.assertEqual(m.owner("u_1111abcd"), (99, 100), "no user yet: the session account's")
            self.assertEqual(m.owner(), (99, 100))
        m.agent = SimpleNamespace(account_users_on=lambda: False)
        with mock.patch.object(cs.os, "geteuid", return_value=0):
            self.assertEqual(m.owner("u_0000abcd"), (99, 100), "the setting off: as before")


if __name__ == "__main__":
    unittest.main()
