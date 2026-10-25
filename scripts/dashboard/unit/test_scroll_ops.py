"""macros.scroll_ops: a finger's drag on a shell's terminal scrolls tmux's
history by lines (R133 step 11), in the argv a node's agent already runs
(tmux_ops: send-keys or copy-mode, with -t), bounded however many the page
asks for."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import macros  # noqa: E402


class ScrollOps(unittest.TestCase):
    def test_up_enters_copy_mode_that_leaves_at_the_bottom(self):
        ops = macros.scroll_ops("shell-a", "lineup", 3)
        self.assertEqual(ops[0], ["copy-mode", "-e", "-t", "shell-a"])
        self.assertEqual(ops[1], ["send-keys", "-t", "shell-a", "-X", "-N", "3", "scroll-up"])

    def test_down_scrolls_only(self):
        self.assertEqual(macros.scroll_ops("s", "linedown", 2),
                         [["send-keys", "-t", "s", "-X", "-N", "2", "scroll-down"]])

    def test_lines_are_bounded(self):
        self.assertEqual(macros.scroll_ops("s", "linedown", 5000)[0][5], "60")
        self.assertEqual(macros.scroll_ops("s", "linedown", -4)[0][5], "1")

    def test_every_op_is_one_a_node_runs(self):
        # The agent runs an argv that starts send-keys or copy-mode and names
        # -t; an -X one is not first canceled out of copy mode.
        for key in ("lineup", "linedown"):
            for argv in macros.scroll_ops("s", key, 1):
                self.assertIn(argv[0], ("send-keys", "copy-mode"))
                self.assertIn("-t", argv)
                self.assertLessEqual(len(argv), 12)

    def test_a_count_that_is_no_number_is_refused(self):
        lines: object = "lots"
        self.assertEqual(macros.press("s", "lineup", None, lines)[1], 400)  # type: ignore[arg-type]


class Leave(unittest.TestCase):
    """The page leaves copy mode before it types into a pane it scrolled
    back (B254): on a node an empty send-keys, which the agent leaves copy
    mode for; here only a pane that is in a mode is canceled out of it."""
    def setUp(self):
        self.ran, self.mode = [], "1"
        self.was = (macros.run, macros.tmux_sessions, macros.session_tmux, macros._answer)
        macros.run = lambda argv, timeout=10: (self.ran.append(argv) or
                                               {"out": self.mode if "display-message" in argv else ""})
        macros.tmux_sessions = lambda: [{"name": "s"}]
        macros.session_tmux = lambda nid, ops: ops
        macros._answer = lambda x: (x, 200)

    def tearDown(self):
        macros.run, macros.tmux_sessions, macros.session_tmux, macros._answer = self.was

    def test_on_a_node_an_empty_send_keys(self):
        ops, _ = macros.press("s", "leave", {"node_id": "n_1", "node_name": "u_1~shell-a"})
        self.assertEqual(ops, [{"session": "u_1~shell-a", "argv": ["send-keys", "-t", "u_1~shell-a"]}])

    def test_here_canceled_only_in_a_mode(self):
        macros.press("s", "leave", None)
        self.assertIn(["tmux", "send-keys", "-t", "s", "-X", "cancel"], self.ran)
        self.ran, self.mode = [], "0"
        macros.press("s", "leave", None)
        self.assertFalse(any("cancel" in a for a in self.ran))


if __name__ == "__main__":
    unittest.main()
