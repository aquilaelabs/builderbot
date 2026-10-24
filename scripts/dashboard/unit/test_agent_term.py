"""BuilderBot's own terminal on a node (R133, term.py on screen.py's port):
only what the controller signed opens, and the program it runs is the one
the session agent recorded for that kind, in a real pty. Keys typed reach
it, a resize reaches it, a read-only terminal drops keys, and when the
program ends the socket closes saying how."""
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "agent"))
from builderbot_agent import screen, term  # noqa: E402

KEY = screen.screen_key("bbn_secret")


def masked(payload, op=2):
    """A browser's frame: always masked."""
    mask = b"\x01\x02\x03\x04"
    n = len(payload)
    head = bytes([0x80 | op]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n))
    return head + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload))


class Client:
    """One connection to serve_one, as the controller's proxy makes it."""
    def __init__(self, blob, when=None, sig=None, kinds=None):
        a, b = socket.socketpair()
        self.sock, self.frames = a, screen._Frames()
        when = int(time.time()) if when is None else when
        sig = term.sign(KEY, blob, when) if sig is None else sig
        self.t = threading.Thread(target=self._serve, args=(b, kinds), daemon=True)
        self.t.start()
        key = base64.b64encode(os.urandom(16)).decode()
        a.sendall(f"GET /term?a={blob}&t={when}&s={sig} HTTP/1.1\r\nHost: n\r\nUpgrade: websocket\r\n"
                  f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n\r\n".encode())
        self.head = b""
        a.settimeout(10)
        while b"\r\n\r\n" not in self.head:
            got = a.recv(4096)
            if not got:
                break
            self.head += got
        self.head, _, rest = self.head.partition(b"\r\n\r\n")
        self.got = list(self.frames.feed(rest)) if rest else []

    def _serve(self, b, kinds):
        try:
            screen.serve_one(b, KEY, kinds)
        finally:
            b.close()

    def send(self, kind, body):
        self.sock.sendall(masked(bytes([kind]) + body))

    def read_until(self, pred, secs=10):
        """The pty's bytes so far, and the close frame's reason if it came."""
        end, out, closed = time.time() + secs, b"", None
        for op, d in self.got:
            out, closed = (out + d, closed) if op == 2 else (out, d[2:] if op == 8 else closed)
        self.got = []
        while time.time() < end and not pred(out, closed):
            try:
                got = self.sock.recv(65536)
            except socket.timeout:
                break
            if not got:
                break
            for op, d in self.frames.feed(got):
                if op == 2:
                    out += d
                elif op == 8:
                    closed = d[2:]
        return out, closed


def kinds(argv):
    how = {"argv": argv, "env": {"PATH": os.environ["PATH"], "TERM": "xterm", "LANG": "C.UTF-8"},
           "who": {}, "cwd": "/"}
    return lambda: {"rw": how, "ro": how}


class Term(unittest.TestCase):
    def test_a_blob_names_a_kind_and_its_words_and_nothing_else(self):
        self.assertEqual(term.unpack(term.pack({"kind": "rw", "argv": ["claude:web"], "cols": 120, "rows": 40})),
                         {"kind": "rw", "argv": ["claude:web"], "cols": 120, "rows": 40})
        for bad in ({"kind": "root", "argv": []}, {"kind": "rw", "argv": "claude:web"},
                    {"kind": "rw", "argv": ["a\0b"]}, {"kind": "rw", "argv": ["x"] * 40}):
            self.assertIsNone(term.unpack(term.pack(bad)), bad)
        self.assertIsNone(term.unpack("not base64 json"))

    def test_an_unsigned_or_stale_terminal_is_refused(self):
        blob = term.pack({"kind": "rw", "argv": ["x"]})
        c = Client(blob, sig="0" * 64, kinds=kinds(["/bin/cat"]))
        self.assertIn(b"403", c.head)
        c = Client(blob, when=int(time.time()) - 600, kinds=kinds(["/bin/cat"]))
        self.assertIn(b"403", c.head)
        other = term.pack({"kind": "rw", "argv": ["y"]})
        c = Client(blob, sig=term.sign(KEY, other, int(time.time())), kinds=kinds(["/bin/cat"]))
        self.assertIn(b"403", c.head, "a signature is for the one terminal it names")

    def test_a_rotation_s_previous_key_is_taken_beside_the_current(self):
        # The controller signs with the token it has seen used, for a few
        # minutes the one before a rotation (R135 step 4).
        blob, now = term.pack({"kind": "rw", "argv": ["x"]}), int(time.time())
        old, new = screen.screen_key("bbn_old"), screen.screen_key("bbn_new")
        self.assertTrue(term.signed([new, old], blob, now, term.sign(old, blob, now)))
        self.assertFalse(term.signed([new], blob, now, term.sign(old, blob, now)))

    def test_no_terminals_up_says_so(self):
        c = Client(term.pack({"kind": "rw", "argv": []}), kinds=lambda: {})
        self.assertIn(b"409", c.head)

    def test_keys_and_a_resize_reach_the_program_in_its_pty(self):
        # A shell that prints the size it is given, then echoes a line.
        script = 'stty size; read x; echo "got:$x"; stty size'
        c = Client(term.pack({"kind": "rw", "argv": ["-c", script], "cols": 100, "rows": 30}),
                   kinds=kinds(["/bin/sh"]))
        self.assertIn(b"101 Switching Protocols", c.head)
        out, _ = c.read_until(lambda o, _: b"30 100" in o)
        self.assertIn(b"30 100", out, "the size asked for at the start")
        c.send(1, json.dumps({"cols": 90, "rows": 20}).encode())
        time.sleep(0.2)
        c.send(0, b"hello\r")
        out, closed = c.read_until(lambda o, cl: cl is not None)
        self.assertIn(b"got:hello", out)
        self.assertIn(b"20 90", out, "the resize reached the pty")
        self.assertEqual(closed, b"ended", "the close says the program ended")

    def test_a_resize_is_signalled_as_tmux_needs(self):
        # The pty is the program's controlling terminal, so a resize is a
        # SIGWINCH to it: what makes tmux redraw at the new size.
        c = Client(term.pack({"kind": "rw", "argv": ["-c", 'trap "echo winch" WINCH; echo up; '
                                                           'i=0; while [ $i -lt 50 ]; do sleep 0.1; i=$((i+1)); done']}),
                   kinds=kinds(["/bin/sh"]))
        c.read_until(lambda o, _: b"up" in o)
        c.send(1, json.dumps({"cols": 70, "rows": 15}).encode())
        out, _ = c.read_until(lambda o, _: b"winch" in o, secs=5)
        self.assertIn(b"winch", out)

    def test_the_program_is_told_its_terminal(self):
        # tmux refuses a terminal it has no entry for: the pty says what
        # xterm.js is, as ttyd did, whatever the environment it was given.
        how = {"argv": ["/bin/sh"], "env": {"PATH": os.environ["PATH"]}, "who": {}, "cwd": "/"}
        c = Client(term.pack({"kind": "rw", "argv": ["-c", "echo term:$TERM"]}), kinds=lambda: {"rw": how})
        out, _ = c.read_until(lambda o, cl: cl is not None)
        self.assertIn(b"term:xterm-256color", out)

    def test_read_only_drops_keys(self):
        c = Client(term.pack({"kind": "ro", "argv": ["-c", "read -t 2 x; echo \"got:[$x]\""]}),
                   kinds=kinds(["/bin/sh"]))
        c.send(0, b"typed\r")
        out, closed = c.read_until(lambda o, cl: cl is not None)
        self.assertIn(b"got:[]", out)
        self.assertNotIn(b"got:[typed]", out)

    def test_an_exit_code_is_said(self):
        c = Client(term.pack({"kind": "rw", "argv": ["-c", "exit 3"]}), kinds=kinds(["/bin/sh"]))
        _, closed = c.read_until(lambda o, cl: cl is not None)
        self.assertEqual(closed, b"ended with exit code 3")

    def test_the_relay_unmasks_a_long_frame_whole(self):
        f = screen._Frames()
        payload = os.urandom(70000)
        mask = b"\x09\x08\x07\x06"
        frame = bytes([0x82, 0x80 | 127]) + struct.pack(">Q", len(payload)) + mask \
            + bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
        self.assertEqual(f.feed(frame), [(2, payload)])
        self.assertEqual(hashlib.sha256(payload).digest(), hashlib.sha256(f.feed(b"") and b"" or payload).digest())


if __name__ == "__main__":
    unittest.main()


class Census(unittest.TestCase):
    def test_the_controller_keeps_whether_a_node_serves_its_own_terminal(self):
        # The controller keeps a node's session half field by field; one it
        # drops reads as a node that serves none, and every tab there went
        # back to ttyd (found walking it on the dev pair).
        sys.path.insert(0, os.path.join(HERE, ".."))
        import nodes
        got = nodes._census({"session": {"up": True, "port": 7681, "ro_port": 7682, "term": True}})
        self.assertIs(got["session"]["term"], True)
        self.assertIs(nodes._census({"session": {"up": True}})["session"]["term"], False)
