"""The array (R162 step 2): the agent renders snapraid.conf and the fstab
lines from its record, reads the array into the census, and holds the
storage-array job to its shapes (a parity disk at least as large as the
largest data disk, no held disk without wipe, never the system disk) before
mkfs, mergerfs or SnapRAID run; the controller keeps the census's array
to its shape and queues the job for the own machine alone."""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import agentpkg  # noqa: E402

DISKS = [{"name": "sda", "model": "WDC", "serial": "A", "size_mb": 3815447, "system": False, "holds": "nothing", "parts": []},
         {"name": "sdb", "model": "WDC", "serial": "B", "size_mb": 1907729, "system": False, "holds": "nothing", "parts": []},
         {"name": "sdc", "model": "WDC", "serial": "C", "size_mb": 3815447, "system": False, "holds": "nothing", "parts": []},
         {"name": "sdd", "model": "WDC", "serial": "D", "size_mb": 7630885, "system": False, "holds": "", "parts": [{"name": "sdd1", "holds": "ext4, not mounted"}]},
         {"name": "nvme0n1", "model": "SSD", "serial": "S", "size_mb": 488386, "system": True, "holds": "", "parts": [{"name": "nvme0n1p2", "holds": "squashfs at /"}]}]
REC = {"policy": "epmfs", "data": [{"slot": 1, "id": "ata-WDC_A", "uuid": "1111", "fs": "xfs"}, {"slot": 2, "id": "ata-WDC_B", "uuid": "2222", "fs": "xfs"}],
       "parity": [{"slot": 1, "id": "ata-WDC_C", "uuid": "3333", "fs": "xfs"}]}


class Job:
    def __init__(self):
        self.log = []

    def say(self, s):
        self.log.append(s)

    def text(self):
        return "".join(self.log)


class TheAgent(unittest.TestCase):
    def setUp(self):
        self.agent = agentpkg.load("builderbot_agent_array")
        self.am = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".array"]
        self.d = tempfile.mkdtemp()
        self.env = {"BB_ARRAY_RECORD": os.path.join(self.d, "array.json"), "BB_ARRAY_STATE": os.path.join(self.d, "state.json"),
                    "BB_ARRAY_FSTAB": os.path.join(self.d, "fstab"), "BB_SNAPRAID_CONF": os.path.join(self.d, "snapraid.conf")}
        open(self.env["BB_ARRAY_FSTAB"], "w").write("UUID=root / ext4 defaults 0 1\n")
        am = self.am
        ran = self.ran = []

        class A(am.ArrayMixin):
            def _sh(self, job, argv, timeout=0, **kw):
                ran.append(argv)
                return 0

            def hello_again(self, why):
                self.said = why
        self.A = A

    def test_the_files_are_rendered_from_the_record(self):
        conf = self.am.render_snapraid(REC)
        self.assertIn("parity /mnt/parity/p1/snapraid.parity\n", conf)
        self.assertNotIn("2-parity", conf)
        self.assertIn("content /var/lib/builderbot/snapraid.content\n", conf)
        self.assertIn("content /mnt/disks/d1/.snapraid.content\n", conf)
        self.assertIn("data d2 /mnt/disks/d2/\n", conf)
        two = self.am.render_snapraid({**REC, "parity": REC["parity"] + [{"slot": 2, "id": "x", "uuid": "4", "fs": "xfs"}]})
        self.assertIn("2-parity /mnt/parity/p2/snapraid.2-parity\n", two)
        fstab = self.am.render_fstab(REC)
        self.assertIn("UUID=1111 /mnt/disks/d1 xfs defaults,nofail,noatime 0 0 # builderbot-array\n", fstab)
        self.assertIn("UUID=3333 /mnt/parity/p1 xfs defaults,nofail,noatime 0 0 # builderbot-array\n", fstab)
        merged = [ln for ln in fstab.splitlines() if "fuse.mergerfs" in ln][0]
        self.assertTrue(merged.startswith("/mnt/disks/d* /mnt/array fuse.mergerfs "))
        self.assertIn("category.create=epmfs", merged)
        self.assertIn("minfreespace=20G", merged)
        self.assertIn("x-systemd.requires-mounts-for=/mnt/disks/d2", merged)
        with mock.patch.dict(os.environ, self.env):
            self.am.write_fstab(REC)
            self.am.write_fstab(REC)
            text = open(self.env["BB_ARRAY_FSTAB"]).read()
        self.assertEqual(text.count("# builderbot-array"), 4, "written whole each time, the rest of fstab kept")
        self.assertTrue(text.startswith("UUID=root / ext4 defaults 0 1\n"))

    def test_the_census_reads_the_record_the_mounts_and_the_state(self):
        with mock.patch.dict(os.environ, self.env):
            self.assertEqual(self.am.array_now(), {}, "no record, no array")
            self.am.write_record(REC)
            self.am._state_set(last_sync=1761624000, status="Everything OK", running="")
            with mock.patch.object(self.am.os.path, "ismount", side_effect=lambda p: p in ("/mnt/disks/d1", "/mnt/array")), \
                 mock.patch.object(self.am, "_df", return_value=(1000, 400)):
                got = self.am.array_now()
        self.assertEqual((got["policy"], got["mounted"], got["last_sync"], got["status"]), ("epmfs", True, 1761624000, "Everything OK"))
        self.assertEqual([(x["slot"], x["mounted"], x["size_mb"], x["used_mb"]) for x in got["data"]], [(1, True, 1000, 400), (2, False, 0, 0)])
        self.assertEqual(got["parity"][0]["id"], "ata-WDC_C")

    def run_job(self, cfg, rec=None):
        job = Job()
        with mock.patch.dict(os.environ, self.env):
            if rec is not None:
                self.am.write_record(rec)
            elif os.path.exists(self.env["BB_ARRAY_RECORD"]):
                os.unlink(self.env["BB_ARRAY_RECORD"])
            with mock.patch.object(self.am, "disks_now", return_value=DISKS), mock.patch.object(self.am.shutil, "which", side_effect=lambda t: f"/usr/bin/{t}"), \
                 mock.patch.object(self.am.os, "geteuid", return_value=0), mock.patch.object(self.am, "by_id", side_effect=lambda n: f"ata-{n}"), \
                 mock.patch.object(self.am, "_out", return_value="uuid-x\n"), mock.patch.object(self.am.os.path, "ismount", return_value=False), \
                 mock.patch.object(self.am.os, "makedirs"), mock.patch.object(self.am, "_df", return_value=(3815447, 10)):
                state, code = self.A()._apply_storage_array(job, cfg)
            return state, code, job.text(), self.am.read_record()

    def test_an_array_is_made_of_wiped_disks_and_synced_once(self):
        state, code, text, rec = self.run_job({"array": "create", "data": ["sda", "sdb"], "parity": ["sdc"], "fs": "xfs", "policy": "mfs"})
        self.assertEqual((state, code), ("succeeded", 0), text)
        argv = [a for a in self.ran if a[0] == "mkfs.xfs"]
        self.assertEqual([a[-1] for a in argv], ["/dev/sda", "/dev/sdb", "/dev/sdc"])
        self.assertEqual(argv[0][1:3], ["-L", "bb-d1"])
        self.assertEqual(argv[2][1:3], ["-L", "bb-p1"])
        self.assertNotIn("-f", argv[0], "mkfs keeps its own refusal where the job did not say to wipe")
        self.assertNotIn(["wipefs", "-a", "/dev/sda"], self.ran, "nothing to wipe without the word")
        self.assertEqual([a for a in self.ran if a[0] == "mount"], [["mount", "/mnt/disks/d1"], ["mount", "/mnt/disks/d2"], ["mount", "/mnt/parity/p1"], ["mount", "/mnt/array"]])
        self.assertEqual(self.ran[-1], ["/usr/bin/snapraid", "sync"])
        self.assertEqual([(d["slot"], d["id"], d["uuid"]) for d in rec["data"]], [(1, "ata-sda", "uuid-x"), (2, "ata-sdb", "uuid-x")])
        self.assertEqual(rec["policy"], "mfs")
        self.assertIn("data d2 /mnt/disks/d2/", open(self.env["BB_SNAPRAID_CONF"]).read())
        self.assertIn("fuse.mergerfs", open(self.env["BB_ARRAY_FSTAB"]).read())

    def test_what_is_refused_runs_nothing(self):
        for cfg, rec, why in (({"array": "create", "data": ["sda"], "parity": ["sdb"]}, None, "at least as large"),
                              ({"array": "create", "data": ["sdd"], "parity": ["sda"]}, None, "holds ext4"),
                              ({"array": "create", "data": ["nvme0n1"], "parity": ["sda"]}, None, "system disk"),
                              ({"array": "create", "data": ["sda"], "parity": ["sda"]}, None, "each once"),
                              ({"array": "create", "data": ["sdb"], "parity": ["sda"], "policy": "random"}, None, "a policy one of"),
                              ({"array": "create", "data": ["sdb"], "parity": ["sda"]}, REC, "here already"),
                              ({"array": "sync"}, None, "no array here"),
                              ({"array": "destroy"}, REC, "the word array again"),
                              ({"array": "replace", "which": "d9", "new": "sda"}, REC, "has no d9"),
                              ({"array": "shrink"}, REC, "not an array action")):
            self.ran.clear()
            state, code, text, _ = self.run_job(cfg, rec)
            self.assertEqual(state, "failed", cfg)
            self.assertIn(why, text)
            self.assertEqual(self.ran, [], cfg)

    def test_a_disk_replaced_is_rebuilt_and_a_sync_is_one_at_a_time(self):
        state, code, text, rec = self.run_job({"array": "replace", "which": "d2", "new": "sdb", "wipe": True}, REC)
        self.assertEqual(state, "succeeded", text)
        self.assertIn(["wipefs", "-a", "/dev/sdb"], self.ran)
        self.assertEqual(self.ran[-2:], [["/usr/bin/snapraid", "fix", "-d", "d2"], ["/usr/bin/snapraid", "sync"]])
        self.assertEqual(rec["data"][1]["id"], "ata-sdb")
        self.ran.clear()
        state, code, text, rec = self.run_job({"array": "replace", "which": "p1", "new": "sda"}, REC)
        self.assertEqual(self.ran[-1], ["/usr/bin/snapraid", "sync", "-F"])
        with mock.patch.dict(os.environ, self.env):
            self.am._state_set(running="sync")
        state, code, text, _ = self.run_job({"array": "scrub"}, REC)
        self.assertEqual(state, "failed")
        self.assertIn("one at a time", text)
        with mock.patch.dict(os.environ, self.env):
            self.am._state_set(running="")
        state, code, text, _ = self.run_job({"array": "destroy", "confirm": "array"}, REC)
        self.assertEqual(state, "succeeded", text)
        self.assertFalse(os.path.exists(self.env["BB_ARRAY_RECORD"]))
        self.assertNotIn("builderbot-array", open(self.env["BB_ARRAY_FSTAB"]).read())


class TheController(unittest.TestCase):
    def test_the_census_keeps_the_array_to_its_shape(self):
        import nodes
        got = nodes._census({"array": {"policy": "mfs<b>", "mount": "/mnt/array", "mounted": True, "last_sync": "x", "last_scrub": 5, "status": "ok", "running": "",
                                       "data": [{"slot": 1, "id": "ata-A", "fs": "xfs", "size_mb": 10, "used_mb": 2, "mounted": True}, {"slot": 0}, "junk"],
                                       "parity": [{"slot": 1, "id": "ata-P", "fs": "xfs", "size_mb": 10, "used_mb": 1, "mounted": "yes"}]}})
        self.assertEqual(got["array"], {"policy": "mfsb", "mount": "/mnt/array", "mounted": True, "last_sync": 0, "last_scrub": 5, "last_check": 0, "status": "ok", "running": "",
                                        "data": [{"slot": 1, "id": "ata-A", "fs": "xfs", "size_mb": 10, "used_mb": 2, "mounted": True}],
                                        "parity": [{"slot": 1, "id": "ata-P", "fs": "xfs", "size_mb": 10, "used_mb": 1, "mounted": False}]})
        self.assertEqual(nodes._census({"array": {"data": []}})["array"], {})

    def test_the_verb_is_the_own_machines_and_holds_the_shapes(self):
        import nodes
        nodes.configure(state=tempfile.mkdtemp())
        self.assertEqual(nodes.node_storage_array("user:t", "n_none", {"array": "sync"})["error"], "no such node")
        n = {"id": "n1", "name": "box", "kind": "agent", "live": True, "config": {"own": True},
             "reported": {"administers": True, "features": {"storage": {"mergerfs": True, "snapraid": True}}, "disks": DISKS, "array": {}}}
        with mock.patch.object(nodes, "node", return_value=n), mock.patch.object(nodes, "own_machine", return_value=True), \
             mock.patch.object(nodes, "node_locked", return_value=""), mock.patch.object(nodes, "system_job_for", return_value=None), \
             mock.patch.object(nodes, "audit"), mock.patch.object(nodes, "job_add", side_effect=lambda *a: {"ok": True, "job": "j1", "spec": a[3]}) as add:
            self.assertIn("at least as large", nodes.node_storage_array("user:t", "n1", {"array": "create", "data": ["sda"], "parity": ["sdb"]})["error"])
            self.assertIn("system disk", nodes.node_storage_array("user:t", "n1", {"array": "create", "data": ["nvme0n1"], "parity": ["sda"]})["error"])
            self.assertIn("no array on the machine", nodes.node_storage_array("user:t", "n1", {"array": "sync"})["error"])
            self.assertEqual(add.call_count, 0)
            r = nodes.node_storage_array("user:t", "n1", {"array": "create", "data": ["sdb", "sda"], "parity": ["sdc"], "fs": "btrfs", "policy": "lfs", "wipe": True})
            self.assertTrue(r.get("ok"), r)
            self.assertEqual(add.call_args[0][3]["config"], {"array": "create", "data": ["sdb", "sda"], "parity": ["sdc"], "fs": "btrfs", "policy": "lfs", "wipe": True})
            self.assertEqual(add.call_args[0][3]["timeout"], 86400)
            n["reported"]["array"] = {"data": [{"slot": 1}], "parity": [{"slot": 1}]}
            self.assertIn("one of d1, p1", nodes.node_storage_array("user:t", "n1", {"array": "replace", "which": "d3", "new": "sdb"})["error"])
            self.assertIn("typed again", nodes.node_storage_array("user:t", "n1", {"array": "destroy"})["error"])
            r = nodes.node_storage_array("user:t", "n1", {"array": "check"})
            self.assertEqual(add.call_args[0][3]["timeout"], 900)


if __name__ == "__main__":
    unittest.main()
