"""A finished install whose names the node's listing does not show yet keeps
the Library asking (the operator, 12 Oct: the census landed thirteen
seconds after the job's end, and the rows stayed unticked until a reload)."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402


class Settling(unittest.TestCase):
    def setUp(self):
        test = self
        self.job_row = {"state": "succeeded", "ended": int(time.time()), "spec": {"names": ["jdk", "go"]}}

        class Nodes:
            @staticmethod
            def job(jid, with_log=True):
                return test.job_row
        saved = toolchains.nodes
        self.addCleanup(setattr, toolchains, "nodes", saved)
        toolchains.nodes = Nodes()

    def items(self, *here):
        return [{"name": n, "installed": n in here} for n in ("jdk", "go", "node")]

    def test_an_install_settles_once_the_listing_shows_it(self):
        job = {"running": False, "action": "install", "id": "j1"}
        self.assertTrue(toolchains._store_settling(job, self.items("jdk")), "go is not listed yet")
        self.assertFalse(toolchains._store_settling(job, self.items("jdk", "go")))

    def test_a_removal_settles_once_it_is_gone(self):
        job = {"running": False, "action": "remove", "id": "j1"}
        self.assertTrue(toolchains._store_settling(job, self.items("go")))
        self.assertFalse(toolchains._store_settling(job, self.items("node")))

    def test_not_for_a_failed_old_or_running_job(self):
        job = {"running": False, "action": "install", "id": "j1"}
        self.job_row["state"] = "failed"
        self.assertFalse(toolchains._store_settling(job, self.items()))
        self.job_row.update(state="succeeded", ended=int(time.time()) - 300)
        self.assertFalse(toolchains._store_settling(job, self.items()), "two minutes at most")
        self.assertFalse(toolchains._store_settling({"running": True, "action": "install"}, self.items()))


if __name__ == "__main__":
    unittest.main()
