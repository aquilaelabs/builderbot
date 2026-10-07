"""A project's file access over FTP (ftp.py, R151): the settings' checks,
what a node is told to run, the login the node relays, and who may set it
(the ftp grant, named only)."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ftp  # noqa: E402
import roles  # noqa: E402
import users  # noqa: E402


def write_json(p, d, mode=0o644):
    Path(p).write_text(json.dumps(d))


class Ftp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        ws = Path(self.tmp) / "ws"
        for p in ("alpha", "beta", "gamma"):
            (ws / p).mkdir(parents=True)
        users.configure(state=self.tmp, write_json=write_json)
        roles.configure(state=self.tmp, write_json=write_json)
        pw = users.hash_password("password1", iterations=1000)
        with users._lock:
            d = users.load()
            d["users"] = {
                "boss": {"uid": "u_1", "role": "owner", "projects": ["alpha", "beta", "gamma"], "password": pw},
                "adm": {"uid": "u_2", "role": "admin", "projects": ["alpha"], "password": pw},
                "ann": {"uid": "u_3", "role": "user", "projects": ["alpha"], "password": pw},
                "bob": {"uid": "u_4", "role": "user", "projects": ["beta"], "password": pw},
            }
            users._save(d)
        self.nodes = {"alpha": "n1", "beta": "n1", "gamma": "n2"}
        self.audited = []
        self.hellos = []
        ftp.configure(state=self.tmp, workspace=ws, write_json=write_json, users=users,
                      audit=lambda *a: self.audited.append(a), project_node=lambda p: self.nodes.get(p, ""),
                      ask_hello=self.hellos.append)
        ftp._fails.clear()
        ftp._status.clear()

    def test_turning_it_on_offers_a_free_port_and_tells_the_node(self):
        v, code = ftp.save("alpha", {"on": True}, "boss")
        self.assertEqual(code, 200)
        self.assertEqual((v["on"], v["port"]), (True, 2121))
        self.assertEqual(self.hellos, ["n1"])
        self.assertEqual(ftp.for_node("n1"), [{"project": "alpha", "port": 2121, "root": "/workspace/alpha"}])
        self.assertEqual(ftp.for_node("n2"), [])
        # beta on the same node is offered the next free block, gamma on
        # another node the same port as alpha.
        self.assertEqual(ftp.save("beta", {"on": True}, "boss")[0]["port"], 2131)
        self.assertEqual(ftp.save("gamma", {"on": True}, "boss")[0]["port"], 2121)

    def test_ports_are_checked(self):
        ftp.save("alpha", {"on": True, "port": 3000}, "boss")
        for port, said in [(80, "a port from 1024"), (65530, "a port from 1024"),
                           (7675, "session terminal"), (3005, "alpha uses 3000 to 3009")]:
            j, code = ftp.save("beta", {"on": True, "port": port}, "boss")
            self.assertEqual(code, 400, port)
            self.assertIn(said, j["error"])
        self.assertEqual(ftp.save("beta", {"on": True, "port": 3010}, "boss")[1], 200)
        self.assertEqual(ftp.save("gamma", {"on": True, "port": 3005}, "boss")[1], 200, "another node")

    def test_a_project_with_no_node_cannot_be_turned_on(self):
        self.nodes["alpha"] = ""
        j, code = ftp.save("alpha", {"on": True}, "boss")
        self.assertEqual(code, 400)
        self.assertIn("no node", j["error"])

    def test_access_is_kept_per_account_and_an_unknown_one_is_dropped(self):
        ftp.save("alpha", {"on": True, "access": {"u_3": "r", "u_2": "rw", "u_9": "rw", "u_1": "x"}}, "boss")
        self.assertEqual(ftp.get("alpha")["access"], {"u_3": "r", "u_2": "rw"})
        ftp.save("alpha", {"access": {"u_3": ""}}, "boss")
        self.assertEqual(ftp.get("alpha")["access"], {"u_2": "rw"})
        names = [p["name"] for p in ftp.view("alpha", True)["people"]]
        self.assertEqual(names, ["adm", "ann", "boss"], "the accounts that see alpha; bob does not")

    def test_a_login_answers_the_access_and_nothing_else(self):
        ftp.save("alpha", {"on": True, "access": {"u_3": "r", "u_2": "rw"}}, "boss")
        self.assertEqual(ftp.login("n1", "alpha", "ann", "password1", "10.0.0.5"), {"access": "r"})
        self.assertEqual(ftp.login("n1", "alpha", "adm", "password1", "10.0.0.5"), {"access": "rw"})
        self.assertEqual(ftp.login("n1", "alpha", "ann", "wrong", "10.0.0.5")["access"], "")
        self.assertIn("no file access", ftp.login("n1", "alpha", "boss", "password1", "10.0.0.5")["why"])
        # Asked by a node that is not alpha's, or with it turned off: refused.
        self.assertEqual(ftp.login("n2", "alpha", "ann", "password1", "10.0.0.5")["access"], "")
        ftp.save("alpha", {"on": False}, "boss")
        self.assertEqual(ftp.login("n1", "alpha", "ann", "password1", "10.0.0.5")["access"], "")
        self.assertTrue(any(a[1] == "ftp-login" for a in self.audited))
        self.assertTrue(any(a[1] == "ftp-login-failed" for a in self.audited))

    def test_an_account_taken_off_the_project_loses_its_access(self):
        ftp.save("alpha", {"on": True, "access": {"u_3": "rw"}}, "boss")
        with users._lock:
            d = users.load()
            d["users"]["ann"]["projects"] = []
            users._save(d)
        self.assertEqual(ftp.login("n1", "alpha", "ann", "password1", "a")["access"], "")

    def test_failed_logins_are_throttled_per_address(self):
        ftp.save("alpha", {"on": True, "access": {"u_3": "r"}}, "boss")
        for _ in range(ftp.FAIL_LIMIT):
            ftp.login("n1", "alpha", "ann", "nope", "10.0.0.9")
        got = ftp.login("n1", "alpha", "ann", "password1", "10.0.0.9")
        self.assertEqual(got["access"], "")
        self.assertIn("Too many", got["why"])
        self.assertEqual(ftp.login("n1", "alpha", "ann", "password1", "10.0.0.8"), {"access": "r"})

    def test_what_the_node_says_is_shown(self):
        ftp.save("alpha", {"on": True}, "boss")
        ftp.report("n1", [{"project": "alpha", "up": False, "why": "the ftp toolchain is not installed", "port": 2121}])
        self.assertIn("not installed", ftp.view("alpha", True)["status"]["why"])

    def test_the_grant_is_the_owners_alone_and_never_a_sessions(self):
        self.assertEqual(users.may(users.get("boss"), "ftp", "alpha"), "")
        self.assertIn("owner", users.may(users.get("adm"), "ftp", "alpha"), "named only: an admin is refused")
        self.assertNotEqual(users.may(users.get("ann"), "ftp", "alpha"), "")
        sess = {"name": "session:alpha", "role": "owner", "projects": ["alpha"], "session": "alpha", "uid": "u_1"}
        self.assertIn("session", users.may(sess, "ftp", "alpha"))
        roles.set_role("files", [{"cap": "ftp", "scope": ["alpha"]}])
        with users._lock:
            d = users.load()
            d["users"]["adm"]["roles"] = ["admin", "files"]
            users._save(d)
        self.assertEqual(users.may(users.get("adm"), "ftp", "alpha"), "", "a role that names ftp grants it")


if __name__ == "__main__":
    unittest.main()
