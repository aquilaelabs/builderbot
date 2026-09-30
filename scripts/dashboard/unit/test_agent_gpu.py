"""The node agent's GPU name in its census (B391): only an nvidia-smi that
answered is a name. Drives _gpu_name against a stand-in nvidia-smi on PATH."""
import importlib.util
import os
import shutil
import stat
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "builderbot_agent", os.path.join(HERE, "..", "..", "agent", "builderbot-agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class GpuName(unittest.TestCase):
    def setUp(self):
        self.bin = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.bin, True)
        self.path = os.environ.get("PATH", "")
        os.environ["PATH"] = self.bin + os.pathsep + self.path

    def tearDown(self):
        os.environ["PATH"] = self.path

    def stand_in(self, body):
        f = os.path.join(self.bin, "nvidia-smi")
        with open(f, "w") as h:
            h.write("#!/bin/sh\n" + body + "\n")
        os.chmod(f, os.stat(f).st_mode | stat.S_IEXEC)

    def test_a_driver_that_answers_names_the_card(self):
        self.stand_in('echo "NVIDIA GeForce RTX 3070 Ti"')
        self.assertEqual(agent._gpu_name(), "NVIDIA GeForce RTX 3070 Ti")

    def test_a_driver_that_does_not_answer_is_no_name(self):
        self.stand_in('echo "NVIDIA-SMI has failed because it couldn\'t communicate with the NVIDIA driver."; exit 9')
        self.assertEqual(agent._gpu_name(), "")

    def test_no_nvidia_smi_is_no_name(self):
        os.environ["PATH"] = self.bin
        self.assertEqual(agent._gpu_name(), "")


class GpuDriver(unittest.TestCase):
    """Where the driver stands, read from sysfs and modinfo (R102): the row
    has to tell not installed, installed and waiting for a reboot, running,
    and removed but still loaded apart, before nvidia-smi can answer."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.bin = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.bin, True)

    def card(self, bound="nouveau", vendor="0x10de", cls="0x030000"):
        d = os.path.join(self.root, "bus", "pci", "devices", "0000:04:00.0")
        os.makedirs(d, exist_ok=True)
        for name, text in (("vendor", vendor), ("class", cls), ("device", "0x2482")):
            with open(os.path.join(d, name), "w") as f:
                f.write(text + "\n")
        if bound:
            drv = os.path.join(self.root, "bus", "pci", "drivers", bound)
            os.makedirs(drv, exist_ok=True)
            os.symlink(drv, os.path.join(d, "driver"))

    def loaded(self, version):
        d = os.path.join(self.root, "module", "nvidia")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "version"), "w") as f:
            f.write(version + "\n")

    def modinfo(self, version=""):
        f = os.path.join(self.bin, "modinfo")
        with open(f, "w") as h:
            h.write("#!/bin/sh\n" + (f'echo "{version}"\n' if version
                                      else 'echo "modinfo: ERROR: Module nvidia not found." >&2; exit 1\n'))
        os.chmod(f, os.stat(f).st_mode | stat.S_IEXEC)
        return f

    def read(self, mod=""):
        return agent._gpu_driver(sys_root=self.root, modinfo=self.modinfo(mod))

    def test_no_nvidia_card_is_nothing(self):
        self.card(vendor="0x1234")
        self.assertEqual(self.read(), {})

    def test_nouveau_with_no_driver_installed(self):
        self.card("nouveau")
        self.assertEqual(self.read(), {"installed": "", "loaded": "", "bound": "nouveau"})

    def test_installed_and_waiting_for_a_reboot(self):
        self.card("nouveau")
        self.assertEqual(self.read("580.95.05"), {"installed": "580.95.05", "loaded": "", "bound": "nouveau"})

    def test_running_the_card(self):
        self.card("nvidia")
        self.loaded("580.95.05")
        self.assertEqual(self.read("580.95.05"), {"installed": "580.95.05", "loaded": "580.95.05", "bound": "nvidia"})

    def test_removed_but_still_loaded(self):
        self.card("nvidia")
        self.loaded("580.95.05")
        self.assertEqual(self.read(), {"installed": "", "loaded": "580.95.05", "bound": "nvidia"})

    def test_a_card_with_no_driver_bound(self):
        self.card(bound="")
        self.assertEqual(self.read()["bound"], "")


if __name__ == "__main__":
    unittest.main()
