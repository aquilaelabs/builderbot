"""The Toolchains page's read says the job as it stood when its rows were
read (B13): a job that ended while the rows were being read said "done"
over a row read mid-removal, and the page, seeing nothing running, stopped
asking and kept a removed toolchain installed."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402


class JobWithItsRows(unittest.TestCase):
    def test_a_job_ending_mid_read_is_still_running_in_that_read(self):
        saved = dict(toolchains._tc_job)
        self.addCleanup(lambda: (toolchains._tc_job.clear(), toolchains._tc_job.update(saved)))
        toolchains._tc_job.update(running=True, action="remove", current="android:emulator")

        def path_then_end(probe):
            # The worker finishes while the rows are read.
            toolchains._tc_job["running"] = False
            return "/sdk/" + probe

        with mock.patch.object(toolchains, "_tc_path", path_then_end), \
                mock.patch.object(toolchains, "sdk_root_path", lambda: "/sdk"), \
                mock.patch.object(toolchains, "is_mount", lambda p: False):
            got = toolchains.payload()
        self.assertTrue(got["job"]["running"], "the rows were read while it ran, so the read says it runs")
        self.assertEqual(got["job"]["action"], "remove")
        self.assertFalse(toolchains._tc_job["running"], "...and the next read is the one that says it ended")


if __name__ == "__main__":
    unittest.main()
