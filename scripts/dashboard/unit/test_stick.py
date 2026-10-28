"""The USB stick maker (R161 step 5, tools/builderbot-stick.py): the disks
listed off the system's own tools, the system disk and a fixed disk never
written, an image written whole from its xz and read back, a sha256 that
does not match refused before anything is written."""
import hashlib
import importlib.util
import lzma
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TOOL = os.path.join(ROOT, "tools", "builderbot-stick.py")


def load():
    spec = importlib.util.spec_from_file_location("builderbot_stick", TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


LSBLK = '{"blockdevices": [{"name": "sda", "size": 512110190592, "model": "Samsung SSD", "rm": false, "tran": "sata", "type": "disk", "mountpoints": ["/"]},' \
        '{"name": "sdb", "size": 32000000000, "model": "Ultra Fit", "rm": true, "tran": "usb", "type": "disk", "mountpoints": [null]},' \
        '{"name": "loop0", "size": 1, "type": "loop", "mountpoints": []}]}'


class Stick(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.d = tempfile.mkdtemp()
        p = os.path.join(self.d, "lsblk")
        with open(p, "w") as f:
            f.write(f"#!/bin/sh\ncase \"$*\" in *MOUNTPOINTS\\ /dev/*) echo '';; *) cat <<'EOF'\n{LSBLK}\nEOF\n;; esac\n")
        os.chmod(p, stat.S_IRWXU)
        self.env = mock.patch.dict(os.environ, {"PATH": self.d + ":" + os.environ.get("PATH", "")})
        self.env.start(); self.addCleanup(self.env.stop)
        self.linux = mock.patch.object(self.m.platform, "system", return_value="Linux")
        self.linux.start(); self.addCleanup(self.linux.stop)

    def test_the_disks_are_listed_and_only_a_removable_one_may_be_written(self):
        rows = self.m.disks()
        self.assertEqual([(r["id"], r["removable"], r["system"]) for r in rows], [("/dev/sda", False, True), ("/dev/sdb", True, False)])
        with self.assertRaises(SystemExit):
            self.m.pick("/dev/sda")
        with self.assertRaises(SystemExit):
            self.m.pick("/dev/sdz")
        self.assertEqual(self.m.pick("/dev/sdb")["model"], "Ultra Fit")

    def test_an_image_is_written_whole_from_its_xz_and_read_back(self):
        raw = os.urandom(3 << 20) + b"\0" * (1 << 20)
        img = os.path.join(self.d, "builderbot-os-0.9.0.stick.raw.xz")
        with lzma.open(img, "wb") as f:
            f.write(raw)
        dev = os.path.join(self.d, "stick.img")
        with open(dev, "wb") as f:
            f.write(b"\xff" * len(raw))
        with mock.patch.object(self.m, "open_disk", side_effect=lambda d: open(d, "r+b", buffering=0)):
            self.m.write_image(img, dev)
        self.assertEqual(open(dev, "rb").read(), raw)
        with open(dev, "r+b") as f:
            f.seek(100); f.write(b"x")
        with self.assertRaises(SystemExit):
            self.m.verify(dev, len(raw), hashlib.sha256(raw).hexdigest())

    def test_a_sha256_that_does_not_match_is_refused(self):
        img = os.path.join(self.d, "x.xz")
        open(img, "wb").write(b"data")
        open(img + ".sha256", "w").write("0" * 64 + "  x.xz\n")
        with self.assertRaises(SystemExit):
            self.m.check_sha(img, img + ".sha256")
        open(img + ".sha256", "w").write(hashlib.sha256(b"data").hexdigest() + "  x.xz\n")
        self.m.check_sha(img, img + ".sha256")

    def test_the_tool_says_how(self):
        r = subprocess.run([sys.executable, TOOL, "--help"], capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0)
        self.assertIn("write DISK", r.stdout)
        r = subprocess.run([sys.executable, TOOL, "write", "/dev/sdb"], capture_output=True, text=True, check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--image FILE, --release vX.Y.Z or --latest", r.stderr)


if __name__ == "__main__":
    unittest.main()
