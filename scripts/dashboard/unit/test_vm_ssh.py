"""bb vm ssh (scripts/lib/vm-verbs.py): the key bb vm new made for the session,
and the hosts it met, named to ssh from $HOME, the account's own home, where
own_key made them. ssh reads the Unix account's home from the password file,
which for an account's session is the shared session account's (B307)."""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "..", "lib")


def load():
    sys.path.insert(0, LIB)
    spec = importlib.util.spec_from_file_location("vm_verbs", os.path.join(LIB, "vm-verbs.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Ssh(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.vm = load()
        self.vm.read = lambda: {"vms": [{"project": "p", "name": "tiny", "ip": "10.232.0.9", "user": "builder"}]}
        self.vm.mine = lambda d, name: next((v for v in d["vms"] if v["name"] == name), None)

    def argv(self):
        got = []
        with mock.patch.dict(os.environ, {"HOME": self.home}), \
                mock.patch.object(self.vm.os, "execvp", lambda f, a: got.extend(a)):
            self.vm.cmd_ssh(["tiny", "uname", "-a"])
        return got

    def test_the_key_made_in_home_is_the_one_used(self):
        os.makedirs(os.path.join(self.home, ".ssh"))
        open(os.path.join(self.home, ".ssh", "id_ed25519"), "w").close()
        a = self.argv()
        self.assertEqual(a[a.index("-i") + 1], os.path.join(self.home, ".ssh", "id_ed25519"))
        self.assertIn(f"UserKnownHostsFile={os.path.join(self.home, '.ssh', 'known_hosts')}", a)
        self.assertEqual(a[-3:], ["builder@10.232.0.9", "uname", "-a"])

    def test_with_no_key_there_ssh_picks_its_own(self):
        a = self.argv()
        self.assertNotIn("-i", a)
        self.assertIn(f"UserKnownHostsFile={os.path.join(self.home, '.ssh', 'known_hosts')}", a)


if __name__ == "__main__":
    unittest.main()
