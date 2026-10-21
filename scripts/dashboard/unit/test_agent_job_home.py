"""A job on a node whose agent is not root runs with a HOME it can write:
the agent's own, or one under the data store where the uid has none (a
container started as a bare number), where npm stopped on uv_os_homedir
(B145, diagnostics #122)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import agentpkg  # noqa: E402


class JobHome(unittest.TestCase):
    def setUp(self):
        self.Agent = agentpkg.load("jobhome").Agent
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def fake(self):
        f = type("F", (), {"state": {"stores": {"data": self.tmp.name}}})()
        f.as_user = lambda env, user: {}
        f.job_home = lambda: self.Agent.job_home(f)
        return f

    def env_for(self, home):
        env = {}
        with mock.patch.dict(os.environ, {"HOME": home} if home else {}, clear=False):
            if not home:
                os.environ.pop("HOME", None)
            with mock.patch("os.path.expanduser", return_value="/"):
                self.Agent.drop_privileges(self.fake(), env)
        return env

    def test_its_own_home_where_it_has_one(self):
        own = os.path.join(self.tmp.name, "own")
        os.makedirs(own)
        self.assertEqual(self.env_for(own)["HOME"], own)

    def test_one_under_the_data_store_where_it_has_none(self):
        home = self.env_for("")["HOME"]
        self.assertEqual(home, os.path.join(self.tmp.name, "home"))
        self.assertTrue(os.path.isdir(home))


if __name__ == "__main__":
    unittest.main()
