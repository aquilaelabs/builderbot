"""termws.term_follow (R133 step 12): a log in a dock tab, followed. What is
new is sent as it is written, a log rewritten (not the same text grown) is
drawn again, the end is said and the socket closed, and the reader's grant
going ends it."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import termws  # noqa: E402


class Conn:
    """A socket that takes what is sent and never has anything to read."""
    def __init__(self):
        self.out = []

    def settimeout(self, _s):
        pass

    def sendall(self, data):
        self.out.append(data)

    def recv(self, _n):
        raise TimeoutError()

    def payloads(self):
        got = []
        for f in self.out:
            n, i = f[1] & 0x7F, 2
            if n == 126:
                n, i = struct.unpack(">H", f[2:4])[0], 4
            got.append((f[0] & 0x0F, f[i:i + n]))
        return got


class Follow(unittest.TestCase):
    def setUp(self):
        termws.FOLLOW_S = 0

    def test_what_is_new_is_sent_and_the_end_closes_it(self):
        steps = iter([("one\n", ""), ("one\ntwo\n", ""), ("one\ntwo\n", "the job succeeded")])
        c = Conn()
        termws.term_follow(c, lambda: next(steps))
        p = c.payloads()
        self.assertEqual(p[0], (2, b"one\r\n"))
        self.assertEqual(p[1], (2, b"two\r\n"))
        self.assertIn(b"[the job succeeded]", p[2][1])
        self.assertEqual(p[-1][0], 8, "closed, saying why")
        self.assertIn(b"the job succeeded", p[-1][1])

    def test_a_rewritten_log_is_drawn_again(self):
        steps = iter([("abc\n", ""), ("xyz\n", ""), ("xyz\n", "done")])
        c = Conn()
        termws.term_follow(c, lambda: next(steps))
        self.assertEqual(c.payloads()[1], (2, b"\x1b[2J\x1b[Hxyz\r\n"))

    def test_a_grant_that_goes_ends_it(self):
        termws.CHECK_S, was = 0, termws.CHECK_S
        self.addCleanup(lambda: setattr(termws, "CHECK_S", was))
        c = Conn()
        termws.term_follow(c, lambda: ("x\n", ""), alive=lambda: "no longer yours to read")
        self.assertEqual(c.payloads()[-1][0], 8)
        self.assertIn(b"no longer yours to read", c.payloads()[-1][1])


if __name__ == "__main__":
    unittest.main()
