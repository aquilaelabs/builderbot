"""Home's numbers (R218 step 5, home.py): the jobs running and failed today,
the last ten, the nodes online of enrolled and the containers across the
docker nodes, with a node that does not answer counted as unknown rather
than holding the page."""
import contextlib
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import home  # noqa: E402


class Nodes:
    rows = []

    @staticmethod
    def node_list():
        return Nodes.rows


class Devapp:
    """devapp's two calls, with the node a thread is addressing kept per
    thread, as devapp's own context is: the read runs one thread a node."""
    listings = {}
    _here = threading.local()

    @staticmethod
    @contextlib.contextmanager
    def on_node(nid):
        Devapp._here.nid = nid
        yield

    @staticmethod
    def containers():
        got = Devapp.listings.get(Devapp._here.nid)
        if got == "slow":
            time.sleep(3)
            return {"containers": []}
        return got


class Home(unittest.TestCase):
    def setUp(self):
        home.configure(nodes_mod=Nodes, devapp_mod=Devapp)
        self.addCleanup(setattr, home, "CONTAINER_WAIT_S", home.CONTAINER_WAIT_S)
        self.addCleanup(setattr, home, "KEPT_WAIT_S", home.KEPT_WAIT_S)
        home._kept.clear()
        Nodes.rows = [
            {"id": "n_a", "kind": "agent", "state": "online", "live": True, "reported": {"docker": "29"}},
            {"id": "n_b", "kind": "agent", "state": "online", "live": False, "reported": {"docker": "29"}},
            {"id": "n_c", "kind": "agent", "state": "retired", "reported": {"docker": "29"}},
            {"id": "local", "kind": "local", "state": "online"},
        ]
        Devapp.listings = {
            "n_a": {"containers": [{"state": "running"}, {"state": "exited"}]},
            "n_b": {"containers": [{"state": "running"}], "stale": True},
        }

    def test_jobs_running_failed_today_and_the_last_ten(self):
        now = time.time()
        rows = [{"id": f"j_{i}", "state": "succeeded", "queued": now - i} for i in range(12)]
        rows += [{"id": "j_run", "state": "running", "queued": now},
                 {"id": "j_fail", "state": "failed", "queued": now, "ended": now},
                 {"id": "j_old", "state": "failed", "queued": now - 3 * 86400, "ended": now - 3 * 86400}]
        got, code = home.read(rows, {}, False)
        self.assertEqual(code, 200)
        self.assertEqual((got["jobs"]["running"], got["jobs"]["failed_today"]), (1, 1))
        self.assertEqual(len(got["jobs"]["last"]), 10)
        self.assertIsNone(got["nodes"], "an account that does not count the machines is told nothing of them")

    def test_machines_and_their_containers(self):
        got, _ = home.read([], {}, True)
        self.assertEqual(got["nodes"], {"enrolled": 2, "online": 1})
        c = got["containers"]
        self.assertEqual((c["running"], c["all"], c["nodes"], c["stale"], c["unknown"]), (2, 3, 2, 1, 0))

    def test_a_light_read_asks_no_node_for_its_containers(self):
        Devapp.listings = {}
        got, _ = home.read([], {}, True, light=True)
        self.assertEqual(got["nodes"]["enrolled"], 2)
        self.assertIsNone(got["containers"], "the page keeps the containers it had")

    def test_a_node_that_does_not_answer_is_unknown_not_waited_for(self):
        Devapp.listings["n_b"] = "slow"
        home.CONTAINER_WAIT_S = 0.5
        t0 = time.time()
        got, _ = home.read([], {}, True)
        self.assertLess(time.time() - t0, 2, "the read did not wait for the slow node")
        self.assertEqual((got["containers"]["running"], got["containers"]["unknown"]), (1, 1))

    def test_a_node_answered_before_is_counted_from_it_not_waited_for(self):
        home.read([], {}, True)
        Devapp.listings["n_a"] = "slow"
        home.KEPT_WAIT_S = 0.3
        t0 = time.time()
        got, _ = home.read([], {}, True)
        self.assertLess(time.time() - t0, 1, "every node had answered before, so the read waited the short time")
        c = got["containers"]
        self.assertEqual((c["running"], c["all"], c["stale"], c["unknown"]), (2, 3, 2, 0),
                         "the slow node counted from its last listing, as last seen")


if __name__ == "__main__":
    unittest.main()
