"""The controller's own machine's storage on the bell (R164 step 3): a
disk SMART calls failing, a hot disk, a pool not online and an array slot
not mounted, each a row keyed on what is wrong, from the census alone."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nodes  # noqa: E402


def own(reported, own=True):
    return {"id": "n1", "name": "nas", "kind": "agent", "live": True, "config": {"own": own}, "reported": reported}


class StorageRows(unittest.TestCase):
    def rows(self, ns):
        with mock.patch.object(nodes, "node_list", lambda: ns):
            return nodes.storage_attention()

    def test_a_failing_disk_a_hot_disk_a_sick_pool_and_a_slot_gone(self):
        rep = {"disks": [{"name": "sda", "model": "WDC", "serial": "A", "smart": {"health": "failing", "temp_c": 61}},
                         {"name": "sdb", "model": "WDC", "serial": "B", "smart": {"health": "ok", "temp_c": 57}},
                         {"name": "sdc", "model": "WDC", "serial": "C", "smart": {"health": "ok", "temp_c": 40}}],
               "pools": [{"name": "tank", "health": "degraded", "errors": "No known data errors"}, {"name": "fast", "health": "online"}],
               "array": {"data": [{"slot": 1, "id": "ata-X", "mounted": True}, {"slot": 2, "id": "ata-Y", "mounted": False}], "parity": [{"slot": 1, "mounted": True}]}}
        got = self.rows([own(rep)])
        self.assertEqual([(r["what"], r["bad"], r["key"]) for r in got],
                         [("failing", True, "disk:failing:n1:A"), ("hot", False, "disk:hot:n1:B:55"), ("pool", True, "pool:n1:tank:degraded"), ("array", True, "array:n1:d2")])
        self.assertIn("replace it before it goes", got[0]["said"])
        self.assertIn("57 °C", got[1]["said"])
        self.assertTrue(all(r["kind"] == "disk" and r["node"] == "nas" for r in got))

    def test_nothing_from_a_healthy_machine_or_another_node(self):
        rep = {"disks": [{"name": "sda", "smart": {"health": "ok", "temp_c": 40}}], "pools": [{"name": "tank", "health": "online"}], "array": {}}
        self.assertEqual(self.rows([own(rep)]), [])
        rep["disks"][0]["smart"]["health"] = "failing"
        self.assertEqual(self.rows([own(rep, own=False)]), [], "another node's disks are its own administrator's")


if __name__ == "__main__":
    unittest.main()
