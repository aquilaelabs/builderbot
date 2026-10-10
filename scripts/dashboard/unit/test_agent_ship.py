"""The agent's half of shipping an image between two nodes (R166): an
upload step sends a file of its job's compose directory to the controller's
image verb and removes it here; a fetch step brings one into that
directory; nothing outside the directory and no other verb is touched."""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agentpkg  # noqa: E402

AGENT = agentpkg.load("ship")
WorkMixin = AGENT.module("work").WorkMixin


class Ctl:
    def __init__(self):
        self.calls = []

    def upload(self, verb, path, timeout=0, offset=0, length=None):
        with open(path, "rb") as f:
            self.calls.append(("upload", verb, f.read()))
        return 200, {"ok": True}

    def fetch(self, verb, dest, timeout=0):
        self.calls.append(("fetch", verb))
        with open(dest, "wb") as f:
            f.write(b"the image")
        return 200, ""


class Job:
    def __init__(self):
        self.said = []

    def say(self, s):
        self.said.append(s)


class Box(WorkMixin):
    def __init__(self):
        self.ctl = Ctl()
        self.state = {}

    def drop_privileges(self, env):
        return {}


class Ship(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cdir = os.path.join(self.tmp, "compose", "web")
        os.makedirs(self.cdir)
        self.box = Box()

    def test_upload_sends_and_removes(self):
        with open(os.path.join(self.cdir, "image.tar"), "wb") as f:
            f.write(b"layers")
        st, code = self.box.ship_step(Job(), {"upload": "{cdir}/image.tar", "to": "devimage-put?job=j_1"}, self.cdir)
        self.assertEqual((st, code), ("succeeded", 0))
        self.assertEqual(self.box.ctl.calls, [("upload", "devimage-put?job=j_1", b"layers")])
        self.assertFalse(os.path.exists(os.path.join(self.cdir, "image.tar")), "removed once sent")

    def test_fetch_brings_it_into_the_directory(self):
        st, _ = self.box.ship_step(Job(), {"fetch": "devimage?job=j_2", "dest": "{cdir}/image.tar"}, self.cdir)
        self.assertEqual(st, "succeeded")
        with open(os.path.join(self.cdir, "image.tar"), "rb") as f:
            self.assertEqual(f.read(), b"the image")

    def test_nothing_outside_the_directory_or_another_verb(self):
        outside = os.path.join(self.tmp, "secret")
        with open(outside, "w") as f:
            f.write("x")
        for stp in ({"upload": outside, "to": "devimage-put?job=j"},
                    {"upload": "{cdir}/../../secret", "to": "devimage-put?job=j"},
                    {"fetch": "devimage?job=j", "dest": "/etc/passwd"},
                    {"upload": "{cdir}/x", "to": "sync-put?project=alpha&path=x"},
                    {"fetch": "file?job=j", "dest": "{cdir}/x"}):
            st, code = self.box.ship_step(Job(), stp, self.cdir)
            self.assertEqual((st, code), ("failed", 78), stp)
        self.assertEqual(self.box.ctl.calls, [])
        self.assertTrue(os.path.exists(outside))


if __name__ == "__main__":
    unittest.main()
