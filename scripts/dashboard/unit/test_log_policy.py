"""One log policy, applied on a clock and bounded everywhere (the operator,
12 Oct): a running job's log is capped with its start and its end kept, the
job logs follow the Logs section's days, Clear reaches the job logs and the
CI runs, old job rows and audit rows go, and a live file past its ceiling
is copied to its next generation and emptied in place."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db  # noqa: E402
import logs  # noqa: E402
import nodes  # noqa: E402


class JobLogs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        nodes.configure(state=self.tmp)
        self.n = nodes.LOCAL
        saved = nodes.log_days
        self.addCleanup(setattr, nodes, "log_days", saved)

    def job(self, jid, state="running", project="p", ago=0):
        nodes._exec("INSERT INTO jobs (id, type, project, requested_by, placement, source, spec, outputs, "
                    "state, node, queued, ended) VALUES (?, 'exec', ?, 'test', '{}', '{}', '{}', '[]', ?, ?, ?, ?)",
                    (jid, project, state, self.n, int(time.time()) - ago,
                     None if state == "running" else int(time.time()) - ago))

    def test_a_probe_ending_sweeps_nothing(self):
        """A quiet probe's end leaves the sweep alone (the operator, 17 Oct:
        each Docker read's result swept every project's history); a job
        somebody queued still sweeps its project's."""
        swept = []
        real = nodes.prune_job_logs
        self.addCleanup(setattr, nodes, "prune_job_logs", real)
        nodes.prune_job_logs = lambda project=None: swept.append(project) or 0
        self.job("jq", project="")
        nodes._probe_ids.add("jq")
        self.addCleanup(nodes._probe_ids.discard, "jq")
        self.assertEqual(nodes.job_result(self.n, "jq", "succeeded", 0), {"ok": True})
        self.assertEqual(swept, [], "the probe swept nothing")
        self.job("jr")
        nodes.job_result(self.n, "jr", "succeeded", 0)
        self.assertEqual(swept, ["p"], "a queued job sweeps its own project")

    def test_a_running_jobs_log_keeps_its_start_and_its_end(self):
        self.job("j1")
        total = nodes.JOB_LOG_MAX_CHUNKS + 40
        for i in range(1, total + 1, 50):
            nodes.job_log(self.n, "j1", [{"seq": s, "chunk": f"line {s}\n"} for s in range(i, min(i + 50, total + 1))])
        rows = nodes._rows("SELECT seq, chunk FROM job_logs WHERE job_id = 'j1' ORDER BY seq")
        self.assertLessEqual(len(rows), nodes.JOB_LOG_MAX_CHUNKS)
        text = "".join(r["chunk"] for r in rows)
        self.assertIn("line 1\n", text, "the start is kept")
        self.assertIn(f"line {total}\n", text, "the end is kept")
        self.assertIn("left out here", text, "the gap says so, where it is")

    def test_the_days_and_clear_reach_the_job_logs(self):
        self.job("old", state="succeeded", ago=3 * 86400)
        self.job("new", state="succeeded")
        self.job("run")
        for j in ("old", "new", "run"):
            nodes._exec("INSERT INTO job_logs (job_id, seq, at, chunk) VALUES (?, 1, 0, 'x')", (j,))
        nodes.log_days = lambda: 2
        self.assertEqual(nodes.prune_job_logs(), 1)
        self.assertEqual(nodes.clear_job_logs(), 1, "Clear takes the finished one left")
        left = {r["job_id"] for r in nodes._rows("SELECT job_id FROM job_logs")}
        self.assertEqual(left, {"run"}, "a running job's log is never cleared")
        self.assertEqual(len(nodes._rows("SELECT id FROM jobs")), 3, "the rows stay")

    def test_old_job_rows_and_audit_rows_go(self):
        saved = (nodes.JOB_ROWS_KEEP, nodes.JOB_ROWS_DAYS)
        self.addCleanup(lambda: setattr(nodes, "JOB_ROWS_KEEP", saved[0]) or setattr(nodes, "JOB_ROWS_DAYS", saved[1]))
        nodes.JOB_ROWS_KEEP, nodes.JOB_ROWS_DAYS = 1, 1
        for i in range(3):
            self.job(f"o{i}", state="failed", ago=(2 + i) * 86400)
        self.assertEqual(nodes.prune_jobs(), 2, "past the age, beyond the newest one kept")
        db._exec("INSERT INTO audit (id, at, principal, action, target, params) VALUES ('a1', 1, 'x', 'y', 'z', '')")
        db._exec("INSERT INTO audit (id, at, principal, action, target, params) VALUES ('a2', ?, 'x', 'y', 'z', '')",
                 (int(time.time()),))
        self.assertGreaterEqual(db.prune_audit(), 1)
        self.assertEqual({r["id"] for r in db._rows("SELECT id FROM audit WHERE id IN ('a1', 'a2')")}, {"a2"})


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "logs").mkdir()
        (self.tmp / "ci" / "repo").mkdir(parents=True)
        os.environ["BB_LOG_DIR"] = str(self.tmp / "logs")
        os.environ["BB_CI_LOG_DIR"] = str(self.tmp / "ci")
        self.addCleanup(os.environ.pop, "BB_LOG_DIR", None)
        self.addCleanup(os.environ.pop, "BB_CI_LOG_DIR", None)
        saved = (logs.LIVE_MAX_BYTES, logs.clear_job_logs)
        self.addCleanup(lambda: setattr(logs, "LIVE_MAX_BYTES", saved[0]) or setattr(logs, "clear_job_logs", saved[1]))

    def test_a_live_file_past_its_ceiling_is_cut_into_a_generation(self):
        logs.LIVE_MAX_BYTES = 10
        live = self.tmp / "logs" / "dashboard.log"
        live.write_text("x" * 50)
        (self.tmp / "logs" / "dashboard.log.1").write_text("older")
        with open(live, "ab") as writer:            # a writer that holds it open, as tee does
            self.assertEqual(logs.cap_live(), 1)
            writer.write(b"after\n")
        self.assertEqual((self.tmp / "logs" / "dashboard.log.1").read_text(), "x" * 50)
        self.assertEqual((self.tmp / "logs" / "dashboard.log.2").read_text(), "older")
        self.assertEqual(live.read_bytes().lstrip(b"\0"), b"after\n")

    def test_clear_takes_the_ci_runs_and_the_job_logs(self):
        (self.tmp / "ci" / "repo" / "1-1.log").write_text("run")
        (self.tmp / "logs" / "builderbot.log").write_text("live")
        (self.tmp / "logs" / "builderbot.log.1").write_text("older")
        logs.clear_job_logs = lambda: 4
        r = logs.clear()
        self.assertEqual((r["removed"], r["job_logs"]), (2, 4))
        self.assertTrue((self.tmp / "logs" / "builderbot.log").exists(), "the live one stays")


if __name__ == "__main__":
    unittest.main()
