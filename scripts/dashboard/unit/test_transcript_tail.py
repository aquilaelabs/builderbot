"""bb transcripts show prints the newest part of a long conversation: read
from the start, a day-long one (900 MB on 19 Oct) outran the verb's wait and
printed nothing, when the end is what a session coming back to it needs."""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import transcripts  # noqa: E402


def said(text):
    return json.dumps({"type": "user", "message": {"content": text}}) + "\n"


class Tail(unittest.TestCase):
    def setUp(self):
        self.f = pathlib.Path(tempfile.mkdtemp()) / "s.jsonl"
        self.f.write_text(said("the first ask") + said("x" * (2 * 1024 * 1024)) + said("the last ask"))

    def render(self, tail):
        with mock.patch.object(transcripts, "_find", lambda *a: self.f):
            return transcripts.render("u_1", "alpha", "s", tail=tail)[0]

    def test_a_long_one_is_read_from_its_end(self):
        text = self.render(1024 * 1024)
        self.assertIn("the last ask", text)
        self.assertNotIn("the first ask", text)
        self.assertIn("[the newest 1 MB of 2 MB]", text)

    def test_a_short_one_or_no_tail_is_whole(self):
        for tail in (0, 8 * 1024 * 1024):
            text = self.render(tail)
            self.assertIn("the first ask", text)
            self.assertNotIn("the newest", text)


if __name__ == "__main__":
    unittest.main()


class Resumable(unittest.TestCase):
    """A conversation with nothing said in it is not offered as Resume (B276):
    Claude Code does not resume it, and bb-tty said No transcript."""

    def test_only_a_conversation_with_a_turn_counts(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "said.jsonl").write_text(said("fix the login"))
        (d / "empty.jsonl").write_text(json.dumps({"type": "summary", "summary": "x"}) + "\n")
        self.assertTrue(transcripts.has_turn(d / "said.jsonl"))
        self.assertFalse(transcripts.has_turn(d / "empty.jsonl"))
