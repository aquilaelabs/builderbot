"""workspace._safe_name, which decides what a node may write into dist/, and
vmtemplate's minted identity (R86 named these modules as untested)."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import vmtemplate  # noqa: E402
import workspace  # noqa: E402


class SafeName(unittest.TestCase):
    def test_plain_names_at_most_two_levels(self):
        self.assertEqual(workspace._safe_name("app.apk"), "app.apk")
        self.assertEqual(workspace._safe_name("emu/shot-1.png"), "emu/shot-1.png")
        self.assertEqual(workspace._safe_name("emu\\shot.png"), "emu/shot.png")

    def test_what_is_not_a_name(self):
        for name in ("", None, ".", "..", "../x", "a/../b", "a/b/c", "-x", " x", "a b",
                     "x/" + "a" * 130, "a;b"):
            self.assertIsNone(workspace._safe_name(name), repr(name))


class VmIdentity(unittest.TestCase):
    def test_a_mac_in_the_hypervisors_range(self):
        for _ in range(50):
            m = vmtemplate.mac("00:50:56")
            self.assertRegex(m, r"^00:50:56:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}$")
            self.assertLessEqual(int(m.split(":")[3], 16), 0x3F, m)
        self.assertTrue(vmtemplate.mac().startswith("52:54:00:"))

    def test_defaults_mint_a_fresh_identity_each_time(self):
        a, b = vmtemplate.defaults(), vmtemplate.defaults()
        self.assertNotEqual(a["uuid"], b["uuid"])
        self.assertTrue(re.fullmatch(r"[0-9a-f-]{36}", a["uuid"]))
        self.assertGreater(a["cores"], 0)
        self.assertGreater(a["memory_gb"], 0)


if __name__ == "__main__":
    unittest.main()
