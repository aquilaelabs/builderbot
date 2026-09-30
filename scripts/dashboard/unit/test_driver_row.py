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

    def test_here_is_on_the_machine_whether_or_not_it_has_the_card(self):
        here = lambda **kw: row({"installed": "", "loaded": "", "bound": "", **kw})["here"]  # noqa: E731
        self.assertFalse(here(bound="nouveau"))
        self.assertTrue(here(installed="595.91.07", bound="nouveau"))
        self.assertTrue(here(installed="595.91.07", loaded="595.91.07", bound="nvidia"))
        self.assertFalse(here(loaded="595.91.07", bound="nvidia"))

    def test_an_update_is_a_candidate_that_is_not_what_is_installed(self):
        base = {"installed": "595.91.07", "loaded": "595.91.07", "bound": "nvidia",
                "package": "nvidia-driver-595", "pkg_version": "595.91.07-0ubuntu1"}
        self.assertEqual(row({**base, "candidate": "595.95.01-0ubuntu1"})["newer"], "595.95.01")
        self.assertEqual(row({**base, "candidate": "595.91.07-0ubuntu1"})["newer"], "")
        self.assertEqual(row({**base, "candidate": ""})["newer"], "")


class DriverName(unittest.TestCase):
    """What the job carries for the driver, and what is refused first."""
    OPTS = [{"pkg": "nvidia-driver-610", "version": "610.57.04", "open": False},
            {"pkg": "nvidia-driver-595", "version": "595.91.07", "open": False}]

    def node(self, sandbox=True, lock=False, **gd):
        rep = {"gpu_card": CARD, "sandbox": sandbox,
               "gpu_driver": {"installed": "", "loaded": "", "bound": "nouveau", "options": self.OPTS, **gd}}
        return {"id": "n_x", "name": "x", "reported": rep, "config": {"lock": lock}}

    def test_the_recommended_one_and_a_picked_branch(self):
        self.assertEqual(toolchains._driver_name(self.node(), "install", ""), ("nvidia-driver", ""))
        self.assertEqual(toolchains._driver_name(self.node(), "install", "nvidia-driver-610"),
                         ("nvidia-driver:nvidia-driver-610", ""))
        self.assertEqual(toolchains._driver_name(self.node(), "remove", "nvidia-driver-610"), ("nvidia-driver", ""))

    def test_refusals(self):
        for n, act, pkg in (
                (self.node(sandbox=False), "install", ""),
                (self.node(lock=True), "install", ""),
                (self.node(), "install", "nvidia-driver-999"),
                (self.node(installed="595.91.07", package="nvidia-driver-595"), "install", "nvidia-driver-610"),
                ({"id": "n", "name": "x", "reported": {"gpu_card": CARD, "sandbox": True}}, "install", ""),
                ({"id": "n", "name": "x", "reported": {"sandbox": True}}, "install", "")):
            name, why = toolchains._driver_name(n, act, pkg)
            self.assertEqual(name, "")
            self.assertTrue(why)

    def test_an_update_of_the_installed_branch_is_not_refused(self):
        n = self.node(installed="595.91.07", package="nvidia-driver-595")
        self.assertEqual(toolchains._driver_name(n, "install", "nvidia-driver-595")[1], "")
        self.assertEqual(toolchains._driver_name(n, "install", "")[1], "")


if __name__ == "__main__":
    unittest.main()
