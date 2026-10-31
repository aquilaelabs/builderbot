"""The room keeper's prune of build caches by age (R110 step 7): a job's
use stamps its project's cache, and cache-clear with older_days drops only
the ones no job has used for that long."""
import os
import shutil
import tempfile
import time
import types
import unittest

import agentpkg  # noqa: E402
agent = agentpkg.load("builderbot_agent_cache_age")
agent.log = lambda *a, **k: None


class CacheAge(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cache-")
        self.addCleanup(shutil.rmtree, self.root, True)
        old = time.time() - 30 * 86400
        for name, used in (("stale", old), ("fresh", time.time()), ("unstamped", old)):
            d = os.path.join(self.root, name)
            os.makedirs(d)
            if name != "unstamped":
                with open(os.path.join(d, ".used"), "w"):
                    pass
                os.utime(os.path.join(d, ".used"), (used, used))
            os.utime(d, (used, used))
        self.said = []
        self.job = types.SimpleNamespace(say=self.said.append)
        self.me = types.SimpleNamespace(state={"stores": {"cache": self.root}}, hello=lambda: None)

    def clear(self, spec):
        return agent.WorkMixin.cache_clear(self.me, self.job, spec)

    def test_age_reads_the_stamp_then_the_directory(self):
        self.assertGreater(agent.cache_age_days(os.path.join(self.root, "stale")), 29)
        self.assertLess(agent.cache_age_days(os.path.join(self.root, "fresh")), 1)
        self.assertGreater(agent.cache_age_days(os.path.join(self.root, "unstamped")), 29)
        self.assertEqual(agent.cache_age_days(os.path.join(self.root, "gone")), 0.0)

    def test_older_days_keeps_what_was_used(self):
        self.assertEqual(self.clear({"older_days": 14}), ("succeeded", 0))
        self.assertEqual(sorted(os.listdir(self.root)), ["fresh"])

    def test_without_an_age_every_cache_goes(self):
        self.clear({})
        self.assertEqual(os.listdir(self.root), [])

    def test_a_dotted_project_never_reaches_past_the_store(self):
        # ".." named the store's parent, which root then removed whole.
        beside = os.path.join(os.path.dirname(self.root), os.path.basename(self.root) + "-beside")
        os.makedirs(beside)
        self.addCleanup(shutil.rmtree, beside, True)
        for bad in ("..", ".", "../x"):
            self.assertEqual(self.clear({"project": bad}), ("failed", 64), bad)
        self.assertTrue(os.path.isdir(beside))
        self.assertEqual(sorted(os.listdir(self.root)), ["fresh", "stale", "unstamped"])

    def test_a_link_in_the_store_is_not_followed(self):
        out = tempfile.mkdtemp(prefix="outside-")
        self.addCleanup(shutil.rmtree, out, True)
        os.symlink(out, os.path.join(self.root, "linked"))
        self.clear({})
        self.assertTrue(os.path.isdir(out), "what a link in the store points at stays")


if __name__ == "__main__":
    unittest.main()
