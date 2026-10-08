"""toolchains.store_areas: what part of a shared toolchain store a job
writes, which is what two nodes sharing it wait on. A toolchain is its own
directory, the Android SDK is one tree, and the machine's own installs and a
check write none of it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402


class StoreAreas(unittest.TestCase):
    def areas(self, names, action="install"):
        return sorted(a for _, a in toolchains.store_areas(names, action, "linux/amd64"))

    def test_each_toolchain_is_its_own_directory(self):
        self.assertEqual(self.areas(["jdk", "go"]), ["go", "jdk"])

    def test_the_android_sdk_is_one_tree(self):
        self.assertEqual(self.areas(["android-tools", "android:ndk", "android:cmake"]), ["android"])

    def test_the_machine_s_own_write_no_store(self):
        self.assertEqual(self.areas([toolchains.DRIVER + ":595", toolchains.TOOLKIT]), [])
        self.assertEqual(self.areas(["jdk"], "check"), [])
        self.assertEqual(self.areas([], "sysdeps"), [])

    def test_a_platform_is_its_own_scope(self):
        a = toolchains.store_areas(["jdk"], "install", "linux/amd64")
        b = toolchains.store_areas(["jdk"], "install", "linux/arm64")
        self.assertFalse(a & b)


if __name__ == "__main__":
    unittest.main()
