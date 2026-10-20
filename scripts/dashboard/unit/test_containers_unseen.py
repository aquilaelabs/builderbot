"""The Containers page for an account that reads some projects' containers
and not others' (B89): what is left out of the answer is left out whole,
and the answer says that something was, so an empty page reads "nothing
here is yours to see" rather than that the daemon is empty."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import containers  # noqa: E402
import devapp  # noqa: E402
import imagecheck  # noqa: E402
import nginxproxy  # noqa: E402
import relocate  # noqa: E402


class Unseen(unittest.TestCase):
    def view(self, seen):
        over = {"node": "", "instances": [{"project": "web", "instance": "", "owner": "web", "name": "web-app"}],
                "containers": [{"name": "stray", "owner": "other"}]}
        with mock.patch.object(devapp, "forget_available", lambda: None), \
                mock.patch.object(devapp, "overview", lambda nid: {k: list(v) if isinstance(v, list) else v
                                                                   for k, v in over.items()}), \
                mock.patch.object(devapp, "refs_of", lambda p: []), \
                mock.patch.object(devapp, "override_files", lambda p: []), \
                mock.patch.object(devapp, "is_file_source", lambda p: False), \
                mock.patch.object(imagecheck, "last_at", lambda: 0), \
                mock.patch.object(imagecheck, "of", lambda n: {}), \
                mock.patch.object(nginxproxy, "record", lambda n: {}), \
                mock.patch.object(relocate, "view", lambda p, i: None):
            return containers.manager_view("", seen)

    def test_an_account_that_reads_none_of_it_is_told_so(self):
        got = self.view(set())
        self.assertEqual((got["instances"], got["containers"]), ([], []))
        self.assertTrue(got["unseen"], "something runs there that this account may not read")

    def test_nothing_left_out_says_nothing(self):
        got = self.view({"web", "other"})
        self.assertEqual(len(got["instances"]) + len(got["containers"]), 2)
        self.assertFalse(got["unseen"])

    def test_an_administrator_is_not_filtered(self):
        got = self.view(None)
        self.assertNotIn("unseen", got)


if __name__ == "__main__":
    unittest.main()
