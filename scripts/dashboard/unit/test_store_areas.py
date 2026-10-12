"""toolchains.store_areas: what part of a shared toolchain store a job
writes, which is what two machines sharing it wait on. Each keeps its
toolchains in its own directory (R196), so a toolchain is its own area in
its own directory, the Android SDK is one tree there, the system images are
the one area every machine shares, and the machine's own installs and a
check write none of it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402


class StoreAreas(unittest.TestCase):
    def areas(self, names, action="install"):
        return sorted(a for _, a in toolchains.store_areas(names, action, "n_aaaa1111"))

    def test_each_toolchain_is_its_own_directory(self):
        self.assertEqual(self.areas(["jdk", "go"]), ["go", "jdk"])

    def test_the_android_sdk_is_one_tree(self):
        self.assertEqual(self.areas(["android-tools", "android:ndk", "android:cmake"]), ["android"])

    def test_the_machine_s_own_write_no_store(self):
        self.assertEqual(self.areas([toolchains.DRIVER + ":595", toolchains.TOOLKIT]), [])
        self.assertEqual(self.areas(["jdk"], "check"), [])
        self.assertEqual(self.areas([], "sysdeps"), [])

    def test_a_node_s_directory_is_its_own(self):
        a = toolchains.store_areas(["jdk", "android-tools"], "install", "n_aaaa1111")
        b = toolchains.store_areas(["jdk", "android-tools"], "install", "n_bbbb2222")
        self.assertFalse(a & b)


def node(nid, name):
    return {"id": nid, "name": name, "kind": "agent", "state": "online", "live": True, "os": "linux", "arch": "x86_64",
            "reported": {"mounts": [], "stores": {"toolchains": {"path": "/s", "id": "share1", "scope": nid}}}}


class AcrossNodes(unittest.TestCase):
    """Two nodes on one share wait for each other only on the system images."""

    def setUp(self):
        test = self
        self.nodes_ = [node("n_aaaa1111", "a"), node("n_bbbb2222", "b")]
        self.jobs = {}

        class Nodes:
            LOCAL = "local"

            @staticmethod
            def node(nid):
                return next((n for n in test.nodes_ if n["id"] == nid), None)

            @staticmethod
            def node_list(all=False):
                return list(test.nodes_)

            @staticmethod
            def jobs_for(node_id=None, type=None, n=50, active=False, **k):
                return [j for j in test.jobs.get(node_id, []) if j["type"] == type]
        saved = (toolchains.nodes, toolchains._store_share)
        self.addCleanup(lambda: setattr(toolchains, "nodes", saved[0]) or setattr(toolchains, "_store_share", saved[1]))
        toolchains.nodes = Nodes()
        toolchains._store_share = lambda n: "share1"

    def test_a_toolchain_install_on_one_never_waits_for_the_other(self):
        self.jobs["n_bbbb2222"] = [{"type": "toolchain", "spec": {"action": "install", "names": ["jdk", "android-tools"]}}]
        self.assertEqual(toolchains.store_busy("n_aaaa1111", ["jdk", "android:ndk"]), "")

    def test_an_image_job_waits_for_the_other_s_image_job(self):
        self.jobs["n_bbbb2222"] = [{"type": "image", "spec": {"action": "add"}}]
        self.assertIn("android system images", toolchains.store_busy("n_aaaa1111", None))
        self.assertEqual(toolchains.store_busy("n_aaaa1111", ["jdk"]), "", "a toolchain is not an image")


if __name__ == "__main__":
    unittest.main()
