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


class RootTmpRefused(unittest.TestCase):
    """A file under the session's own /tmp is refused before anybody is
    asked, since root runs outside that view (B159): no dashboard call is
    made, so none is configured here."""
    def test_nobody_is_asked(self):
        import subprocess
        import tempfile
        verbs = os.path.join(os.path.dirname(__file__), "..", "..", "lib", "root-verbs.py")
        with tempfile.NamedTemporaryFile(dir="/tmp") as f:
            r = subprocess.run([sys.executable, verbs, "run", "cat", f.name], capture_output=True, text=True, timeout=30,
                               env=os.environ | {"BB_PHONE_AUTH": "x", "BB_PHONE_WHY": "x", "BB_DASHBOARD": "http://127.0.0.1:9"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("nobody was asked", r.stderr)
        self.assertNotIn("asked ", r.stderr.replace("nobody was asked", ""))


if __name__ == "__main__":
    unittest.main()
