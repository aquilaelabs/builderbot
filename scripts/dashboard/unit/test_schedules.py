"""Scheduled scripts (R117): the timetable in words and its next minute, a
schedule held to its shapes, and the timer: one run at a time, a run the
controller was down for run once and said, the bell's rows."""
import json
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import schedules  # noqa: E402


def _write(path, data):
    with open(path, "w") as f:
        json.dump(data, f)


class Timetable(unittest.TestCase):
    def test_a_timetable_is_said_in_words(self):
        said = {e: schedules.words(e) for e in ("0 4 * * 0", "0 4 * * 7", "*/15 * * * *", "30 * * * *", "0 4 * * *",
                                                 "0 9 * * 1-5", "0 4 1 * *", "5 4 * * sun,wed", "0 4 1 6 *", "nope")}
        self.assertEqual(said, {"0 4 * * 0": "Sundays at 4:00", "0 4 * * 7": "Sundays at 4:00",
                                "*/15 * * * *": "every 15 minutes", "30 * * * *": "hourly at :30",
                                "0 4 * * *": "daily at 4:00", "0 9 * * 1-5": "weekdays at 9:00",
                                "0 4 1 * *": "on the 1st at 4:00", "5 4 * * sun,wed": "Sundays, Wednesdays at 4:05",
                                "0 4 1 6 *": "cron 0 4 1 6 *", "nope": "not a timetable"})

    def test_its_next_minute_is_after_now_and_on_the_timetable(self):
        base = time.mktime((2026, 10, 25, 21, 7, 30, 0, 0, -1))        # a Sunday evening
        nxt = lambda e: time.localtime(schedules.next_after(e, base))  # noqa: E731
        self.assertEqual(time.strftime("%a %d %H:%M", nxt("0 4 * * 0")), "Sun 01 04:00")
        self.assertEqual(time.strftime("%a %d %H:%M", nxt("*/15 * * * *")), "Sun 25 21:15")
        self.assertEqual(time.strftime("%d %H:%M", nxt("0 4 1 * *")), "01 04:00")
        self.assertEqual(time.strftime("%a %H:%M", nxt("0 9 * * 1-5")), "Mon 09:00")
        # Both a day of the month and a day of the week named: either, as cron's.
        self.assertEqual(time.strftime("%a %d", nxt("0 4 13 * 5")), "Fri 30")
        self.assertIsNone(schedules.next_after("61 4 * * *", base))


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)
        schedules.configure(state=self.dir, write_json=_write)

    def test_the_scan_is_the_scanners_pages_now(self):
        # The row the built-in scan kept before 0.9.0 is not listed, and
        # not a schedule to save or remove (migration 0016 moved it).
        self.assertEqual(schedules.listing(), [])
        _write(schedules.FILE, {"schedules": {"scan": {"id": "scan", "on": True, "cron": "0 4 * * 0", "builtin": "scan"}}})
        self.assertEqual(schedules.listing(), [])
        self.assertIn("Scanners page", schedules.save({"id": "scan", "on": False}, "u")["error"])
        self.assertIn("Scanners page", schedules.remove("scan")["error"])

    def test_a_schedule_is_held_to_its_shapes(self):
        self.assertIn("five fields", schedules.save({"name": "x", "cron": "every day", "script": "true"}, "u")["error"])
        self.assertIn("needs its script", schedules.save({"name": "x", "cron": "0 4 * * *"}, "u")["error"])
        self.assertIn("pick the node", schedules.save({"name": "x", "cron": "0 4 * * *", "script": "true"}, "u")["error"])
        r = schedules.save({"name": "Backup", "cron": "0 4 * * *", "script": "true", "node": "n1"}, "user:sam")
        s = r["schedule"]
        self.assertEqual((s["name"], s["on"], s["as"], s["words"]), ("Backup", True, "job", "daily at 4:00"))
        self.assertIn("jobs account (job) or as root", schedules.save({"id": s["id"], "as": "admin"}, "u")["error"])
        self.assertTrue(schedules.remove(s["id"])["ok"])

    def test_a_system_schedule_is_one_of_the_tables_jobs_and_says_what_it_does(self):
        # The Storage page's snapshot schedules (R162 step 5): no script,
        # root on the node, the config held to the table's shape.
        self.assertIn("one of the table's jobs", schedules.save({"name": "x", "cron": "0 * * * *", "node": "n1", "system": {"apply": "reboot"}}, "u")["error"])
        self.assertIn("keep is missing", schedules.save({"name": "x", "cron": "0 * * * *", "node": "n1",
                                                         "system": {"apply": "storage-snapshot", "config": {"pool": "tank", "kind": "hourly", "keep": "7"}}}, "u")["error"])
        r = schedules.save({"name": "Snapshots of tank, hourly", "cron": "0 * * * *", "node": "n1",
                            "system": {"apply": "storage-snapshot", "config": {"pool": "tank", "kind": "hourly", "keep": 24, "extra": 1}}}, "user:sam")
        s = r["schedule"]
        self.assertEqual((s["as"], s["script"], s["system"]), ("root", "", {"apply": "storage-snapshot", "config": {"pool": "tank", "kind": "hourly", "keep": 24}}))
        self.assertEqual(s["does"], "a hourly snapshot of the pool tank, 24 kept")
        self.assertEqual([(x["pool"], x["kind"], x["keep"], x["on"]) for x in schedules.snapshot_schedules("n1")], [("tank", "hourly", 24, True)])
        self.assertEqual(schedules.snapshot_schedules("n2"), [])
        self.assertTrue(schedules.remove(s["id"])["ok"])


class Timer(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)
        schedules.configure(state=self.dir, write_json=_write)
        self.base = time.mktime((2026, 10, 25, 3, 59, 10, 0, 0, -1))
        self.sid = schedules.save({"name": "Nightly", "cron": "0 4 * * *", "script": "true", "node": "n1"},
                                  "u")["schedule"]["id"]
        # Due from a minute before it falls due, as saved then.
        schedules._record(self.sid, due=schedules.next_after("0 4 * * *", self.base))
        self.queued, self.states = [], {}

    def queue(self, s, argv, by):
        jid = f"j{len(self.queued) + 1}"
        self.queued.append((s["id"], by))
        return {"job": jid}

    def state(self, jid):
        return self.states.get(jid, "")

    def test_it_fires_on_its_minute_and_not_before(self):
        self.assertEqual(schedules.tick(self.queue, self.state, now=self.base + 20), [])
        self.assertEqual(schedules.tick(self.queue, self.state, now=self.base + 55), [self.sid])
        self.assertEqual(self.queued, [(self.sid, "schedule")])
        s = schedules.get(self.sid)
        self.assertEqual((s["last"]["job"], s["last"]["late"]), ("j1", ""))
        # ...and not again that minute, nor until the next day's.
        self.assertEqual(schedules.tick(self.queue, self.state, now=self.base + 80), [])

    def test_one_run_at_a_time(self):
        schedules.tick(self.queue, self.state, now=self.base + 55)
        self.states["j1"] = "running"
        tomorrow = self.base + 86400 + 55
        self.assertEqual(schedules.tick(self.queue, self.state, now=tomorrow), [])
        rows = schedules.attention(self.state)
        self.assertEqual([(r["kind"], r["bad"]) for r in rows], [("schedule", False)])
        self.assertIn("still going", rows[0]["why"])

    def test_a_run_the_controller_was_down_for_is_run_once_and_said(self):
        three_days = self.base + 3 * 86400 + 3600
        self.assertEqual(schedules.tick(self.queue, self.state, now=three_days), [self.sid])
        self.assertEqual(schedules.tick(self.queue, self.state, now=three_days + 30), [])
        self.assertEqual(len(self.queued), 1)
        self.assertTrue(schedules.get(self.sid)["last"]["late"])

    def test_a_failed_run_is_on_the_bell(self):
        schedules.tick(self.queue, self.state, now=self.base + 55)
        self.states["j1"] = "failed"
        rows = schedules.attention(self.state)
        self.assertEqual([(r["kind"], r["bad"], r["job"]) for r in rows], [("schedule", True, "j1")])

    def test_a_schedule_that_is_off_never_fires(self):
        schedules.save({"id": self.sid, "on": False}, "u")
        self.assertEqual(schedules.tick(self.queue, self.state, now=self.base + 55), [])


if __name__ == "__main__":
    unittest.main()
