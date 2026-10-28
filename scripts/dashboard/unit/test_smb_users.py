"""SMB passwords for the accounts (R164 step 1): the NT hash Samba keeps,
set and cleared on Profile, handed to the own machine's hello, a share's
names resolved to Unix users, and the shares a person reaches."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import users  # noqa: E402


class SmbPasswords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        users.configure(state=self.tmp, write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
        with users._lock:
            d = users.load()
            d["users"]["ada"] = {"uid": "u_0a1b2c3d", "role": "admin", "projects": [], "password": "x", "created": 0, "seen": 0}
            d["users"]["bob"] = {"uid": "u_deadbeef", "role": "user", "roles": ["media"], "projects": [], "password": "x", "created": 0, "seen": 0}
            users._save(d)

    def test_the_hash_is_the_one_samba_keeps(self):
        # RFC 1320's vectors through the NT form, and the hash of "password" every tool prints.
        self.assertEqual(users.nt_hash("password"), "8846F7EAEE8FB117AD06BDD830B7586C")
        self.assertEqual(users.nt_hash(""), "31D6CFE0D16AE931B73C59D7E0C089C0")
        self.assertEqual(users._md4(b"abc").hex(), "a448017aaf21d8525fc10ae87aa6729d")
        self.assertEqual(users._md4(b"12345678901234567890123456789012345678901234567890123456789012345678901234567890").hex(),
                         "e33b4ddc9c38f2199c3e7b164fcc0536")

    def test_set_and_cleared_and_handed_over_as_the_unix_user(self):
        self.assertIn("8 characters", users.set_smb_password("ada", "short")["error"])
        self.assertIn("no account", users.set_smb_password("nobody", "longenough")["error"])
        self.assertEqual(users.set_smb_password("ada", "correct horse")["set"], True)
        self.assertEqual(users.smb_users(), [{"user": "bbu-0a1b2c3d", "nt": users.nt_hash("correct horse")}])
        self.assertNotIn("smb_nt", users.all_users()[0], "a listing never carries it")
        self.assertEqual(users.set_smb_password("ada", "")["set"], False)
        self.assertEqual(users.smb_users(), [])
        self.assertNotIn("smb_nt", users.get("ada"))

    def test_a_shares_names_resolve_to_unix_users(self):
        with mock.patch.object(users.roles, "roles_of", side_effect=lambda u: [u.get("role", "user")] + list(u.get("roles") or [])):
            self.assertEqual(users.smb_resolve(["ada", "role:media", "nas", " ", "ada"]), (["bbu-0a1b2c3d", "bbu-deadbeef", "nas"], ""))
            self.assertEqual(users.smb_resolve(["role:nobody-has-it"])[1], "nobody holds the role nobody-has-it")
            self.assertIn("not an account", users.smb_resolve(["Bad Name!"])[1])
        self.assertEqual(users.smb_names(), {"bbu-0a1b2c3d": "ada", "bbu-deadbeef": "bob"})

    def test_the_shares_a_person_reaches_with_the_address(self):
        import nodes
        own = {"id": "n1", "name": "nas", "kind": "agent", "config": {"own": True},
               "reported": {"hostname": "nas", "network": {"addresses": ["192.168.1.20/24"]}, "features": {"shares": {"smb": True}},
                            "shares": [{"name": "media", "smb": {"on": True, "guest": True, "ro": False, "tm": False, "users": []}},
                                       {"name": "docs", "smb": {"on": True, "guest": False, "ro": True, "tm": False, "users": ["bbu-0a1b2c3d"]}},
                                       {"name": "tm", "smb": {"on": True, "guest": False, "ro": False, "tm": True, "users": ["bbu-deadbeef"]}},
                                       {"name": "nfsonly", "smb": {"on": False}, "nfs": {"on": True}}]}}
        with mock.patch.object(nodes, "node_list", return_value=[{"id": "n0", "kind": "agent", "config": {}}, own]):
            got = nodes.smb_shares_for("u_0a1b2c3d")
            self.assertEqual((got["host"], got["address"]), ("nas", "192.168.1.20"))
            self.assertEqual([(r["name"], r["ro"], r["guest"]) for r in got["rows"]], [("media", False, True), ("docs", True, False)])
            self.assertEqual([r["name"] for r in nodes.smb_shares_for("u_deadbeef")["rows"]], ["media", "tm"])
        with mock.patch.object(nodes, "node_list", return_value=[{"id": "n0", "kind": "agent", "config": {}}]):
            self.assertIsNone(nodes.smb_shares_for("u_0a1b2c3d"), "no own machine: the section is not drawn")
        own["reported"]["features"] = {}
        with mock.patch.object(nodes, "node_list", return_value=[own]):
            self.assertIsNone(nodes.smb_shares_for("u_0a1b2c3d"), "an own machine without Samba: not drawn either")


if __name__ == "__main__":
    unittest.main()
