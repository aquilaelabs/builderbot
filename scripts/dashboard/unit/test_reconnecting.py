"""Right after the controller starts, a node it heard a moment before it went
down is reconnecting, not down: its project cards say so quietly rather than in red
(the operator, 7 Oct). The function, read from server.py and run on its own
(importing the server opens /config)."""
import ast
import os
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "..", "server.py"), encoding="utf-8").read()
FNS = [n for n in ast.parse(SRC).body if isinstance(n, ast.FunctionDef) and n.name in ("_went_down", "_reconnecting")]


def reconnecting(n, started, wait=300, others=()):
    class Nodes:
        @staticmethod
        def node_list():
            return [{"kind": "agent", **x} for x in (n, *others)]
    ns = {"time": time, "STARTED": started, "NODE_WAIT": wait, "_DOWN": [], "nodes": Nodes}
    exec(compile(ast.Module(FNS, []), "server.py", "exec"), ns)  # noqa: S102 (our own function)
    return ns["_reconnecting"](n)


def node(seen):
    return {"agent": {"last_seen": seen}}


class Reconnecting(unittest.TestCase):
    def test_seen_just_before_the_start_and_inside_the_wait(self):
        now = time.time()
        self.assertTrue(reconnecting(node(now - 30), started=now - 10))

    def test_seen_long_before_the_others_is_down(self):
        now = time.time()
        self.assertFalse(reconnecting(node(now - 7200), started=now - 10, others=[node(now - 30)]))

    def test_seen_just_before_a_long_outage_is_reconnecting(self):
        # The controller was down an hour (19 Oct): what counts is how near
        # its going down the node was heard, not how near its start.
        now = time.time()
        self.assertTrue(reconnecting(node(now - 3630), started=now - 10, others=[node(now - 3600)]))

    def test_off_long_before_the_outage_is_down(self):
        now = time.time()
        self.assertFalse(reconnecting(node(now - 90000), started=now - 10, others=[node(now - 3600)]))

    def test_past_the_wait_is_down(self):
        now = time.time()
        self.assertFalse(reconnecting(node(now - 700), started=now - 600))


if __name__ == "__main__":
    unittest.main()
