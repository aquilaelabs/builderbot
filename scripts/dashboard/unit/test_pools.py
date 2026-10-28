"""ZFS pools on the controller's own machine (R162 step 1): the agent reads
zpool's list and status into the census, its storage-pool job holds every
argument to its shape and every disk to the census before zpool runs, and
names disks by their by-id links; the controller keeps the census's pools
to their shape and queues the job for the own machine alone. Snapshots
(step 5): counted by kind for the census, taken with the oldest of the
kind pruned, rolled back only with the name typed again, and scheduled as
a system schedule the Storage page lists per pool."""
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
SNAPS = ("tank@bb-hourly-20261027-2200\t1761602400\t1048576\n"
         "tank/data@bb-hourly-20261027-2200\t1761602400\t2097152\n"
         "tank@bb-hourly-20261027-2300\t1761606000\t1048576\n"
         "tank@bb-daily-20261028-0400\t1761624000\t3145728\n"
         "tank@manual-old\t1761000000\t10\n"
         "other@bb-manual-20261028-0900\t1761642000\t0\n")
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
        if argv[1:4] == ["list", "-H", "-p"] and "snapshot" in argv:
            return SNAPS
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

    def test_the_census_counts_each_pools_snapshots_by_kind_once_across_its_datasets(self):
        with mock.patch.object(self.pm, "_out", side_effect=self.fake_out), mock.patch.object(self.pm.shutil, "which", return_value="/usr/sbin/zfs"):
            got = self.pm.snapshots_now()
        self.assertEqual(sorted(got), ["other", "tank"])
        t = got["tank"]
        self.assertEqual((t["count"], t["used_mb"], t["kinds"]), (3, 7, {"hourly": 2, "daily": 1, "weekly": 0, "manual": 0}))
        self.assertEqual([x["name"] for x in t["newest"]], ["bb-daily-20261028-0400", "bb-hourly-20261027-2300", "bb-hourly-20261027-2200"])
        self.assertEqual(t["newest"][0]["at"], 1761624000)

    def run_snap(self, cfg):
        job = Job()
        with mock.patch.object(self.pm, "_out", side_effect=self.fake_out), mock.patch.object(self.pm.shutil, "which", return_value="/usr/sbin/zfs"), \
             mock.patch.object(self.pm.os, "geteuid", return_value=0), mock.patch.object(self.pm.time, "strftime", return_value="bb-hourly-20261028-0900"):
            state, code = self.A()._apply_storage_snapshot(job, cfg)
        return state, code, job.text()

    def test_a_snapshot_taken_prunes_the_oldest_of_its_kind_past_what_is_kept(self):
        state, code, text = self.run_snap({"snapshot": "take", "pool": "tank", "kind": "hourly", "keep": 2})
        self.assertEqual((state, code), ("succeeded", 0), text)
        self.assertEqual(self.ran[0][1:], ["snapshot", "-r", "tank@bb-hourly-20261028-0900"])
        # Three hourly with the new one, two kept: the oldest goes, whole.
        self.assertEqual(self.ran[1][1:], ["destroy", "-r", "tank@bb-hourly-20261027-2200"])
        self.assertEqual(len(self.ran), 2)
        self.assertIn("pruned tank@bb-hourly-20261027-2200", text)

    def test_a_rollback_takes_the_name_again_and_the_rest_are_refused_before_zfs(self):
        for cfg, why in (({"snapshot": "rollback", "pool": "tank", "name": "bb-daily-20261028-0400"}, "name again"),
                         ({"snapshot": "rollback", "pool": "tank", "name": "nope", "confirm": "nope"}, "named bb-KIND"),
                         ({"snapshot": "destroy", "pool": "tank", "name": "bb-daily-20261028-0500"}, "no snapshot"),
                         ({"snapshot": "destroy", "pool": "tank", "dataset": "other", "name": "bb-daily-20261028-0400"}, "named bb-KIND"),
                         ({"snapshot": "take", "pool": "nope"}, "not a pool"),
                         ({"snapshot": "take", "pool": "tank", "kind": "yearly"}, "kind is one of"),
                         ({"snapshot": "freeze", "pool": "tank"}, "not a snapshot action")):
            self.ran.clear()
            state, code, text = self.run_snap(cfg)
            self.assertEqual(state, "failed", cfg)
            self.assertIn(why, text)
            self.assertEqual(self.ran, [], cfg)
        self.run_snap({"snapshot": "rollback", "pool": "tank", "dataset": "tank/data", "name": "bb-hourly-20261027-2200", "confirm": "bb-hourly-20261027-2200"})
        self.assertEqual(self.ran[-1][1:], ["rollback", "-r", "tank/data@bb-hourly-20261027-2200"])
        self.run_snap({"snapshot": "destroy", "pool": "tank", "name": "bb-daily-20261028-0400"})
        self.assertEqual(self.ran[-1][1:], ["destroy", "tank@bb-daily-20261028-0400"])


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

    def test_the_census_keeps_each_pools_snapshots_to_their_shape(self):
        import nodes
        got = nodes._census({"snapshots": {"tank": {"count": 2, "used_mb": "x", "kinds": {"hourly": 2, "odd": 1},
                                                    "newest": [{"name": "bb-hourly-20261027-2300", "at": 5}, {"name": "rm -rf", "at": 1}, "junk"]},
                                           "Bad Name": {"count": 1}, "other": "junk"}})
        self.assertEqual(got["snapshots"], {"tank": {"count": 2, "used_mb": 0, "kinds": {"hourly": 2, "daily": 0, "weekly": 0, "manual": 0},
                                                     "newest": [{"name": "bb-hourly-20261027-2300", "at": 5}]}})

    def test_the_snapshot_verb_is_the_own_machines_and_holds_the_shapes(self):
        import nodes
        nodes.configure(state=tempfile.mkdtemp())
        self.assertEqual(nodes.node_storage_snapshot("user:t", "n_none", {"snapshot": "take", "pool": "tank"})["error"], "no such node")
        with mock.patch.object(nodes, "node", return_value={"id": "n1", "name": "box", "kind": "agent", "live": True, "config": {"own": True},
                                                            "reported": {"administers": True, "features": {"storage": {"zfs": True}}, "pools": [{"name": "tank"}]}}), \
             mock.patch.object(nodes, "own_machine", return_value=True), mock.patch.object(nodes, "node_locked", return_value=""), \
             mock.patch.object(nodes, "system_job_for", return_value=None), mock.patch.object(nodes, "audit"), \
             mock.patch.object(nodes, "job_add", side_effect=lambda *a: {"ok": True, "job": "j1", "spec": a[3]}) as add:
            self.assertIn("not a pool", nodes.node_storage_snapshot("user:t", "n1", {"snapshot": "take", "pool": "nope"})["error"])
            self.assertIn("kind", nodes.node_storage_snapshot("user:t", "n1", {"snapshot": "take", "pool": "tank", "kind": "yearly"})["error"])
            self.assertIn("typed again", nodes.node_storage_snapshot("user:t", "n1", {"snapshot": "rollback", "pool": "tank", "name": "bb-daily-20261028-0400"})["error"])
            self.assertIn("named bb-KIND", nodes.node_storage_snapshot("user:t", "n1", {"snapshot": "destroy", "pool": "tank", "name": "x"})["error"])
            self.assertEqual(add.call_count, 0)
            r = nodes.node_storage_snapshot("user:t", "n1", {"snapshot": "take", "pool": "tank", "kind": "daily", "keep": 7})
            self.assertTrue(r.get("ok"), r)
            self.assertEqual(add.call_args[0][3]["config"], {"snapshot": "take", "pool": "tank", "kind": "daily", "keep": 7})
            r = nodes.node_storage_snapshot("user:t", "n1", {"snapshot": "rollback", "pool": "tank", "dataset": "tank/data", "name": "bb-daily-20261028-0400", "confirm": "bb-daily-20261028-0400"})
            self.assertEqual(add.call_args[0][3]["config"], {"snapshot": "rollback", "pool": "tank", "name": "bb-daily-20261028-0400", "dataset": "tank/data", "confirm": "bb-daily-20261028-0400"})


if __name__ == "__main__":
    unittest.main()
