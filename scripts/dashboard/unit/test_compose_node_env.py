"""B448: compose config is asked with the node's own variables, so a compose
that requires BB_DOCKER_GID (${BB_DOCKER_GID:?...}) can be read for its
ports and mounts, and one that still cannot says what compose said."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402


class NodeEnv(unittest.TestCase):
    def test_config_carries_the_nodes_docker_gid_and_what_compose_said(self):
        seen = {}

        def run(argv, timeout=60, env_extra=None, **kw):
            seen["env"] = dict(env_extra or {})
            return {"code": 1, "out": "required variable BB_DOCKER_GID is missing a value"} if "BB_DOCKER_GID" not in seen["env"] \
                else {"code": 0, "out": '{"services": {"web": {"image": "nginx:1"}}}'}
        with mock.patch.object(devapp, "_run", run), mock.patch.object(devapp, "_compose", lambda *a: ["docker", "compose", "config"]), \
                mock.patch.object(devapp, "_instance_node", lambda p, i: "n_1"), \
                mock.patch.object(devapp, "node_reported", lambda nid: {"docker_gid": 988}):
            cfg = devapp._config("demo", devapp.MAIN)
            self.assertEqual(seen["env"]["BB_DOCKER_GID"], "988")
            self.assertEqual(list(cfg["services"]), ["web"])
            cfg = devapp._config("demo", devapp.MAIN, env_extra={"X": "1"})
            self.assertEqual((seen["env"]["X"], seen["env"]["BB_DOCKER_GID"]), ("1", "988"), "a caller's own variables beside the node's")
        with mock.patch.object(devapp, "_run", run), mock.patch.object(devapp, "_compose", lambda *a: ["docker", "compose", "config"]), \
                mock.patch.object(devapp, "node_reported", None):
            self.assertIsNone(devapp._config("demo", devapp.MAIN))
            self.assertIn("BB_DOCKER_GID is missing", devapp._cfg_err.said, "what compose said is kept for the row")


if __name__ == "__main__":
    unittest.main()
