"""The NVIDIA container toolkit (R102): the agent's census of it, the row
the Toolchains tab draws from that census, what a job is refused for first,
and the gate a compose file that reserves the GPU meets before it starts.
test_sandbox_gpu.py runs the helper's own install and removal."""
import importlib.util
import os
import shutil
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import devapp  # noqa: E402
import toolchains  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "builderbot_agent", os.path.join(HERE, "..", "..", "agent", "builderbot-agent.py"))
assert spec is not None and spec.loader is not None
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

CARD = "NVIDIA Corporation GA104 [GeForce RTX 3070 Ti] [10de:2482] (rev a1)"
LOADED = {"installed": "610.57.04", "loaded": "610.57.04", "bound": "nvidia"}
ABSENT = {"installed": "", "loaded": "", "bound": "nouveau"}


def node(toolkit=None, driver=None, docker="28.1", card=CARD, sandbox=True, lock=False):
    rep = {"gpu_card": card, "sandbox": sandbox, "docker": docker,
           "gpu_driver": LOADED if driver is None else driver}
    if toolkit is not None:
        rep["gpu_container"] = toolkit
    return {"id": "n_x", "name": "x", "reported": rep, "config": {"lock": lock}}


class Census(unittest.TestCase):
    def setUp(self):
        self.bin = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.bin, True)
        self.path = os.environ.get("PATH", "")
        os.environ["PATH"] = self.bin
        self.addCleanup(os.environ.__setitem__, "PATH", self.path)

    def tool(self, name, body):
        f = os.path.join(self.bin, name)
        with open(f, "w") as h:
            h.write("#!/bin/sh\n" + body + "\n")
        os.chmod(f, os.stat(f).st_mode | stat.S_IEXEC)

    def docker(self, runtimes='{"io.containerd.runc.v2":{},"runc":{}}'):
        self.tool("docker", f"echo '{runtimes}'")

    def test_no_card_or_no_docker_is_nothing(self):
        self.assertEqual(agent._gpu_container(card=CARD), {})
        self.docker()
        self.assertEqual(agent._gpu_container(card=""), {})

    def test_not_installed_and_no_source_on_the_machine(self):
        self.docker()
        self.tool("dpkg-query", "exit 1")
        self.tool("apt-cache", "printf 'nvidia-container-toolkit:\\n  Installed: (none)\\n  Candidate: (none)\\n'")
        self.assertEqual(agent._gpu_container(card=CARD), {"installed": "", "candidate": "", "runtime": False})

    def test_installed_with_the_runtime_and_a_newer_one_on_offer(self):
        self.docker('{"nvidia":{"path":"nvidia-container-runtime"},"runc":{}}')
        self.tool("dpkg-query", "printf '1.17.8-1 ii \\n'")
        self.tool("apt-cache", "printf 'nvidia-container-toolkit:\\n  Installed: 1.17.8-1\\n  Candidate: 1.18.0-1\\n'")
        self.assertEqual(agent._gpu_container(card=CARD),
                         {"installed": "1.17.8-1", "candidate": "1.18.0-1", "runtime": True})

    def test_removed_but_not_purged_is_not_installed(self):
        self.docker()
        self.tool("dpkg-query", "printf '1.17.8-1 rc \\n'")
        self.assertEqual(agent._gpu_container(card=CARD)["installed"], "")

    def test_installed_without_dpkg_is_read_from_its_own_tool(self):
        self.docker('{"nvidia":{}}')
        self.tool("nvidia-ctk", "echo 'NVIDIA Container Toolkit CLI version 1.17.8'; echo 'commit: abc'")
        got = agent._gpu_container(card=CARD)
        self.assertEqual((got["installed"], got["runtime"]), ("1.17.8", True))


class Row(unittest.TestCase):
    def row(self, *a, **kw):
        return toolchains.container_row(node(*a, **kw))

    def test_no_card_or_no_docker_is_no_row(self):
        self.assertIsNone(self.row({}, card=""))
        self.assertIsNone(self.row({}, docker=""))

    def test_each_state(self):
        self.assertEqual(self.row()["state"], "unknown")
        self.assertEqual(self.row({"installed": "", "candidate": "", "runtime": False})["state"], "absent")
        self.assertEqual(self.row({"installed": "1.17.8-1", "runtime": False})["state"], "unconfigured")
        self.assertEqual(self.row({"installed": "1.17.8-1", "runtime": True})["state"], "ready")

    def test_an_update_is_a_candidate_that_is_not_what_is_installed(self):
        self.assertEqual(self.row({"installed": "1.17.8-1", "candidate": "1.18.0-1", "runtime": True})["newer"], "1.18.0-1")
        self.assertEqual(self.row({"installed": "1.17.8-1", "candidate": "1.17.8-1", "runtime": True})["newer"], "")
        self.assertEqual(self.row({"installed": "", "candidate": "1.18.0-1", "runtime": False})["newer"], "")

    def test_it_knows_where_the_driver_stands(self):
        got = self.row({"installed": "", "runtime": False}, driver=ABSENT)
        self.assertEqual((got["driver"], got["driver_loaded"]), (False, False))
        got = self.row({"installed": "", "runtime": False}, driver={**ABSENT, "installed": "610.57.04"})
        self.assertEqual((got["driver"], got["driver_loaded"]), (True, False))
        got = self.row({"installed": "", "runtime": False})
        self.assertEqual((got["driver"], got["driver_loaded"]), (True, True))


class JobName(unittest.TestCase):
    OFF = {"installed": "", "candidate": "", "runtime": False}

    def ask(self, n, action="install", also=()):
        return toolchains._machine_name(n, action, toolchains.TOOLKIT, [toolchains.TOOLKIT, *also])

    def test_with_the_driver_on_the_machine(self):
        self.assertEqual(self.ask(node(self.OFF)), (toolchains.TOOLKIT, ""))

    def test_without_the_driver_it_is_refused_unless_the_driver_is_in_the_batch(self):
        name, why = self.ask(node(self.OFF, driver=ABSENT))
        self.assertEqual(name, "")
        self.assertIn("driver", why)
        self.assertEqual(self.ask(node(self.OFF, driver=ABSENT), also=[toolchains.DRIVER]), (toolchains.TOOLKIT, ""))

    def test_removal_does_not_ask_for_the_driver(self):
        self.assertEqual(self.ask(node({"installed": "1.17.8-1", "runtime": True}, driver=ABSENT), "remove")[1], "")

    def test_refusals(self):
        for n in (node(self.OFF, sandbox=False), node(self.OFF, lock=True), node(), node(self.OFF, docker=""),
                  node(self.OFF, card="")):
            name, why = self.ask(n)
            self.assertEqual(name, "")
            self.assertTrue(why)


class Error(unittest.TestCase):
    """Each of the machine's two rows reads its own part of one job's log."""
    LOG = ("== bb-sandbox gpu-driver install \n== installing the NVIDIA driver\nE: Unable to locate package nvidia-driver-999\n"
           "!! apt could not install it\n"
           "== bb-sandbox gpu-container install \n== adding NVIDIA's package source for the container toolkit\n"
           "!! could not fetch the package source's signing key from https://nvidia.github.io/libnvidia-container\n")

    def why(self, name, log=None):
        class Nodes:
            @staticmethod
            def job_tail(job_id, n=0):
                return self.LOG if log is None else log
        was, toolchains.nodes = toolchains.nodes, Nodes
        toolchains._node_errors_seen.clear()
        try:
            return toolchains._node_errors("j_1", [name], "install")[name]
        finally:
            toolchains.nodes = was

    def test_the_toolkits_reason_is_its_own(self):
        self.assertIn("signing key", self.why(toolchains.TOOLKIT))
        self.assertNotIn("Unable to locate", self.why(toolchains.TOOLKIT))

    def test_the_drivers_reason_is_its_own(self):
        self.assertIn("Unable to locate", self.why(toolchains.DRIVER))
        self.assertNotIn("signing key", self.why(toolchains.DRIVER))

    def test_the_agents_refusal_goes_to_the_row_it_names(self):
        log = "refused: nvidia-container-toolkit is this machine's own, and this node was not provisioned as a BuilderBot sandbox\n"
        self.assertIn("not provisioned", self.why(toolchains.TOOLKIT, log))
        self.assertNotIn("not provisioned", self.why(toolchains.DRIVER, log))


class Why(unittest.TestCase):
    """Why a container there cannot be given the card, or ""."""
    ON = {"installed": "1.17.8-1", "candidate": "1.17.8-1", "runtime": True}

    def test_everything_in_place(self):
        self.assertEqual(toolchains.container_why(node(self.ON)), "")

    def test_each_missing_piece_is_named(self):
        self.assertIn("no node", toolchains.container_why(None))
        self.assertIn("no NVIDIA card", toolchains.container_why(node(self.ON, card="")))
        self.assertIn("no Docker", toolchains.container_why(node(self.ON, docker="")))
        self.assertIn("update it", toolchains.container_why(node()))
        self.assertIn("Toolchains tab", toolchains.container_why(node({"installed": "", "runtime": False})))
        self.assertIn("runtime", toolchains.container_why(node({"installed": "1.17.8-1", "runtime": False})))
        self.assertIn("driver", toolchains.container_why(node(self.ON, driver={**ABSENT, "installed": "610.57.04"})))


class ComposeAsks(unittest.TestCase):
    """Which services of a compose file reserve the GPU, in each spelling."""

    def asks(self, **services):
        return devapp.gpu_asks({"services": services})

    def test_a_device_reservation(self):
        dev = {"deploy": {"resources": {"reservations": {"devices": [
            {"driver": "nvidia", "count": 1, "capabilities": ["gpu"]}]}}}}
        self.assertEqual(self.asks(web={"image": "nginx"}, train=dev), ["train"])

    def test_the_capability_with_no_driver_named(self):
        dev = {"deploy": {"resources": {"reservations": {"devices": [{"capabilities": ["gpu"]}]}}}}
        self.assertEqual(self.asks(train=dev), ["train"])

    def test_the_runtime_and_gpus_spellings(self):
        self.assertEqual(self.asks(a={"runtime": "nvidia"}, b={"gpus": "all"}, c={"runtime": "runc"}), ["a", "b"])

    def test_another_vendors_device_and_odd_shapes_are_not_it(self):
        other = {"deploy": {"resources": {"reservations": {"devices": [{"driver": "amd", "capabilities": ["gpu"]}]}}}}
        self.assertEqual(self.asks(a=other, b={"deploy": None}, c={"deploy": {"resources": {"reservations": {"devices": "x"}}}},
                                   d={"deploy": {"resources": {"limits": {"cpus": "2"}}}}), [])
        self.assertEqual(devapp.gpu_asks(None), [])


class ComposeGate(unittest.TestCase):
    CFG = {"services": {"train": {"runtime": "nvidia"}, "web": {"image": "nginx"}}}

    def setUp(self):
        self.was = (devapp.gpu_why, devapp.project_node, devapp.node_for)
        self.addCleanup(lambda: setattr(devapp, "gpu_why", self.was[0]))
        self.addCleanup(lambda: setattr(devapp, "project_node", self.was[1]))
        self.asked = []
        devapp.project_node = lambda p: "n_x"
        self.read, devapp._read_rec = devapp._read_rec, lambda p, i: {}
        self.addCleanup(lambda: setattr(devapp, "_read_rec", self.read))

    def why(self, text):
        def f(project, nid):
            self.asked.append((project, nid))
            return text
        devapp.gpu_why = f

    def test_a_compose_that_does_not_ask_is_not_held_and_nothing_is_asked(self):
        self.why("x has no NVIDIA container toolkit")
        self.assertEqual(devapp.gpu_gate("p", "main", {"services": {"web": {"image": "nginx"}}}), "")
        self.assertEqual(self.asked, [])

    def test_one_that_asks_where_the_card_can_be_given(self):
        self.why("")
        self.assertEqual(devapp.gpu_gate("p", "main", self.CFG), "")
        self.assertEqual(self.asked, [("p", "n_x")])

    def test_one_that_asks_where_it_cannot_names_the_service_and_the_reason(self):
        self.why("x has no NVIDIA container toolkit")
        got = devapp.gpu_gate("p", "main", self.CFG)
        self.assertIn("train reserves the NVIDIA GPU", got)
        self.assertIn("no NVIDIA container toolkit", got)

    def test_with_nobody_to_ask_it_is_not_held(self):
        devapp.gpu_why = None
        self.assertEqual(devapp.gpu_gate("p", "main", self.CFG), "")


if __name__ == "__main__":
    unittest.main()
