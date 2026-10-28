"""Reporting (R164 step 4): the own machine's samples kept for weeks at
falling resolution: five-minute means closed into points, a closed hour
folded into one, the rates from the agent's counters (a counter back to
zero skipped, never a spike), the spans read back with the open bucket as
the last point, and one file per node under the state."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import history  # noqa: E402


class History(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        history.configure(state=self.d)

    def feed(self, t0, n, step=30):
        for i in range(n):
            at = t0 + i * step
            history.add("n1", {"at": at, "cpu_pct": 10 + (i % 2) * 20, "mem_mb": 1000, "mem_used_mb": 250,
                               "net": [1000 * i * step, 500 * i * step], "io": [200 * i * step, 100 * i * step], "temp_c": 40}, disk_temp=35)

    def test_buckets_close_into_points_and_an_hour_folds(self):
        t0 = 1_700_000_000 - 1_700_000_000 % 3600
        self.feed(t0, 2 * 120 + 1)                       # two hours and a sample
        got = history.points("n1", "6h")
        self.assertEqual(got["fields"], list(history.FIELDS))
        self.assertEqual(got["step"], 300)
        closed = got["points"][:-1]
        self.assertEqual(len(closed), 24, "twelve five-minute points an hour, two hours")
        self.assertEqual(closed[0][0], t0)
        cpu, mem, rx, tx, rd, wr, temp, dtemp = closed[1][1:]
        self.assertEqual((cpu, mem, temp, dtemp), (20.0, 25.0, 40.0, 35.0))
        self.assertEqual((rx, tx, rd, wr), (1000.0, 500.0, 200.0, 100.0), "the rates from the counters' differences")
        self.assertEqual(closed[0][3], 1000.0, "the first sample has nothing before it and is left out of the mean")
        self.assertEqual(got["points"][-1][0], t0 + 7200, "the bucket still open comes last")
        week = history.points("n1", "week")
        self.assertEqual(week["step"], 3600)
        self.assertEqual([p[0] for p in week["points"]], [t0, t0 + 3600, t0 + 7200])
        self.assertEqual(week["points"][0][1], 20.0)
        with open(os.path.join(self.d, "history", "n1.json")) as f:
            on_disk = json.load(f)
        self.assertEqual((len(on_disk["m5"]), len(on_disk["h1"])), (24, 2))

    def test_a_counter_back_to_zero_is_a_skipped_point_and_a_reload_reads_the_file(self):
        t0 = 1_700_000_000 - 1_700_000_000 % 3600
        history.add("n1", {"at": t0, "cpu_pct": 1, "mem_mb": 1, "mem_used_mb": 0, "net": [5000, 5000], "io": [1, 1]})
        history.add("n1", {"at": t0 + 30, "cpu_pct": 1, "mem_mb": 1, "mem_used_mb": 0, "net": [10, 10], "io": [2, 2]})
        history.add("n1", {"at": t0 + 60, "cpu_pct": 1, "mem_mb": 1, "mem_used_mb": 0, "net": [310, 10], "io": [2, 2]})
        history.add("n1", {"at": t0 + 300, "cpu_pct": 1, "mem_mb": 1, "mem_used_mb": 0, "net": [310, 10], "io": [2, 2]})
        p = history.points("n1", "day")["points"][0]
        self.assertEqual(p[3], 10.0, "only the one honest difference counts (300 bytes over 30 s)")
        history.configure(state=self.d)
        self.assertEqual(len(history.points("n1", "day")["points"]), 1, "read back from the file, the open bucket gone with the restart")
        history.forget("n1")
        self.assertFalse(os.path.exists(os.path.join(self.d, "history", "n1.json")))

    def test_the_rings_are_held_to_their_length(self):
        t0 = 1_700_000_000 - 1_700_000_000 % 3600
        self.feed(t0, 50 * 12 * 2, step=150)              # fifty hours, one sample per 150 s
        self.assertEqual(len(history.points("n1", "day")["points"]), 289)
        with open(os.path.join(self.d, "history", "n1.json")) as f:
            on_disk = json.load(f)
        self.assertEqual(len(on_disk["m5"]), history.M5_KEEP)
        self.assertEqual(len(on_disk["h1"]), 49)


if __name__ == "__main__":
    unittest.main()
