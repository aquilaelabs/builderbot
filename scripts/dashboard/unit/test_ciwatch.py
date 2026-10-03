"""ciwatch.py (R117): one look at a project's CI. The tree's workflows give
a moving label and actions a major behind; a stand-in for GitHub's API
gives a red newest run on main and the notice GitHub wrote on it. What it
finds is kept, and a red main branch is what the bell is handed."""
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
import ciwatch  # noqa: E402

ASKED = []
FLOW = """name: Android CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: android-actions/setup-android@v3
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02   # v7, pinned by commit
      - uses: ./local-action
  smoke:
    runs-on: [self-hosted, ${{ inputs.node }}]
"""


class Forge(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def answer(self, body, code=200):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = self.path
        ASKED.append(p)
        if p.endswith("/releases/latest"):
            return self.answer({"tag_name": {"actions/checkout": "v7.0.1", "android-actions/setup-android": "v4.0.4",
                                             "actions/upload-artifact": "v7.0.1"}.get(p.split("/")[2] + "/" + p.split("/")[3], "")})
        if p.startswith("/repos/o/app/actions/runs?"):
            return self.answer({"workflow_runs": [
                {"id": 13, "name": "Android CI", "head_branch": "main", "status": "completed",
                 "conclusion": "cancelled", "created_at": "2026-10-03T02:00:00Z"},
                {"id": 10, "name": "lint", "head_branch": "main", "status": "completed",
                 "conclusion": "success", "created_at": "2026-10-02T23:00:00Z"},
                {"id": 12, "name": "Android CI", "head_branch": "claude/x", "status": "completed",
                 "conclusion": "success", "created_at": "2026-10-03T01:00:00Z"},
                {"id": 11, "name": "Android CI", "head_branch": "main", "status": "completed",
                 "conclusion": "failure", "created_at": "2026-10-03T00:44:51Z"}]})
        if p.startswith("/repos/o/app/actions/runs/11/jobs"):
            return self.answer({"jobs": [{"id": 111, "name": "build"}]})
        if p == "/repos/o/app/check-runs/111/annotations":
            return self.answer([
                {"annotation_level": "warning", "message": "Node.js 20 is deprecated. The following actions "
                                                           "target Node.js 20 but are being forced to run on Node.js 24"},
                {"annotation_level": "notice", "message": 'The ubuntu-latest label will migrate to Ubuntu 26 '
                                                          'beginning October 19, 2026.'},
                {"annotation_level": "failure", "message": "Process completed with exit code 1."}])
        return self.answer({"message": "Not Found"}, 404)


class Look(unittest.TestCase):
    def setUp(self):
        ASKED.clear()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Forge)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        wf = self.tmp / "ws" / "app" / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "android.yml").write_text(FLOW)
        head = self.tmp / "ws" / "app" / ".git" / "refs" / "remotes" / "origin"
        head.mkdir(parents=True)
        (head / "HEAD").write_text("ref: refs/remotes/origin/main\n")
        (self.tmp / "gitcreds").mkdir()
        (self.tmp / "gitcreds" / "app").write_text("https://x:tok@github.com\n")

        def wj(path, data):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps(data))
        cilogs.configure(state=self.tmp, workspace=self.tmp / "ws",
                         push_record_fn={"app": {"repo": "o/app", "host": "github.com"}}.get)
        ciwatch.configure(state=self.tmp, workspace=self.tmp / "ws", write_json_fn=wj, projects=lambda: ["app"])
        api = cilogs.API
        cilogs.API = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.addCleanup(setattr, cilogs, "API", api)

    def test_one_look_finds_what_drifted_and_keeps_it(self):
        rec = ciwatch.look("app")
        kinds = sorted(f["kind"] for f in rec["findings"])
        self.assertEqual(kinds, ["action", "action", "label", "notice", "notice", "run"])
        acts = " ".join(f["text"] for f in rec["findings"] if f["kind"] == "action")
        self.assertIn("actions/checkout@v4: v7 is out", acts)
        self.assertIn("android-actions/setup-android@v3: v4 is out", acts)
        self.assertNotIn("upload-artifact", acts)            # its commit pin says v7: current
        # main's newest verdict: not the newer branch run, not the run a
        # successor cancelled, and the passing lint workflow is no finding.
        self.assertEqual(rec["run"]["id"], 11)
        self.assertEqual([f["where"] for f in rec["findings"] if f["kind"] == "run"], ["run 11"])
        self.assertTrue(any("Ubuntu 26" in f["text"] for f in rec["findings"]))
        self.assertEqual(ciwatch.read("app")["run"]["id"], 11)
        self.assertEqual([r["project"] for r in ciwatch.red(["app"])], ["app"])
        self.assertFalse(ciwatch.due("app"))

    def test_a_release_is_asked_once_a_day_across_looks(self):
        ciwatch.look("app")
        n = sum(1 for p in ASKED if p.endswith("/releases/latest"))
        ciwatch.look("app")
        self.assertEqual(sum(1 for p in ASKED if p.endswith("/releases/latest")), n)

    def test_a_project_off_github_still_gets_the_tree_half(self):
        cilogs.configure(state=self.tmp, workspace=self.tmp / "ws", push_record_fn=lambda p: None)
        rec = ciwatch.look("app")
        self.assertEqual(rec["repo"], "")
        self.assertIn("label", [f["kind"] for f in rec["findings"]])
        self.assertNotIn("run", [f["kind"] for f in rec["findings"]])

    def test_a_project_with_no_workflows_is_never_due(self):
        (self.tmp / "ws" / "bare").mkdir()
        self.assertFalse(ciwatch.due("bare"))
        self.assertTrue(ciwatch.due("app"))


if __name__ == "__main__":
    unittest.main()
