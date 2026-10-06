"""bb node busy says what holds the card's memory, by kind (B532): an
Android 37 phone filled the card while it booted, and a session could not
tell an emulator from a PyTorch job."""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("builderbot_agent_gpu", os.path.join(HERE, "..", "..", "agent", "builderbot-agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

SMI = """
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|    0   N/A  N/A            1201      G   /usr/lib/xorg/Xorg                       27MiB |
|    0   N/A  N/A            4242    C+G   ...ator/qemu/linux-x86_64/qemu-system-x86_64  7100MiB |
|    0   N/A  N/A            5150      C   /opt/sdk/pytorch/bin/python3              300MiB |
|    0   N/A  N/A            6000      C   /usr/bin/mystery                           12MiB |
+-----------------------------------------------------------------------------------------+
"""


class GpuMemKinds(unittest.TestCase):
    def setUp(self):
        self.proc = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.proc, ignore_errors=True)
        for pid, comm, cmd in (("1201", "Xorg", "/usr/lib/xorg/Xorg :0"),
                               ("4242", "qemu-system-x86", "qemu-system-x86_64 -avd builderbot-37.0"),
                               ("5150", "python3", "python3 train.py")):
            os.makedirs(os.path.join(self.proc, pid))
            Path(self.proc, pid, "comm").write_text(comm + "\n")
            Path(self.proc, pid, "cmdline").write_bytes(cmd.replace(" ", "\0").encode())

    def test_by_kind_never_by_name(self):
        got = agent._gpu_mem_kinds(proc_root=self.proc, smi=SMI)
        self.assertEqual(got, {"display": 27, "emulator": 7100, "python": 300, "other": 12})


if __name__ == "__main__":
    unittest.main()
