"""B39: Delete for good on the projects share, which is FUSE on Unraid: a
.fuse_hidden file that vanishes while the tree is taken apart is deleted as
far as the purge is concerned, rather than a 500 that leaves the project in
the trash for good."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import projects  # noqa: E402


class PurgeOnTheShare(unittest.TestCase):
    def test_a_file_that_vanishes_mid_delete_is_deleted(self):
        with tempfile.TemporaryDirectory() as t:
            tree = os.path.join(t, "walk-proj-a")
            os.makedirs(os.path.join(tree, "src"))
            for f in ("src/a.txt", ".fuse_hidden000a7e8500002328"):
                with open(os.path.join(tree, f), "w") as fh:
                    fh.write("x")
            real = os.unlink

            def unlink(name, *a, **kw):
                # The share takes the hidden file away itself, a moment
                # before the delete reaches it.
                if str(name).startswith(".fuse_hidden"):
                    real(name, *a, **kw)
                    raise FileNotFoundError(2, "No such file or directory", name)
                return real(name, *a, **kw)
            with mock.patch("os.unlink", unlink):
                projects._rmtree_share(tree, tries=2)
            self.assertFalse(os.path.exists(tree))

    def test_what_will_not_go_is_still_said(self):
        with tempfile.TemporaryDirectory() as t:
            tree = os.path.join(t, "stuck")
            os.makedirs(tree)
            with open(os.path.join(tree, "held"), "w") as fh:
                fh.write("x")
            with mock.patch("os.unlink", side_effect=PermissionError(13, "Permission denied")):
                with self.assertRaises(OSError):
                    projects._rmtree_share(tree, tries=2)


if __name__ == "__main__":
    unittest.main()
