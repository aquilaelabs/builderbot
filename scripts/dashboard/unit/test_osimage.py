"""BuilderBot OS updated from the page (R160 step 4): the agent's os-update
job fetches the release's four files (or takes them from a folder), holds
each to its sha256, writes the slot not in use, puts the kernel beside it on
the ESP and names the slot for the next boot; a file that does not match
writes nothing; the census says the image, the slot and the next; the
controller queues the job only for a machine that runs the image; the
update window applies once per release at its hour and never by default."""
import hashlib
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))
import agentpkg  # noqa: E402


class Job:
    def __init__(self):
        self.log = []

    def say(self, s):
        self.log.append(s)

    def step(self, s):
        self.log.append(f"[{s}]")

    def text(self):
        return "".join(self.log)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class World:
    """A BuilderBot OS machine in a folder: the release file, a slot tool that
    keeps the next slot in a file, two slot partitions as files, an ESP, and
    a release's files served by file://."""
    def __init__(self, slot="a", version="0.9.0"):
        self.d = tempfile.mkdtemp()
        self.release = os.path.join(self.d, "release")
        with open(self.release, "w") as f:
            f.write(f"BUILDERBOT_OS_VERSION={version}\nDEBIAN_SNAPSHOT=20261020T000000Z\nBUILT=2026-10-20T00:00:00Z\n")
        self.nextf = os.path.join(self.d, "next")
        self.tool = os.path.join(self.d, "slot")
        self.trialf = os.path.join(self.d, "trial")
        with open(self.tool, "w") as f:
            f.write(f'#!/usr/bin/env bash\ncase "$1" in current) echo {slot};; other) echo {"b" if slot == "a" else "a"};; '
                    f'next) if [ -n "$2" ]; then echo "$2" > {self.nextf}; else cat {self.nextf} 2>/dev/null || echo a; fi;; '
                    f'trial) echo "prev=$2 ver=$3" > {self.trialf};; good) rm -f {self.trialf};; '
                    f'status) echo "booted: slot {slot}"; [ -f {self.trialf} ] && echo "trial: on";; fell-back) echo no;; esac\n')
        self.state = os.path.join(self.d, "state", "config")
        os.makedirs(self.state)
        with open(os.path.join(self.state, "state.json"), "w") as f:
            f.write("{}")
        os.makedirs(os.path.join(self.state, "logs"))
        with open(os.path.join(self.state, "logs", "big.log"), "w") as f:
            f.write("x" * 1000)
        os.chmod(self.tool, stat.S_IRWXU)
        self.dev = {}
        for s in "ab":
            self.dev[s] = os.path.join(self.d, f"dev-{s}")
            with open(self.dev[s], "wb") as f:
                f.write(b"\0" * 4096)
        self.esp = os.path.join(self.d, "esp")
        os.makedirs(os.path.join(self.esp, "builderbot", "a"))
        self.work = os.path.join(self.d, "work")
        self.env = {"BB_OS_RELEASE": self.release, "BB_OS_SLOT": self.tool, "BB_OS_DEV_A": self.dev["a"], "BB_OS_DEV_B": self.dev["b"],
                    "BB_OS_ESP": self.esp, "BB_OS_WORK": self.work, "BB_OS_RELEASE_URL": "file://" + os.path.join(self.d, "rel"),
                    "BB_OS_STATE": self.state}

    def publish(self, version, bad=None):
        """The release's files under rel/vVERSION, each with its sha256; `bad`
        names a piece whose sha256 file lies."""
        d = os.path.join(self.d, "rel", "v" + version)
        os.makedirs(d, exist_ok=True)
        files = {"root.squashfs": b"hsqs" + version.encode() * 300, "vmlinuz": b"MZkernel" + version.encode(),
                 "initrd": b"initrd" + version.encode(), "release": f"BUILDERBOT_OS_VERSION={version}\n".encode()}
        for piece, data in files.items():
            with open(os.path.join(d, f"builderbot-os-{version}.{piece}"), "wb") as f:
                f.write(data)
            with open(os.path.join(d, f"builderbot-os-{version}.{piece}.sha256"), "w") as f:
                f.write(f"{'0' * 64 if piece == bad else sha(data)}  builderbot-os-{version}.{piece}\n")
        return d, files


class TheAgent(unittest.TestCase):
    def setUp(self):
        self.agent = agentpkg.load("builderbot_agent_os")
        self.av = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".osimage"]
        av = self.av

        class A(av.OsImageMixin):
            def _sh(self, job, argv, timeout=0, **kw):
                r = subprocess.run(argv, capture_output=True, text=True, check=False)
                job.say(r.stdout + r.stderr)
                return r.returncode

            def hello_again(self, why):
                self.said = why
        self.A = A
        real = self.av.shutil.which
        self.nogh = mock.patch.object(self.av.shutil, "which", side_effect=lambda n: None if n == "gh" else real(n))
        self.nogh.start()
        self.addCleanup(self.nogh.stop)

    def run_update(self, w, cfg):
        with mock.patch.dict(os.environ, w.env):
            job = Job()
            state, code = self.A()._apply_os_update(job, cfg)
        return state, code, job.text()

    def test_the_partitions_are_the_images(self):
        sh = open(os.path.join(ROOT, "image", "partitions.sh")).read()
        for slot, key in (("a", "BB_PART_ROOT_A"), ("b", "BB_PART_ROOT_B")):
            uuid = re.search(rf"^{key}=([0-9a-f-]+)", sh, re.M).group(1)
            self.assertEqual(self.av.SLOT_DEV[slot], f"/dev/disk/by-partuuid/{uuid}")
        self.assertEqual(str(self.av.SLOT_MIB), re.search(r"^BB_SIZE_SLOT_MIB=(\d+)", sh, re.M).group(1))

    def test_the_census_says_the_image_the_slot_and_the_next(self):
        w = World(slot="b")
        with mock.patch.dict(os.environ, w.env):
            got = self.av.os_release()
        self.assertEqual((got["version"], got["snapshot"], got["slot"], got["next"]), ("0.9.0", "20261020T000000Z", "b", "a"))
        with mock.patch.dict(os.environ, {"BB_OS_RELEASE": os.path.join(w.d, "none")}):
            self.assertEqual(self.av.os_release(), {})

    def test_a_release_is_written_into_the_other_slot_and_named_for_the_next_boot(self):
        w = World(slot="a")
        _, files = w.publish("0.9.1")
        state, code, text = self.run_update(w, {"release": "v0.9.1"})
        self.assertEqual((state, code), ("succeeded", 0), text)
        with open(w.dev["b"], "rb") as f:
            self.assertTrue(f.read().startswith(files["root.squashfs"]))
        with open(w.dev["a"], "rb") as f:
            self.assertEqual(f.read(), b"\0" * 4096, "the running slot is untouched")
        for piece in ("vmlinuz", "initrd", "release"):
            with open(os.path.join(w.esp, "builderbot", "b", piece), "rb") as f:
                self.assertEqual(f.read(), files[piece])
        self.assertEqual(open(w.nextf).read().strip(), "b")
        self.assertIn("slot b holds BuilderBot OS 0.9.1", text)
        # On trial (R161 step 2), going back to slot a; and the configuration
        # as it was kept beside it, without its logs.
        self.assertEqual(open(w.trialf).read().strip(), "prev=a ver=0.9.1")
        kept = os.path.join(w.work, "before", "0.9.0.tar.gz")
        self.assertTrue(os.path.isfile(kept), text)
        names = subprocess.run(["tar", "-tzf", kept], capture_output=True, text=True, check=False).stdout
        self.assertIn("config/state.json", names)
        self.assertNotIn("big.log", names)
        with mock.patch.dict(os.environ, w.env):
            got = self.av.os_release()
        self.assertTrue(got["trial"])
        self.assertEqual(got["fell_back"], "")
        self.assertIn("no gh here", text)
        self.assertFalse(os.path.exists(os.path.join(w.work, "update")), "the working files are gone")

    def test_a_fallback_the_health_check_recorded_is_said_until_the_next_update(self):
        w = World(slot="a")
        os.makedirs(w.work)
        with open(os.path.join(w.work, "fell-back"), "w") as f:
            f.write("the slot written by the last update did not come up healthy twice, so this boot is back on slot a as it was\n")
        with mock.patch.dict(os.environ, w.env):
            self.assertIn("back on slot a", self.av.os_release()["fell_back"])
        w.publish("0.9.3")
        state, code, text = self.run_update(w, {"release": "v0.9.3"})
        self.assertEqual(state, "succeeded", text)
        self.assertFalse(os.path.exists(os.path.join(w.work, "fell-back")))

    def test_a_file_that_does_not_match_its_sha256_writes_nothing(self):
        w = World(slot="a")
        w.publish("0.9.1", bad="vmlinuz")
        state, code, text = self.run_update(w, {"release": "v0.9.1"})
        self.assertEqual((state, code), ("failed", 67), text)
        self.assertIn("vmlinuz: its sha256 does not match", text)
        with open(w.dev["b"], "rb") as f:
            self.assertEqual(f.read(), b"\0" * 4096)
        self.assertFalse(os.path.exists(w.nextf))

    def test_an_offline_machine_takes_the_files_from_a_folder(self):
        w = World(slot="b")
        d, files = w.publish("0.9.2")
        state, code, text = self.run_update(w, {"from": d})
        self.assertEqual((state, code), ("succeeded", 0), text)
        with open(w.dev["a"], "rb") as f:
            self.assertTrue(f.read().startswith(files["root.squashfs"]))
        self.assertEqual(open(w.nextf).read().strip(), "a")
        state, code, text = self.run_update(w, {"from": os.path.join(w.d, "nowhere")})
        self.assertEqual(state, "failed")
        self.assertIn("is not a folder", text)

    def test_what_is_refused(self):
        w = World()
        state, code, text = self.run_update(w, {"release": "latest"})
        self.assertEqual((state, code), ("failed", 64))
        state, code, text = self.run_update(w, {})
        self.assertIn("names a release", text)
        with mock.patch.dict(os.environ, {**w.env, "BB_OS_RELEASE": os.path.join(w.d, "none")}):
            state, code = self.A()._apply_os_update(Job(), {"release": "v0.9.1"})
        self.assertEqual(code, 77)


class TheController(unittest.TestCase):
    def test_the_census_keeps_the_image_to_its_shape(self):
        import nodes
        got = nodes._census({"os_image": {"version": "0.9.1<b>", "snapshot": "20261020T000000Z", "built": "2026-10-20T00:00:00Z", "slot": "a", "next": "c",
                                          "trial": True, "fell_back": "back on slot a <b>"}})
        self.assertEqual(got["os_image"], {"version": "0.9.1b", "snapshot": "20261020T000000Z", "built": "2026-10-20T00:00:00Z", "slot": "a", "next": "",
                                           "trial": True, "fell_back": "back on slot a b"})
        self.assertNotIn("os_image", nodes._census({"os_image": {}}))

    def test_the_update_window_applies_once_at_its_hour_and_never_by_default(self):
        import releasecheck
        applied = []
        releasecheck._latest.update(version="0.9.5", tag="v0.9.5")
        self.addCleanup(lambda: releasecheck._latest.update(version="", tag=""))
        self.addCleanup(lambda: releasecheck._applied.update(version=""))
        window = ["", 4]
        releasecheck.configure(version=lambda: "0.9.0", bare_metal=lambda: True, window=lambda: tuple(window), apply=applied.append)
        at = time.mktime(time.localtime()[:3] + (4, 30, 0, 0, 0, -1))
        self.assertEqual(releasecheck.window_pass(at), "", "no window set: nothing by itself")
        window[0] = "daily"
        self.assertEqual(releasecheck.window_pass(at + 3600), "", "an hour later is outside the window")
        self.assertEqual(releasecheck.window_pass(at), "0.9.5")
        self.assertEqual(releasecheck.window_pass(at), "", "one window queues one release once")
        self.assertEqual(applied, ["0.9.5"])
        window[0] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[time.localtime(at).tm_wday]
        releasecheck._applied["version"] = ""
        self.assertEqual(releasecheck.window_pass(at), "0.9.5", "the weekday named")
        releasecheck._applied["version"] = ""
        window[0] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[(time.localtime(at).tm_wday + 1) % 7]
        self.assertEqual(releasecheck.window_pass(at), "", "another weekday")


if __name__ == "__main__":
    unittest.main()
