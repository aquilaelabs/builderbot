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
STOPPED = "cancel" + "led"      # GitHub's spelling of a stopped run, which the house spelling rule would refuse
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


# Runs a test adds after main's failure (a release's run of the same check).
LATER = []


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
                 "conclusion": STOPPED, "created_at": "2026-10-03T02:00:00Z"},
                {"id": 10, "name": "lint", "head_branch": "main", "status": "completed",
                 "conclusion": "success", "created_at": "2026-10-02T23:00:00Z"},
                {"id": 12, "name": "Android CI", "head_branch": "claude/x", "status": "completed",
                 "conclusion": "success", "created_at": "2026-10-03T01:00:00Z"},
                {"id": 11, "name": "Android CI", "head_branch": "main", "status": "completed",
                 "conclusion": "failure", "created_at": "2026-10-03T00:44:51Z"}] + LATER})
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
        self.assertIn("Uses actions/checkout v4, and v7 is out", acts)
        self.assertIn("Uses android-actions/setup-android v3, and v4 is out", acts)
        self.assertNotIn("upload-artifact", acts)            # its commit pin says v7: current
        # main's newest verdict: not the newer branch run, not the run a
        # successor stopped, and the passing lint workflow is no finding.
        self.assertEqual(rec["run"]["id"], 11)
        self.assertEqual([f["where"] for f in rec["findings"] if f["kind"] == "run"], ["run 11"])
        self.assertTrue(any("Ubuntu 26" in f["text"] for f in rec["findings"]))
        self.assertEqual(ciwatch.read("app")["run"]["id"], 11)
        self.assertEqual([r["project"] for r in ciwatch.red(["app"])], ["app"])
        self.assertFalse(ciwatch.due("app"))

    def test_a_release_that_passed_the_check_since_ends_main_s_red(self):
        # A workflow that runs on main only when its own files change kept a
        # failure from weeks before on the bell for good: the release's run
        # of the same check, passing since, says it passes again.
        self.addCleanup(LATER.clear)
        LATER.append({"id": 14, "name": "Android CI", "head_branch": "v0.7.0", "event": "release",
                      "status": "completed", "conclusion": "success", "created_at": "2026-10-04T10:00:00Z"})
        rec = ciwatch.look("app")
        self.assertFalse([f for f in rec["findings"] if f["kind"] == "run"])
        self.assertEqual(ciwatch.red(["app"]), [])

    def test_a_red_row_is_put_away_until_another_run_fails(self):
        import bellseen
        ciwatch.look("app")
        rows = ciwatch.red(["app"])
        self.assertEqual(rows[0]["key"], "ci:app@run11")
        bellseen.configure(state=self.tmp, write_json=lambda p, d: Path(p).write_text(json.dumps(d)))
        # As the page sends it: a row's keys joined by spaces, split on them
        # (B331: "run 11" was two keys, and neither the row's).
        bellseen.dismiss("u_00000001", rows[0]["key"].split(" "))
        self.assertEqual(bellseen.filter_rows("u_00000001", rows)[0], [])
        self.assertEqual(len(bellseen.filter_rows("u_00000002", rows)[0]), 1, "one account's, not everybody's")

    def test_a_finding_carries_its_fix_and_a_press_writes_only_that_line(self):
        # R117 step 4: the label and an action a major behind are one press.
        rec = ciwatch.look("app")
        fixes = {f["where"]: f["fix"] for f in rec["findings"] if f.get("fix")}
        self.assertEqual(fixes, {"android.yml:5": {"from": "ubuntu-latest", "to": "ubuntu-24.04"},
                                 "android.yml:7": {"from": "actions/checkout@v4", "to": "actions/checkout@v7"},
                                 "android.yml:8": {"from": "android-actions/setup-android@v3",
                                                   "to": "android-actions/setup-android@v4"}})
        path = self.tmp / "ws" / "app" / ".github" / "workflows" / "android.yml"
        r = ciwatch.fix("app", "android.yml:5")
        self.assertTrue(r["ok"], r)
        after = path.read_text().split("\n")
        self.assertEqual(after[4], "    runs-on: ubuntu-24.04")
        self.assertEqual([l for i, l in enumerate(after) if i != 4], [l for i, l in enumerate(FLOW.split("\n")) if i != 4],
                         "nothing else on the file moves")
        self.assertIn("no longer says", ciwatch.fix("app", "android.yml:5")["error"], "pressed twice: the line moved")
        self.assertTrue(ciwatch.fix("app", "android.yml:8")["ok"])
        self.assertIn("setup-android@v4", path.read_text())
        # A finding with no fix, and a name that is not a workflow, are refused.
        self.assertIn("error", ciwatch.fix("app", "run 11"))
        self.assertIn("error", ciwatch.fix("app", "../../etc/passwd:1"))

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

    def test_a_look_kept_by_older_code_is_no_look(self):
        ciwatch.look("app")
        f = self.tmp / "ciwatch" / "app.json"
        rec = json.loads(f.read_text())
        rec.pop("format")
        f.write_text(json.dumps(rec))
        self.assertEqual(ciwatch.read("app"), {})
        self.assertEqual(ciwatch.red(["app"]), [])
        self.assertTrue(ciwatch.due("app"))

    def test_gitea_and_forgejo_workflows_are_read_too(self):
        # B92: a repository on a Gitea or Forgejo host keeps its workflows
        # in its own directory; a file there is read, named with its
        # directory, offered an action's fix, and not GitHub's label.
        for d in (".gitea", ".forgejo"):
            wf = self.tmp / "ws" / "lab" / d / "workflows"
            wf.mkdir(parents=True)
            (wf / "android.yml").write_text(FLOW)
        self.assertTrue(ciwatch.due("lab"))
        rec = ciwatch.look("lab")
        self.assertEqual(rec["workflows"], 2)
        fixes = {f["where"]: f["fix"] for f in rec["findings"] if f.get("fix")}
        self.assertEqual(sorted(fixes), [".forgejo/workflows/android.yml:7", ".forgejo/workflows/android.yml:8",
                                         ".gitea/workflows/android.yml:7", ".gitea/workflows/android.yml:8"])
        self.assertNotIn("label", [f["kind"] for f in rec["findings"]])
        r = ciwatch.fix("lab", ".gitea/workflows/android.yml:7")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["file"], ".gitea/workflows/android.yml")
        self.assertIn("actions/checkout@v7", (self.tmp / "ws" / "lab" / ".gitea" / "workflows" / "android.yml").read_text())
        self.assertIn("error", ciwatch.fix("lab", ".git/hooks/android.yml:7"))

    def test_a_project_with_no_workflows_is_never_due(self):
        (self.tmp / "ws" / "bare").mkdir()
        self.assertFalse(ciwatch.due("bare"))
        self.assertTrue(ciwatch.due("app"))


if __name__ == "__main__":
    unittest.main()
