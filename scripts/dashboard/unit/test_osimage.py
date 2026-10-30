"""BuilderBot OS updated from the page (R160 step 4): the agent's os-update
job fetches the release's ISO (or takes it from a folder), holds it to its
sha256, takes the slot, kernel, initrd and release stamp out of its live/
folder, writes the slot not in use, puts the kernel beside it on
the ESP and names the slot for the next boot; a file that does not match
writes nothing; the census says the image, the slot and the next; the
controller queues the job only for a machine that runs the image; the
update window applies once per release at its hour and never by default."""
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
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


# Where image/build.sh puts each piece on the ISO.
IN_ISO = {"root.squashfs": "live/filesystem.squashfs", "vmlinuz": "live/vmlinuz",
          "initrd": "live/initrd", "release": "live/release"}


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
                    f'hold) echo {slot} > {self.nextf}; rm -f {self.trialf};; '
                    f'switch) [ -z "$BB_FAKE_SWITCH_FAILS" ] || exit 1; echo "$2" > {self.nextf}; echo "prev=$3 ver=$4" > {self.trialf};; '
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
                    "BB_OS_STATE": self.state, "BB_OS_ATTEST_URL": "file://" + os.path.join(self.d, "attestations.json"),
                    "BB_OS_TRUSTED_ROOT": os.path.join(self.d, "trusted-root.jsonl")}
        with open(os.path.join(self.d, "trusted-root.jsonl"), "w") as f:
            f.write("{}\n")

    def publish(self, version, bad=False, without=""):
        """The release's ISO under rel/vVERSION with its sha256: here a tar
        holding the ISO's live/ folder, which the test's mount unpacks. `bad`
        makes the sha256 file lie; `without` leaves a piece out."""
        d = os.path.join(self.d, "rel", "v" + version)
        os.makedirs(d, exist_ok=True)
        files = {"root.squashfs": b"hsqs" + version.encode() * 300, "vmlinuz": b"MZkernel" + version.encode(),
                 "initrd": b"initrd" + version.encode(), "release": f"BUILDERBOT_OS_VERSION={version}\n".encode()}
        live = os.path.join(self.d, "live-" + version)
        os.makedirs(os.path.join(live, "live"), exist_ok=True)
        for piece, data in files.items():
            if piece != without:
                with open(os.path.join(live, IN_ISO[piece]), "wb") as f:
                    f.write(data)
        iso = os.path.join(d, f"builderbot-os-{version}.iso")
        with tarfile.open(iso, "w") as t:
            t.add(os.path.join(live, "live"), arcname="live")
        with open(iso, "rb") as f:
            want = sha(f.read())
        with open(iso + ".sha256", "w") as f:
            f.write(f"{'0' * 64 if bad else want}  builderbot-os-{version}.iso\n")
        # Its build attestation: what GitHub's API answers for the ISO's
        # digest, and the bundle the release carries beside it.
        bundle = {"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json", "subject": want}
        with open(os.path.join(self.d, "attestations.json"), "w") as f:
            json.dump({"attestations": [{"bundle": bundle}]}, f)
        with open(os.path.join(d, f"builderbot-os-{version}.attestation.jsonl"), "w") as f:
            f.write(json.dumps(bundle) + "\n")
        return d, files


class TheAgent(unittest.TestCase):
    def setUp(self):
        self.agent = agentpkg.load("builderbot_agent_os")
        self.av = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".osimage"]
        av = self.av

        class A(av.OsImageMixin):
            def _sh(self, job, argv, timeout=0, **kw):
                # The ISO is opened by mount, which needs root: here the
                # test's ISO is a tar, unpacked where it would be mounted.
                if argv[0] == "mount":
                    self.mounted = argv
                    with tarfile.open(argv[-2]) as t:
                        t.extractall(argv[-1], filter="data")
                    return 0
                if argv[0] == "umount":
                    self.unmounted = argv
                    return 0
                r = subprocess.run(argv, capture_output=True, text=True, check=False)
                job.say(r.stdout + r.stderr)
                return r.returncode

            def hello_again(self, why):
                self.said = why
        self.A = A
        # A gh that answers as BB_FAKE_GH_RC says, standing in for GitHub's
        # attestation check; BB_FAKE_NO_GH takes it away.
        real = self.av.shutil.which
        self.ghd = tempfile.mkdtemp()
        gh = os.path.join(self.ghd, "gh")
        with open(gh, "w") as f:
            # It wants --bundle, a file holding a bundle for the ISO's digest,
            # as the real one checks the bundle against the file.
            f.write('#!/bin/sh\necho "gh $*"\nf="$3"; b="$5"\n[ "$4" = --bundle ] || exit 9\n'
                    'grep -q "$(sha256sum "$f" | cut -d" " -f1)" "$b" || exit 8\nexit "${BB_FAKE_GH_RC:-0}"\n')
        os.chmod(gh, stat.S_IRWXU)
        self.fakegh = mock.patch.object(self.av.shutil, "which", side_effect=lambda n: (
            None if os.environ.get("BB_FAKE_NO_GH") else gh) if n == "gh" else real(n))
        self.fakegh.start()
        self.addCleanup(self.fakegh.stop)

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
        self.assertIn("gh attestation verify", text)
        self.assertFalse(os.path.exists(os.path.join(w.work, "update")), "the working files are gone")

    def test_a_slot_on_trial_is_never_the_one_an_update_runs_from(self):
        # B470: running slot b on trial, slot a is the only good one, and an
        # update would have written it.
        w = World(slot="b")
        with open(w.nextf, "w") as f:
            f.write("b\n")
        with open(w.trialf, "w") as f:
            f.write("prev=a ver=0.9.1\n")
        w.publish("0.9.2")
        state, code, text = self.run_update(w, {"release": "v0.9.2"})
        self.assertEqual((state, code), ("failed", 79), text)
        with open(w.dev["a"], "rb") as f:
            self.assertEqual(f.read(), b"\0" * 4096, "the good slot is untouched")

    def test_an_image_with_no_attestation_check_writes_nothing(self):
        w = World(slot="a")
        w.publish("0.9.1")
        for env, said in (({"BB_FAKE_NO_GH": "1"}, "no gh here"), ({"BB_FAKE_GH_RC": "1"}, "did not verify")):
            with mock.patch.dict(os.environ, env):
                state, code, text = self.run_update(w, {"release": "v0.9.1"})
            self.assertEqual((state, code), ("failed", 68), text)
            self.assertIn(said, text)
            with open(w.dev["b"], "rb") as f:
                self.assertEqual(f.read(), b"\0" * 4096)
            self.assertFalse(os.path.exists(os.path.join(w.work, "update")), "a failed update leaves nothing behind")

    def test_an_image_that_would_not_fit_is_not_fetched(self):
        # R191 step 4: refused before a byte is written, saying how much.
        w = World(slot="a")
        w.publish("0.9.1")
        full = mock.Mock(f_bavail=10, f_frsize=4096)
        with mock.patch.object(self.av.os, "statvfs", return_value=full):
            state, code, text = self.run_update(w, {"release": "v0.9.1"})
        self.assertEqual((state, code), ("failed", 66), text)
        self.assertIn("the update needs about", text)
        with open(w.dev["b"], "rb") as f:
            self.assertEqual(f.read(), b"\0" * 4096)

    def test_an_offline_folder_without_its_attestation_writes_nothing(self):
        # R191 step 1: a folder on a share is no proof of who built it.
        w = World(slot="a")
        d, _ = w.publish("0.9.2")
        os.unlink(os.path.join(d, "builderbot-os-0.9.2.attestation.jsonl"))
        state, code, text = self.run_update(w, {"from": d})
        self.assertEqual((state, code), ("failed", 68), text)
        self.assertIn("attestation.jsonl", text)
        with open(w.dev["b"], "rb") as f:
            self.assertEqual(f.read(), b"\0" * 4096)

    def test_github_with_no_attestation_for_the_image_writes_nothing(self):
        w = World(slot="a")
        w.publish("0.9.1")
        with open(os.path.join(w.d, "attestations.json"), "w") as f:
            f.write('{"attestations": []}')
        state, code, text = self.run_update(w, {"release": "v0.9.1"})
        self.assertEqual((state, code), ("failed", 68), text)
        self.assertIn("no build attestation", text)

    def test_a_trial_not_set_leaves_the_next_boot_here(self):
        w = World(slot="a")
        w.publish("0.9.1")
        with mock.patch.dict(os.environ, {"BB_FAKE_SWITCH_FAILS": "1"}):
            state, code, text = self.run_update(w, {"release": "v0.9.1"})
        self.assertEqual((state, code), ("failed", 73), text)
        self.assertEqual(open(w.nextf).read().strip(), "a")
        self.assertFalse(os.path.exists(w.trialf))

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

    def test_an_image_that_does_not_match_its_sha256_writes_nothing(self):
        w = World(slot="a")
        w.publish("0.9.1", bad=True)
        state, code, text = self.run_update(w, {"release": "v0.9.1"})
        self.assertEqual((state, code), ("failed", 67), text)
        self.assertIn("builderbot-os-0.9.1.iso: its sha256 does not match", text)
        with open(w.dev["b"], "rb") as f:
            self.assertEqual(f.read(), b"\0" * 4096)
        self.assertFalse(os.path.exists(w.nextf))

    def test_an_image_missing_a_piece_writes_nothing_and_is_closed_again(self):
        w = World(slot="a")
        w.publish("0.9.1", without="initrd")
        a = self.A()
        with mock.patch.dict(os.environ, w.env):
            job = Job()
            state, code = a._apply_os_update(job, {"release": "v0.9.1"})
        self.assertEqual((state, code), ("failed", 66), job.text())
        self.assertIn("the image has no live/initrd", job.text())
        self.assertEqual(a.mounted[:3], ["mount", "-o", "loop,ro,nodev,nosuid,noexec"])
        self.assertEqual(a.unmounted[-1], a.mounted[-1])
        with open(w.dev["b"], "rb") as f:
            self.assertEqual(f.read(), b"\0" * 4096)

    def test_an_offline_machine_takes_the_files_from_a_folder(self):
        w = World(slot="b")
        d, files = w.publish("0.9.2")
        state, code, text = self.run_update(w, {"from": d})
        self.assertEqual((state, code), ("succeeded", 0), text)
        with open(w.dev["a"], "rb") as f:
            self.assertTrue(f.read().startswith(files["root.squashfs"]))
        self.assertEqual(open(w.nextf).read().strip(), "a")
        # Verified with no network, against the root the image was built with.
        self.assertIn("--custom-trusted-root", text)
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
