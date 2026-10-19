"""The agent's root command runner (_sh) posts as the command runs: the
step first and its output as it comes. It ran the command to the end with
nothing posted, so the NVIDIA rows on the Toolchains page never said
installing and the job sat at assigned for as long as apt took (30 Sep)."""
import os
import threading
import time
import unittest
import agentpkg  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
agent = agentpkg.load("builderbot_agent")


class FakeJob:
    """What _sh uses of a Job: say, flush, pending, and the cancel hooks."""

    def __init__(self):
        self.pending, self.posts, self.proc, self.canceled = [], [], None, False
        self.lock = threading.Lock()

    def say(self, text):
        with self.lock:
            self.pending.append(text)

    def flush(self, keepalive=False):
        with self.lock:
            self.posts.append((time.monotonic(), "".join(self.pending)))
            self.pending = []
        return True

    @staticmethod
    def _kill(p):
        agent.Job._kill(p)


class Streamed(unittest.TestCase):
    def run_sh(self, argv, timeout=30):
        job = FakeJob()
        t0 = time.monotonic()
        rc = agent.Agent._sh(None, job, argv, timeout=timeout)
        return rc, job, t0, time.monotonic()

    def test_the_command_and_its_first_output_are_posted_before_it_ends(self):
        rc, job, t0, t1 = self.run_sh(["sh", "-c", "echo one; sleep 1.2; echo two"])
        self.assertEqual(rc, 0)
        self.assertIn("$ sh -c", job.posts[0][1])
        self.assertLess(job.posts[0][0] - t0, 0.5)
        first = next(at for at, text in job.posts if "one" in text)
        self.assertLess(first, t1 - 0.6, "the first line waited for the command to end")
        self.assertIn("two", "".join(t for _, t in job.posts) + "".join(job.pending))

    def test_its_exit_code_comes_back(self):
        self.assertEqual(self.run_sh(["sh", "-c", "exit 3"])[0], 3)

    def test_a_command_that_is_not_there_is_said(self):
        rc, job, _, _ = self.run_sh(["/nonexistent/tool"])
        self.assertEqual(rc, 1)
        self.assertIn("/nonexistent/tool", "".join(t for _, t in job.posts) + "".join(job.pending))

    def test_a_timeout_ends_it(self):
        rc, job, t0, t1 = self.run_sh(["sh", "-c", "sleep 30"], timeout=1)
        self.assertEqual(rc, 124)
        self.assertLess(t1 - t0, 10)


if __name__ == "__main__":
    unittest.main()
