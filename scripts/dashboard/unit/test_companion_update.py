"""The Windows companion kept current by its controller (R270 step 9): a
newer copy fetched only when the controller holds one, kept only when it
matches the controller's sha256, and swapped in at the next start; a
checkout never replaced."""
import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "windows"))
from bbcompanion import update  # noqa: E402


class Ctl:
    """The door's connection: what it holds, and the file it serves."""

    def __init__(self, version, body, sha=None, name="builderbot-companion-9.9.9.pyz"):
        self.version, self.body, self.name = version, body, name
        self.sha = sha or hashlib.sha256(body).hexdigest()
        self.fetched = []

    def call(self, verb, body=None, **_):
        return 200, {"apps": [{"name": "companion", "version": self.version,
                               "files": [{"file": self.name, "sha256": self.sha}]}]}

    def fetch(self, path, dest, **_):
        self.fetched.append(path)
        with open(dest, "wb") as f:
            f.write(self.body)
        return 200, ""


class Update(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.me = os.path.join(self.dir, "builderbot-companion.pyz")
        with open(self.me, "wb") as f:
            f.write(b"old")
        self.patches = [mock.patch.object(update, "running_as", lambda: ("pyz", self.me)),
                        mock.patch.object(update, "version", lambda: "1.0.0")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_versions_compare_as_numbers(self):
        self.assertTrue(update.newer("1.10.0", "1.9.3"))
        self.assertFalse(update.newer("1.0.0", "1.0.0"))
        self.assertTrue(update.newer("v2.0.0", "1.99.99"))

    def test_nothing_is_fetched_when_this_copy_is_current(self):
        ctl = Ctl("1.0.0", b"same")
        self.assertEqual(update.check(ctl), {"current": "1.0.0"})
        self.assertEqual(ctl.fetched, [])

    def test_a_newer_copy_is_fetched_beside_this_one(self):
        got = update.check(Ctl("1.1.0", b"new"))
        self.assertEqual(got, {"pending": "1.1.0"})
        with open(self.me + ".new", "rb") as f:
            self.assertEqual(f.read(), b"new")

    def test_one_that_does_not_match_its_sha256_is_not_kept(self):
        got = update.check(Ctl("1.1.0", b"new", sha="0" * 64))
        self.assertIn("did not match", got["said"])
        self.assertFalse(os.path.exists(self.me + ".new"))

    def test_the_next_start_swaps_it_in_and_starts_from_it(self):
        update.check(Ctl("1.1.0", b"new"))
        with mock.patch.object(update.subprocess, "Popen") as popen, self.assertRaises(SystemExit):
            update.apply_pending([])
        with open(self.me, "rb") as f:
            self.assertEqual(f.read(), b"new")
        self.assertEqual(popen.call_args[0][0][-1], self.me)
        self.assertTrue(os.path.exists(self.me + ".old"))

    def test_a_checkout_is_never_replaced(self):
        with mock.patch.object(update, "running_as", lambda: ("", "")):
            got = update.check(Ctl("1.1.0", b"new"))
        self.assertIn("checkout", got["said"])


class Handshake(unittest.TestCase):
    """R79 step 8: the app says which door and release it is on every call,
    and says plainly when its controller's door is older than it needs."""

    def test_every_call_says_the_door_and_the_release(self):
        with mock.patch.object(update, "version", lambda: "1.2.3"):
            self.assertEqual(update.headers(), {"X-BB-Door": str(update.DOOR), "X-BB-App": "companion/1.2.3"})

    def test_a_controller_that_says_no_door_speaks_the_first(self):
        self.assertEqual(update.controller_too_old({"projects": []}), "")
        self.assertEqual(update.controller_too_old({"door": update.NEEDS_DOOR}), "")

    def test_a_controller_older_than_this_app_is_said_plainly(self):
        with mock.patch.object(update, "NEEDS_DOOR", 3):
            said = update.controller_too_old({"door": 2})
            self.assertIn("speaks door 2", said)
            self.assertIn("update BuilderBot on the controller", said)
            self.assertIn("speaks door 1", update.controller_too_old({}))
        self.assertIn("speaks door 0", update.controller_too_old({"door": 0}))

    def test_the_sync_is_told_nothing_while_the_controller_is_too_old(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))
        from bbcompanion import core

        door = core.DeviceDoor("http://127.0.0.1:9", "bbd_x", picked={"alpha": "/tmp/alpha"})
        self.assertEqual(door.ctl.headers["X-BB-App"].split("/")[0], "companion")
        answer = {"door": 1, "projects": [{"project": "alpha", "access": "rw", "rev": 4}]}
        with mock.patch.object(door.ctl, "call", lambda *a, **k: (200, answer)), \
                mock.patch.object(update, "NEEDS_DOOR", 2):
            st, r = door.call("sync", {"action": "projects"})
        self.assertEqual(st, 409)
        self.assertIn("needs 2 or newer", door.error)
        with mock.patch.object(door.ctl, "call", lambda *a, **k: (200, answer)):
            st, r = door.call("sync", {"action": "projects"})
        self.assertEqual((st, r["projects"], door.error), (200, {"alpha": 4}, ""))


if __name__ == "__main__":
    unittest.main()
