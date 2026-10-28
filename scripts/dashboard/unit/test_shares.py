"""SMB and NFS shares on the controller's own machine (R162 step 1): the
agent reads its two files whole into the census and writes them whole from
the storage-share job, each argument held to its shape, each user to the
machine's and the path to a folder under a pool; the controller keeps the
census's shares to their shape and queues the job for the own machine alone."""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import agentpkg  # noqa: E402

SMB = """# Written by BuilderBot
[media]
    path = /mnt/tank/media
    browseable = yes
    read only = no
    guest ok = yes
    force user = nobody

[docs]
    path = /mnt/tank/docs
    read only = yes
    guest ok = no
    valid users = bbu-0a1b2c3d ada
"""
NFS = """# Written by BuilderBot
/mnt/tank/media 192.168.1.0/24(rw,sync,no_subtree_check,root_squash) nas2(ro,sync,no_subtree_check,root_squash)
/mnt/tank/backup *(ro,sync,no_subtree_check,root_squash)
"""


class Job:
    def __init__(self):
        self.log = []

    def say(self, s):
        self.log.append(s)

    def step(self, s):
        self.log.append(f"[{s}]")

    def text(self):
        return "".join(self.log)


class TheAgent(unittest.TestCase):
    def setUp(self):
        self.agent = agentpkg.load("builderbot_agent_shares")
        self.sm = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".shares"]
        self.d = tempfile.mkdtemp()
        self.smb = os.path.join(self.d, "samba", "builderbot.conf")
        self.nfs = os.path.join(self.d, "exports.d", "builderbot.exports")
        os.makedirs(os.path.dirname(self.smb)); os.makedirs(os.path.dirname(self.nfs))
        open(self.smb, "w").write(SMB); open(self.nfs, "w").write(NFS)
        self.env = {"BB_SMB_FILE": self.smb, "BB_NFS_FILE": self.nfs}
        sm = self.sm
        ran = self.ran = []

        class A(sm.SharesMixin):
            def _sh(self, job, argv, timeout=0, **kw):
                ran.append(argv)
                return 0

            def hello_again(self, why):
                self.said = why
        self.A = A

    def test_the_census_reads_both_files_as_one_list(self):
        with mock.patch.dict(os.environ, self.env):
            got = self.sm.shares_now()
        by = {s["name"]: s for s in got}
        self.assertEqual(set(by), {"media", "docs", "backup"})
        self.assertEqual(by["media"]["smb"], {"on": True, "guest": True, "ro": False, "users": []})
        self.assertEqual(by["media"]["nfs"], {"on": True, "ro": True, "clients": ["192.168.1.0/24", "nas2"]})
        self.assertEqual(by["docs"]["smb"]["users"], ["bbu-0a1b2c3d", "ada"])
        self.assertFalse(by["docs"]["nfs"]["on"])
        self.assertEqual((by["backup"]["smb"]["on"], by["backup"]["nfs"]["clients"]), (False, ["*"]))

    def run_job(self, cfg, users=("ada", "bbu-0a1b2c3d"), folders=("/mnt/tank/media", "/mnt/tank/docs", "/mnt/tank/photos")):
        job = Job()
        import pwd
        real_isdir = os.path.isdir
        with mock.patch.dict(os.environ, self.env), mock.patch.object(self.sm.os, "geteuid", return_value=0), \
             mock.patch.object(self.sm.os.path, "isdir", side_effect=lambda p: p in folders or (not p.startswith("/mnt/") and real_isdir(p))), \
             mock.patch.object(pwd, "getpwnam", side_effect=lambda u: u if u in users else (_ for _ in ()).throw(KeyError(u))), \
             mock.patch.object(self.sm.shutil, "which", side_effect=lambda n: "/usr/bin/" + n if n in ("smbcontrol", "exportfs") else None):
            state, code = self.A()._apply_storage_share(job, cfg)
        return state, code, job.text()

    def test_a_share_set_is_written_whole_and_the_daemons_told(self):
        state, code, text = self.run_job({"share": "set", "name": "photos", "path": "/mnt/tank/photos",
                                          "smb": {"on": True, "guest": False, "ro": False, "users": ["ada"]},
                                          "nfs": {"on": True, "ro": True, "clients": ["192.168.1.0/24"]}})
        self.assertEqual((state, code), ("succeeded", 0), text)
        smb, nfs = open(self.smb).read(), open(self.nfs).read()
        self.assertIn("[photos]\n    path = /mnt/tank/photos", smb)
        self.assertIn("valid users = ada", smb)
        self.assertIn("[media]", smb, "the shares before are kept")
        self.assertIn("/mnt/tank/photos 192.168.1.0/24(ro,sync,no_subtree_check,root_squash)", nfs)
        self.assertEqual([a[0] for a in self.ran], ["/usr/bin/smbcontrol", "/usr/bin/exportfs"])
        state, code, text = self.run_job({"share": "remove", "name": "media"})
        self.assertEqual(state, "succeeded", text)
        self.assertNotIn("[media]", open(self.smb).read())
        self.assertNotIn("/mnt/tank/media", open(self.nfs).read())

    def test_what_is_refused_writes_nothing(self):
        before = open(self.smb).read()
        for cfg, why in (({"share": "set", "name": "x", "path": "/home/ada", "smb": {"on": True, "guest": True}}, "under /mnt or /srv"),
                         ({"share": "set", "name": "x", "path": "/mnt/tank/nope", "smb": {"on": True, "guest": True}}, "that is here"),
                         ({"share": "set", "name": "x", "path": "/mnt/tank/photos"}, "SMB, NFS or both"),
                         ({"share": "set", "name": "x", "path": "/mnt/tank/photos", "smb": {"on": True, "users": ["zed"]}}, "not a user this machine has"),
                         ({"share": "set", "name": "x", "path": "/mnt/tank/photos", "smb": {"on": True, "users": []}}, "takes the users"),
                         ({"share": "set", "name": "x", "path": "/mnt/tank/photos", "nfs": {"on": True, "clients": ["bad client"]}}, "not a client"),
                         ({"share": "set", "name": "x", "path": "/mnt/tank/media", "smb": {"on": True, "guest": True}}, "shared already under another name"),
                         ({"share": "remove", "name": "nope"}, "no share called"),
                         ({"share": "set", "name": "bad name!", "path": "/mnt/tank/photos"}, "not a share name")):
            self.ran.clear()
            state, code, text = self.run_job(cfg)
            self.assertEqual(state, "failed", cfg)
            self.assertIn(why, text, cfg)
        self.assertEqual(open(self.smb).read(), before)
        self.assertEqual(self.ran, [])


class TheController(unittest.TestCase):
    def test_the_census_keeps_each_share_to_its_shape(self):
        import nodes
        got = nodes._census({"shares": [{"name": "media", "path": "/mnt/tank/media<b>", "smb": {"on": True, "guest": "yes", "ro": False, "users": ["ada", 7]},
                                         "nfs": {"on": True, "ro": True, "clients": ["192.168.1.0/24"]}}, {"name": "bad name"}]})
        self.assertEqual(got["shares"], [{"name": "media", "path": "/mnt/tank/mediab", "smb": {"on": True, "guest": False, "ro": False, "users": ["ada"]},
                                          "nfs": {"on": True, "ro": True, "clients": ["192.168.1.0/24"]}}])

    def test_the_verb_is_the_own_machines(self):
        import nodes
        nodes.configure(state=tempfile.mkdtemp())
        self.assertEqual(nodes.node_storage_share("user:t", "n_none", {"share": "remove", "name": "x"})["error"], "no such node")


if __name__ == "__main__":
    unittest.main()
