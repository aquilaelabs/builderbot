"""The heartbeat's store readings land on the census rows (B434)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nodes  # noqa: E402


class StoreMerge(unittest.TestCase):
    def test_a_grown_disk_takes_its_new_size_with_its_free_space(self):
        census = {"data": {"path": "/var/lib/builderbot/data", "free_mb": 2900, "total_mb": 63000}}
        nodes.store_merge(census, {"data": 64500}, {"data": 128000})
        self.assertEqual(census["data"], {"path": "/var/lib/builderbot/data",
                                          "free_mb": 64500, "total_mb": 128000})

    def test_an_older_agent_without_a_size_keeps_the_census_size(self):
        census = {"data": {"path": "/d", "free_mb": 1, "total_mb": 63000}}
        nodes.store_merge(census, {"data": 2000}, {"data": None})
        self.assertEqual(census["data"]["total_mb"], 63000)
        self.assertEqual(census["data"]["free_mb"], 2000)

    def test_a_role_the_census_does_not_have_is_left_out(self):
        census = {}
        nodes.store_merge(census, {"cache": 10}, {"cache": 20})
        self.assertEqual(census, {})


if __name__ == "__main__":
    unittest.main()
