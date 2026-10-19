"""A node heard again re-asks the doctor (the operator, 19 Oct: after a crash
the card kept saying draconis and bb-sandbox were not dialing in long after
both were back). Two ways that ask was lost: one made while a run was out was
dropped, and a starting agent's beat made the node live before its hello, so
the hello never asked."""
import os
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import doctor  # noqa: E402
import nodes  # noqa: E402


class AskedMidRun(unittest.TestCase):
    def test_an_ask_while_one_is_out_runs_again_after_it(self):
        runs, inside, go = [], threading.Event(), threading.Event()

        def run(argv, timeout):
            runs.append(argv)
            if len(runs) == 1:
                inside.set()
                go.wait(5)
            return {"out": "  [ok]   fine\n", "code": 0}
        doctor.configure(run=run, wait_for_boot=lambda: None)
        t = threading.Thread(target=doctor.refresh)
        t.start()
        inside.wait(5)
        self.assertFalse(doctor.refresh(), "a second run at once is not started")
        go.set()
        t.join(5)
        self.assertEqual(len(runs), 2, "the ask made mid-run is run when that one ends")
        self.assertFalse(doctor.payload()["running"])
        self.assertTrue(doctor.refresh(), "and the next ask runs as before")
        self.assertEqual(len(runs), 3)


class HeardAgain(unittest.TestCase):
    def setUp(self):
        nodes.configure(state=tempfile.mkdtemp())
        mint = nodes.enroll_mint("user:test", "box")
        nodes.enroll(nodes.authenticate(mint["token"]), {"cpu": 2, "mem_mb": 4096, "arch": "x86_64",
                                                         "system": "linux"}, "10.0.0.5", user="bb")
        self.nid = mint["id"]
        self.back = []
        self.was = nodes.came_back
        nodes.came_back = self.back.append
        nodes._exec("UPDATE nodes SET agent = json_set(agent, '$.last_seen', 1) WHERE id = ?", (self.nid,))
        nodes.checks_wanted.discard(self.nid)

    def tearDown(self):
        nodes.came_back = self.was

    def test_a_beat_from_a_quiet_node_says_it_came_back(self):
        r0 = nodes._rev[0]
        nodes.beat(self.nid)
        self.assertEqual(self.back, [self.nid])
        self.assertIn(self.nid, nodes.checks_wanted, "its toolchains are checked on its start, as a hello's were")
        self.assertNotEqual(nodes._rev[0], r0, "the pages that say it is offline are told")
        nodes.beat(self.nid)
        self.assertEqual(self.back, [self.nid], "once: a live node's beat is not news")

    def test_a_heartbeat_from_a_quiet_node_says_it_came_back(self):
        nodes.heartbeat(self.nid, {}, "10.0.0.5")
        self.assertEqual(self.back, [self.nid])


if __name__ == "__main__":
    unittest.main()
