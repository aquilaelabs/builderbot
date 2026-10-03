"""cilogs.py (R115): a project's runs on GitHub's own runners and a failed
job's log, read with the controller's token against a stand-in for GitHub's
API on a local port. The log answers with a redirect to another host, as
GitHub's does, and the token must not follow it there."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cilogs  # noqa: E402

SEEN = []


class Forge(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def answer(self, code, body, ctype="application/json", extra=None):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        SEEN.append((self.path, self.headers.get("Authorization")))
        p = self.path
        if p.startswith("/blob/"):
            return self.answer(200, "2026-10-02T10:00:00.0000000Z ##[group]Run ./gradlew\n"
                               + "".join(f"2026-10-02T10:00:01.0000000Z line {i}\n" for i in range(500))
                               + "2026-10-02T10:00:02.0000000Z ##[error]Process completed with exit code 1.\n",
                               "text/plain")
        if self.headers.get("Authorization") != "Bearer tok-123":
            return self.answer(401, {"message": "Requires authentication"})
        if p.startswith("/repos/o/app/actions/runs?"):
            return self.answer(200, {"workflow_runs": [
                {"id": 9, "name": "Android CI", "head_branch": "main", "event": "push", "status": "in_progress",
                 "conclusion": None, "created_at": "2026-10-02T11:00:00Z", "head_sha": "abc"},
                {"id": 8, "name": "Android CI", "head_branch": "main", "event": "push", "status": "completed",
                 "conclusion": "failure", "created_at": "2026-10-02T10:00:00Z", "head_sha": "def"}]})
        if p == "/repos/o/app/actions/runs/8":
            return self.answer(200, {"name": "Android CI", "head_branch": "main", "conclusion": "failure",
                                     "created_at": "2026-10-02T10:00:00Z", "html_url": "https://github.com/o/app/actions/runs/8"})
        if p.startswith("/repos/o/app/actions/runs/8/jobs"):
            return self.answer(200, {"jobs": [
                {"id": 81, "name": "build", "conclusion": "failure",
                 "steps": [{"name": "Set up", "conclusion": "success"}, {"name": "Build, test, lint", "conclusion": "failure"}]},
                {"id": 82, "name": "lint", "conclusion": "success", "steps": []}]})
        if p == "/repos/o/app/actions/jobs/81/logs":
            host, port = self.server.server_address[:2]
            return self.answer(302, "", extra={"Location": f"http://localhost:{port}/blob/81"})
        if p == "/repos/o/app/actions/runs/7":
            return self.answer(410, {"message": "gone"})
        return self.answer(404, {"message": "Not Found"})


class CiLogs(unittest.TestCase):
    def setUp(self):
        SEEN.clear()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Forge)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "gitcreds").mkdir()
        (self.tmp / "gitcreds" / "app").write_text("https://x-access-token:tok-123@github.com\n")
        self.rights = {"app": {"repo": "o/app", "host": "github.com"}, "gl": {"repo": "o/gl", "host": "gitlab.com"}}
        cilogs.configure(state=self.tmp, workspace=self.tmp / "ws", push_record_fn=self.rights.get)
        api = cilogs.API
        cilogs.API = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.addCleanup(setattr, cilogs, "API", api)

    def test_runs_are_listed_with_the_projects_token(self):
        r = cilogs.runs("app")
        self.assertEqual(r["repo"], "o/app")
        self.assertEqual([x["id"] for x in r["runs"]], [9, 8])
        self.assertEqual(r["runs"][1]["conclusion"], "failure")

    def test_the_newest_finished_runs_failed_job_and_its_end(self):
        r = cilogs.log("app")
        self.assertEqual(r["run"]["id"], 8)
        build, lint = r["jobs"]
        self.assertEqual(build["failed_step"], "Build, test, lint")
        self.assertEqual(build["lines"], 502)
        tail = build["log"].splitlines()
        self.assertEqual(len(tail), cilogs.TAIL_LINES)
        self.assertEqual(tail[-1], "##[error]Process completed with exit code 1.")
        self.assertNotIn("log", lint)                    # it passed: not fetched
        # The token went to the API and never to the host the log is kept on.
        blob = [a for p, a in SEEN if p.startswith("/blob/")]
        self.assertEqual(blob, [None])

    def test_what_it_refuses_in_words(self):
        with self.assertRaises(cilogs.Refused) as e:
            cilogs.runs("gl")
        self.assertIn("not on github.com", str(e.exception))
        with self.assertRaises(cilogs.Refused) as e:
            cilogs.log("app", 7)
        self.assertIn("no longer keeps", str(e.exception))
        (self.tmp / "gitcreds" / "app").write_text("https://x-access-token:wrong@github.com\n")
        with self.assertRaises(cilogs.Refused) as e:
            cilogs.runs("app")
        self.assertIn("Actions", str(e.exception))
        with self.assertRaises(cilogs.Refused):
            cilogs._get("/user/emails", "tok-123")


if __name__ == "__main__":
    unittest.main()
