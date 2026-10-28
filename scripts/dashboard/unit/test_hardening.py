"""The process hardened (R158 step 6): core dumps off and the process not
dumpable, said for the Doctor; wipe() zeroes a key's bytes in place."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, HERE)
import hardening  # noqa: E402


class Apply(unittest.TestCase):
    def test_in_a_child_core_is_off_and_the_status_is_written(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        st = os.path.join(tmp, "h.json")
        code = ("import sys, resource; sys.path.insert(0, sys.argv[1]); import hardening\n"
                "hardening.apply(mlock=False, status_file=sys.argv[2])\n"
                "print(resource.getrlimit(resource.RLIMIT_CORE)[0])\n"
                "print(open('/proc/self/status').read().count('\\n'))")
        p = subprocess.run([sys.executable, "-c", code, HERE, st], capture_output=True, text=True, check=True)
        self.assertEqual(p.stdout.split()[0], "0", "the core limit is zero")
        d = json.load(open(st))
        self.assertTrue(d["core"])
        self.assertTrue(d["dumpable"], d)
        self.assertFalse(d["mlock"])

    def test_wipe_zeroes_in_place(self):
        b = bytearray(b"secret")
        self.assertTrue(hardening.wipe(b))
        self.assertEqual(bytes(b), b"\0" * 6)
        k = os.urandom(32)
        self.assertTrue(hardening.wipe(k))
        self.assertEqual(k, b"\0" * 32)
        self.assertFalse(hardening.wipe("not bytes"))


if __name__ == "__main__":
    unittest.main()
