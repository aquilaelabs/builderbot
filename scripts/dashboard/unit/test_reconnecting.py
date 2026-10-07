"""Right after the controller starts, a node it saw a moment before is
reconnecting, not down: its project cards say so quietly rather than in red
(the operator, 7 Oct). The function, read from server.py and run on its own
(importing the server opens /config)."""
import ast
import os
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "..", "server.py"), encoding="utf-8").read()
FN = next(n for n in ast.parse(SRC).body if isinstance(n, ast.FunctionDef) and n.name == "_reconnecting")


def reconnecting(n, started, wait=300):
    ns = {"time": time, "STARTED": started, "NODE_WAIT": wait}
    exec(compile(ast.Module([FN], []), "server.py", "exec"), ns)  # noqa: S102 (our own function)
    return ns["_reconnecting"](n)


def node(seen):
    return {"agent": {"last_seen": seen}}


class Reconnecting(unittest.TestCase):
    def test_seen_just_before_the_start_and_inside_the_wait(self):
        now = time.time()
        self.assertTrue(reconnecting(node(now - 30), started=now - 10))

    def test_seen_long_before_the_start_is_down(self):
        now = time.time()
        self.assertFalse(reconnecting(node(now - 7200), started=now - 10))

    def test_past_the_wait_is_down(self):
        now = time.time()
        self.assertFalse(reconnecting(node(now - 700), started=now - 600))


if __name__ == "__main__":
    unittest.main()
