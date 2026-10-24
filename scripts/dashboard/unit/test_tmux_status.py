"""The status line every terminal wears (lib/tmux.conf): the session's own
name, without the account prefix a session on a node carries, and the room
to show it whole (B334: cut at tmux's ten characters it read u_8fb841d with
the window's 0 run into it)."""
import os
import shutil
import subprocess
import unittest
import uuid

CONF = os.path.join(os.path.dirname(__file__), "..", "..", "lib", "tmux.conf")


@unittest.skipUnless(shutil.which("tmux"), "no tmux here")
class Status(unittest.TestCase):
    def test_the_session_is_named_whole_and_without_its_account(self):
        sock = f"b334-{uuid.uuid4().hex[:8]}"
        self.addCleanup(lambda: subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True, check=False))
        name = "u_8fb841d7~shell-hello-2"
        subprocess.run(["tmux", "-L", sock, "-f", CONF, "new-session", "-d", "-s", name, "sleep 30"], check=True)
        left = subprocess.run(["tmux", "-L", sock, "display-message", "-p", "-t", name, "#{T:status-left}"],
                              capture_output=True, text=True, check=True).stdout
        length = subprocess.run(["tmux", "-L", sock, "show-options", "-gv", "status-left-length"],
                                capture_output=True, text=True, check=True).stdout.strip()
        self.assertIn("shell-hello-2", left)
        self.assertNotIn("u_8fb841d7", left)
        self.assertGreaterEqual(int(length), len(" shell-hello-2 "))


if __name__ == "__main__":
    unittest.main()
