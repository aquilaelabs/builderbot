"""bb-gate's liveness verdict (B719): a controller that accepts the
connection and is slow to answer is busy, not down; only a connection nobody
accepts is a restart or an outage."""
import importlib.machinery
import importlib.util
import os
import socket
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


gate = load("bb_gate", os.path.join(HERE, "..", "bb-gate"))


class FakeConn:
    """An HTTPConnection as the gate uses it: connect, request, getresponse,
    close. `fail` names which step raises, and with what."""
    def __init__(self, fail=None):
        self.fail = fail or {}
        self.sock = None
        self.closed = False

    def connect(self):
        if "connect" in self.fail:
            raise self.fail["connect"]
        self.sock = object()

    def request(self, *_a, **_k):
        if "request" in self.fail:
            raise self.fail["request"]

    def getresponse(self):
        if "response" in self.fail:
            raise self.fail["response"]
        class R:
            status = 401
            def read(self):
                return b'{"error": "not signed in"}'
        return R()

    def close(self):
        self.closed = True


class Answers(unittest.TestCase):
    def ask(self, conn):
        was = gate.bbapi._conn
        gate.bbapi._conn = lambda timeout: (conn, "")
        try:
            return gate.controller_answers("p")
        finally:
            gate.bbapi._conn = was

    def test_a_refusal_is_an_answer(self):
        c = FakeConn()
        self.assertTrue(self.ask(c))
        self.assertTrue(c.closed)

    def test_a_slow_answer_is_a_busy_controller_not_a_down_one(self):
        c = FakeConn(fail={"response": socket.timeout("timed out")})
        self.assertTrue(self.ask(c), "the connection was accepted, so something is listening")
        self.assertTrue(c.closed)

    def test_a_connection_nobody_accepts_is_down(self):
        self.assertFalse(self.ask(FakeConn(fail={"connect": ConnectionRefusedError()})))
        self.assertFalse(self.ask(FakeConn(fail={"connect": socket.timeout("timed out")})),
                         "a connect that times out is a host that is not there")

    def test_a_connection_dropped_mid_answer_is_down(self):
        self.assertFalse(self.ask(FakeConn(fail={"response": ConnectionResetError()})))

    def test_an_already_connected_helper_is_not_reconnected(self):
        # https connects inside _conn, for the certificate pin.
        c = FakeConn()
        c.sock = object()
        c.connect = lambda: (_ for _ in ()).throw(AssertionError("connected twice"))
        self.assertTrue(self.ask(c))


if __name__ == "__main__":
    unittest.main()
