"""The wall a session meets on the controller's own machine (R90 step 7):
bb-session reads the folders /etc/bb-session.wall names and covers each in
the view, and refuses to start a session (and `check` says why, which the
node's row then says) when the machine carries a controller and no wall,
when a folder it names is the session's or the job account's to read, when
either account is in the docker group or the controller's, when sessions
here do not run in a network of their own, or when the controller's
loopback ports are not refused to them. Every cover is checked inside the
view before the drop."""
import importlib.machinery
import importlib.util
import os
import pwd
import stat
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


session = load("bb_session_wall", os.path.join(ROOT, "nodes", "bb-session"))
ME = pwd.getpwuid(os.getuid()).pw_name
NET = {"SESSION_NET": "on", "SESSION_NET_CIDR": "10.231.0.0/16"}


def wall_file(d, text):
    p = os.path.join(d, "bb-session.wall")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


class TheFile(unittest.TestCase):
    def test_no_controller_no_wall(self):
        with mock.patch.dict(os.environ, {"BB_SESSION_WALL": "/nonexistent/wall", "BB_SESSION_MARKS": "/nonexistent/x"}):
            self.assertEqual(session.wall_conf(), "")

    def test_a_controller_without_a_wall_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"BB_SESSION_WALL": f"{d}/none", "BB_SESSION_MARKS": d}):
                with self.assertRaises(session.Refused) as e:
                    session.wall_conf()
                self.assertIn("no wall", str(e.exception))

    def test_read_as_written(self):
        with tempfile.TemporaryDirectory() as d:
            p = wall_file(d, "# a comment\nACCOUNT=builderbot\nJOBS_USER=bb\n"
                             "COVER=/var/lib/builderbot-controller:/etc/builderbot-controller/:/x/../y:rel\n"
                             "PORTS=7681,7682\n")
            with mock.patch.dict(os.environ, {"BB_SESSION_WALL": p}):
                w = session.wall_conf()
        self.assertEqual(w["ACCOUNT"], "builderbot")
        self.assertEqual(w["JOBS_USER"], "bb")
        self.assertEqual(w["COVER"], ["/var/lib/builderbot-controller", "/etc/builderbot-controller"])
        self.assertEqual(w["PORTS"], [7681, 7682])

    def test_one_naming_nothing_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = wall_file(d, "ACCOUNT=builderbot\n")
            with mock.patch.dict(os.environ, {"BB_SESSION_WALL": p}):
                with self.assertRaises(session.Refused):
                    session.wall_conf()


class Faults(unittest.TestCase):
    # The session account is this test's own; the job account one that is
    # in no docker group; the controller's, one more.
    def wall(self, cover, jobs="daemon"):
        return {"ACCOUNT": "nobody", "JOBS_USER": jobs, "COVER": cover, "PORTS": [7681, 7682]}

    def c(self, **kw):
        return {"SESSION_USER": ME, **NET, **kw}

    def test_a_wall_that_holds_says_nothing(self):
        self.assertEqual(session.wall_faults(self.c(), self.wall(["/root", "/nonexistent/x"]), guard=True), [])

    def test_a_group_that_is_root_by_another_door(self):
        # libvirt's, disk's, lxd's and incus-admin's are root on the machine
        # as docker's is (R90 step 14): the session account in one is a fault.
        import collections
        import grp
        G = collections.namedtuple("G", "gr_gid")
        real = grp.getgrnam
        def fake(name):
            if name == "libvirt":
                return G(os.getgid())
            return real(name)
        with mock.patch.object(grp, "getgrnam", side_effect=fake):
            got = session.wall_faults(self.c(), self.wall(["/root"]), guard=True)
        self.assertIn(f"the session account ({ME}) is in the libvirt group", got)

    def test_an_account_user_is_held_to_the_same_groups(self):
        # Each account's own user (R125, bbu-) runs that account's sessions,
        # so a banned group of its is a fault as the session account's is.
        import collections
        import grp
        G = collections.namedtuple("G", "gr_gid")
        real_gr, real_ids = grp.getgrnam, session._ids
        P = collections.namedtuple("P", "pw_name")
        with mock.patch.object(grp, "getgrnam", side_effect=lambda n: G(os.getgid()) if n == "disk" else real_gr(n)), \
             mock.patch.object(session.pwd, "getpwall", return_value=[P("bbu-0a1b2c3d")]), \
             mock.patch.object(session, "_ids", side_effect=lambda n: real_ids(ME) if n.startswith("bbu-") else real_ids(n)):
            got = session.wall_faults(self.c(SESSION_USER=""), self.wall(["/root"]), guard=True)
        self.assertIn("the account user bbu-0a1b2c3d (bbu-0a1b2c3d) is in the disk group", got)

    def test_no_wall_says_nothing(self):
        self.assertEqual(session.wall_faults(self.c(), "", guard=False), [])

    def test_a_folder_the_session_owns(self):
        with tempfile.TemporaryDirectory() as d:
            os.chmod(d, 0o700)
            got = session.wall_faults(self.c(), self.wall([d]), guard=True)
        self.assertEqual(got, [f"{d} is the session account's ({ME})"])

    def test_a_folder_anybody_enters(self):
        got = session.wall_faults(self.c(), self.wall(["/usr"]), guard=True)
        self.assertEqual(got, ["/usr lets anybody in (mode 755)"])

    def test_a_folder_the_group_lets_in(self):
        mine = os.getgid()
        real = os.stat

        def fake(p, *a, **k):
            if p == "/ctl/state":
                return os.stat_result((stat.S_IFDIR | 0o750, 0, 0, 1, 0, mine, 0, 0, 0, 0))
            return real(p, *a, **k)
        with mock.patch.object(session.os, "stat", fake):
            got = session.wall_faults(self.c(), self.wall(["/ctl/state"]), guard=True)
        self.assertEqual(got, [f"/ctl/state lets the session account ({ME}) in through its group"])

    def test_an_account_in_the_docker_group(self):
        try:
            import grp
            members = grp.getgrnam("docker").gr_mem
        except KeyError:
            self.skipTest("no docker group on this machine")
        if not members:
            self.skipTest("nobody is in the docker group here")
        got = session.wall_faults(self.c(), self.wall(["/root"], jobs=members[0]), guard=True)
        self.assertIn(f"the job account ({members[0]}) is in the docker group", got)

    def test_sessions_on_the_nodes_own_network(self):
        got = session.wall_faults({"SESSION_USER": ME}, self.wall(["/root"]), guard=True)
        self.assertEqual(len(got), 1)
        self.assertIn("network of their own", got[0])

    def test_the_loopback_ports_unguarded(self):
        got = session.wall_faults(self.c(), self.wall(["/root"]), guard=False)
        self.assertEqual(len(got), 1)
        self.assertIn("7681, 7682", got[0])
        self.assertIn("builderbot_wall", got[0])

    def test_every_fault_is_said_at_once(self):
        got = session.wall_faults({"SESSION_USER": ME}, self.wall(["/usr"]), guard=False)
        self.assertEqual(len(got), 3)

    def test_check_and_enter_both_ask(self):
        src = open(os.path.join(ROOT, "nodes", "bb-session"), encoding="utf-8").read()
        check = src[src.index("def check(c):"):src.index("def check_net(c):")]
        self.assertIn("wall_hold(c)", check)
        enter = src[src.index("def enter(c, a, command):"):src.index("def check(c):")]
        self.assertLess(enter.index("wall = wall_hold(c)"), enter.index("steps = plan(c, a, uid, wall)"))
        self.assertLess(enter.index("apply(steps, uid, gid)"), enter.index("wall_covered(wall)"))
        self.assertLess(enter.index("wall_covered(wall)"), enter.index("_drop(name, uid, gid)"))


class TheView(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.d, True))
        ws, home = f"{self.d}/ws", f"{self.d}/home"
        self.account = "u_0000abcd"
        for p in (f"{ws}/proj", f"{home}/users/{self.account}", f"{self.d}/ctl/config", f"{self.d}/ctl-etc"):
            os.makedirs(p)
        open(f"{self.d}/agent.sock", "w").close()
        self.c = {"SESSION_USER": ME, "WORKSPACE": ws, "HOME_ROOT": home, "DATA_STORE": "", "ARTIFACTS_STORE": "",
                  "RUNNER_DIR": "/nonexistent", "HIDE": "", "STATE_DIR": "", "TOOLCHAINS_STORE": ""}
        self.a = {"project": "proj", "account": self.account, "home": f"{home}/users/{self.account}",
                  "cwd": f"{ws}/proj"}

    def test_every_folder_the_wall_names_is_covered(self):
        w = {"ACCOUNT": "nobody", "JOBS_USER": "daemon", "PORTS": [],
             "COVER": [f"{self.d}/ctl", f"{self.d}/ctl-etc", f"{self.d}/agent.sock", f"{self.d}/gone"]}
        steps = session.plan(self.c, self.a, None, w)
        self.assertIn(("hide", f"{self.d}/ctl"), steps)
        self.assertIn(("hide", f"{self.d}/ctl-etc"), steps)
        self.assertIn(("hidefile", f"{self.d}/agent.sock"), steps)
        self.assertFalse(any(s[-1] == f"{self.d}/gone" for s in steps))
        # Before the view is let go of, and after what it covers is bound.
        self.assertLess(steps.index(("hide", f"{self.d}/ctl")), steps.index(("detach", session.STAGE)))

    def test_no_wall_no_covers(self):
        with mock.patch.dict(os.environ, {"BB_SESSION_WALL": "/nonexistent/wall", "BB_SESSION_MARKS": "/nonexistent/x"}):
            steps = session.plan(self.c, self.a, None)
        self.assertFalse(any(s[-1].startswith(f"{self.d}/ctl") for s in steps))

    def test_a_cover_that_did_not_hold_stops_the_session(self):
        w = {"COVER": [f"{self.d}/ctl", f"{self.d}/agent.sock", f"{self.d}/gone"]}
        with self.assertRaises(session.Refused) as e:
            session.wall_covered(w)
        self.assertIn(f"{self.d}/ctl is still there", str(e.exception))
        os.rmdir(f"{self.d}/ctl/config")
        with self.assertRaises(session.Refused) as e:
            session.wall_covered(w)
        self.assertIn("agent.sock is still there", str(e.exception))
        session.wall_covered({"COVER": [f"{self.d}/ctl", "/dev/null"]})


class NoFallback(unittest.TestCase):
    """bb-tty runs a session without a view on a node that cannot build one
    (a Mac, a guest); on the controller's own machine it never does: a
    failing check there is a refusal, in bb-session's words (R90)."""

    def run_in_view(self, marks):
        src = open(os.path.join(ROOT, "scripts", "dashboard", "bb-tty"), encoding="utf-8").read()
        fn = src[src.index("\nin_view() {") + 1:]
        fn = fn[:fn.index("\n}\n") + 3]
        script = ("set -euo pipefail\n"
                  "on_node() { return 0; }\n"
                  "isolating() { return 1; }\n"
                  "sudo() { echo 'bb-session: the wall around this machine'\"'\"'s controller does not hold: "
                  "the job account (bb) is in the docker group' >&2; return 2; }\n"
                  "bad() { for l in \"$@\"; do echo \"$l\"; done; exit 1; }\n"
                  "SESSION_BIN=/usr/local/sbin/bb-session\n"
                  f"CONTROLLER_MARKS=({' '.join(marks)})\n"
                  + fn + 'in_view proj /workspace/proj claude; echo "ran: ${RUN[*]}"\n')
        import subprocess
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, check=False)

    def test_a_node_without_views_runs_the_session_as_it_always_has(self):
        r = self.run_in_view(["/nonexistent/a", "/nonexistent/b"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ran: claude", r.stdout)

    def test_the_controllers_own_machine_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_in_view(["/nonexistent/a", d])
        self.assertEqual(r.returncode, 1)
        self.assertIn("This machine is the controller's own", r.stdout)
        self.assertIn("the job account (bb) is in the docker group", r.stdout)
        self.assertNotIn("ran:", r.stdout)

    def test_the_marks_are_bb_sessions(self):
        src = open(os.path.join(ROOT, "scripts", "dashboard", "bb-tty"), encoding="utf-8").read()
        line = next(ln for ln in src.splitlines() if ln.startswith("CONTROLLER_MARKS=("))
        for m in line[len("CONTROLLER_MARKS=("):-1].split():
            self.assertTrue(m == session.WALL or m in session.CONTROLLER_MARKS, m)


if __name__ == "__main__":
    unittest.main()
