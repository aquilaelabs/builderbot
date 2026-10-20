"""A container job is asked for by the account that pressed the button, and a
canceled job ends naming whoever pressed Cancel, where every compose job said
'operator' and every cancel 'stopped by the operator' (B69)."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import devactions  # noqa: E402
import nodes  # noqa: E402


class Cancels(unittest.TestCase):
    def setUp(self):
        nodes.configure(state=tempfile.mkdtemp())
        mint = nodes.enroll_mint("user:test", "box")
        nodes.enroll(nodes.authenticate(mint["token"]), {"cpu": 2, "mem_mb": 4096, "arch": "x86_64",
                                                         "system": "linux", "session": {"up": True, "user": "b"}},
                     "10.0.0.5", user="bb")
        self.nid = mint["id"]

    def queued(self):
        return nodes.job_add("user:stencil", {"node": self.nid}, "system",
                             {"apply": "uninstall", "config": {}, "timeout": 900})["job"]

    def test_a_running_job_ends_naming_who_pressed_cancel(self):
        jid = self.queued()
        nodes.job_next(self.nid, 0)
        nodes.job_cancel("user:alice", jid)
        # The agent's own words, which know nothing of who pressed.
        nodes.job_result(self.nid, jid, "canceled", None, "stopped by the operator")
        self.assertEqual(nodes.job(jid, with_log=False)["error"], "stopped by alice")

    def test_a_queued_job_ends_naming_who_pressed_cancel(self):
        jid = self.queued()
        nodes.job_cancel("user:alice", jid)
        self.assertEqual(nodes.job(jid, with_log=False)["error"], "canceled by alice before it started")

    def test_no_person_behind_the_cancel_keeps_the_plain_words(self):
        jid = self.queued()
        nodes.job_next(self.nid, 0)
        nodes.job_cancel("dashboard", jid)
        nodes.job_result(self.nid, jid, "canceled", None, "stopped")
        self.assertEqual(nodes.job(jid, with_log=False)["error"], "stopped")

    def test_a_reason_of_its_own_is_kept(self):
        jid = self.queued()
        nodes.job_next(self.nid, 0)
        nodes.job_cancel("user:alice", jid)
        nodes.job_result(self.nid, jid, "canceled", None, "canceled: the agent was stopped")
        self.assertEqual(nodes.job(jid, with_log=False)["error"], "canceled: the agent was stopped")


class Asker(unittest.TestCase):
    def test_acting_as_names_the_account_inside_and_the_old_word_outside(self):
        self.assertEqual(devactions._by.get(), "operator")
        with devactions.acting_as("user:stencil"):
            self.assertEqual(devactions._by.get(), "user:stencil")
        self.assertEqual(devactions._by.get(), "operator")

    def test_a_compose_job_is_queued_by_the_account(self):
        seen = []

        class Q:
            def job_add(self, who, placement, kind, spec, project=""):
                seen.append(who)
                return {"error": "stop here"}

        was = (devactions.devapp.queue, devactions._active_job, devactions.devapp._instance_node,
               devactions.shipped, devactions.devapp._read_rec)
        devactions.devapp.queue = Q()
        devactions.devapp._read_rec = lambda p, i: {"node": "n1"}
        devactions._active_job = lambda p, i: None
        devactions.devapp._instance_node = lambda p, i: "n1"
        devactions.shipped = lambda p, i: False
        try:
            with devactions.acting_as("user:stencil"):
                devactions._submit("hello", "main", "up")
        finally:
            (devactions.devapp.queue, devactions._active_job, devactions.devapp._instance_node,
             devactions.shipped, devactions.devapp._read_rec) = was
        self.assertEqual(seen, ["user:stencil"])


if __name__ == "__main__":
    unittest.main()
