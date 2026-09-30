"""The node agent's GPU name in its census (B391): only an nvidia-smi that
answered is a name. Drives _gpu_name against a stand-in nvidia-smi on PATH."""
import importlib.util
import os
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


if __name__ == "__main__":
    unittest.main()
