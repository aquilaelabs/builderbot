"""toolchains.driver_row: the census turned into the NVIDIA driver row's
state on the Toolchains tab (R102). The page draws each state's sentence;
this holds which state each census is."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402

CARD = "NVIDIA Corporation GA104 [GeForce RTX 3070 Ti] [10de:2482] (rev a1)"


def row(driver=None, card=CARD, sandbox=True):
    rep = {"gpu_card": card, "sandbox": sandbox}
    if driver is not None:
        rep["gpu_driver"] = driver
    return toolchains.driver_row({"id": "n_x", "name": "x", "reported": rep})


class DriverRow(unittest.TestCase):
    def setUp(self):
        self.was, toolchains.nodes = toolchains.nodes, None
        self.addCleanup(setattr, toolchains, "nodes", self.was)

    def state(self, installed="", loaded="", bound=""):
        return row({"installed": installed, "loaded": loaded, "bound": bound})["state"]

    def test_no_card_is_no_row(self):
        self.assertIsNone(row(card=""))

    def test_an_agent_that_does_not_report_the_driver(self):
        self.assertEqual(row()["state"], "unknown")

    def test_each_state(self):
        self.assertEqual(self.state(bound="nouveau"), "absent")
        self.assertEqual(self.state("580.95.05", bound="nouveau"), "waiting")
        self.assertEqual(self.state("580.95.05", "580.95.05", "nvidia"), "loaded")
        self.assertEqual(self.state("580.95.05", "575.64", "nvidia"), "update")
        self.assertEqual(self.state("", "580.95.05", "nvidia"), "leaving")

    def test_whose_machine_it_is(self):
        self.assertTrue(row({"installed": "", "loaded": "", "bound": "nouveau"})["managed"])
        self.assertFalse(row({"installed": "", "loaded": "", "bound": "nouveau"}, sandbox=False)["managed"])

    def test_no_job_means_nothing_running_or_settling(self):
        r = row({"installed": "", "loaded": "", "bound": "nouveau"})
        self.assertEqual((r["job"], r["settling"]), ({"running": False}, False))


if __name__ == "__main__":
    unittest.main()
