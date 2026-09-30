"""testreg.py's parsing, alignment, suspicion and run-in-progress record,
as functions. test/testreg.mjs proves the tab and the CLI around them."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import testreg  # noqa: E402


def row(suite, ord_, name):
    return {"suite": suite, "ord": ord_, "name": name, "status": "pass", "ms": 1}


class Parse(unittest.TestCase):
    def test_results_timing_and_totals(self):
        rows, files = testreg.parse(
            "[dashboard-test] == a.mjs ==\nPASS  [+1.5s] one\nFAIL  two\nSKIP  three\n"
            "1 passed, 1 failed in 3.0s\n")
        self.assertEqual([(r["ord"], r["status"], r["ms"]) for r in rows],
                         [(1, "pass", 1500), (2, "fail", None), (3, "skip", None)])
        self.assertEqual(files["a.mjs"], {"wall": 3.0, "passed": 1, "failed": 1})

    def test_a_rerun_banner_does_not_start_a_second_roster(self):
        rows, _ = testreg.parse("[dashboard-test] == a.mjs ==\nFAIL  one\n"
                                "[dashboard-test] == a.mjs again ==\nPASS  one\n")
        self.assertEqual(len([r for r in rows if r["suite"] == "a.mjs"]), 1)

    def test_lines_outside_a_suite_are_ignored(self):
        self.assertEqual(testreg.parse("PASS  orphan\nnoise\n")[0], [])


class Align(unittest.TestCase):
    """{new index: old index}, per file roster."""

    def test_an_insertion_keeps_the_others_paired(self):
        old = [row("a.mjs", 1, "one"), row("a.mjs", 2, "two")]
        new = [row("a.mjs", 1, "one"), row("a.mjs", 2, "inserted"), row("a.mjs", 3, "two")]
        self.assertEqual(testreg._align(old, new), {0: 0, 2: 1})

    def test_a_rename_in_place_is_paired_by_its_words(self):
        old = [row("a.mjs", 1, "one"), row("a.mjs", 2, "the lock asks first")]
        new = [row("a.mjs", 1, "one"), row("a.mjs", 2, "the lock asks first, naming them")]
        self.assertEqual(testreg._align(old, new), {0: 0, 1: 1})

    def test_a_minted_value_in_a_name_does_not_unpair_it(self):
        old = [row("a.mjs", 1, "made a node (n_5659a7c1)")]
        new = [row("a.mjs", 1, "made a node (n_0000ffff)")]
        self.assertEqual(testreg._align(old, new), {0: 0})

    def test_unlike_words_are_not_paired(self):
        old = [row("a.mjs", 1, "alpha beta gamma")]
        new = [row("a.mjs", 1, "zzz qqq")]
        self.assertEqual(testreg._align(old, new), {})


class Suspect(unittest.TestCase):
    def test_a_duration_just_over_a_round_wait_is_suspect(self):
        self.assertEqual(testreg.suspect(20_400), 20)
        self.assertEqual(testreg.suspect(5_100), 5)

    def test_short_or_off_boundary_durations_are_not(self):
        self.assertIsNone(testreg.suspect(2_000))
        self.assertIsNone(testreg.suspect(17_000))
        self.assertIsNone(testreg.suspect(0))


class Running(unittest.TestCase):
    def setUp(self):
        testreg.RUNNING.clear()

    def test_begin_end_by_id(self):
        rec = testreg.begin("p", "npm test", "me")
        now = testreg.running("p")
        assert now is not None
        self.assertEqual(now["cmd"], "npm test")
        self.assertNotIn("id", now)
        self.assertFalse(testreg.end("p", "someone-else"))
        self.assertTrue(testreg.end("p", rec["id"]))
        self.assertIsNone(testreg.running("p"))
        self.assertFalse(testreg.end("p", ""))

    def test_a_later_start_is_not_undone_by_an_earlier_end(self):
        first = testreg.begin("p")
        testreg.begin("p")
        self.assertFalse(testreg.end("p", first["id"]))
        self.assertIsNotNone(testreg.running("p"))

    def test_a_run_whose_end_never_came_is_forgotten(self):
        testreg.RUNNING["p"] = {"id": "x", "since": int(time.time()) - testreg.STALE_S - 1, "cmd": "", "by": ""}
        self.assertIsNone(testreg.running("p"))
        self.assertNotIn("p", testreg.RUNNING)


if __name__ == "__main__":
    unittest.main()
