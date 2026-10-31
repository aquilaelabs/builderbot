"""Other disks and shares (R162 step 4): the controller's record held to
its shapes with a share's password sealed and never listed, the hello's
copy with it opened, and the agent mounting what the record says and
unmounting what it no longer says, an SMB share's credentials root's
alone."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import agentpkg  # noqa: E402
import extmounts  # noqa: E402


class TheRecord(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        extmounts.configure(state=self.d, write_json=lambda p, v: open(p, "w").write(json.dumps(v)),
                            seal=lambda b: b"S" + b[::-1], unseal=lambda b: b[1:][::-1], sealing=lambda: True)

    def test_held_to_its_shapes_sealed_and_handed_over_opened(self):
        self.assertIn("a disk, an SMB share", extmounts.set_mount({"kind": "tape", "name": "x"})["error"])
        self.assertIn("name is a letter", extmounts.set_mount({"kind": "disk", "name": "Bad Name", "source": "usb-X"})["error"])
        self.assertIn("by-id link", extmounts.set_mount({"kind": "disk", "name": "backup", "source": "../etc"})["error"])
        self.assertIn("host it is on", extmounts.set_mount({"kind": "smb", "name": "media", "host": "", "path": "media"})["error"])
        self.assertIn("from /", extmounts.set_mount({"kind": "nfs", "name": "exp", "host": "nas", "path": "export"})["error"])
        r = extmounts.set_mount({"kind": "smb", "name": "media", "host": "nas.local", "path": "media", "user": "ada", "password": "hunter22", "ro": True})
        m = r["mount"]
        self.assertEqual((m["kind"], m["name"], m["host"], m["path"], m["user"], m["ro"], m["on"], m["password_set"]), ("smb", "media", "nas.local", "media", "ada", True, True, True))
        self.assertNotIn("password", m)
        on_disk = json.load(open(os.path.join(self.d, "extmounts.json")))["mounts"][0]["password"]
        self.assertTrue(on_disk.startswith("sealed:") and "hunter22" not in on_disk)
        self.assertEqual(extmounts.wanted()[0]["password"], "hunter22")
        self.assertNotIn("password", extmounts.rows()[0])
        self.assertIn("taken by another", extmounts.set_mount({"kind": "nfs", "name": "media", "host": "nas", "path": "/x"})["error"])
        r2 = extmounts.set_mount({"id": m["id"], "ro": False})
        self.assertEqual((r2["mount"]["ro"], r2["mount"]["password_set"]), (False, True), "a change keeps the password")
        self.assertEqual(extmounts.turn(m["id"], False)["mount"]["on"], False)
        d = extmounts.set_mount({"kind": "disk", "name": "backup", "source": "usb-Seagate_Expansion_NA1234-0:0"})["mount"]
        self.assertEqual([x["name"] for x in extmounts.wanted()], ["media", "backup"])
        self.assertTrue(extmounts.remove(d["id"])["ok"])
        self.assertIn("no such", extmounts.remove("x_none")["error"])

    def test_seal_all_seals_what_was_kept_plain(self):
        extmounts.configure(state=self.d, write_json=lambda p, v: open(p, "w").write(json.dumps(v)), seal=None, unseal=None, sealing=lambda: False)
        extmounts.set_mount({"kind": "smb", "name": "media", "host": "nas", "path": "media", "password": "plain"})
        self.assertEqual(json.load(open(os.path.join(self.d, "extmounts.json")))["mounts"][0]["password"], "plain")
        extmounts.configure(seal=lambda b: b"S" + b[::-1], unseal=lambda b: b[1:][::-1], sealing=lambda: True)
        self.assertEqual(extmounts.seal_all(), 1)
        self.assertTrue(json.load(open(os.path.join(self.d, "extmounts.json")))["mounts"][0]["password"].startswith("sealed:"))
        self.assertEqual(extmounts.wanted()[0]["password"], "plain")


class TheAgent(unittest.TestCase):
    def setUp(self):
        self.agent = agentpkg.load("builderbot_agent_extmounts")
        self.em = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".extmounts"]
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.root, self.creds, self.byid = [os.path.join(self.d, x) for x in ("other", "creds", "by-id")]
        for p in (self.root, self.byid):
            os.makedirs(p)
        open(os.path.join(self.byid, "usb-Seagate_NA1-0:0"), "w").write("")
        open(os.path.join(self.byid, "usb-Seagate_NA1-0:0-part1"), "w").write("")
        self.env = {"BB_OTHER_ROOT": self.root, "BB_CREDS": self.creds, "BB_BY_ID": self.byid}
        em = self.em

        class A(em.ExtMountsMixin):
            def __init__(self):
                self.state = {}
        self.A = A
        self.mounted = set()
        self.runs = []

        def run(argv, **kw):
            self.runs.append(argv)
            if argv[0] == "mount":
                self.mounted.add(argv[-1] if "-o" not in argv or argv[-2] != "-o" else argv[argv.index("-o") - 1])
            if argv[0] == "umount":
                self.mounted.discard(argv[-1])
            return mock.Mock(returncode=0, stdout="", stderr="")
        self.run = run

    def test_the_record_is_mounted_unmounted_and_the_credentials_are_roots(self):
        a = self.A()
        rows = [{"id": "x_1", "kind": "disk", "name": "backup", "source": "usb-Seagate_NA1-0:0", "on": True, "ro": False},
                {"id": "x_2", "kind": "smb", "name": "media", "host": "nas", "path": "media", "user": "ada", "password": "hunter22", "on": True, "ro": True},
                {"id": "x_3", "kind": "nfs", "name": "exp", "host": "nas", "path": "/export", "on": False},
                {"id": "x_4", "kind": "disk", "name": "gone", "source": "usb-Nope-0:0", "on": True}]
        with mock.patch.dict(os.environ, self.env), mock.patch.object(self.em.os, "geteuid", return_value=0), mock.patch.object(self.em, "save_state"), \
             mock.patch.object(self.em.subprocess, "run", side_effect=self.run), mock.patch.object(self.em.shutil, "which", side_effect=lambda t: t), \
             mock.patch.object(self.em.os.path, "ismount", side_effect=lambda p: p in self.mounted):
            a.ext_mounts_want(rows)
            self.assertEqual(self.runs[0], ["mount", "-o", "nosuid,nodev", os.path.join(self.byid, "usb-Seagate_NA1-0:0-part1"), f"{self.root}/backup"])
            self.assertEqual(self.runs[1][:4], ["mount", "-t", "cifs", "//nas/media"])
            self.assertIn("credentials=" + os.path.join(self.creds, "media"), self.runs[1][-1])
            self.assertIn(",ro", self.runs[1][-1])
            self.assertEqual(len(self.runs), 2, "the one off is left alone, the one not plugged in waits")
            self.assertEqual(open(os.path.join(self.creds, "media")).read(), "username=ada\npassword=hunter22\n")
            self.assertEqual(oct(os.stat(os.path.join(self.creds, "media")).st_mode & 0o777), "0o600")
            n = len(self.runs)
            a.ext_mounts_want(rows)
            self.assertEqual(len(self.runs), n, "the same record again mounts nothing twice")
            self.assertEqual([(m["name"], m["mounted"], m["present"]) for m in self.em.extmounts_now(a.state)],
                             [("backup", True, True), ("media", True, True), ("exp", False, True), ("gone", False, False)])
            # Eject: the disk's row off; and the share dropped from the record.
            rows[0]["on"] = False
            a.ext_mounts_want(rows[:1] + rows[2:])
            self.assertIn(["umount", f"{self.root}/backup"], self.runs)
            self.assertIn(["umount", f"{self.root}/media"], self.runs)
            self.assertFalse(os.path.exists(os.path.join(self.creds, "media")), "its credentials go with it")
            self.assertFalse(os.path.isdir(f"{self.root}/media"))


if __name__ == "__main__":
    unittest.main()
