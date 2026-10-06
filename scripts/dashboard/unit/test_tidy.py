"""bb tidy gives back what a task left holding (the operator, 6 Oct): this
session's own emulator, its processes on the card, its build daemons, the
browsers a finished test left, and its files in /tmp; never what it runs
inside of, a running test's browsers, Claude Code's own folder, a socket,
the suite's lock, or a file something still has open."""
import importlib.util
import os
import shutil
import socket
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tidy", os.path.join(HERE, "..", "..", "lib", "tidy.py"))
tidy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tidy)
UID = os.getuid()


def proc(root, pid, comm, args, ppid=1, fds=()):
    d = Path(root, str(pid))
    (d / "fd").mkdir(parents=True)
    (d / "comm").write_text(comm + "\n")
    (d / "cmdline").write_bytes(args.replace(" ", "\0").encode())
    (d / "stat").write_text(f"{pid} ({comm}) S {ppid} 0 0\n")
    for i, f in enumerate(fds):
        os.symlink(f, d / "fd" / str(i + 3))


class Tidy(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_what_it_ends_and_what_it_spares(self):
        r = self.root
        proc(r, 10, "claude", "claude")
        proc(r, 20, "qemu-system-x86", "qemu-system-x86_64 -avd builderbot-36", fds=["/dev/nvidia0"])
        proc(r, 30, "python3", "python3 train.py", fds=["/dev/nvidiactl"])
        proc(r, 40, "java", "java org.gradle.launcher.daemon.bootstrap.GradleDaemon 9.1")
        proc(r, 50, "chrome", "/ms-playwright/chromium/chrome --headless", ppid=1)
        proc(r, 60, "node", "node test.mjs")
        proc(r, 61, "chrome", "/ms-playwright/chromium/chrome --headless", ppid=60)
        proc(r, 70, "chrome_crashpad", "chrome_crashpad_handler", ppid=1)
        proc(r, 80, "java", "java -jar app.jar")
        got = sorted(tidy.processes(root=r, uid=UID, spare=set()))
        self.assertEqual(got, [(20, "qemu-system-x86", "emulator"), (30, "python3", "gpu"),
                               (40, "java", "gradle"), (50, "chrome", "browser")])

    def test_a_crash_handler_goes_once_no_driven_browser_is_left(self):
        proc(self.root, 70, "chrome_crashpad", "chrome_crashpad_handler", ppid=1)
        self.assertEqual(tidy.processes(root=self.root, uid=UID, spare=set()), [(70, "chrome_crashpad", "browser")])

    def test_tmp_spares_claude_code_sockets_the_lock_and_what_is_open(self):
        t = Path(self.root, "tmp")
        t.mkdir()
        for name in (f"claude-{UID}", "dashboard-test.d", "old-build", "in-use"):
            (t / name).mkdir()
        (t / "junk.log").write_text("x" * 10)
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(t / "sock"))
        self.addCleanup(s.close)
        got = tidy.tmp_entries(tmp=str(t), uid=UID, held={str(t / "in-use" / "file")})
        self.assertEqual(sorted(os.path.basename(x) for x in got), ["junk.log", "old-build"])


if __name__ == "__main__":
    unittest.main()
