"""The machine's disks in the census (R162 step 1): read off lsblk's and
smartctl's JSON, loop and RAM devices left out, each partition's holding
in words, the system disk marked; and the controller keeps each to its
shape."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import agentpkg  # noqa: E402

LSBLK = {"blockdevices": [
    {"name": "sda", "kname": "sda", "type": "disk", "size": 2000398934016, "model": "WDC WD20EFRX", "serial": "WD-WCC4M1234567", "rota": True, "tran": "sata", "rm": False,
     "children": [{"name": "sda1", "kname": "sda1", "type": "part", "size": 2000397868544, "fstype": "zfs_member", "label": "tank", "mountpoint": None}]},
    {"name": "nvme0n1", "kname": "nvme0n1", "type": "disk", "size": 512110190592, "model": "Samsung SSD 980", "serial": "S5GXNX0R", "rota": False, "tran": "nvme", "rm": False,
     "children": [{"name": "nvme0n1p1", "kname": "nvme0n1p1", "type": "part", "size": 536870912, "fstype": "vfat", "mountpoint": "/boot/efi"},
                  {"name": "nvme0n1p2", "kname": "nvme0n1p2", "type": "part", "size": 4294967296, "fstype": "squashfs", "mountpoint": "/"},
                  {"name": "nvme0n1p3", "kname": "nvme0n1p3", "type": "part", "size": 8589934592, "fstype": "swap", "mountpoint": "[SWAP]"}]},
    {"name": "sdb", "kname": "sdb", "type": "disk", "size": 32000000000, "model": "Ultra Fit", "serial": "4C53", "rota": True, "tran": "usb", "rm": True, "fstype": "exfat", "mountpoint": None},
    {"name": "loop0", "kname": "loop0", "type": "loop", "size": 100000000},
    {"name": "bad name", "kname": "bad name", "type": "disk", "size": 1},
]}
SMART = {"smart_status": {"passed": True}, "temperature": {"current": 34}, "power_on_time": {"hours": 12345}}


class Disks(unittest.TestCase):
    def setUp(self):
        self.agent = agentpkg.load("builderbot_agent_disks")
        self.dk = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".disks"]

    def test_every_whole_disk_with_what_it_holds_and_its_smart_facts(self):
        def fake(argv, timeout=0):
            return LSBLK if argv[0] == "lsblk" else SMART
        with mock.patch.object(self.dk, "_json", side_effect=fake), mock.patch.object(self.dk.shutil, "which", return_value="/usr/sbin/x"):
            got = self.dk.disks_now()
        self.assertEqual([d["name"] for d in got], ["sda", "nvme0n1", "sdb"], "loop devices and a name that is not one are left out")
        sda, nv, sdb = got
        self.assertEqual((sda["model"], sda["serial"], sda["size_mb"], sda["ssd"], sda["tran"], sda["system"]),
                         ("WDC WD20EFRX", "WD-WCC4M1234567", 1907729, False, "sata", False))
        self.assertEqual(sda["parts"][0]["holds"], "ZFS pool tank")
        self.assertEqual(sda["smart"], {"health": "ok", "temp_c": 34, "hours": 12345})
        self.assertTrue(nv["system"] and nv["ssd"])
        self.assertEqual([p["holds"] for p in nv["parts"]], ["vfat at /boot/efi", "squashfs at /", "swap"])
        self.assertEqual((sdb["removable"], sdb["holds"], sdb["parts"]), (True, "exfat, not mounted", []))

    def test_without_smartctl_or_lsblk_nothing_breaks(self):
        with mock.patch.object(self.dk, "_json", return_value=LSBLK), mock.patch.object(self.dk.shutil, "which", side_effect=lambda n: None if n == "smartctl" else "/x"):
            got = self.dk.disks_now()
        self.assertEqual(got[0]["smart"], {})
        with mock.patch.object(self.dk.shutil, "which", return_value=None):
            self.assertEqual(self.dk.disks_now(), [])


class TheController(unittest.TestCase):
    def test_each_disk_is_kept_to_its_shape(self):
        import nodes
        got = nodes._census({"disks": [{"name": "sda", "model": "WD <b>Red</b>", "serial": "X1", "size_mb": 1000, "ssd": "yes", "tran": "sata", "system": True,
                                        "parts": [{"name": "sda1", "size_mb": "9", "holds": "ZFS pool tank"}], "smart": {"health": "meh", "temp_c": 40, "hours": "1"}},
                                       {"name": "bad name"}, "junk"]})
        self.assertEqual(got["disks"], [{"name": "sda", "model": "WD bRed/b", "serial": "X1", "size_mb": 1000, "ssd": False, "tran": "sata", "removable": False,
                                         "system": True, "holds": "", "parts": [{"name": "sda1", "size_mb": 0, "holds": "ZFS pool tank"}], "smart": {"temp_c": 40}}])


if __name__ == "__main__":
    unittest.main()
