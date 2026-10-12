"""A session started before something it cannot see until it starts again
says so on its project's row (the operator, 12 Oct): a toolchain installed
on its node that puts something on PATH, named, and nothing for one that
landed before it started or changes no environment."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import projsessions  # noqa: E402
import toolchains  # noqa: E402


class LandedSince(unittest.TestCase):
    def setUp(self):
        jobs = [{"state": "succeeded", "ended": 200, "spec": {"action": "install", "names": ["jdk"]}},
                {"state": "succeeded", "ended": 50, "spec": {"action": "install", "names": ["go"]}},
                {"state": "failed", "ended": 300, "spec": {"action": "install", "names": ["node"]}}]

        class Nodes:
            @staticmethod
            def jobs_for(node_id=None, type=None, n=50, **k):
                return jobs
        saved = toolchains.nodes
        self.addCleanup(setattr, toolchains, "nodes", saved)
        toolchains.nodes = Nodes()

    def test_what_landed_after_it_started_and_changes_its_path(self):
        jdk = next(p for p in toolchains.TOOLCHAINS if p["name"] == "jdk")
        self.assertEqual(toolchains.landed_since("n1", 100), [jdk["label"]],
                         "jdk landed after; go before; node's install failed")
        self.assertEqual(toolchains.landed_since("n1", 0), [], "a session with no start time is not judged")


class Rows(unittest.TestCase):
    def test_the_reason_rides_the_row(self):
        saved = {k: getattr(projsessions, k) for k in ("BASE", "OWNER", "ACCOUNTS", "OWNER_NAME", "BEHIND")}
        self.addCleanup(lambda: [setattr(projsessions, k, v) for k, v in saved.items()])
        projsessions.BASE = lambda n: n.split("~", 1)[-1]
        projsessions.OWNER = lambda n: n.split("~", 1)[0]
        projsessions.ACCOUNTS = lambda: {"u_1": "sam"}
        projsessions.OWNER_NAME = lambda: "sam"
        projsessions.BEHIND = lambda s: ["jdk installed on box since it started"] if s.get("created") == 1 else []
        got = projsessions.where([{"name": "u_1~claude-app", "node": "box", "created": 1},
                                  {"name": "u_1~claude-web", "node": "box", "created": 9}])
        self.assertEqual(got["app"][0]["behind"], ["jdk installed on box since it started"])
        self.assertEqual(got["web"][0]["behind"], [])


if __name__ == "__main__":
    unittest.main()
