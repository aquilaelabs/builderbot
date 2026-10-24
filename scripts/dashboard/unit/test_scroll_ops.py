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
        # -t; an -X one is not first cancelled out of copy mode.
        for key in ("lineup", "linedown"):
            for argv in macros.scroll_ops("s", key, 1):
                self.assertIn(argv[0], ("send-keys", "copy-mode"))
                self.assertIn("-t", argv)
                self.assertLessEqual(len(argv), 12)

    def test_a_count_that_is_no_number_is_refused(self):
        lines: object = "lots"
        self.assertEqual(macros.press("s", "lineup", None, lines)[1], 400)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
