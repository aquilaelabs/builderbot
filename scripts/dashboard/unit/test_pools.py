"""ZFS pools on the controller's own machine (R162 step 1): the agent reads
zpool's list and status into the census, its storage-pool job holds every
argument to its shape and every disk to the census before zpool runs, and
names disks by their by-id links; the controller keeps the census's pools
to their shape and queues the job for the own machine alone."""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import agentpkg  # noqa: E402

LIST = "tank\t4000000000000\t1000000000000\t3000000000000\tONLINE\t-\n"
STATUS = """  pool: tank
 state: ONLINE
  scan: scrub repaired 0B in 00:10:00 with 0 errors on Sun Oct 25 04:10:00 2026
config:

\tNAME                        STATE     READ WRITE CKSUM
\ttank                        ONLINE       0     0     0
\t  mirror-0                  ONLINE       0     0     0
\t    ata-WDC_WD20EFRX_WD-A   ONLINE       0     0     0
\t    ata-WDC_WD20EFRX_WD-B   ONLINE       0     0     0

errors: No known data errors
"""
DISKS = [{"name": "sda", "model": "WDC", "serial": "A", "size_mb": 1907729, "system": False, "holds": "", "parts": [{"name": "sda1", "holds": "ZFS pool tank"}]},
         {"name": "sdb", "model": "WDC", "serial": "B", "size_mb": 1907729, "system": False, "holds": "nothing", "parts": []},
         {"name": "sdc", "model": "WDC", "serial": "C", "size_mb": 1907729, "system": False, "holds": "nothing", "parts": []},
         {"name": "nvme0n1", "model": "SSD", "serial": "S", "size_mb": 488386, "system": True, "holds": "", "parts": [{"name": "nvme0n1p2", "holds": "squashfs at /"}]}]


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
        self.agent = agentpkg.load("builderbot_agent_pools")
        self.pm = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".pools"]
        pm = self.pm
        ran = self.ran = []

        class A(pm.PoolsMixin):
            def _sh(self, job, argv, timeout=0, **kw):
                ran.append(argv)
                return 0

            def hello_again(self, why):
                self.said = why
        self.A = A

    def fake_out(self, argv, timeout=0):
        if argv[1:2] == ["list"]:
            return LIST
        if argv[1:2] == ["status"]:
            return STATUS
        if argv[1:3] == ["get", "-H"]:
            return "/mnt/tank\n"
        return ""

    def test_the_census_reads_each_pool_whole(self):
        with mock.patch.object(self.pm, "_out", side_effect=self.fake_out), mock.patch.object(self.pm.shutil, "which", return_value="/usr/sbin/zpool"):
            got = self.pm.pools_now()
        self.assertEqual(len(got), 1)
        p = got[0]
        self.assertEqual((p["name"], p["size_mb"], p["alloc_mb"], p["health"], p["mount"]), ("tank", 3814697, 953674, "online", "/mnt/tank"))
        self.assertEqual(p["vdevs"], [{"type": "mirror", "state": "online", "disks": [{"id": "ata-WDC_WD20EFRX_WD-A", "state": "online"}, {"id": "ata-WDC_WD20EFRX_WD-B", "state": "online"}]}])
        self.assertIn("scrub repaired 0B", p["scrub"])
        self.assertEqual(p["errors"], "No known data errors")

    def run_job(self, cfg):
        job = Job()
        with mock.patch.object(self.pm, "_out", side_effect=self.fake_out), mock.patch.object(self.pm, "disks_now", return_value=DISKS), \
             mock.patch.object(self.pm.shutil, "which", return_value="/usr/sbin/zpool"), mock.patch.object(self.pm.os, "geteuid", return_value=0), \
             mock.patch.object(self.pm, "by_id", side_effect=lambda n: f"/dev/disk/by-id/ata-{n}"):
            state, code = self.A()._apply_storage_pool(job, cfg)
        return state, code, job.text()

    def test_a_mirror_is_made_of_disks_that_hold_nothing_by_their_links(self):
        state, code, text = self.run_job({"pool": "create", "name": "data", "layout": "mirror", "disks": ["sdb", "sdc"]})
        self.assertEqual((state, code), ("succeeded", 0), text)
        argv = self.ran[-1]
        self.assertEqual(argv[1], "create")
        self.assertNotIn("-f", argv)
        self.assertEqual(argv[-3:], ["mirror", "/dev/disk/by-id/ata-sdb", "/dev/disk/by-id/ata-sdc"])
        self.assertIn("-m", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "/mnt/data")

    def test_the_system_disk_a_held_disk_and_a_bad_shape_are_refused_before_zpool(self):
        for cfg, why in (({"pool": "create", "name": "x", "layout": "single", "disks": ["nvme0n1"]}, "system disk"),
                         ({"pool": "create", "name": "x", "layout": "single", "disks": ["sda"]}, "holds ZFS pool tank"),
                         ({"pool": "create", "name": "x", "layout": "mirror", "disks": ["sdb"]}, "takes 2 disk"),
                         ({"pool": "create", "name": "Tank!", "layout": "single", "disks": ["sdb"]}, "not a pool name"),
                         ({"pool": "create", "name": "tank", "layout": "single", "disks": ["sdb"]}, "here already"),
                         ({"pool": "destroy", "name": "tank"}, "takes its name again"),
                         ({"pool": "shrink", "name": "tank"}, "not a pool action"),
                         ({"pool": "scrub", "name": "nope"}, "no pool called")):
            self.ran.clear()
            state, code, text = self.run_job(cfg)
            self.assertEqual(state, "failed", cfg)
            self.assertIn(why, text)
            self.assertEqual(self.ran, [], cfg)

    def test_a_held_disk_goes_in_when_the_job_says_wipe_and_the_rest_run_as_named(self):
        state, code, text = self.run_job({"pool": "add", "name": "tank", "layout": "single", "disks": ["sda"], "wipe": True})
        self.assertEqual(state, "succeeded", text)
        self.assertEqual(self.ran[-1][1:4], ["add", "-f", "tank"])
        self.run_job({"pool": "scrub", "name": "tank"})
        self.assertEqual(self.ran[-1][1:], ["scrub", "tank"])
        self.run_job({"pool": "replace", "name": "tank", "old": "ata-WDC_WD20EFRX_WD-A", "new": "sdb"})
        self.assertEqual(self.ran[-1][1:], ["replace", "tank", "ata-WDC_WD20EFRX_WD-A", "/dev/disk/by-id/ata-sdb"])
        self.run_job({"pool": "destroy", "name": "tank", "confirm": "tank"})
        self.assertEqual(self.ran[-1][1:], ["destroy", "-f", "tank"])
        self.run_job({"pool": "export", "name": "tank"})
        self.assertEqual(self.ran[-1][1:], ["export", "tank"])


class TheController(unittest.TestCase):
    def test_the_census_keeps_each_pool_to_its_shape(self):
        import nodes
        got = nodes._census({"pools": [{"name": "tank", "size_mb": 10, "alloc_mb": "x", "free_mb": 4, "health": "ONLINE<b>", "mount": "/mnt/tank",
                                        "scrub": "none requested", "errors": "No known data errors",
                                        "vdevs": [{"type": "mirror", "state": "online", "disks": [{"id": "ata-A", "state": "online"}, "junk"]}]},
                                       {"name": "Bad Name"}]})
        self.assertEqual(got["pools"], [{"name": "tank", "size_mb": 10, "alloc_mb": 0, "free_mb": 4, "health": "ONLINEb", "mount": "/mnt/tank",
                                         "scrub": "none requested", "errors": "No known data errors",
                                         "vdevs": [{"type": "mirror", "state": "online", "disks": [{"id": "ata-A", "state": "online"}]}]}])

    def test_the_verb_is_the_own_machines_and_holds_the_shapes(self):
        import nodes
        nodes.configure(state=tempfile.mkdtemp())
        self.assertEqual(nodes.node_storage_pool("user:t", "n_none", {"pool": "scrub", "name": "tank"})["error"], "no such node")


if __name__ == "__main__":
    unittest.main()
