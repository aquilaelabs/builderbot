"""The root agent asks a binary for its version as the account that owns
it, or as nobody where root owns it and others may write it; only a binary
root owns and alone may write runs as root (B523: a build or a session
could replace the toolchain store's java or its own claude, which root ran)."""
import os
import stat
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))
from builderbot_agent import base  # noqa: E402


def st(uid, mode):
    return mock.Mock(st_uid=uid, st_gid=uid, st_mode=stat.S_IFREG | mode)


class ProbeAs(unittest.TestCase):
    def as_(self, uid, mode):
        with mock.patch.object(base.os, "geteuid", return_value=0), \
                mock.patch.object(base.os, "stat", return_value=st(uid, mode)):
            return base._probe_as("/s/jdk/bin/java")

    def test_a_binary_an_account_owns_runs_as_that_account(self):
        self.assertEqual(self.as_(1001, 0o755), {"user": 1001, "group": 1001, "extra_groups": []})

    def test_one_root_owns_that_others_may_write_runs_as_nobody(self):
        self.assertEqual(self.as_(0, 0o775)["user"], 65534)
        self.assertEqual(self.as_(0, 0o757)["user"], 65534)

    def test_one_root_alone_may_write_runs_as_root(self):
        self.assertEqual(self.as_(0, 0o755), {})

    def test_not_root_changes_nothing(self):
        with mock.patch.object(base.os, "geteuid", return_value=1000):
            self.assertEqual(base._probe_as("/bin/sh"), {})


if __name__ == "__main__":
    unittest.main()
