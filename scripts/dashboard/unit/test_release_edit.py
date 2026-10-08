"""An edit of a published release (R139): what may be attached is checked
before anybody is asked (a build in dist/ or a committed file, inside the
project, of a kind a release carries), the edit goes to the project's owner
as its own ask with the notes whole, and on each forge the notes are
replaced, a file of the same name is replaced rather than doubled, and
(asset:NAME) in the notes becomes that file's address on the release."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cilogs  # noqa: E402
import forgerelease as fr  # noqa: E402
import forges  # noqa: E402
import phone  # noqa: E402

SEEN = []
GL = "/api/v4/projects/grp%2Fsub%2Fapp"
GH = "/repos/o/app/releases"
GT = "/api/v1/repos/o/app/releases"


class Forge(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def answer(self, code, body=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def authed(self):
        return self.headers.get("Authorization") in ("Bearer tok", "token tok") or self.headers.get("PRIVATE-TOKEN") == "tok"

    def do_GET(self):
        SEEN.append(("GET", self.path, None))
        old = {"id": 3, "name": "shot.png", "browser_download_url": "http://x/old/shot.png"}
        if self.path == f"{GH}/tags/v0.5.4":
            return self.answer(200, {"id": 7, "html_url": "https://github.com/o/app/releases/tag/v0.5.4", "assets": [old]})
        if self.path == f"{GT}/tags/v0.5.4":
            return self.answer(200, {"id": 9, "html_url": "http://gitea.lan/o/app/releases/tag/v0.5.4", "assets": [old]})
        if self.path == f"{GL}/releases/v0.5.4":
            return self.answer(200, {"tag_name": "v0.5.4", "_links": {"self": "https://gl.example/grp/sub/app/-/releases/v0.5.4"},
                                     "assets": {"links": [{"id": 3, "name": "shot.png", "url": "http://x/old"}]}})
        return self.answer(404, {"message": "Not Found"})

    def write(self, verb):
        raw = self.body()
        if not self.authed():
            return self.answer(401, {"message": "Bad credentials"})
        try:
            b = json.loads(raw)
        except ValueError:
            b = {"bytes": len(raw), "type": self.headers.get("Content-Type")}
        SEEN.append((verb, self.path, b))
        name = self.path.split("name=")[-1] if "name=" in self.path else ""
        return self.answer(201 if verb != "DELETE" else 204,
                           {"browser_download_url": f"http://dl/{name}"} if name else ({} if verb != "DELETE" else None))

    def do_POST(self):
        return self.write("POST")

    def do_PATCH(self):
        return self.write("PATCH")

    def do_PUT(self):
        return self.write("PUT")

    def do_DELETE(self):
        return self.write("DELETE")


def git(app, *a):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x"}
    return subprocess.run(["git", "-C", str(app), *a], check=True, capture_output=True, text=True, env=env).stdout


class Base(unittest.TestCase):
    def setUp(self):
        SEEN.clear()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        app = self.app = self.tmp / "ws" / "app"
        (app / "docs").mkdir(parents=True)
        (app / "dist").mkdir()
        (app / ".gitignore").write_text("dist/\nloose.png\n")
        (app / "docs" / "shot.png").write_bytes(b"\x89PNG shot")
        (app / "tool.sh").write_text("echo\n")
        git(app, "init", "-q"); git(app, "add", "-A"); git(app, "commit", "-qm", "0.5.4"); git(app, "tag", "v0.5.4")
        (app / "loose.png").write_bytes(b"png")
        (app / "dist" / "app-0.5.4-dev.1-abc1234-release-signed.apk").write_bytes(b"apk" * 400)
        (app / "dist" / "app-0.5.4-dev.1-abc1234-dirty.apk").write_bytes(b"apk")
        (self.tmp / "secret.txt").write_text("not the project's")
        (self.tmp / "gitcreds").mkdir()

        def wj(path, d):
            Path(path).write_text(json.dumps(d))
        fr.configure(state=self.tmp, workspace=self.tmp / "ws", write_json_fn=wj)


class Plan(Base):
    def test_a_build_and_a_committed_screenshot_are_attachable(self):
        p = fr.edit_plan("app", "v0.5.4", "notes", ["dist/app-0.5.4-dev.1-abc1234-release-signed.apk", "docs/shot.png"])
        self.assertNotIn("error", p, p)
        self.assertEqual([(x["name"], x["signed"]) for x in p["files"]],
                         [("app-0.5.4-dev.1-abc1234-release-signed.apk", True), ("shot.png", False)])
        self.assertEqual(p["files"][0]["size"], 1200)

    def test_what_is_refused_before_anybody_is_asked(self):
        for attach, why in ((["loose.png"], "not committed"), (["../secret.txt"], "not a file in app"),
                            (["dist/app-0.5.4-dev.1-abc1234-dirty.apk"], "uncommitted changes"),
                            (["tool.sh"], "not a kind of file"), (["docs/shot.png", "docs/shot.png"], "two files")):
            self.assertIn(why, fr.edit_plan("app", "v0.5.4", None, attach).get("error", ""), attach)
        self.assertIn("say what changes", fr.edit_plan("app", "v0.5.4", None, [])["error"])
        self.assertIn("empty", fr.edit_plan("app", "v0.5.4", "  \n", [])["error"])
        self.assertIn("not a tag here", fr.edit_plan("app", "v9.9.9", "x", [])["error"])


class Edit(Base):
    KIND, REPO = "github", "o/app"

    def setUp(self):
        super().setUp()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Forge)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.host = f"127.0.0.1:{self.srv.server_address[1]}"
        base = f"http://{self.host}"
        if self.KIND == "github":
            (self.tmp / "gitcreds" / "app").write_text("https://x:tok@github.com\n")
            cilogs.configure(state=self.tmp, workspace=self.tmp / "ws",
                             push_record_fn={"app": {"repo": "o/app", "host": "github.com"}}.get)
            for k in ("API", "UPLOADS"):
                self.addCleanup(setattr, fr, k, getattr(fr, k))
                setattr(fr, k, base)
        else:
            (self.tmp / "gitcreds" / "app").write_text(f"http://lab:tok@{self.host}\n")
            cilogs.configure(state=self.tmp, workspace=self.tmp / "ws",
                             push_record_fn={"app": {"repo": self.REPO, "host": self.host}}.get)
            self.addCleanup(setattr, forges, "known", forges.known)
            forges.known = lambda: {self.host: self.KIND}
        self.plan = fr.edit_plan("app", "v0.5.4", "# 0.5.4\n\n![Code mode](asset:shot.png)\n![gone](asset:nope.png)",
                                 ["docs/shot.png"])

    def check(self, notes_verb, notes_path, notes_key):
        r = fr.edit("app", self.plan)
        self.assertNotIn("error", r, r)
        self.assertEqual((r["attached"], r["replaced"]), (["shot.png"], ["shot.png"]))
        self.assertTrue([1 for m, p, b in SEEN if m == "DELETE"], "the old file of that name went first")
        notes = [b for m, p, b in SEEN if m == notes_verb and p == notes_path][0][notes_key]
        return r, notes

    def test_github(self):
        r, notes = self.check("PATCH", f"{GH}/7", "body")
        self.assertIn("![Code mode](http://dl/shot.png)", notes)
        self.assertIn("(asset:nope.png)", notes)
        self.assertTrue(any("asset:nope.png" in s for s in r["skipped"]), r)
        self.assertIn("edited on GitHub: the notes replaced; attached shot.png; replacing shot.png", fr.edit_said(r))


class Remove(Edit):
    """A file off the release: its own ask, the name checked against the
    forge's own list before anybody is asked, and the forge's delete made at
    the Allow, on each forge (the operator, 5 Oct)."""

    def removes(self, path):
        plan = fr.remove_plan("app", "v0.5.4", ["shot.png"])
        self.assertEqual(plan.get("files"), [{"name": "shot.png", "size": plan["files"][0]["size"]}], plan)
        self.assertIn("has no nope.apk; it has shot.png", fr.remove_plan("app", "v0.5.4", ["nope.apk"])["error"])
        self.assertIn("say which files", fr.remove_plan("app", "v0.5.4", [])["error"])
        self.assertFalse([1 for m, _, _ in SEEN if m == "DELETE"], "a plan deletes nothing")
        r = fr.remove("app", plan)
        self.assertEqual(r.get("removed"), ["shot.png"], r)
        self.assertEqual([p for m, p, _ in SEEN if m == "DELETE"], [path])
        self.assertIn("removed from the release on", fr.remove_said(r))

    def test_github(self):
        self.removes(f"{GH}/assets/3")


class RemoveGitea(Remove):
    KIND = "gitea"

    def test_github(self):
        self.removes(f"{GT}/9/assets/3")


class RemoveGitLab(Remove):
    KIND, REPO = "gitlab", "grp/sub/app"

    def test_github(self):
        self.removes(f"{GL}/releases/v0.5.4/assets/links/3")


class EditGitea(Edit):
    KIND = "gitea"

    def test_github(self):
        pass

    def test_gitea(self):
        r, notes = self.check("PATCH", f"{GT}/9", "body")
        self.assertIn("![Code mode](http://dl/shot.png)", notes)
        up = [b for m, p, b in SEEN if m == "POST" and "/assets?name=" in p][0]
        self.assertTrue(up["type"].startswith("multipart/form-data"), up)


class EditGitLab(Edit):
    KIND, REPO = "gitlab", "grp/sub/app"

    def test_github(self):
        pass

    def test_gitlab(self):
        r, notes = self.check("PUT", f"{GL}/releases/v0.5.4", "description")
        put = [p for m, p, b in SEEN if m == "PUT" and "/packages/generic/" in p]
        self.assertEqual(put, [f"{GL}/packages/generic/app/0.5.4/shot.png"])
        self.assertIn(f"![Code mode](http://{self.host}{put[0]})", notes)
        link = [b for m, p, b in SEEN if m == "POST" and p.endswith("/assets/links")][0]
        self.assertEqual(link["link_type"], "image")


class Ask(unittest.TestCase):
    def setUp(self):
        self.ran = []
        self.addCleanup(setattr, phone, "release_editor", phone.release_editor)
        phone.release_editor = lambda project, plan, asker, principal: (
            self.ran.append((project, plan["tag"], [x["name"] for x in plan["files"]], principal))
            or ({"edited": {}, "said": "edited on GitHub: the notes replaced; https://x"}, 200))
        self.plan = {"tag": "v0.5.4", "notes": "# 0.5.4\nThe first release",
                     "files": [{"path": "dist/a-signed.apk", "name": "a-signed.apk", "size": 22_681_006, "signed": True}]}

    def test_the_owner_reads_the_notes_whole_and_each_file(self):
        r = phone.ask_release_edit("screenshots for the page", "app", self.plan, "u_00000002", "ada",
                                   asker_name="sean", principal="session:app")
        self.assertTrue(r.get("ok"), r)
        mine = [x for x in phone.requests_open("u_00000002", False) if x["id"] == r["id"]][0]
        self.assertEqual(mine["kind"], "release-edit")
        self.assertEqual(mine["detail"], "# 0.5.4\nThe first release")
        self.assertEqual(mine["cmd"], ["version", "release", "--edit", "v0.5.4", "notes (25 characters)",
                                       "attach a-signed.apk (22.7 MB, signed)"])
        self.assertNotIn("principal", mine)
        self.assertFalse([x for x in phone.requests_open("u_00000009", True) if x["id"] == r["id"]],
                         "an administrator who does not own the project is not the one asked")

    def test_allow_makes_the_edit_and_says_it(self):
        r = phone.ask_release_edit("the APKs", "app", self.plan, "u_00000002", "ada", principal="session:app")
        self.assertTrue(phone.decide(r["id"], True, "u_00000002", name="ada", admin=False).get("ok"))
        self.assertEqual(self.ran, [("app", "v0.5.4", ["a-signed.apk"], "session:app")])
        self.assertIn("the notes replaced", phone.outcome(r["id"])["out"])

    def test_a_removal_is_its_own_ask_naming_each_file(self):
        ran = []
        self.addCleanup(setattr, phone, "release_remover", phone.release_remover)
        phone.release_remover = lambda project, plan, asker, principal: (
            ran.append([x["name"] for x in plan["files"]]) or ({"removed": {}, "said": "removed from the release"}, 200))
        r = phone.ask_release_remove("a broken build", "app", {"tag": "v0.5.4", "files": [
            {"name": "a-signed.apk", "size": 22_681_006}]}, "u_00000002", "ada", principal="session:app")
        mine = [x for x in phone.requests_open("u_00000002", False) if x["id"] == r["id"]][0]
        self.assertEqual((mine["kind"], mine["cmd"]), ("release-remove",
                         ["version", "release", "--remove", "v0.5.4", "a-signed.apk (22.7 MB)"]))
        self.assertTrue(phone.decide(r["id"], True, "u_00000002", name="ada", admin=False).get("ok"))
        self.assertEqual(ran, [["a-signed.apk"]])

    def test_deny_makes_nothing_and_a_reason_is_needed(self):
        r = phone.ask_release_edit("x", "app", self.plan, "u_00000002", "ada")
        phone.decide(r["id"], False, "u_00000002", name="ada", admin=False)
        self.assertEqual(self.ran, [])
        self.assertIn("--why", phone.ask_release_edit("", "app", self.plan, "u_1", "x")["error"])


if __name__ == "__main__":
    unittest.main()
