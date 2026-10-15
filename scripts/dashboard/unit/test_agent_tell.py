"""A line told to a Claude session on a node (the bell's Resume, Send to
Claude): Enter only once the line is seen on the screen, and seen for long
enough that an idle session's slow redraw is not taken for a dialog (B774)."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agentpkg  # noqa: E402

agent = agentpkg.load("builderbot_agent_tell")
LINE = ("BuilderBot is back after an update. Pick up where you stopped: read the note you "
        "left on where you were and what was next, and carry on.")


class Job:
    def __init__(self):
        self.said = []

    def say(self, s):
        self.said.append(s)


class Pane:
    """A tmux whose screen shows the typed line only after `late` looks."""
    def __init__(self, late):
        self.late, self.looks, self.typed, self.keys = late, 0, False, []

    def __call__(self, argv):
        if argv[0] == "capture-pane":
            if self.typed:
                self.looks += 1
            return ("> " + LINE) if self.typed and self.looks > self.late else "> "
        if argv[0] == "send-keys":
            self.keys.append(argv[-1])
            if "-l" in argv:
                self.typed = True
            return ""
        return ""


def tell(pane):
    me = mock.Mock()
    me.sessions_now = lambda: [{"name": "claude-hello"}]
    me._tmux = pane
    with mock.patch("time.sleep", lambda _s: None):
        return agent.SessionsMixin.tell(me, Job(), {"session": "claude-hello", "text": LINE})


class Tell(unittest.TestCase):
    def test_a_slow_redraw_is_still_sent(self):
        # Seen on the fifth look, a second and more after it was typed: two
        # looks gave up and left it in the box.
        pane = Pane(late=4)
        self.assertEqual(tell(pane), ("succeeded", 0))
        self.assertEqual(pane.keys[-1], "Enter")

    def test_a_line_that_never_shows_is_left_unsent(self):
        # A dialog has the keyboard: the line never echoes, and Enter never goes.
        pane = Pane(late=10_000)
        self.assertEqual(tell(pane), ("failed", 3))
        self.assertNotIn("Enter", pane.keys)


if __name__ == "__main__":
    unittest.main()
