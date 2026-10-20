"""An approved bb root run prints what the command said, from who allowed it
on, without the agent's own lines about the job before it ("system: root", a
sandbox tool refreshed from the bundle), which the Jobs page keeps (B58)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import phone  # noqa: E402

HEAD = "# root on this node, allowed by sean: load the module\n$ modprobe binder\n"


class RootSaid(unittest.TestCase):
    def test_the_agents_lines_go(self):
        log = "system: root\n/usr/local/sbin/bb-sandbox refreshed from the bundle\n" + HEAD + "done\n"
        self.assertEqual(phone.root_said(log), HEAD + "done\n")

    def test_a_log_that_opens_with_it_is_left_alone(self):
        self.assertEqual(phone.root_said(HEAD), HEAD)

    def test_a_refusal_without_it_is_left_whole(self):
        log = "system: root\nrefused: this node was not provisioned as a BuilderBot sandbox\n"
        self.assertEqual(phone.root_said(log), log)


if __name__ == "__main__":
    unittest.main()
