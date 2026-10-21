"""bb devapp probe (R248): whether an instance answers on its node's
loopback, from its own published ports only, through the node's agent and
a program the controller fixes word for word (nodes.PROBE), so a session
reads it with no root ask and a hosting-only node accepts it and nothing
else."""
import http.server
import os
import socket
import subprocess
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devactions  # noqa: E402
import devapp  # noqa: E402
import nodes  # noqa: E402


class LocalQueue:
    """The nodes module's probe_ports, with the node being this machine: the
    program run here, its lines read the way run_wait hands them back."""
    asked = []

    def probe_ports(self, principal, node_id, ports, path="/"):
        LocalQueue.asked.append((principal, node_id, list(ports), path))
        r = subprocess.run(["python3", "-c", nodes.PROBE, path] + [str(p) for p in ports],
                           capture_output=True, text=True, timeout=30, check=False)
        import json
        return {"ports": [json.loads(x) for x in r.stdout.splitlines() if x.startswith("{")]}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 (the base class's name)
        del format, args


class Probe(unittest.TestCase):
    def setUp(self):
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.closed = s.getsockname()[1]
        s.close()
        self.live = self.srv.server_port
        saved = (devapp.queue, devapp._instance_node, devactions.state_ports, devapp.pname, devapp.node_name,
                 devapp.field)
        self.addCleanup(lambda: (setattr(devapp, "queue", saved[0]), setattr(devapp, "_instance_node", saved[1]),
                                 setattr(devactions, "state_ports", saved[2]), setattr(devapp, "pname", saved[3]),
                                 setattr(devapp, "node_name", saved[4]), setattr(devapp, "field", saved[5])))
        devapp.field = lambda req, key: req.get(key)   # server.field, which configure() hands it
        devapp.queue = LocalQueue()
        devapp._instance_node = lambda project, instance: "n_draco"
        devapp.pname = lambda project, instance: f"{project}-{instance}"
        devapp.node_name = lambda nid: "hostbox"
        devactions.state_ports = lambda project, instance: [f"127.0.0.1:{self.live}->80/tcp",
                                                            f"{self.closed}->9000/tcp", "5353->5353/udp"]
        LocalQueue.asked = []

    def test_each_published_tcp_port_is_probed_on_the_loopback(self):
        out, code = devactions.probe("tl", "site", {}, "session:tl")
        self.assertEqual(code, 200, out)
        self.assertEqual(LocalQueue.asked[0][1:3], ("n_draco", [self.live, self.closed]), "the udp one left out")
        by = {p["port"]: p for p in out["ports"]}  # type: ignore[index]
        self.assertTrue(by[self.live]["open"])
        self.assertEqual(by[self.live]["http"], 200)
        self.assertFalse(by[self.closed]["open"])
        self.assertEqual((out["name"], out["node"]), ("tl-site", "hostbox"))

    def test_only_its_own_ports(self):
        out, code = devactions.probe("tl", "site", {"port": "22"}, "session:tl")
        self.assertEqual(code, 400)
        self.assertIn("port 22 is not one tl-site publishes", out["error"])
        self.assertEqual(LocalQueue.asked, [], "nothing was run")
        out, code = devactions.probe("tl", "site", {"port": str(self.live), "path": "/nope"}, "session:tl")
        self.assertEqual(code, 200, out)
        self.assertEqual(out["ports"][0]["http"], 404, "a GET of the path asked, its status said")

    def test_the_running_containers_ports_when_the_wiring_names_none(self):
        # B7: a compose file whose port comes from an env value names none in
        # its wiring, while docker has it bound; the probe asks what runs.
        saved = devactions.running_ports
        self.addCleanup(setattr, devactions, "running_ports", saved)
        devactions.state_ports = lambda project, instance: []
        devactions.running_ports = lambda project, instance: [f"{self.live}->{self.live}/tcp"]
        out, code = devactions.probe("tl", "site", {}, "session:tl")
        self.assertEqual(code, 200, out)
        self.assertEqual(LocalQueue.asked[0][2], [self.live])
        devactions.running_ports = lambda project, instance: []
        out, code = devactions.probe("tl", "site", {}, "session:tl")
        self.assertEqual(code, 400)
        self.assertIn("publishes no TCP port", out["error"])

    def test_a_hosting_node_takes_this_program_and_no_other(self):
        self.assertTrue(nodes.host_exec_ok("exec", {"argv": ["python3", "-c", nodes.PROBE, "/", "9090"]}))
        self.assertFalse(nodes.host_exec_ok("exec", {"argv": ["python3", "-c", "import os; os.system('id')"]}))
        self.assertFalse(nodes.host_exec_ok("exec", {"argv": ["curl", "http://127.0.0.1:9090"]}))

    def test_a_hosting_node_takes_a_containers_start_on_boot_and_no_other_update(self):
        # B139: refused, the choice never reached it, asked again at every read.
        self.assertTrue(nodes.host_exec_ok("exec", {"argv": ["docker", "update", "--restart", "unless-stopped", "app-1"]}))
        self.assertTrue(nodes.host_exec_ok("exec", {"argv": ["docker", "update", "--restart", "no", "app-1", "db-1"]}))
        self.assertFalse(nodes.host_exec_ok("exec", {"argv": ["docker", "update", "--restart", "always", "app-1"]}))
        self.assertFalse(nodes.host_exec_ok("exec", {"argv": ["docker", "update", "--memory", "1g", "app-1"]}))
        self.assertFalse(nodes.host_exec_ok("exec", {"argv": ["docker", "update", "--restart", "no"]}))
        self.assertFalse(nodes.host_exec_ok("exec", {"argv": ["docker", "rm", "-f", "app-1"]}))

    def test_host_ports_reads_both_shapes(self):
        self.assertEqual(devactions.host_ports(["127.0.0.1:9090->80/tcp", "9787->9787/tcp", "53->53/udp",
                                               "9090->81/tcp"]), [9090, 9787])


if __name__ == "__main__":
    unittest.main()
