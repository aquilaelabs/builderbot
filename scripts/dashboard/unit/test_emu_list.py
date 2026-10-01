"""bb emu list and the default AVD read the AVDs' own files (B425), not
avdmanager, which scanned the whole shared SDK first and took 105 s: names,
the target and the image, and the newest builderbot-N as the default."""
import os
import subprocess
import tempfile
import time
import unittest

BB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "bb")


class EmuList(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.avd = os.path.join(self.home, ".android", "avd")
        for api in ("35", "36"):
            d = os.path.join(self.avd, f"builderbot-{api}.avd")
            os.makedirs(d)
            with open(os.path.join(self.avd, f"builderbot-{api}.ini"), "w") as f:
                f.write(f"path={d}\ntarget=android-{api}\n")
            with open(os.path.join(d, "config.ini"), "w") as f:
                f.write("tag.id = google_apis\nabi.type = x86_64\n")

    def test_it_lists_them_from_their_files_and_quickly(self):
        env = dict(os.environ, HOME=self.home, ANDROID_AVD_HOME=self.avd, ANDROID_HOME=self.home,
                   PATH="/usr/bin:/bin")
        env.pop("ANDROID_AVD_NAME", None)
        t = time.time()
        p = subprocess.run(["bash", BB, "emu", "list"], env=env, capture_output=True, text=True,
                           timeout=60, check=False)
        self.assertLess(time.time() - t, 20)
        self.assertIn("Name: builderbot-35\n  Based on: android-35 google_apis x86_64", p.stdout)
        self.assertIn("Name: builderbot-36", p.stdout)
        self.assertIn("default for `bb emu start`: builderbot-36", p.stdout)


if __name__ == "__main__":
    unittest.main()
