"""A toolchain install asks its source's host first (R82): a machine with
no internet is told in one sentence, naming the host, before anything is
touched."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import sdkmeta  # noqa: E402


class Reach(unittest.TestCase):
    def test_the_source_host_is_the_catalogs(self):
        self.assertEqual(sdkmeta.source_host(sdkmeta.toolchain("node")), "nodejs.org")
        self.assertEqual(sdkmeta.source_host(sdkmeta.toolchain("android:ndk")), "dl.google.com")
        self.assertEqual(sdkmeta.source_host({"source": {"kind": "command"}}), "")

    def test_a_name_that_does_not_resolve_is_said(self):
        with mock.patch("socket.getaddrinfo", side_effect=OSError("no")):
            self.assertIn("could not be looked up", sdkmeta.unreachable("nodejs.org"))

    def test_a_host_that_does_not_answer_is_said(self):
        with mock.patch("socket.getaddrinfo", return_value=[]), \
             mock.patch("socket.create_connection", side_effect=OSError(113, "No route to host")):
            self.assertIn("nodejs.org did not answer (No route to host)", sdkmeta.unreachable("nodejs.org"))

    def test_a_host_that_answers_is_nothing(self):
        conn = mock.MagicMock()
        with mock.patch("socket.getaddrinfo", return_value=[]), \
             mock.patch("socket.create_connection", return_value=conn):
            self.assertEqual(sdkmeta.unreachable("nodejs.org"), "")


if __name__ == "__main__":
    unittest.main()
