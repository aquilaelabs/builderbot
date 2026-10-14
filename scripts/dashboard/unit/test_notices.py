"""What the page said to each account, kept (R218 step 6, notices.py): added
newest first and capped, deleted one at a time, cleared whole or by kind,
one file per account and nothing for a request with none."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import notices  # noqa: E402

A, B = "u_0000000a", "u_0000000b"


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)


class Notices(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        notices.configure(state=self.tmp, write_json=write_json)

    def test_kept_newest_first_per_account_and_capped(self):
        notices.act(A, {"action": "add", "items": [{"text": "one"}, {"text": "two", "level": "bad", "kind": "job",
                                                                       "job": "j_1a2b"}]})
        got, _ = notices.listing(A)
        self.assertEqual([n["text"] for n in got["notices"]], ["two", "one"])
        self.assertEqual((got["notices"][0]["level"], got["notices"][0]["kind"], got["notices"][0]["job"]),
                         ("bad", "job", "j_1a2b"))
        self.assertEqual(notices.listing(B)[0]["notices"], [], "another account's are its own")
        old = notices.CAP
        self.addCleanup(setattr, notices, "CAP", old)
        notices.CAP = 3
        notices.act(A, {"action": "add", "items": [{"text": f"x{i}"} for i in range(5)]})
        self.assertEqual(len(notices.listing(A)[0]["notices"]), 3)

    def test_odd_values_are_tamed(self):
        notices.act(A, {"action": "add", "text": "t", "kind": "nonsense", "level": "loud", "job": "rm -rf"})
        n = notices.listing(A)[0]["notices"][0]
        self.assertEqual((n["kind"], n["level"], "job" in n), ("said", "info", False))
        self.assertEqual(notices.act(A, {"action": "add", "text": "  "})[1], 400)

    def test_delete_and_clear(self):
        notices.act(A, {"action": "add", "items": [{"text": "a"}, {"text": "b", "kind": "ask"}, {"text": "c"}]})
        rows = notices.listing(A)[0]["notices"]
        notices.act(A, {"action": "delete", "id": rows[0]["id"]})
        self.assertEqual([n["text"] for n in notices.listing(A)[0]["notices"]], ["b", "a"])
        notices.act(A, {"action": "clear", "kind": "ask"})
        self.assertEqual([n["text"] for n in notices.listing(A)[0]["notices"]], ["a"])
        notices.act(A, {"action": "clear"})
        self.assertEqual(notices.listing(A)[0]["notices"], [])

    def test_nothing_for_a_request_with_no_account(self):
        self.assertEqual(notices.listing("")[1], 400)
        self.assertEqual(notices.act("../x", {"action": "add", "text": "t"})[1], 400)


if __name__ == "__main__":
    unittest.main()
