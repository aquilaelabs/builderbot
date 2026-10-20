"""A failed compose job's row says why it failed (B96): a Rebuild on a node
whose image could not be pulled ended 'exit 1', and the row said only that,
while the reason was in the job's log on the Jobs page."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402


class Queue:
    """The job queue: one failed job, its log's reason."""
    why = "Error response from daemon: manifest for nginx:walk-typo-404 not found"

    def failed_why(self, job_id):
        return self.why if job_id == "j1" else ""


class JobWhy(unittest.TestCase):
    def setUp(self):
        self.was = devapp.queue
        devapp.queue = Queue()

    def tearDown(self):
        devapp.queue = self.was

    def test_an_exit_code_alone_is_replaced_by_the_log_reason(self):
        got = devapp.job_why({"id": "j1", "state": "failed", "error": "exit 1"})
        self.assertEqual(got, Queue.why + " (exit 1)")

    def test_no_error_at_all_still_says_why(self):
        self.assertEqual(devapp.job_why({"id": "j1", "state": "failed", "error": ""}), Queue.why)

    def test_a_reason_already_given_is_kept(self):
        got = devapp.job_why({"id": "j1", "state": "failed", "error": "up failed:\npool overlaps"})
        self.assertEqual(got, "up failed:\npool overlaps")

    def test_a_canceled_job_is_not_given_a_log_line(self):
        self.assertEqual(devapp.job_why({"id": "j1", "state": "canceled", "error": "canceled"}), "canceled")

    def test_nothing_in_the_log_keeps_the_code(self):
        self.assertEqual(devapp.job_why({"id": "j2", "state": "failed", "error": "exit 1"}), "exit 1")


if __name__ == "__main__":
    unittest.main()
