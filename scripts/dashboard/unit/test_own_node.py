"""The controller's own machine as a node of itself (R90 step 6): minted from
a shell on a controller installed bare metal (bb nodes enroll-token --own),
an ordinary agent row that builds and runs sessions and runs no containers,
with each session in a network of its own from the first hello; there is
one such row, its session network cannot be switched off, and docker-host
cannot be given to it. The provisioner run for it keeps the job account out
of the docker group and leaves the daemon unstamped."""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.normpath(os.path.join(HERE, ".."))
LIB = os.path.normpath(os.path.join(HERE, "..", "..", "lib"))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))


def mint(state, *args):
    return subprocess.run([sys.executable, os.path.join(LIB, "nodes-verbs.py"), "enroll-token",
                           os.path.join(DASH, "nodes.py"), *args],
                          env=dict(os.environ, DASHBOARD_STATE=state), capture_output=True, text=True, timeout=60)


class OwnRow(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        sys.path.insert(0, DASH)
        import nodes
        self.nodes = nodes

    def row(self, name):
        self.nodes.configure(state=self.state)
        return next(n for n in self.nodes.node_list(all=True) if n["name"] == name)

    def test_minted_as_this_machine(self):
        t = mint(self.state, "nas", "--user", "bb", "--own")
        self.assertEqual(t.returncode, 0, t.stderr)
        self.assertTrue(t.stdout.strip().startswith("bbe_"))
        n = self.row("nas")
        self.assertEqual(n["kind"], "agent")
        self.assertEqual(n["capabilities"], ["package-build"])
        self.assertTrue(n["config"]["own"])
        self.assertTrue(n["config"]["session_net"])
        self.assertTrue(self.nodes.own_machine(n))

    def test_an_ordinary_token_is_not_this_machine(self):
        self.assertEqual(mint(self.state, "box1").returncode, 0)
        n = self.row("box1")
        self.assertFalse(self.nodes.own_machine(n))
        self.assertNotIn("own", n["config"])
        self.assertIn("docker-host", n["capabilities"])

    def test_there_is_one(self):
        self.assertEqual(mint(self.state, "nas", "--own").returncode, 0)
        again = mint(self.state, "nas2", "--own")
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("own machine is a node already", again.stderr)

    def test_its_session_network_stays_on_and_it_hosts_no_containers(self):
        mint(self.state, "nas", "--own")
        n = self.row("nas")
        # The switch went in 0.9.0 (R146): its sessions' own network is a fact.
        r = self.nodes.node_session_net("user:t", n["id"], False)
        self.assertIn("went in 0.9.0", r.get("error", ""))
        self.assertTrue(self.nodes.session_net_on(n["id"]))
        r = self.nodes.node_update("user:t", n["id"], {"capabilities": ["package-build", "docker-host"]})
        self.assertIn("runs no containers", r.get("error", ""))
        self.assertEqual(self.row("nas")["capabilities"], ["package-build"])

    def test_it_is_no_vm_host(self):
        # libvirt's group is root on the machine (R90 step 14), so VM host is
        # refused on it as docker-host is, whatever else the row says.
        mint(self.state, "nas", "--own")
        n = self.row("nas")
        r = self.nodes.node_feature("user:t", n["id"], "vmhost", "install")
        self.assertIn("controller's own machine, so it is no VM host", r.get("error", ""))


class TheDoctorSaysTheWall(unittest.TestCase):
    """bb doctor (and so the Doctor card) on a controller whose own machine is
    a node: whether the wall holds there, from that node's bb-session check,
    in red when it does not (R90 step 8)."""

    def setUp(self):
        self.state = tempfile.mkdtemp()
        sys.path.insert(0, DASH)
        import nodes
        self.nodes = nodes
        mint(self.state, "nas", "--own")
        nodes.configure(state=self.state)
        self.nid = next(n["id"] for n in nodes.node_list(all=True) if n["name"] == "nas")

    def report(self, iso):
        import json
        import time
        self.nodes._exec("UPDATE nodes SET state = 'online', reported = ?, agent = ? WHERE id = ?",
                         (json.dumps({"isolation": iso, "session": {"up": bool(iso.get("sessions"))}}),
                          json.dumps({"last_seen": int(time.time()), "version": "0.6.1"}), self.nid))

    def doctor(self):
        r = subprocess.run([sys.executable, os.path.join(LIB, "doctor-probes.py"), "node", os.path.join(DASH, "nodes.py")],
                           env=dict(os.environ, DASHBOARD_STATE=self.state), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_not_reported_yet(self):
        self.assertIn("[warn] the wall on this controller's own node (nas) is not known", self.doctor())

    def test_holding(self):
        self.report({"sessions": True, "why": ""})
        self.assertIn("[ok]   the wall holds on this controller's own node (nas)", self.doctor())

    def test_not_in_force_says_why_in_red(self):
        self.report({"sessions": False, "why": "bb-session: the wall around this machine's controller does not hold: "
                                               "the job account (bb) is in the docker group"})
        out = self.doctor()
        self.assertIn("[FAIL] the wall on this controller's own node (nas) is not in force", out)
        self.assertIn("the job account (bb) is in the docker group", out)

    def test_a_node_that_is_not_this_machine_says_nothing_of_it(self):
        mint(self.state, "box1")
        self.assertNotIn("box1", self.doctor().split("can run a session")[-1])


class TheProvisionerBesideAController(unittest.TestCase):
    def test_the_flag_keeps_docker_from_the_job_account_and_the_stamp_off(self):
        text = open(os.path.join(ROOT, "nodes", "provision-linux.sh"), encoding="utf-8").read()
        self.assertIn('--beside-controller) BESIDE_CONTROLLER=1; shift ;;', text)
        accounts = text[text.index('say "user ${USER_NAME}"'):text.index("# WHO ADMINISTERS THIS MACHINE")]
        guarded = accounts[accounts.index('if [ "$BESIDE_CONTROLLER" = 1 ]; then'):]
        self.assertLess(guarded.index("gpasswd -d"), guarded.index('usermod -aG docker "$USER_NAME"'))
        stamp = text[text.index("have_jq() {"):]
        self.assertLess(stamp.index('if [ "$BESIDE_CONTROLLER" = 1 ]; then'), stamp.index("elif stamp_daemon; then"))

    def test_the_installer_enrolls_with_it(self):
        text = open(os.path.join(ROOT, "nodes", "install-controller.sh"), encoding="utf-8").read()
        body = text[text.index("own_node() {"):]
        body = body[:body.index("\n}\n")]
        self.assertIn('nodes enroll-token "$name" --user "$JOBS_USER" --own', body)
        self.assertIn("--beside-controller", body)
        self.assertIn('ctl="http://${ip}:${PORT}"', body)


if __name__ == "__main__":
    unittest.main()
