"""A node's last hour for its charts (R218 step 9): the controller keeps each
heartbeat's sample, and each running container's use the agent sends once a
minute, in rings held by time, not by count, since the poll's interval is a
setting; what a node sends about its containers is whitelisted like
everything else it says."""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import nodes  # noqa: E402


class Spark(unittest.TestCase):
    def setUp(self):
        nodes.configure(state=tempfile.mkdtemp())
        mint = nodes.enroll_mint("user:test", "box")
        nodes.enroll(nodes.authenticate(mint["token"]), {"cpu": 2, "mem_mb": 4096, "arch": "x86_64",
                                                         "system": "linux", "session": {"up": True, "user": "b"}},
                     "10.0.0.5", user="bb")
        self.nid = mint["id"]
        nodes._samples.pop(self.nid, None)
        nodes._ctr_samples.pop(self.nid, None)

    def beat(self, at, sample):
        with mock.patch.object(nodes.time, "time", return_value=at):
            nodes.heartbeat(self.nid, sample, "10.0.0.5")

    def test_the_ring_holds_the_last_hour(self):
        t0 = 1_000_000
        for i in range(200):                 # 200 polls 25s apart: 83 minutes
            self.beat(t0 + i * 25, {"cpu_pct": i % 100, "mem_mb": 4000, "mem_used_mb": 1000})
        got = nodes.spark_of(self.nid)
        last = t0 + 199 * 25
        self.assertEqual(got[-1][0], last)
        self.assertGreaterEqual(got[0][0], last - nodes.SAMPLES_KEEP_S)
        self.assertEqual(len(got), 145)      # 3600 / 25 + the one at the edge
        self.assertEqual(got[-1][1:], [99.0 % 100, 25.0])  # cpu %, memory % of the total

    def test_a_containers_use_is_whitelisted_and_kept_an_hour(self):
        t0 = 2_000_000
        self.beat(t0, {"ctr_stats": {"web-1": [12.5, 40.0], "../etc/x": [1, 2], "bad": "nope",
                                     "short": [3], "loud": [-5, 250]}})
        self.beat(t0 + 60, {"ctr_stats": {"web-1": [20, 41]}})
        got = nodes.ctr_spark(self.nid)
        self.assertEqual(set(got), {"web-1", "..etcx", "loud"})
        self.assertEqual(got["web-1"], [[t0, 12.5, 40.0], [t0 + 60, 20.0, 41.0]])
        self.assertEqual(got["loud"], [[t0, 0.0, 100.0]], "clamped: no negative CPU, no memory past 100%")
        self.assertEqual(set(nodes.ctr_spark(self.nid, {"web-1"})), {"web-1"})
        # A container gone for more than an hour is forgotten.
        self.beat(t0 + 3700, {"ctr_stats": {"web-1": [5, 10]}})
        self.assertEqual(set(nodes.ctr_spark(self.nid)), {"web-1"})
        self.assertEqual(nodes.ctr_spark(self.nid)["web-1"], [[t0 + 3700, 5.0, 10.0]])

    def test_the_nodes_read_carries_it(self):
        self.beat(3_000_000, {"cpu_pct": 7, "mem_mb": 2000, "mem_used_mb": 500})
        with mock.patch.object(nodes, "turns_of", lambda n: {}), mock.patch.object(nodes, "node_for", lambda: ""):
            row = next(n for n in nodes.tab_view(nodes.node_list(), False)["nodes"] if n["id"] == self.nid)
        self.assertEqual(row["spark"], [[3_000_000, 7.0, 25.0]])


if __name__ == "__main__":
    unittest.main()
