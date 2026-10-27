"""The keys the dashboard's terminal sends down its socket (lib/tmux-keys.conf,
page-term.js TERM_LEAVE, TERM_LINE_UP, TERM_LINE_DOWN), through a real tmux
client: a line of history up enters copy mode and a line down ends it at
the bottom, a drag's lines arriving at once all counted (assume-paste-time);
the leave key, ahead of what is typed, takes a pane out of copy mode so the
first letter reaches the program (B254); and on a pane not in a mode none of
them is ever typed."""
import os
import pty
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(HERE, "..", "..", "lib", "tmux-keys.conf")
BBTTY = os.path.join(HERE, "..", "bb-tty")
PAGE = os.path.join(HERE, "..", "page-term.js")


@unittest.skipUnless(shutil.which("tmux"), "no tmux here")
class Leave(unittest.TestCase):
    def setUp(self):
        self.sock = os.path.join(tempfile.mkdtemp(), "s")
        self.tm("-f", CONF, "new-session", "-d", "-x", "80", "-y", "10", "-s", "t", "seq 1 100; cat")
        self.addCleanup(self.tm, "kill-server")
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.environ["TERM"] = "xterm-256color"
            os.execvp("tmux", ["tmux", "-S", self.sock, "attach", "-t", "t"])
        self.addCleanup(lambda: os.close(self.fd))
        self.wait(lambda: self.tm("list-clients", "-F", "x").strip())

    def tm(self, *a):
        return subprocess.run(["tmux", "-S", self.sock, *a], capture_output=True, text=True, timeout=10).stdout

    def wait(self, ok, s=5):
        end = time.time() + s
        while time.time() < end and not ok():
            time.sleep(0.05)
        return ok()

    def mode(self):
        return self.tm("display-message", "-p", "-t", "t", "#{pane_in_mode}").strip()

    def screen(self):
        return [ln for ln in self.tm("capture-pane", "-p", "-t", "t").split("\n") if ln]

    def test_the_page_sends_the_keys_tmux_keys_conf_binds(self):
        page = open(PAGE, encoding="utf-8").read()
        for name, n in (("TERM_LEAVE", "9001"), ("TERM_LINE_UP", "9002"), ("TERM_LINE_DOWN", "9003")):
            self.assertIn(f'{name} = "\\x1b[{n}~"', page)
        self.assertIn('user-keys[0] "\\e[9001~"', open(CONF, encoding="utf-8").read())
        # ...and bb-tty gives it to the server before every attach.
        text = open(BBTTY, encoding="utf-8").read()
        self.assertEqual(text.count("exec tmux attach-session"), text.count("tmux_keys\n"))

    def test_in_copy_mode_it_leaves_and_what_follows_is_the_programs(self):
        self.tm("copy-mode", "-t", "t")
        self.assertEqual(self.mode(), "1")
        os.write(self.fd, b"\x1b[9001~hello\r")
        self.assertTrue(self.wait(lambda: "hello" in self.screen()), self.screen())
        self.assertEqual(self.mode(), "0")

    def test_out_of_copy_mode_none_is_ever_typed(self):
        os.write(self.fd, b"\x1b[9001~\x1b[9003~\x1b[9003~world\r")
        self.assertTrue(self.wait(lambda: "world" in self.screen()), self.screen())
        self.assertNotIn("900", "".join(self.screen()))

    def pos(self):
        return self.tm("display-message", "-p", "-t", "t", "#{pane_in_mode} #{scroll_position}").strip()

    def test_a_drags_lines_at_once_all_count(self):
        self.wait(lambda: "100" in self.screen())
        os.write(self.fd, b"\x1b[9002~" * 9)
        self.assertTrue(self.wait(lambda: self.pos() == "1 9"), self.pos())
        os.write(self.fd, b"\x1b[9003~" * 4)
        self.assertTrue(self.wait(lambda: self.pos() == "1 5"), self.pos())
        # Past the bottom: copy mode ends by itself, and the rest are nothing.
        os.write(self.fd, b"\x1b[9003~" * 12 + b"\x1b[9001~hi\r")
        self.assertTrue(self.wait(lambda: "hi" in self.screen()), self.screen())
        self.assertEqual(self.mode(), "0")
        self.assertNotIn("900", "".join(self.screen()))


if __name__ == "__main__":
    unittest.main()
