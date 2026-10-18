"""The card is read on a thread of its own and the heartbeat takes what it
last read (B841): nvidia-smi takes a second or so to start, and asked three
times before every work poll it held a job queued after another for three
seconds on a node with the driver installed. The sample never waits on it,
one reading is two calls, and a driver with no card is asked again only
after GPU_GONE_S."""
import os
import subprocess
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import agentpkg  # noqa: E402
agent = agentpkg.load("builderbot_agent_gpu_cache")
gpu = agent.module("gpu")

TABLE = """|  GPU   GI   CI        PID   Type   Process name                              GPU Memory |
|    0   N/A  N/A      1234      C   python3                                       2048MiB |
|    0   N/A  N/A      5678      G   qemu-system-x86_64                            1024MiB |
"""


class GpuCache(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def run(argv, **kw):
            self.calls.append(argv)
            time.sleep(0.3)                      # nvidia-smi's own start-up
            if "--query-gpu=utilization.gpu,memory.used,memory.total" in argv:
                return subprocess.CompletedProcess(argv, 0, "40, 3072, 8192\n", "")
            return subprocess.CompletedProcess(argv, 0, TABLE, "")
        self.saved = (gpu.subprocess.run, gpu.shutil.which, dict(gpu._gpu))
        gpu.subprocess.run = run
        gpu.shutil.which = lambda name: "/usr/bin/" + name
        gpu._gpu.update(val={}, thread=None)

    def tearDown(self):
        gpu.subprocess.run, gpu.shutil.which, was = self.saved
        gpu._gpu.update(was)

    def test_the_heartbeat_never_waits_on_nvidia_smi(self):
        t0 = time.monotonic()
        first = gpu.gpu_cached()
        self.assertLess(time.monotonic() - t0, 0.1, "the first call starts the reader and returns")
        self.assertEqual(first, {})
        for _ in range(40):
            if gpu.gpu_cached():
                break
            time.sleep(0.05)
        got = gpu.gpu_cached()
        self.assertEqual(got["gpu_pct"], 40.0)
        self.assertEqual(got["gpu_mem_used_mb"], 3072)
        self.assertEqual(got["gpu_procs"], 1, "one computing, the emulator drawing is not computing")
        self.assertEqual(sum(got["gpu_mem_kinds"].values()), 3072)

    def test_one_reading_is_two_calls(self):
        gpu.gpu_read()
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
