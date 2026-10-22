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


class HeldNotes(unittest.TestCase):
    """R251: a session held by the gate may still keep its own notes, its
    memory and its scratchpad being files on its own machine; anything else
    is refused, with the sentence saying to write where it is and stop."""
    def run_gate(self, make_call):
        import io
        import json
        import sys
        import tempfile
        home = tempfile.mkdtemp()
        env, argv = dict(os.environ), sys.argv
        os.environ.update(HOME=home, BB_ACCOUNT_UID="u_1")
        os.environ.pop("XDG_CACHE_HOME", None)
        was_in, was_err, was_answers = sys.stdin, sys.stderr, gate.controller_answers
        sys.stdin, sys.stderr = io.StringIO(json.dumps(make_call(home))), io.StringIO()
        gate.controller_answers = lambda project: False
        sys.argv = ["bb-gate", "alpha", "s"]
        try:
            return gate.main(), sys.stderr.getvalue()
        finally:
            sys.stdin, sys.stderr, gate.controller_answers, sys.argv = was_in, was_err, was_answers, argv
            os.environ.clear()
            os.environ.update(env)

    def test_memory_and_the_scratchpad_are_allowed(self):
        code, _ = self.run_gate(lambda home: {"tool_name": "Write", "tool_input": {
            "file_path": home + "/.claude/projects/x/memory/where.md"}})
        self.assertEqual(code, 0, "its memory")
        code, _ = self.run_gate(lambda home: {"tool_name": "Edit", "tool_input": {
            "file_path": "/tmp/claude-99/x/scratchpad/n.md"}})
        self.assertEqual(code, 0, "its scratchpad")
        code, _ = self.run_gate(lambda home: {"tool_name": "TodoWrite", "tool_input": {}})
        self.assertEqual(code, 0, "its to-do list")
        # ...and Codex's and Copilot's own, which reach the gate as Edit
        # through bb-agent-hook (R95 step 18).
        code, _ = self.run_gate(lambda home: {"tool_name": "Edit", "tool_input": {
            "file_path": home + "/.codex/notes.md"}})
        self.assertEqual(code, 0, "Codex's own folder")
        code, _ = self.run_gate(lambda home: {"tool_name": "update_plan", "tool_input": {}})
        self.assertEqual(code, 0, "Codex's plan")

    def test_a_hold_is_marked_and_cleared(self):
        # R251: the mark its node's agent reports, for the bell's Resume.
        import json
        import tempfile
        home = tempfile.mkdtemp()
        hf = os.path.join(home, "gate-dir", "held")
        os.makedirs(os.path.dirname(hf))
        sf = os.path.join(home, "gate-dir", "gate")
        gate.held_mark(sf, "claude-alpha", True, 1000)
        gate.held_mark(sf, "claude-alpha", True, 2000)
        with open(hf) as f:
            self.assertEqual(json.load(f), {"session": "claude-alpha", "since": 1000}, "kept from the first refusal")
        gate.held_mark(sf, "claude-alpha", False, 3000)
        self.assertFalse(os.path.exists(hf), "gone with the first call let through")

    def test_the_rest_is_held_with_what_to_do(self):
        code, said = self.run_gate(lambda home: {"tool_name": "Bash", "tool_input": {"command": "bb status"}})
        self.assertEqual(code, 2)
        self.assertIn("write where you are and what is next", said)
        code, _ = self.run_gate(lambda home: {"tool_name": "Write", "tool_input": {"file_path": "/workspace/alpha/main.py"}})
        self.assertEqual(code, 2, "the project's own files are not notes")
        code, _ = self.run_gate(lambda home: {"tool_name": "Write", "tool_input": {
            "file_path": home + "/.claude/../elsewhere.txt"}})
        self.assertEqual(code, 2, "a path that only starts out in ~/.claude is resolved first")
