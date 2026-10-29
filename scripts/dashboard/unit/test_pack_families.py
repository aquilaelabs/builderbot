"""A tool pack across distributions (R171): its system block names packages
per package manager as the shipped recipes do, each list held to its
manager's names; a node whose manager the pack names none for is told so
on the pack's row and refused at Install, and a pack with no system
packages, or one naming the node's manager, fits every family."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402
import toolpacks  # noqa: E402

BASE = {"name": "hexkit", "label": "Hex kit", "about": "Looks inside binaries.", "platforms": ["linux/amd64"],
        "install": {"steps": [["sh", "{dir}/install.sh"]]}, "layout": {"bin": ["bin"], "tool": "bin/hexkit"},
        "verbs": {"dump": {"about": "A file as hex.", "usage": "FILE", "run": ["{dir}/bin/hexkit", "dump", "{args}"]}}}


class Families(unittest.TestCase):
    def test_each_manager_keeps_its_own_names(self):
        m, errors = toolpacks.validate(dict(BASE, system={"apt": ["libssl-dev"], "dnf": ["openssl-devel"], "pacman": ["openssl"],
                                                           "zypper": ["libopenssl-devel"], "apk": ["openssl-dev"]}))
        self.assertEqual(errors, [])
        self.assertEqual(sorted(m["system"]), ["apk", "apt", "dnf", "pacman", "zypper"])
        _, errors = toolpacks.validate(dict(BASE, system={"apt": ["Bad Name"], "brew": ["x"]}))
        self.assertTrue(any("system.apt lists Debian and Ubuntu package names" in e for e in errors), errors)
        self.assertTrue(any("system.brew is not a package manager" in e for e in errors), errors)

    def test_a_node_of_another_manager_is_told_and_one_it_names_is_not(self):
        apt_only = {"system": {"apt": ["libssl-dev"]}}
        self.assertIn("for apt only, and this node installs with dnf", toolchains.family_miss(apt_only, "dnf"))
        self.assertEqual(toolchains.family_miss(apt_only, "apt"), "")
        self.assertEqual(toolchains.family_miss(apt_only, ""), "", "a node that has not said is not judged")
        self.assertEqual(toolchains.family_miss({}, "dnf"), "", "a pack with no system packages fits every family")


if __name__ == "__main__":
    unittest.main()
