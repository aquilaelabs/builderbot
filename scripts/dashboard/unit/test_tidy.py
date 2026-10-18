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
        # Never the real /tmp: a test run going on this machine holds its lock there.
        saved = tidy.TMP
        self.addCleanup(setattr, tidy, "TMP", saved)
        tidy.TMP = os.path.join(self.root, "no-tmp")

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

    def test_a_server_left_listening_goes_and_a_running_ones_stays(self):
        r = self.root
        Path(r, "net").mkdir()
        hdr = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        Path(r, "net", "tcp").write_text(hdr + "   0: 0100007F:10E1 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000 0 5001\n"
                                         + "   1: 0100007F:1F90 00000000:0000 01 00000000:00000000 00:00000000 00000000  1000 0 5002\n")
        Path(r, "net", "tcp6").write_text(hdr + "   0: 00000000000000000000000000000000:1F40 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000  1000 0 5003\n")
        proc(r, 10, "node", "node astro.mjs preview --port 4321", ppid=1, fds=["socket:[5001]"])
        proc(r, 11, "python3", "python3 -m http.server 8000", ppid=1, fds=["socket:[5003]"])
        proc(r, 20, "bash", "bash run.sh")
        proc(r, 21, "python3", "python3 server.py --port 9000", ppid=20, fds=["socket:[5003]"])
        proc(r, 30, "node", "node client.mjs", ppid=1, fds=["socket:[5002]"])
        proc(r, 40, "node", "node idle.mjs", ppid=1)
        proc(r, 50, "python3", "python3 /tmp/bb-suite.x1/scripts/dashboard/server.py", ppid=1, fds=["socket:[5001]"])
        proc(r, 9, "claude", "claude")
        proc(r, 60, "node", "node vite.js --port 5173", ppid=9, fds=["socket:[5003]"])
        # A background tool call's own server, still running (B840): the call's
        # shell, bb run's, then the server, under Claude Code.
        proc(r, 70, "bash", "bash -c bb run -- python3 server.py", ppid=9)
        proc(r, 71, "bash", "bash /opt/builderbot/scripts/bb run -- python3 server.py", ppid=70)
        proc(r, 72, "python3", "python3 scripts/dashboard/server.py", ppid=71, fds=["socket:[5003]"])
        got = sorted(tidy.processes(root=r, uid=UID, spare=set()))
        self.assertEqual(got, [(10, "node", "server"), (11, "python3", "server"), (60, "node", "server"),
                               (72, "python3", "server")],
                         "an orphan listening goes, adopted by pid 1 or by Claude Code, and so does a background "
                         "tool call's own server; a running suite's server, the harness's own, a connection and "
                         "an idle node stay")

    def test_no_server_is_ended_while_a_test_run_holds_its_lock(self):
        r, t = self.root, Path(self.root, "tmp", "dashboard-test.d")
        t.mkdir(parents=True)
        (t / "lock").write_text(str(os.getpid()))
        saved = tidy.TMP, tidy.PROC
        self.addCleanup(lambda: (setattr(tidy, "TMP", saved[0]), setattr(tidy, "PROC", saved[1])))
        tidy.TMP, tidy.PROC = str(Path(r, "tmp")), "/proc"
        Path(r, "net").mkdir()
        Path(r, "net", "tcp").write_text("hdr\n   0: 0100007F:10E1 00000000:0000 0A 0 0 0 1000 0 7001\n")
        proc(r, 10, "node", "node astro.mjs preview", ppid=1, fds=["socket:[7001]"])
        self.assertTrue(tidy.suite_running(tidy.TMP))
        self.assertEqual(tidy.processes(root=r, uid=UID, spare=set()), [])

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
