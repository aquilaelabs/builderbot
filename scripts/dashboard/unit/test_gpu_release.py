"""bb gpu release ends this session's own processes that hold the card
(the operator, 6 Oct: a session done with the card clears its usage off it):
found by a device under /dev/nvidia among their open files."""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("gpu", os.path.join(HERE, "..", "..", "lib", "gpu.py"))
gpu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gpu)


class Holding(unittest.TestCase):
    def setUp(self):
        self.proc = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.proc, ignore_errors=True)
        for pid, comm, dev in (("90001", "qemu-system-x86", "/dev/nvidia0"),
                               ("90002", "python3", "/dev/nvidiactl"),
                               ("90003", "gradle", "/tmp/build.lock")):
            fd = Path(self.proc, pid, "fd")
            fd.mkdir(parents=True)
            Path(self.proc, pid, "comm").write_text(comm + "\n")
            os.symlink(dev, fd / "3")

    def test_what_has_the_card_open_and_nothing_else(self):
        self.assertEqual(sorted(gpu.holding(self.proc)), [(90001, "qemu-system-x86"), (90002, "python3")])


if __name__ == "__main__":
    unittest.main()
