"""forgerelease.py on Gitea and GitLab (R124), against stand-ins for their
APIs on a local port: the release made with the changelog's notes, the
signed build attached the way each forge takes one (a multipart upload on
Gitea; on GitLab a generic package the release links to), the project's own
token sent the way each wants it, and only to the root its link stored."""
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
import forgerelease as fr  # noqa: E402
import forges  # noqa: E402

SEEN = []
MADE = {}
GL = "/api/v4/projects/grp%2Fsub%2Fapp"


class Forge(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def answer(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authed(self):
        return (self.headers.get("Authorization") == "token tok"
                or self.headers.get("PRIVATE-TOKEN") == "tok")

    def do_GET(self):
        SEEN.append(("GET", self.path, None))
        for pre in ("/api/v1/repos/o/app/releases/tags/", GL + "/releases/"):
            if self.path.startswith(pre):
                tag = self.path.rsplit("/", 1)[-1]
                return self.answer(200, MADE[tag]) if tag in MADE else self.answer(404, {"message": "Not Found"})
        return self.answer(404, {"message": "Not Found"})

    def body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_PUT(self):
        raw = self.body()
        if not self.authed():
            return self.answer(401, {"message": "401 Unauthorized"})
        SEEN.append(("PUT", self.path, len(raw)))
        return self.answer(201, {"message": "201 Created"})

    def do_POST(self):
        raw = self.body()
        if not self.authed():
            return self.answer(401, {"message": "token is required"})
        if self.path in ("/api/v1/repos/o/app/releases", GL + "/releases"):
            b = json.loads(raw)
            SEEN.append(("POST", self.path, b))
            MADE[b["tag_name"]] = ({"id": 9, "html_url": f"http://gitea.lan/o/app/releases/tag/{b['tag_name']}"}
                                   if "/v1/" in self.path else
                                   {"tag_name": b["tag_name"],
                                    "_links": {"self": f"https://gl.example/grp/sub/app/-/releases/{b['tag_name']}"}})
            return self.answer(201, MADE[b["tag_name"]])
        if self.path.startswith("/api/v1/repos/o/app/releases/9/assets?name="):
            SEEN.append(("UPLOAD", self.path, (self.headers.get("Content-Type"), raw)))
            return self.answer(201, {"id": 1})
        if self.path == GL + "/releases/v0.5.0/assets/links":
            SEEN.append(("LINK", self.path, json.loads(raw)))
            return self.answer(201, {"id": 1})
        return self.answer(404, {"message": "Not Found"})


class Base(unittest.TestCase):
    KIND = "gitea"
    REPO = "o/app"

    def setUp(self):
        SEEN.clear(); MADE.clear()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Forge)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.host = f"127.0.0.1:{self.srv.server_address[1]}"
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "gitcreds").mkdir()
        # As the link writes it: the account, the token, and the host with
        # its port, on the plain http a LAN forge answers.
        (self.tmp / "gitcreds" / "app").write_text(f"http://lab:tok@{self.host.replace(':', '%3a')}\n")
        app = self.tmp / "ws" / "app"
        (app / "dist").mkdir(parents=True)
        (app / "CHANGELOG.md").write_text("# Changelog\n\n## 0.5.0: 2026-10-04\n\n### Added\n\n- Voice typing\n\n"
                                          "## 0.4.0: 2026-09-01\n\n### Added\n\n- older\n")
        for n in ("app-0.5.0-dev.12-65298e0-release.apk", "app-0.5.0-dev.12-65298e0-release-signed.apk"):
            (app / "dist" / n).write_bytes(b"apk-bytes")
        cilogs.configure(state=self.tmp, workspace=self.tmp / "ws",
                         push_record_fn={"app": {"repo": self.REPO, "host": self.host}}.get)
        self.addCleanup(setattr, forges, "known", forges.known)
        forges.known = lambda: {self.host: self.KIND}

        def wj(path, d):
            Path(path).write_text(json.dumps(d))
        fr.configure(state=self.tmp, workspace=self.tmp / "ws", write_json_fn=wj)


class Gitea(Base):
    def test_the_release_carries_the_notes_and_the_signed_build_as_an_upload(self):
        r = fr.publish("app", "v0.5.0", "0.5.0", "65298e0")
        self.assertTrue(r.get("made"), r)
        self.assertEqual(r["forge"], "Gitea")
        made = [b for m, p, b in SEEN if m == "POST"][0]
        self.assertEqual((made["tag_name"], made["name"]), ("v0.5.0", "0.5.0"))
        self.assertIn("- Voice typing", made["body"])
        self.assertNotIn("older", made["body"])
        ups = [b for m, p, b in SEEN if m == "UPLOAD"]
        self.assertEqual(len(ups), 1)
        ctype, raw = ups[0]
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="), ctype)
        self.assertIn(b'name="attachment"; filename="app-0.5.0-dev.12-65298e0-release-signed.apk"', raw)
        self.assertIn(b"apk-bytes", raw)
        self.assertEqual(r["assets"], ["app-0.5.0-dev.12-65298e0-release-signed.apk"])
        kept = fr.kept("app")["v0.5.0"]
        self.assertEqual((kept["url"], kept["forge"]), ("http://gitea.lan/o/app/releases/tag/v0.5.0", "Gitea"))

    def test_a_second_press_makes_nothing_twice(self):
        fr.publish("app", "v0.5.0", "0.5.0", "65298e0")
        n = len([1 for m, _, _ in SEEN if m == "POST"])
        r = fr.publish("app", "v0.5.0", "0.5.0", "65298e0")
        self.assertFalse(r["made"])
        self.assertEqual(len([1 for m, _, _ in SEEN if m == "POST"]), n)

    def test_a_refused_token_names_the_forge_and_the_scope(self):
        (self.tmp / "gitcreds" / "app").write_text(f"http://lab:wrong@{self.host}\n")
        r = fr.publish("app", "v0.5.0", "0.5.0", "65298e0")
        self.assertIn("Gitea refused the token for releases", r["error"])
        self.assertIn("Gitea refused", fr.kept("app")["v0.5.0"]["error"])

    def test_a_token_stored_for_another_host_is_not_sent(self):
        (self.tmp / "gitcreds" / "app").write_text("https://lab:tok@elsewhere.example\n")
        r = fr.publish("app", "v0.5.0", "0.5.0", "65298e0")
        self.assertIn("no Gitea token", r["error"])
        self.assertEqual(SEEN, [], "nothing was asked of the forge")


class GitLab(Base):
    KIND = "gitlab"
    REPO = "grp/sub/app"

    def test_the_release_links_the_build_from_the_package_registry(self):
        r = fr.publish("app", "v0.5.0", "0.5.0", "65298e0")
        self.assertTrue(r.get("made"), r)
        self.assertEqual((r["forge"], r["url"]), ("GitLab", "https://gl.example/grp/sub/app/-/releases/v0.5.0"))
        made = [b for m, p, b in SEEN if m == "POST"][0]
        self.assertIn("- Voice typing", made["description"])
        put = [p for m, p, b in SEEN if m == "PUT"]
        self.assertEqual(put, [GL + "/packages/generic/app/0.5.0/app-0.5.0-dev.12-65298e0-release-signed.apk"])
        link = [b for m, p, b in SEEN if m == "LINK"][0]
        self.assertEqual(link["url"], f"http://{self.host}{put[0]}")
        self.assertEqual(link["link_type"], "package")


class Elsewhere(Base):
    KIND = "bitbucket"

    def test_a_forge_with_no_release_api_leaves_the_tag_as_the_release(self):
        r = fr.publish("app", "v0.5.0", "0.5.0", "65298e0")
        self.assertIn("is on Bitbucket, which has no release this can make", r["error"])
        self.assertEqual(SEEN, [])


if __name__ == "__main__":
    unittest.main()
